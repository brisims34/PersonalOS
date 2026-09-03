"""All SQL for projects, workstreams, locations, work resources and dependencies.

Containment is expressed with real foreign keys — a workstream belongs to a
project, a charge code belongs to a project — because budget rollups and
utilization maths need real joins with real integrity (CLAUDE.md rule 9).
`entity_links` is for the cross-cutting relationships only.
"""
from app.core.database import get_db

PROJECT_SELECT = """
SELECT p.*,
       pf.name        AS portfolio_name,
       pf.folder_slug AS portfolio_slug,
       pf.portfolio_kind,
       lp.full_name   AS lead_partner_name,
       em.full_name   AS engagement_manager_name,
       pl.full_name   AS project_lead_name,
       rc.name        AS rate_card_name,
       (SELECT COUNT(*) FROM workstreams w
         WHERE w.project_id = p.id AND w.archived_at IS NULL)  AS workstream_count,
       (SELECT COUNT(*) FROM charge_codes c
         WHERE c.project_id = p.id AND c.archived_at IS NULL)  AS charge_code_count,
       (SELECT COUNT(*) FROM charge_codes c
         WHERE c.project_id = p.id AND c.status = 'active')    AS active_code_count
  FROM projects p
  JOIN portfolios pf ON pf.id = p.portfolio_id
  LEFT JOIN people lp     ON lp.id = p.lead_partner_person_id
  LEFT JOIN people em     ON em.id = p.engagement_manager_person_id
  LEFT JOIN people pl     ON pl.id = p.project_lead_person_id
  LEFT JOIN rate_cards rc ON rc.id = p.rate_card_id
"""

WRITABLE = (
    "portfolio_id", "name", "code", "client_org", "description", "service_offering",
    "project_type", "status", "priority", "rag_status", "baseline_start",
    "baseline_end", "forecast_start", "forecast_end", "actual_start", "actual_end",
    "rate_card_id", "erp_pct", "budget_hours", "budget_fees", "budget_expenses",
    "lead_partner_person_id", "engagement_manager_person_id",
    "project_lead_person_id", "cover_image",
)


def _filters(search=None, portfolio_id=None, status=None, project_type=None,
             priority=None, include_archived=False):
    clauses, params = [], []
    if not include_archived:
        clauses.append("p.archived_at IS NULL")
    if search:
        clauses.append("(p.name LIKE ? OR p.client_org LIKE ? OR p.code LIKE ?)")
        params.extend([f"%{search}%"] * 3)
    if portfolio_id:
        clauses.append("p.portfolio_id = ?")
        params.append(portfolio_id)
    if status:
        clauses.append("p.status = ?")
        params.append(status)
    if project_type:
        clauses.append("p.project_type = ?")
        params.append(project_type)
    if priority:
        clauses.append("p.priority = ?")
        params.append(priority)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def list_projects(limit=200, offset=0, **filters):
    where, params = _filters(**filters)
    sql = PROJECT_SELECT + where + (
        " ORDER BY CASE p.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        " p.forecast_end IS NULL, p.forecast_end, p.name LIMIT ? OFFSET ?"
    )
    return get_db().execute(sql, params + [limit, offset]).fetchall()


def count_projects(**filters):
    where, params = _filters(**filters)
    sql = "SELECT COUNT(*) AS n FROM projects p JOIN portfolios pf ON pf.id = p.portfolio_id" + where
    return get_db().execute(sql, params).fetchone()["n"]


def get_project(project_id):
    return get_db().execute(PROJECT_SELECT + " WHERE p.id = ?", (project_id,)).fetchone()


def portfolio_summary():
    return get_db().execute(
        "SELECT pf.*, "
        "  (SELECT COUNT(*) FROM projects p WHERE p.portfolio_id = pf.id "
        "   AND p.archived_at IS NULL) AS project_count, "
        "  (SELECT COUNT(*) FROM projects p WHERE p.portfolio_id = pf.id "
        "   AND p.status = 'active' AND p.archived_at IS NULL) AS active_count "
        "FROM portfolios pf WHERE pf.archived_at IS NULL ORDER BY pf.sort_order"
    ).fetchall()


