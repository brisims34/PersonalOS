"""Portfolios — the partition that makes "everything is a project" work.

Client engagements, internal initiatives, innovation work and training are all
rows in `projects`. The portfolio is what separates them, and it is also the
top level of the notes vault folder tree.
"""
from app.core.database import get_db

WRITABLE = ("name", "portfolio_kind", "description", "folder_slug", "sort_order")


def list_portfolios(include_archived=False):
    sql = (
        "SELECT pf.*, "
        "  (SELECT COUNT(*) FROM projects p WHERE p.portfolio_id = pf.id "
        "   AND p.archived_at IS NULL) AS project_count, "
        "  (SELECT COUNT(*) FROM projects p WHERE p.portfolio_id = pf.id "
        "   AND p.status = 'active' AND p.archived_at IS NULL) AS active_count, "
        "  (SELECT COUNT(*) FROM charge_codes c JOIN projects p ON p.id = c.project_id "
        "   WHERE p.portfolio_id = pf.id AND c.status = 'active') AS active_codes "
        "FROM portfolios pf"
    )
    if not include_archived:
        sql += " WHERE pf.archived_at IS NULL"
    sql += " ORDER BY pf.sort_order, pf.name"
    return get_db().execute(sql).fetchall()


def get_portfolio(portfolio_id):
    return get_db().execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()


def create_portfolio(fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE and v is not None}
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO portfolios ({columns}) VALUES ({placeholders})", list(payload.values())
    )
    db.commit()
    return cursor.lastrowid


def update_portfolio(portfolio_id, fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE portfolios SET {assignments} WHERE id = ?",
        list(payload.values()) + [portfolio_id],
    )
    db.commit()
    return cursor.rowcount
