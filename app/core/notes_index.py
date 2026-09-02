"""The notes index.

The `.md` file on disk is the truth. Everything here is a rebuildable index —
delete it, rescan, and you are back where you were. Nothing in this module ever
stores note content in SQLite except the FTS5 search index, which is
contentless and derived (CLAUDE.md rule 6).

Two-stage change detection: mtime and size first, SHA-256 only when they
differ. A vault of a few thousand notes rescans in well under a second when
nothing has changed, which is what makes scan-on-page-load viable.
"""
import os
from datetime import datetime
from pathlib import Path

from app.core import markdown as md
from app.core import paths
from app.core.database import get_db

SKIP_DIRS = {".obsidian", ".git", ".trash", "attachments", "__pycache__", "node_modules"}
NOTE_SUFFIX = ".md"

DEFAULT_ROOTS = (
    ("projects", "Project Notes", lambda: paths.VAULT_ROOT, 0, 10),
    ("docs", "Specifications", lambda: paths.DOCS_ROOT, 0, 20),
    ("templates", "Template Library", lambda: paths.TEMPLATE_LIBRARY_ROOT, 1, 30),
)


def ensure_roots():
    """Seed or repair vault roots.

    Done at runtime rather than in a migration because the absolute path
    depends on where the application is installed — it differs between the WSL
    checkout and the Windows copy, and a migration cannot know which it is on.
    """
    db = get_db()
    for key, label, resolve, readonly, order in DEFAULT_ROOTS:
        abs_path = str(resolve())
        row = db.execute("SELECT id, abs_path FROM vault_roots WHERE root_key = ?",
                         (key,)).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO vault_roots (root_key, label, abs_path, is_readonly, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, label, abs_path, readonly, order),
            )
        elif row["abs_path"] != abs_path:
            # The tree moved — most likely the WSL to Windows sync.
            db.execute("UPDATE vault_roots SET abs_path = ? WHERE id = ?",
                       (abs_path, row["id"]))
    db.commit()


def roots(enabled_only=True):
    sql = "SELECT * FROM vault_roots"
    if enabled_only:
        sql += " WHERE is_enabled = 1"
    return get_db().execute(sql + " ORDER BY sort_order").fetchall()


def get_root(root_id):
    return get_db().execute("SELECT * FROM vault_roots WHERE id = ?", (root_id,)).fetchone()


def root_by_key(key):
    return get_db().execute("SELECT * FROM vault_roots WHERE root_key = ?", (key,)).fetchone()


def _walk(root_path):
    root_path = Path(root_path)
    if not root_path.exists():
        return
    for current, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for filename in filenames:
            if not filename.endswith(NOTE_SUFFIX) or filename.startswith("."):
                continue
            yield Path(current) / filename


# --- scanning ---------------------------------------------------------------


def scan_root(root, force=False):
    """Index one root. Returns counts of what happened."""
    db = get_db()
    root_path = Path(root["abs_path"])
    counts = {"seen": 0, "added": 0, "updated": 0, "unchanged": 0, "missing": 0}

    indexed = {
        row["rel_path"]: row
        for row in db.execute(
            "SELECT id, rel_path, content_hash, mtime, size_bytes FROM notes WHERE root_id = ?",
            (root["id"],),
        ).fetchall()
    }
    on_disk = set()

    for path in _walk(root_path):
        rel = path.relative_to(root_path).as_posix()
        on_disk.add(rel)
        counts["seen"] += 1

        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds")
        existing = indexed.get(rel)

        if (not force and existing
                and existing["mtime"] == mtime and existing["size_bytes"] == stat.st_size):
            counts["unchanged"] += 1
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # A file being written by an editor can be briefly unreadable.
            # Leave the existing row alone and pick it up next scan.
            continue

        digest = md.content_hash(text)
        if not force and existing and existing["content_hash"] == digest:
            db.execute("UPDATE notes SET mtime = ?, size_bytes = ? WHERE id = ?",
                       (mtime, stat.st_size, existing["id"]))
            counts["unchanged"] += 1
            continue

        note_id = _upsert(db, root, rel, text, digest, mtime, stat.st_size,
                          existing["id"] if existing else None)
        counts["updated" if existing else "added"] += 1
        _index_links(db, note_id, text)
        _index_fts(db, note_id, text)

    gone = set(indexed) - on_disk
    for rel in gone:
        # Mark, never delete. An editor's atomic-save window or a network drive
        # hiccup must not destroy backlinks.
        db.execute(
            "UPDATE notes SET note_type = 'missing', indexed_at = datetime('now') "
            "WHERE id = ?",
            (indexed[rel]["id"],),
        )
        counts["missing"] += 1

    db.commit()
    _resolve_note_links(db)
    return counts


