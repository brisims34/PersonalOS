import sqlite3

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from app.core import activity, config, links, paths
from app.core.module_registry import guard_blueprint
from app.core.paths import safe_slug
from app.modules.projects import models as project_models

from . import models

bp = Blueprint("portfolios", __name__, url_prefix="/portfolios")
guard_blueprint(bp, "portfolios")

CRUMB = ("Portfolios", "/portfolios")

TABS = [("overview", "Overview"), ("projects", "Projects")]


@bp.get("/")
def index():
    return render_template(
        "modules/portfolios/index.html",
        rows=models.list_portfolios(),
        kinds=config.options("portfolio_kind"),
        vault_root=str(paths.VAULT_ROOT),
        crumbs=[CRUMB[0]],
    )


@bp.get("/<int:portfolio_id>")
def detail(portfolio_id):
    portfolio = models.get_portfolio(portfolio_id)
    if portfolio is None:
        abort(404)
    return render_template(
        "modules/portfolios/detail.html",
        portfolio=portfolio,
        tab=request.args.get("tab", "overview"),
        tab_items=TABS,
        projects=project_models.list_projects(portfolio_id=portfolio_id),
        related_records=links.related("portfolio", portfolio_id),
        trail=activity.for_entity("portfolio", portfolio_id, limit=10),
        crumbs=[CRUMB, portfolio["name"]],
    )


@bp.post("/save")
def save():
    portfolio_id = request.form.get("portfolio_id", type=int)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("A portfolio needs a name.", "error")
        return redirect(url_for("portfolios.index"))

    fields = {
        "name": name,
        "portfolio_kind": request.form.get("portfolio_kind", "client"),
        "description": (request.form.get("description") or "").strip() or None,
        "sort_order": request.form.get("sort_order", type=int) or 0,
    }

    if portfolio_id:
        models.update_portfolio(portfolio_id, fields)
        activity.log("portfolio", portfolio_id, "updated", f"Updated portfolio {name}")
        flash(f"{name} updated.", "success")
    else:
        # The folder name is a heading a human reads in Explorer, so it keeps
        # its capitals; only the illegal characters are stripped.
        taken = {row["folder_slug"].lower() for row in models.list_portfolios(True)}
        fields["folder_slug"] = name if safe_slug(name) not in taken else safe_slug(name, taken)
        portfolio_id = models.create_portfolio(fields)
        activity.log("portfolio", portfolio_id, "created", f"Created portfolio {name}")
        flash(
            f"{name} created. Projects filed under it get a folder at "
            f"projects/{fields['folder_slug']}/.",
            "success",
        )
    return redirect(url_for("portfolios.detail", portfolio_id=portfolio_id))


@bp.post("/<int:portfolio_id>/archive")
def archive(portfolio_id):
    portfolio = models.get_portfolio(portfolio_id)
    if portfolio is None:
        abort(404)
    restoring = portfolio["archived_at"] is not None
    models.archive_portfolio(portfolio_id, archived=not restoring)
    action = "restored" if restoring else "archived"
    activity.log("portfolio", portfolio_id, action, f"{action.title()} {portfolio['name']}")
    flash(
        f"{portfolio['name']} {action}. "
        + ("It is back in the active portfolio list." if restoring
           else "Hidden from active lists — its projects and folder are all kept."),
        "success",
    )
    return redirect(url_for("portfolios.detail", portfolio_id=portfolio_id))


INLINE_FIELDS = {"portfolio_kind", "sort_order"}


@bp.post("/<int:portfolio_id>/field")
def update_field(portfolio_id):
    portfolio = models.get_portfolio(portfolio_id)
    if portfolio is None:
        abort(404)
    if portfolio["archived_at"] is not None:
        return {"ok": False, "error": "This portfolio is archived — restore it first to edit."}

    field = request.form.get("field")
    value = request.form.get("value")
    if field not in INLINE_FIELDS:
        return {"ok": False, "error": f"\"{field}\" can't be edited inline here."}

    if field == "sort_order":
        try:
            value = int(value) if value else 0
        except ValueError:
            return {"ok": False, "error": "Sort order must be a whole number."}

    try:
        models.update_portfolio(portfolio_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_portfolio(portfolio_id)
    activity.log("portfolio", portfolio_id, "updated", f"Updated {field} for {updated['name']}")
    display = str(updated[field]) if updated[field] is not None else ""
    return {"ok": True, "display": display}
