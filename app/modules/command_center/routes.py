from datetime import date, timedelta

from flask import Blueprint, render_template, request

from app.core import activity, config
from app.core.module_registry import guard_blueprint
from app.modules.tasks import models as task_models

from . import models

bp = Blueprint("command_center", __name__, url_prefix="/")
guard_blueprint(bp, "command_center")


@bp.get("/")
def index():
    # The evaluation date is a parameter, not an assumption — the route supplies
    # the default and the whole page can be asked about a future date.
    as_of = request.args.get("as_of") or date.today().isoformat()
    horizon = (date.fromisoformat(as_of) + timedelta(days=7)).isoformat()
    self_person_id = config.get_int("self_person_id")

    dependencies, waiting = models.chase_list(as_of)

    return render_template(
        "modules/command_center/index.html",
        as_of=as_of,
        counts=models.action_strip(as_of, self_person_id),
        overdue=task_models.overdue(as_of),
        upcoming=task_models.due_between(as_of, horizon),
        health=models.project_health(as_of),
        codes=models.my_charge_codes(as_of),
        dependencies=dependencies,
        waiting=waiting,
        notes=models.recent_notes(),
        recent=activity.recent(limit=8),
        progress=models.build_progress(),
        schema=models.schema_state(),
        empty=models.is_empty(),
    )
