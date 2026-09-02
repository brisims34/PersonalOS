"""Queries behind the Command Center.

Read-only. Every number is a live query and nothing here is stored — a cached
count that drifts from the list it links to is worse than no count.

`as_of` is a parameter throughout, so the whole page can be asked "what will
this look like in March?" without a rewrite (CLAUDE.md rule 17).
"""
from app.core.database import get_db
from app.core.module_registry import NAV_GROUP_ORDER


def action_strip(as_of, self_person_id=None):
    """The counts across the top. Each one links to the list behind it (P3)."""
    from app.modules.tasks import models as task_models

    counts = task_models.counts(as_of, self_person_id)
    db = get_db()

    counts["unpriced_people"] = db.execute(
        "SELECT COUNT(*) FROM people WHERE archived_at IS NULL AND status = 'active' "
        "AND level_id IS NULL"
    ).fetchone()[0]

    counts["tenure_due"] = db.execute(
        "SELECT COUNT(*) FROM people p JOIN person_levels l ON l.id = p.level_id "
        "WHERE p.archived_at IS NULL AND p.level_start_date IS NOT NULL "
        "  AND l.auto_promote_after_months IS NOT NULL "
        "  AND date(p.level_start_date, '+' || l.auto_promote_after_months || ' months') <= ?",
        (as_of,),
    ).fetchone()[0]

    counts["at_risk_dependencies"] = db.execute(
        "SELECT COUNT(*) FROM dependencies WHERE archived_at IS NULL "
        "AND status IN ('at_risk','broken')"
    ).fetchone()[0]

    counts["dependencies_due"] = db.execute(
        "SELECT COUNT(*) FROM dependencies WHERE archived_at IS NULL "
        "AND status NOT IN ('satisfied') AND needed_by_date IS NOT NULL "
        "AND needed_by_date <= date(?, '+14 days')",
        (as_of,),
    ).fetchone()[0]

    counts["unresolved_links"] = db.execute(
        "SELECT COUNT(*) FROM note_links WHERE is_resolved = 0"
    ).fetchone()[0]

    return counts


def project_health(as_of):
    """RAG, schedule and open work per active project."""
    return get_db().execute(
        "SELECT p.id, p.name, p.client_org, p.rag_status, p.priority, p.status, "
        "       p.baseline_end, p.forecast_end, "
        "       CAST(julianday(p.forecast_end) - julianday(p.baseline_end) AS INTEGER) AS slip_days, "
        "       CAST(julianday(p.forecast_end) - julianday(?) AS INTEGER) AS days_remaining, "
        "  (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id "
        "     AND t.archived_at IS NULL AND t.status IN ('open','in_progress','blocked')) AS open_tasks, "
        "  (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id "
        "     AND t.archived_at IS NULL AND t.status IN ('open','in_progress','blocked') "
        "     AND t.due_date < ?) AS overdue_tasks, "
        "  (SELECT COUNT(*) FROM workstreams w WHERE w.project_id = p.id "
        "     AND w.archived_at IS NULL) AS workstreams, "
        "  (SELECT COUNT(*) FROM charge_codes c WHERE c.project_id = p.id "
        "     AND c.status = 'active') AS active_codes "
        "FROM projects p "
        "WHERE p.archived_at IS NULL AND p.status IN ('active','pipeline') "
        "ORDER BY CASE p.rag_status WHEN 'red' THEN 0 WHEN 'amber' THEN 1 ELSE 2 END, "
        "         overdue_tasks DESC, p.name",
        (as_of, as_of),
    ).fetchall()


def my_charge_codes(as_of, limit=12):
    """"Where do I book this hour" — answered without opening anything."""
    return get_db().execute(
        "SELECT c.id, c.code, c.name, c.is_default, p.name AS project_name, "
        "       w.name AS workstream_name, "
        "       COALESCE(em.full_name, pem.full_name) AS manager_name "
        "FROM charge_codes c JOIN projects p ON p.id = c.project_id "
        "LEFT JOIN workstreams w ON w.id = c.workstream_id "
        "LEFT JOIN people em ON em.id = c.engagement_manager_person_id "
        "LEFT JOIN people pem ON pem.id = p.engagement_manager_person_id "
        "WHERE c.status = 'active' AND c.archived_at IS NULL AND p.archived_at IS NULL "
        "  AND (c.opened_on IS NULL OR c.opened_on <= ?) "
        "  AND (c.closed_on IS NULL OR c.closed_on >= ?) "
        "ORDER BY c.is_default DESC, p.name, c.code LIMIT ?",
        (as_of, as_of, limit),
    ).fetchall()


