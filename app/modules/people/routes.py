import sqlite3
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from app.core import activity, config, links, paths, rates
from app.core.module_registry import guard_blueprint
from app.core.xlsx import SpreadsheetError

from . import importer, models

bp = Blueprint("people", __name__, url_prefix="/people")
guard_blueprint(bp, "people")

PAGE_SIZE = 50
CRUMB = ("Contacts", "/people")

PERSON_INLINE_FIELDS = {"status", "job_title", "department", "manager_person_id"}


@bp.get("/")
def index():
    as_of = request.args.get("as_of") or date.today().isoformat()
    page = max(request.args.get("page", 1, type=int), 1)
    sort = request.args.get("sort", "name")
    filters = {
        "search": (request.args.get("q") or "").strip() or None,
        "level_id": request.args.get("level_id", type=int),
        "company": request.args.get("company") or None,
        "function": request.args.get("function") or None,
        "import_source": request.args.get("source") or None,
        "unmapped": request.args.get("unmapped") == "1",
        "no_manager": request.args.get("no_manager") == "1",
        "include_archived": request.args.get("archived") == "1",
    }

    total = models.count_people(**filters)
    rows = models.list_people(
        sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE, **filters
    )

    return render_template(
        "modules/people/index.html",
        rows=rows,
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        page_count=max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1),
        sort=sort,
        filters=filters,
        options=models.filter_values(),
        summary=models.roster_summary(),
        unmapped_titles=models.unmapped_titles(),
        transitions=rates.tenure_transitions_due(as_of),
        as_of=as_of,
        people_options=[{"id": p["id"], "label": p["full_name"]}
                        for p in models.list_people(limit=1000)],
        crumbs=[CRUMB[0]],
    )


@bp.get("/<int:person_id>")
def detail(person_id):
    person = models.get_person(person_id)
    if person is None:
        abort(404)

    as_of = request.args.get("as_of") or date.today().isoformat()
    resolved = rates.resolve_rates(person_id, as_of)

    return render_template(
        "modules/people/detail.html",
        person=person,
        tab=request.args.get("tab", "overview"),
        as_of=as_of,
        resolved=resolved,
        history=models.level_history(person_id),
        capacity=models.capacity_rows(person_id),
        statuses=models.status_events(person_id),
        current_status=models.disposition_at(person_id, as_of),
        overrides=rates.overrides_for(person_id),
        reports=models.direct_reports(person_id),
        chain=models.chain_up(person_id),
        involvements=models.involvements_for_person(person_id),
        levels=rates.levels(),
        dispositions=config.options("disposition"),
        related_records=links.related("person", person_id),
        trail=activity.for_entity("person", person_id, limit=15),
        people_options=[{"id": p["id"], "label": p["full_name"]}
                        for p in models.list_people(limit=1000)],
        crumbs=[CRUMB, person["full_name"]],
    )


