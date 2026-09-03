"""Notes Vault — markdown on disk, indexed into SQLite.

The file is the truth. Every write here writes the file first and re-indexes
afterwards, so an external edit in VS Code or Obsidian is never lost and the
index can always be thrown away and rebuilt.
"""
from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)

from app.core import activity, charter, notes_index
from app.core import markdown as md
from app.core.module_registry import guard_blueprint
from app.core.paths import PathConfinementError

bp = Blueprint("notes", __name__, url_prefix="/notes")
guard_blueprint(bp, "notes")

CRUMB = ("Notes Vault", "/notes")


def _resolver(note=None):
    """Turn a parsed wikilink into (url, is_resolved) for rendering."""
    from app.core.database import get_db

    db = get_db()

    def resolve(link):
        if link["kind"] == "record":
            namespace, reference = link["type"], link["ref"]
            if namespace == "project":
                row = db.execute(
                    "SELECT id FROM projects WHERE code = ? OR name = ? OR folder_path LIKE ?",
                    (reference, reference, f"%/{reference}"),
                ).fetchone()
                return (f"/projects/{row['id']}", True) if row else ("#", False)
            if namespace == "person":
                row = db.execute(
                    "SELECT id FROM people WHERE lower(email) = lower(?) OR full_name = ?",
                    (reference, reference),
                ).fetchone()
                return (f"/people/{row['id']}", True) if row else ("#", False)
            if namespace == "charge":
                row = db.execute("SELECT id FROM charge_codes WHERE code = ?",
                                 (reference,)).fetchone()
                return (f"/charge-codes/{row['id']}", True) if row else ("#", False)
            if namespace == "task" and reference.isdigit():
                row = db.execute("SELECT id FROM tasks WHERE id = ?",
                                 (int(reference),)).fetchone()
                return (f"/tasks/{row['id']}", True) if row else ("#", False)
            if namespace == "workstream":
                row = db.execute("SELECT id FROM workstreams WHERE name = ?",
                                 (reference,)).fetchone()
                return (f"/projects/workstreams/{row['id']}", True) if row else ("#", False)
            return "#", False

        root_id = note["root_id"] if note else None
        reference = link["ref"].strip()
        row = db.execute(
            "SELECT id FROM notes WHERE root_id = ? AND (rel_path = ? OR rel_path = ?)",
            (root_id, reference, reference + ".md"),
        ).fetchone()
        if row is None:
            candidates = db.execute(
                "SELECT id FROM notes WHERE root_id = ? AND rel_path LIKE ?",
                (root_id, f"%{reference}.md"),
            ).fetchall()
            row = candidates[0] if len(candidates) == 1 else None
        return (f"/notes/{row['id']}", True) if row else ("#", False)

    return resolve


@bp.get("/")
def index():
    root_key = request.args.get("root")
    root = notes_index.root_by_key(root_key) if root_key else None
    return render_template(
        "modules/notes/index.html",
        notes=notes_index.list_notes(
            root_id=root["id"] if root else None,
            search=(request.args.get("q") or "").strip() or None,
            tag=request.args.get("tag") or None,
        ),
        roots=notes_index.roots(),
        current_root=root,
        tags=notes_index.all_tags()[:40],
        stats=notes_index.stats(),
        filters={"q": request.args.get("q") or "", "tag": request.args.get("tag") or ""},
        crumbs=[CRUMB[0]],
    )


@bp.get("/<int:note_id>")
def detail(note_id):
    note = notes_index.get_note(note_id)
    if note is None:
        abort(404)
    try:
        text = notes_index.read_note(note)
    except PathConfinementError:
        abort(400)

    if text is None:
        flash(
            f"{note['rel_path']} is indexed but not on disk. The index row is kept "
            "so backlinks survive — rescan once the file is back.",
            "warning",
        )
        return redirect(url_for("notes.index"))

    return render_template(
        "modules/notes/detail.html",
        note=note,
        html=md.render(text, resolver=_resolver(note)),
        frontmatter=md.split_frontmatter(text)[0],
        backlinks=notes_index.note_backlinks(note_id),
        outbound=notes_index.outbound_links(note_id),
        blocks=md.find_blocks(text)[0],
        trail=activity.for_entity("note", note_id, limit=15),
        crumbs=[CRUMB, note["title"]],
    )


@bp.get("/<int:note_id>/edit")
def edit(note_id):
    note = notes_index.get_note(note_id)
    if note is None:
        abort(404)
    if note["is_readonly"]:
        flash(f"The {note['root_label']} root is read-only.", "error")
        return redirect(url_for("notes.detail", note_id=note_id))

    text = notes_index.read_note(note) or ""
    return render_template(
        "modules/notes/edit.html",
        note=note,
        text=text,
        content_hash=md.content_hash(text),
        crumbs=[CRUMB, (note["title"], url_for("notes.detail", note_id=note_id)), "Edit"],
    )