def chase_list(as_of, limit=15):
    """Dependencies and delegated work waiting on somebody else."""
    db = get_db()
    dependencies = db.execute(
        "SELECT d.id, d.title, d.status, d.criticality, d.needed_by_date, "
        "       d.project_id, p.name AS project_name, "
        "       COALESCE(tw.name, d.external_party) AS provider, "
        "       o.full_name AS owner_name "
        "FROM dependencies d JOIN projects p ON p.id = d.project_id "
        "LEFT JOIN workstreams tw ON tw.id = d.to_workstream_id "
        "LEFT JOIN people o ON o.id = d.owner_person_id "
        "WHERE d.archived_at IS NULL AND d.status NOT IN ('satisfied') "
        "  AND (d.needed_by_date IS NULL OR d.needed_by_date <= date(?, '+21 days')) "
        "ORDER BY CASE d.status WHEN 'broken' THEN 0 WHEN 'at_risk' THEN 1 ELSE 2 END, "
        "         d.needed_by_date IS NULL, d.needed_by_date LIMIT ?",
        (as_of, limit),
    ).fetchall()

    waiting = db.execute(
        "SELECT t.id, t.title, t.due_date, t.task_type, a.full_name AS assignee_name, "
        "       p.name AS project_name "
        "FROM tasks t LEFT JOIN people a ON a.id = t.assignee_person_id "
        "LEFT JOIN projects p ON p.id = t.project_id "
        "WHERE t.archived_at IS NULL AND t.status IN ('open','in_progress','blocked') "
        "  AND t.task_type IN ('delegated','waiting_on','follow_up') "
        "ORDER BY t.due_date IS NULL, t.due_date LIMIT ?",
        (limit,),
    ).fetchall()
    return dependencies, waiting


def recent_notes(limit=8):
    return get_db().execute(
        "SELECT n.id, n.title, n.rel_path, n.mtime, r.root_key, p.name AS project_name "
        "FROM notes n JOIN vault_roots r ON r.id = n.root_id "
        "LEFT JOIN projects p ON p.id = n.project_id "
        "WHERE n.note_type IS NOT 'missing' ORDER BY n.mtime DESC LIMIT ?",
        (limit,),
    ).fetchall()


def build_progress():
    """Which modules are live. Read from the registry, never hard-coded."""
    rows = get_db().execute(
        "SELECT nav_group, module_key, label, url_prefix, is_enabled "
        "FROM module_registry ORDER BY sort_order"
    ).fetchall()

    groups = {}
    for row in rows:
        groups.setdefault(row["nav_group"], {"live": [], "pending": []})
        bucket = "live" if row["is_enabled"] else "pending"
        groups[row["nav_group"]][bucket].append(
            {"key": row["module_key"], "label": row["label"], "url": row["url_prefix"]}
        )

    ordered = [(name, groups.pop(name)) for name in NAV_GROUP_ORDER if name in groups]
    ordered.extend(sorted(groups.items()))
    live = sum(1 for r in rows if r["is_enabled"])
    return {
        "groups": ordered,
        "live_count": live,
        "total_count": len(rows),
        "pending_count": len(rows) - live,
    }


def schema_state():
    db = get_db()
    version = db.execute("PRAGMA user_version").fetchone()[0]
    applied = db.execute(
        "SELECT migration, applied_at FROM schema_migrations ORDER BY version_to DESC LIMIT 1"
    ).fetchone()
    table_count = db.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchone()["n"]
    return {
        "version": version,
        "last_migration": applied["migration"] if applied else None,
        "applied_at": applied["applied_at"] if applied else None,
        "table_count": table_count,
    }


def is_empty():
    """True when nothing has been entered yet, so the page can say what to do first."""
    db = get_db()
    for table in ("people", "projects", "tasks"):
        if db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]:
            return False
    return True
