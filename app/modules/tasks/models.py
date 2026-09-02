"""Tasks, and the recurrence engine behind them.

`as_of` is a parameter on every date-sensitive query. Routes supply
`date.today()`; nothing here assumes it (CLAUDE.md rule 17). That is what
makes "what will be overdue in March?" answerable without a rewrite.
"""
import json

from app.core.database import get_db

SELECT = """
SELECT t.*,
       p.name  AS project_name,
       w.name  AS workstream_name,
       c.code  AS charge_code,
       a.full_name AS assignee_name
  FROM tasks t
  LEFT JOIN projects p     ON p.id = t.project_id
  LEFT JOIN workstreams w  ON w.id = t.workstream_id
  LEFT JOIN charge_codes c ON c.id = t.charge_code_id
  LEFT JOIN people a       ON a.id = t.assignee_person_id
"""

WRITABLE = (
    "title", "description", "task_type", "status", "priority", "due_date",
    "start_date", "project_id", "workstream_id", "charge_code_id",
    "assignee_person_id", "estimate_hours", "source", "source_ref", "sort_order",
)

OPEN_STATUSES = ("open", "in_progress", "blocked")


def _filters(search=None, status=None, priority=None, project_id=None,
             workstream_id=None, charge_code_id=None, assignee_person_id=None,
             task_type=None, open_only=False, include_archived=False):
    clauses, params = [], []
    if not include_archived:
        clauses.append("t.archived_at IS NULL")
    if open_only:
        clauses.append("t.status IN ('open','in_progress','blocked')")
    if search:
        clauses.append("(t.title LIKE ? OR t.description LIKE ?)")
        params.extend([f"%{search}%"] * 2)
    for column, value in (("t.status", status), ("t.priority", priority),
                          ("t.task_type", task_type), ("t.project_id", project_id),
                          ("t.workstream_id", workstream_id),
                          ("t.charge_code_id", charge_code_id),
                          ("t.assignee_person_id", assignee_person_id)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def list_tasks(sort="due", limit=200, offset=0, **filters):
    where, params = _filters(**filters)
    order = {
        "due": "t.due_date IS NULL, t.due_date, "
               "CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END",
        "priority": "CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
                    "t.due_date IS NULL, t.due_date",
        "created": "t.created_at DESC",
        "project": "p.name, t.due_date",
    }.get(sort, "t.due_date IS NULL, t.due_date")
    return get_db().execute(
        SELECT + where + f" ORDER BY {order} LIMIT ? OFFSET ?", params + [limit, offset]
    ).fetchall()


def count_tasks(**filters):
    where, params = _filters(**filters)
    return get_db().execute(
        "SELECT COUNT(*) AS n FROM tasks t LEFT JOIN projects p ON p.id = t.project_id" + where,
        params,
    ).fetchone()["n"]


def get_task(task_id):
    return get_db().execute(SELECT + " WHERE t.id = ?", (task_id,)).fetchone()


def create_task(fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE and v is not None}
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO tasks ({columns}) VALUES ({placeholders})", list(payload.values())
    )
    db.commit()
    return cursor.lastrowid


def update_task(task_id, fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE tasks SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        list(payload.values()) + [task_id],
    )
    db.commit()
    return cursor.rowcount


def set_status(task_ids, status):
    """Bulk status change in one statement, one transaction."""
    if not task_ids:
        return 0
    placeholders = ", ".join("?" for _ in task_ids)
    completed = "completed_at = datetime('now')," if status == "completed" else \
                "completed_at = NULL," if status in OPEN_STATUSES else ""
    db = get_db()
    cursor = db.execute(
        f"UPDATE tasks SET status = ?, {completed} updated_at = datetime('now') "
        f"WHERE id IN ({placeholders})",
        [status] + list(task_ids),
    )
    db.commit()
    return cursor.rowcount


def archive_task(task_id, archived=True):
    db = get_db()
    stamp = "datetime('now')" if archived else "NULL"
    cursor = db.execute(
        f"UPDATE tasks SET archived_at = {stamp}, updated_at = datetime('now') WHERE id = ?",
        (task_id,),
    )
    db.commit()
    return cursor.rowcount


# --- the numbers behind the Command Center ----------------------------------


