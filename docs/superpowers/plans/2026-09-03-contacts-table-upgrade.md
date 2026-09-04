# Contacts Table Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the contacts roster sort, filter, paginate, export and edit over the whole dataset rather than the rendered page, and give the level ladder a screen that can manage it.

**Architecture:** Every list control writes to the URL and is parsed by one helper, `_list_query()`, which feeds both the index and the CSV export — so the export cannot drift from the screen. Sorting and filtering move from client-side JavaScript to SQL. The level ladder gets a management screen under Budgets & Rates, where archiving replaces deletion for anything money references.

**Tech Stack:** Python 3.11, Flask 3.x, Jinja2, stdlib `sqlite3` (no ORM), vanilla JavaScript (no framework, no build step), Bootstrap 5.3 vendored locally.

**Spec:** `docs/superpowers/specs/2026-09-03-contacts-table-upgrade-design.md`

**Covers:** sections A–F of that spec. Section G (rate-card fiscal year and effective dates) is a separate subsystem with its own plan.

## Global Constraints

These come from `CLAUDE.md` and apply to every task. Violating one fails the task regardless of whether its own steps pass.

- **Parameterised queries only.** Never interpolate request data into SQL. Table and column names built into query strings must be developer constants looked up from a dict — never a value from `request`.
- **POST for every state change.** Create, update, delete, archive, link, unlink. A CSV export is a read and is correctly a `GET`.
- **Autoescaping stays on.** Never `| safe` on user content.
- **Schema changes require a migration:** a new numbered file in `app/core/migrations/`, plus an update to `docs/DATABASE_SCHEMA.md` **including that section's mermaid ER diagram**.
- **Never drop a user table, never overwrite user-entered data.**
- **All money math goes through `resolve_rates()`.** No inline rate lookups.
- **Activity-log every mutation** via `activity.log(...)`. No sensitive values in log entries.
- **Every route checks `is_module_enabled()`** — handled by `guard_blueprint(bp, "<module>")` at the top of each module's routes.
- **No build step, no framework, no TypeScript, no ORM.** Vanilla JS only.
- **No inline `<script>`.** The Content-Security-Policy forbids it; all behaviour lives in `app/static/js/*.js`.
- **`as_of` is a parameter, never an assumption.** No function in `app/core/` calls `date.today()`; routes supply the default.
- **Comments explain non-obvious WHY only.** No docstrings on self-evident functions.

## Testing In This Repo — Read This First

**There is no pytest suite and you must not create one.** `CLAUDE.md` is explicit: validation is `python health_check.py` plus the manual checklist in `docs/BUILD_SEQUENCE.md`. `health_check.py` is where regressions get caught, and it is the "test file" every task below refers to.

TDD still applies, in this shape:

1. Add the new check to `health_check.py` **first**.
2. Run `python health_check.py` and confirm it FAILS with the message you expect.
3. Implement.
4. Run `python health_check.py` and confirm it PASSES and that nothing else broke.
5. Commit.

Checks are added inside the `with app.test_client() as client:` block in section 7 (`# --- 7. application ---`), near the existing `"a disabled module 404s"` check, using the existing `check(name, passed, detail)` helper.

**Interpreter note:** the `.venv` in this working copy is empty and has no `pip`, so `.venv\Scripts\python.exe` cannot run anything. Use a working Python 3.11+ with `requirements.txt` installed. Verify before starting:

```bash
python -c "import flask, openpyxl, nh3, markdown, yaml, dateutil, requests; print('ok')"
```

**Never run the app or the health check against `app/data/personalos.db` without copying it first** — it holds live contact data. To test against a copy, override the config after the app is built:

```python
app = create_app(run_migrations=False)
app.config["DATABASE_PATH"] = str(path_to_a_copy)
```

---

### Task 1: The query contract and server-side ordering

Everything else depends on this. It replaces the hardcoded page size and the direction-less sort with one parsed query object.

**Files:**
- Modify: `app/modules/people/models.py` — `SORTABLE`, `_filter_clause`, `list_people`
- Modify: `app/modules/people/routes.py` — `_list_query`, `DEFAULT_PER_PAGE`, `PER_PAGE_OPTIONS`, `index`
- Test: `health_check.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `models.SORTABLE: dict[str, tuple[str, str, str]]` — sort key → `(lead_expression, default_direction, tiebreak_expression)`
  - `models.list_people(sort="name", direction=None, limit=100, offset=0, **filters)` — `limit=None` means no `LIMIT` clause at all
  - `models._filter_clause(...)` additionally accepts `department=None`, `status=None`
  - `routes.DEFAULT_PER_PAGE = 100`, `routes.PER_PAGE_OPTIONS = (25, 50, 100, 250, 500, 1000)`
  - `routes._list_query() -> dict` with keys `filters` (dict), `sort` (str), `direction` (`"asc"`/`"desc"`), `page` (int), `per_page` (int)
  - `routes._query_args(query) -> dict` — the non-empty query parameters, for `url_for`

- [ ] **Step 1: Write the failing checks**

In `health_check.py`, inside the `with app.test_client() as client:` block, after the `"re-enabling restores it"` check:

```python
            # The list controls are a URL contract: anything the user can
            # type has to survive the parser as a legal value, because both
            # the index and the CSV export are built from what it returns.
            from app.modules.people import routes as people_routes

            with app.test_request_context(
                "/people/?per_page=999999&sort=nonsense&dir=sideways"
            ):
                parsed = people_routes._list_query()
            check("per_page clamps to the allowed set",
                  parsed["per_page"] == people_routes.DEFAULT_PER_PAGE,
                  f"got {parsed['per_page']}")
            check("an unknown sort falls back to name",
                  parsed["sort"] == "name", f"got {parsed['sort']}")
            check("an unknown direction falls back to the column default",
                  parsed["direction"] == "asc", f"got {parsed['direction']}")

            with app.test_request_context("/people/?per_page=1000&sort=level"):
                parsed = people_routes._list_query()
            check("an allowed per_page is honoured", parsed["per_page"] == 1000,
                  f"got {parsed['per_page']}")
            check("level defaults to descending — most senior first",
                  parsed["direction"] == "desc", f"got {parsed['direction']}")

            check("sorting descending reverses the roster",
                  client.get("/people/?sort=name&dir=asc").status_code == 200
                  and client.get("/people/?sort=name&dir=desc").status_code == 200)
```

- [ ] **Step 2: Run the checks and watch them fail**

Run: `python health_check.py`
Expected: FAIL — `AttributeError: module 'app.modules.people.routes' has no attribute '_list_query'`, surfacing as `create_app() succeeds` failing or a traceback. That is the correct failure; it proves the check is wired to real code.

- [ ] **Step 3: Rewrite `SORTABLE` and the ordering helper**

In `app/modules/people/models.py`, replace the existing `SORTABLE` dict:

```python
# sort key -> (leading expression, its default direction, tie-breaker).
# Direction applies to the leading term only. The tie-breaker keeps its own
# fixed direction so that two people who sort equally never swap places
# between page 1 and page 2.
SORTABLE = {
    "name":       ("p.last_name",  "asc",  "p.first_name"),
    "email":      ("p.email",      "asc",  "p.last_name"),
    "title":      ("p.job_title",  "asc",  "p.last_name"),
    "level":      ("l.sort_order", "desc", "p.last_name"),
    "department": ("p.department", "asc",  "p.last_name"),
    "company":    ("p.company",    "asc",  "p.last_name"),
    "city":       ("p.city",       "asc",  "p.last_name"),
    "function":   ("p.function",   "asc",  "p.last_name"),
    "status":     ("p.status",     "asc",  "p.last_name"),
    "manager":    ("m.last_name",  "asc",  "p.last_name"),
}

_DIRECTIONS = {"asc": "ASC", "desc": "DESC"}


