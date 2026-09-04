"""Rate resolution — the single source of budget truth.

Every hours-to-money calculation in the application goes through
`resolve_rates()` (CLAUDE.md rule 8). That is what keeps plan and actual
priced identically, and what makes a promotion mid-engagement reprice
correctly without anybody touching a spreadsheet.

See docs/FINANCIAL_MODEL.md §2 for the full chain and the worked example.
"""
from collections import namedtuple

from app.core.database import get_db

ResolvedRates = namedtuple(
    "ResolvedRates",
    "standard_rate erp_pct engagement_rate cost_rate source level_id level_label is_priced",
)

# Where the numbers came from, carried through onto the row that stores them.
SOURCE_OVERRIDE = "person_override"
SOURCE_CARD = "rate_card"
SOURCE_DEFAULT_CARD = "default_card"
SOURCE_UNPRICED = "unpriced"


def _effective(sql_alias, date_param="?"):
    """The effective-dated window clause used by every lookup here."""
    return (
        f"{sql_alias}.effective_from <= {date_param} "
        f"AND ({sql_alias}.effective_to IS NULL OR {sql_alias}.effective_to >= {date_param})"
    )


def level_at(person_id, as_of):
    """The person's level on a given date.

    `person_level_history` is authoritative — two people with the same job
    title bill differently depending on when they reached it. Falls back to
    `people.level_id` when no history exists, which is the normal state
    straight after a spreadsheet import.
    """
    db = get_db()
    row = db.execute(
        "SELECT h.level_id, l.level_key, l.label "
        "FROM person_level_history h JOIN person_levels l ON l.id = h.level_id "
        f"WHERE h.person_id = ? AND {_effective('h')} "
        "ORDER BY h.effective_from DESC, h.id DESC LIMIT 1",
        (person_id, as_of, as_of),
    ).fetchone()
    if row:
        return row["level_id"], row["level_key"], row["label"]

    row = db.execute(
        "SELECT p.level_id, l.level_key, l.label "
        "FROM people p LEFT JOIN person_levels l ON l.id = p.level_id "
        "WHERE p.id = ?",
        (person_id,),
    ).fetchone()
    if row and row["level_id"]:
        return row["level_id"], row["level_key"], row["label"]
    return None, None, None


def resolve_rates(person_id, work_date, project_id=None, charge_code_id=None,
                  rate_card_id=None, erp_pct=None):
    """Return a ResolvedRates for one person on one date.

    All four numbers are returned rather than just the final one, because a
    budget line reading "$500 standard x 85% ERP = $425" is auditable and a
    bare $425 is not. Callers snapshot all four onto the row they write.

    `work_date` is always supplied by the caller — no function here calls
    date.today() (CLAUDE.md rule 17).
    """
    db = get_db()
    card_id, resolved_erp = _resolve_card_and_erp(
        project_id, charge_code_id, rate_card_id, erp_pct
    )
    level_id, _level_key, level_label = level_at(person_id, work_date)

    # 1. A person-specific override wins outright. This is how a contractor,
    #    who has no rate card row at all, gets priced.
    override = db.execute(
        "SELECT bill_rate, cost_rate FROM person_rate_overrides o "
        f"WHERE o.person_id = ? AND {_effective('o')} "
        "AND (o.rate_card_id IS NULL OR o.rate_card_id = ?) "
        "ORDER BY o.rate_card_id IS NULL, o.effective_from DESC LIMIT 1",
        (person_id, work_date, work_date, card_id),
    ).fetchone()
    if override and override["bill_rate"] is not None:
        return _build(override, resolved_erp, SOURCE_OVERRIDE, level_id, level_label)

    if level_id is None:
        return _unpriced(resolved_erp, None, None)

    # 2. The card in force for this project or charge code.
    if card_id:
        entry = db.execute(
            "SELECT bill_rate, cost_rate FROM rate_card_entries e "
            f"WHERE e.rate_card_id = ? AND e.level_id = ? AND {_effective('e')} "
            "ORDER BY e.effective_from DESC LIMIT 1",
            (card_id, level_id, work_date, work_date),
        ).fetchone()
        if entry and entry["bill_rate"] is not None:
            return _build(entry, resolved_erp, SOURCE_CARD, level_id, level_label)

    # 3. The default card for the person's company. Company scopes the card
    #    because offshore cost rates differ from US rates by a large multiple,
    #    and mis-scoping understates cost on every blended engagement.
    company = db.execute("SELECT company FROM people WHERE id = ?", (person_id,)).fetchone()
    fallback = db.execute(
        "SELECT e.bill_rate, e.cost_rate FROM rate_card_entries e "
        "JOIN rate_cards c ON c.id = e.rate_card_id "
        "WHERE c.is_default = 1 AND c.archived_at IS NULL AND e.level_id = ? "
        f"AND {_effective('e')} "
        "AND (c.company = ? OR c.company IS NULL) "
        "ORDER BY c.company IS NULL, e.effective_from DESC LIMIT 1",
        (level_id, work_date, work_date, company["company"] if company else None),
    ).fetchone()
    if fallback and fallback["bill_rate"] is not None:
        return _build(fallback, resolved_erp, SOURCE_DEFAULT_CARD, level_id, level_label)

    # 4. Nothing found. None, never zero — a zero that looks like a real rate
    #    is far more dangerous than a visible gap (DESIGN_DECISIONS.md F1).
    return _unpriced(resolved_erp, level_id, level_label)


