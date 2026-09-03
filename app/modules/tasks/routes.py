import sqlite3
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from app.core import activity, config, links, notes_index
from app.core.module_registry import guard_blueprint
from app.modules.charge_codes import models as code_models
from app.modules.people import models as people_models
from app.modules.projects import models as project_models

from . import models

bp = Blueprint("tasks", __name__, url_prefix="/tasks")
guard_blueprint(bp, "tasks")

CRUMB = ("Tasks", "/tasks")

TASK_INLINE_FIELDS = {"status", "priority", "due_date", "estimate_hours", "assignee_person_id"}


@bp.get("/")
def index():
    as_of = request.args.get("as_of") or date.today().isoformat()
    project_id = request.args.get("project_id", type=int)
    filters = {
        "search": (request.args.get("q") or "").strip() or None,
        "status": request.args.get("status") or None,
        "priority": request.args.get("priority") or None,
        "project_id": project_id,
        "workstream_id": request.args.get("workstream_id", type=int),
        "charge_code_id": request.args.get("charge_code_id", type=int),
        "assignee_person_id": request.args.get("assignee", type=int),
        "task_type": request.args.get("task_type") or None,
        "open_only": request.args.get("open") == "1",
    }
    return render_template(
        "modules/tasks/index.html",
        rows=models.list_tasks(sort=request.args.get("sort", "due"), **filters),
        total=models.count_tasks(**filters),
        counts=models.counts(as_of),
        filters=filters,
        as_of=as_of,
        projects=project_models.list_projects(limit=500),
        # Scoped to the selected project when one is chosen, else every
        # workstream labelled with its project name (P8 — no re-asking).
        workstreams=project_models.all_workstreams(project_id),
        codes=code_models.active_codes(),
        people=people_models.list_people(limit=1000),
        people_options=[{"id": p["id"], "label": p["full_name"]}
                        for p in people_models.list_people(limit=1000)],
        task_types=config.options("task_type"),
        crumbs=[CRUMB[0]],
    )


@bp.get("/<int:task_id>")
def detail(task_id):
    task = models.get_task(task_id)
    if task is None:
        abort(404)
    people = people_models.list_people(limit=1000)
    return render_template(
        "modules/tasks/detail.html",
        task=task,
        projects=project_models.list_projects(limit=500),
        workstreams=project_models.workstreams(task["project_id"]) if task["project_id"] else [],
        codes=code_models.active_codes(),
        people=people,
        people_options=[{"id": p["id"], "label": p["full_name"]} for p in people],
        task_types=config.options("task_type"),
        backlinks=notes_index.backlinks("task", task_id),
        related_records=links.related("task", task_id),
        trail=activity.for_entity("task", task_id, limit=15),
        crumbs=[CRUMB, task["title"]],
    )


