"""Rate cards, rate entries and the rate calculator.

Rates are entered here rather than seeded in a migration, for two reasons:
they are firm-confidential and do not belong in a file that is committed, and
they change every fiscal year, which is a data event and not a schema one.
"""
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from app.core import activity, links, rates
from app.core.database import get_db
from app.core.module_registry import guard_blueprint

bp = Blueprint("rates", __name__, url_prefix="/rates")
guard_blueprint(bp, "rates")

CRUMB = ("Budgets & Rates", "/rates")


@bp.get("/")
def index():
    as_of = request.args.get("as_of") or date.today().isoformat()
    return render_template(
        "modules/rates/index.html",
        cards=rates.all_cards(),
        levels=rates.levels(),
        transitions=rates.tenure_transitions_due(as_of),
        unpriced=rates.unpriced_people(as_of),
        as_of=as_of,
        crumbs=[CRUMB[0]],
    )


@bp.get("/cards/<int:card_id>")
def card(card_id):
    record = rates.card(card_id)
    if record is None:
        abort(404)
    entries = rates.card_entries(card_id)

    # Group by effective_from so a fiscal year reads as one block rather than
    # nine loose rows.
    years = {}
    for entry in entries:
        years.setdefault(entry["effective_from"], []).append(entry)

    return render_template(
        "modules/rates/card.html",
        card=record,
        entries=entries,
        years=sorted(years.items(), reverse=True),
        levels=rates.levels(),
        related_records=links.related("rate_card", card_id),
        trail=activity.for_entity("rate_card", card_id, limit=15),
        crumbs=[CRUMB, record["name"]],
    )


def _card_period():
    """The card's fiscal year and the dates it is in force.

    Fill either half and the other follows. A contradictory pair is refused
    rather than silently resolved: "which one did it believe" is not a
    question you want to have to ask of a rate card. Raises ValueError with
    the message to show.
    """
    fiscal_year = request.form.get("fiscal_year", type=int)
    effective_from = request.form.get("effective_from") or None
    effective_to = request.form.get("effective_to") or None

    if fiscal_year and not effective_from and not effective_to:
        effective_from, effective_to = rates.dates_for_fiscal_year(fiscal_year)
    elif effective_from and not fiscal_year:
        fiscal_year = rates.fiscal_year_for(effective_from)
    elif fiscal_year and effective_from:
        implied = rates.fiscal_year_for(effective_from)
        if implied != fiscal_year:
            raise ValueError(
                f"Not saved — {effective_from} falls in FY{implied}, not "
                f"FY{fiscal_year}. Fix one of the two."
            )
    return fiscal_year, effective_from, effective_to


@bp.post("/cards")
def create_card():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("A rate card needs a name.", "error")
        return redirect(url_for("rates.index"))

    scope = request.form.get("scope", "standard")
    company = (request.form.get("company") or "").strip() or None
    is_default = 1 if request.form.get("is_default") == "1" else 0

    try:
        fiscal_year, effective_from, effective_to = _card_period()
    except ValueError as mismatch:
        flash(str(mismatch), "error")
        return redirect(url_for("rates.index"))

    db = get_db()
    if is_default:
        # Only one default per company, or the fallback lookup is ambiguous.
        db.execute(
            "UPDATE rate_cards SET is_default = 0 "
            "WHERE is_default = 1 AND (company IS ? OR company = ?)",
            (company, company),
        )
    try:
        cursor = db.execute(
            "INSERT INTO rate_cards (name, company, scope, is_default, note, "
            "fiscal_year, effective_from, effective_to) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, company, scope, is_default, request.form.get("note") or None,
             fiscal_year, effective_from, effective_to),
        )
        db.commit()
    except Exception:
        db.rollback()
        flash(f"A card called “{name}” already exists for that company.", "error")
        return redirect(url_for("rates.index"))

    activity.log("rate_card", cursor.lastrowid, "created", f"Created rate card {name}")
    flash(
        f"Rate card “{name}” created. Add a rate for each level to make it usable.",
        "success",
    )
    return redirect(url_for("rates.card", card_id=cursor.lastrowid))


