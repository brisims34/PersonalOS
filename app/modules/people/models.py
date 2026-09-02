"""All SQL for the people module.

`manager_person_id` is the **administrative** reporting line from the
directory. It is deliberately not the counselee relationship, which is the
performance line and lives in `performance_tracks` (Phase 17). People
routinely report to one person and are counselled by another; collapsing the
two would corrupt both the org chart and the performance module.
"""
from app.core.database import get_db

MAX_CHAIN_DEPTH = 20  # cycle guard — real directory data does contain loops

SORTABLE = {
    "name": "p.last_name, p.first_name",
    "email": "p.email",
    "title": "p.job_title",
    "level": "l.sort_order DESC, p.last_name",
    "company": "p.company, p.last_name",
    "city": "p.city, p.last_name",
    "manager": "m.last_name, p.last_name",
}

_SELECT = """
SELECT p.*,
       l.label      AS level_label,
       l.level_key  AS level_key,
       l.sort_order AS level_sort,
       m.full_name  AS manager_name,
       m.id         AS manager_id
  FROM people p
  LEFT JOIN person_levels l ON l.id = p.level_id
  LEFT JOIN people m        ON m.id = p.manager_person_id
"""


def _filter_clause(search=None, level_id=None, company=None, function=None,
                   import_source=None, include_archived=False, unmapped=False,
                   no_manager=False):
    """Fixed clause text only; every value is bound (CLAUDE.md rule 2)."""
    clauses, params = [], []
    if not include_archived:
        clauses.append("p.archived_at IS NULL")
    if search:
        clauses.append(
            "(p.full_name LIKE ? OR p.email LIKE ? OR p.job_title LIKE ? OR p.city LIKE ?)"
        )
        params.extend([f"%{search}%"] * 4)
    if level_id:
        clauses.append("p.level_id = ?")
        params.append(level_id)
    if company:
        clauses.append("p.company = ?")
        params.append(company)
    if function:
        clauses.append("p.function = ?")
        params.append(function)
    if import_source:
        clauses.append("p.import_source = ?")
        params.append(import_source)
    if unmapped:
        clauses.append("p.level_id IS NULL")
    if no_manager:
        clauses.append("p.manager_person_id IS NULL")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def list_people(sort="name", limit=100, offset=0, **filters):
    where, params = _filter_clause(**filters)
    order = SORTABLE.get(sort, SORTABLE["name"])
    sql = _SELECT + where + f" ORDER BY {order} LIMIT ? OFFSET ?"
    return get_db().execute(sql, params + [limit, offset]).fetchall()


def count_people(**filters):
    where, params = _filter_clause(**filters)
    sql = (
        "SELECT COUNT(*) AS n FROM people p "
        "LEFT JOIN person_levels l ON l.id = p.level_id "
        "LEFT JOIN people m ON m.id = p.manager_person_id" + where
    )
    return get_db().execute(sql, params).fetchone()["n"]


def get_person(person_id):
    return get_db().execute(_SELECT + " WHERE p.id = ?", (person_id,)).fetchone()


def by_email(email):
    if not email:
        return None
    return get_db().execute(
        _SELECT + " WHERE lower(p.email) = lower(?)", (email,)
    ).fetchone()


def filter_values():
    db = get_db()
    return {
        "companies": [r[0] for r in db.execute(
            "SELECT DISTINCT company FROM people WHERE company IS NOT NULL ORDER BY company")],
        "functions": [r[0] for r in db.execute(
            "SELECT DISTINCT function FROM people WHERE function IS NOT NULL ORDER BY function")],
        "levels": db.execute(
            "SELECT id, label FROM person_levels ORDER BY sort_order DESC").fetchall(),
        "sources": [r[0] for r in db.execute(
            "SELECT DISTINCT import_source FROM people ORDER BY import_source")],
    }


def roster_summary():
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) AS total, "
        "  SUM(CASE WHEN level_id IS NULL THEN 1 ELSE 0 END) AS unmapped, "
        "  SUM(CASE WHEN manager_person_id IS NULL THEN 1 ELSE 0 END) AS no_manager, "
        "  SUM(CASE WHEN import_source = 'gal_manager_chain' THEN 1 ELSE 0 END) AS chain_pulled "
        "FROM people WHERE archived_at IS NULL"
    ).fetchone()
    by_level = db.execute(
        "SELECT l.label, l.sort_order, COUNT(p.id) AS n "
        "FROM person_levels l LEFT JOIN people p "
        "  ON p.level_id = l.id AND p.archived_at IS NULL "
        "GROUP BY l.id HAVING n > 0 ORDER BY l.sort_order DESC"
    ).fetchall()
    return {"totals": row, "by_level": by_level}


