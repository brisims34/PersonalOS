# Contacts Table Upgrade — Design

**Date:** 2026-09-03
**Branch:** `contacts-table-upgrade`
**Status:** approved — ready for an implementation plan

Sections A–F are the contacts roster and the levels admin screen. Section G —
fiscal year and effective dates on rate cards — is the money subsystem, and is
sequenced after them so the roster work does not wait behind a change to how
rates resolve.

Builds on `2026-09-02-inline-table-editing-design.md`, which defines the
inline-edit mechanism (the `data-edit-base` / `data-field` / `data-type`
contract, the `POST /<module>/<id>/field` route shape, and the
`{ok, display}` / `{ok, error}` response). This spec extends that contract
rather than restating it.

## Context

The contacts roster at `/people/` is the page Brian works from daily, and four
things about it are wrong.

1. **Sorting lies.** `tables.js` reorders only the rows already rendered, so on
   a paginated view "sort by Level" sorts fifty rows out of four hundred and
   fifty and says nothing about it. The server can already sort the whole set
   through `?sort=`, but no header uses it. Filtering lives in a panel above the
   table rather than on the columns it filters, and the page size is hardcoded
   at 50.
2. **Export CSV exports the page.** `toCsv()` walks the rendered DOM, so the
   file holds whichever fifty rows happened to be on screen, with nothing to
   indicate the other four hundred are missing.
3. **Level is unmanageable.** `person_levels` is a proper lookup table with a
   seeded ladder, and rate cards price by it, but no screen in the application
   creates, edits or retires a level — and the contacts table does not even let
   you set one.
4. **Only four fields edit inline:** `status`, `job_title`, `department` and
   `manager_person_id`. Everything else is a round trip through the edit form.

## Non-goals

- Does not touch the org chart, the import wizard, or the job-title map at
  `/people/titles`.
- Does not convert any other module's tables. The controls are built so another
  module can adopt them, but nothing else is converted here.
- Does not add column-visibility toggles, saved filter views, multi-select
  filters (one value per column), bulk edit across selected rows, or CSV import
  of edits.
- Does not make name or email inline-editable — see section E.

## A. One query contract

Every control writes to the URL. Nothing holds list state in JavaScript.

```text
/people/?q=&sort=level&dir=desc&per_page=100&page=1
        &level_id=&company=&department=&function=&status=
        &archived=&unmapped=&no_manager=
```

A single `_list_query()` helper in `app/modules/people/routes.py` parses this
into the keyword arguments `models.list_people()` and `models.count_people()`
already accept. **Both the index view and the export view call it.** The export
cannot drift from what is on screen, because there is one parse rather than two
that have to agree.

The page stays bookmarkable, the back button behaves, and every filtered view
has a URL — which is what lets a roster count link to the rows behind it (P3).

## B. Header controls

Each `<th>` in the contacts table carries:

**A sort link** — `?sort=<key>&dir=asc|desc`, preserving every other parameter.
The active column sets `aria-sort` to `ascending` or `descending` and shows a
glyph; clicking the active column toggles direction. `SORTABLE` in
`app/modules/people/models.py` gains `department`, `status` and `function`
entries, and `list_people()` gains a `direction` argument. Direction is
validated against `("asc", "desc")` and mapped to fixed SQL text — never
interpolated from the request (CLAUDE.md rule 2).

Today's `SORTABLE` entries bake direction into the expression: `level` is
`"l.sort_order DESC, p.last_name"`, so a `direction` argument layered on top of
it would produce either `DESC DESC` or a silent contradiction. Each entry
therefore becomes a pair — a direction-neutral ordering expression and the
column's **default** direction — with the query builder appending `ASC` or
`DESC` to the leading term. `level` keeps `desc` as its default, so the first
click on that header still shows the most senior people first, exactly as the
column behaves today. Every tie-breaker after the leading term keeps its fixed
direction, so ordering stays stable across pages.

**A filter menu**, on the columns whose values come from a fixed set: Level,
Company, Department, Function, Status. A `<details>` disclosure holds that
column's distinct values with a count beside each, an "All" reset, and one link
per value setting the corresponding query parameter. Counts honour every *other*
active filter — the behaviour a spreadsheet autofilter trains you to expect —
while a column's own filter is excluded from its own counts, so you can always
see what else you could switch to.

A new `models.column_values(column, **filters)` returns those value/count pairs.
`column` is resolved through a developer-defined dict of permitted columns, so
no request data ever reaches the SQL text (rule 2).

