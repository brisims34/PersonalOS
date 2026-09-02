# PersonalOS — Decision Log

**Purpose.** `DESIGN_DECISIONS.md` records *every* judgement call and why it was made — 39 entries, and it is long on purpose. This file is the short version: **only the decisions that are yours to make, ordered by when they stop being cheap to change.**

Nothing here is blocking today. Every item has a working default already in the code, so the build can continue while you think. What matters is that a few of these get expensive once data exists on top of them.

**How to use it.** Write your answer in the *Decision* line. Then move the matching entry in `DESIGN_DECISIONS.md` from `open` to `confirmed` (or change the code and mark it `superseded`). Leaving something as `open` is a legitimate answer — it means "the default is fine for now."

**Status:** Milestone 1 (Phases 0–4) built and statically verified. Nothing committed to git. The application has never been run under Flask — see §7.

---

## 1. State of play — what you are deciding on top of

| | |
|---|---|
| **Documentation** | 16 documents, 8,400 lines. 86 tables across 23 planned migrations. Verified: all DDL executes, 142 foreign keys resolve, 67 capabilities traceable, 0 broken references. |
| **Milestone 1 code** | ~12,000 lines. 11 modules live, 6 migrations, 28 tables, 44 templates. |
| **Verified offline** | Migration chain 0001–0006 applies clean with no FK violations. The `FINANCIAL_MODEL.md` §2 promotion example reproduces **exactly**. Tenure flagging honours `as_of`. Promotion vs correction clock semantics. Managed blocks preserve prose byte-for-byte. Path confinement and folder rename-with-move. All 450 rows of `AASppl.xlsx` parse. 44 templates compile; every `url_for` endpoint exists. No interpolated SQL in `app/`. |
| **Not verified** | **The application has never started.** No page has been served, no interaction exercised. This sandbox has no network, so Flask could not be installed. |
| **Next** | Double-click `Install to Windows.bat`, then `Start PersonalOS.bat`. First run takes a few minutes. Then import `AASppl.xlsx` from Contacts. |
| **Git** | Zero commits. Everything is untracked working tree. |

---

## 2. Before Phase 1 — People, levels and rates

Phase 1 imports 450 people and stands up `resolve_rates()`. These four shape every budget figure produced afterwards.

### 2.1 The three job titles with no rate card row · `DESIGN_DECISIONS.md` F4

`AASppl.xlsx` contains 13 job titles. Nine map cleanly to the rate ladder. These do not:

| Title | Defaulted to | The concern |
|---|---|---|
| `Assistant Manager` | `manager` | Could equally be `senior_associate`. One band difference on every hour they book. |
| `Consultant` | `associate` | No card row exists. |
| `Contractor` | `contractor`, off ladder | **No rate at all.** Every contractor hour prices as *unpriced* until you add a per-person override. |
| `Specialist MD` / `Specialist Dir` | their ladder level | They may carry their own rates. |

**Why it needs you:** a wrong mapping does not announce itself. It produces a plausible number that is quietly wrong, and it propagates into budgets, burn, EAC and margin.

**Reversal cost:** editing `job_title_map` in Admin is instant — but anything already priced under the old mapping needs re-pricing.

**Decision:**

### 2.2 Should `Contractor` price as unpriced, or as something? · F4

The deliberate choice is that an unpriced person returns `None`, **never zero** (F1), and gets flagged. A contractor with no override therefore shows up as a gap rather than as free labour.

**The alternative** is a default contractor rate, which is convenient and hides the gap.

**Decision:**

### 2.3 Does ERP touch cost rates? · F6

Currently **no** — ERP reduces the bill rate only; cost comes straight off the card. Applying ERP to cost would inflate margin on every engagement, and that error presents as good news, which is the hardest kind to catch.

I recommend keeping this. Flagged only because it is an assumption I made, not something you said.

**Decision:**

### 2.4 On re-import, does the spreadsheet or the GAL win? · new

Re-importing a refreshed `AASppl.xlsx` over records the GAL has since enriched: which source wins per field?

**Default I would build:** the GAL wins for directory attributes (title, department, phones, city, manager), the spreadsheet wins for nothing, and any locally hand-edited field is flagged as divergent rather than overwritten — the same rule already used for Smartsheet (R3).

**Decision:**

---

## 3. Before Phase 9 — Financials

### 3.1 Do the fees compound? · F5

Admin 12%, Technology 3%, Kinergy 8% sell side / 5% buy side. All three are currently seeded as a percentage of **labour revenue only**.

The alternative is that Technology and Kinergy compound on top of Admin. On a $420,000 engagement the difference is roughly $1,000 — small proportionally, wrong absolutely, and it recurs on every engagement.

**Reversal cost:** one field per fee row in Admin, no migration. But existing `project_fees` rows keep their snapshotted basis, so already-resolved projects need re-resolving.

**Decision:**

### 3.2 Do the fees apply to expenses, or labour only? · new

Related but separate from compounding, and I did not ask at the time. Currently: labour only. Expenses pass through unfeed.

**Decision:**

### 3.3 Are rates snapshotted onto rows at insert? · F2

Currently **yes** — a time entry and a budget line carry the rate that was resolved when the row was written, not a live lookup. This is what makes a historical report reproduce the same number twice.