def scan_all(force=False):
    ensure_roots()
    totals = {"seen": 0, "added": 0, "updated": 0, "unchanged": 0, "missing": 0}
    per_root = {}
    for root in roots():
        counts = scan_root(root, force=force)
        per_root[root["root_key"]] = counts
        for key in totals:
            totals[key] += counts[key]
    return totals, per_root


def _upsert(db, root, rel, text, digest, mtime, size, note_id):
    frontmatter, _body = md.split_frontmatter(text)
    title = md.title_from(text, fallback=Path(rel).stem.replace("-", " ").title())
    tags = md.parse_tags(text, frontmatter)
    project_id, workstream_id = _infer_owner(db, root, rel, frontmatter)

    import json

    payload = (
        title,
        frontmatter.get("type") or None,
        project_id,
        workstream_id,
        json.dumps(frontmatter, default=str) if frontmatter else None,
        ",".join(tags) if tags else None,
        digest,
        mtime,
        size,
    )

    if note_id:
        db.execute(
            "UPDATE notes SET title = ?, note_type = ?, project_id = ?, workstream_id = ?, "
            "frontmatter_json = ?, tags = ?, content_hash = ?, mtime = ?, size_bytes = ?, "
            "indexed_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            payload + (note_id,),
        )
        return note_id

    cursor = db.execute(
        "INSERT INTO notes (root_id, rel_path, title, note_type, project_id, workstream_id, "
        "frontmatter_json, tags, content_hash, mtime, size_bytes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (root["id"], rel) + payload,
    )
    return cursor.lastrowid


def _infer_owner(db, root, rel, frontmatter):
    """Bind a note to its project and workstream from the folder it sits in.

    Folder position is used rather than frontmatter alone, because the folder
    is what a person sees and moves — and the file is the truth.
    """
    if root["root_key"] != "projects":
        return None, None

    parts = rel.split("/")
    if len(parts) < 2:
        return None, None

    portfolio_slug, project_slug = parts[0], parts[1]
    project = db.execute(
        "SELECT p.id FROM projects p JOIN portfolios pf ON pf.id = p.portfolio_id "
        "WHERE p.folder_path = ? OR (pf.folder_slug = ? AND p.folder_path LIKE ?)",
        (f"{portfolio_slug}/{project_slug}", portfolio_slug, f"%/{project_slug}"),
    ).fetchone()
    if project is None:
        return None, None

    workstream_id = None
    if len(parts) > 3 or (len(parts) == 3 and not parts[2].endswith(NOTE_SUFFIX)):
        workstream = db.execute(
            "SELECT id FROM workstreams WHERE project_id = ? AND folder_path LIKE ?",
            (project["id"], f"%/{parts[2]}"),
        ).fetchone()
        if workstream:
            workstream_id = workstream["id"]

    return project["id"], workstream_id


def _index_links(db, note_id, text):
    db.execute("DELETE FROM note_links WHERE from_note_id = ?", (note_id,))
    for link in md.parse_links(text):
        db.execute(
            "INSERT INTO note_links (from_note_id, link_text, target_kind, target_type, "
            "target_id, is_resolved) VALUES (?, ?, ?, ?, ?, 0)",
            (note_id, link["raw"], link["kind"],
             link["type"] if link["kind"] == "record" else None, None),
        )


def _index_fts(db, note_id, text):
    body = md.split_frontmatter(text)[1]
    title = md.title_from(text)
    db.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
    db.execute("INSERT INTO notes_fts (rowid, title, body) VALUES (?, ?, ?)",
               (note_id, title, body))


def _resolve_note_links(db):
    """Point every link at a real row where one exists.

    Resolution order per docs/NOTES_VAULT_SPEC.md §4: exact relative path, then
    a *unique* filename match within the same root. Ambiguous filenames stay
    unresolved rather than being guessed at, and show in the report.

    Done in Python rather than SQL because "unique basename within root" is
    unreadable as a correlated subquery, and unreadable is how this kind of
    thing ends up silently wrong.
    """
    notes_by_root = {}
    for row in db.execute("SELECT id, root_id, rel_path FROM notes").fetchall():
        by_path, by_stem = notes_by_root.setdefault(row["root_id"], ({}, {}))
        by_path[row["rel_path"].lower()] = row["id"]
        stem = row["rel_path"].rsplit("/", 1)[-1]
        if stem.endswith(NOTE_SUFFIX):
            stem = stem[: -len(NOTE_SUFFIX)]
        by_stem.setdefault(stem.lower(), []).append(row["id"])

    pending = db.execute(
        "SELECT l.id, l.link_text, n.root_id FROM note_links l "
        "JOIN notes n ON n.id = l.from_note_id "
        "WHERE l.target_kind = 'note' AND l.target_note_id IS NULL"
    ).fetchall()

    for link in pending:
        by_path, by_stem = notes_by_root.get(link["root_id"], ({}, {}))
        reference = link["link_text"].strip().lower()
        target = by_path.get(reference) or by_path.get(reference + NOTE_SUFFIX)
        if target is None:
            candidates = by_stem.get(reference.rsplit("/", 1)[-1], [])
            target = candidates[0] if len(candidates) == 1 else None
        if target is not None:
            db.execute(
                "UPDATE note_links SET target_note_id = ?, is_resolved = 1 WHERE id = ?",
                (target, link["id"]),
            )

    _resolve_record_links(db)
    db.commit()