@bp.post("/cards/<int:card_id>/entries")
def save_entries(card_id):
    record = rates.card(card_id)
    if record is None:
        abort(404)

    effective_from = request.form.get("effective_from")
    if not effective_from:
        flash("Rates need an effective date — that is what makes them year-aware.", "error")
        return redirect(url_for("rates.card", card_id=card_id))

    # Optional. Left blank the rate stays open, which is right for the current
    # year's rates; setting it is how a superseded rate stops pricing.
    effective_to = request.form.get("effective_to") or None
    if effective_to and effective_to < effective_from:
        flash(
            f"Not saved — a rate running from {effective_from} to "
            f"{effective_to} ends before it starts.",
            "error",
        )
        return redirect(url_for("rates.card", card_id=card_id))

    # Rates live inside their card's year. The card's range decides what
    # prices, so a rate outside it could never price anything, and accepting
    # one silently is how you get a card that looks complete and prices
    # nothing.
    outside = (
        (record["effective_from"] and effective_from < record["effective_from"])
        or (record["effective_to"] and effective_from > record["effective_to"])
        or (record["effective_to"] and effective_to
            and effective_to > record["effective_to"])
    )
    if outside:
        flash(
            f"Not saved — “{record['name']}” is in force "
            f"{record['effective_from'] or 'from any date'} to "
            f"{record['effective_to'] or 'any date'}, so rates running "
            f"{effective_from} to {effective_to or 'open'} would fall outside it.",
            "error",
        )
        return redirect(url_for("rates.card", card_id=card_id))

    db = get_db()
    written = 0
    try:
        db.execute("BEGIN")
        for level in rates.levels():
            bill = request.form.get(f"bill_{level['id']}", type=float)
            cost = request.form.get(f"cost_{level['id']}", type=float)
            if bill is None and cost is None:
                continue
            existing = db.execute(
                "SELECT id FROM rate_card_entries "
                "WHERE rate_card_id = ? AND level_id = ? AND effective_from = ?",
                (card_id, level["id"], effective_from),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE rate_card_entries SET bill_rate = ?, cost_rate = ?, "
                    "effective_to = ? WHERE id = ?",
                    (bill, cost, effective_to, existing["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO rate_card_entries "
                    "(rate_card_id, level_id, bill_rate, cost_rate, "
                    " effective_from, effective_to) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (card_id, level["id"], bill, cost, effective_from, effective_to),
                )
            written += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    activity.log("rate_card", card_id, "updated",
                 f"{written} rate(s) set on {record['name']} effective "
                 f"{effective_from} to {effective_to or 'open'}")
    flash(
        f"{written} rate{'s' if written != 1 else ''} saved on “{record['name']}” "
        f"effective {effective_from}"
        + (f" to {effective_to}" if effective_to else " and open-ended")
        + ". Existing budgets and time entries keep the rate "
        "they were priced at.",
        "success",
    )
    return redirect(url_for("rates.card", card_id=card_id))


@bp.post("/cards/<int:card_id>")
def update_card(card_id):
    """Correct a card in place.

    Without this, a typo in the fiscal year could only be fixed by archiving
    the card and building it again, which would strand its rate history.
    """
    record = rates.card(card_id)
    if record is None:
        abort(404)

    name = (request.form.get("name") or "").strip()
    if not name:
        flash("A rate card needs a name.", "error")
        return redirect(url_for("rates.card", card_id=card_id))

    try:
        fiscal_year, effective_from, effective_to = _card_period()
    except ValueError as mismatch:
        flash(str(mismatch), "error")
        return redirect(url_for("rates.card", card_id=card_id))

    company = (request.form.get("company") or "").strip() or None
    is_default = 1 if request.form.get("is_default") == "1" else 0

    db = get_db()
    if is_default:
        # Only one default per company, or the fallback lookup is ambiguous.
        db.execute(
            "UPDATE rate_cards SET is_default = 0 "
            "WHERE is_default = 1 AND id != ? AND (company IS ? OR company = ?)",
            (card_id, company, company),
        )
    try:
        db.execute(
            "UPDATE rate_cards SET name = ?, company = ?, scope = ?, "
            "is_default = ?, note = ?, fiscal_year = ?, effective_from = ?, "
            "effective_to = ?, updated_at = datetime('now') WHERE id = ?",
            (name, company, request.form.get("scope", record["scope"]), is_default,
             request.form.get("note") or None, fiscal_year, effective_from,
             effective_to, card_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        flash(f"A card called “{name}” already exists for that company.", "error")
        return redirect(url_for("rates.card", card_id=card_id))

    activity.log("rate_card", card_id, "updated", f"Updated rate card {name}")
    flash(
        f"“{name}” saved. Rates already resolved onto budget lines and time "
        "entries keep the numbers they were priced at.",
        "success",
    )
    return redirect(url_for("rates.card", card_id=card_id))


@bp.post("/cards/<int:card_id>/entries/<int:entry_id>/delete")
def delete_entry(card_id, entry_id):
    """Remove one wrong rate without rebuilding the card.

    Rows already priced from it keep their snapshotted numbers, so this
    removes a rate going forward rather than rewriting what it once priced.
    """
    record = rates.card(card_id)
    if record is None:
        abort(404)

    db = get_db()
    entry = db.execute(
        "SELECT e.*, l.label AS level_label FROM rate_card_entries e "
        "JOIN person_levels l ON l.id = e.level_id "
        "WHERE e.id = ? AND e.rate_card_id = ?",
        (entry_id, card_id),
    ).fetchone()
    if entry is None:
        abort(404)

    db.execute("DELETE FROM rate_card_entries WHERE id = ?", (entry_id,))
    db.commit()
    activity.log("rate_card", card_id, "deleted",
                 f"Removed the {entry['level_label']} rate effective "
                 f"{entry['effective_from']} from {record['name']}")
    flash(
        f"{entry['level_label']} effective {entry['effective_from']} removed. "
        "Anything already priced from it keeps the rate it was written with.",
        "success",
    )
    return redirect(url_for("rates.card", card_id=card_id))


@bp.post("/cards/<int:card_id>/delete")
def delete_card(card_id):
    """Delete only an empty card. Anything that has priced work is archived.

    A card with entries is history: deleting it would leave budget lines and
    time entries pointing at a card that no longer explains their numbers.
    """
    record = rates.card(card_id)
    if record is None:
        abort(404)

    entries = rates.card_entries(card_id)
    if entries:
        flash(
            f"“{record['name']}” cannot be deleted — it carries "
            f"{len(entries)} rate{'s' if len(entries) != 1 else ''}. Archive it "
            "instead: that takes it out of use and leaves everything it priced "
            "exactly as it is.",
            "error",
        )
        return redirect(url_for("rates.card", card_id=card_id))

    db = get_db()
    db.execute("DELETE FROM rate_cards WHERE id = ?", (card_id,))
    db.commit()
    activity.log("rate_card", card_id, "deleted",
                 f"Deleted the empty rate card {record['name']}")
    flash(f"“{record['name']}” deleted. It carried no rates.", "success")
    return redirect(url_for("rates.index"))


@bp.post("/cards/<int:card_id>/archive")
def archive_card(card_id):
    record = rates.card(card_id)
    if record is None:
        abort(404)
    db = get_db()
    restoring = record["archived_at"] is not None
    db.execute(
        "UPDATE rate_cards SET archived_at = "
        + ("NULL" if restoring else "datetime('now')")
        + ", updated_at = datetime('now') WHERE id = ?",
        (card_id,),
    )
    db.commit()
    action = "restored" if restoring else "archived"
    activity.log("rate_card", card_id, action, f"{action.title()} rate card {record['name']}")
    flash(
        f"“{record['name']}” {action}. Rates already resolved onto rows are untouched.",
        "success",
    )
    return redirect(url_for("rates.card", card_id=card_id))


@bp.get("/calculator")
def calculator():
    """Resolve one person on one date and show every step.

    This is the traceable-number pattern applied to the rate engine itself
    (P3): the answer is worth little without the chain that produced it.
    """
    from app.modules.people import models as people_models

    person_id = request.args.get("person_id", type=int)
    as_of = request.args.get("as_of") or date.today().isoformat()
    erp = request.args.get("erp_pct", type=float)
    hours = request.args.get("hours", type=float) or 1.0

    resolved = revenue = cost = None
    person = None
    if person_id:
        person = people_models.get_person(person_id)
        if person:
            resolved = rates.resolve_rates(person_id, as_of, erp_pct=erp)
            revenue, cost = rates.price(hours, resolved)

    return render_template(
        "modules/rates/calculator.html",
        person=person,
        people=people_models.list_people(limit=1000),
        resolved=resolved,
        revenue=revenue,
        cost=cost,
        hours=hours,
        erp=erp,
        as_of=as_of,
        history=people_models.level_history(person_id) if person_id else [],
        crumbs=[CRUMB, "Rate calculator"],
    )


# --- the level ladder -------------------------------------------------------
#
# Levels live here rather than in their own module because they are the
# rate-bearing ladder: rate cards price by level, and a level with no card
# entry prices nothing. The identifier is the row id; label and sort order
# carry the meaning, and both are kept unique among live levels.


@bp.get("/levels")
def levels_index():
    as_of = request.args.get("as_of") or date.today().isoformat()
    ladder = rates.list_levels()
    return render_template(
        "modules/rates/levels.html",
        levels=ladder,
        as_of=as_of,
        usage={level["id"]: rates.level_usage(level["id"]) for level in ladder},
        rates_at={level["id"]: rates.rate_for_level(level["id"], as_of)
                  for level in ladder},
        crumbs=[CRUMB, "Levels"],
    )


def _level_form():
    label = (request.form.get("label") or "").strip()
    sort_order = request.form.get("sort_order", type=int)
    on_ladder = 1 if request.form.get("is_on_ladder") else 0
    return label, sort_order, on_ladder


@bp.post("/levels")
def create_level():
    label, sort_order, on_ladder = _level_form()
    if not label or sort_order is None:
        flash("A level needs a name and a sort order.", "error")
        return redirect(url_for("rates.levels_index"))

    clash = rates.label_or_order_taken(label, sort_order)
    if clash:
        flash(f"Not created — {clash}.", "error")
        return redirect(url_for("rates.levels_index"))

    level_id = rates.create_level(label, sort_order, on_ladder)
    activity.log("rate_card", level_id, "created", f"Added the level {label}")
    flash(
        f"{label} added to the ladder at sort order {sort_order}. It has no "
        "rate-card entries yet, so nobody prices from it until you add one.",
        "success",
    )
    return redirect(url_for("rates.levels_index"))


@bp.post("/levels/<int:level_id>")
def update_level(level_id):
    label, sort_order, on_ladder = _level_form()
    if not label or sort_order is None:
        flash("A level needs a name and a sort order.", "error")
        return redirect(url_for("rates.levels_index"))

    clash = rates.label_or_order_taken(label, sort_order, exclude_id=level_id)
    if clash:
        flash(f"Not saved — {clash}.", "error")
        return redirect(url_for("rates.levels_index"))

    rates.update_level(level_id, {"label": label, "sort_order": sort_order,
                                  "is_on_ladder": on_ladder})
    activity.log("rate_card", level_id, "updated", f"Updated the level {label}")
    flash(f"{label} saved.", "success")
    return redirect(url_for("rates.levels_index"))


@bp.post("/levels/<int:level_id>/archive")
def archive_level(level_id):
    rates.set_level_archived(level_id, True)
    activity.log("rate_card", level_id, "archived", f"Archived level {level_id}")
    flash(
        "Level archived. It is gone from the pickers, and every rate-card "
        "entry and history row that referenced it is untouched and still prices.",
        "success",
    )
    return redirect(url_for("rates.levels_index"))


@bp.post("/levels/<int:level_id>/restore")
def restore_level(level_id):
    rates.set_level_archived(level_id, False)
    activity.log("rate_card", level_id, "restored", f"Restored level {level_id}")
    flash("Level restored — it is selectable again.", "success")
    return redirect(url_for("rates.levels_index"))


@bp.post("/levels/<int:level_id>/delete")
def delete_level(level_id):
    usage = rates.level_usage(level_id)
    if any(usage.values()):
        held = ", ".join(f"{count} {name.replace('_', ' ')}"
                         for name, count in usage.items() if count)
        flash(
            f"This level cannot be deleted — {held} still reference it. Archive "
            "it instead: that hides it from the pickers and leaves every priced "
            "row exactly as it is.",
            "error",
        )
        return redirect(url_for("rates.levels_index"))

    rates.delete_level(level_id)
    activity.log("rate_card", level_id, "deleted",
                 f"Deleted the unused level {level_id}")
    flash("Level deleted. Nothing referenced it.", "success")
    return redirect(url_for("rates.levels_index"))