# --- writes -----------------------------------------------------------------

WRITABLE = (
    "external_ref", "first_name", "last_name", "preferred_name", "email", "upn",
    "company", "department", "job_title", "level_id", "level_start_date",
    "last_promoted_on", "function", "relationship_type", "status",
    "business_phone", "home_phone", "mobile_phone", "city", "state_province",
    "location", "manager_email", "manager_person_id", "import_source",
    "outlook_entry_id", "smartsheet_row_id", "notes", "strengths",
    "development_areas", "tags", "last_interaction_date", "next_follow_up_date",
)


def _full_name(fields):
    first = (fields.get("preferred_name") or fields.get("first_name") or "").strip()
    last = (fields.get("last_name") or "").strip()
    return " ".join(part for part in (first, last) if part) or "Unnamed"


def create_person(fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE}
    if payload.get("email"):
        # SMTP local parts are case-insensitive everywhere that matters, and the
        # seed file mixes cases in the same column.
        payload["email"] = payload["email"].strip().lower()
    payload["full_name"] = _full_name(payload)

    # Column names come from the WRITABLE constant above — developer constants,
    # never request data. Every value is bound (CLAUDE.md rule 2).
    columns = ", ".join(payload)
    placeholders = ", ".join("?" for _ in payload)
    db = get_db()
    cursor = db.execute(
        f"INSERT INTO people ({columns}) VALUES ({placeholders})", list(payload.values())
    )
    db.commit()
    return cursor.lastrowid


def update_person(person_id, fields):
    payload = {k: v for k, v in fields.items() if k in WRITABLE}
    if not payload:
        return 0
    if payload.get("email"):
        payload["email"] = payload["email"].strip().lower()

    existing = get_person(person_id)
    merged = {
        "first_name": existing["first_name"],
        "last_name": existing["last_name"],
        "preferred_name": existing["preferred_name"],
    }
    merged.update({k: v for k, v in payload.items() if k in merged})
    payload["full_name"] = _full_name(merged)

    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE people SET {assignments}, updated_at = datetime('now') WHERE id = ?",
        list(payload.values()) + [person_id],
    )
    db.commit()
    return cursor.rowcount


def archive_person(person_id, archived=True):
    """Archive or restore. Never deletes — the row and its links survive (P5)."""
    db = get_db()
    stamp = "datetime('now')" if archived else "NULL"
    cursor = db.execute(
        f"UPDATE people SET archived_at = {stamp}, updated_at = datetime('now') WHERE id = ?",
        (person_id,),
    )
    db.commit()
    return cursor.rowcount


# --- level history ----------------------------------------------------------


def level_history(person_id):
    return get_db().execute(
        "SELECT h.*, l.label AS level_label, l.level_key "
        "FROM person_level_history h JOIN person_levels l ON l.id = h.level_id "
        "WHERE h.person_id = ? ORDER BY h.effective_from DESC, h.id DESC",
        (person_id,),
    ).fetchall()


def record_level_change(person_id, level_id, effective_from, reason="promotion", note=None):
    """Write a history row and maintain the denormalised clocks on `people`.

    `level_start_date` moves for any level change. `last_promoted_on` moves
    only for an actual promotion — a `correction` is a data fix and must not
    read as a promotion or reset somebody's tenure clock
    (DESIGN_DECISIONS.md F7).
    """
    db = get_db()
    db.execute(
        "UPDATE person_level_history SET effective_to = date(?, '-1 day') "
        "WHERE person_id = ? AND effective_to IS NULL AND effective_from < ?",
        (effective_from, person_id, effective_from),
    )
    cursor = db.execute(
        "INSERT INTO person_level_history (person_id, level_id, effective_from, reason, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (person_id, level_id, effective_from, reason, note),
    )
    if reason == "promotion":
        db.execute(
            "UPDATE people SET level_id = ?, level_start_date = ?, last_promoted_on = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (level_id, effective_from, effective_from, person_id),
        )
    else:
        db.execute(
            "UPDATE people SET level_id = ?, level_start_date = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (level_id, effective_from, person_id),
        )
    db.commit()
    return cursor.lastrowid


