"""Cross-cutting relationships via `entity_links`.

For many-to-many relationships that cut across modules — notes to anything,
people to anything, emails to anything. **Not** for containment or money:
a workstream belongs to a project through a real foreign key, and always will
(CLAUDE.md rule 9, PersonalOS_Spec.md §7.1).

Direction convention: the linking subject is always the source. Linking a note
to a project stores ('note', n, 'project', p).
"""
from app.core.database import get_db

# Distinguishes "the caller didn't pass link_label" from "the caller passed
# link_label=None on purpose" — the two need different SQL (see unlink()).
_UNSET = object()


def exists(source_type, source_id, target_type, target_id, link_label=None):
    """Whether this exact (source, target, label) link is already present.

    Needed because `entity_links`' UNIQUE constraint includes link_label, and
    SQL treats every NULL as distinct from every other NULL — so two links
    with no label never collide there. `link()` calls this to restore the
    "adding it twice is a no-op" guarantee for the no-label case too.
    """
    db = get_db()
    sql = ("SELECT 1 FROM entity_links WHERE source_type = ? AND source_id = ? "
           "AND target_type = ? AND target_id = ?")
    params = [source_type, source_id, target_type, target_id]
    if link_label is None:
        sql += " AND link_label IS NULL"
    else:
        sql += " AND link_label = ?"
        params.append(link_label)
    return db.execute(sql + " LIMIT 1", params).fetchone() is not None


# What the links panel resolves an entity_type to: (table, display-name column,
# url builder). entity_type strings are free text in entity_links (it is
# polymorphic by design), so this map is the only place they are ever turned
# into a table or column name — always a developer constant, never row data
# (CLAUDE.md rule 2). A None url builder means the type has no standalone
# detail page yet; the panel then shows the resolved name as plain text.
_ENTITY_DISPLAY = {
    "project":     ("projects", "name", lambda entity_id: f"/projects/{entity_id}"),
    "workstream":  ("workstreams", "name", lambda entity_id: f"/projects/workstreams/{entity_id}"),
    "person":      ("people", "full_name", lambda entity_id: f"/people/{entity_id}"),
    "location":    ("locations", "name", None),
    "portfolio":   ("portfolios", "name", lambda entity_id: f"/portfolios/{entity_id}"),
    "task":        ("tasks", "title", lambda entity_id: f"/tasks/{entity_id}"),
    "note":        ("notes", "title", lambda entity_id: f"/notes/{entity_id}"),
    "charge_code": ("charge_codes", "name", lambda entity_id: f"/charge-codes/{entity_id}"),
}


def _resolve_targets(rows):
    """Attach the actual target entity's display_name/url to each related-record row.

    One query per distinct type in the batch (not per row) — a project's team
    tab may list a dozen people, and that should not be a dozen round trips.
    `link_label` is left untouched: on project/workstream Team links it holds
    the person's role, not their name, and callers still need it separately.
    """
    db = get_db()
    ids_by_type = {}
    for row in rows:
        ids_by_type.setdefault(row["type"], set()).add(row["entity_id"])

    names = {}
    for entity_type, ids in ids_by_type.items():
        spec = _ENTITY_DISPLAY.get(entity_type)
        if not spec:
            continue
        table, name_col, _url = spec
        placeholders = ",".join("?" * len(ids))
        query = f"SELECT id, {name_col} AS name FROM {table} WHERE id IN ({placeholders})"
        for record in db.execute(query, tuple(ids)).fetchall():
            names[(entity_type, record["id"])] = record["name"]

    for row in rows:
        spec = _ENTITY_DISPLAY.get(row["type"])
        name = names.get((row["type"], row["entity_id"]))
        row["display_name"] = name
        row["url"] = spec[2](row["entity_id"]) if spec and spec[2] and name is not None else None

    return rows


