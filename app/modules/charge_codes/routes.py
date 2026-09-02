from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from app.core import activity, links, rates
from app.core.module_registry import guard_blueprint
from app.modules.people import models as people_models
from app.modules.projects import models as project_models

from . import models

bp = Blueprint("charge_codes", __name__, url_prefix="/charge-codes")
guard_blueprint(bp, "charge_codes")

CRUMB = ("Charge Codes", "/charge-codes")


@bp.get("/")
def index():
    return render_template(
        "modules/charge_codes/index.html",
        rows=models.list_codes(
            search=(request.args.get("q") or "").strip() or None,
            status=request.args.get("status") or None,
        ),
        summary=models.summary(),
        filters={"q": request.args.get("q") or "", "status": request.args.get("status") or ""},
        crumbs=[CRUMB[0]],
    )


@bp.get("/<int:code_id>")
def detail(code_id):
    code = models.get_code(code_id)
    if code is None:
        abort(404)
    return render_template(
        "modules/charge_codes/detail.html",
        code=code,
        people=people_models.list_people(limit=1000),
        cards=rates.all_cards(),
        workstreams=project_models.workstreams(code["project_id"]),
        related_records=links.related("charge_code", code_id),
        trail=activity.for_entity("charge_code", code_id, limit=15),
        crumbs=[CRUMB, code["code"]],
    )


def _fields(form):
    fields = {}
    for key in models.WRITABLE:
        if key not in form:
            continue
        value = form.get(key)
        fields[key] = (value.strip() or None) if isinstance(value, str) else value
    for key in ("project_id", "workstream_id", "lead_partner_person_id",
                "engagement_manager_person_id", "rate_card_id", "is_default"):
        if fields.get(key) is not None:
            fields[key] = int(fields[key])
    for key in ("erp_pct", "budget_hours", "budget_fees"):
        if fields.get(key) is not None:
            fields[key] = float(fields[key])
    return fields


@bp.post("/save")
def save():
    code_id = request.form.get("code_id", type=int)
    fields = _fields(request.form)

    if not fields.get("code") or not fields.get("name"):
        flash("A charge code needs both a code and a name.", "error")
        return redirect(request.referrer or url_for("charge_codes.index"))

    clash = models.by_code(fields["code"])
    if clash and clash["id"] != code_id:
        flash(
            f"{fields['code']} is already used by {clash['project_name']}. "
            "Charge codes are unique across every project — that is what makes "
            "timesheet reconciliation possible.",
            "error",
        )
        return redirect(request.referrer or url_for("charge_codes.index"))

    if code_id:
        models.update_code(code_id, fields)
        code = models.get_code(code_id)
        activity.log("charge_code", code_id, "updated", f"Updated charge code {code['code']}")
        flash(f"Charge code {code['code']} updated.", "success")
    else:
        if not fields.get("project_id"):
            flash("A charge code has to belong to a project.", "error")
            return redirect(request.referrer or url_for("charge_codes.index"))
        code_id = models.create_code(fields)
        code = models.get_code(code_id)
        activity.log("charge_code", code_id, "created",
                     f"Created charge code {code['code']} on {code['project_name']}")
        flash(
            f"Charge code {code['code']} created on {code['project_name']}. "
            "Time is booked against the code, and project and workstream are derived from it.",
            "success",
        )
    return redirect(url_for("charge_codes.detail", code_id=code_id))


@bp.post("/<int:code_id>/status")
def set_status(code_id):
    code = models.get_code(code_id)
    if code is None:
        abort(404)
    status = request.form.get("status")
    if status not in ("active", "inactive", "closed"):
        abort(400)
    models.set_status(code_id, status)
    activity.log("charge_code", code_id, "updated", f"{code['code']} marked {status}")
    flash(
        f"{code['code']} is now {status}."
        + (" Closed codes are hidden from booking pickers." if status == "closed" else ""),
        "success",
    )
    return redirect(url_for("charge_codes.detail", code_id=code_id))
