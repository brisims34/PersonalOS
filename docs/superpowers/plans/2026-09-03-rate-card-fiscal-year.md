# Rate Card Fiscal Year and Effective Dates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record which fiscal year a rate card is for and the dates it is in force, and make those dates decide which rates apply.

**Architecture:** Three additive nullable columns on `rate_cards`, where a NULL bound means unbounded so every existing card prices exactly as it does today. The card's range becomes authoritative over the per-entry dates, expressed as a single intersection window inside `resolve_rates()` rather than as a second competing date filter.

**Tech Stack:** Python 3.11, Flask 3.x, Jinja2, stdlib `sqlite3` (no ORM), vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-09-03-contacts-table-upgrade-design.md`, section G.

**Covers:** section G only. Sections A–F are `2026-09-03-contacts-table-upgrade.md` and should land first — both plans edit `app/modules/rates/routes.py`.

## Global Constraints

Same as the contacts plan, and read that plan's "Testing In This Repo" section before starting — there is no pytest suite, `health_check.py` is the test file, and you must never run against `app/data/personalos.db` without copying it first. Beyond those:

- **All money math goes through `resolve_rates()`.** This plan changes that function; nothing else may learn to price.
- **`as_of` is a parameter, never an assumption.** No function in `app/core/` calls `date.today()`.
- **Schema changes require a migration** plus `docs/DATABASE_SCHEMA.md` including the Money mermaid ER diagram.
- **The migration must not reprice anything.** A card that prices a given hour today must price that hour identically afterwards. This is the single most important property in this plan.

---

### Task 1: The columns, and proving nothing repriced

**Files:**
- Create: `app/core/migrations/0028_rate_card_effective_dates.sql`
- Modify: `docs/DATABASE_SCHEMA.md` — the `rate_cards` DDL and the Money mermaid diagram
- Test: `health_check.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `rate_cards.fiscal_year INTEGER`, `rate_cards.effective_from DATE`, `rate_cards.effective_to DATE`.

- [ ] **Step 1: Capture what today's prices are, before touching anything**

Write `scratch_rate_snapshot.py` in your scratch directory (not the repo). It records what every person prices at on a set of dates, so the migration can be proved neutral:

```python
import json
import sys

sys.path.insert(0, r"<repo path>")

from app import create_app
from app.core.rates import resolve_rates
from app.modules.people import models as people

app = create_app(run_migrations=False)
app.config["DATABASE_PATH"] = r"<path to a copy of personalos.db>"

DATES = ("2025-01-15", "2025-10-15", "2026-01-15", "2026-06-15")

with app.app_context():
    snapshot = {}
    for person in people.list_people(limit=None):
        for work_date in DATES:
            resolved = resolve_rates(person["id"], work_date)
            snapshot[f"{person['id']}@{work_date}"] = [
                resolved.bill_rate, resolved.cost_rate, resolved.is_priced,
            ]

print(json.dumps(snapshot, indent=0))
```

Run it and save the output to `before.json`.

- [ ] **Step 2: Write the failing check**

In `health_check.py`, in the application section:

```python
            with app.app_context():
                from app.core.database import get_db
                columns = {row["name"] for row in
                           get_db().execute("PRAGMA table_info(rate_cards)")}
            check("rate_cards records its fiscal year and dates",
                  {"fiscal_year", "effective_from", "effective_to"} <= columns,
                  f"missing {{'fiscal_year', 'effective_from', 'effective_to'}} - columns")
```

- [ ] **Step 3: Run it and watch it fail**

Run: `python health_check.py`
Expected: FAIL — `rate_cards records its fiscal year and dates`.

- [ ] **Step 4: Write the migration**

Create `app/core/migrations/0028_rate_card_effective_dates.sql`:

```sql
-- A card's fiscal year was previously implied by its entries' dates, which
-- is why the rates index groups entries by effective_from to make a year
-- read as one block. Recording it makes "which year is this card" answerable.
ALTER TABLE rate_cards ADD COLUMN fiscal_year    INTEGER;
ALTER TABLE rate_cards ADD COLUMN effective_from DATE;
ALTER TABLE rate_cards ADD COLUMN effective_to   DATE;

-- Backfill the year for display only, from the earliest entry on each card.
-- The fiscal year starts on the month-day in app_settings.fiscal_year_start
-- (seeded 10-01), so an entry from October belongs to the NEXT numbered year.
UPDATE rate_cards
   SET fiscal_year = (
       SELECT CAST(strftime('%Y', MIN(e.effective_from)) AS INTEGER)
              + (CASE WHEN strftime('%m-%d', MIN(e.effective_from))
                           >= (SELECT value FROM app_settings
                                WHERE key = 'fiscal_year_start')
                      THEN 1 ELSE 0 END)
         FROM rate_card_entries e
        WHERE e.rate_card_id = rate_cards.id
   )
 WHERE fiscal_year IS NULL;

-- The date columns are deliberately left NULL. A NULL bound is unbounded, so
-- every card keeps pricing exactly what it priced before this migration ran.
-- Setting a real range is a deliberate act, card by card.
```

- [ ] **Step 5: Apply it and confirm the backup ran**

Run: `python apply_migrations.py`
Expected: a pre-migration backup lands in `app/data/backups/`, then the migration applies. A failed backup must abort the migration — do not continue past one.

- [ ] **Step 6: Prove nothing repriced**

Re-run the snapshot script from Step 1 into `after.json`, then:

```bash
diff before.json after.json && echo "IDENTICAL — nothing repriced"
```

Expected: no differences. If any line differs, stop: the migration has changed money and must be fixed before going further.

- [ ] **Step 7: Update the schema documentation**

Add the three columns to the `rate_cards` `CREATE TABLE` block in `docs/DATABASE_SCHEMA.md`, and add `fiscal_year` to the Money section's mermaid ER diagram. Update the sentence that says a standard card is "one per fiscal year" to note the year is now recorded rather than implied.

- [ ] **Step 8: Run both gates and commit**

```bash
python verify_docs.py
python health_check.py
git add app/core/migrations/0028_rate_card_effective_dates.sql \
        docs/DATABASE_SCHEMA.md health_check.py
git commit -m "Record fiscal year and effective dates on rate cards"
```

---

### Task 2: The card's dates decide

**Files:**
- Modify: `app/core/rates.py` — `_effective`, the card lookup in `resolve_rates`
- Test: `health_check.py`

**Interfaces:**
- Consumes: the columns from Task 1.
- Produces: `rates._card_window(entry_alias, card_alias) -> str` — the SQL predicate for the intersected window.

- [ ] **Step 1: Write the failing checks**

```python
            # The card range is authoritative, but it is expressed as one
            # window intersected with the entry's, not as a second filter —
            # two competing date tests is how a rate resolves to the wrong year.
            with app.app_context():
                from app.core import rates as core_rates
                from app.core.database import get_db

                db = get_db()
                card_id = db.execute(
                    "INSERT INTO rate_cards (name, company, scope, fiscal_year, "
                    "effective_from, effective_to) "
                    "VALUES ('Health Check FY26', 'HC', 'standard', 2026, "
                    "'2025-10-01', '2026-09-30') RETURNING id"
                ).fetchone()["id"]
                level_id = core_rates.levels()[0]["id"]
                # An entry deliberately wider than its card on both sides.
                db.execute(
                    "INSERT INTO rate_card_entries (rate_card_id, level_id, "
                    "bill_rate, cost_rate, effective_from, effective_to) "
                    "VALUES (?, ?, 500, 250, '2020-01-01', '2030-01-01')",
                    (card_id, level_id),
                )
                db.commit()

                inside = core_rates.entry_for(card_id, level_id, "2026-01-15")
                before = core_rates.entry_for(card_id, level_id, "2025-06-15")
                after = core_rates.entry_for(card_id, level_id, "2026-12-15")

            check("a date inside the card prices", inside is not None)
            check("a date before the card does not price, though the entry covers it",
                  before is None)
            check("a date after the card does not price, though the entry covers it",
                  after is None)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python health_check.py`
Expected: FAIL — `module 'app.core.rates' has no attribute 'entry_for'`.

- [ ] **Step 3: Write the intersected window**

In `app/core/rates.py`, beside the existing `_effective` helper:

```python
# Brian's decision: the card's dates decide. The danger in that is two
# competing date filters — the card's and the entry's — disagreeing, which is
# exactly how a rate resolves to the wrong fiscal year. So there is only ever
# one window: the later of the two starts, the earlier of the two ends. A NULL
# bound on either side is unbounded, which is what keeps every pre-migration
# card pricing exactly what it always did.
_FAR_FUTURE = "9999-12-31"


def _card_window(entry="e", card="c"):
    return (
        f"max({entry}.effective_from, "
        f"    coalesce({card}.effective_from, {entry}.effective_from)) <= ? "
        f"AND ? <= min(coalesce({entry}.effective_to, '{_FAR_FUTURE}'), "
        f"             coalesce({card}.effective_to, '{_FAR_FUTURE}'))"
    )


def entry_for(card_id, level_id, work_date):
    """The rate row in force on this card, for this level, on this date."""
    return get_db().execute(
        "SELECT e.bill_rate, e.cost_rate FROM rate_card_entries e "
        "JOIN rate_cards c ON c.id = e.rate_card_id "
        f"WHERE e.rate_card_id = ? AND e.level_id = ? AND {_card_window()} "
        "ORDER BY e.effective_from DESC LIMIT 1",
        (card_id, level_id, work_date, work_date),
    ).fetchone()
```

- [ ] **Step 4: Route both card lookups through it**

In `resolve_rates()`, replace the inline entry query in branch 2 (the card in force for this project or charge code):

```python
    if card_id:
        entry = entry_for(card_id, level_id, work_date)
        if entry and entry["bill_rate"] is not None:
            return _build(entry, resolved_erp, SOURCE_CARD, level_id, level_label)
```

Then find branch 3 — the default card for the person's company — and route its entry lookup through `entry_for()` in the same way, so both paths share one window. Read the whole function before editing: every branch that reads `rate_card_entries` must go through `entry_for`, or the card range will apply to some lookups and not others, which is the exact failure this design avoids.

- [ ] **Step 5: Run the checks and watch them pass**

Run: `python health_check.py`
Expected: PASS on all three, exit 0.

- [ ] **Step 6: Prove the untouched cards still price the same**

Re-run the snapshot from Task 1 Step 1 and diff against `before.json`. Cards with NULL dates must still be byte-identical. This is the regression that matters.

- [ ] **Step 7: Commit**

```bash
git add app/core/rates.py health_check.py
git commit -m "Let a rate card's effective range decide which entries apply"
```

---

### Task 3: Editing the year and the range

**Files:**
- Modify: `app/modules/rates/models.py` — `fiscal_year_for`, `dates_for_fiscal_year`
- Modify: `app/modules/rates/routes.py` — card create/update, entry validation
- Modify: `app/templates/modules/rates/index.html`, `card.html`
- Test: `health_check.py`

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces:
  - `models.fiscal_year_for(day) -> int`
  - `models.dates_for_fiscal_year(year) -> tuple[str, str]`

- [ ] **Step 1: Write the failing checks**

```python
            with app.app_context():
                from app.modules.rates import models as rates_models
                # fiscal_year_start is seeded 10-01, so FY2026 runs
                # 1 Oct 2025 to 30 Sep 2026.
                check("a date in October belongs to the next fiscal year",
                      rates_models.fiscal_year_for("2025-10-01") == 2026,
                      str(rates_models.fiscal_year_for("2025-10-01")))
                check("a date in September belongs to the current one",
                      rates_models.fiscal_year_for("2026-09-30") == 2026,
                      str(rates_models.fiscal_year_for("2026-09-30")))
                check("a fiscal year maps back to its dates",
                      rates_models.dates_for_fiscal_year(2026)
                      == ("2025-10-01", "2026-09-30"),
                      str(rates_models.dates_for_fiscal_year(2026)))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `python health_check.py`
Expected: FAIL — `module 'app.modules.rates.models' has no attribute 'fiscal_year_for'`.

- [ ] **Step 3: Derive the year from the dates and back again**

In `app/modules/rates/models.py`:

```python
def _fiscal_year_start():
    from app.core import config

    # MM-DD. Seeded 10-01; a firm that runs on the calendar year sets 01-01.
    return config.get_setting("fiscal_year_start", "10-01")