The panel above the table keeps what does not belong to any single column: the
search box and the archived / unmapped / no-manager toggles.

Every control is a link or a form control. The page works with JavaScript
disabled, needs no inline script (the CSP forbids them), and everything is
reachable by keyboard (P10). `tables.js` stops applying its client-side sort to
tables marked `data-pos-server-sort`, and gains menu behaviour: close on
Escape, close on outside click, submit on change.

## C. Pagination

`per_page` accepts 25, 50, 100, 250, 500 or 1000, defaulting to **100**, clamped
server-side to that set so a hand-edited `?per_page=999999` cannot ask SQLite
for the whole table. A selector sits beside the result count and preserves the
rest of the query. `PAGE_SIZE = 50` becomes `DEFAULT_PER_PAGE = 100` with
`PER_PAGE_OPTIONS` beside it.

The `pager()` macro currently receives a hand-built dict of arguments at each
call site, which is how `department`, `status` and `dir` would silently vanish
from the next-page link. The index passes the parsed query through instead, so
pagination carries the full state.

## D. Export

`GET /people/export.csv` streams the full filtered result set with no `LIMIT`
and no `OFFSET`.

- The same `_list_query()` parse as the index, so the file matches the screen's
  filters exactly. No filters means the whole roster.
- Exports every directory field rather than the eight visible columns: external
  ref, name parts, email, company, department, job title, level, function,
  status, all three phones, city, state/province, manager name, manager email.
- `Content-Disposition: attachment; filename="personalos-contacts-YYYY-MM-DD.csv"`.
- Written through the `csv` module and a generator, so quoting and embedded
  newlines are correct and the response streams rather than assembling one
  string in memory.
- `GET` is correct here: it changes no state. Rule 4 governs writes.

The Export CSV button becomes a link carrying the current query string, and the
contacts table drops `data-pos-export`. `makeExportable()` stays in `tables.js`
for the non-paginated tables still using it.

## E. Inline editing

`PERSON_INLINE_FIELDS` grows from four fields to nine, reusing the `data-type`
contract from the 2026-09-02 spec:

| Field | `data-type` |
|---|---|
| `job_title` | `text` |
| `department` | `text` |
| `company` | `text` |
| `city` | `text` |
| `state_province` | `text` |
| `function` | `text` |
| `status` | `select` — active / inactive / departed |
| `manager_person_id` | `fk-select` against the page's people options block |
| `level_id` | `level-popover` — a new type, see below |

Name and email stay on the edit form. Email is the key the contact importer
deduplicates on, so a typo corrected in a grid cell would quietly cause the next
spreadsheet load to insert that person again instead of updating them.

### Level is not a plain dropdown

Writing `people.level_id` directly would bypass `models.record_level_change()`,
which closes the open `person_level_history` row and maintains the denormalised
clocks on `people`. Per DESIGN_DECISIONS F7, a *promotion* moves
`last_promoted_on` while a *correction* deliberately must not. A one-tap
dropdown would have to guess which was meant, corrupting either tenure or rate
history.

So the Level cell expands to a popover with three controls — level, effective
from (defaulting to today), reason (Correction / Promotion) — posting to
`POST /people/<id>/level/inline`. That endpoint shares its body with the
existing `change_level` view and returns the `{ok, display}` JSON the grid
expects instead of a redirect.

**Reason defaults to Correction**, because assigning levels across a freshly
imported roster is a data fix; it must not read as four hundred promotions or
reset anybody's tenure clock.

The options are the non-archived levels plus the person's current level if that
happens to be archived, so an existing assignment is never silently dropped from
its own picker.

## F. Levels administration

Under Budgets & Rates, not a new module — levels are the rate-bearing ladder and
rate cards price by them.

`GET /rates/levels` lists the ladder in sort order: label, sort order,
on-ladder flag, archived state, and **usage counts** — people on it, rate-card
entries priced at it, job-title mappings pointing at it, level-history rows
referencing it. Each count links to the rows behind it (P3).

### The identifier is the row id

`person_levels.id` is already `INTEGER PRIMARY KEY AUTOINCREMENT`, and every
foreign key that matters — `people.level_id`, `rate_card_entries.level_id`,
`job_title_map.level_id`, `person_level_history.level_id` — already points at
it. It is the immutable numeric key; nothing else needs to be.