# --- capacity and disposition -----------------------------------------------


def capacity_rows(person_id):
    return get_db().execute(
        "SELECT * FROM person_capacity WHERE person_id = ? ORDER BY effective_from DESC",
        (person_id,),
    ).fetchall()


def add_capacity(person_id, weekly_hours, fte, effective_from, note=None):
    db = get_db()
    db.execute(
        "UPDATE person_capacity SET effective_to = date(?, '-1 day') "
        "WHERE person_id = ? AND effective_to IS NULL AND effective_from < ?",
        (effective_from, person_id, effective_from),
    )
    cursor = db.execute(
        "INSERT INTO person_capacity (person_id, weekly_hours, fte, effective_from, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (person_id, weekly_hours, fte, effective_from, note),
    )
    db.commit()
    return cursor.lastrowid


def status_events(person_id, as_of=None):
    sql = "SELECT * FROM person_status_events WHERE person_id = ?"
    params = [person_id]
    if as_of:
        sql += " AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)"
        params.extend([as_of, as_of])
    sql += " ORDER BY start_date DESC"
    return get_db().execute(sql, params).fetchall()


def add_status_event(person_id, disposition, start_date, end_date=None,
                     detail=None, source="manual"):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO person_status_events "
        "(person_id, disposition, start_date, end_date, detail, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (person_id, disposition, start_date, end_date, detail, source),
    )
    db.commit()
    return cursor.lastrowid


def disposition_at(person_id, as_of):
    """The disposition in force on a date, or 'available' if nothing says otherwise."""
    row = get_db().execute(
        "SELECT disposition, detail, end_date FROM person_status_events "
        "WHERE person_id = ? AND start_date <= ? AND (end_date IS NULL OR end_date >= ?) "
        "ORDER BY start_date DESC LIMIT 1",
        (person_id, as_of, as_of),
    ).fetchone()
    return row


# --- org chart --------------------------------------------------------------


def chain_up(person_id):
    """Everyone this person reports to, in order, bounded against cycles."""
    return get_db().execute(
        """
        WITH RECURSIVE chain(id, full_name, email, job_title, manager_person_id, depth, path) AS (
            SELECT p.id, p.full_name, p.email, p.job_title, p.manager_person_id, 0,
                   ',' || p.id || ','
              FROM people p WHERE p.id = ?
            UNION ALL
            SELECT m.id, m.full_name, m.email, m.job_title, m.manager_person_id,
                   c.depth + 1, c.path || m.id || ','
              FROM people m JOIN chain c ON m.id = c.manager_person_id
             WHERE c.depth < ?
               AND c.path NOT LIKE '%,' || m.id || ',%'
        )
        SELECT * FROM chain WHERE depth > 0 ORDER BY depth
        """,
        (person_id, MAX_CHAIN_DEPTH),
    ).fetchall()


def downline(person_id, max_depth=MAX_CHAIN_DEPTH):
    """Everyone beneath this person, at every level."""
    return get_db().execute(
        """
        WITH RECURSIVE tree(id, full_name, email, job_title, manager_person_id, depth, path) AS (
            SELECT p.id, p.full_name, p.email, p.job_title, p.manager_person_id, 0,
                   ',' || p.id || ','
              FROM people p WHERE p.id = ?
            UNION ALL
            SELECT r.id, r.full_name, r.email, r.job_title, r.manager_person_id,
                   t.depth + 1, t.path || r.id || ','
              FROM people r JOIN tree t ON r.manager_person_id = t.id
             WHERE t.depth < ?
               AND r.archived_at IS NULL
               AND t.path NOT LIKE '%,' || r.id || ',%'
        )
        SELECT * FROM tree WHERE depth > 0 ORDER BY depth, full_name
        """,
        (person_id, max_depth),
    ).fetchall()


def direct_reports(person_id):
    return get_db().execute(
        "SELECT p.id, p.full_name, p.email, p.job_title, l.label AS level_label "
        "FROM people p LEFT JOIN person_levels l ON l.id = p.level_id "
        "WHERE p.manager_person_id = ? AND p.archived_at IS NULL "
        "ORDER BY l.sort_order DESC, p.full_name",
        (person_id,),
    ).fetchall()