RECORD_RESOLVERS = {
    "project": ("projects", "id",
                "SELECT id FROM projects WHERE code = ? OR folder_path LIKE ? OR name = ?"),
    "task": ("tasks", "id", "SELECT id FROM tasks WHERE id = ?"),
    "person": ("people", "id",
               "SELECT id FROM people WHERE lower(email) = lower(?) OR full_name = ?"),
    "charge": ("charge_codes", "id", "SELECT id FROM charge_codes WHERE code = ?"),
    "workstream": ("workstreams", "id", "SELECT id FROM workstreams WHERE name = ?"),
}


def _resolve_record_links(db):
    pending = db.execute(
        "SELECT id, target_type, link_text FROM note_links "
        "WHERE target_kind = 'record' AND target_id IS NULL"
    ).fetchall()

    for row in pending:
        namespace = row["target_type"]
        reference = row["link_text"].partition(":")[2].strip()
        if not reference or namespace not in RECORD_RESOLVERS:
            continue

        if namespace == "project":
            found = db.execute(RECORD_RESOLVERS[namespace][2],
                               (reference, f"%/{reference}", reference)).fetchone()
        elif namespace == "person":
            found = db.execute(RECORD_RESOLVERS[namespace][2],
                               (reference, reference)).fetchone()
        elif namespace == "task":
            if not reference.isdigit():
                continue
            found = db.execute(RECORD_RESOLVERS[namespace][2], (int(reference),)).fetchone()
        else:
            found = db.execute(RECORD_RESOLVERS[namespace][2], (reference,)).fetchone()

        if found:
            db.execute("UPDATE note_links SET target_id = ?, is_resolved = 1 WHERE id = ?",
                       (found["id"], row["id"]))


# --- reads ------------------------------------------------------------------