`level_key` carries no logic today. It appears in six queries as a projection,
is discarded unused at `app/core/rates.py:79`, and no template renders it. Its
only real job was identifying seed rows in `0002_people.sql`.

So it is **retired rather than removed**: it disappears from this screen and
from every query the application uses for logic, and new levels auto-fill it
with a slug of the label plus the row id to satisfy its `NOT NULL UNIQUE`
constraint. The column stays because SQLite refuses to drop a UNIQUE column
(`cannot drop UNIQUE column: "level_key"`), so removing it would mean rebuilding
a table that four foreign keys point into — open-heart surgery on the table that
prices all the money, for no behaviour change.

Because label and sort order now carry the meaning, the create and update routes
enforce both as **unique among non-archived levels**. Without that, "the level
above Manager" has no defined answer. This is enforced in the route rather than
by a schema constraint, for the same rebuild reason.

Mutations are all POST (rule 4) and all activity-logged (rule 13):

- `POST /rates/levels` — create.
- `POST /rates/levels/<id>` — update label, sort order, on-ladder flag, and the
  auto-promotion pair. The row id never changes; `level_key` is neither shown
  nor editable.
- `POST /rates/levels/<id>/archive` and `/restore` — archiving hides a level
  from every picker while leaving history and rate-card entries priced exactly
  as they were. This mirrors what rate cards already do at
  `app/modules/rates/routes.py:154`.
- `POST /rates/levels/<id>/delete` — permitted only when all four usage counts
  are zero. Otherwise refused, naming what references it and how many (P5:
  destructive actions preview, and archive rather than delete).

`rates.levels()` gains `include_archived=False`, so every existing caller keeps
today's behaviour by default.

## G. Rate card fiscal year and effective dates

Sequenced after A–F and independently implementable — this is the money
subsystem, not the contacts table, and the roster work should not wait behind
it.

Today `rate_cards` records no fiscal year and no dates. Dates live only on
`rate_card_entries`, so a card's fiscal year is *implied* by its entry dates:
`app/modules/rates/routes.py:43` groups entries by `effective_from` "so a fiscal
year reads as one block", and `DATABASE_SCHEMA.md` already claims "one card per
fiscal year" while nothing records which one.

The `fiscal_year_start` app setting already exists, seeded `10-01`, so FY2026
means 1 October 2025 to 30 September 2026 and no new configuration is needed.

Migration `app/core/migrations/0028_rate_card_effective_dates.sql`:

```sql
ALTER TABLE rate_cards ADD COLUMN fiscal_year    INTEGER;
ALTER TABLE rate_cards ADD COLUMN effective_from DATE;
ALTER TABLE rate_cards ADD COLUMN effective_to   DATE;
```

All three additive and nullable. `fiscal_year` is backfilled for existing cards
from the earliest entry date, which is display only and changes no arithmetic.
**The date columns are deliberately left NULL on existing cards**, because a
NULL bound means unbounded — so every card that prices something today prices it
identically after the migration. Setting a range is then a deliberate act per
card.

`fiscal_year` is stored as an INTEGER so it sorts and `FY + 1` is arithmetic.
Note this diverges from `performance_cycles.fiscal_year`, which a later phase
defines as TEXT.

### The card's dates decide

Brian's decision. The risk in it is two competing date filters inside
`resolve_rates()`, which is how a rate quietly resolves to the wrong fiscal
year, so the semantics are defined as a single window rather than two tests:

1. A card with a range applies only when the work date falls inside it. A NULL
   bound is unbounded.
2. Within an applicable card, the window for an entry is the **intersection** of
   the entry's range and the card's — the later of the two starts, the earlier
   of the two ends. One predicate, one selection path.

```sql
  AND max(e.effective_from, coalesce(c.effective_from, e.effective_from)) <= :work_date
  AND :work_date <= min(coalesce(e.effective_to, '9999-12-31'),
                        coalesce(c.effective_to, '9999-12-31'))
```

`_effective()` in `app/core/rates.py` gains a card-aware form; `resolve_rates()`
remains the only place money is priced (rule 8).

Consequently the entry editor pre-fills entry dates from the card's range and
**refuses** an entry outside it. An entry outside its card's range can never
price anything, and accepting one silently is how you get a rate card that looks
complete and prices nothing.

Fiscal year and dates derive from each other — fill either and the other is
proposed. A contradictory pair is refused, naming both values.