@bp.post("/<int:note_id>/save")
def save(note_id):
    note = notes_index.get_note(note_id)
    if note is None:
        abort(404)

    text = request.form.get("body", "")
    expected = request.form.get("content_hash")

    # The file is the truth, so an edit made in VS Code while this tab was open
    # must not be silently clobbered.
    current = notes_index.read_note(note)
    if current is not None and expected and md.content_hash(current) != expected:
        flash(
            f"{note['rel_path']} changed on disk while you were editing. Nothing was "
            "saved — reopen it, and reapply your change on top of the newer version.",
            "error",
        )
        return redirect(url_for("notes.detail", note_id=note_id))

    try:
        notes_index.write_note(note, text)
    except PermissionError as exc:
        flash(str(exc), "error")
        return redirect(url_for("notes.detail", note_id=note_id))

    activity.log("note", note_id, "updated", f"Edited {note['rel_path']}")
    flash(f"Saved to {note['rel_path']} on disk and re-indexed.", "success")
    return redirect(url_for("notes.detail", note_id=note_id))


@bp.post("/preview")
def preview():
    """Server-side render for the editor's live preview.

    One renderer for preview and read view, so what you see while typing cannot
    diverge from what gets saved.
    """
    return jsonify({"html": md.render(request.form.get("body", ""), resolver=_resolver())})


@bp.get("/new")
def new():
    return render_template(
        "modules/notes/new.html",
        roots=[r for r in notes_index.roots() if not r["is_readonly"]],
        suggested_path=request.args.get("path", ""),
        crumbs=[CRUMB, "New note"],
    )


@bp.post("/create")
def create():
    root_id = request.form.get("root_id", type=int)
    rel_path = (request.form.get("rel_path") or "").strip().lstrip("/")
    title = (request.form.get("title") or "").strip()

    if not root_id or not rel_path:
        flash("A note needs a vault root and a path.", "error")
        return redirect(url_for("notes.new"))

    body = request.form.get("body") or f"# {title or rel_path}\n\n"
    try:
        note_id = notes_index.create_note(root_id, rel_path, body)
    except FileExistsError:
        flash(f"{rel_path} already exists. Open it rather than creating a second one.", "error")
        return redirect(url_for("notes.new", path=rel_path))
    except (PermissionError, PathConfinementError, ValueError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("notes.new", path=rel_path))

    activity.log("note", note_id, "created", f"Created note {rel_path}")
    flash(f"Created {rel_path} on disk.", "success")
    return redirect(url_for("notes.detail", note_id=note_id))


@bp.post("/rescan")
def rescan():
    force = request.form.get("force") == "1"
    totals, per_root = notes_index.scan_all(force=force)
    activity.log("notes", None, "synced",
                 f"Vault scan: {totals['added']} new, {totals['updated']} changed, "
                 f"{totals['missing']} missing")
    flash(
        f"Scanned {totals['seen']} file{'s' if totals['seen'] != 1 else ''} — "
        f"{totals['added']} new, {totals['updated']} changed, "
        f"{totals['unchanged']} unchanged"
        + (f", {totals['missing']} indexed but no longer on disk." if totals["missing"]
           else "."),
        "success",
    )
    return redirect(request.referrer or url_for("notes.index"))


@bp.get("/reports/unresolved")
def unresolved():
    return render_template(
        "modules/notes/unresolved.html",
        links=notes_index.unresolved_links(),
        missing=notes_index.missing_notes(),
        crumbs=[CRUMB, "Unresolved links"],
    )


@bp.post("/<int:note_id>/refresh-blocks")
def refresh_blocks(note_id):
    """Re-render the managed blocks in a charter from live data."""
    note = notes_index.get_note(note_id)
    if note is None:
        abort(404)
    if not note["workstream_id"]:
        flash("Managed blocks only refresh on a note bound to a workstream.", "error")
        return redirect(url_for("notes.detail", note_id=note_id))

    text = notes_index.read_note(note)
    if text is None:
        flash("That file is not on disk.", "error")
        return redirect(url_for("notes.index"))

    updated, changed, warnings = charter.refresh(text, note["workstream_id"])
    if changed:
        notes_index.write_note(note, updated)
        activity.log("note", note_id, "updated",
                     f"Refreshed managed blocks: {', '.join(changed)}")

    for warning in warnings:
        flash(warning.capitalize(), "warning")
    flash(
        f"Refreshed {len(changed)} block{'s' if len(changed) != 1 else ''} "
        f"({', '.join(changed)}). Everything you wrote between them is unchanged."
        if changed else "Every managed block was already up to date.",
        "success",
    )
    return redirect(url_for("notes.detail", note_id=note_id))
