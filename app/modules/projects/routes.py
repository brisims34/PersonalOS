from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from app.core import activity, config, folders, links
from app.core.module_registry import guard_blueprint
from app.modules.people import models as people_models

from . import models

bp = Blueprint("projects", __name__, url_prefix="/projects")
guard_blueprint(bp, "projects")

CRUMB = ("Projects", "/projects")

TABS = [
    ("overview", "Overview"), ("workstreams", "Workstreams"),
    ("codes", "Charge codes"), ("team", "Team"),
    ("locations", "Locations & resources"), ("dependencies", "Dependencies"),
]


@bp.get("/")
def index():
    filters = {
        "search": (request.args.get("q") or "").strip() or None,
        "portfolio_id": request.args.get("portfolio_id", type=int),
        "status": request.args.get("status") or None,
        "project_type": request.args.get("project_type") or None,
        "priority": request.args.get("priority") or None,
        "include_archived": request.args.get("archived") == "1",
    }
    return render_template(
        "modules/projects/index.html",
        rows=models.list_projects(**filters),
        total=models.count_projects(**filters),
        filters=filters,
        portfolios=models.portfolio_summary(),
        project_types=config.options("project_type"),
        crumbs=[CRUMB[0]],
    )


@bp.get("/<int:project_id>")
def detail(project_id):
    project = models.get_project(project_id)
    if project is None:
        abort(404)

    tab = request.args.get("tab", "overview")
    from app.modules.charge_codes import models as code_models

    return render_template(
        "modules/projects/detail.html",
        project=project,
        tab=tab,
        tab_items=TABS,
        workstreams=models.workstreams(project_id),
        codes=code_models.for_project(project_id),
        team=models.project_team(project_id),
        locations=models.locations(project_id),
        all_locations=models.locations(),
        resources=models.work_resources(project_id=project_id),
        deps=models.dependencies(project_id),
        folder=folders.folder_summary(project["folder_path"]),
        people=people_models.list_people(limit=1000),
        related_records=links.related("project", project_id),
        trail=activity.for_entity("project", project_id, limit=15),
        crumbs=[CRUMB, project["name"]],
    )


@bp.get("/new")
def new():
    return render_template(
        "modules/projects/edit.html",
        project=None,
        portfolios=models.portfolio_summary(),
        people=people_models.list_people(limit=1000),
        service_offerings=config.options("service_offering"),
        project_types=config.options("project_type"),
        cards=_rate_cards(),
        crumbs=[CRUMB, "New project"],
    )


@bp.get("/<int:project_id>/edit")
def edit(project_id):
    project = models.get_project(project_id)
    if project is None:
        abort(404)
    return render_template(
        "modules/projects/edit.html",
        project=project,
        portfolios=models.portfolio_summary(),
        people=people_models.list_people(limit=1000),
        service_offerings=config.options("service_offering"),
        project_types=config.options("project_type"),
        cards=_rate_cards(),
        crumbs=[CRUMB, (project["name"], url_for("projects.detail", project_id=project_id)),
                "Edit"],
    )


def _rate_cards():
    from app.core import rates

    return rates.all_cards()


def _form_fields(form, writable):
    fields = {}
    for key in writable:
        if key not in form:
            continue
        value = form.get(key)
        value = value.strip() if isinstance(value, str) else value
        fields[key] = value or None
    for key in ("portfolio_id", "rate_card_id", "lead_partner_person_id",
                "engagement_manager_person_id", "project_lead_person_id",
                "lead_person_id", "owner_person_id", "site_contact_person_id",
                "from_workstream_id", "to_workstream_id", "workstream_id",
                "project_id", "sort_order"):
        if key in fields and fields[key] is not None:
            fields[key] = int(fields[key])
    for key in ("erp_pct", "budget_hours", "budget_fees", "budget_expenses"):
        if key in fields and fields[key] is not None:
            fields[key] = float(fields[key])
    return fields