def counts(as_of, self_person_id=None):
    """Every action-strip figure, as one query per figure and nothing stored."""
    db = get_db()
    mine = " AND t.assignee_person_id = ?" if self_person_id else ""
    args = [self_person_id] if self_person_id else []

    def scalar(sql, params=()):
        return db.execute(sql, params).fetchone()[0]

    base = ("SELECT COUNT(*) FROM tasks t WHERE t.archived_at IS NULL "
            "AND t.status IN ('open','in_progress','blocked')")
    return {
        "overdue": scalar(f"{base} AND t.due_date < ?{mine}", [as_of] + args),
        "due_today": scalar(f"{base} AND t.due_date = ?{mine}", [as_of] + args),
        "due_week": scalar(
            f"{base} AND t.due_date > ? AND t.due_date <= date(?, '+7 days'){mine}",
            [as_of, as_of] + args),
        "no_due_date": scalar(f"{base} AND t.due_date IS NULL{mine}", args),
        "blocked": scalar(
            "SELECT COUNT(*) FROM tasks t WHERE t.archived_at IS NULL "
            f"AND t.status = 'blocked'{mine}", args),
        "open_total": scalar(f"{base}{mine}", args),
        "completed_week": scalar(
            "SELECT COUNT(*) FROM tasks t WHERE t.status = 'completed' "
            f"AND date(t.completed_at) > date(?, '-7 days'){mine}", [as_of] + args),
    }


def overdue(as_of, limit=20):
    return get_db().execute(
        SELECT + " WHERE t.archived_at IS NULL AND t.status IN ('open','in_progress','blocked') "
        "AND t.due_date < ? ORDER BY t.due_date LIMIT ?",
        (as_of, limit),
    ).fetchall()


def due_between(start, end, limit=40):
    return get_db().execute(
        SELECT + " WHERE t.archived_at IS NULL AND t.status IN ('open','in_progress','blocked') "
        "AND t.due_date >= ? AND t.due_date <= ? ORDER BY t.due_date, t.priority LIMIT ?",
        (start, end, limit),
    ).fetchall()


def by_project(as_of):
    """Open task load per project, for the health zone."""
    return get_db().execute(
        "SELECT p.id, p.name, p.rag_status, p.status, p.forecast_end, "
        "  COUNT(t.id) AS open_tasks, "
        "  SUM(CASE WHEN t.due_date < ? THEN 1 ELSE 0 END) AS overdue_tasks "
        "FROM projects p LEFT JOIN tasks t "
        "  ON t.project_id = p.id AND t.archived_at IS NULL "
        "  AND t.status IN ('open','in_progress','blocked') "
        "WHERE p.archived_at IS NULL AND p.status = 'active' "
        "GROUP BY p.id ORDER BY overdue_tasks DESC, p.name",
        (as_of,),
    ).fetchall()


# --- recurrence -------------------------------------------------------------


def recurrences(active_only=True):
    sql = "SELECT * FROM task_recurrences"
    if active_only:
        sql += " WHERE is_active = 1"
    return get_db().execute(sql + " ORDER BY next_due IS NULL, next_due").fetchall()


def create_recurrence(title, rrule, payload, next_due=None, until_date=None):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO task_recurrences (template_title, rrule, next_due, until_date, payload_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (title, rrule, next_due, until_date, json.dumps(payload)),
    )
    db.commit()
    return cursor.lastrowid


def next_occurrence(rrule_text, after):
    """The next date an RRULE fires after `after`. None if it has run out."""
    try:
        from dateutil.rrule import rrulestr
    except ImportError:
        return None

    from datetime import datetime

    try:
        start = datetime.fromisoformat(str(after))
        rule = rrulestr(rrule_text, dtstart=start)
        following = rule.after(start, inc=False)
        return following.date().isoformat() if following else None
    except (ValueError, TypeError):
        return None


def regenerate_from(task_id, as_of):
    """When a recurring task is completed, create the next one.

    Returns the new task id, or None when the series has ended.
    """
    db = get_db()
    task = get_task(task_id)
    if task is None or not task["recurrence_id"]:
        return None

    rule = db.execute("SELECT * FROM task_recurrences WHERE id = ? AND is_active = 1",
                      (task["recurrence_id"],)).fetchone()
    if rule is None:
        return None

    following = next_occurrence(rule["rrule"], task["due_date"] or as_of)
    if following is None or (rule["until_date"] and following > rule["until_date"]):
        db.execute("UPDATE task_recurrences SET is_active = 0 WHERE id = ?", (rule["id"],))
        db.commit()
        return None

    payload = json.loads(rule["payload_json"])
    payload.update({"title": rule["template_title"], "due_date": following, "status": "open"})
    fields = {k: v for k, v in payload.items() if k in WRITABLE}
    columns = ", ".join(fields) + ", recurrence_id"
    placeholders = ", ".join("?" for _ in fields) + ", ?"
    cursor = db.execute(
        f"INSERT INTO tasks ({columns}) VALUES ({placeholders})",
        list(fields.values()) + [rule["id"]],
    )
    db.execute("UPDATE task_recurrences SET next_due = ? WHERE id = ?", (following, rule["id"]))
    db.commit()
    return cursor.lastrowid