def default_direction(sort):
    return SORTABLE.get(sort, SORTABLE["name"])[1]


def _order_by(sort, direction):
    lead, fallback, tiebreak = SORTABLE.get(sort, SORTABLE["name"])
    keyword = _DIRECTIONS.get(direction, _DIRECTIONS[fallback])
    return f"{lead} {keyword}, {tiebreak}"
```

- [ ] **Step 4: Add the two new filters**

In the same file, extend `_filter_clause`'s signature and body:

```python
def _filter_clause(search=None, level_id=None, company=None, function=None,
                   department=None, status=None,
                   import_source=None, include_archived=False, unmapped=False,
                   no_manager=False):
```

and add, beside the existing `company` clause:

```python
    if department:
        clauses.append("p.department = ?")
        params.append(department)
    if status:
        clauses.append("p.status = ?")
        params.append(status)
```

- [ ] **Step 5: Teach `list_people` about direction and an absent limit**

```python
def list_people(sort="name", direction=None, limit=100, offset=0, **filters):
    where, params = _filter_clause(**filters)
    sql = _SELECT + where + f" ORDER BY {_order_by(sort, direction)}"
    # limit=None is the CSV export: the whole filtered set, no pagination.
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params = params + [limit, offset]
    return get_db().execute(sql, params).fetchall()
```

- [ ] **Step 6: Write the query parser**

In `app/modules/people/routes.py`, replace `PAGE_SIZE = 50` with:

```python
DEFAULT_PER_PAGE = 100
PER_PAGE_OPTIONS = (25, 50, 100, 250, 500, 1000)
```

and add below the module constants:

```python
def _list_query():
    """Parse the roster's URL controls once, for the index and the export.

    Both views build from this, which is what stops an export of "what I am
    looking at" from quietly meaning something else than the screen.
    """
    per_page = request.args.get("per_page", type=int)
    if per_page not in PER_PAGE_OPTIONS:
        per_page = DEFAULT_PER_PAGE

    sort = request.args.get("sort", "name")
    if sort not in models.SORTABLE:
        sort = "name"

    direction = request.args.get("dir")
    if direction not in ("asc", "desc"):
        direction = models.default_direction(sort)

    return {
        "filters": {
            "search": (request.args.get("q") or "").strip() or None,
            "level_id": request.args.get("level_id", type=int),
            "company": request.args.get("company") or None,
            "department": request.args.get("department") or None,
            "function": request.args.get("function") or None,
            "status": request.args.get("status") or None,
            "import_source": request.args.get("source") or None,
            "unmapped": request.args.get("unmapped") == "1",
            "no_manager": request.args.get("no_manager") == "1",
            "include_archived": request.args.get("archived") == "1",
        },
        "sort": sort,
        "direction": direction,
        "page": max(request.args.get("page", 1, type=int), 1),
        "per_page": per_page,
    }


# Query keys as they appear in the URL, paired with the filter key they
# parse into. Used to rebuild a link that keeps the current view.
_QUERY_KEYS = (
    ("q", "search"), ("level_id", "level_id"), ("company", "company"),
    ("department", "department"), ("function", "function"),
    ("status", "status"), ("source", "import_source"),
)


def _query_args(query, **overrides):
    """The current view as url_for keyword arguments, minus empty values."""
    args = {}
    for url_key, filter_key in _QUERY_KEYS:
        value = query["filters"].get(filter_key)
        if value:
            args[url_key] = value
    for flag, filter_key in (("unmapped", "unmapped"), ("no_manager", "no_manager"),
                             ("archived", "include_archived")):
        if query["filters"].get(filter_key):
            args[flag] = 1
    args["sort"] = query["sort"]
    args["dir"] = query["direction"]
    args["per_page"] = query["per_page"]
    args.update(overrides)
    return args
