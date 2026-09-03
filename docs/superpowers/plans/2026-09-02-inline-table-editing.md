# Inline Table Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every editable record table in PersonalOS support click-a-cell inline editing, so common field changes (status, dates, simple lookups) don't require leaving the list for a full Edit page.

**Architecture:** One shared vanilla-JS component (`app/static/js/inline-edit.js`) reads declarative `data-*` attributes on `<table>`/`<tr>`/`<td>` elements and POSTs field changes to one new thin route per module (`POST /<module-prefix>/<id>/field`), each of which reuses that module's existing `update_<record>()` function and `WRITABLE` allowlist, and returns JSON.

**Tech Stack:** Flask 3.x, stdlib `sqlite3` (no ORM), Jinja2 (autoescaping on), vanilla JS (no build step), Bootstrap 5.3 (already vendored).

## Global Constraints

- Parameterized queries only; column names passed to SQL are never taken from request data — only checked against a developer-defined `WRITABLE`/`*_WRITABLE` tuple already in each module's `models.py`.
- Every state change is a `POST`.
- Every successful field save calls `activity.log(...)` exactly once (no batching).
- Inline edit never applies to archived/inactive rows, containment FKs (`portfolio_id`, `project_id` on workstreams/tasks/charge codes, etc.), long-text fields, or money/budget fields — these stay on the existing full edit forms.
- No automated test suite exists in this repo. Verification is `python health_check.py` (must show 0 new failures beyond the existing 4 pre-existing optional-dependency warnings) and `python verify_docs.py` (must exit 0) after every task, plus a manual `curl`/PowerShell smoke test of each new route against a running `python run.py` dev server.
- No `| safe` on user content; Jinja's `| tojson` filter is used wherever a value is embedded into an inline `<script type="application/json">` block, so it's correctly escaped (this also sidesteps the apostrophe-breaks-JS bug class found elsewhere in this codebase's `onsubmit="confirm('...')"` patterns).
- Every module's blueprint already calls `guard_blueprint(bp, "<module_key>")` — new routes automatically inherit the disabled-module 404 gate; nothing extra needed per route.
- Follow the module isolation rule: `app/modules/<name>/routes.py` and `models.py` may only be edited within that module; no cross-module imports beyond what already exists in each file.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/static/js/inline-edit.js` (new) | The shared click-to-edit component: builds the right input type, POSTs via `fetch`, handles success/error/keyboard. |
| `app/static/css/personalos.css` (modify) | Small addition: `.pos-inline-input`, `.pos-inline-error`, `.pos-inline-error-msg`, `.pos-inline-busy` rules. |
| `app/templates/base.html` (modify) | One new `<script>` tag loading `inline-edit.js`. |
| `app/modules/portfolios/routes.py` (modify) | `POST /portfolios/<id>/field`. |
| `app/modules/portfolios/models.py` (modify) | None needed — `update_portfolio`/`WRITABLE` already exist. |
| `app/templates/modules/portfolios/index.html`, `detail.html` (modify) | `data-*` annotations on the portfolios table. |
| `app/modules/projects/routes.py` (modify, across 5 tasks) | `POST /projects/<id>/field`, `POST /projects/workstreams/<id>/field`, `POST /projects/locations/<id>/field`, `POST /projects/<project_id>/resources/<id>/field`, `POST /projects/dependencies/<id>/field`. |
| `app/templates/modules/projects/index.html`, `detail.html`, `workstream.html` (modify, across 5 tasks) | `data-*` annotations on the projects, workstreams, locations, resources, and dependencies tables. |
| `app/modules/tasks/routes.py` (modify) | `POST /tasks/<id>/field`. |
| `app/templates/modules/tasks/index.html`, `detail.html` (modify) | `data-*` annotations. |
| `app/modules/people/routes.py` (modify) | `POST /people/<id>/field`. |
| `app/templates/modules/people/index.html`, `detail.html` (modify) | `data-*` annotations. |
| `app/modules/charge_codes/routes.py` (modify) | `POST /charge-codes/<id>/field`. |
| `app/templates/modules/charge_codes/index.html`, `detail.html` (modify) | `data-*` annotations. |

---

## Task 1: Shared inline-edit JS component + CSS + base wiring

**Files:**
- Create: `app/static/js/inline-edit.js`
- Modify: `app/static/css/personalos.css` (append to the end of section "9. Tables")
- Modify: `app/templates/base.html:42-44`

**Interfaces (produced, for every later task to consume):**
- HTML contract read by the script:
  - `<table data-edit-base="/prefix/{id}/field">` — `{id}` is replaced with the row's `data-record-id`.
  - `<tr data-record-id="42" data-archived="0">` — `data-archived="1"` disables editing for that row entirely.
  - `<td data-field="status" data-type="select" data-options="open,in_progress,done" tabindex="0">Open</td>` — a plain select.
  - `<td data-field="assignee_person_id" data-type="fk-select" data-options-src="#people-options" data-value="7" tabindex="0">Ada Lovelace</td>` — an FK-picker; `data-value` carries the raw id (the visible text is the display name, not usable as the select's current value).
  - `<td data-field="due_date" data-type="date" tabindex="0">2026-09-10</td>`, `data-type="number"`, `data-type="text"` — plain scalar types.
  - A `<script type="application/json" id="people-options">[{"id":7,"label":"Ada Lovelace"}, ...]</script>` block rendered once per page, referenced by `data-options-src="#people-options"`.
- No JS function from this file is called directly by other files — it's a self-contained IIFE attached via delegated `document` listeners, activated purely by the markup above.

- [ ] **Step 1: Write `app/static/js/inline-edit.js`**

```javascript
/* PersonalOS — inline table editing.
 *
 * Any <td data-field="..."> inside a <table data-edit-base="..."> becomes a
 * click-to-edit cell. Each field saves independently on commit (Enter, Tab,
 * or blur) via a POST to the table's edit-base with {id} substituted from
 * the row's data-record-id. See docs/superpowers/specs/2026-09-02-inline-table-editing-design.md.
 */
(function () {
  "use strict";

  function optionsFromSrc(selector) {
    var el = document.querySelector(selector);
    if (!el) return [];
    try {
      return JSON.parse(el.textContent);
    } catch (err) {
      return [];
    }
  }

  function buildInput(td) {
    var type = td.dataset.type;
    var currentValue = td.dataset.value !== undefined ? td.dataset.value : td.textContent.trim();
    var input;

    if (type === "select" || type === "fk-select") {
      input = document.createElement("select");
      var blank = document.createElement("option");
      blank.value = "";
      blank.textContent = "—";
      input.appendChild(blank);

      var opts;
      if (type === "select") {
        opts = (td.dataset.options || "")
          .split(",")
          .filter(function (o) { return o !== ""; })
          .map(function (o) { return { id: o, label: o }; });
      } else {
        opts = optionsFromSrc(td.dataset.optionsSrc);
      }
      opts.forEach(function (o) {
        var opt = document.createElement("option");
        opt.value = String(o.id);
        opt.textContent = o.label;
        if (String(o.id) === String(currentValue)) opt.selected = true;
        input.appendChild(opt);
      });
    } else {
      input = document.createElement("input");
      input.type = type === "number" ? "number" : type === "date" ? "date" : "text";
      input.value = currentValue || "";
    }
    input.className = "pos-inline-input";
    return input;
  }

  function endpointFor(td) {
    var tr = td.closest("tr");
    var table = td.closest("table");
    var base = (table && table.dataset.editBase) || "";
    var url = base.replace("{id}", tr.dataset.recordId);
    // A few sub-resource routes (e.g. Work Resources) nest under their
    // parent's id too — data-project-id can be set on the <tr> (overrides)
    // or the <table> (shared for every row) when a route needs it.
    var projectId = tr.dataset.projectId || (table && table.dataset.projectId);
    if (projectId) url = url.replace("{project_id}", projectId);
    return url;
  }

  function clearError(td) {
    td.classList.remove("pos-inline-error");
    var note = td.querySelector(".pos-inline-error-msg");
    if (note) note.remove();
  }

  function showError(td, message) {
    td.classList.add("pos-inline-error");
    var note = td.querySelector(".pos-inline-error-msg");
    if (!note) {
      note = document.createElement("div");
      note.className = "pos-inline-error-msg";
      td.appendChild(note);
    }
    note.textContent = message;
  }

  function enterEdit(td) {
    if (td.dataset.editing === "1") return;
    var tr = td.closest("tr");
    if (!tr || tr.dataset.archived === "1") return;
    if (!td.dataset.field) return;

    td.dataset.editing = "1";
    td.dataset.savedText = td.textContent;
    clearError(td);

    var input = buildInput(td);
    td.textContent = "";
    td.appendChild(input);
    input.focus();
    if (typeof input.select === "function") input.select();

    var settled = false;

    function commit() {
      if (settled || td.dataset.editing !== "1") return;
      settled = true;
      var newValue = input.value;
      var endpoint = endpointFor(td);
      td.classList.add("pos-inline-busy");

      var body = new URLSearchParams();
      body.set("field", td.dataset.field);
      body.set("value", newValue);

      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          td.classList.remove("pos-inline-busy");
          if (data && data.ok) {
            td.dataset.editing = "0";
            td.dataset.value = newValue;
            td.textContent = data.display;
            clearError(td);
          } else {
            settled = false;
            showError(td, (data && data.error) || "Save failed.");
            input.focus();
          }
        })
        .catch(function () {
          td.classList.remove("pos-inline-busy");
          settled = false;
          showError(td, "Could not reach the server.");
          input.focus();
        });
    }

    function cancel() {
      settled = true;
      td.dataset.editing = "0";
      clearError(td);
      td.textContent = td.dataset.savedText;
    }

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        commit();
      } else if (event.key === "Escape") {
        event.preventDefault();
        cancel();
      }
      // Tab is left to the browser's default focus movement; blur (below)
      // performs the commit before focus actually leaves the input.
    });
    input.addEventListener("blur", function () {
      if (td.dataset.editing === "1") commit();
    });
  }

  document.addEventListener("click", function (event) {
    var td = event.target.closest("td[data-field]");
    if (!td || td.dataset.editing === "1") return;
    enterEdit(td);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    if (event.target.tagName === "INPUT" || event.target.tagName === "SELECT") return;
    var td = event.target.closest("td[data-field]");
    if (!td || td !== event.target || td.dataset.editing === "1") return;
    event.preventDefault();
    enterEdit(td);
  });
})();
```

- [ ] **Step 2: Append inline-edit CSS to `app/static/css/personalos.css`**

Find the end of the "9. Tables" section (after the `.pos-table-sortable` rules, before `.pos-result-count`) and insert:

```css
.pos-inline-input {
  width: 100%; min-width: 80px;
  padding: 2px 4px;
  font: inherit; font-size: inherit;
  border: 1px solid var(--pos-accent);
  border-radius: var(--pos-radius-sm);
  background: var(--pos-surface-0); color: var(--pos-text);
}
td[data-field] { cursor: pointer; }
td[data-field]:hover { background: var(--pos-surface-2); }
tr[data-archived="1"] td[data-field] { cursor: default; }
tr[data-archived="1"] td[data-field]:hover { background: transparent; }
.pos-inline-busy { opacity: 0.6; }
.pos-inline-error { outline: 2px solid var(--pos-danger); outline-offset: -2px; }
.pos-inline-error-msg {
  margin-top: 2px;
  font-size: var(--pos-fs-meta); color: var(--pos-danger);
}
```

(`--pos-danger` is confirmed as the existing token, e.g. `.pos-flash-error { border-left-color: var(--pos-danger); }` at `personalos.css:307` — reuse it, don't introduce a new hardcoded color.)

- [ ] **Step 3: Wire the script into `base.html`**

In `app/templates/base.html`, change:

```html
<script src="{{ url_for('static', filename='js/app.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/palette.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/tables.js') }}" defer></script>
```

to:

```html
<script src="{{ url_for('static', filename='js/app.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/palette.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/tables.js') }}" defer></script>
<script src="{{ url_for('static', filename='js/inline-edit.js') }}" defer></script>
```

- [ ] **Step 4: Verify the app still starts cleanly**

Run: `python health_check.py` (from repo root, with a working venv — reuse `.venv_verify` if present, else create one and `pip install -r requirements.txt`).
Expected: `0 failure(s)` (same warning count as before this change — this step only adds a static file and a `<script>` tag, so nothing functional should change yet).

- [ ] **Step 5: Commit**

```bash
git add app/static/js/inline-edit.js app/static/css/personalos.css app/templates/base.html
git commit -m "Add shared inline table-editing JS component"
```

---

## Task 2: Portfolios — inline edit for `portfolio_kind`, `sort_order`

**Files:**
- Modify: `app/modules/portfolios/routes.py`
- Modify: `app/templates/modules/portfolios/index.html`

**Interfaces:**
- Consumes: `models.get_portfolio(id)`, `models.update_portfolio(id, fields)`, `models.WRITABLE` (all pre-existing), `config.options("portfolio_kind")` (pre-existing).
- Produces: `POST /portfolios/<id>/field` returning `{"ok": true, "display": "<text>"}` or `{"ok": false, "error": "<text>"}`.

- [ ] **Step 1: Add the field route to `app/modules/portfolios/routes.py`**

Add near the bottom of the file, after the existing `archive` route, and add `import sqlite3` at the top alongside the existing imports:

```python
import sqlite3
```

```python
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
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

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
```

`INLINE_FIELDS` is a deliberately narrower set than `WRITABLE` — `name`, `description`, and `folder_slug` stay on the full edit form (name changes the folder slug logic, description is long text).

- [ ] **Step 2: Annotate `app/templates/modules/portfolios/index.html`**

Find the `<table>` that lists portfolios (it currently has class `pos-table` and likely `data-pos-table` for sorting — check the actual attributes present and keep them). Add `data-edit-base="/portfolios/{id}/field"` to the `<table>` tag. For each `<tr>` in the loop, add `data-record-id="{{ row.id }}" data-archived="{{ '1' if row.archived_at else '0' }}"`. Find the cell showing `portfolio_kind` (likely rendered via a badge/macro showing `row.portfolio_kind`) and change it to a plain editable cell:

```html
<td data-field="portfolio_kind" data-type="select"
    data-options="{{ kinds | join(',') }}" tabindex="0">{{ row.portfolio_kind }}</td>