@bp.post("/save")
def save():
    project_id = request.form.get("project_id", type=int)
    fields = _form_fields(request.form, models.WRITABLE)

    if not fields.get("name"):
        flash("A project needs a name.", "error")
        return redirect(request.referrer or url_for("projects.index"))
    if not fields.get("portfolio_id"):
        flash("Choose which portfolio this project belongs to.", "error")
        return redirect(request.referrer or url_for("projects.index"))

    if project_id:
        before = models.get_project(project_id)
        models.update_project(project_id, fields)
        project = models.get_project(project_id)

        moved = None
        if before["name"] != project["name"] and before["folder_path"]:
            try:
                new_path, _abs = folders.rename_folder(before["folder_path"], project["name"])
                models.set_folder_path(project_id, new_path)
                moved = new_path
            except (folders.FolderError, OSError) as exc:
                flash(f"Renamed, but the folder could not be moved: {exc}", "warning")

        activity.log("project", project_id, "updated", f"Updated {project['name']}",
                     {"fields": sorted(fields)})
        flash(
            f"{project['name']} updated."
            + (f" Folder moved to {moved}, contents intact." if moved else ""),
            "success",
        )
    else:
        project_id = models.create_project(fields)
        project = models.get_project(project_id)
        rel = _provision(project)
        activity.log("project", project_id, "created", f"Created project {project['name']}")
        flash(
            f"{project['name']} created in {project['portfolio_name']}"
            + (f" with a folder at {rel}." if rel else ", but the folder could not be created."),
            "success",
        )
    return redirect(url_for("projects.detail", project_id=project_id))


def _provision(project):
    try:
        rel, _abs = folders.provision_project(project["portfolio_slug"], project["name"])
        models.set_folder_path(project["id"], rel)
        return rel
    except (folders.FolderError, OSError) as exc:
        flash(f"The project folder could not be created: {exc}", "warning")
        return None


@bp.post("/<int:project_id>/provision")
def provision(project_id):
    project = models.get_project(project_id)
    if project is None:
        abort(404)
    rel = _provision(project)
    if rel:
        activity.log("project", project_id, "created", f"Provisioned folder {rel}")
        flash(f"Folder ready at {rel}. Workstream folders sit inside it.", "success")
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/<int:project_id>/open-folder")
def open_folder(project_id):
    project = models.get_project(project_id)
    if project is None or not project["folder_path"]:
        abort(404)
    try:
        opened = folders.open_in_explorer(project["folder_path"])
    except folders.FolderError as exc:
        flash(str(exc), "error")
        return redirect(url_for("projects.detail", project_id=project_id))
    flash(
        f"Opened {opened} in Explorer." if opened
        else "Explorer is only available on Windows. The folder is at "
             f"{project['folder_path']}.",
        "success" if opened else "info",
    )
    return redirect(url_for("projects.detail", project_id=project_id))


@bp.post("/<int:project_id>/archive")
def archive(project_id):
    project = models.get_project(project_id)
    if project is None:
        abort(404)
    restoring = project["archived_at"] is not None
    models.archive_project(project_id, archived=not restoring)
    action = "restored" if restoring else "archived"
    activity.log("project", project_id, action, f"{action.title()} {project['name']}")
    flash(
        f"{project['name']} {action}. "
        + ("It is back in the active list." if restoring
           else "Its folder, notes and charge codes are all kept — nothing was deleted."),
        "success",
    )
    return redirect(url_for("projects.detail", project_id=project_id))


# --- workstreams ------------------------------------------------------------