def get_portfolio(portfolio_id):
    return get_db().execute(
        "SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)
    ).fetchone()


def create_project(fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE and v is not None}
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO projects ({columns}) VALUES ({placeholders})", list(payload.values())
    )
    db.commit()
    return cursor.lastrowid


def update_project(project_id, fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE projects SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        list(payload.values()) + [project_id],
    )
    db.commit()
    return cursor.rowcount


def set_folder_path(project_id, folder_path):
    db = get_db()
    db.execute("UPDATE projects SET folder_path = ? WHERE id = ?", (folder_path, project_id))
    db.commit()


def archive_project(project_id, archived=True):
    """Archive, never delete — and the folder on disk is left exactly as it is."""
    db = get_db()
    stamp = "datetime('now')" if archived else "NULL"
    cursor = db.execute(
        f"UPDATE projects SET archived_at = {stamp}, updated_at = datetime('now') WHERE id = ?",
        (project_id,),
    )
    db.commit()
    return cursor.rowcount


# --- workstreams ------------------------------------------------------------

WORKSTREAM_WRITABLE = (
    "project_id", "name", "description", "lead_person_id", "status",
    "baseline_start", "baseline_end", "forecast_start", "forecast_end",
    "budget_hours", "sort_order",
)


def workstreams(project_id, include_archived=False):
    sql = (
        "SELECT w.*, l.full_name AS lead_name, "
        "  (SELECT COUNT(*) FROM charge_codes c WHERE c.workstream_id = w.id) AS code_count "
        "FROM workstreams w LEFT JOIN people l ON l.id = w.lead_person_id "
        "WHERE w.project_id = ?"
    )
    if not include_archived:
        sql += " AND w.archived_at IS NULL"
    sql += " ORDER BY w.sort_order, w.name"
    return get_db().execute(sql, (project_id,)).fetchall()


def get_workstream(workstream_id):
    return get_db().execute(
        "SELECT w.*, l.full_name AS lead_name, p.name AS project_name, "
        "       p.folder_path AS project_folder "
        "FROM workstreams w JOIN projects p ON p.id = w.project_id "
        "LEFT JOIN people l ON l.id = w.lead_person_id WHERE w.id = ?",
        (workstream_id,),
    ).fetchone()


def create_workstream(fields):
    payload = {k: v for k, v in fields.items() if k in WORKSTREAM_WRITABLE and v is not None}
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO workstreams ({columns}) VALUES ({placeholders})", list(payload.values())
    )
    db.commit()
    return cursor.lastrowid


def update_workstream(workstream_id, fields):
    payload = {k: v for k, v in fields.items() if k in WORKSTREAM_WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE workstreams SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        list(payload.values()) + [workstream_id],
    )
    db.commit()
    return cursor.rowcount


def set_workstream_folder(workstream_id, folder_path):
    db = get_db()
    db.execute("UPDATE workstreams SET folder_path = ? WHERE id = ?",
               (folder_path, workstream_id))
    db.commit()


def workstream_tasks(workstream_id):
    """The tasks that belong to this workstream, for the workstream detail page.

    `tasks` is owned by the tasks module, but this is a read-only display
    query against a shared table (CLAUDE.md rule — no cross-module import of
    tasks/models.py, the same way app/core/ queries shared tables directly).
    """
    return get_db().execute(
        "SELECT t.id, t.title, t.status, t.due_date, "
        "       a.full_name AS assignee_name "
        "FROM tasks t LEFT JOIN people a ON a.id = t.assignee_person_id "
        "WHERE t.workstream_id = ? AND t.archived_at IS NULL "
        "ORDER BY t.due_date IS NULL, t.due_date, t.sort_order, t.title",
        (workstream_id,),
    ).fetchall()