@bp.post("/<int:person_id>/field")
def update_field(person_id):
    person = models.get_person(person_id)
    if person is None:
        abort(404)
    if person["archived_at"] is not None:
        return {"ok": False, "error": "This contact is archived — restore it first to edit."}

    field = request.form.get("field")
    value = request.form.get("value") or None
    if field not in PERSON_INLINE_FIELDS:
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

    if field == "manager_person_id" and value is not None:
        try:
            value = int(value)
        except ValueError:
            return {"ok": False, "error": "That doesn't look like a valid person."}
        if value == person_id:
            return {"ok": False, "error": "A person can't be their own manager."}
        if models.get_person(value) is None:
            return {"ok": False, "error": "That person no longer exists."}

    try:
        models.update_person(person_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_person(person_id)
    activity.log("person", person_id, "updated", f"Updated {field} for {updated['full_name']}")
    if field == "manager_person_id":
        manager = models.get_person(updated["manager_person_id"]) if updated["manager_person_id"] else None
        display = manager["full_name"] if manager else ""
    else:
        display = updated[field] or ""
    return {"ok": True, "display": display}


@bp.get("/new")
def new():
    return render_template(
        "modules/people/edit.html",
        person=None,
        levels=rates.levels(),
        companies=models.filter_values()["companies"],
        crumbs=[CRUMB, "New contact"],
    )


@bp.get("/<int:person_id>/edit")
def edit(person_id):
    person = models.get_person(person_id)
    if person is None:
        abort(404)
    return render_template(
        "modules/people/edit.html",
        person=person,
        levels=rates.levels(),
        companies=models.filter_values()["companies"],
        crumbs=[CRUMB, (person["full_name"], url_for("people.detail", person_id=person_id)),
                "Edit"],
    )


@bp.post("/save")
def save():
    person_id = request.form.get("person_id", type=int)
    fields = {key: (value.strip() or None) for key, value in request.form.items()
              if key in models.WRITABLE}
    if request.form.get("level_id"):
        fields["level_id"] = request.form.get("level_id", type=int)

    if not fields.get("last_name"):
        flash("A contact needs at least a last name.", "error")
        return redirect(request.referrer or url_for("people.index"))

    email = fields.get("email")
    if email:
        clash = models.by_email(email)
        if clash and clash["id"] != person_id:
            flash(
                f"{clash['full_name']} already uses {email}. "
                "Two contacts cannot share an address.",
                "error",
            )
            return redirect(request.referrer or url_for("people.index"))

    if person_id:
        models.update_person(person_id, fields)
        person = models.get_person(person_id)
        activity.log("person", person_id, "updated",
                     f"Updated {person['full_name']}", {"fields": sorted(fields)})
        flash(f"{person['full_name']} updated.", "success")
    else:
        fields.setdefault("import_source", "manual")
        person_id = models.create_person(fields)
        person = models.get_person(person_id)
        activity.log("person", person_id, "created", f"Added {person['full_name']}")
        flash(
            f"{person['full_name']} added"
            + (f" as {person['level_label']}." if person["level_label"] else "."),
            "success",
        )
    return redirect(url_for("people.detail", person_id=person_id))


@bp.post("/<int:person_id>/archive")
def archive(person_id):
    person = models.get_person(person_id)
    if person is None:
        abort(404)
    restoring = person["archived_at"] is not None
    models.archive_person(person_id, archived=not restoring)
    action = "restored" if restoring else "archived"
    activity.log("person", person_id, action, f"{action.title()} {person['full_name']}")
    flash(
        f"{person['full_name']} {action}. "
        + ("They appear in lists again." if restoring
           else "Their record and every link to it are kept."),
        "success",
    )
    return redirect(url_for("people.detail", person_id=person_id))


@bp.post("/<int:person_id>/level")
def change_level(person_id):
    person = models.get_person(person_id)
    if person is None:
        abort(404)

    level_id = request.form.get("level_id", type=int)
    effective_from = request.form.get("effective_from")
    reason = request.form.get("reason", "promotion")
    if not level_id or not effective_from:
        flash("A level change needs a level and an effective date.", "error")
        return redirect(url_for("people.detail", person_id=person_id, tab="rates"))

    models.record_level_change(person_id, level_id, effective_from, reason,
                               request.form.get("note") or None)
    updated = models.get_person(person_id)
    resolved = rates.resolve_rates(person_id, effective_from)
    activity.log("person", person_id, "updated",
                 f"{person['full_name']} recorded as {updated['level_label']} "
                 f"from {effective_from} ({reason})",
                 {"reason": reason, "effective_from": effective_from})
    flash(
        f"{updated['full_name']} is {updated['level_label']} from {effective_from}. "
        + (f"Hours on or after that date price at ${resolved.engagement_rate:,.2f}."
           if resolved.is_priced
           else "No rate card covers that level yet, so those hours are unpriced."),
        "success",
    )
    return redirect(url_for("people.detail", person_id=person_id, tab="rates"))


@bp.post("/<int:person_id>/capacity")
def add_capacity(person_id):
    if models.get_person(person_id) is None:
        abort(404)
    weekly = request.form.get("weekly_hours", type=float)
    fte = request.form.get("fte", type=float)
    effective_from = request.form.get("effective_from")
    if weekly is None or not effective_from:
        flash("Capacity needs weekly hours and an effective date.", "error")
        return redirect(url_for("people.detail", person_id=person_id, tab="capacity"))

    models.add_capacity(person_id, weekly, fte if fte is not None else 1.0,
                        effective_from, request.form.get("note") or None)
    activity.log("person", person_id, "updated",
                 f"Capacity set to {weekly:g}h/week from {effective_from}")
    flash(f"Capacity set to {weekly:g} hours a week from {effective_from}.", "success")
    return redirect(url_for("people.detail", person_id=person_id, tab="capacity"))


@bp.post("/<int:person_id>/status")
def add_status(person_id):
    person = models.get_person(person_id)
    if person is None:
        abort(404)
    disposition = request.form.get("disposition")
    start_date = request.form.get("start_date")
    if not disposition or not start_date:
        flash("A disposition needs a status and a start date.", "error")
        return redirect(url_for("people.detail", person_id=person_id, tab="capacity"))

    end_date = request.form.get("end_date") or None
    models.add_status_event(person_id, disposition, start_date, end_date,
                            request.form.get("detail") or None)
    label = config.option_label("disposition", disposition)
    activity.log("person", person_id, "updated",
                 f"{person['full_name']} marked {label} from {start_date}")
    flash(
        f"{person['full_name']} is {label} from {start_date}"
        + (f" to {end_date}." if end_date else ", with no end date set."),
        "success",
    )
    return redirect(url_for("people.detail", person_id=person_id, tab="capacity"))


@bp.post("/<int:person_id>/override")
def add_override(person_id):
    person = models.get_person(person_id)
    if person is None:
        abort(404)
    bill = request.form.get("bill_rate", type=float)
    cost = request.form.get("cost_rate", type=float)
    effective_from = request.form.get("effective_from")
    if bill is None or not effective_from:
        flash("A rate override needs at least a bill rate and an effective date.", "error")
        return redirect(url_for("people.detail", person_id=person_id, tab="rates"))

    from app.core.database import get_db

    db = get_db()
    db.execute(
        "INSERT INTO person_rate_overrides "
        "(person_id, bill_rate, cost_rate, effective_from, effective_to, reason) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (person_id, bill, cost, effective_from,
         request.form.get("effective_to") or None,
         request.form.get("reason") or None),
    )
    db.commit()
    activity.log("person", person_id, "created",
                 f"Rate override for {person['full_name']}: ${bill:,.2f} from {effective_from}")
    flash(
        f"{person['full_name']} now prices at ${bill:,.2f} an hour from {effective_from}, "
        "ahead of any rate card.",
        "success",
    )
    return redirect(url_for("people.detail", person_id=person_id, tab="rates"))