@bp.post("/<int:project_id>/workstreams")
def add_workstream(project_id):
    project = models.get_project(project_id)
    if project is None:
        abort(404)

    fields = _form_fields(request.form, models.WORKSTREAM_WRITABLE)
    fields["project_id"] = project_id
    if not fields.get("name"):
        flash("A workstream needs a name.", "error")
        return redirect(url_for("projects.detail", project_id=project_id, tab="workstreams"))

    workstream_id = models.create_workstream(fields)

    rel = None
    if project["folder_path"]:
        try:
            rel, _abs = folders.provision_workstream(project["folder_path"], fields["name"])
            models.set_workstream_folder(workstream_id, rel)
        except (folders.FolderError, OSError) as exc:
            flash(f"Workstream created, but its folder could not be: {exc}", "warning")

    activity.log("workstream", workstream_id, "created",
                 f"Added workstream {fields['name']} to {project['name']}")
    flash(
        f"Workstream “{fields['name']}” added to {project['name']}"
        + (f", with a folder at {rel}." if rel else "."),
        "success",
    )
    return redirect(url_for("projects.detail", project_id=project_id, tab="workstreams"))


@bp.get("/workstreams/<int:workstream_id>")
def workstream(workstream_id):
    record = models.get_workstream(workstream_id)
    if record is None:
        abort(404)
    inbound, outbound = models.workstream_dependencies(workstream_id)
    return render_template(
        "modules/projects/workstream.html",
        workstream=record,
        inbound=inbound,
        outbound=outbound,
        resources=models.work_resources(workstream_id=workstream_id),
        folder=folders.folder_summary(record["folder_path"]),
        related_records=links.related("workstream", workstream_id),
        trail=activity.for_entity("workstream", workstream_id, limit=15),
        crumbs=[CRUMB,
                (record["project_name"], url_for("projects.detail", project_id=record["project_id"])),
                record["name"]],
    )


# --- locations, resources, dependencies -------------------------------------


@bp.post("/<int:project_id>/locations")
def add_location(project_id):
    if models.get_project(project_id) is None:
        abort(404)

    existing_id = request.form.get("location_id", type=int)
    if existing_id:
        location_id = existing_id
    else:
        fields = _form_fields(request.form, models.LOCATION_WRITABLE)
        if not fields.get("name"):
            flash("A location needs a name.", "error")
            return redirect(url_for("projects.detail", project_id=project_id, tab="locations"))
        location_id = models.create_location(fields)
        activity.log("location", location_id, "created", f"Added location {fields['name']}")

    links.link("project", project_id, "location", location_id)
    name = next((row["name"] for row in models.locations() if row["id"] == location_id), "Location")
    flash(f"{name} linked to this project. One site can serve several projects.", "success")
    return redirect(url_for("projects.detail", project_id=project_id, tab="locations"))


@bp.get("/locations/<int:location_id>/edit")
def edit_location(location_id):
    location = models.get_location(location_id)
    if location is None:
        abort(404)
    project_id = request.args.get("project_id", type=int)
    return render_template(
        "modules/projects/location_edit.html",
        location=location,
        project_id=project_id,
        people=people_models.list_people(limit=1000),
        crumbs=[CRUMB, location["name"]],
    )


@bp.post("/locations/<int:location_id>/edit")
def update_location(location_id):
    location = models.get_location(location_id)
    if location is None:
        abort(404)
    project_id = request.form.get("project_id", type=int)

    fields = _form_fields(request.form, models.LOCATION_WRITABLE)
    if not fields.get("name"):
        flash("A location needs a name.", "error")
        return redirect(url_for("projects.edit_location", location_id=location_id,
                                 project_id=project_id))

    models.update_location(location_id, fields)
    location = models.get_location(location_id)
    activity.log("location", location_id, "updated", f"Updated location {location['name']}")
    flash(f"{location['name']}’s details were updated.", "success")

    if project_id and models.location_linked_to_project(project_id, location_id):
        return redirect(url_for("projects.detail", project_id=project_id, tab="locations"))
    return redirect(url_for("projects.index"))


@bp.post("/<int:project_id>/locations/<int:location_id>/remove")
def remove_location(project_id, location_id):
    project = models.get_project(project_id)
    if project is None:
        abort(404)
    location = models.get_location(location_id)
    name = location["name"] if location else "This location"

    removed = links.unlink("project", project_id, "location", location_id)
    if removed:
        activity.log("project", project_id, "updated",
                     f"Removed location {name} from {project['name']}")
        flash(
            f"{name} removed from this project. The location record itself is kept — "
            "it can still be linked to other projects.",
            "success",
        )
    else:
        flash(f"{name} was not linked to this project.", "warning")
    return redirect(url_for("projects.detail", project_id=project_id, tab="locations"))