```

(`kinds` is already passed to this template from `config.options("portfolio_kind")` in the `index` route — confirm this variable name matches what's actually in the route before templating; adjust if it's named differently.) If a `sort_order` column exists in this table, annotate it the same way with `data-type="number"`; if it isn't currently shown as a column, skip it — this task doesn't add new columns, only makes existing ones editable.

- [ ] **Step 3: Manual verification**

Start the dev server: `PYTHONIOENCODING=utf-8 ./.venv_verify/Scripts/python.exe run.py --port 5921 --no-browser` (background it).

Create a portfolio first if none exist:
```bash
curl -s -X POST http://127.0.0.1:5921/portfolios/save -d "name=Verify Inline&portfolio_kind=client"
```

Then POST a field change (substitute the real id from the DB or the redirect location):
```bash
curl -s -X POST http://127.0.0.1:5921/portfolios/1/field -d "field=portfolio_kind&value=internal"
```
Expected: `{"ok": true, "display": "internal"}`.

Then a disallowed field:
```bash
curl -s -X POST http://127.0.0.1:5921/portfolios/1/field -d "field=name&value=Hacked"
```
Expected: `{"ok": false, "error": "“name” can't be edited inline here."}`.

Then a nonexistent portfolio:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5921/portfolios/99999/field -d "field=portfolio_kind&value=internal"
```
Expected: `404`.