# --- job title map ----------------------------------------------------------


@bp.get("/titles")
def titles():
    return render_template(
        "modules/people/titles.html",
        mappings=models.title_map(),
        unmapped=models.unmapped_titles(),
        levels=rates.levels(),
        functions=config.options("function"),
        crumbs=[CRUMB, "Job titles"],
    )


@bp.post("/titles/<int:map_id>")
def save_title(map_id):
    level_id = request.form.get("level_id", type=int)
    if not level_id:
        abort(400)
    models.set_title_mapping(map_id, level_id, request.form.get("function") or None,
                             request.form.get("is_specialist") == "1")
    changed = models.apply_title_map(only_unmapped=False)
    activity.log("job_title_map", map_id, "updated",
                 f"Title mapping changed; {changed} contact(s) re-levelled")
    flash(
        f"Mapping saved. {changed} contact{'s' if changed != 1 else ''} re-levelled. "
        "Anything already priced under the old mapping needs re-pricing.",
        "success",
    )
    return redirect(url_for("people.titles"))


@bp.post("/resolve-managers")
def resolve_managers():
    linked, unresolved = models.resolve_manager_links()
    activity.log("people", None, "updated",
                 f"Resolved {linked} manager link(s)")
    if linked:
        flash(
            f"Linked {linked} contact{'s' if linked != 1 else ''} to their manager. "
            + (f"{len(unresolved)} manager address{'es' if len(unresolved) != 1 else ''} "
               "are not in the database yet." if unresolved else "Every manager resolved."),
            "success",
        )
    else:
        flash(
            "No new manager links. "
            + (f"{len(unresolved)} manager address(es) are still missing from the database."
               if unresolved else "Every contact with a manager email is already linked."),
            "info",
        )
    return redirect(request.referrer or url_for("people.index"))


# --- import wizard ----------------------------------------------------------


