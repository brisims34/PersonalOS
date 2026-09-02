"""Org chart reports.

Recursive CTEs over `manager_person_id`, which is the administrative reporting
line from the directory — not the counselee relationship, which is the
performance line and is maintained separately (Phase 17).

Every walk is bounded: a depth cap and a path check, because real directory
data does contain reporting cycles and an unbounded CTE would hang the request.
"""
from flask import Blueprint, abort, render_template, request, url_for

from app.core.module_registry import guard_blueprint
from app.modules.people import models

bp = Blueprint("org_chart", __name__, url_prefix="/org-chart")
guard_blueprint(bp, "org_chart")

CRUMB = ("Org Chart", "/org-chart")


def _tree(person_id, max_depth):
    """Nest the flat downline into parent → children for rendering."""
    flat = models.downline(person_id, max_depth=max_depth)
    children = {}
    for row in flat:
        children.setdefault(row["manager_person_id"], []).append(dict(row))
    return children, len(flat)


@bp.get("/")
def index():
    return render_template(
        "modules/org_chart/index.html",
        roots=models.roots(),
        spans=models.span_of_control()[:25],
        summary=models.roster_summary(),
        crumbs=[CRUMB[0]],
    )


@bp.get("/<int:person_id>")
def person(person_id):
    subject = models.get_person(person_id)
    if subject is None:
        abort(404)

    depth = min(max(request.args.get("depth", 4, type=int), 1), models.MAX_CHAIN_DEPTH)
    children, total = _tree(person_id, depth)

    return render_template(
        "modules/org_chart/person.html",
        subject=subject,
        chain=models.chain_up(person_id),
        children=children,
        direct=models.direct_reports(person_id),
        total_downline=total,
        depth=depth,
        crumbs=[CRUMB, subject["full_name"]],
    )