def link(source_type, source_id, target_type, target_id, link_label=None):
    """Create the link if it does not exist. Returns True if a row was added."""
    if (source_type, source_id) == (target_type, target_id):
        raise ValueError("an entity cannot be linked to itself")

    db = get_db()
    if link_label is None and exists(source_type, source_id, target_type, target_id, None):
        # UNIQUE can't catch this one (see exists()) — check by hand.
        return False
    cursor = db.execute(
        "INSERT OR IGNORE INTO entity_links "
        "(source_type, source_id, target_type, target_id, link_label) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_type, source_id, target_type, target_id, link_label),
    )
    db.commit()
    return cursor.rowcount == 1


def unlink(source_type, source_id, target_type, target_id, link_label=_UNSET):
    """Remove the link(s) between a source and target.

    `link_label` is now part of `entity_links`' UNIQUE key (§0008), so one
    pair of entities can carry several links with different labels — a
    person holding two roles on the same project, say. Passing `link_label`
    (including explicitly passing `None`, to mean "the link with no label")
    removes only that one specific link. Omitting the argument entirely is
    the historical call shape and removes every link between the pair —
    keep using that form only when there is deliberately no more than one
    link per pair to worry about; anything that hands a person a specific
    row to remove (like the Team tab) must pass that row's actual label,
    `None` included, or a blank-labelled row's removal will take every
    other role that person holds on the same project down with it.
    """
    db = get_db()
    sql = ("DELETE FROM entity_links WHERE source_type = ? AND source_id = ? "
           "AND target_type = ? AND target_id = ?")
    params = [source_type, source_id, target_type, target_id]
    if link_label is not _UNSET:
        if link_label is None:
            sql += " AND link_label IS NULL"
        else:
            sql += " AND link_label = ?"
            params.append(link_label)
    cursor = db.execute(sql, params)
    db.commit()
    return cursor.rowcount


def links_for(entity_type, entity_id):
    """What this record points at."""
    return get_db().execute(
        "SELECT id, target_type AS other_type, target_id AS other_id, link_label, created_at "
        "FROM entity_links WHERE source_type = ? AND source_id = ? "
        "ORDER BY target_type, target_id",
        (entity_type, entity_id),
    ).fetchall()


def backlinks_for(entity_type, entity_id):
    """What points at this record — the panel that makes the vault useful."""
    return get_db().execute(
        "SELECT id, source_type AS other_type, source_id AS other_id, link_label, created_at "
        "FROM entity_links WHERE target_type = ? AND target_id = ? "
        "ORDER BY source_type, source_id",
        (entity_type, entity_id),
    ).fetchall()


def related(entity_type, entity_id):
    """Both directions, deduplicated, for the links panel of the object grammar.

    Dedup key includes link_label, not just the other entity — since §0008
    widened entity_links to allow more than one link per pair (a person
    holding two roles on the same project, say), collapsing on identity
    alone would silently drop every role past the first from the panel.
    """
    seen, combined = set(), []
    for direction, rows in (
        ("outbound", links_for(entity_type, entity_id)),
        ("inbound", backlinks_for(entity_type, entity_id)),
    ):
        for row in rows:
            identity = (row["other_type"], row["other_id"], row["link_label"])
            if identity in seen:
                continue
            seen.add(identity)
            combined.append(
                {
                    "id": row["id"],
                    "direction": direction,
                    "type": row["other_type"],
                    "entity_id": row["other_id"],
                    "label": row["link_label"],
                    "created_at": row["created_at"],
                }
            )
    return _resolve_targets(combined)


def unlink_all_for(entity_type, entity_id):
    """Drop every link touching a record. Call when a record is hard-deleted.

    Archiving must not call this — an archived record keeps its relationships
    so restoring it restores its context (CLAUDE.md rule 5, P5).
    """
    db = get_db()
    cursor = db.execute(
        "DELETE FROM entity_links WHERE (source_type = ? AND source_id = ?) "
        "OR (target_type = ? AND target_id = ?)",
        (entity_type, entity_id, entity_type, entity_id),
    )
    db.commit()
    return cursor.rowcount


def count_for(entity_type, entity_id):
    row = get_db().execute(
        "SELECT COUNT(*) AS n FROM entity_links "
        "WHERE (source_type = ? AND source_id = ?) OR (target_type = ? AND target_id = ?)",
        (entity_type, entity_id, entity_type, entity_id),
    ).fetchone()
    return row["n"]
