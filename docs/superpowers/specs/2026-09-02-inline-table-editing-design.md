# Inline Table Editing — Design

## Context

Every list of records in PersonalOS (`.pos-table`, per `docs/UI_DESIGN_SYSTEM.md` §3.5) currently requires navigating to a full Edit page to change even a single field — e.g. bumping a task's status, correcting a person's job title, or reassigning a workstream lead all mean leaving the list, opening a form, and coming back. The recent UX/CRUD audit (see the merged branches from `worktree-agent-*`, now on `main`) filled in missing CRUD operations across the app but didn't address this friction. The user asked for inline editing "for all tables of records" — both the main per-module list pages and the smaller record tables embedded in detail pages (Team members, Locations, Dependencies, Work Resources, etc.).

This spec covers the mechanism and scope for click-a-cell, spreadsheet-style inline editing, applied consistently across every `.pos-table` that lists editable records.

## Non-goals

- Does **not** replace any existing full Edit page/form — those remain the complete-record view and the only path for fields not exposed in a table column.
- Does **not** cover long-text fields (notes, descriptions) — editing those inline in a table cell is a bad interaction; they stay on the full edit form.
- Does **not** cover containment-changing relationships (a project's `portfolio_id`, a workstream's `project_id`, a task's `project_id`/`workstream_id`, a charge code's `project_id`) — reassigning what a record belongs to is a structural action per CLAUDE.md rule 9 (hard FKs for containment), not a quick inline edit.
- Does **not** cover the Team-tab-style role-linking rows (`entity_links` add/remove flows) — those already have their own dedicated add/remove forms from the recent CRUD work and aren't simple scalar fields.
- Does **not** add bulk/multi-cell editing, undo, or offline queuing. Single-user local app; each edit is a single independent POST.

## Architecture

**One new route per module**, not a generic core helper. Every module that has a `WRITABLE` allowlist and an `update_<record>()` function (all of them, post-audit) gets one additional thin route:

```
POST /<module-prefix>/<id>/field
```

e.g. `POST /tasks/42/field`, `POST /projects/7/field`, `POST /projects/workstreams/12/field`, `POST /people/3/field`.

Request body: `field` (the column name) and `value` (the new value, as submitted by the form-encoded POST — same encoding the existing save routes already use).