def all_workstreams(project_id=None):
    """Every workstream labelled with its project name, for the tasks filter
    dropdown — scoped to one project when a project is already selected."""
    sql = (
        "SELECT w.id, w.name, p.name AS project_name "
        "FROM workstreams w JOIN projects p ON p.id = w.project_id "
        "WHERE w.archived_at IS NULL AND p.archived_at IS NULL"
    )
    params = []
    if project_id:
        sql += " AND w.project_id = ?"
        params.append(project_id)
    sql += " ORDER BY p.name, w.sort_order, w.name"
    return get_db().execute(sql, params).fetchall()


def archive_workstream(workstream_id, archived=True):
    """Archive, never delete — and the folder on disk is left exactly as it is."""
    db = get_db()
    stamp = "datetime('now')" if archived else "NULL"
    cursor = db.execute(
        f"UPDATE workstreams SET archived_at = {stamp}, updated_at = datetime('now') WHERE id = ?",
        (workstream_id,),
    )
    db.commit()
    return cursor.rowcount


# --- locations --------------------------------------------------------------


def locations(project_id=None):
    """Physical sites. Linked to workstreams through entity_links, since one
    site regularly serves several workstreams and several projects."""
    if project_id is None:
        return get_db().execute(
            "SELECT * FROM locations WHERE archived_at IS NULL ORDER BY name"
        ).fetchall()
    return get_db().execute(
        "SELECT l.* FROM locations l "
        "JOIN entity_links el ON el.target_type = 'location' AND el.target_id = l.id "
        "WHERE el.source_type = 'project' AND el.source_id = ? AND l.archived_at IS NULL "
        "ORDER BY l.name",
        (project_id,),
    ).fetchall()


def location_linked_to_project(project_id, location_id):
    """True only if this exact site is linked to this exact project — guards
    against a tampered or stale project_id being used to route a flash/redirect
    at an unrelated project after an edit."""
    row = get_db().execute(
        "SELECT 1 FROM entity_links WHERE source_type = 'project' AND source_id = ? "
        "AND target_type = 'location' AND target_id = ?",
        (project_id, location_id),
    ).fetchone()
    return row is not None


LOCATION_WRITABLE = (
    "name", "location_kind", "organization", "address_line1", "address_line2",
    "city", "state_province", "postal_code", "country", "building", "floor",
    "room", "access_notes", "logistics_notes", "site_contact_person_id",
    "map_url", "notes",
)


def create_location(fields):
    payload = {k: v for k, v in fields.items() if k in LOCATION_WRITABLE and v is not None}
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO locations ({columns}) VALUES ({placeholders})", list(payload.values())
    )
    db.commit()
    return cursor.lastrowid


def get_location(location_id):
    return get_db().execute(
        "SELECT l.*, p.full_name AS site_contact_name FROM locations l "
        "LEFT JOIN people p ON p.id = l.site_contact_person_id "
        "WHERE l.id = ? AND l.archived_at IS NULL",
        (location_id,),
    ).fetchone()


def update_location(location_id, fields):
    """A location's own fields — address, access notes, contact. Not the link
    to any particular project, which lives in entity_links (CLAUDE.md rule 9)."""
    payload = {k: v for k, v in fields.items() if k in LOCATION_WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE locations SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        list(payload.values()) + [location_id],
    )
    db.commit()
    return cursor.rowcount


# --- work resources ---------------------------------------------------------

RESOURCE_WRITABLE = (
    "project_id", "workstream_id", "label", "resource_kind", "resource_role",
    "path_or_url", "description", "access_notes", "owner_person_id", "sort_order",
)


def work_resources(project_id=None, workstream_id=None, include_inactive=False):
    """Active resources only by default (the pickers, the verify action). The
    project detail page passes include_inactive=True so a deactivated resource
    stays visible — with a status label — instead of vanishing with no way
    back to reactivate it."""
    clauses, params = [], []
    if not include_inactive:
        clauses.append("is_active = 1")
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if workstream_id:
        clauses.append("workstream_id = ?")
        params.append(workstream_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return get_db().execute(
        "SELECT * FROM work_resources" + where
        + " ORDER BY is_active DESC, resource_role, sort_order, label",
        params,
    ).fetchall()


def get_work_resource(resource_id):
    return get_db().execute(
        "SELECT * FROM work_resources WHERE id = ?", (resource_id,)
    ).fetchone()


def create_work_resource(fields):
    payload = {k: v for k, v in fields.items() if k in RESOURCE_WRITABLE and v is not None}
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO work_resources ({columns}) VALUES ({placeholders})",
        list(payload.values()),
    )
    db.commit()
    return cursor.lastrowid


