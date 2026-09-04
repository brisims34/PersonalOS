# Session Handoff — 3 September 2026

Branch **`contacts-table-upgrade`**, 16 commits ahead of `main`. `main` is level
with `origin/main`, so **none of this work is merged or pushed.**

Read this first, then `docs/superpowers/specs/2026-09-03-contacts-table-upgrade-design.md`
for the reasoning behind any of it.

---

## 1. What you need to do

### Actions only you can take — these block real use

| # | Action | Where | Why it is yours |
|---|---|---|---|
| 1 | Run the contact import | `/people/import` | Writes 450 rows to the live database. Verified end to end; `AASppl.xlsx` is detected and 0 rows would be skipped. |
| 2 | Create the first rate card and enter rates | `/rates/` | Until a card exists with entries, **everyone prices at nothing**. |

Live database as at the end of this session:

```
people                1        rate_cards            0
person_levels        10        rate_card_entries     0
job_title_map        13        notes                 0
tasks                 1        projects              1
schema version       28
```

### Input needed from you

**The actual firm rates** — bill and cost by level, per company, per fiscal
year. They can be entered from a spreadsheet or a pasted table, but they cannot
be invented, and by design they are never seeded into a migration: rates are
confidential and migration files are committed to git (`DESIGN_DECISIONS.md`).

Also: **which company scoping** for the first card. The form offers *KPMG United
States of America* and *KPMG Global Services Private Limited*. Mis-scoping
understates cost on every blended engagement, which is why `company` exists on
the card at all.

Nothing else is needed — the contact spreadsheet is already in place at the repo
root.

### Decisions outstanding

1. **What happens to this branch.** 16 commits, unmerged, unpushed. Merge to
   `main`? Open a PR? Leave it running?
2. **`verify_docs.py` cannot run on Windows.** Pre-existing, unrelated to this
   work: line ~137 falls back to `os.environ.get("TMPDIR", "/tmp")`, and `/tmp`
   does not exist here, so gate 0 dies with `unable to open database file`. The
   workaround used all session was setting `TMPDIR` first. One-line fix with
   `tempfile.gettempdir()` if wanted.
3. **Auto-promotion is not exposed.** `person_levels.auto_promote_to_level_id`
   and `auto_promote_after_months` drive the "Tenure transitions due" panel, and
   they are in `LEVEL_WRITABLE`, but the Levels screen does not offer them. Add
   them to that form?
4. **`fiscal_year` type divergence.** Stored INTEGER on `rate_cards`;
   `performance_cycles.fiscal_year` in a later phase is TEXT. Harmless today,
   deliberate, unresolved.
5. **Deliberately not built** — say if any are wanted: saved filter views,
   column-visibility toggles, multi-select filters (one value per column
   today), bulk edit across selected rows, CSV import of edits.
6. **Ten stale `worktree-agent-*` branches** are still checked out in
   `.claude/worktrees/` with unmerged commits, from an earlier session. Not from
   this work. Clean up?

---

## 2. What was built this session

### The reported bug: contact import was unusable

Two defects stacked, the second hidden behind the first.

- **A 403 on every form POST in the app.** `Referrer-Policy: no-referrer` made
  browsers serialise the `Origin` of a non-CORS POST — every plain form
  submission — as `null`, which the same-origin guard then rejected. All 27
  form templates were affected; only the `fetch()`-based inline edits worked,
  because CORS-mode requests are exempt from that rule. Fixed to `same-origin`.
- **A 500 on the import preview.** `plan.update` in Jinja resolved to
  `dict.update`, the bound method, because Jinja tries attribute access before
  item access. `{% if plan.update %}` was therefore always true and
  `| length` raised. Fixed with subscript syntax, with the trap documented in
  the template.

Email deduplication was already correct and simply unreachable: lower-cased
email as the key, matched across files, within-file duplicates flagged, and
`people.email` unique. Verified on a database copy — 450 created, then a
modified re-export produced 1 update and 1 insert, not 450 duplicates.

### The contacts table (spec sections A–F)

- Sorting moved from JavaScript to SQL. `tables.js` had reordered only the
  rendered page while appearing to sort everything — on 450 rows that is a lie
  the user cannot see. Tables marked `data-pos-server-sort` are left alone by
  the client sorter.
- Sort links and per-column filter menus in the table header, with counts that
  honour the other active filters while excluding a column's own filter from
  its own counts, the way a spreadsheet autofilter behaves.
- Rows per page selectable 25–1000, default 100, clamped server-side. The pager
  now carries the whole view; it previously received four hand-picked
  parameters and silently dropped the rest.
- `GET /people/export.csv` exports every filtered row rather than the rendered
  page, sharing the index's query parser so the two cannot drift, and carries
  the whole directory record rather than the visible columns.
- Inline editing across every scalar column. **Name and email stay on the edit
  form** — email is the importer's deduplication key, so a typo fixed in a grid
  cell would quietly re-add that person on the next import.
- Level edits open a popover carrying an effective date and a reason
  (defaulting to Correction), because writing `level_id` directly bypasses
  `record_level_change()` and, per `DESIGN_DECISIONS.md` F7, a promotion moves
  the tenure clock where a correction must not.