Route behavior (mirrors the existing full-save route's validation, minus the parts that only apply to a full form):
1. Look up the record; 404 if it doesn't exist.
2. Reject if the record is archived (see "Archived rows" below) — flash-equivalent JSON error, no mutation.
3. Reject if `field not in WRITABLE` (or the module's specific `*_WRITABLE` constant, e.g. `WORKSTREAM_WRITABLE`) — this is the same allowlist check the full save route already does, so no new validation surface. Column names are never taken from the request as raw SQL identifiers; only `field` values that match a name already in the developer-defined `WRITABLE` tuple are used.
4. Apply the same type/enum validation the full save route applies to that field today (e.g. a `status` value must be one of the CHECK-constrained options; a date must parse; a person-picker value must resolve to an existing, non-archived person).
5. On success: call the module's existing `update_<record>(id, {field: value})`, call `activity.log(...)` exactly as the full edit route does (one entry per saved field — no batching), and return `{"ok": true, "display": "<rendered text for the cell>"}`. `display` is the human-readable text the cell should now show (e.g. a person's name for an `assignee_person_id` field, not the raw id) — computed server-side so the client never has to duplicate lookup logic.
6. On failure: return `{"ok": false, "error": "<specific message>"}` (HTTP 200 with an error body, not a 4xx, so the client's generic fetch-error handling doesn't need a special case) naming the actual problem, per P2 (no generic "Save failed").

This reuses each module's existing, already-tested `update_<record>()` and validation logic rather than introducing a new generic SQL-building layer — keeping validation where it already lives, consistent with the module-isolation rule (`app/modules/<name>/models.py` owns its own queries; no cross-module imports).

## Frontend: one shared component, declarative per table

New file: `app/static/js/inline-edit.js` (vanilla JS, loaded on every page alongside `app.js`, per CLAUDE.md's "vanilla only, no build step" rule).

**Opt-in contract**, set in each `.pos-table`'s markup by the module template — no JS configuration needed per table:

- `<table class="pos-table" data-edit-base="/tasks/{id}/field">` — the table declares its per-row endpoint template; `{id}` is substituted per row from `data-record-id` on each `<tr>`.
- `<tr data-record-id="42" data-archived="0">` — each editable row carries its id and archived state.
- `<td data-field="status" data-type="select" data-options="open,in_progress,blocked,done">` — a plain-text-backed select; `data-options` is a comma-separated value list read from the same `config.options(...)` vocabulary the full edit form already uses (rendered server-side into the attribute, not fetched separately).
- `<td data-field="assignee_person_id" data-type="fk-select" data-options-src="#people-options">` — an FK-picker cell; `data-options-src` points at a `<script type="application/json" id="people-options">[{"id":3,"label":"Ada Lovelace"}, ...]</script>` block rendered **once** per page (not per cell, not per row) so a table of 50 tasks doesn't re-fetch or re-embed the people list 50 times.
- `<td data-field="due_date" data-type="date">`, `<td data-field="estimate_hours" data-type="number">`, `<td data-field="title" data-type="text">` — plain scalar types, no options needed.
- A `<td>` with no `data-field` attribute is not editable (e.g. computed columns, IDs, containment FKs) — the click handler only attaches to annotated cells.

**Interaction**, delegated from a single document-level click/keydown listener (matching `app.js`'s existing pattern of delegated listeners rather than per-element handlers):

1. Click (or `Enter`/`Space` when focused via Tab) on an editable, non-archived cell → replace its rendered content with the appropriate input (`<input type="text">`, `<input type="date">`, `<input type="number">`, or `<select>` populated from `data-options`/`data-options-src`), pre-filled with the current value, and focus it.
2. `Enter` or blur → POST to the row's resolved endpoint (`data-edit-base` with `{id}` substituted) with `field`/`value`. While pending, the cell shows a subtle busy state (no full-page spinner). `Tab` behaves like Enter (commit) and then moves focus to the next editable cell — the browser's natural tab order, not a custom loop.
3. On `{ok: true}` → replace the cell with the returned `display` text, briefly flash a saved indicator (text/icon, not color alone), done.
4. On `{ok: false}` or a network error → revert the input's value to what was last saved, keep it in edit mode, show the `error` message inline (small text under/beside the cell, plus an outline — not color alone) so the user can correct and retry without losing their place.
5. `Escape` → revert to the last-saved value and exit edit mode without saving, no request sent.

This is a spreadsheet-style, per-field-independent save model: nothing is buffered across cells, each field commits on its own.

## Archived rows are read-only

A row with `data-archived="1"` never attaches edit handlers — clicking does nothing (cursor stays default, no visual affordance suggesting it's editable). This matches the existing pattern where several modules already suppress mutation actions on archived records, and avoids a confusing "I edited it but nothing happened until I restored it first" moment.

## Activity logging

Every successful inline save calls `activity.log(...)` exactly once, immediately, the same way the full edit route does — no debouncing or batching that would blur the audit trail. Rapidly editing five cells in a row produces five activity entries, matching what five separate full-form edits would have produced.

## Scope: which tables, which columns

Applies to every `.pos-table` across the app that lists editable records — both module index pages and detail-page sub-tables. The exact editable-column set per table is **the subset of that module's `WRITABLE` (or `*_WRITABLE`) constant that is already rendered as a column in that particular table today** — this spec doesn't hardcode a column list per table (templates already decide what's shown; inline-edit opt-in is annotating those existing columns, not adding new ones). Representative examples, grounded in the actual `WRITABLE` constants read from the codebase:

| Table | Inline-editable examples | Stays on full edit page |
|---|---|---|
| Tasks index/detail | `status`, `priority`, `due_date`, `estimate_hours`, `assignee_person_id` (fk-select) | `description`, `project_id`/`workstream_id`/`charge_code_id` (containment) |
| Projects index/detail | `status`, `priority`, `rag_status`, `forecast_end`, `lead_partner_person_id`/`engagement_manager_person_id`/`project_lead_person_id` (fk-select) | `description`, `portfolio_id` (containment), budget fields (money math — stays on the form that shows the full budget picture together) |
| Workstreams (project detail sub-table) | `status`, `lead_person_id` (fk-select), `forecast_end` | `project_id` (containment), `description` |
| People (Contacts) index/detail | `status`, `job_title`, `department`, `manager_person_id` (fk-select) | `notes`, `strengths`, `development_areas` (long text) |
| Portfolios index | `portfolio_kind`, `sort_order` | `description` |
| Charge Codes index/detail | `status`, `opened_on`/`closed_on`, `lead_partner_person_id`/`engagement_manager_person_id` (fk-select) | `project_id`/`workstream_id` (containment), budget fields |
| Locations (project detail sub-table) | `location_kind`, `site_contact_person_id` (fk-select), `access_notes`→ excluded (long text) | address fields (multi-field, stays on the dedicated edit form added in the CRUD audit) |
| Work Resources (project detail sub-table) | `label`, `resource_kind`, `owner_person_id` (fk-select) | `path_or_url`, `description` |
| Dependencies (project detail sub-table) | `status`, `criticality`, `needed_by_date`, `owner_person_id` (fk-select) | `title`, `description` (already has a dedicated edit form) |

Money/budget fields are intentionally excluded from inline editing everywhere — CLAUDE.md rule 8 requires all money math go through `resolve_rates()`, and a table cell isn't the place to show that context; budget edits stay on the full form where the fee/hours/rate-card relationship is visible together.

## Verification

No automated test suite exists in this repo (per CLAUDE.md). Verification is manual, per module, following the same pattern used for the CRUD audit fixes:
1. `health_check.py` / `verify_docs.py` after each module's change — must stay clean.
2. Start the dev server, and for each new `/field` route: `curl`/PowerShell POST a valid field change, confirm the JSON response and that the value persisted (re-`GET` the page or check the DB directly); POST an invalid value (bad enum, non-existent FK id) and confirm a specific `{"ok": false, "error": ...}` response, not a 500.
3. If Playwright is available at implementation time, drive the actual click-to-edit interaction in a real page for at least one representative table per field type (text, select, date, number, fk-select) to confirm the JS component itself works, not just the backend route — this is the one part of this feature that can't be fully verified via curl alone.
4. Confirm an archived row's cells do not attach edit handlers (inspect the rendered HTML for the `data-archived="1"` attribute and confirm no click behavior).

## Rollout

Implemented as one shared JS file (`inline-edit.js`) plus one work unit per module (mirroring the structure of the earlier CRUD-audit batch): each unit adds that module's `/field` route(s), extends templates with the `data-*` annotations described above for its table(s), and verifies per the steps above. Modules in scope: Portfolios, Projects (incl. Workstreams, Locations, Work Resources, Dependencies sub-tables), Tasks, People, Charge Codes. Rate Cards and Activity Log are excluded — rate card entries are versioned/append-only by design, and the Activity Log is deliberately read-only.