def update_work_resource(resource_id, fields):
    # Unlike update_project(), None is dropped rather than written through:
    # resource_kind/resource_role/label/path_or_url are NOT NULL/CHECK columns,
    # and a stripped-down or forged POST omitting one must leave it as-is
    # rather than raising sqlite3.IntegrityError.
    payload = {k: v for k, v in fields.items() if k in RESOURCE_WRITABLE and v is not None}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE work_resources SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        list(payload.values()) + [resource_id],
    )
    db.commit()
    return cursor.rowcount


def set_resource_active(resource_id, active):
    """Deactivate/reactivate — never delete. Verification history and the
    activity trail both stay intact either way."""
    db = get_db()
    cursor = db.execute(
        "UPDATE work_resources SET is_active = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if active else 0, resource_id),
    )
    db.commit()
    return cursor.rowcount


def verify_work_resources(project_id):
    """Check every recorded path still exists. Records status, never contents.

    A URL cannot be checked without leaving the machine, so it is marked
    `not_verifiable` rather than guessed at (CLAUDE.md rule 1).
    """
    from pathlib import Path

    db = get_db()
    rows = db.execute(
        "SELECT id, path_or_url, resource_kind FROM work_resources "
        "WHERE project_id = ? AND is_active = 1",
        (project_id,),
    ).fetchall()

    counts = {"ok": 0, "missing": 0, "not_verifiable": 0}
    for row in rows:
        target = row["path_or_url"] or ""
        if target.lower().startswith(("http://", "https://", "mailto:", "msteams:")):
            status = "not_verifiable"
        else:
            try:
                status = "ok" if Path(target).exists() else "missing"
            except OSError:
                status = "missing"
        counts[status] += 1
        db.execute(
            "UPDATE work_resources SET verify_status = ?, last_verified_at = datetime('now') "
            "WHERE id = ?",
            (status, row["id"]),
        )
    db.commit()
    return counts


# --- dependencies -----------------------------------------------------------

DEPENDENCY_WRITABLE = (
    "project_id", "from_workstream_id", "to_workstream_id", "external_party",
    "title", "description", "dependency_type", "criticality", "needed_by_date",
    "status", "owner_person_id", "notes",
)

# Fields the dedicated edit form may change after creation. Direction
# (from/to workstream, external party) and type are load-bearing for the
# RAID union and are deliberately left fixed once logged.
DEPENDENCY_EDIT_WRITABLE = (
    "title", "description", "criticality", "needed_by_date", "owner_person_id",
)


def dependencies(project_id, include_archived=False):
    sql = (
        "SELECT d.*, "
        "       fw.name AS from_name, tw.name AS to_name, o.full_name AS owner_name "
        "FROM dependencies d "
        "LEFT JOIN workstreams fw ON fw.id = d.from_workstream_id "
        "LEFT JOIN workstreams tw ON tw.id = d.to_workstream_id "
        "LEFT JOIN people o       ON o.id = d.owner_person_id "
        "WHERE d.project_id = ?"
    )
    if not include_archived:
        sql += " AND d.archived_at IS NULL"
    sql += (
        " ORDER BY CASE d.criticality WHEN 'critical' THEN 0 WHEN 'important' THEN 1 ELSE 2 END, "
        "         d.needed_by_date IS NULL, d.needed_by_date"
    )
    return get_db().execute(sql, (project_id,)).fetchall()