def span_of_control():
    """Managers by direct and total downline size."""
    return get_db().execute(
        "SELECT m.id, m.full_name, m.job_title, l.label AS level_label, "
        "       COUNT(p.id) AS direct_reports "
        "FROM people m "
        "JOIN people p ON p.manager_person_id = m.id AND p.archived_at IS NULL "
        "LEFT JOIN person_levels l ON l.id = m.level_id "
        "WHERE m.archived_at IS NULL "
        "GROUP BY m.id ORDER BY direct_reports DESC, m.full_name"
    ).fetchall()


def roots():
    """People with no manager — the tops of the tree, and the gaps."""
    return get_db().execute(
        "SELECT p.id, p.full_name, p.job_title, p.manager_email, "
        "       (SELECT COUNT(*) FROM people r WHERE r.manager_person_id = p.id "
        "        AND r.archived_at IS NULL) AS report_count "
        "FROM people p WHERE p.manager_person_id IS NULL AND p.archived_at IS NULL "
        "ORDER BY report_count DESC, p.full_name"
    ).fetchall()


def resolve_manager_links():
    """Match `manager_email` to a person and set `manager_person_id`.

    Returns (linked, unresolved_emails). Does not fetch anybody from the GAL —
    that is the Phase 1 chain walk, which runs as a queued job because it is
    many COM round trips.
    """
    db = get_db()
    cursor = db.execute(
        "UPDATE people SET manager_person_id = ("
        "  SELECT m.id FROM people m WHERE lower(m.email) = lower(people.manager_email)"
        ") WHERE manager_email IS NOT NULL AND manager_email <> '' "
        "  AND manager_person_id IS NULL "
        "  AND EXISTS (SELECT 1 FROM people m WHERE lower(m.email) = lower(people.manager_email))"
    )
    db.commit()
    unresolved = db.execute(
        "SELECT DISTINCT manager_email FROM people "
        "WHERE manager_email IS NOT NULL AND manager_email <> '' "
        "  AND manager_person_id IS NULL ORDER BY manager_email"
    ).fetchall()
    return cursor.rowcount, [r["manager_email"] for r in unresolved]


# --- job title map ----------------------------------------------------------


def title_map():
    return get_db().execute(
        "SELECT j.*, l.label AS level_label, l.level_key, l.sort_order, "
        "       (SELECT COUNT(*) FROM people p WHERE p.job_title = j.job_title "
        "        AND p.archived_at IS NULL) AS people_count "
        "FROM job_title_map j JOIN person_levels l ON l.id = j.level_id "
        "ORDER BY l.sort_order DESC, j.job_title"
    ).fetchall()


def unmapped_titles():
    """Titles in the roster with no mapping — these price at nothing."""
    return get_db().execute(
        "SELECT p.job_title, COUNT(*) AS n FROM people p "
        "WHERE p.archived_at IS NULL AND p.job_title IS NOT NULL "
        "  AND NOT EXISTS (SELECT 1 FROM job_title_map j WHERE j.job_title = p.job_title) "
        "GROUP BY p.job_title ORDER BY n DESC"
    ).fetchall()


def set_title_mapping(map_id, level_id, function=None, is_specialist=0):
    db = get_db()
    cursor = db.execute(
        "UPDATE job_title_map SET level_id = ?, function = ?, is_specialist = ? WHERE id = ?",
        (level_id, function, 1 if is_specialist else 0, map_id),
    )
    db.commit()
    return cursor.rowcount


def apply_title_map(only_unmapped=True):
    """Push job_title_map onto people. Returns how many rows changed."""
    db = get_db()
    condition = " AND p.level_id IS NULL" if only_unmapped else ""
    cursor = db.execute(
        "UPDATE people AS p SET "
        "  level_id = (SELECT j.level_id FROM job_title_map j WHERE j.job_title = p.job_title), "
        "  function = COALESCE("
        "    (SELECT j.function FROM job_title_map j WHERE j.job_title = p.job_title), p.function), "
        "  updated_at = datetime('now') "
        "WHERE EXISTS (SELECT 1 FROM job_title_map j WHERE j.job_title = p.job_title)"
        + condition
    )
    db.commit()
    return cursor.rowcount