The trade: correcting a rate card retroactively does not fix rows already written. That needs a deliberate re-price action.

**Decision:**

---

## 4. Expensive to reverse — worth the most thought

Everything above is a data edit. These four are structural.

| | Decision in force | Why it is expensive later | Ref |
|---|---|---|---|
| **`as_of` is a parameter everywhere** | No function in `app/core/` calls `date.today()`; the evaluation date is passed in | This is what makes "what will be overdue in March?" and backdated imports possible at all. It cannot be retrofitted cheaply — it would mean touching every core function. | T1 |
| **Hybrid relational model** | Hard foreign keys for containment and money; `entity_links` only for cross-cutting many-to-many | Getting this backwards means either broken referential integrity on budget rollups, or a polymorphic join where a real key belongs. Rewriting the direction later is a migration plus a query sweep. | D1 |
| **Charge code is the reconciliation key** | `time_entries.charge_code_id` is the foreign key; project and workstream are *derived* | Everything financial rolls up through this. Changing the grain later invalidates every budget-to-actual view. | — |
| **Files are the truth for notes** | The database is a rebuildable index; delete it and rescan | The alternative — content in SQLite — is a one-way door. Once notes only exist in the database, Obsidian and VS Code stop working on them. | N1 |

I recommend keeping all four. Listed because "expensive to reverse" is exactly the category that deserves your attention before Phase 1 rather than after Phase 12.

**Decision:**

---

## 5. Phase 0 deviations — things I decided while building

Each is small, each is reversible, none needs an answer today.

| | What I did | Instead of | Reversal | Ref |
|---|---|---|---|---|
| Script location | Maintenance scripts at the repo root: `python health_check.py` | `scripts/health_check.py` | `git mv` plus a sed. Ten minutes. | B1 |
| Activity Log | Built at Phase 0 | Phase 22 with the rest of Admin | None — Phase 22 keeps the Admin surface | S4 |
| Rounding | `Decimal` with `ROUND_HALF_UP` in every numeric formatter | Plain float formatting | Trivial, but don't — float gives $2.67 for $2.675 | B2 |
| Security policy | CSP forbids inline script entirely | The usual `'unsafe-inline'` | One line | B3 |
| Request guard | Same-origin header check on writes | CSRF tokens, or nothing | Stated limitation: a request with no `Origin` **and** no `Referer` passes, because the maintenance scripts send neither | B4 |
| Bootstrap | Fetched by `vendor_assets.py`, with `--from` for a blocked proxy | Committed by hand, or a CDN | None. Once fetched it should be committed | B5 |

---

## 6. Scope and sequencing

### 6.1 Is Milestone 1 still "through Phase 4"? · new

The agreed stopping point was Phase 4 — People, Projects, Charge Codes, Notes Vault, Tasks, Command Center v1 — then review. Phases 1–4 are roughly four times the size of Phase 0.

**Worth considering:** stopping after **Phase 1** instead. People, levels and rates is the phase where a wrong assumption is most expensive, it is self-contained enough to be genuinely useful on its own, and reviewing `resolve_rates()` against a real promotion is a two-minute check that protects every later phase.

**Decision:**

### 6.2 When do we start committing to git? · new

Nothing is committed. That is fine for a documentation pass; it is less fine now that there is code, because there is no way back to a known-good state.

**Recommendation:** commit Phase 0 as one commit before Phase 1 starts, so there is a floor to return to.

**Decision:**

### 6.3 Should semantic search come forward? · S1

AI is planned for Phases 20–21. Semantic vault search needs only Phase 3, and it is the AI feature most likely to earn its keep on CPU-only hardware — embeddings are cheap and small models are genuinely good at retrieval. Long-form drafting is the weak one.

**Decision:**

---

## 7. Still unverified, and how that gets closed

| Claim | How it gets proven |
|---|---|
| The app starts and serves pages | `Start PersonalOS.bat`, then `health_check.py` — 38 checks, currently 27 pass, all 11 gaps trace to Flask being absent here |
| `Ctrl-K`, `?`, `g`+`c`, theme toggle, focus rings | The unticked items in `BUILD_SEQUENCE.md` Phase 0 |
| `onnxruntime-genai` installs without a compiler; HuggingFace reachability | `preflight.py` on the Windows machine, before Phase 20. This rests on an environment I could not inspect — it is informed expectation, not verified fact |
| Bootstrap is obtainable at all | `vendor_assets.py`, or `--from` a folder filled from another machine |

---

## 8. Questions I have for you

Not decisions — things I do not know that would change what I build.

1. **Is `AASppl.xlsx` the whole population you staff from, or a subset?** 450 rows, all department `AAS`. If engagements routinely pull people from outside it, the GAL manager-chain walk matters much more than I have assumed.
2. **Do you book time yourself against multiple charge codes in a normal week?** It determines whether "My Active Charge Codes" is a convenience card or the most-used control in the app.
3. **Who else sees this?** Everything is specified single-user. If a counselee or an engagement manager ever needs read access, that is the one assumption in the whole design that is genuinely expensive to unwind.
4. **Is there an existing rate card file** you can drop in, or do rate cards get typed in by hand at Phase 1?