def get_dependency(dependency_id):
    return get_db().execute(
        "SELECT d.*, p.name AS project_name, "
        "       fw.name AS from_name, tw.name AS to_name, o.full_name AS owner_name "
        "FROM dependencies d "
        "JOIN projects p          ON p.id = d.project_id "
        "LEFT JOIN workstreams fw ON fw.id = d.from_workstream_id "
        "LEFT JOIN workstreams tw ON tw.id = d.to_workstream_id "
        "LEFT JOIN people o       ON o.id = d.owner_person_id "
        "WHERE d.id = ?",
        (dependency_id,),
    ).fetchone()


def workstream_dependencies(workstream_id):
    """Inbound (this workstream needs) and outbound (others need this one)."""
    db = get_db()
    inbound = db.execute(
        "SELECT d.*, tw.name AS to_name FROM dependencies d "
        "LEFT JOIN workstreams tw ON tw.id = d.to_workstream_id "
        "WHERE d.from_workstream_id = ? AND d.archived_at IS NULL ORDER BY d.needed_by_date",
        (workstream_id,),
    ).fetchall()
    outbound = db.execute(
        "SELECT d.*, fw.name AS from_name FROM dependencies d "
        "LEFT JOIN workstreams fw ON fw.id = d.from_workstream_id "
        "WHERE d.to_workstream_id = ? AND d.archived_at IS NULL ORDER BY d.needed_by_date",
        (workstream_id,),
    ).fetchall()
    return inbound, outbound


def create_dependency(fields):
    payload = {k: v for k, v in fields.items() if k in DEPENDENCY_WRITABLE and v is not None}
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO dependencies ({columns}) VALUES ({placeholders})", list(payload.values())
    )
    db.commit()
    return cursor.lastrowid


def set_dependency_status(dependency_id, status):
    db = get_db()
    cursor = db.execute(
        "UPDATE dependencies SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, dependency_id),
    )
    db.commit()
    return cursor.rowcount


def update_dependency(dependency_id, fields):
    payload = {k: v for k, v in fields.items() if k in DEPENDENCY_EDIT_WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE dependencies SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        list(payload.values()) + [dependency_id],
    )
    db.commit()
    return cursor.rowcount


def archive_dependency(dependency_id, archived=True):
    """Archive, never delete — status history and links stay on the row."""
    db = get_db()
    stamp = "datetime('now')" if archived else "NULL"
    cursor = db.execute(
        f"UPDATE dependencies SET archived_at = {stamp}, updated_at = datetime('now') WHERE id = ?",
        (dependency_id,),
    )
    db.commit()
    return cursor.rowcount


# --- team -------------------------------------------------------------------


def project_team(project_id):
    """People linked to the project, plus whoever holds a named role on it."""
    return get_db().execute(
        "SELECT DISTINCT pe.id, pe.full_name, pe.email, pe.job_title, "
        "       l.label AS level_label, el.link_label "
        "FROM entity_links el "
        "JOIN people pe ON pe.id = el.target_id "
        "LEFT JOIN person_levels l ON l.id = pe.level_id "
        "WHERE el.source_type = 'project' AND el.source_id = ? AND el.target_type = 'person' "
        "  AND pe.archived_at IS NULL "
        "ORDER BY l.sort_order DESC, pe.full_name",
        (project_id,),
    ).fetchall()


def workstream_team(workstream_id):
    """People linked to the workstream, plus whoever holds a named role on it.

    Mirrors project_team() with source_type='workstream' — the same free-text
    entity_links role vocabulary as projects, so the two features converge in
    behavior once the parallel project-Team-tab fixes land.
    """
    return get_db().execute(
        "SELECT DISTINCT pe.id, pe.full_name, pe.email, pe.job_title, "
        "       l.label AS level_label, el.link_label "
        "FROM entity_links el "
        "JOIN people pe ON pe.id = el.target_id "
        "LEFT JOIN person_levels l ON l.id = pe.level_id "
        "WHERE el.source_type = 'workstream' AND el.source_id = ? AND el.target_type = 'person' "
        "  AND pe.archived_at IS NULL "
        "ORDER BY l.sort_order DESC, pe.full_name",
        (workstream_id,),
    ).fetchall()
