"""The workstream charter.

Generated when a workstream is created, so anybody onboarding has one document
that answers where the work happens, who is on it, what it depends on and what
"done" looks like.

Half its content is database-owned and half is prose somebody wrote. Managed
blocks are what let both live in one file: the tables refresh, the prose does
not. A team list that was accurate two weeks ago is actively misleading to a
new joiner — worse than no list at all.

See docs/TEMPLATE_LIBRARY.md §8A and docs/NOTES_VAULT_SPEC.md §5A.
"""
from app.core import markdown as md
from app.core.database import get_db

BLOCKS = ("team", "milestones", "dependencies", "locations", "resources")

PLACEHOLDER = "_Nothing recorded yet._"

TEMPLATE = """---
title: {name} — Workstream Charter
type: charter
project: {project_slug}
workstream: {workstream_slug}
tags: [charter, onboarding]
---

# {name}

> The first thing to read when joining this workstream. Sections marked
> *live* are refreshed by PersonalOS; everything else is written by hand and is
> never overwritten.

## 1. Objective and problem statement

_What is this workstream for, and what problem does it solve? Two or three
sentences that would make sense to somebody who joined this morning._

## 2. People — *live*

<!-- personalos:team -->
{PLACEHOLDER}
<!-- /personalos:team -->

### Who to ask about what

_Name the person behind each area. This is the part a new joiner actually
needs, and it is the part no table can generate._

## 3. Milestones and deadlines — *live*

<!-- personalos:milestones -->
{PLACEHOLDER}
<!-- /personalos:milestones -->

## 4. Major tasks

_The five to ten pieces of work that make up this workstream. Detail lives in
the task list; this is the shape of it._

## 5. Key dependencies — *live*

Dependencies **across** workstreams matter more than the ones inside this one,
because nobody owns the gap between two teams by default.

<!-- personalos:dependencies -->
{PLACEHOLDER}
<!-- /personalos:dependencies -->

## 6. Assumptions and things to consider

_What are we taking as given? Each one that turns out to be wrong is a change
request, so write them down while they still feel too obvious to mention._

## 7. Work locations — *live*

### Physical sites

<!-- personalos:locations -->
{PLACEHOLDER}
<!-- /personalos:locations -->

### Folders, files, scripts and channels

<!-- personalos:resources -->
{PLACEHOLDER}
<!-- /personalos:resources -->

## 8. Validation checks

_How do we know the output is right? List the checks, who runs them, and how
often. A checklist here beats a table in the database because these vary too
much between engagements to model._

- [ ]
- [ ]

## 9. Anything else worth knowing

_Client quirks, standing meetings, escalation paths, the thing that caught out
the last person._
"""


def initial_content(workstream, project, project_slug, workstream_slug):
    return TEMPLATE.format(
        name=workstream["name"],
        project_slug=project_slug,
        workstream_slug=workstream_slug,
        PLACEHOLDER=PLACEHOLDER,
    )


# --- block rendering --------------------------------------------------------


def _table(headers, rows):
    if not rows:
        return PLACEHOLDER
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        cells = [str(cell).replace("|", "\\|") if cell not in (None, "") else "—"
                 for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_blocks(workstream_id):
    """Build every managed block for one workstream from live data."""
    db = get_db()
    workstream = db.execute(
        "SELECT w.*, p.id AS project_id FROM workstreams w "
        "JOIN projects p ON p.id = w.project_id WHERE w.id = ?",
        (workstream_id,),
    ).fetchone()
    if workstream is None:
        return {}

    project_id = workstream["project_id"]

    team = db.execute(
        "SELECT pe.full_name, pe.job_title, l.label AS level_label, pe.company, "
        "       COALESCE(pe.city, pe.location) AS place, el.link_label, pe.email "
        "FROM entity_links el JOIN people pe ON pe.id = el.target_id "
        "LEFT JOIN person_levels l ON l.id = pe.level_id "
        "WHERE el.source_type = 'project' AND el.source_id = ? "
        "  AND el.target_type = 'person' AND pe.archived_at IS NULL "
        "ORDER BY l.sort_order DESC, pe.full_name",
        (project_id,),
    ).fetchall()

    milestones = db.execute(
        "SELECT name, forecast_end, status FROM workstreams WHERE id = ?", (workstream_id,)
    ).fetchall()

    inbound = db.execute(
        "SELECT d.title, d.dependency_type, d.criticality, d.needed_by_date, d.status, "
        "       COALESCE(tw.name, d.external_party) AS provider "
        "FROM dependencies d LEFT JOIN workstreams tw ON tw.id = d.to_workstream_id "
        "WHERE d.from_workstream_id = ? AND d.archived_at IS NULL "
        "ORDER BY d.needed_by_date IS NULL, d.needed_by_date",
        (workstream_id,),
    ).fetchall()

    locations = db.execute(
        "SELECT l.name, l.building, l.floor, l.room, "
        "       l.address_line1 || COALESCE(', ' || l.city, '') AS address, l.access_notes "
        "FROM locations l JOIN entity_links el "
        "  ON el.target_type = 'location' AND el.target_id = l.id "
        "WHERE ((el.source_type = 'workstream' AND el.source_id = ?) "
        "    OR (el.source_type = 'project' AND el.source_id = ?)) "
        "  AND l.archived_at IS NULL ORDER BY l.name",
        (workstream_id, project_id),
    ).fetchall()

    resources = db.execute(
        "SELECT label, resource_role, resource_kind, path_or_url, verify_status "
        "FROM work_resources WHERE (workstream_id = ? OR project_id = ?) AND is_active = 1 "
        "ORDER BY resource_role, sort_order, label",
        (workstream_id, project_id),
    ).fetchall()

    return {
        "team": _table(
            ["Name", "Title", "Level", "Company", "Location", "Role", "Email"],
            [(r["full_name"], r["job_title"], r["level_label"], r["company"],
              r["place"], r["link_label"], r["email"]) for r in team],
        ),
        "milestones": _table(
            ["Milestone", "Forecast", "Status"],
            [(r["name"], r["forecast_end"], r["status"]) for r in milestones],
        ),
        "dependencies": _table(
            ["Needs", "From", "Type", "Criticality", "Needed by", "Status"],
            [(r["title"], r["provider"], r["dependency_type"], r["criticality"],
              r["needed_by_date"], r["status"]) for r in inbound],
        ),
        "locations": _table(
            ["Site", "Building", "Floor", "Room", "Address", "Access"],
            [(r["name"], r["building"], r["floor"], r["room"], r["address"],
              r["access_notes"]) for r in locations],
        ),
        "resources": _table(
            ["Resource", "Role", "Kind", "Path or URL", "Last check"],
            [(r["label"], r["resource_role"], r["resource_kind"], r["path_or_url"],
              r["verify_status"] or "unchecked") for r in resources],
        ),
    }


def refresh(text, workstream_id):
    """Replace every managed block. Returns (new_text, names changed, warnings).

    A block whose closing marker was removed is reported and skipped — never
    guessed at, because guessing means overwriting the rest of the file.
    """
    blocks = render_blocks(workstream_id)
    present, unbalanced = md.find_blocks(text)
    updated, changed = md.refresh_blocks(text, {k: v for k, v in blocks.items()
                                                if k in present})

    warnings = []
    for name in unbalanced:
        warnings.append(f"the “{name}” block is missing one of its markers, so it was skipped")
    for name in blocks:
        if name not in present and name not in unbalanced:
            warnings.append(f"there is no “{name}” block in this note, so it was not updated")
    return updated, changed, warnings
