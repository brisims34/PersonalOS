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
    """Both directions, deduplicated, for the links panel of the object grammar."""
    seen, combined = set(), []
    for direction, rows in (
        ("outbound", links_for(entity_type, entity_id)),
        ("inbound", backlinks_for(entity_type, entity_id)),
    ):
        for row in rows:
            identity = (row["other_type"], row["other_id"])
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
    return combined


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