@bp.post("/<int:task_id>/field")
def update_field(task_id):
    task = models.get_task(task_id)
    if task is None:
        abort(404)
    if task["archived_at"] is not None:
        return {"ok": False, "error": "This task is archived — restore it first to edit."}

    field = request.form.get("field")
    value = request.form.get("value") or None
    if field not in TASK_INLINE_FIELDS:
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

    if field == "assignee_person_id" and value is not None:
        try:
            value = int(value)
        except ValueError:
            return {"ok": False, "error": "That doesn't look like a valid person."}
        if people_models.get_person(value) is None:
            return {"ok": False, "error": "That person no longer exists."}
    elif field == "estimate_hours" and value is not None:
        try:
            value = float(value)
        except ValueError:
            return {"ok": False, "error": "Estimate hours must be a number."}

    try:
        models.update_task(task_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_task(task_id)
    activity.log("task", task_id, "updated", f"Updated {field} for “{updated['title']}”")
    if field == "assignee_person_id":
        assignee = people_models.get_person(updated["assignee_person_id"]) if updated["assignee_person_id"] else None
        display = assignee["full_name"] if assignee else ""
    else:
        display = str(updated[field]) if updated[field] is not None else ""
    return {"ok": True, "display": display}


def _fields(form):
    fields = {}
    for key in models.WRITABLE:
        if key not in form:
            continue
        value = form.get(key)
        fields[key] = (value.strip() or None) if isinstance(value, str) else value
    for key in ("project_id", "workstream_id", "charge_code_id", "assignee_person_id",
                "sort_order"):
        if fields.get(key) is not None:
            fields[key] = int(fields[key])
    if fields.get("estimate_hours") is not None:
        fields["estimate_hours"] = float(fields["estimate_hours"])
    return fields


@bp.post("/save")
def save():
    task_id = request.form.get("task_id", type=int)
    fields = _fields(request.form)
    if not fields.get("title"):
        flash("A task needs a title.", "error")
        return redirect(request.referrer or url_for("tasks.index"))

    # Context the app already knows is never re-asked (P8): a charge code
    # implies its project and workstream, so fill them rather than demand them.
    if fields.get("charge_code_id") and not fields.get("project_id"):
        code = code_models.get_code(fields["charge_code_id"])
        if code:
            fields["project_id"] = code["project_id"]
            fields.setdefault("workstream_id", code["workstream_id"])

    if task_id:
        models.update_task(task_id, fields)
        task = models.get_task(task_id)
        activity.log("task", task_id, "updated", f"Updated task “{task['title']}”")
        flash(f"“{task['title']}” updated.", "success")
    else:
        task_id = models.create_task(fields)
        task = models.get_task(task_id)
        activity.log("task", task_id, "created", f"Created task “{task['title']}”")
        parts = []
        if task["project_name"]:
            parts.append(task["project_name"])
        if task["charge_code"]:
            parts.append(task["charge_code"])
        if task["due_date"]:
            parts.append(f"due {task['due_date']}")
        flash(
            f"“{task['title']}” added" + (f" — {', '.join(parts)}." if parts else "."),
            "success",
        )
    return redirect(request.form.get("next") or url_for("tasks.detail", task_id=task_id))


@bp.post("/quick-add")
def quick_add():
    """One field, everything else inherited from where you were."""
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("Nothing to add.", "error")
        return redirect(request.referrer or url_for("tasks.index"))

    fields = {"title": title, "status": "open", "priority": "medium"}
    for key in ("project_id", "workstream_id", "charge_code_id", "assignee_person_id"):
        if request.form.get(key):
            fields[key] = int(request.form.get(key))
    if request.form.get("due_date"):
        fields["due_date"] = request.form.get("due_date")

    task_id = models.create_task(fields)
    task = models.get_task(task_id)
    activity.log("task", task_id, "created", f"Quick-added “{title}”")
    flash(
        f"“{title}” added"
        + (f" to {task['project_name']}" if task["project_name"] else "")
        + (f", due {task['due_date']}." if task["due_date"] else "."),
        "success",
    )
    return redirect(request.referrer or url_for("tasks.index"))


@bp.post("/bulk")
def bulk():
    task_ids = [int(v) for v in request.form.getlist("task_ids") if v.isdigit()]
    status = request.form.get("status")
    if not task_ids:
        flash("No tasks were selected.", "error")
        return redirect(request.referrer or url_for("tasks.index"))
    if status not in ("open", "in_progress", "blocked", "completed", "cancelled"):
        abort(400)

    as_of = date.today().isoformat()
    changed = models.set_status(task_ids, status)

    regenerated = 0
    if status == "completed":
        for task_id in task_ids:
            if models.regenerate_from(task_id, as_of):
                regenerated += 1

    activity.log("tasks", None, "updated",
                 f"{changed} task(s) set to {status}", {"ids": task_ids})
    flash(
        f"{changed} task{'s' if changed != 1 else ''} set to {status.replace('_', ' ')}"
        + (f". {regenerated} recurring task{'s' if regenerated != 1 else ''} "
           "regenerated at the next due date." if regenerated else "."),
        "success",
    )
    return redirect(request.referrer or url_for("tasks.index"))


@bp.post("/<int:task_id>/complete")
def complete(task_id):
    task = models.get_task(task_id)
    if task is None:
        abort(404)
    as_of = date.today().isoformat()
    models.set_status([task_id], "completed")
    following = models.regenerate_from(task_id, as_of)

    activity.log("task", task_id, "updated", f"Completed “{task['title']}”")
    if following:
        new_task = models.get_task(following)
        flash(
            f"“{task['title']}” completed. The next one is due {new_task['due_date']}.",
            "success",
        )
    else:
        flash(f"“{task['title']}” completed.", "success")
    return redirect(request.referrer or url_for("tasks.index"))


@bp.post("/<int:task_id>/archive")
def archive(task_id):
    task = models.get_task(task_id)
    if task is None:
        abort(404)
    restoring = task["archived_at"] is not None
    models.archive_task(task_id, archived=not restoring)
    action = "restored" if restoring else "archived"
    activity.log("task", task_id, action, f"{action.title()} “{task['title']}”")
    flash(f"“{task['title']}” {action}. Nothing was deleted.", "success")
    return redirect(url_for("tasks.detail", task_id=task_id))


@bp.get("/new")
def new():
    """Create with context pre-filled from wherever you came from (P8)."""
    project_id = request.args.get("project_id", type=int)
    project = project_models.get_project(project_id) if project_id else None
    codes = code_models.for_project(project_id) if project_id else code_models.active_codes()
    default_code = next((c for c in codes if c["is_default"] and c["status"] == "active"),
                        codes[0] if len(codes) == 1 else None)

    return render_template(
        "modules/tasks/edit.html",
        task=None,
        project=project,
        default_charge_code_id=default_code["id"] if default_code else None,
        workstream_id=request.args.get("workstream_id", type=int),
        projects=project_models.list_projects(limit=500),
        workstreams=project_models.workstreams(project_id) if project_id else [],
        codes=codes,
        people=people_models.list_people(limit=1000),
        task_types=config.options("task_type"),
        crumbs=[CRUMB, "New task"],
    )


@bp.get("/<int:task_id>/edit")
def edit(task_id):
    task = models.get_task(task_id)
    if task is None:
        abort(404)
    return render_template(
        "modules/tasks/edit.html",
        task=task,
        project=project_models.get_project(task["project_id"]) if task["project_id"] else None,
        default_charge_code_id=task["charge_code_id"],
        workstream_id=task["workstream_id"],
        projects=project_models.list_projects(limit=500),
        workstreams=project_models.workstreams(task["project_id"]) if task["project_id"] else [],
        codes=code_models.active_codes(),
        people=people_models.list_people(limit=1000),
        task_types=config.options("task_type"),
        crumbs=[CRUMB, (task["title"], url_for("tasks.detail", task_id=task_id)), "Edit"],
    )
