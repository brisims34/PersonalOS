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


@bp.post("/cards")
def create_card():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("A rate card needs a name.", "error")
        return redirect(url_for("rates.index"))

    scope = request.form.get("scope", "standard")
    company = (request.form.get("company") or "").strip() or None
    is_default = 1 if request.form.get("is_default") == "1" else 0

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
            "INSERT INTO rate_cards (name, company, scope, is_default, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, company, scope, is_default, request.form.get("note") or None),
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
                    "UPDATE rate_card_entries SET bill_rate = ?, cost_rate = ? WHERE id = ?",
                    (bill, cost, existing["id"]),
                )
            else:
                db.execute(
                    "INSERT INTO rate_card_entries "
                    "(rate_card_id, level_id, bill_rate, cost_rate, effective_from) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (card_id, level["id"], bill, cost, effective_from),
                )
            written += 1
        db.commit()
    except Exception:
        db.rollback()
        raise

    activity.log("rate_card", card_id, "updated",
                 f"{written} rate(s) set on {record['name']} effective {effective_from}")
    flash(
        f"{written} rate{'s' if written != 1 else ''} saved on “{record['name']}” "
        f"effective {effective_from}. Existing budgets and time entries keep the rate "
        "they were priced at.",
        "success",
    )
    return redirect(url_for("rates.card", card_id=card_id))


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