def _candidate_files():
    """Spreadsheets in the inbox or sitting at the application root.

    Each is hashed and checked against `import_batches`, so the page can say
    "already loaded on 14 Nov" before you click anything rather than after.
    Hashing a few hundred kilobytes is immaterial; hashing a large timesheet
    export would not be, which is why the timesheet importer at Phase 9 will
    check size and mtime first.
    """
    from app.core.xlsx import file_sha256

    found = []
    for folder in (paths.INBOX_DIR, paths.APP_ROOT):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.xlsx")):
            if path.name.startswith("~$"):
                continue  # Excel lock file
            try:
                prior = importer.previous_batch(file_sha256(path))
            except OSError:
                prior = None
            found.append({
                "path": str(path),
                "name": path.name,
                "where": "inbox" if folder == paths.INBOX_DIR else "application folder",
                "size": path.stat().st_size,
                "prior": prior,
            })
    return found


@bp.get("/import")
def import_select():
    return render_template(
        "modules/people/import_select.html",
        files=_candidate_files(),
        columns=importer.COLUMN_MAP,
        history=importer.history(),
        crumbs=[CRUMB, "Import contacts"],
    )


@bp.post("/import/preview")
def import_preview():
    source = request.form.get("path")
    upload = request.files.get("file")

    if upload and upload.filename:
        if not upload.filename.lower().endswith(".xlsx"):
            flash("Only .xlsx files can be imported.", "error")
            return redirect(url_for("people.import_select"))
        paths.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        target = paths.confine(paths.INBOX_DIR, paths.safe_slug(upload.filename[:-5]) + ".xlsx")
        upload.save(target)
        source = str(target)

    if not source:
        flash("Choose a file to import.", "error")
        return redirect(url_for("people.import_select"))

    try:
        plan = importer.preview(source)
    except SpreadsheetError as exc:
        flash(f"Could not read that file: {exc}", "error")
        return redirect(url_for("people.import_select"))

    return render_template(
        "modules/people/import_preview.html",
        plan=plan,
        crumbs=[CRUMB, ("Import contacts", url_for("people.import_select")), "Preview"],
    )


@bp.post("/import/commit")
def import_commit():
    source = request.form.get("path")
    expected = request.form.get("sha256")
    if not source or not expected:
        abort(400)

    try:
        plan = importer.preview(source)
    except SpreadsheetError as exc:
        flash(f"Could not read that file: {exc}", "error")
        return redirect(url_for("people.import_select"))

    # The preview is regenerated rather than carried through the session, so
    # what gets written is what was on screen. If the file moved underneath,
    # refuse rather than import something the preview never showed.
    if plan["sha256"] != expected:
        flash(
            "That file changed since you previewed it. Nothing was imported — "
            "preview it again.",
            "error",
        )
        return redirect(url_for("people.import_select"))

    if plan["already_imported"]:
        prior = plan["prior"]
        flash(
            f"{plan['file_name']} was already loaded on "
            f"{prior['imported_at'][:10]} — {prior['rows_imported']} row(s). "
            "This is a one-time load, so nothing was written. To load a refreshed "
            "extract, export it again; a changed file has a different content hash.",
            "info",
        )
        return redirect(url_for("people.index"))

    if not plan["create"] and not plan["update"]:
        flash(
            f"Nothing to import — all {plan['counts']['read']} rows already match "
            "what is in the database.",
            "info",
        )
        return redirect(url_for("people.index"))

    try:
        result = importer.commit(plan)
    except importer.AlreadyImported:
        flash(
            f"{plan['file_name']} was already loaded. Nothing was written — the "
            "database refuses a second load of the same file.",
            "info",
        )
        return redirect(url_for("people.index"))
    activity.log(
        "people", None, "imported",
        f"Imported {result['created']} new and updated {result['updated']} "
        f"contact(s) from {source.rsplit('/', 1)[-1]}",
        {"sha256": result["sha256"], **result},
    )

    parts = []
    if result["created"]:
        parts.append(f"{result['created']} added")
    if result["updated"]:
        parts.append(f"{result['updated']} updated")
    if result["unchanged"]:
        parts.append(f"{result['unchanged']} unchanged")
    detail = ", ".join(parts)

    flash(
        f"Imported {detail}. {result['levels_mapped']} levelled from job title, "
        f"{result['managers_linked']} linked to a manager"
        + (f", {result['managers_unresolved']} manager address(es) not yet in the database."
           if result["managers_unresolved"] else "."),
        "success",
    )
    return redirect(url_for("people.index"))