```

- [ ] **Step 7: Rewrite the index view to use it**

Replace the body of `index()` down to the `render_template` call:

```python
@bp.get("/")
def index():
    as_of = request.args.get("as_of") or date.today().isoformat()
    query = _list_query()
    filters = query["filters"]

    total = models.count_people(**filters)
    rows = models.list_people(
        sort=query["sort"], direction=query["direction"],
        limit=query["per_page"], offset=(query["page"] - 1) * query["per_page"],
        **filters
    )

    return render_template(
        "modules/people/index.html",
        rows=rows,
        total=total,
        page=query["page"],
        page_size=query["per_page"],
        page_count=max((total + query["per_page"] - 1) // query["per_page"], 1),
        sort=query["sort"],
        direction=query["direction"],
        per_page_options=PER_PAGE_OPTIONS,
        query_args=_query_args(query),
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
```

- [ ] **Step 8: Run the checks and watch them pass**

Run: `python health_check.py`
Expected: PASS for all six new checks, and `GET /people/ → 200` still passing. Exit code 0.

- [ ] **Step 9: Load the page and confirm it still renders**

Run `python run.py --port 5055 --no-browser` against a **copy** of the database, open `http://127.0.0.1:5055/people/`, and confirm the roster renders with 100 rows per page. The old `?sort=` links still work; the header UI arrives in Task 2.

- [ ] **Step 10: Commit**

```bash
git add app/modules/people/models.py app/modules/people/routes.py health_check.py
git commit -m "Parse the roster's URL controls once, and sort in SQL"
```

---

### Task 2: Header sort links and per-column filter menus

**Files:**
- Modify: `app/modules/people/models.py` — `FILTERABLE_COLUMNS`, `column_values`
- Modify: `app/modules/people/routes.py` — pass `menus` to the template
- Modify: `app/templates/modules/people/index.html` — the `<thead>`
- Modify: `app/static/js/tables.js` — skip client sort on server-sorted tables, menu behaviour
- Modify: `app/static/css/personalos.css` — menu styles
- Test: `health_check.py`

**Interfaces:**
- Consumes: `models.SORTABLE`, `_list_query()`, `_query_args()` from Task 1.
- Produces:
  - `models.FILTERABLE_COLUMNS: dict[str, tuple[str, str]]` — column key → `(value_expression, label_expression)`
  - `models.column_values(column, **filters) -> list[sqlite3.Row]` with fields `value`, `label`, `n`
  - Template variable `menus: dict[str, list]` keyed by column

- [ ] **Step 1: Write the failing checks**

In `health_check.py`, after the Task 1 checks:

```python
            # A column's own filter is excluded from its own counts, so the
            # menu still shows what else you could switch to after picking.
            with app.app_context():
                from app.modules.people import models as people_models

                everything = people_models.column_values("company")
                narrowed = people_models.column_values("company", status="active")
            check("column_values returns value/label/count rows",
                  all({"value", "label", "n"} <= set(r.keys()) for r in everything),
                  f"{len(everything)} row(s)")
            check("a column's menu counts honour the other filters",
                  sum(r["n"] for r in narrowed) <= sum(r["n"] for r in everything))
            check("the level menu keys on id, not label",
                  all(isinstance(r["value"], int)
                      for r in people_models.column_values("level")
                      if r["value"] is not None))
```

- [ ] **Step 2: Run the checks and watch them fail**

Run: `python health_check.py`
Expected: FAIL — `module 'app.modules.people.models' has no attribute 'column_values'`.

- [ ] **Step 3: Add the filterable-column registry and the value query**

In `app/modules/people/models.py`:

```python
# Column key -> (value expression, label expression). The key arrives from
# the request; the SQL never does. A key that is not in this dict is a
# programming error, not user input, so a KeyError is the right failure.
FILTERABLE_COLUMNS = {
    "company":    ("p.company",    "p.company"),
    "department": ("p.department", "p.department"),
    "function":   ("p.function",   "p.function"),
    "status":     ("p.status",     "p.status"),
    "level":      ("l.id",         "l.label"),
}

# Which filter a column's own menu must ignore when counting, so that
# choosing "KPMG" does not reduce the Company menu to just KPMG.
FILTER_FOR_COLUMN = {
    "company": "company", "department": "department", "function": "function",
    "status": "status", "level": "level_id",
}


def column_values(column, **filters):
    value_expression, label_expression = FILTERABLE_COLUMNS[column]
    filters.pop(FILTER_FOR_COLUMN[column], None)
    where, params = _filter_clause(**filters)
    sql = (
        f"SELECT {value_expression} AS value, {label_expression} AS label, "
        "COUNT(*) AS n FROM people p "
        "LEFT JOIN person_levels l ON l.id = p.level_id "
        "LEFT JOIN people m ON m.id = p.manager_person_id"
        + where +
        f" GROUP BY {value_expression} HAVING value IS NOT NULL"
        f" ORDER BY {label_expression}"
    )
    return get_db().execute(sql, params).fetchall()
```

- [ ] **Step 4: Hand the menus to the template**

In `index()` in `app/modules/people/routes.py`, before `render_template`:

```python
    menus = {column: models.column_values(column, **filters)
             for column in models.FILTERABLE_COLUMNS}
```

and pass `menus=menus,` in the `render_template` call.

- [ ] **Step 5: Rewrite the table header**

In `app/templates/modules/people/index.html`, add this macro just after the `{% from %}` line at the top:

```jinja
{% macro column_head(label, key, filter_key=none, menu=none) %}
  {% set is_current = sort == key %}
  {% set next_dir = 'desc' if (is_current and direction == 'asc') else 'asc' %}
  <th scope="col"
      aria-sort="{{ 'ascending' if is_current and direction == 'asc'
                    else 'descending' if is_current else 'none' }}">
    <a class="pos-th-sort" href="{{ url_for('people.index',
        **dict(query_args, sort=key, dir=next_dir, page=1)) }}">
      {{ label }}
      <span aria-hidden="true">{{ '▲' if is_current and direction == 'asc'
                                  else '▼' if is_current else '↕' }}</span>
    </a>
    {% if menu %}
    <details class="pos-th-filter">
      <summary aria-label="Filter by {{ label }}">
        {{ '●' if filters[filter_key] else '▾' }}
      </summary>
      <div class="pos-menu-panel" role="menu">
        <a class="pos-menu-item" role="menuitem"
           href="{{ url_for('people.index',
                   **dict(query_args, page=1, **{filter_key: none})) }}">All</a>
        {% for row in menu %}
        <a class="pos-menu-item" role="menuitem"
           href="{{ url_for('people.index',
                   **dict(query_args, page=1, **{filter_key: row.value})) }}">
          {{ row.label }} <span class="pos-muted">({{ row.n | num }})</span>
        </a>
        {% endfor %}
      </div>
    </details>
    {% endif %}
  </th>
{% endmacro %}
```

Then replace the `<thead>` block of the contacts table with:

```jinja
  <thead>
    <tr>
      {{ column_head('Name', 'name') }}
      {{ column_head('Job title', 'title') }}
      {{ column_head('Level', 'level', 'level_id', menus.level) }}
      {{ column_head('Department', 'department', 'department', menus.department) }}
      {{ column_head('Company', 'company', 'company', menus.company) }}
      {{ column_head('City', 'city') }}
      {{ column_head('State', 'state') }}
      {{ column_head('Manager', 'manager') }}
      {{ column_head('Status', 'status', 'status', menus.status) }}
    </tr>
  </thead>
```

Note the Location column is split into City and State so each sorts and edits on its own; Task 5 splits the matching `<td>`s. Add `"state": ("p.state_province", "asc", "p.last_name")` to `SORTABLE` in `models.py` for the new header.

- [ ] **Step 6: Mark the table server-sorted**

Change the opening tag of the contacts table to:

```jinja
<table class="pos-table" id="people-table" data-pos-table data-pos-server-sort
       data-edit-base="/people/{id}/field">
```

`pos-table-sortable` and `data-pos-export-name` are both removed — sorting is the server's job now, and the export becomes a link in Task 4.

- [ ] **Step 7: Stop the client sort hijacking server-sorted tables**

In `app/static/js/tables.js`, replace the `DOMContentLoaded` handler:

```javascript
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-pos-table]").forEach(function (table) {
      /* A server-sorted table orders the whole result set. Re-sorting the
       * rendered page on top of that would silently reorder one page of
       * many and claim to have sorted everything. */
      if (table.classList.contains("pos-table-sortable")
          && !table.hasAttribute("data-pos-server-sort")) {
        makeSortable(table);
      }
      makeExportable(table);
    });

    /* One open filter menu at a time, and Escape closes it. */
    document.addEventListener("click", function (event) {
      document.querySelectorAll("details.pos-th-filter[open]").forEach(function (menu) {
        if (!menu.contains(event.target)) menu.removeAttribute("open");
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      document.querySelectorAll("details.pos-th-filter[open]").forEach(function (menu) {
        menu.removeAttribute("open");
      });
    });
  });
```

- [ ] **Step 8: Style the header controls**

Append to `app/static/css/personalos.css`:

```css
/* Sort and filter handles live in the header cell itself. */
.pos-th-sort { color: inherit; text-decoration: none; white-space: nowrap; }
.pos-th-sort:hover { text-decoration: underline; }
.pos-th-filter { display: inline-block; position: relative; }
.pos-th-filter > summary {
  cursor: pointer; list-style: none; padding: 0 .25rem; font-size: .85em;
}
.pos-th-filter > summary::-webkit-details-marker { display: none; }
.pos-th-filter .pos-menu-panel {
  position: absolute; z-index: 20; min-width: 12rem; max-height: 20rem;
  overflow-y: auto; text-align: left; font-weight: 400;
}
```

- [ ] **Step 9: Run the checks and watch them pass**

Run: `python health_check.py`
Expected: PASS on all three new checks, exit 0.

- [ ] **Step 10: Confirm in the browser**

Start the app against a copy of the database. On `/people/`: click a column header and confirm the URL gains `sort=` and `dir=`, the arrow flips on a second click, and the row order changes across the *whole* set (page 2 continues the order rather than restarting it). Open a filter menu, pick a value, confirm the count in the header menu and the result count agree. Tab to a header and press Enter — it must sort without a mouse (P10).

- [ ] **Step 11: Commit**

```bash
git add app/modules/people/models.py app/modules/people/routes.py \
        app/templates/modules/people/index.html app/static/js/tables.js \
        app/static/css/personalos.css health_check.py
git commit -m "Put sort and filter handles in the contacts table header"
```

---

### Task 3: Page-size selector and a pager that keeps the view

**Files:**
- Modify: `app/templates/modules/people/index.html` — selector and pager call
- Modify: `app/static/js/tables.js` — submit-on-change
- Test: `health_check.py`

**Interfaces:**
- Consumes: `per_page_options`, `query_args`, `page`, `page_count` from Task 1.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing check**

```python
            # Paging must not drop the view. A next-page link that loses the
            # filter is how you silently page into the unfiltered roster.
            # Asserted against the parser rather than the rendered HTML, so
            # it holds whatever the database happens to contain.
            with app.test_request_context(
                "/people/?company=Acme&status=active&sort=level&dir=asc&per_page=25"
            ):
                args = people_routes._query_args(people_routes._list_query())
            check("the page link keeps the filters",
                  args.get("company") == "Acme" and args.get("status") == "active",
                  str(args))
            check("the page link keeps sort, direction and page size",
                  args.get("sort") == "level" and args.get("dir") == "asc"
                  and args.get("per_page") == 25, str(args))
            check("empty filters are left out of the link",
                  "q" not in args and "level_id" not in args, str(args))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python health_check.py`
Expected: FAIL — the rendered pager currently receives only `q`, `level_id`, `company` and `sort`.

- [ ] **Step 3: Add the selector beside the result count**

Replace the `<p class="pos-result-count">` block in `index.html`:

```jinja
<div class="pos-result-count" aria-live="polite">
  <span>{{ total | num }} contact{{ 's' if total != 1 }}{% if page_count > 1 %}
        · page {{ page }} of {{ page_count }}{% endif %}</span>

  <form class="pos-inline-form" method="get" action="{{ url_for('people.index') }}">
    {% for key, value in query_args.items() if key not in ('per_page', 'page') %}
    <input type="hidden" name="{{ key }}" value="{{ value }}">
    {% endfor %}
    <label for="f-per-page">Rows per page</label>
    <select id="f-per-page" name="per_page" data-pos-submit-on-change>
      {% for option in per_page_options %}
      <option value="{{ option }}" {% if option == page_size %}selected{% endif %}>
        {{ option | num }}
      </option>
      {% endfor %}
    </select>
    <noscript><button type="submit" class="pos-btn">Apply</button></noscript>
  </form>
</div>
```

- [ ] **Step 4: Pass the whole view to the pager**

Replace the `{{ pager(...) }}` call:

```jinja
{{ pager('people.index', page, page_count,
         dict(query_args, **{'per_page': page_size})) }}
```

- [ ] **Step 5: Submit the selector on change**

Append inside the `DOMContentLoaded` handler in `app/static/js/tables.js`:

```javascript
    /* The CSP forbids inline handlers, so submit-on-change is wired here.
     * The <noscript> button is the fallback, not decoration. */
    document.querySelectorAll("[data-pos-submit-on-change]").forEach(function (control) {
      control.addEventListener("change", function () {
        if (control.form) control.form.submit();
      });
    });
```

- [ ] **Step 6: Run the check and watch it pass**

Run: `python health_check.py`
Expected: PASS, exit 0.

- [ ] **Step 7: Confirm in the browser**

Set rows per page to 1000 and confirm the URL gains `per_page=1000` and the page renders every contact. Apply a company filter, sort by level descending, then click Next — the filter, the sort and the direction must all survive.

- [ ] **Step 8: Commit**

```bash
git add app/templates/modules/people/index.html app/static/js/tables.js health_check.py
git commit -m "Make rows per page selectable and keep the view across pages"
```

---

### Task 4: Export the filtered set, not the page

**Files:**
- Modify: `app/modules/people/routes.py` — `EXPORT_COLUMNS`, `export_csv`
- Modify: `app/templates/modules/people/index.html` — the export link
- Test: `health_check.py`

**Interfaces:**
- Consumes: `_list_query()`, `_query_args()`, `models.list_people(limit=None)`.
- Produces: route `people.export_csv` at `/people/export.csv`.

- [ ] **Step 1: Write the failing checks**

```python
            # The bug being fixed: the old export walked the rendered DOM and
            # so returned one page. Row count is compared against the count
            # query rather than a fixed number, so this holds on any database.
            with app.app_context():
                from app.modules.people import models as people_models
                everyone = people_models.count_people()
                actives = people_models.count_people(status="active")

            dump = client.get("/people/export.csv?per_page=1")
            body = dump.data.decode("utf-8-sig").strip().splitlines()
            check("export.csv returns a CSV attachment",
                  dump.headers.get("Content-Disposition", "").startswith("attachment"),
                  dump.headers.get("Content-Disposition", "(none)"))
            check("export ignores pagination and returns every row",
                  len(body) - 1 == everyone, f"{len(body) - 1} rows for {everyone} contacts")

            filtered = client.get("/people/export.csv?status=active")
            filtered_body = filtered.data.decode("utf-8-sig").strip().splitlines()
            check("export honours the screen's filters",
                  len(filtered_body) - 1 == actives,
                  f"{len(filtered_body) - 1} rows for {actives} active")
            check("export carries more than the visible columns",
                  b"Mobile phone" in filtered.data)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python health_check.py`
Expected: FAIL — `/people/export.csv` returns 404.

- [ ] **Step 3: Write the export route**

Add to the imports at the top of `app/modules/people/routes.py`:

```python
import csv
import io

from flask import Response
```

and add the route after `index()`:

```python
# (row key, column heading). The export carries the whole directory record,
# not the columns the table happens to show — an export you have to go back
# and re-run with different columns is not an export.
EXPORT_COLUMNS = (
    ("external_ref", "ID"), ("first_name", "First name"), ("last_name", "Last name"),
    ("preferred_name", "Preferred name"), ("email", "Email"), ("company", "Company"),
    ("department", "Department"), ("job_title", "Job title"),
    ("level_label", "Level"), ("function", "Function"), ("status", "Status"),
    ("business_phone", "Business phone"), ("mobile_phone", "Mobile phone"),
    ("home_phone", "Home phone"), ("city", "City"), ("state_province", "State/Province"),
    ("manager_name", "Manager"), ("manager_email", "Manager email"),
)


@bp.get("/export.csv")
def export_csv():
    query = _list_query()
    rows = models.list_people(
        sort=query["sort"], direction=query["direction"], limit=None,
        **query["filters"]
    )

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        def flush():
            value = buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            return value

        writer.writerow([heading for _, heading in EXPORT_COLUMNS])
        yield flush()
        for row in rows:
            keys = row.keys()
            writer.writerow([
                row[key] if key in keys and row[key] is not None else ""
                for key, _ in EXPORT_COLUMNS
            ])
            yield flush()

    stamp = date.today().isoformat()
    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                f'attachment; filename="personalos-contacts-{stamp}.csv"'
        },
    )
```

- [ ] **Step 4: Turn the button into a link that carries the view**

In `index.html`, replace the export button with:

```jinja
  <a class="pos-btn" href="{{ url_for('people.export_csv', **query_args) }}">
    Export CSV{% if filters.search or filters.level_id or filters.company
                  or filters.department or filters.function or filters.status %}
    — filtered{% endif %}
  </a>
```

The label states what will happen, so the file cannot surprise you (P2).

- [ ] **Step 5: Run the checks and watch them pass**

Run: `python health_check.py`
Expected: PASS on all four, exit 0.

- [ ] **Step 6: Confirm in the browser**

Filter to one company, click Export CSV, open the file: it must contain every contact of that company — including those on pages you never looked at — and columns the table does not display. Clear the filters and export again: the whole roster.

- [ ] **Step 7: Commit**

```bash
git add app/modules/people/routes.py app/templates/modules/people/index.html health_check.py
git commit -m "Export the filtered contact set rather than the rendered page"
```

---

### Task 5: Inline editing across the scalar columns

**Files:**
- Modify: `app/modules/people/routes.py` — `PERSON_INLINE_FIELDS`
- Modify: `app/templates/modules/people/index.html` — the `<td>`s
- Test: `health_check.py`

**Interfaces:**
- Consumes: the existing `POST /people/<id>/field` route and the `data-field` / `data-type` contract from `docs/superpowers/specs/2026-09-02-inline-table-editing-design.md`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing checks**

```python
            # Editing is allowlisted server-side; the grid's attributes are
            # not the security boundary.
            with app.app_context():
                from app.modules.people import models as people_models
                subject = people_models.list_people(limit=1)
            if subject:
                person_id = subject[0]["id"]
                before = subject[0]["company"]
                saved = client.post(f"/people/{person_id}/field",
                                    data={"field": "company", "value": "Health Check Co"},
                                    headers={"Origin": "http://localhost"})
                check("company edits inline", saved.get_json().get("ok") is True,
                      str(saved.get_json()))
                client.post(f"/people/{person_id}/field",
                            data={"field": "company", "value": before or ""},
                            headers={"Origin": "http://localhost"})
                refused = client.post(f"/people/{person_id}/field",
                                      data={"field": "notes", "value": "nope"},
                                      headers={"Origin": "http://localhost"})
                check("a field outside the allowlist is refused",
                      refused.get_json().get("ok") is False)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python health_check.py`
Expected: FAIL on `company edits inline` — `company` is not yet in `PERSON_INLINE_FIELDS`, so the route answers `"company" can't be edited inline here.`

- [ ] **Step 3: Widen the allowlist**

In `app/modules/people/routes.py`:

```python
# Name and email are deliberately absent. Email is the key the contact
# importer deduplicates on, so a typo fixed in a grid cell would quietly make
# the next spreadsheet load insert that person again instead of updating them.
PERSON_INLINE_FIELDS = {
    "status", "job_title", "department", "company", "city", "state_province",
    "function", "manager_person_id",
}
```

- [ ] **Step 4: Annotate the cells**

In `index.html`, replace the combined Location cell with two cells and annotate the rest:

```jinja
      <td class="pos-small" data-field="company" data-type="text"
          data-value="{{ row.company or '' }}" tabindex="0">{{ row.company or '—' }}</td>
      <td class="pos-small" data-field="city" data-type="text"
          data-value="{{ row.city or '' }}" tabindex="0">{{ row.city or '—' }}</td>
      <td class="pos-small" data-field="state_province" data-type="text"
          data-value="{{ row.state_province or '' }}" tabindex="0">{{ row.state_province or '—' }}</td>
```

The Job title, Department, Manager and Status cells already carry their attributes and need no change.

- [ ] **Step 5: Run the checks and watch them pass**

Run: `python health_check.py`
Expected: PASS, exit 0.

- [ ] **Step 6: Confirm in the browser**

Click a Company cell, type, press Enter: it saves and shows the new value. Press Escape mid-edit: the old value returns and nothing is written. Tab to a City cell and press Enter to open it without a mouse. Check `/activity/` shows one entry per saved field.

- [ ] **Step 7: Commit**

```bash
git add app/modules/people/routes.py app/templates/modules/people/index.html health_check.py
git commit -m "Extend inline editing to every scalar contacts column"
```

---

### Task 6: The archived-level migration

**Files:**
- Create: `app/core/migrations/0027_person_levels_archive.sql`
- Modify: `app/core/rates.py` — `levels(include_archived=False)`
- Modify: `docs/DATABASE_SCHEMA.md` — the `person_levels` DDL and the People mermaid diagram
- Test: `health_check.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `person_levels.archived_at`; `rates.levels(on_ladder_only=False, include_archived=False)`.

- [ ] **Step 1: Write the failing check**

```python
            with app.app_context():
                from app.core import rates as core_rates
                visible = core_rates.levels()
                everything = core_rates.levels(include_archived=True)
            check("levels() hides archived levels by default",
                  len(visible) <= len(everything),
                  f"{len(visible)} visible of {len(everything)}")
```

Add `"person_levels"` is already in `EXPECTED_TABLES`; no change needed there.

- [ ] **Step 2: Run it and watch it fail**

Run: `python health_check.py`
Expected: FAIL — `levels() got an unexpected keyword argument 'include_archived'`.

- [ ] **Step 3: Write the migration**

Create `app/core/migrations/0027_person_levels_archive.sql`:

```sql
-- Retiring a level must never unprice history. Archiving hides it from the
-- pickers while every rate_card_entry and person_level_history row that
-- references it stays exactly as it was.
ALTER TABLE person_levels ADD COLUMN archived_at DATETIME;
```

- [ ] **Step 4: Apply it against a copy and confirm the backup ran**

Run: `python apply_migrations.py`
Expected: a pre-migration backup is written to `app/data/backups/`, then the migration applies. If the backup fails the migration must abort — do not proceed past a failed backup.

- [ ] **Step 5: Teach `levels()` about archiving**

In `app/core/rates.py`:

```python
def levels(on_ladder_only=False, include_archived=False):
    clauses = []
    if on_ladder_only:
        clauses.append("is_on_ladder = 1")
    if not include_archived:
        clauses.append("archived_at IS NULL")
    sql = "SELECT * FROM person_levels"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY sort_order"
    return get_db().execute(sql).fetchall()
```

- [ ] **Step 6: Update the schema documentation**

In `docs/DATABASE_SCHEMA.md`, add `archived_at DATETIME` to the `person_levels` `CREATE TABLE` block, and add the column to that section's mermaid ER diagram. This is required, not optional — `verify_docs.py` executes the DDL in that document.

- [ ] **Step 7: Run both gates**

Run: `python verify_docs.py` then `python health_check.py`
Expected: `verify_docs.py` exits 0 (note: it fails on Windows for an unrelated pre-existing reason — it falls back to `/tmp`, which does not exist there; run it from WSL, or fix that line separately). `health_check.py` exits 0 with the new check passing.

- [ ] **Step 8: Commit**

```bash
git add app/core/migrations/0027_person_levels_archive.sql app/core/rates.py \
        docs/DATABASE_SCHEMA.md health_check.py
git commit -m "Add archived_at to person_levels and hide archived levels by default"
```

---

### Task 7: The levels screen and its usage counts

**Files:**
- Modify: `app/modules/rates/models.py` — `list_levels`, `level_usage`
- Modify: `app/modules/rates/routes.py` — `GET /rates/levels`
- Create: `app/templates/modules/rates/levels.html`
- Modify: `app/templates/modules/rates/index.html` — a link to it
- Test: `health_check.py`

**Interfaces:**
- Consumes: `rates.levels(include_archived=True)` from Task 6.
- Produces:
  - `models.list_levels() -> list[sqlite3.Row]` — every level including archived
  - `models.level_usage(level_id) -> dict` with integer keys `people`, `rate_entries`, `title_maps`, `history`
  - Route `rates.levels_index` at `/rates/levels`

- [ ] **Step 1: Write the failing check**

```python
            check("GET /rates/levels → 200",
                  client.get("/rates/levels").status_code == 200,
                  f"got {client.get('/rates/levels').status_code}")
            with app.app_context():
                from app.modules.rates import models as rates_models
                ladder = rates_models.list_levels()
                usage = rates_models.level_usage(ladder[0]["id"]) if ladder else {}
            check("level_usage counts all four dependants",
                  {"people", "rate_entries", "title_maps", "history"} <= set(usage),
                  str(sorted(usage)))
```

- [ ] **Step 2: Run it and watch it fail**

Run: `python health_check.py`
Expected: FAIL — `GET /rates/levels` returns 404.

- [ ] **Step 3: Add the model queries**

In `app/modules/rates/models.py`:

```python
def list_levels():
    return get_db().execute(
        "SELECT * FROM person_levels ORDER BY sort_order DESC"
    ).fetchall()


def level_usage(level_id):
    """What would break if this level went away.

    Shown before any destructive action, and each count links to its rows,
    so "128 people" is checkable rather than a number to be trusted (P3).
    """
    db = get_db()
    counts = {}
    for key, sql in (
        ("people", "SELECT COUNT(*) AS n FROM people WHERE level_id = ?"),
        ("rate_entries", "SELECT COUNT(*) AS n FROM rate_card_entries WHERE level_id = ?"),
        ("title_maps", "SELECT COUNT(*) AS n FROM job_title_map WHERE level_id = ?"),
        ("history", "SELECT COUNT(*) AS n FROM person_level_history WHERE level_id = ?"),
    ):
        counts[key] = db.execute(sql, (level_id,)).fetchone()["n"]
    return counts
```

- [ ] **Step 4: Add the route**

In `app/modules/rates/routes.py`:

```python
@bp.get("/levels")
def levels_index():
    ladder = models.list_levels()
    return render_template(
        "modules/rates/levels.html",
        levels=ladder,
        usage={level["id"]: models.level_usage(level["id"]) for level in ladder},
        crumbs=[("Budgets & Rates", url_for("rates.index")), "Levels"],
    )
```

- [ ] **Step 5: Write the template**

Create `app/templates/modules/rates/levels.html`:

```jinja
{% extends "base.html" %}
{% block title %}Levels{% endblock %}

{% block content %}
<header class="pos-page-head">
  <div>
    <h1 class="pos-page-title">Levels</h1>
    <p class="pos-page-subtitle">
      The rate-bearing ladder. Rate cards price by level, so a level is not a
      label — it is what somebody bills at. Retiring one archives it; the rate
      history that referenced it stays priced exactly as it was.
    </p>
  </div>
</header>

<section class="pos-panel">
  <h2 class="pos-panel-heading">The ladder</h2>
  <table class="pos-table pos-table-compact">
    <thead>
      <tr>
        <th scope="col">Level</th><th scope="col" class="pos-num">Sort</th>
        <th scope="col">On ladder</th>
        <th scope="col" class="pos-num">People</th>
        <th scope="col" class="pos-num">Rate entries</th>
        <th scope="col" class="pos-num">Title maps</th>
        <th scope="col" class="pos-num">History</th>
        <th scope="col">State</th>
      </tr>
    </thead>
    <tbody>
      {% for level in levels %}
      <tr {% if level.archived_at %}class="pos-row-archived"{% endif %}>
        <td>{{ level.label }}</td>
        <td class="pos-num">{{ level.sort_order | num }}</td>
        <td>{{ 'yes' if level.is_on_ladder else 'no' }}</td>
        <td class="pos-num">
          <a class="pos-trace"
             href="{{ url_for('people.index', level_id=level.id) }}">{{ usage[level.id].people | num }}</a>
        </td>
        <td class="pos-num">{{ usage[level.id].rate_entries | num }}</td>
        <td class="pos-num">
          <a class="pos-trace" href="{{ url_for('people.titles') }}">{{ usage[level.id].title_maps | num }}</a>
        </td>
        <td class="pos-num">{{ usage[level.id].history | num }}</td>
        <td>
          {% if level.archived_at %}
            <span class="pos-badge pos-badge-archived">archived</span>
          {% else %}
            <span class="pos-badge pos-badge-ok">active</span>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

- [ ] **Step 6: Link it from the rates index**

In `app/templates/modules/rates/index.html`, add to the page actions:

```jinja
    <a class="pos-btn" href="{{ url_for('rates.levels_index') }}">Levels</a>
```

- [ ] **Step 7: Run the check and watch it pass**

Run: `python health_check.py`
Expected: PASS, exit 0. Also add `("/rates/levels", 200)` to the `routes` list in the same file so the page is smoke-tested from now on.

- [ ] **Step 8: Commit**

```bash
git add app/modules/rates/models.py app/modules/rates/routes.py \
        app/templates/modules/rates/levels.html \
        app/templates/modules/rates/index.html health_check.py
git commit -m "Add a levels screen showing what each level prices"
```

---

### Task 8: Creating, editing, archiving and deleting a level

**Files:**
- Modify: `app/modules/rates/models.py` — `create_level`, `update_level`, `set_level_archived`, `delete_level`, `label_or_order_taken`
- Modify: `app/modules/rates/routes.py` — five POST routes
- Modify: `app/templates/modules/rates/levels.html` — forms
- Test: `health_check.py`

**Interfaces:**
- Consumes: `models.level_usage` from Task 7.
- Produces:
  - `models.create_level(label, sort_order, is_on_ladder) -> int`
  - `models.update_level(level_id, fields) -> int`
  - `models.set_level_archived(level_id, archived=True) -> int`
  - `models.delete_level(level_id) -> int`
  - `models.label_or_order_taken(label, sort_order, exclude_id=None) -> str | None`

- [ ] **Step 1: Write the failing checks**

```python
            with app.app_context():
                from app.modules.rates import models as rates_models
                new_id = rates_models.create_level("Health Check Level", 9999, 0)
                clash = rates_models.label_or_order_taken("Health Check Level", 1)
            check("a duplicate label is reported", clash is not None, str(clash))

            # Find a level something actually references rather than assuming
            # an id, so this holds on any database.
            with app.app_context():
                referenced = next(
                    (l["id"] for l in rates_models.list_levels()
                     if any(rates_models.level_usage(l["id"]).values())),
                    None,
                )
            if referenced:
                in_use = client.post(f"/rates/levels/{referenced}/delete",
                                     headers={"Origin": "http://localhost"},
                                     follow_redirects=True)
                check("deleting a level in use is refused",
                      b"cannot be deleted" in in_use.data)
                with app.app_context():
                    still_there = [l["id"] for l in rates_models.list_levels()]
                check("and the level survives the refusal", referenced in still_there)

            client.post(f"/rates/levels/{new_id}/archive", headers={"Origin": "http://localhost"})
            with app.app_context():
                from app.core import rates as core_rates
                labels = [l["label"] for l in core_rates.levels()]
            check("an archived level leaves the pickers",
                  "Health Check Level" not in labels)

            client.post(f"/rates/levels/{new_id}/delete", headers={"Origin": "http://localhost"})
            with app.app_context():
                remaining = [l["id"] for l in rates_models.list_levels()]
            check("an unused level can be deleted", new_id not in remaining)
```

Level id `1` must be one that people reference; if the seeded ladder differs, use any id whose `level_usage` is non-zero.

- [ ] **Step 2: Run them and watch them fail**

Run: `python health_check.py`
Expected: FAIL — `module 'app.modules.rates.models' has no attribute 'create_level'`.

- [ ] **Step 3: Add the model writes**

In `app/modules/rates/models.py`:

```python
def label_or_order_taken(label, sort_order, exclude_id=None):
    """Which uniqueness rule this would break, or None.

    Label and sort order carry the ladder's meaning now that level_key is
    retired, so two live levels sharing either one leaves "the level above
    Manager" with no defined answer.
    """
    db = get_db()
    clash = db.execute(
        "SELECT label FROM person_levels "
        "WHERE archived_at IS NULL AND lower(label) = lower(?) AND id IS NOT ?",
        (label, exclude_id),
    ).fetchone()
    if clash:
        return f"another level is already called {clash['label']}"
    clash = db.execute(
        "SELECT label FROM person_levels "
        "WHERE archived_at IS NULL AND sort_order = ? AND id IS NOT ?",
        (sort_order, exclude_id),
    ).fetchone()
    if clash:
        return f"{clash['label']} already sorts at {sort_order}"
    return None


def _level_key_for(label, row_id):
    """level_key is retired: it carries no logic and is never shown.

    It survives only because SQLite refuses to drop a UNIQUE column, so new
    rows still have to satisfy the constraint. The row id is the identifier.
    """
    from app.core.paths import safe_slug

    return f"{safe_slug(label)}-{row_id}"


def create_level(label, sort_order, is_on_ladder=1):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO person_levels (level_key, label, sort_order, is_on_ladder) "
        "VALUES (?, ?, ?, ?)",
        (f"pending-{sort_order}-{label}"[:60], label, sort_order, is_on_ladder),
    )
    level_id = cursor.lastrowid
    db.execute("UPDATE person_levels SET level_key = ? WHERE id = ?",
               (_level_key_for(label, level_id), level_id))
    db.commit()
    return level_id


LEVEL_WRITABLE = ("label", "sort_order", "is_on_ladder",
                  "auto_promote_to_level_id", "auto_promote_after_months")


def update_level(level_id, fields):
    payload = {k: v for k, v in fields.items() if k in LEVEL_WRITABLE}
    if not payload:
        return 0
    assignments = ", ".join(f"{column} = ?" for column in payload)
    db = get_db()
    cursor = db.execute(
        f"UPDATE person_levels SET {assignments} WHERE id = ?",
        list(payload.values()) + [level_id],
    )
    db.commit()
    return cursor.rowcount


def set_level_archived(level_id, archived=True):
    db = get_db()
    stamp = "datetime('now')" if archived else "NULL"
    cursor = db.execute(
        f"UPDATE person_levels SET archived_at = {stamp} WHERE id = ?", (level_id,)
    )
    db.commit()
    return cursor.rowcount


def delete_level(level_id):
    db = get_db()
    cursor = db.execute("DELETE FROM person_levels WHERE id = ?", (level_id,))
    db.commit()
    return cursor.rowcount
```

- [ ] **Step 4: Add the five routes**

In `app/modules/rates/routes.py`:

```python
@bp.post("/levels")
def create_level():
    label = (request.form.get("label") or "").strip()
    sort_order = request.form.get("sort_order", type=int)
    if not label or sort_order is None:
        flash("A level needs a name and a sort order.", "error")
        return redirect(url_for("rates.levels_index"))

    clash = models.label_or_order_taken(label, sort_order)
    if clash:
        flash(f"Not created — {clash}.", "error")
        return redirect(url_for("rates.levels_index"))

    level_id = models.create_level(label, sort_order,
                                   1 if request.form.get("is_on_ladder") else 0)
    activity.log("rate_card", None, "created", f"Added the level {label}")
    flash(f"{label} added to the ladder at sort order {sort_order}. "
          "It has no rate-card entries yet, so nobody prices from it.", "success")
    return redirect(url_for("rates.levels_index"))


@bp.post("/levels/<int:level_id>")
def update_level(level_id):
    label = (request.form.get("label") or "").strip()
    sort_order = request.form.get("sort_order", type=int)
    if not label or sort_order is None:
        flash("A level needs a name and a sort order.", "error")
        return redirect(url_for("rates.levels_index"))

    clash = models.label_or_order_taken(label, sort_order, exclude_id=level_id)
    if clash:
        flash(f"Not saved — {clash}.", "error")
        return redirect(url_for("rates.levels_index"))

    models.update_level(level_id, {
        "label": label,
        "sort_order": sort_order,
        "is_on_ladder": 1 if request.form.get("is_on_ladder") else 0,
    })
    activity.log("rate_card", None, "updated", f"Updated the level {label}")
    flash(f"{label} saved.", "success")
    return redirect(url_for("rates.levels_index"))


@bp.post("/levels/<int:level_id>/archive")
def archive_level(level_id):
    models.set_level_archived(level_id, True)
    activity.log("rate_card", None, "archived", f"Archived level {level_id}")
    flash("Level archived. It is gone from the pickers; every rate-card entry "
          "and history row that referenced it is untouched and still prices.",
          "success")
    return redirect(url_for("rates.levels_index"))


@bp.post("/levels/<int:level_id>/restore")
def restore_level(level_id):
    models.set_level_archived(level_id, False)
    activity.log("rate_card", None, "restored", f"Restored level {level_id}")
    flash("Level restored — it is selectable again.", "success")
    return redirect(url_for("rates.levels_index"))


@bp.post("/levels/<int:level_id>/delete")
def delete_level(level_id):
    usage = models.level_usage(level_id)
    if any(usage.values()):
        parts = [f"{count} {name.replace('_', ' ')}"
                 for name, count in usage.items() if count]
        flash(
            "This level cannot be deleted — " + ", ".join(parts) +
            " still reference it. Archive it instead: that hides it from the "
            "pickers and leaves every priced row exactly as it is.",
            "error",
        )
        return redirect(url_for("rates.levels_index"))

    models.delete_level(level_id)
    activity.log("rate_card", None, "deleted", f"Deleted the unused level {level_id}")
    flash("Level deleted. Nothing referenced it.", "success")
    return redirect(url_for("rates.levels_index"))
```

- [ ] **Step 5: Add the forms to the template**

In `levels.html`, add an Actions column to the table with archive/restore and delete forms per row, and a create form below the table:

```jinja
        <td>
          <form method="post" class="pos-inline-form"
                action="{{ url_for('rates.archive_level', level_id=level.id)
                           if not level.archived_at
                           else url_for('rates.restore_level', level_id=level.id) }}">
            <button type="submit" class="pos-btn pos-btn-small">
              {{ 'Restore' if level.archived_at else 'Archive' }}
            </button>
          </form>
          {% if not usage[level.id].values() | select | list %}
          <form method="post" class="pos-inline-form"
                action="{{ url_for('rates.delete_level', level_id=level.id) }}">
            <button type="submit" class="pos-btn pos-btn-small pos-btn-danger">Delete</button>
          </form>
          {% endif %}
        </td>
```

```jinja
<section class="pos-panel">
  <h2 class="pos-panel-heading">Add a level</h2>
  <form method="post" action="{{ url_for('rates.create_level') }}">
    <div class="pos-field">
      <label for="l-label">Name</label>
      <input type="text" id="l-label" name="label" required>
    </div>
    <div class="pos-field">
      <label for="l-sort">Sort order — higher is more senior</label>
      <input type="number" id="l-sort" name="sort_order" required>
    </div>
    <div class="pos-field">
      <label for="l-ladder">
        <input type="checkbox" id="l-ladder" name="is_on_ladder" checked> On the rate ladder
      </label>
    </div>
    <div class="pos-page-actions">
      <button type="submit" class="pos-btn pos-btn-primary">Add level</button>
    </div>
  </form>
</section>
```

- [ ] **Step 6: Run the checks and watch them pass**

Run: `python health_check.py`
Expected: PASS on all four, exit 0.

- [ ] **Step 7: Confirm in the browser**

Add a level, try to add a second with the same name — the refusal must name the clash. Try to delete a level people hold: the message must say how many of what. Archive it instead, then open a contact and confirm the level is gone from the picker while anyone already on it still displays it.

- [ ] **Step 8: Commit**

```bash
git add app/modules/rates/models.py app/modules/rates/routes.py \
        app/templates/modules/rates/levels.html health_check.py
git commit -m "Manage the level ladder: create, edit, archive, restore, delete"
```

---

### Task 9: The level popover in the contacts grid

**Files:**
- Modify: `app/modules/people/routes.py` — `change_level_inline`
- Modify: `app/static/js/inline-edit.js` — the `level-popover` type
- Modify: `app/templates/modules/people/index.html` — the Level cell and the options block
- Modify: `app/static/css/personalos.css` — popover styles
- Test: `health_check.py`

**Interfaces:**
- Consumes: `models.record_level_change(person_id, level_id, effective_from, reason, note)`, `rates.levels()` from Task 6.
- Produces: route `people.change_level_inline` at `POST /people/<id>/level/inline`, returning `{"ok": true, "display": "<level label>"}`.

- [ ] **Step 1: Write the failing checks**

```python
            # A level change is a money event, not a text edit: it has to
            # write history, and a correction must not read as a promotion.
            if subject:
                with app.app_context():
                    from app.core import rates as core_rates
                    from app.modules.people import models as people_models
                    target = core_rates.levels()[0]["id"]
                    was = people_models.get_person(person_id)["last_promoted_on"]
                    history_before = len(people_models.level_history(person_id))

                changed = client.post(
                    f"/people/{person_id}/level/inline",
                    data={"level_id": target, "effective_from": "2026-01-01",
                          "reason": "correction"},
                    headers={"Origin": "http://localhost"},
                )
                check("an inline level change succeeds",
                      changed.get_json().get("ok") is True, str(changed.get_json()))

                with app.app_context():
                    now = people_models.get_person(person_id)
                    history_after = len(people_models.level_history(person_id))
                check("it writes a level-history row",
                      history_after > history_before,
                      f"{history_before} → {history_after}")
                check("a correction does not touch last_promoted_on",
                      now["last_promoted_on"] == was,
                      f"{was} → {now['last_promoted_on']}")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python health_check.py`
Expected: FAIL — `POST /people/<id>/level/inline` returns 404.

- [ ] **Step 3: Add the inline endpoint**

In `app/modules/people/routes.py`, after `change_level`:

```python
@bp.post("/<int:person_id>/level/inline")
def change_level_inline(person_id):
    """The grid's level editor. Same write as change_level, JSON out.

    Level is the one grid field that cannot be a plain dropdown: writing
    people.level_id directly would skip record_level_change(), which closes
    the open history row and maintains the tenure clocks — and a promotion
    moves last_promoted_on where a correction deliberately must not
    (DESIGN_DECISIONS F7).
    """
    person = models.get_person(person_id)
    if person is None:
        abort(404)
    if person["archived_at"] is not None:
        return {"ok": False, "error": "This contact is archived — restore it first."}

    level_id = request.form.get("level_id", type=int)
    effective_from = request.form.get("effective_from")
    reason = request.form.get("reason", "correction")
    if not level_id or not effective_from:
        return {"ok": False, "error": "A level change needs a level and an effective date."}
    if reason not in ("promotion", "correction"):
        return {"ok": False, "error": "A level change is either a promotion or a correction."}

    models.record_level_change(person_id, level_id, effective_from, reason,
                               request.form.get("note") or None)
    updated = models.get_person(person_id)
    activity.log("person", person_id, "updated",
                 f"{person['full_name']} recorded as {updated['level_label']} "
                 f"from {effective_from} ({reason})",
                 {"reason": reason, "effective_from": effective_from})
    return {"ok": True, "display": updated["level_label"] or ""}
```

- [ ] **Step 4: Render the Level cell as a popover trigger**

In `index.html`, replace the Level `<td>`:

```jinja
      <td data-field="level_id" data-type="level-popover"
          data-level-endpoint="/people/{{ row.id }}/level/inline"
          data-options-src="#level-options" data-value="{{ row.level_id or '' }}"
          tabindex="0">
        {% if row.level_label %}{{ row.level_label }}
        {% else %}<span class="pos-badge pos-badge-danger">no level</span>{% endif %}
      </td>
```

and add the options block once per page, beside the existing manager options block:

```jinja
<script type="application/json" id="level-options">
  {{ level_options | tojson }}
</script>
```

In `index()`, build the options before `render_template` and pass them:

```python
    # Archiving retires a level; it must not silently unset anybody already on
    # one. So the picker offers the live ladder plus any archived level
    # somebody on this page still holds, labelled for what it is.
    live_levels = rates.levels()
    known = {level["id"] for level in live_levels}
    level_options = [{"id": level["id"], "label": level["label"]}
                     for level in live_levels]
    for row in rows:
        if row["level_id"] and row["level_id"] not in known:
            known.add(row["level_id"])
            level_options.append({"id": row["level_id"],
                                  "label": f"{row['level_label']} (archived)"})
```

and in the `render_template` call:

```python
        level_options=level_options,
        today=date.today().isoformat(),
```

- [ ] **Step 5: Add the popover editor**

In `app/static/js/inline-edit.js`, at the top of `enterEdit`, before `var input = buildInput(td);`:

```javascript
    if (td.dataset.type === "level-popover") {
      openLevelPopover(td);
      return;
    }
```

and add this function above `enterEdit`:

```javascript
  /* Level is not a scalar edit. It carries an effective date and a reason,
   * because a promotion moves the tenure clock and a correction must not,
   * so the cell opens a small form rather than a dropdown. */
  function openLevelPopover(td) {
    if (td.dataset.editing === "1") return;
    var tr = td.closest("tr");
    if (!tr || tr.dataset.archived === "1") return;

    td.dataset.editing = "1";
    td.dataset.savedHtml = td.innerHTML;
    clearError(td);

    var form = document.createElement("form");
    form.className = "pos-level-popover";

    var select = document.createElement("select");
    select.name = "level_id";
    optionsFromSrc(td.dataset.optionsSrc).forEach(function (o) {
      var opt = document.createElement("option");
      opt.value = String(o.id);
      opt.textContent = o.label;
      if (String(o.id) === String(td.dataset.value)) opt.selected = true;
      select.appendChild(opt);
    });

    var when = document.createElement("input");
    when.type = "date";
    when.name = "effective_from";
    /* Today comes from the server on the table's data-today, not from the
     * browser's clock: the effective date of a level change is a business
     * fact, and a machine with a skewed clock must not write one. */
    var table = td.closest("table");
    when.value = (table && table.dataset.today) || "";

    var reason = document.createElement("select");
    reason.name = "reason";
    [["correction", "Correction — fixing the record"],
     ["promotion", "Promotion — resets the tenure clock"]].forEach(function (pair) {
      var opt = document.createElement("option");
      opt.value = pair[0];
      opt.textContent = pair[1];
      reason.appendChild(opt);
    });

    var save = document.createElement("button");
    save.type = "submit";
    save.className = "pos-btn pos-btn-small pos-btn-primary";
    save.textContent = "Save";

    [select, when, reason, save].forEach(function (el) { form.appendChild(el); });
    td.textContent = "";
    td.appendChild(form);
    select.focus();

    function close() {
      td.dataset.editing = "0";
      td.innerHTML = td.dataset.savedHtml;
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var body = new URLSearchParams();
      body.set("level_id", select.value);
      body.set("effective_from", when.value);
      body.set("reason", reason.value);
      td.classList.add("pos-inline-busy");

      fetch(td.dataset.levelEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          td.classList.remove("pos-inline-busy");
          if (data && data.ok) {
            td.dataset.editing = "0";
            td.dataset.value = select.value;
            td.textContent = data.display;
            clearError(td);
          } else {
            showError(td, (data && data.error) || "Save failed.");
          }
        })
        .catch(function () {
          td.classList.remove("pos-inline-busy");
          showError(td, "Could not reach the server.");
        });
    });

    form.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    });
  }
```

Set `data-today` on the table in `index.html`, which is what the popover reads:

```jinja
<table class="pos-table" id="people-table" data-pos-table data-pos-server-sort
       data-today="{{ today }}" data-edit-base="/people/{id}/field">
```

- [ ] **Step 6: Style the popover**

Append to `app/static/css/personalos.css`:

```css
.pos-level-popover { display: flex; flex-wrap: wrap; gap: .25rem; align-items: center; }
.pos-level-popover select,
.pos-level-popover input { font-size: .9em; }
```

- [ ] **Step 7: Run the checks and watch them pass**

Run: `python health_check.py`
Expected: PASS on all three, exit 0.

- [ ] **Step 8: Confirm in the browser**

Click a Level cell: the popover opens with the level list, today's date and Correction preselected. Save, then open that person's record and check the level history tab shows the new row and `last_promoted_on` is unchanged. Repeat choosing Promotion and confirm the tenure clock does move. Press Escape to confirm it closes without writing.

- [ ] **Step 9: Run the full gate and commit**

```bash
python verify_docs.py
python health_check.py
git add app/modules/people/routes.py app/static/js/inline-edit.js \
        app/templates/modules/people/index.html app/static/css/personalos.css \
        health_check.py
git commit -m "Edit a contact's level from the grid, with its date and reason"
```

---

## Final Verification

After Task 9, walk the whole thing once:

- [ ] `python verify_docs.py` exits 0 (run from WSL; see the note in Task 6)
- [ ] `python health_check.py` exits 0
- [ ] `python run.py` starts with no traceback
- [ ] `/people/` and `/rates/levels` load with no 500s in the log
- [ ] The Key Principles checklist in `CLAUDE.md` passes for both screens — in particular P3 (every count links to its rows), P5 (levels archive rather than delete), P9 (thousands separators, long-form dates), P10 (a keyboard path to every control), and no state carried by colour alone
- [ ] `docs/BUILD_SEQUENCE.md` updated with what landed
- [ ] Update `docs/UI_DESIGN_SYSTEM.md` §3.5 to describe the header sort/filter handles, so the next table to adopt them copies a documented pattern rather than reverse-engineering this one