@bp.post("/<int:project_id>/resources")
def add_resource(project_id):
    if models.get_project(project_id) is None:
        abort(404)
    fields = _form_fields(request.form, models.RESOURCE_WRITABLE)
    fields["project_id"] = project_id
    if not fields.get("label") or not fields.get("path_or_url"):
        flash("A work resource needs a label and a path or URL.", "error")
        return redirect(url_for("projects.detail", project_id=project_id, tab="locations"))

    resource_id = models.create_work_resource(fields)
    activity.log("work_resource", resource_id, "created",
                 f"Recorded {fields['resource_role']} resource {fields['label']}")
    flash(
        f"“{fields['label']}” recorded as a {fields['resource_role']} resource. "
        "PersonalOS stores the path only, never the contents.",
        "success",
    )
    return redirect(url_for("projects.detail", project_id=project_id, tab="locations"))


@bp.post("/<int:project_id>/resources/verify")
def verify_resources(project_id):
    if models.get_project(project_id) is None:
        abort(404)
    counts = models.verify_work_resources(project_id)
    activity.log("project", project_id, "ran",
                 f"Verified work resources: {counts['ok']} ok, {counts['missing']} missing")
    flash(
        f"{counts['ok']} resource{'s' if counts['ok'] != 1 else ''} found, "
        f"{counts['missing']} missing, "
        f"{counts['not_verifiable']} could not be checked because they are URLs.",
        "warning" if counts["missing"] else "success",
    )
    return redirect(url_for("projects.detail", project_id=project_id, tab="locations"))


@bp.post("/<int:project_id>/dependencies")
def add_dependency(project_id):
    if models.get_project(project_id) is None:
        abort(404)
    fields = _form_fields(request.form, models.DEPENDENCY_WRITABLE)
    fields["project_id"] = project_id
    if not fields.get("title"):
        flash("A dependency needs a title — what is actually needed.", "error")
        return redirect(url_for("projects.detail", project_id=project_id, tab="dependencies"))
    if not fields.get("to_workstream_id") and not fields.get("external_party"):
        flash("Say who it depends on: another workstream, or an external party.", "error")
        return redirect(url_for("projects.detail", project_id=project_id, tab="dependencies"))

    dependency_id = models.create_dependency(fields)
    activity.log("dependency", dependency_id, "created", f"Logged dependency {fields['title']}")
    flash(
        f"Dependency “{fields['title']}” logged. It shows as outbound on the "
        "needing workstream and inbound on the providing one.",
        "success",
    )
    return redirect(url_for("projects.detail", project_id=project_id, tab="dependencies"))


@bp.post("/dependencies/<int:dependency_id>/status")
def dependency_status(dependency_id):
    status = request.form.get("status")
    project_id = request.form.get("project_id", type=int)
    if status not in ("identified", "confirmed", "at_risk", "satisfied", "broken"):
        abort(400)
    models.set_dependency_status(dependency_id, status)
    activity.log("dependency", dependency_id, "updated", f"Dependency marked {status}")
    flash(f"Dependency marked {status.replace('_', ' ')}.", "success")
    return redirect(url_for("projects.detail", project_id=project_id, tab="dependencies"))


@bp.post("/<int:project_id>/team")
def add_team_member(project_id):
    person_id = request.form.get("person_id", type=int)
    if not person_id or models.get_project(project_id) is None:
        abort(400)
    person = people_models.get_person(person_id)
    links.link("project", project_id, "person", person_id,
               request.form.get("role") or None)
    activity.log("project", project_id, "updated", f"Linked {person['full_name']} to the project")
    flash(f"{person['full_name']} linked to this project.", "success")
    return redirect(url_for("projects.detail", project_id=project_id, tab="team"))
