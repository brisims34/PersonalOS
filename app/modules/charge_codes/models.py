"""Charge codes — the financial reconciliation key.

The charge code, not the project, is what time is booked against, what the
timesheet export carries, and what external reporting rolls up by. Leadership
lives on the code and falls back to the project when null, because distinct
leadership across codes on one engagement is normal.
"""
from app.core.database import get_db

SELECT = """
SELECT c.*,
       p.name AS project_name,
       p.lead_partner_person_id       AS project_partner_id,
       p.engagement_manager_person_id AS project_manager_id,
       w.name AS workstream_name,
       COALESCE(lp.full_name, plp.full_name) AS lead_partner_name,
       CASE WHEN c.lead_partner_person_id IS NULL THEN 1 ELSE 0 END AS partner_inherited,
       COALESCE(em.full_name, pem.full_name) AS engagement_manager_name,
       CASE WHEN c.engagement_manager_person_id IS NULL THEN 1 ELSE 0 END AS manager_inherited,
       rc.name AS rate_card_name
  FROM charge_codes c
  JOIN projects p        ON p.id = c.project_id
  LEFT JOIN workstreams w ON w.id = c.workstream_id
  LEFT JOIN people lp    ON lp.id = c.lead_partner_person_id
  LEFT JOIN people em    ON em.id = c.engagement_manager_person_id
  LEFT JOIN people plp   ON plp.id = p.lead_partner_person_id
  LEFT JOIN people pem   ON pem.id = p.engagement_manager_person_id
  LEFT JOIN rate_cards rc ON rc.id = c.rate_card_id
"""

WRITABLE = (
    "project_id", "workstream_id", "code", "name", "status", "opened_on",
    "closed_on", "lead_partner_person_id", "engagement_manager_person_id",
    "rate_card_id", "erp_pct", "budget_hours", "budget_fees", "external_ref",
    "is_default", "notes",
)


def list_codes(search=None, status=None, project_id=None, include_archived=False):
    clauses, params = [], []
    if not include_archived:
        clauses.append("c.archived_at IS NULL")
    if search:
        clauses.append("(c.code LIKE ? OR c.name LIKE ? OR p.name LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    if status:
        clauses.append("c.status = ?")
        params.append(status)
    if project_id:
        clauses.append("c.project_id = ?")
        params.append(project_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return get_db().execute(
        SELECT + where + " ORDER BY c.status, c.code", params
    ).fetchall()


def for_project(project_id):
    return list_codes(project_id=project_id)


def get_code(code_id):
    return get_db().execute(SELECT + " WHERE c.id = ?", (code_id,)).fetchone()


def by_code(code):
    return get_db().execute(SELECT + " WHERE c.code = ?", (code,)).fetchone()


def active_codes():
    """What the Command Center's "where do I book this hour" card reads."""
    return get_db().execute(
        SELECT + " WHERE c.status = 'active' AND c.archived_at IS NULL "
        "AND p.archived_at IS NULL ORDER BY c.is_default DESC, p.name, c.code"
    ).fetchall()


def create_code(fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE and v is not None}
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO charge_codes ({columns}) VALUES ({placeholders})", list(payload.values())
    )
    db.commit()
    return cursor.lastrowid


def update_code(code_id, fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE charge_codes SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        list(payload.values()) + [code_id],
    )
    db.commit()
    return cursor.rowcount


def set_status(code_id, status):
    db = get_db()
    closed = "closed_on = date('now')," if status == "closed" else ""
    cursor = db.execute(
        f"UPDATE charge_codes SET status = ?, {closed} updated_at = datetime('now') WHERE id = ?",
        (status, code_id),
    )
    db.commit()
    return cursor.rowcount


def summary():
    row = get_db().execute(
        "SELECT COUNT(*) AS total, "
        "  SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active, "
        "  SUM(CASE WHEN status = 'inactive' THEN 1 ELSE 0 END) AS inactive, "
        "  SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed "
        "FROM charge_codes WHERE archived_at IS NULL"
    ).fetchone()
    return row