- `/rates/levels` manages the ladder with four usage counts, archive rather
  than delete, and a delete that is refused while anything references the
  level, naming what and how many.

### Rate cards (spec section G)

- `0028_rate_card_effective_dates.sql` adds `fiscal_year`, `effective_from`,
  `effective_to`.
- **The card's dates decide** which of its entries apply — expressed as one
  window, the intersection of the entry's range with the card's, so
  `resolve_rates()` never holds two date filters that could disagree.
- A NULL bound is unbounded, and the migration leaves the date columns NULL, so
  every pre-existing card prices exactly what it always did.
- The Levels screen now shows the bill and cost rate in force on a date, read
  through that same window.

### Two fixes found while looking at screenshots

- `.pos-field` applied `min-width: 180px` to every input, **including
  checkboxes**, so the box itself was 180px wide and its label stranded at the
  far end. Affected the Add-a-level form and the contacts filter toggles.
- `ago()` and `datetime_long()` read UTC timestamps against a local clock, so
  anything written in the last few hours displayed as **"in the future"** and
  activity times were hours off. `notes.mtime` was the one column stored in
  local time, so `ago()` was being handed two conventions; it now stores UTC
  like everything else. That field is change-detection state, so the next scan
  re-indexes each note once and self-heals.

---

## 3. Decisions already made — do not relitigate

| Decision | Why |
|---|---|
| `level_key` is retired, not dropped | The row id was always the immutable identifier every FK points at. The column stays because SQLite refuses to drop a UNIQUE column, and rebuilding a table four FKs point into buys no behaviour change. New rows auto-fill it; nothing reads it. |
| Label and sort order are unique among non-archived levels | They now carry the meaning `level_key` used to. Without it, "the level above Manager" has no defined answer. Enforced in the route, not the schema, for the same rebuild reason. |
| Level is a popover, not a dropdown | A dropdown would have to guess promotion vs correction and would corrupt either tenure or rate history. |
| Card dates decide, entry dates refine | Brian's call, against the original recommendation. The risk was two competing date filters, so it is implemented as a single intersected window instead. |
| Levels admin lives under Budgets & Rates | Brian's call. Levels are the rate-bearing ladder. |
| Level operations live in `app/core/rates.py` | The rates module has no `models.py`; its level queries already lived in core, and other modules read levels through it. |
| Schema doc convention | A table's main DDL block mirrors the migration that created it (see `entity_links` vs §0008); later changes get their own migration section plus a row in the ownership table. `verify_docs` enforces exactly this. |
| Health checks that write run on a throwaway copy | `health_check.py` is run routinely against a live roster; a check that mutated it would be a defect. The copy is migrated to head and seeded, because a check over an empty table passes without proving anything. |

---

## 4. Working notes for the next session

**The repo's `.venv` is empty and has no pip** — `.venv\Scripts\python.exe`
cannot run anything. Build a throwaway venv in the scratchpad from
`C:\Python314\python.exe` and `pip install -r requirements.txt`, then use that
interpreter for `run.py`, `health_check.py`, `apply_migrations.py`.

**Never run against `app/data/personalos.db` while testing.** It holds live
data. Two harnesses were used this session and are worth recreating:

- `serve_seeded.py` — copies the live database to the scratchpad, migrates the
  copy to head, seeds ~140 contacts across several companies, departments and
  levels, and serves on port 5055. Paging, sorting and the filter menus cannot
  be exercised at all against a one-contact roster.
- Overriding `app.config["DATABASE_PATH"]` after `create_app(run_migrations=False)`
  points the app at any copy.

**Templates do not auto-reload without `--debug`.** After editing a `.html`,
restart the server or the old compiled template keeps rendering — and the
traceback will point at the *new* file's line numbers, which is thoroughly
misleading. This cost real time this session.

**`apply_migrations.py` prompts**; use `--yes` in a non-interactive shell.

**`verify_docs.py` needs `TMPDIR` set on Windows** — see decision 2 above.

**Gates:** `python verify_docs.py` and `python health_check.py` must both exit
0. Health check is at 115 checks; 4 warnings are optional packages absent from
the scratch venv (`win32com`, and the three AI-subsystem packages) and are
expected.

---

## 5. Where things are

| Thing | Path |
|---|---|
| Design (all sections A–G) | `docs/superpowers/specs/2026-09-03-contacts-table-upgrade-design.md` |
| Plan — contacts table | `docs/superpowers/plans/2026-09-03-contacts-table-upgrade.md` |
| Plan — rate card fiscal year | `docs/superpowers/plans/2026-09-03-rate-card-fiscal-year.md` |
| What landed | `docs/BUILD_SEQUENCE.md`, at the end |
| Migrations added | `0027_person_levels_archive.sql`, `0028_rate_card_effective_dates.sql` |
| Pre-migration backups | `app/data/backups/personalos-*-premigration-v0026.db`, `-v0027.db` |
| Prior inline-edit contract | `docs/superpowers/specs/2026-09-02-inline-table-editing-design.md` |

Both plans are fully executed. Every task in them was implemented, verified and
committed; the plans are kept as the record of why each step exists.