Docs: `FINANCIAL_MODEL.md` §2, `TEMPORAL_MODEL.md`, and `DATABASE_SCHEMA.md`
(the `rate_cards` DDL and the Money mermaid diagram).

## Data model

Migration `app/core/migrations/0027_person_levels_archive.sql`:

```sql
ALTER TABLE person_levels ADD COLUMN archived_at DATETIME;
```

Additive, nullable, no backfill, no user data touched (rule 5).
`apply_migrations.py` takes its pre-migration backup and aborts if the backup
fails. `docs/DATABASE_SCHEMA.md` is updated — the `person_levels` DDL **and**
the People section's mermaid ER diagram.

## Files touched

| File | Change |
|---|---|
| `app/modules/people/routes.py` | `_list_query()`, index rewrite, `export_csv()`, `change_level_inline()`, `PERSON_INLINE_FIELDS`, `DEFAULT_PER_PAGE` |
| `app/modules/people/models.py` | `direction` on `list_people()`, `SORTABLE` additions, `department`/`status` filters, `column_values()` |
| `app/templates/modules/people/index.html` | header sort links and filter menus, per-page selector, export link, inline attributes on the new cells, level popover |
| `app/modules/rates/routes.py` | levels index and the five mutations |
| `app/modules/rates/models.py` | level CRUD, `level_usage()` |
| `app/core/rates.py` | `levels(include_archived=False)` |
| `app/templates/modules/rates/levels.html` | new |
| `app/templates/modules/rates/index.html` | link to Levels |
| `app/static/js/tables.js` | skip client sort on server-sorted tables, filter-menu behaviour |
| `app/static/js/inline-edit.js` | the `level-popover` editor type |
| `app/static/css/personalos.css` | header menu and popover styles |
| `app/core/migrations/0027_person_levels_archive.sql` | new |
| `health_check.py` | the checks below |
| `docs/DATABASE_SCHEMA.md`, `docs/UI_DESIGN_SYSTEM.md`, `docs/BUILD_SEQUENCE.md` | documentation |

Section G, separately:

| File | Change |
|---|---|
| `app/core/migrations/0028_rate_card_effective_dates.sql` | new |
| `app/core/rates.py` | card-aware `_effective()`, intersection window in `resolve_rates()` |
| `app/modules/rates/routes.py` | fiscal year and date fields on card create/edit; entry dates validated against the card |
| `app/modules/rates/models.py` | fiscal-year derivation from `fiscal_year_start` |
| `app/templates/modules/rates/index.html`, `card.html` | fiscal year and effective range |
| `docs/FINANCIAL_MODEL.md`, `docs/TEMPORAL_MODEL.md` | documentation |

## Verification

There is no test suite; `health_check.py` is where regressions get caught, so it
gains:

- `GET /people/?per_page=999999` clamps rather than returning everything.
- `GET /people/export.csv?company=<x>` returns only that company's rows, and
  more rows than one page holds — the actual bug being fixed.
- Export with no filters returns every non-archived contact.
- Sorting a column with `dir=desc` reverses the first row of `dir=asc`.
- An archived level disappears from the pickers but still renders on a person
  who holds it.
- Deleting a level that people reference is refused; archiving it succeeds.
- An inline level change writes a `person_level_history` row, and a reason of
  `correction` leaves `last_promoted_on` untouched.
- Two non-archived levels cannot share a label or a sort order.

For section G:

- **A card with no dates prices exactly what it priced before the migration.**
  This is the regression that matters; everything else in G is new behaviour.
- A work date outside a card's range does not price from that card.
- An entry whose range is wider than its card's is clamped: a date inside the
  entry but outside the card does not price.
- Fiscal year derives from the dates and the dates from the fiscal year; a
  contradictory pair is refused.

Manual: the Key Principles checklist in `CLAUDE.md`, `python verify_docs.py`,
and the phase checklist in `docs/BUILD_SEQUENCE.md`.

## Key Principles gate

- **P1** — the roster's primary action stays "find a contact and open them".
- **P2** — every inline-edit failure names the actual problem, per the
  2026-09-02 contract.
- **P3** — every count links to its rows, including the level usage counts.
- **P5** — levels archive; delete is refused while referenced.
- **P9** — counts keep thousands separators; dates stay long-form.
- **P10 / P11** — every sort, filter, page-size and edit control is a link, form
  control or button, operable by keyboard.
- **No state by colour alone** — the archived-level chip carries its label.
