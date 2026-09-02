"""Activity Log.

Built at Phase 0 rather than Phase 22 for two reasons: it is the only way to
verify "activity log every mutation" (CLAUDE.md rule 13) while Phases 1–4 are
being built, and it gives the shell a second module so the module-registry
enable/disable behaviour is actually testable.

Read-only. There is no route that edits or deletes a log row, deliberately —
an audit trail you can rewrite is not one.
"""
import json

from flask import Blueprint, abort, render_template, request

from app.core import activity
from app.core.module_registry import guard_blueprint

bp = Blueprint("activity", __name__, url_prefix="/activity")
guard_blueprint(bp, "activity")

PAGE_SIZE = 100


@bp.get("/")
def index():
    page = max(request.args.get("page", 1, type=int), 1)
    entity_type = request.args.get("entity_type") or None
    action = request.args.get("action") or None
    search = (request.args.get("q") or "").strip() or None

    if action and action not in activity.ACTIONS:
        abort(400, "unknown action filter")

    total = activity.count(entity_type=entity_type, action=action, search=search)
    rows = activity.recent(
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
        entity_type=entity_type,
        action=action,
        search=search,
    )

    return render_template(
        "modules/activity/index.html",
        rows=rows,
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        page_count=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
        entity_types=activity.distinct_entity_types(),
        actions=sorted(activity.ACTIONS),
        filters={"entity_type": entity_type, "action": action, "q": search or ""},
        crumbs=[("System", None), "Activity Log"],
    )


@bp.get("/<int:entry_id>")
def detail(entry_id):
    record = activity.by_id(entry_id)
    if record is None:
        abort(404)

    detail = None
    if record["detail_json"]:
        try:
            detail = json.dumps(json.loads(record["detail_json"]), indent=2)
        except ValueError:
            detail = record["detail_json"]

    return render_template(
        "modules/activity/detail.html",
        record=record,
        detail=detail,
        crumbs=[("System", None), ("Activity Log", "/activity"), f"#{record['id']}"],
    )