def list_notes(root_id=None, project_id=None, search=None, tag=None, limit=200, offset=0):
    clauses, params = ["n.note_type IS NOT 'missing'"], []
    if root_id:
        clauses.append("n.root_id = ?")
        params.append(root_id)
    if project_id:
        clauses.append("n.project_id = ?")
        params.append(project_id)
    if tag:
        clauses.append("(',' || n.tags || ',') LIKE ?")
        params.append(f"%,{tag},%")
    if search:
        clauses.append("(n.title LIKE ? OR n.rel_path LIKE ?)")
        params.extend([f"%{search}%"] * 2)

    return get_db().execute(
        "SELECT n.*, r.root_key, r.label AS root_label, r.is_readonly, p.name AS project_name "
        "FROM notes n JOIN vault_roots r ON r.id = n.root_id "
        "LEFT JOIN projects p ON p.id = n.project_id "
        "WHERE " + " AND ".join(clauses)
        + " ORDER BY n.mtime DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()


def get_note(note_id):
    return get_db().execute(
        "SELECT n.*, r.root_key, r.label AS root_label, r.abs_path, r.is_readonly, "
        "       p.name AS project_name, w.name AS workstream_name "
        "FROM notes n JOIN vault_roots r ON r.id = n.root_id "
        "LEFT JOIN projects p ON p.id = n.project_id "
        "LEFT JOIN workstreams w ON w.id = n.workstream_id "
        "WHERE n.id = ?",
        (note_id,),
    ).fetchone()


def note_path(note):
    """Absolute path, confined to the note's own root."""
    return paths.confine(note["abs_path"], note["rel_path"])


def read_note(note):
    path = note_path(note)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write_note(note, text):
    """Write the file, then re-index it. The file is written first, always."""
    root = get_root(note["root_id"])
    if root["is_readonly"]:
        raise PermissionError(f"the {root['label']} root is read-only")

    path = paths.confine(root["abs_path"], note["rel_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")

    db = get_db()
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds")
    note_id = _upsert(db, root, note["rel_path"], text, md.content_hash(text),
                      mtime, stat.st_size, note["id"])
    _index_links(db, note_id, text)
    _index_fts(db, note_id, text)
    db.commit()
    _resolve_note_links(db)
    return note_id


def create_note(root_id, rel_path, text):
    root = get_root(root_id)
    if root is None:
        raise ValueError("no such vault root")
    if root["is_readonly"]:
        raise PermissionError(f"the {root['label']} root is read-only")

    if not rel_path.endswith(NOTE_SUFFIX):
        rel_path += NOTE_SUFFIX
    path = paths.confine(root["abs_path"], rel_path)
    if path.exists():
        raise FileExistsError(f"{rel_path} already exists")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")

    db = get_db()
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds")
    note_id = _upsert(db, root, rel_path, text, md.content_hash(text),
                      mtime, stat.st_size, None)
    _index_links(db, note_id, text)
    _index_fts(db, note_id, text)
    db.commit()
    _resolve_note_links(db)
    return note_id


# Sentinels rather than literal <mark> tags, so the note body can be escaped
# first and only our own highlighting survives as markup. Emitting raw HTML from
# a note body into a template is exactly the hole nh3 exists to close.
_HL_OPEN, _HL_CLOSE = "\x02", "\x03"


def search_notes(query, limit=50):
    """FTS5 with highlighted snippets. Returns [] on a malformed query.

    A bad query is a typo, not an error worth a stack trace — FTS5 raises on
    unbalanced quotes and stray operators, which users produce constantly.
    """
    try:
        rows = get_db().execute(
            "SELECT n.id, n.title, n.rel_path, r.root_key, r.label AS root_label, "
            "       snippet(notes_fts, 1, ?, ?, '…', 24) AS snippet, "
            "       bm25(notes_fts) AS rank "
            "FROM notes_fts JOIN notes n ON n.id = notes_fts.rowid "
            "JOIN vault_roots r ON r.id = n.root_id "
            "WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?",
            (_HL_OPEN, _HL_CLOSE, query, limit),
        ).fetchall()
    except Exception:
        return []

    from html import escape

    from markupsafe import Markup

    results = []
    for row in rows:
        raw = row["snippet"] or ""
        highlighted = escape(raw).replace(_HL_OPEN, "<mark>").replace(_HL_CLOSE, "</mark>")
        record = dict(row)
        record["snippet"] = Markup(highlighted)
        results.append(record)
    return results


def backlinks(target_type, target_id):
    return get_db().execute(
        "SELECT n.id, n.title, n.rel_path, r.root_key, l.link_text "
        "FROM note_links l JOIN notes n ON n.id = l.from_note_id "
        "JOIN vault_roots r ON r.id = n.root_id "
        "WHERE l.target_kind = 'record' AND l.target_type = ? AND l.target_id = ? "
        "ORDER BY n.title",
        (target_type, target_id),
    ).fetchall()


def note_backlinks(note_id):
    return get_db().execute(
        "SELECT n.id, n.title, n.rel_path, l.link_text FROM note_links l "
        "JOIN notes n ON n.id = l.from_note_id "
        "WHERE l.target_note_id = ? ORDER BY n.title",
        (note_id,),
    ).fetchall()


def outbound_links(note_id):
    return get_db().execute(
        "SELECT l.*, n.title AS target_title, n.rel_path AS target_path "
        "FROM note_links l LEFT JOIN notes n ON n.id = l.target_note_id "
        "WHERE l.from_note_id = ? ORDER BY l.target_kind, l.link_text",
        (note_id,),
    ).fetchall()


def unresolved_links():
    return get_db().execute(
        "SELECT l.link_text, l.target_kind, l.target_type, COUNT(*) AS n, "
        "       MIN(n2.title) AS example_note, MIN(n2.id) AS example_id "
        "FROM note_links l JOIN notes n2 ON n2.id = l.from_note_id "
        "WHERE l.is_resolved = 0 GROUP BY l.link_text, l.target_kind, l.target_type "
        "ORDER BY n DESC, l.link_text"
    ).fetchall()


def missing_notes():
    return get_db().execute(
        "SELECT n.*, r.label AS root_label FROM notes n "
        "JOIN vault_roots r ON r.id = n.root_id "
        "WHERE n.note_type = 'missing' ORDER BY n.rel_path"
    ).fetchall()


def all_tags():
    rows = get_db().execute(
        "SELECT tags FROM notes WHERE tags IS NOT NULL AND tags <> ''"
    ).fetchall()
    counts = {}
    for row in rows:
        for tag in row["tags"].split(","):
            tag = tag.strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def stats():
    db = get_db()
    return {
        "notes": db.execute(
            "SELECT COUNT(*) FROM notes WHERE note_type IS NOT 'missing'").fetchone()[0],
        "missing": db.execute(
            "SELECT COUNT(*) FROM notes WHERE note_type = 'missing'").fetchone()[0],
        "links": db.execute("SELECT COUNT(*) FROM note_links").fetchone()[0],
        "unresolved": db.execute(
            "SELECT COUNT(*) FROM note_links WHERE is_resolved = 0").fetchone()[0],
    }