def _resolve_card_and_erp(project_id, charge_code_id, rate_card_id, erp_pct):
    """Charge code overrides project; an explicit argument overrides both."""
    db = get_db()
    card_id, resolved_erp = rate_card_id, erp_pct

    if charge_code_id and (card_id is None or resolved_erp is None):
        code = db.execute(
            "SELECT rate_card_id, erp_pct, project_id FROM charge_codes WHERE id = ?",
            (charge_code_id,),
        ).fetchone()
        if code:
            card_id = card_id or code["rate_card_id"]
            if resolved_erp is None:
                resolved_erp = code["erp_pct"]
            project_id = project_id or code["project_id"]

    if project_id and (card_id is None or resolved_erp is None):
        project = db.execute(
            "SELECT rate_card_id, erp_pct FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project:
            card_id = card_id or project["rate_card_id"]
            if resolved_erp is None:
                resolved_erp = project["erp_pct"]

    # 100 means full standard rate. ERP is a discount, never an uplift default.
    return card_id, 100.0 if resolved_erp is None else float(resolved_erp)


def _build(row, erp, source, level_id, level_label):
    standard = row["bill_rate"]
    cost = row["cost_rate"]
    engagement = None if standard is None else round(standard * erp / 100.0, 2)
    return ResolvedRates(
        standard_rate=standard,
        erp_pct=erp,
        engagement_rate=engagement,
        # ERP is a realization concept on the billing side. Applying it to cost
        # would inflate margin on every engagement, and the error would present
        # as good news (DESIGN_DECISIONS.md F6).
        cost_rate=cost,
        source=source,
        level_id=level_id,
        level_label=level_label,
        is_priced=engagement is not None,
    )


def _unpriced(erp, level_id, level_label):
    return ResolvedRates(None, erp, None, None, SOURCE_UNPRICED, level_id, level_label, False)


def price(hours, rates):
    """(revenue, cost) for a number of hours, or (None, None) if unpriced."""
    if not rates.is_priced or hours is None:
        return None, None
    revenue = round(hours * rates.engagement_rate, 2)
    cost = None if rates.cost_rate is None else round(hours * rates.cost_rate, 2)
    return revenue, cost


# --- tenure transitions -----------------------------------------------------


def tenure_transitions_due(as_of, within_days=0):
    """People at or past their tenure threshold on `as_of`.

    Flagged, never applied — a level change reprices every subsequent hour
    (DESIGN_DECISIONS.md F8). But not flagging is the worse failure: the person
    keeps billing at the junior rate and nothing announces it.
    """
    horizon = f"+{int(within_days)} days"
    return get_db().execute(
        "SELECT p.id, p.full_name, p.email, p.level_start_date, p.last_promoted_on, "
        "       l.label AS current_level, l.auto_promote_after_months, "
        "       n.label AS next_level, n.id AS next_level_id, "
        "       date(p.level_start_date, '+' || l.auto_promote_after_months || ' months') AS due_on, "
        "       CAST(julianday(?) - julianday(date(p.level_start_date, "
        "            '+' || l.auto_promote_after_months || ' months')) AS INTEGER) AS days_over "
        "FROM people p "
        "JOIN person_levels l ON l.id = p.level_id "
        "JOIN person_levels n ON n.id = l.auto_promote_to_level_id "
        "WHERE p.archived_at IS NULL AND p.status = 'active' "
        "  AND p.level_start_date IS NOT NULL "
        "  AND l.auto_promote_after_months IS NOT NULL "
        "  AND date(p.level_start_date, '+' || l.auto_promote_after_months || ' months') "
        "      <= date(?, ?) "
        "ORDER BY due_on",
        (as_of, as_of, horizon),
    ).fetchall()


def unpriced_people(as_of):
    """Active people who would price as unpriced today. A gap, made visible."""
    rows = get_db().execute(
        "SELECT p.id, p.full_name, p.email, p.company, p.job_title, "
        "       l.label AS level_label, l.level_key "
        "FROM people p LEFT JOIN person_levels l ON l.id = p.level_id "
        "WHERE p.archived_at IS NULL AND p.status = 'active' "
        "ORDER BY p.full_name"
    ).fetchall()
    unpriced = []
    for row in rows:
        if not resolve_rates(row["id"], as_of).is_priced:
            unpriced.append(row)
    return unpriced


# --- rate card reads --------------------------------------------------------


def all_cards(include_archived=False):
    sql = (
        "SELECT c.*, p.name AS project_name, "
        "       (SELECT COUNT(*) FROM rate_card_entries e WHERE e.rate_card_id = c.id) AS entry_count "
        "FROM rate_cards c LEFT JOIN projects p ON p.id = c.project_id"
    )
    if not include_archived:
        sql += " WHERE c.archived_at IS NULL"
    sql += " ORDER BY c.is_default DESC, c.scope, c.name"
    return get_db().execute(sql).fetchall()


def card(card_id):
    return get_db().execute(
        "SELECT c.*, p.name AS project_name FROM rate_cards c "
        "LEFT JOIN projects p ON p.id = c.project_id WHERE c.id = ?",
        (card_id,),
    ).fetchone()


def card_entries(card_id):
    return get_db().execute(
        "SELECT e.*, l.label AS level_label, l.level_key, l.sort_order "
        "FROM rate_card_entries e JOIN person_levels l ON l.id = e.level_id "
        "WHERE e.rate_card_id = ? ORDER BY e.effective_from DESC, l.sort_order",
        (card_id,),
    ).fetchall()


def levels(on_ladder_only=False, include_archived=False):
    """The ladder. Archived levels are excluded unless asked for.

    An archived level is retired, not deleted: it disappears from pickers
    while every rate-card entry and history row referencing it keeps
    pricing. Callers that display an existing assignment need
    include_archived, or somebody's level vanishes from its own picker.
    """
    clauses = []
    if on_ladder_only:
        clauses.append("is_on_ladder = 1")
    if not include_archived:
        clauses.append("archived_at IS NULL")

    sql = "SELECT * FROM person_levels"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY sort_order"
    return get_db().execute(sql).fetchall()


def list_levels():
    """The whole ladder, archived rows included. For the levels screen."""
    return get_db().execute(
        "SELECT * FROM person_levels ORDER BY sort_order DESC"
    ).fetchall()


def level_usage(level_id):
    """What would break if this level went away.

    Shown before any destructive action, and each count links to its rows on
    the screen, so "128 people" is checkable rather than a number to trust.
    """
    db = get_db()
    return {
        key: db.execute(sql, (level_id,)).fetchone()["n"]
        for key, sql in (
            ("people", "SELECT COUNT(*) AS n FROM people WHERE level_id = ?"),
            ("rate_entries",
             "SELECT COUNT(*) AS n FROM rate_card_entries WHERE level_id = ?"),
            ("title_maps",
             "SELECT COUNT(*) AS n FROM job_title_map WHERE level_id = ?"),
            ("history",
             "SELECT COUNT(*) AS n FROM person_level_history WHERE level_id = ?"),
        )
    }


def label_or_order_taken(label, sort_order, exclude_id=None):
    """Which uniqueness rule this would break, or None.

    Label and sort order carry the ladder's meaning now that level_key is
    retired, so two live levels sharing either one would leave "the level
    above Manager" with no defined answer.
    """
    db = get_db()
    clash = db.execute(
        "SELECT label FROM person_levels "
        "WHERE archived_at IS NULL AND lower(label) = lower(?) AND id IS NOT ?",
        (label, exclude_id),
    ).fetchone()
    if clash:
        return f"another level is already called {clash['label']}"

    clash = db.execute(
        "SELECT label FROM person_levels "
        "WHERE archived_at IS NULL AND sort_order = ? AND id IS NOT ?",
        (sort_order, exclude_id),
    ).fetchone()
    if clash:
        return f"{clash['label']} already sorts at {sort_order}"
    return None


def create_level(label, sort_order, is_on_ladder=1):
    """Insert a level. The row id is the identifier; level_key is filled and
    then never read — it exists only to satisfy a UNIQUE NOT NULL column that
    SQLite will not let us drop."""
    from app.core.paths import safe_slug

    db = get_db()
    cursor = db.execute(
        "INSERT INTO person_levels (level_key, label, sort_order, is_on_ladder) "
        "VALUES (?, ?, ?, ?)",
        (f"pending-{safe_slug(label)}-{sort_order}", label, sort_order, is_on_ladder),
    )
    level_id = cursor.lastrowid
    db.execute("UPDATE person_levels SET level_key = ? WHERE id = ?",
               (f"{safe_slug(label)}-{level_id}", level_id))
    db.commit()
    return level_id


LEVEL_WRITABLE = ("label", "sort_order", "is_on_ladder",
                  "auto_promote_to_level_id", "auto_promote_after_months")


def update_level(level_id, fields):
    payload = {k: v for k, v in fields.items() if k in LEVEL_WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE person_levels SET {assignments} WHERE id = ?",
        list(payload.values()) + [level_id],
    )
    db.commit()
    return cursor.rowcount


def set_level_archived(level_id, archived=True):
    db = get_db()
    stamp = "datetime('now')" if archived else "NULL"
    cursor = db.execute(
        f"UPDATE person_levels SET archived_at = {stamp} WHERE id = ?", (level_id,)
    )
    db.commit()
    return cursor.rowcount


def delete_level(level_id):
    """Only ever called after level_usage() comes back empty."""
    db = get_db()
    cursor = db.execute("DELETE FROM person_levels WHERE id = ?", (level_id,))
    db.commit()
    return cursor.rowcount


def overrides_for(person_id):
    return get_db().execute(
        "SELECT o.*, c.name AS card_name FROM person_rate_overrides o "
        "LEFT JOIN rate_cards c ON c.id = o.rate_card_id "
        "WHERE o.person_id = ? ORDER BY o.effective_from DESC",
        (person_id,),
    ).fetchall()
