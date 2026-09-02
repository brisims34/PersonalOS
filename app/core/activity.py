"""The activity trail.

Every mutation writes one row (CLAUDE.md rule 13). This is what makes the
object grammar's fifth band real, and what makes an archive reversible.

Never write passwords, file contents or secret values here. `_redact()`
enforces that on the detail blob rather than trusting each caller to remember.
"""
import json

from app.core.config import is_sensitive_key
from app.core.database import get_db

ACTIONS = frozenset(
    [
        "created",
        "updated",
        "deleted",
        "archived",
        "restored",
        "imported",
        "exported",
        "synced",
        "ran",
    ]
)

REDACTED = "[redacted]"
MAX_DETAIL_CHARS = 8000


def _redact(detail):
    if isinstance(detail, dict):
        return {
            k: (REDACTED if is_sensitive_key(k) else _redact(v)) for k, v in detail.items()
        }
    if isinstance(detail, (list, tuple)):
        return [_redact(v) for v in detail]
    return detail


def log(entity_type, entity_id, action, summary, detail=None):
    """Record one mutation. Returns the new activity_log id.

    `summary` is the sentence a human reads, so it should name the specific
    effect the same way the on-screen confirmation does (P2).
    """
    if action not in ACTIONS:
        raise ValueError(
            f"unknown activity action {action!r} — one of {sorted(ACTIONS)}"
        )

    detail_json = None
    if detail is not None:
        try:
            detail_json = json.dumps(_redact(detail), default=str)
        except (TypeError, ValueError):
            detail_json = json.dumps({"unserialisable": str(type(detail))})
        if len(detail_json) > MAX_DETAIL_CHARS:
            detail_json = json.dumps(
                {"truncated": True, "chars": len(detail_json)}
            )

    db = get_db()
    cursor = db.execute(
        "INSERT INTO activity_log (entity_type, entity_id, action, summary, detail_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (entity_type, entity_id, action, summary, detail_json),
    )
    db.commit()
    return cursor.lastrowid


def for_entity(entity_type, entity_id, limit=20):
    return get_db().execute(
        "SELECT id, entity_type, entity_id, action, summary, detail_json, created_at "
        "FROM activity_log WHERE entity_type = ? AND entity_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (entity_type, entity_id, limit),
    ).fetchall()


def by_id(entry_id):
    return get_db().execute(
        "SELECT id, entity_type, entity_id, action, summary, detail_json, created_at "
        "FROM activity_log WHERE id = ?",
        (entry_id,),
    ).fetchone()


def _filter_clause(entity_type=None, action=None, since=None, search=None):
    """Build the shared WHERE clause and its bound parameters.

    The returned SQL contains only the fixed clause text written above — every
    value the caller supplied is in `params` and reaches SQLite as a bound
    parameter (CLAUDE.md rule 2). One helper rather than two copies so there is
    a single place to read when checking that.
    """
    clauses, params = [], []
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    if search:
        clauses.append("summary LIKE ?")
        params.append(f"%{search}%")

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def recent(limit=100, offset=0, entity_type=None, action=None, since=None, search=None):
    """Filtered feed for the Activity Log page."""
    where, params = _filter_clause(entity_type, action, since, search)
    sql = (
        "SELECT id, entity_type, entity_id, action, summary, detail_json, created_at "
        "FROM activity_log" + where + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    )
    return get_db().execute(sql, params + [limit, offset]).fetchall()


def count(entity_type=None, action=None, since=None, search=None):
    where, params = _filter_clause(entity_type, action, since, search)
    sql = "SELECT COUNT(*) AS n FROM activity_log" + where
    return get_db().execute(sql, params).fetchone()["n"]


def distinct_entity_types():
    return [
        r["entity_type"]
        for r in get_db().execute(
            "SELECT DISTINCT entity_type FROM activity_log ORDER BY entity_type"
        ).fetchall()
    ]