Run `python health_check.py` and `python verify_docs.py` — both must pass cleanly. Stop the server.

- [ ] **Step 4: Commit**

```bash
git add app/modules/portfolios/routes.py app/templates/modules/portfolios/index.html
git commit -m "Add inline editing to the Portfolios list"
```

---

## Task 3: Projects — inline edit for `status`, `priority`, `rag_status`, `forecast_end`, and the three lead-role FK fields

**Files:**
- Modify: `app/modules/projects/routes.py`
- Modify: `app/templates/modules/projects/index.html`

**Interfaces:**
- Consumes: `models.get_project(id)`, `models.update_project(id, fields)`, `models.WRITABLE` (pre-existing), `people_models.list_people(limit=1000)` (already imported in this file), `config.options("status")`/`config.options("priority")`/`config.options("rag_status")` (check the actual option-set names used by the existing project edit form — grep `config.options(` calls in this file and reuse the exact same names).
- Produces: `POST /projects/<id>/field`.

- [ ] **Step 1: Add the field route to `app/modules/projects/routes.py`**

Add `import sqlite3` near the top if not already imported by a later task in this same file (Tasks 4–7 also add routes to this file — check for an existing `import sqlite3` before adding a duplicate). Add:

```python
PROJECT_INLINE_FIELDS = {
    "status", "priority", "rag_status", "forecast_end",
    "lead_partner_person_id", "engagement_manager_person_id", "project_lead_person_id",
}
PROJECT_INLINE_FK_FIELDS = {
    "lead_partner_person_id", "engagement_manager_person_id", "project_lead_person_id",
}


@bp.post("/<int:project_id>/field")
def update_project_field(project_id):
    project = models.get_project(project_id)
    if project is None:
        abort(404)
    if project["archived_at"] is not None:
        return {"ok": False, "error": "This project is archived — restore it first to edit."}

    field = request.form.get("field")
    value = request.form.get("value") or None
    if field not in PROJECT_INLINE_FIELDS:
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

    if field in PROJECT_INLINE_FK_FIELDS and value is not None:
        try:
            value = int(value)
        except ValueError:
            return {"ok": False, "error": "That doesn't look like a valid person."}
        if people_models.get_person(value) is None:
            return {"ok": False, "error": "That person no longer exists."}

    try:
        models.update_project(project_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_project(project_id)
    activity.log("project", project_id, "updated", f"Updated {field} for {updated['name']}")

    if field in PROJECT_INLINE_FK_FIELDS:
        name_column = {
            "lead_partner_person_id": "lead_partner_name",
            "engagement_manager_person_id": "engagement_manager_name",
            "project_lead_person_id": "project_lead_name",
        }[field]
        display = updated[name_column] or ""
    else:
        display = str(updated[field]) if updated[field] is not None else ""
    return {"ok": True, "display": display}
```