def fiscal_year_for(day):
    """The fiscal year a date falls in.

    With a start of 10-01, 1 October 2025 is the first day of FY2026 — the
    year is named for the calendar year it ends in, which is what everybody
    means by FY26.
    """
    year, month_day = int(day[:4]), day[5:10]
    return year + 1 if month_day >= _fiscal_year_start() else year


def dates_for_fiscal_year(year):
    from datetime import date, timedelta

    month, day = (int(part) for part in _fiscal_year_start().split("-"))
    start = date(year - 1, month, day) if (month, day) != (1, 1) else date(year, 1, 1)
    end = date(start.year + 1, start.month, start.day) - timedelta(days=1)
    return start.isoformat(), end.isoformat()
```

- [ ] **Step 4: Accept the fields on card create and update**

In `app/modules/rates/routes.py`, in the card create route (`POST /cards`), read the new fields and fill in whichever half was left blank:

```python
    fiscal_year = request.form.get("fiscal_year", type=int)
    effective_from = request.form.get("effective_from") or None
    effective_to = request.form.get("effective_to") or None

    # Fill either half and the other follows. A contradictory pair is refused
    # rather than silently resolved, because "which one did it believe" is not
    # a question you want to ask of a rate card.
    if fiscal_year and not effective_from and not effective_to:
        effective_from, effective_to = models.dates_for_fiscal_year(fiscal_year)
    elif effective_from and not fiscal_year:
        fiscal_year = models.fiscal_year_for(effective_from)
    elif fiscal_year and effective_from:
        implied = models.fiscal_year_for(effective_from)
        if implied != fiscal_year:
            flash(
                f"Not saved — {effective_from} falls in FY{implied}, "
                f"not FY{fiscal_year}. Fix one of the two.",
                "error",
            )
            return redirect(url_for("rates.index"))
```

Pass the three values through to the existing insert, and apply the same block to the card update path.

- [ ] **Step 5: Refuse an entry outside its card**

In the entry route (`POST /cards/<card_id>/entries`), before writing:

```python
    card = models.get_card(card_id)
    if card["effective_from"] and effective_from < card["effective_from"] or (
        card["effective_to"] and effective_to and effective_to > card["effective_to"]
    ):
        flash(
            f"Not saved — this card runs "
            f"{card['effective_from'] or 'from any date'} to "
            f"{card['effective_to'] or 'any date'}, so an entry outside that "
            "range would never price anything.",
            "error",
        )
        return redirect(url_for("rates.card", card_id=card_id))
```

- [ ] **Step 6: Show the year and range on the card screens**

In `app/templates/modules/rates/index.html`, add a Fiscal year column to the card list and an In force column rendering `effective_from` to `effective_to` with `| date_long`, showing "any date" for a NULL bound so an unbounded card reads as deliberate rather than as missing data.

In `card.html`, add the three inputs to the card's edit form, and default the entry date fields to the card's range.

- [ ] **Step 7: Run the checks and watch them pass**

Run: `python health_check.py`
Expected: PASS, exit 0.

- [ ] **Step 8: Confirm in the browser**

Create a card entering only FY2026 and confirm the dates fill in as 1 Oct 2025 – 30 Sep 2026. Create another entering only a start date and confirm the year fills in. Enter a contradictory pair and confirm the refusal names both values. Add an entry dated outside the card's range and confirm it is refused with the card's range stated.

- [ ] **Step 9: Update the money documentation and commit**

Update `docs/FINANCIAL_MODEL.md` §2 and `docs/TEMPORAL_MODEL.md` to state that a card's range decides, that entry windows are intersected with it, and that a NULL bound is unbounded.

```bash
python verify_docs.py
python health_check.py
git add app/modules/rates/ app/templates/modules/rates/ \
        docs/FINANCIAL_MODEL.md docs/TEMPORAL_MODEL.md health_check.py
git commit -m "Edit a rate card's fiscal year and the dates it is in force"
```

---

## Final Verification

- [ ] `python verify_docs.py` exits 0
- [ ] `python health_check.py` exits 0
- [ ] The rate snapshot diff is still empty for every card with NULL dates
- [ ] `/rates/` and a card detail page load with no 500s
- [ ] A budget line written before this work still shows the same four numbers
- [ ] `docs/BUILD_SEQUENCE.md` updated with what landed