This route reuses `PROJECT_SELECT`'s existing joins (`lead_partner_name`, `engagement_manager_name`, `project_lead_name` are already selected by `get_project`, confirmed in `app/modules/projects/models.py:15-17`), so the display name comes straight back without a second query.

- [ ] **Step 2: Annotate `app/templates/modules/projects/index.html`**

Add `data-edit-base="/projects/{id}/field"` to the projects `<table>`. On each `<tr>`, add `data-record-id="{{ row.id }}" data-archived="{{ '1' if row.archived_at else '0' }}"`. Annotate the existing `status`, `priority`, `rag_status`, and `forecast_end` columns:

```html
<td data-field="status" data-type="select" data-options="{{ statuses | join(',') }}" tabindex="0">{{ row.status }}</td>
<td data-field="priority" data-type="select" data-options="{{ priorities | join(',') }}" tabindex="0">{{ row.priority }}</td>
<td data-field="rag_status" data-type="select" data-options="{{ rag_statuses | join(',') }}" tabindex="0">{{ row.rag_status }}</td>
<td data-field="forecast_end" data-type="date" tabindex="0">{{ row.forecast_end or '' }}</td>
```

(Check the exact variable names the `index` route passes for these option lists — grep `config.options(` in `app/modules/projects/routes.py`'s `index` function and use whatever names are already there; don't invent new ones. If an option-list variable isn't currently passed to `index.html` at all, add it to the `index()` route the same way the existing ones are added.)

Add the people-options JSON block once, right before `{% endblock %}` (or in a `{% block scripts %}` region if the template has one) so it isn't duplicated per row. Build the list in Python rather than via a Jinja filter chain: in the `index()` route in `app/modules/projects/routes.py`, add a variable passed alongside the existing `render_template(...)` kwargs:

```python
people_options=[{"id": p["id"], "label": p["full_name"]} for p in people_models.list_people(limit=1000)],
```

and in the template use:

```html
<script type="application/json" id="people-options">{{ people_options | tojson }}</script>
```

Then annotate the three lead-role columns (if shown in this table — if the index table doesn't currently show these columns, skip adding them as new columns; this task only makes *existing* columns editable):

```html
<td data-field="lead_partner_person_id" data-type="fk-select" data-options-src="#people-options"
    data-value="{{ row.lead_partner_person_id or '' }}" tabindex="0">{{ row.lead_partner_name or '' }}</td>
```

(repeat the pattern for `engagement_manager_person_id`/`engagement_manager_name` and `project_lead_person_id`/`project_lead_name` if those columns exist in the index table).

- [ ] **Step 3: Manual verification**

Start the dev server on a fresh port, create a portfolio and a project under it via the existing `/projects/save` route, then:

```bash
curl -s -X POST http://127.0.0.1:5922/projects/1/field -d "field=status&value=active"
```
Expected: `{"ok": true, "display": "active"}`.

```bash
curl -s -X POST http://127.0.0.1:5922/projects/1/field -d "field=lead_partner_person_id&value=1"
```
(after creating at least one person via `/people/save`) — expected `{"ok": true, "display": "<that person's full name>"}`.

```bash
curl -s -X POST http://127.0.0.1:5922/projects/1/field -d "field=portfolio_id&value=2"
```
Expected: `{"ok": false, "error": "“portfolio_id” can't be edited inline here."}` — confirms containment fields are correctly excluded.

Run `python health_check.py` and `python verify_docs.py`. Stop the server.

- [ ] **Step 4: Commit**

```bash
git add app/modules/projects/routes.py app/templates/modules/projects/index.html
git commit -m "Add inline editing to the Projects list"
```

---

## Task 4: Workstreams sub-table — inline edit for `status`, `lead_person_id`, `forecast_end`

**Files:**
- Modify: `app/modules/projects/routes.py`
- Modify: `app/templates/modules/projects/detail.html` (Workstreams tab)

**Interfaces:**
- Consumes: `models.get_workstream(id)`, `models.update_workstream(id, fields)`, `WORKSTREAM_WRITABLE` (pre-existing), the same `people_options` JSON block from Task 3 (already rendered once on this same detail page — reuse it, don't duplicate).
- Produces: `POST /projects/workstreams/<id>/field`.

- [ ] **Step 1: Add the field route**

```python
WORKSTREAM_INLINE_FIELDS = {"status", "lead_person_id", "forecast_end"}


@bp.post("/workstreams/<int:workstream_id>/field")
def update_workstream_field(workstream_id):
    workstream = models.get_workstream(workstream_id)
    if workstream is None:
        abort(404)
    if workstream["archived_at"] is not None:
        return {"ok": False, "error": "This workstream is archived — restore it first to edit."}

    field = request.form.get("field")
    value = request.form.get("value") or None
    if field not in WORKSTREAM_INLINE_FIELDS:
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

    if field == "lead_person_id" and value is not None:
        try:
            value = int(value)
        except ValueError:
            return {"ok": False, "error": "That doesn't look like a valid person."}
        if people_models.get_person(value) is None:
            return {"ok": False, "error": "That person no longer exists."}

    try:
        models.update_workstream(workstream_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_workstream(workstream_id)
    activity.log("workstream", workstream_id, "updated", f"Updated {field} for {updated['name']}")
    display = updated["lead_name"] or "" if field == "lead_person_id" else (str(updated[field]) if updated[field] is not None else "")
    return {"ok": True, "display": display}
```

- [ ] **Step 2: Annotate the Workstreams tab table in `app/templates/modules/projects/detail.html`**

Add `data-edit-base="/projects/workstreams/{id}/field"` to the workstreams `<table>`, `data-record-id="{{ w.id }}" data-archived="{{ '1' if w.archived_at else '0' }}"` on each `<tr>`, and annotate `status`, `lead_person_id`/`lead_name`, and `forecast_end` the same way Task 3 did (reusing the page's `statuses` option variable if one already exists for workstream status — check whether workstream status uses the same `config.options("status")` set as projects or a distinct one, and use `#people-options` for the lead field since it's the same person pool already rendered on this page).

- [ ] **Step 3: Manual verification**

Same pattern as Task 3 — create a workstream via the existing `/projects/<id>/workstreams` route, then:
```bash
curl -s -X POST http://127.0.0.1:5922/projects/workstreams/1/field -d "field=status&value=active"
```
Expected `{"ok": true, ...}`. Then:
```bash
curl -s -X POST http://127.0.0.1:5922/projects/workstreams/1/field -d "field=project_id&value=2"
```
Expected `{"ok": false, ...}` (containment field excluded). Run `health_check.py`/`verify_docs.py`. Stop the server.

- [ ] **Step 4: Commit**

```bash
git add app/modules/projects/routes.py app/templates/modules/projects/detail.html
git commit -m "Add inline editing to the Workstreams sub-table"
```

---

## Task 5: Locations sub-table — inline edit for `location_kind`, `site_contact_person_id`

**Files:**
- Modify: `app/modules/projects/routes.py`
- Modify: `app/templates/modules/projects/detail.html` (Locations tab)

**Interfaces:**
- Consumes: `models.get_location(id)`, `models.update_location(id, fields)`, `LOCATION_WRITABLE` (pre-existing), `config.options("location_kind")` (check the exact name used by `location_edit.html`), `#people-options`.
- Produces: `POST /projects/locations/<id>/field`.

- [ ] **Step 1: Add the field route**

```python
LOCATION_INLINE_FIELDS = {"location_kind", "site_contact_person_id"}


@bp.post("/locations/<int:location_id>/field")
def update_location_field(location_id):
    location = models.get_location(location_id)
    if location is None:
        abort(404)

    field = request.form.get("field")
    value = request.form.get("value") or None
    if field not in LOCATION_INLINE_FIELDS:
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

    if field == "site_contact_person_id" and value is not None:
        try:
            value = int(value)
        except ValueError:
            return {"ok": False, "error": "That doesn't look like a valid person."}
        if people_models.get_person(value) is None:
            return {"ok": False, "error": "That person no longer exists."}

    try:
        models.update_location(location_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_location(location_id)
    activity.log("location", location_id, "updated", f"Updated {field} for {updated['name']}")
    display = updated["site_contact_name"] or "" if field == "site_contact_person_id" else (updated[field] or "")
    return {"ok": True, "display": display}
```

(`models.get_location` already filters `archived_at IS NULL`, so a `None` result covers both "doesn't exist" and "archived" — no separate archived check needed here, matching how `get_location` is used elsewhere in this file.)

- [ ] **Step 2: Annotate the Locations tab table**

Add `data-edit-base="/projects/locations/{id}/field"`, `data-record-id`/`data-archived="0"` (locations shown here are never archived, per Step 1's note — `get_location` already filters them out) on each row, and annotate `location_kind` (select, reuse `config.options("location_kind")`) and `site_contact_person_id`/`site_contact_name` (fk-select, `#people-options`).

- [ ] **Step 3: Manual verification**

```bash
curl -s -X POST http://127.0.0.1:5922/projects/locations/1/field -d "field=location_kind&value=remote"
```
Expected `{"ok": true, ...}`. Run `health_check.py`/`verify_docs.py`. Stop the server.

- [ ] **Step 4: Commit**

```bash
git add app/modules/projects/routes.py app/templates/modules/projects/detail.html
git commit -m "Add inline editing to the Locations sub-table"
```

---

## Task 6: Work Resources sub-table — inline edit for `label`, `resource_kind`, `owner_person_id`

**Files:**
- Modify: `app/modules/projects/routes.py`
- Modify: `app/templates/modules/projects/detail.html` (Resources tab)

**Interfaces:**
- Consumes: `models.get_work_resource(id)`, `models.update_work_resource(id, fields)` (added in the earlier CRUD-audit work), `RESOURCE_WRITABLE`, `_get_project_resource(project_id, resource_id)` (the existing ownership-check helper already used by `edit_resource`/`deactivate_resource`/`reactivate_resource` in this file — reuse it, don't re-derive the check), `#people-options`.
- Produces: `POST /projects/<project_id>/resources/<resource_id>/field`.

**Note 1:** this table's "disabled" state is `is_active = 0`, not `archived_at` — the archived-row check below uses that column instead.

**Note 2:** unlike Workstreams/Locations/Dependencies (which don't nest under `project_id` in their URLs), the existing `edit`/`deactivate`/`reactivate` resource routes in this file all nest under `/<int:project_id>/resources/<int:resource_id>/...` — this task's route must match that existing convention rather than the simpler single-id pattern used elsewhere, so it needs the `{project_id}` placeholder Task 1's `endpointFor()` already supports via `data-project-id`.

- [ ] **Step 1: Add the field route**

```python
RESOURCE_INLINE_FIELDS = {"label", "resource_kind", "owner_person_id"}


@bp.post("/<int:project_id>/resources/<int:resource_id>/field")
def update_resource_field(project_id, resource_id):
    if models.get_project(project_id) is None:
        abort(404)
    resource = _get_project_resource(project_id, resource_id)
    if not resource["is_active"]:
        return {"ok": False, "error": "This resource is deactivated — reactivate it first to edit."}

    field = request.form.get("field")
    value = request.form.get("value") or None
    if field not in RESOURCE_INLINE_FIELDS:
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

    if field == "owner_person_id" and value is not None:
        try:
            value = int(value)
        except ValueError:
            return {"ok": False, "error": "That doesn't look like a valid person."}
        if people_models.get_person(value) is None:
            return {"ok": False, "error": "That person no longer exists."}
    elif field == "label" and not value:
        return {"ok": False, "error": "A resource needs a label."}

    try:
        models.update_work_resource(resource_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_work_resource(resource_id)
    activity.log("work_resource", resource_id, "updated", f"Updated {field} for {updated['label']}")
    if field == "owner_person_id":
        owner = people_models.get_person(updated["owner_person_id"]) if updated["owner_person_id"] else None
        display = owner["full_name"] if owner else ""
    else:
        display = updated[field] or ""
    return {"ok": True, "display": display}
```

(`get_work_resource` doesn't join a person name today, so the owner display name is looked up with one extra `people_models.get_person` call rather than adding a join — this matches the "keep validation/lookups where they already live" principle without changing the shared `get_work_resource` query's shape for every other caller.)

- [ ] **Step 2: Annotate the Resources tab table**

Add `data-edit-base="/projects/{project_id}/resources/{id}/field" data-project-id="{{ project.id }}"` to the resources `<table>` (the table-level `data-project-id` covers every row, since all resources on this tab belong to the same project — no need to repeat it per `<tr>`), `data-record-id="{{ r.id }}" data-archived="{{ '0' if r.is_active else '1' }}"` per row (reusing the existing `is_active`-driven active/inactive badge logic added in the earlier CRUD-audit work — don't duplicate that logic, just add the `data-archived` attribute alongside it), and annotate `label` (text), `resource_kind` (select — reuse whatever option set the existing create form uses), and `owner_person_id` (fk-select, `#people-options`).

- [ ] **Step 3: Manual verification**

```bash
curl -s -X POST http://127.0.0.1:5922/projects/1/resources/1/field -d "field=label&value=Renamed Resource"
```
Expected `{"ok": true, "display": "Renamed Resource"}`. Then an empty label:
```bash
curl -s -X POST http://127.0.0.1:5922/projects/1/resources/1/field -d "field=label&value="
```
Expected `{"ok": false, "error": "A resource needs a label."}`. Run `health_check.py`/`verify_docs.py`. Stop the server.

- [ ] **Step 4: Commit**

```bash
git add app/modules/projects/routes.py app/templates/modules/projects/detail.html
git commit -m "Add inline editing to the Work Resources sub-table"
```

---

## Task 7: Dependencies sub-table — inline edit for `status`, `criticality`, `needed_by_date`, `owner_person_id`

**Files:**
- Modify: `app/modules/projects/routes.py`
- Modify: `app/templates/modules/projects/detail.html` (Dependencies tab)

**Interfaces:**
- Consumes: `models.get_dependency(id)`, `models.update_dependency(id, fields)`, `DEPENDENCY_EDIT_WRITABLE` (the narrower, post-creation-editable set from the earlier CRUD-audit work — use this one, not the wider `DEPENDENCY_WRITABLE` used only at creation), `#people-options`.
- Produces: `POST /projects/dependencies/<id>/field`.

- [ ] **Step 1: Add the field route**

```python
DEPENDENCY_INLINE_FIELDS = {"status", "criticality", "needed_by_date", "owner_person_id"}


@bp.post("/dependencies/<int:dependency_id>/field")
def update_dependency_field(dependency_id):
    dependency = models.get_dependency(dependency_id)
    if dependency is None:
        abort(404)
    if dependency["archived_at"] is not None:
        return {"ok": False, "error": "This dependency is archived — restore it first to edit."}

    field = request.form.get("field")
    value = request.form.get("value") or None
    if field not in DEPENDENCY_INLINE_FIELDS:
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

    if field == "owner_person_id" and value is not None:
        try:
            value = int(value)
        except ValueError:
            return {"ok": False, "error": "That doesn't look like a valid person."}
        if people_models.get_person(value) is None:
            return {"ok": False, "error": "That person no longer exists."}

    try:
        models.update_dependency(dependency_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_dependency(dependency_id)
    activity.log("dependency", dependency_id, "updated", f"Updated {field} for {updated['title']}")
    if field == "owner_person_id":
        display = updated["owner_name"] or ""
    else:
        display = str(updated[field]) if updated[field] is not None else ""
    return {"ok": True, "display": display}
```

- [ ] **Step 2: Annotate the Dependencies tab table**

Add `data-edit-base="/projects/dependencies/{id}/field"`, `data-record-id`/`data-archived` per row, and annotate `status` (select — reuse the same status vocabulary the existing status-change dropdown on this row already uses, per the earlier CRUD-audit work), `criticality` (select), `needed_by_date` (date), and `owner_person_id`/`owner_name` (fk-select, `#people-options`).

- [ ] **Step 3: Manual verification**

```bash
curl -s -X POST http://127.0.0.1:5922/projects/dependencies/1/field -d "field=criticality&value=high"
```
Expected `{"ok": true, "display": "high"}`. Run `health_check.py`/`verify_docs.py`. Stop the server.

- [ ] **Step 4: Commit**

```bash
git add app/modules/projects/routes.py app/templates/modules/projects/detail.html
git commit -m "Add inline editing to the Dependencies sub-table"
```

---

## Task 8: Tasks — inline edit for `status`, `priority`, `due_date`, `estimate_hours`, `assignee_person_id`

**Files:**
- Modify: `app/modules/tasks/routes.py`
- Modify: `app/templates/modules/tasks/index.html`, `app/templates/modules/tasks/detail.html`

**Interfaces:**
- Consumes: `models.get_task(id)`, `models.update_task(id, fields)`, `models.WRITABLE` (pre-existing), `people_models.list_people(limit=1000)` (already imported in this file), `config.options("task_type")`-style option calls already used by this module for `status`/`priority`.
- Produces: `POST /tasks/<id>/field`.

- [ ] **Step 1: Add the field route to `app/modules/tasks/routes.py`**

```python
import sqlite3

TASK_INLINE_FIELDS = {"status", "priority", "due_date", "estimate_hours", "assignee_person_id"}


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
```

Note the existing `/save` route in this file is registered at `POST /tasks/save` (no id in the path — it branches on a hidden `task_id` form field), so `POST /tasks/<int:task_id>/field` doesn't collide with any existing route.

- [ ] **Step 2: Annotate `app/templates/modules/tasks/index.html`**

Add `data-edit-base="/tasks/{id}/field"` to the tasks `<table>`, `data-record-id="{{ row.id }}" data-archived="{{ '1' if row.archived_at else '0' }}"` per row, and annotate `status`, `priority`, `due_date`, and `assignee_person_id` the same way as prior tasks. Reuse the page's existing `people` variable (already passed to this template per `app/modules/tasks/routes.py:47`) to build a `people_options` list — add `people_options=[{"id": p["id"], "label": p["full_name"]} for p in people_models.list_people(limit=1000)]` to the `index()` route's `render_template` call (or reuse `people` directly with a `{% for %}` loop instead of a Python-side list, whichever is more consistent with how `#people-options` was implemented in Task 3 — use the exact same approach for consistency across the app), and render `<script type="application/json" id="people-options">{{ people_options | tojson }}</script>` once per page.

- [ ] **Step 3: Annotate `app/templates/modules/tasks/detail.html`**

If this page shows a small key-value table (not a `<table>` of many tasks, just this one task's fields), the same `data-field`/`data-type` attributes apply to individual `<td>` or equivalent elements showing `status`, `priority`, `due_date`, `estimate_hours`, `assignee_person_id` — wrap the single record's row in a `data-record-id="{{ task.id }}" data-archived="..."` container the same way, even if it's a one-row "table."

- [ ] **Step 4: Manual verification**

```bash
curl -s -X POST http://127.0.0.1:5922/tasks/1/field -d "field=status&value=in_progress"
```
Expected `{"ok": true, "display": "in_progress"}`. Then:
```bash
curl -s -X POST http://127.0.0.1:5922/tasks/1/field -d "field=estimate_hours&value=abc"
```
Expected `{"ok": false, "error": "Estimate hours must be a number."}`. Run `health_check.py`/`verify_docs.py`. Stop the server.

- [ ] **Step 5: Commit**

```bash
git add app/modules/tasks/routes.py app/templates/modules/tasks/index.html app/templates/modules/tasks/detail.html
git commit -m "Add inline editing to Tasks"
```

---

## Task 9: People (Contacts) — inline edit for `status`, `job_title`, `department`, `manager_person_id`

**Files:**
- Modify: `app/modules/people/routes.py`
- Modify: `app/templates/modules/people/index.html`, `app/templates/modules/people/detail.html`

**Interfaces:**
- Consumes: `models.get_person(id)`, `models.update_person(id, fields)`, `models.WRITABLE` (pre-existing), `models.list_people(limit=1000)` (for the manager picker — a person can be their own manager's report, exclude the record itself from its own manager-options list).
- Produces: `POST /people/<id>/field`.

- [ ] **Step 1: Add the field route**

```python
import sqlite3

PERSON_INLINE_FIELDS = {"status", "job_title", "department", "manager_person_id"}


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
```

- [ ] **Step 2: Annotate `app/templates/modules/people/index.html`**

Add `data-edit-base="/people/{id}/field"`, `data-record-id`/`data-archived` per row, annotate `status` (select), `job_title` (text), `department` (text). For `manager_person_id`, render a page-level options blob the same way as `#people-options` in earlier tasks but named distinctly (e.g. `#manager-options`) since it should exclude the row's own id — simplest correct approach: reuse the same full `#people-options` blob (self-selection is a rare, harmlessly-caught edge case already rejected server-side in Step 1, so client-side exclusion isn't required for correctness, just a minor polish that can be skipped here per YAGNI).

- [ ] **Step 3: Annotate `app/templates/modules/people/detail.html`**

Same pattern as Task 8 Step 3 — the single-record fields on this page get the same `data-field`/`data-type` treatment inside a `data-record-id="{{ person.id }}"` container.

- [ ] **Step 4: Manual verification**

```bash
curl -s -X POST http://127.0.0.1:5922/people/1/field -d "field=job_title&value=Senior Consultant"
```
Expected `{"ok": true, "display": "Senior Consultant"}`. Then:
```bash
curl -s -X POST http://127.0.0.1:5922/people/1/field -d "field=manager_person_id&value=1"
```
Expected `{"ok": false, "error": "A person can't be their own manager."}`. Run `health_check.py`/`verify_docs.py`. Stop the server.

- [ ] **Step 5: Commit**

```bash
git add app/modules/people/routes.py app/templates/modules/people/index.html app/templates/modules/people/detail.html
git commit -m "Add inline editing to Contacts"
```

---

## Task 10: Charge Codes — inline edit for `status`, `opened_on`, `closed_on`, `lead_partner_person_id`, `engagement_manager_person_id`

**Files:**
- Modify: `app/modules/charge_codes/routes.py`
- Modify: `app/templates/modules/charge_codes/index.html`, `app/templates/modules/charge_codes/detail.html`

**Interfaces:**
- Consumes: `models.get_code(id)`, `models.update_code(id, fields)`, `models.WRITABLE` (pre-existing), `people_models.list_people(limit=1000)`.
- Produces: `POST /charge-codes/<id>/field`.

**Note:** charge codes have no `archived_at` column (they use a `status` lifecycle instead, confirmed during the earlier CRUD audit) — skip the archived-row check other tasks use; `status` itself is one of the inline-editable fields, including the ability to reopen a closed code.

- [ ] **Step 1: Add the field route**

```python
import sqlite3

CODE_INLINE_FIELDS = {
    "status", "opened_on", "closed_on",
    "lead_partner_person_id", "engagement_manager_person_id",
}
CODE_INLINE_FK_FIELDS = {"lead_partner_person_id", "engagement_manager_person_id"}


@bp.post("/<int:code_id>/field")
def update_field(code_id):
    code = models.get_code(code_id)
    if code is None:
        abort(404)

    field = request.form.get("field")
    value = request.form.get("value") or None
    if field not in CODE_INLINE_FIELDS:
        return {"ok": False, "error": f"“{field}” can't be edited inline here."}

    if field in CODE_INLINE_FK_FIELDS and value is not None:
        try:
            value = int(value)
        except ValueError:
            return {"ok": False, "error": "That doesn't look like a valid person."}
        if people_models.get_person(value) is None:
            return {"ok": False, "error": "That person no longer exists."}

    try:
        models.update_code(code_id, {field: value})
    except sqlite3.Error as exc:
        return {"ok": False, "error": f"Could not save that value: {exc}"}

    updated = models.get_code(code_id)
    activity.log("charge_code", code_id, "updated", f"Updated {field} for {updated['code']}")

    if field in CODE_INLINE_FK_FIELDS:
        person = people_models.get_person(updated[field]) if updated[field] else None
        display = person["full_name"] if person else ""
    else:
        display = str(updated[field]) if updated[field] is not None else ""
    return {"ok": True, "display": display}
```

- [ ] **Step 2: Annotate `app/templates/modules/charge_codes/index.html`**

Add `data-edit-base="/charge-codes/{id}/field"`, `data-record-id="{{ row.id }}" data-archived="0"` per row (no archived concept here, per the note above), annotate `status` (select), `opened_on`/`closed_on` (date), and `lead_partner_person_id`/`engagement_manager_person_id` (fk-select, reuse `#people-options` the same way Task 3 built it — build the equivalent `people_options` variable in this module's `index()` route since it's a separate module and can't reach into `projects`' route function).

- [ ] **Step 3: Annotate `app/templates/modules/charge_codes/detail.html`**

Same single-record pattern as Tasks 8–9.

- [ ] **Step 4: Manual verification**

```bash
curl -s -X POST http://127.0.0.1:5922/charge-codes/1/field -d "field=status&value=closed"
```
Expected `{"ok": true, "display": "closed"}`. Then reopen it:
```bash
curl -s -X POST http://127.0.0.1:5922/charge-codes/1/field -d "field=status&value=active"
```
Expected `{"ok": true, "display": "active"}`. Run `health_check.py`/`verify_docs.py`. Stop the server.

- [ ] **Step 5: Commit**

```bash
git add app/modules/charge_codes/routes.py app/templates/modules/charge_codes/index.html app/templates/modules/charge_codes/detail.html
git commit -m "Add inline editing to Charge Codes"
```

---

## Final Integration Check (after all 10 tasks)

- [ ] **Step 1:** Run `python health_check.py` and `python verify_docs.py` one more time against the fully assembled branch — both must pass cleanly.
- [ ] **Step 2:** Start the dev server, open each of the six modules' index pages plus one detail page each in sequence via `curl` (or, if Playwright is available by this point, drive an actual click-to-edit interaction in a real browser for at least the Tasks list, since that's the one part of this feature no amount of curl-ing fully proves), and confirm no page 500s and every new `/field` route responds as expected.
- [ ] **Step 3:** Confirm archived/inactive rows across all six modules render `data-archived="1"` (or `data-archived` reflecting `is_active` for Work Resources) and that a manual POST to their `/field` route is correctly rejected.
- [ ] **Step 4:** Update `docs/BUILD_SEQUENCE.md`'s manual checklist for whichever phase this work is filed under (or add a short new entry) noting inline editing is available, per CLAUDE.md's "Before Completing a Phase" step 6 (docs updated when behaviour changed).
