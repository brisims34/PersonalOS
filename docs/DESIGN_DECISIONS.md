# PersonalOS — Design Decisions

> **Looking for what needs your answer?** That is `DECISION_LOG.md` — the short
> list, ordered by when each stops being cheap to change. This file is the full
> record of every judgement call and its reasoning, referenced by ID from there. to Revisit

Judgement calls made while writing the specification that went a particular way for a stated reason, but could reasonably have gone another. **None of these were explicitly decided by Brian** — they are defaults chosen to keep the spec moving.

Each entry states what was chosen, what the alternative was, why, and **how to reverse it**. Reversal cost is the important column: some of these are a config change, some are a migration, and knowing which is which tells you how long you can leave them alone.

Status: `open` = still a default nobody has confirmed · `confirmed` = explicitly agreed · `superseded` = overtaken by a later decision.

---

## Financial

### F1 — Unpriced hours return `None`, never zero · `open`

**Chosen:** when rate resolution finds no match, return `None` and flag the row as unpriced in reconciliation.
**Alternative:** default to zero and let the total absorb it.
**Why:** a zero rate looks like a real rate. It silently understates cost and nothing about the resulting number announces that it is wrong. A visible gap is recoverable; a plausible wrong total is not.
**Reversal:** one branch in `resolve_rates()`. Trivial.

### F2 — Rates snapshot onto rows at insert · `open`

**Chosen:** `time_entries` and `budget_lines` store the resolved `bill_rate` / `cost_rate` / `revenue` / `cost` at write time. Editing a rate card later does **not** restate booked history or an approved budget.
**Alternative:** resolve rates live at query time, so every report reflects current rates.
**Why:** live resolution means a colleague correcting a rate card changes every historical report underneath you, including ones already sent to a partner. Restatement should be a deliberate, logged action.
**Reversal:** moderate. Requires a re-pricing job and dropping the stored columns from queries — but the columns can stay.

### F3 — All amounts USD, no conversion · `confirmed` *(Brian, this session)*

**Chosen:** single currency. `currency` columns retained but system-managed and never rendered.
**Reversal:** add an effective-dated `fx_rates` table resolved at transaction date. Nothing in the design blocks it.

### F4 — Job title is not level · `open — needs review before Phase 9`

**Chosen:** `job_title_map` resolves 13 directory titles to the 9 rate card levels. Rates attach to level.
**Four defaults needing confirmation:**

| Title | Defaulted to | Concern |
|---|---|---|
| `Assistant Manager` | `manager` | No rate card row exists; could be `senior_associate` |
| `Consultant` | `associate` | No rate card row exists |
| `Contractor` | `contractor` (off ladder) | **No rate at all** — needs a per-person override or every contractor hour prices unpriced |
| `Specialist MD` / `Specialist Dir` | their ladder level | May carry their own rates |

**Why it matters:** a wrong mapping propagates into every budget figure without announcing itself.
**Reversal:** edit `job_title_map` in Admin — but any budget already priced under the old mapping needs re-pricing.

### F5 — Fees seeded as non-compounding · `open — confirm before Phase 9`

**Chosen:** all three seeded fees use `basis = 'labor_revenue'`, so admin, tech and Kinergy each take a percentage of labour revenue only.
**Alternative:** `labor_plus_prior_fees`, so Technology and Kinergy compound on top of Admin.
**Why:** non-compounding is the simpler and more common reading, and Brian did not specify. On a $420,000 engagement the difference is roughly $1,000 — small proportionally, wrong absolutely, and it accumulates across every engagement.
**Reversal:** one field per fee row in Admin. **No migration.** But existing `project_fees` rows keep their snapshotted basis, so already-resolved projects would need re-resolving.

### F6 — ERP does not touch cost rates · `open — recommend keeping`

**Chosen:** ERP reduces the bill rate only. Cost rates come straight from the card.
**Why:** ERP is a realization concept on the billing side. Applying it to cost would inflate margin on every engagement — and the error would present as good news, which is the hardest kind to notice.
**Reversal:** trivial, but think hard first.

### F7 — `level_start_date` and `last_promoted_on` are columns, not derived · `open`

**Chosen:** both denormalised onto `people` and maintained on write, with `person_level_history` as the audit trail.
**Alternative:** derive the tenure clock from the current history row's `effective_from`.
**Why:** derivation is only correct when history is complete and every row correctly typed. On a 450-person spreadsheet import with no history at all, it is not. They are also kept **separate** from each other because a `correction` row changes the current level without being a promotion — conflating them would let a data fix reset someone's promotion clock, or make them read in a review as newly promoted.
**Reversal:** the columns can be dropped and derived later once history is trustworthy. Additive to remove.

### F8 — Tenure transitions are flagged, never automatic · `open`

**Chosen:** `person_levels.auto_promote_after_months` (36 Director, 60 Partner) surfaces a prompt; a human confirms.
**Alternative:** promote automatically on the anniversary.
**Why:** a level change reprices every subsequent hour, which should be a decision rather than a side effect of the calendar. But the failure mode of *not* prompting is worse — the person keeps billing at the junior rate for months and nothing announces it.
**Reversal:** trivial either direction.

---

## Resourcing

### R1 — Four utilization bands, not the PRD's three · `open`

**Chosen:** added a fourth "bench" band below 60% (blue), keeping green/amber/red above it.
**Alternative:** the PRD specified green / yellow / red only.
**Why:** someone at 30% is a *bench* problem — actionable, and precisely the person you are hunting for when staffing. Collapsing that into "green, good capacity" hides exactly what you opened the board to find.
**Reversal:** `app_settings.utilization_bands`. Config only.

### R2 — Availability is "first week at ≥50% free" · `open`

**Chosen:** `available_from` is the first horizon week where free capacity reaches half, not full.
**Alternative:** require a fully empty week.
**Why:** nobody rolls off cleanly. Waiting for 100% reports an availability date that in practice never arrives, so the field reads as permanently "unavailable."
**Reversal:** one threshold constant. Trivial.

### R3 — Smartsheet divergence preserves the local value · `open`

**Chosen:** when a locally-edited row also changes remotely, keep local, flag `is_diverged`, list for review.
**Alternative:** remote always wins.
**Why:** silently discarding a deliberate local edit is worse than showing a conflict. But it does mean divergences accumulate if nobody reviews them.
**Reversal:** change the branch in the sync upsert. Trivial.

---

## Data Model

### D1 — Hybrid relational model · `open`

**Chosen:** hard foreign keys for containment and money (`workstream.project_id`, `time_entry.charge_code_id`); `entity_links` for cross-cutting many-to-many.
**Alternative:** Rome's approach — route *every* relationship through `entity_links`.
**Why:** budget rollups and utilization math are the core of this application and need real joins with real integrity. Polymorphic links make those queries slow and unverifiable.
**Reversal:** expensive. This is the most structural decision in the schema.

### D2 — Dependencies are their own table, not a `raid_items` type · `open`

**Chosen:** `dependencies` table with direction, provider and needed-by date. `raid_items` covers risk / assumption / issue only. The RAID register unions them for display.
**Alternative:** a fourth `raid_type` with four mostly-null columns.
**Why:** dependencies need fields the other three do not, and workstream charters need dependency capture at Phase 3 — long before governance lands at Phase 14.
**Reversal:** moderate. Merging back means a migration and a wider `raid_items`.

### D3 — Notifications have no table · `open`

**Chosen:** the bell aggregates live queries; only dismissal state is stored in `alert_dismissals`.
**Alternative:** materialise notification rows.
**Why:** a stored copy drifts from the queries that generate it, and then you are debugging why the badge says 3 and the list shows 2.
**Reversal:** additive. A `notifications` table could be introduced without disturbing this.

### D4 — Manager-chain auto-create is the one exception to "never auto-create people" · `open`

**Chosen:** scraped email addresses go to `contact_candidates` for review; managers pulled to complete a reporting chain are created directly, tagged `import_source='gal_manager_chain'`.
**Alternative:** queue chain managers for review too.
**Why:** a reporting chain with a hole in it produces no org chart at all. The tag is what keeps the exception honest and reversible as a group.
**Reversal:** trivial — route them to `contact_candidates` instead.

---

## Notes & Templates

### N1 — Index rows are marked missing, never deleted · `open`

**Chosen:** a note whose file disappears is flagged, not removed from the index.
**Alternative:** delete the row.
**Why:** a network drive hiccup or an editor's atomic-save window would otherwise destroy backlinks permanently.
**Reversal:** trivial, but consider the failure mode first.

### N2 — Save-as-template makes note inclusion opt-in per file · `open`

**Chosen:** exporting a project as a template asks which notes to include, defaulting to none.
**Alternative:** include the whole `notes/` tree automatically.
**Why:** generalisation strips client names from *fields*. It cannot reliably strip them from prose, and a template pack is a thing you might share.
**Reversal:** change the default. But read the note bodies first.

### N3 — Working-day math skips weekends, not holidays · `open`

**Chosen:** `day_basis: working` skips Saturday and Sunday only.
**Alternative:** model a holiday calendar.
**Why:** modelling holidays badly is worse than a documented gap — a half-correct calendar produces dates you trust and shouldn't.
**Reversal:** additive. A `holidays` table consulted by the date resolver.

### N4 — Managed blocks let the app write into user files · `open`

**Chosen:** `<!-- personalos:team -->` regions in notes are refreshed from live data; everything outside them is never touched.
**Alternative:** keep notes purely hand-authored and put live data only on the record page.
**Why:** a workstream charter listing a team that was accurate two weeks ago is actively misleading to someone onboarding.
**Risk to watch:** this is the only place PersonalOS writes into a file the user also edits. If the marker-boundary logic is ever wrong, it eats user prose.
**Reversal:** remove the markers from a note and it stops updating — per-note opt-out is built in.

---

## Interface

### I1 — Server-rendered SVG Gantt, no charting library · `open`

**Chosen:** hand-rolled SVG for the Portfolio Timeline.
**Alternative:** vendor something like frappe-gantt.
**Why:** the RAG, budget and resource-cliff overlays are the entire point of the view, and a generic library's interaction model would have to be fought to add them.
**Reversal:** moderate — a rewrite of one view.

### I2 — Bootstrap vendored, not CDN · `open`

**Chosen:** ship Bootstrap 5.3 in `static/vendor/`.
**Alternative:** CDN, as Rome does.
**Why:** offline reliability behind a corporate proxy. A CDN failure would make the app look broken rather than degraded.
**Reversal:** trivial.

### I3 — Morning Report absorbed into the Staffing Board · `confirmed` *(PRD overrides)*

**Chosen:** the board's left rail is the condensed Morning Report; a full-detail page sits behind it, sharing one query.
**Note:** the Marine Corps disposition detail — rotations, drill-through, roll-ups — lives on the detail page, not the rail.

### I4 — No state encoded by colour alone · `open — recommend keeping`

**Chosen:** every RAG chip, capacity bar, coverage bar and budget flag carries a label or numeral alongside its colour.
**Why:** the application is unusually dense in red/amber/green, and that encoding is unreadable for roughly one in twelve men.
**Reversal:** possible, not advisable.

---

## AI

### A1 — Cloud adapters built but dormant · `confirmed` *(Brian, this session)*

Anthropic and Google adapters exist and pass interface tests; every feature seeds `max_boundary='local'` and disabled.

### A2 — Embeddings hard-pinned local in code · `open`

**Chosen:** `embed.*` rejects a non-local provider regardless of configuration.
**Alternative:** default local, allow override like every other feature.
**Why:** embedding the vault sends *every note in it*, not a selected excerpt. That should not be reachable by a settings change.
**Reversal:** delete the check in `policy.py`. Consider carefully.

### A3 — Fallback never crosses a boundary · `open — recommend keeping`

**Chosen:** a dead local provider fails the job visibly rather than escalating to cloud.
**Why:** silent escalation is the one failure mode that turns a confidentiality guarantee into a breach without anyone noticing.

### A4 — No vendor SDKs · `open`

**Chosen:** Claude and Gemini adapters use plain `requests`.
**Why:** ~40 lines each versus two dependency trees and their version churn.
**Reversal:** trivial, if an SDK later offers something worth having.

### A5 — Single AI worker thread · `open`

**Chosen:** one worker by default; configurable higher.
**Why:** CPU inference serialises anyway; concurrency would thrash a 16GB machine. Cloud-only workloads are the case where raising it helps.
**Reversal:** config only.

---

## Temporal

### T1 — `as_of` is a parameter throughout `core/` · `open — recommend keeping`

**Chosen:** no function in `app/core/` calls `date.today()`; the evaluation date is passed in and routes supply the default.
**Alternative:** read the clock where it is needed, as most applications do.
**Why:** it makes forward views ("what will be overdue in March?", "which promotions fall in FY27?") the same code with a different argument, rather than a feature nobody can afford to build. It also makes backdated timesheet imports price correctly by construction.
**Cost:** every temporal signature carries an extra parameter.
**Reversal:** effectively none — this cannot be retrofitted cheaply across thirty modules, which is precisely why it is a rule from Phase 0 rather than a later improvement.

### T2 — Unified temporal evaluator deferred · `open`

**Chosen:** each time-based signal ships as its own query in its own module for now; the consolidated `temporal_rules` engine is documented but not built.
**Why:** seventeen signals are catalogued in `TEMPORAL_MODEL.md` §2, but only about four exist by Phase 4. Building the engine first would be speculative.
**Trigger to revisit:** the third time a new signal requires copying an existing query and adjusting the comparison — roughly Phase 14.
**Reversal:** consolidation is a refactor of known scope *if* rules 1–7 in `TEMPORAL_MODEL.md` §5 are followed. If they are not, it becomes a rewrite.

---

## Sequencing

### S1 — AI at Phases 20–21 · `open`

**Chosen:** last, because every AI feature attaches to a module built earlier.
**Candidate to pull forward:** semantic search needs only Phase 3.

### S2 — Template Library at Phase 16 · `open`

**Chosen:** late, because one pack import writes across eight tables.
**Candidate to pull forward:** tasks + workstreams + note scaffold could ship right after Phase 8.

### S3 — Quick Steps last, at Phase 23 · `confirmed` *(Brian — "nice to have for later")*

### S4 — Activity Log pulled forward from Phase 22 to Phase 0 · `open — recommend keeping`

**Chosen:** build the read-only log viewer in the foundation phase.
**Alternative:** leave it at Phase 22 with the rest of Admin.
**Why:** `activity_log` exists from migration `0001`, and rule 13 says every mutation writes to it. Through Phases 1–4 that rule would be unverifiable — you would be writing rows nobody can read. It is also the only way to have two modules in the shell, which is what makes the module enable/disable behaviour testable at Phase 0 rather than asserted.
**Cost of reversal:** none. Phase 22 keeps the Admin surface around it.

---

## Foundation *(decided while building Phase 0)*

### B1 — Maintenance scripts at the repository root, not in `scripts/` · `open`

**Chosen:** `python health_check.py` from the root.
**Alternative:** `python scripts/health_check.py`.
**Why:** each script is one self-contained file, `verify_docs.py` already lived at the root, and running from the root means no `sys.path` juggling. The immediate trigger was that the WSL sandbox masks a top-level `scripts` path, but the arrangement stands on its own for eight files.
**Cost of reversal:** `git mv` plus a `sed` over the docs. Ten minutes.

### B2 — Money and hours round half-up through `Decimal` · `open — recommend keeping`

**Chosen:** `Decimal(str(value)).quantize(…, ROUND_HALF_UP)` in every numeric formatter.
**Alternative:** plain float formatting, which is what `f"{x:,.2f}"` gives you.
**Why:** float formatting rounds 1,234.55 down to 1,234.5 and $2.675 down to $2.67, because neither is exactly representable in binary. On a figure that gets multiplied by an hourly rate and summed across a work breakdown structure, that is a real variance, and it is the kind an accountant notices immediately. Caught by the Phase 0 checks.
**Cost of reversal:** trivial, but do not.

### B3 — Content Security Policy forbids inline script · `open`

**Chosen:** `script-src 'self'`, no nonces, no inline `<script>` anywhere. Inline *styles* stay permitted because capacity and coverage bars need a computed width.
**Alternative:** the usual `'unsafe-inline'`.
**Why:** it makes "no client-side templating of business data" (`UI_DESIGN_SYSTEM.md` §11) enforceable by the browser rather than by discipline. The theme is written into the `<html>` element server-side, which removes the one inline script a dark-first app normally needs and eliminates the flash of the wrong theme at the same time.
**Cost of reversal:** one line, if some later feature genuinely needs it.

### B4 — Same-origin check on every state change · `open`

**Chosen:** reject any non-GET whose `Origin` or `Referer` is not this host.
**Alternative:** nothing, or full CSRF tokens.
**Why:** the app has no login because it never listens off localhost — but any page open in the browser can still POST to `127.0.0.1:5000`. The header comparison is about fifteen lines and no dependency; CSRF tokens would mean a form-handling library and a token in every template.
**Limitation, stated plainly:** a request with no `Origin` and no `Referer` is allowed through, because the maintenance scripts and `curl` send neither. That is a deliberate trade, not an oversight.

### B6 — Rate cards are entered in the UI, never seeded in a migration · `open — recommend keeping`

**Chosen:** `0002` seeds the ten levels and the thirteen title mappings — structure only. Rate *values* are typed into `/rates`.
**Alternative:** ship a starter card with real numbers.
**Why:** two reasons, and either alone would settle it. Rates are firm-confidential and a migration file is committed to git. And they change every fiscal year, which is a data event, not a schema one — seeding them would mean a migration every October.
**Cost of reversal:** none.

### B7 — Migration files are extracted from `DATABASE_SCHEMA.md`, not hand-written · `open`

**Chosen:** every `CREATE TABLE` in `app/core/migrations/` is the schema document's DDL verbatim, and `verify_docs.py` check 9 fails the build if they diverge.
**Alternative:** write the migration, then update the doc.
**Why:** rule 5 says a schema change must update the documentation. Writing them twice means they drift, and the drift is silent. Now the document is the source and the divergence is mechanical to detect — 26 table definitions compared, 0 drifted.
**Cost of reversal:** delete one check.

### B8 — The workstream charter is generated on demand, not on create · `open`

**Chosen:** the charter template and its five managed blocks are built and verified; generating one is an action, not a side effect of creating a workstream.
**Alternative:** write the file automatically at workstream creation, as `BUILD_SEQUENCE.md` Phase 3 specifies.
**Why:** honestly, sequencing rather than principle — it let the managed-block engine be verified on its own before being wired into a write path that touches the filesystem. Worth closing.
**Cost of reversal:** a few lines in `projects.add_workstream`.

### B10 — `notes_fts` is an ordinary FTS5 table, not contentless · `superseded` *(the spec was wrong)*

**Originally specified:** a contentless table (`content=''`), so note bodies were never duplicated into SQLite.
**Chosen instead:** an ordinary FTS5 table.
**Why:** the original does not work. SQLite refuses `DELETE` on a contentless FTS5 table, and re-indexing an edited note requires exactly that — it is the indexer's commonest operation. Deleting from a contentless table means supplying the original column values, which is the one thing a contentless table does not keep. `contentless_delete=1` exists from SQLite 3.43 but would pin the app to a newer SQLite than several Python builds ship. Found by running the indexer against a real edit, not by review.
**Cost:** a second copy of the note text inside the FTS index — megabytes for a personal vault. The file on disk is still the truth and the index is still rebuildable by rescanning, so the governing rule is intact.

### B9 — `import_batches` moved from migration 0011 to 0007 · `open — recommend keeping`

**Chosen:** the import ledger is its own migration at Phase 1, and everything from calendar onward shifted up one number (`0007_calendar` → `0008_calendar`, and so on to `0024_quicksteps`).
**Alternative:** leave it in `0011_financials` where the schema document originally filed it, and have the contact importer infer "already loaded" from the activity log.
**Why:** `import_batches` is not a financial concept. It serves the contact seed at Phase 1, the timesheet export at Phase 9 and template packs at Phase 16, and Phase 1 of `BUILD_SEQUENCE.md` always said the seed importer writes one. Inferring a prior load from an activity-log `LIKE` is guesswork; `UNIQUE (batch_type, file_sha256)` is a guarantee. The renumber was safe to do because none of the shifted migrations exist yet — no database has ever applied them — and `verify_docs.py` check 4 proves the ownership table, the section headers and the build plan still agree.
**Cost of reversal:** high once any 0008+ migration ships, because a database will have recorded those version numbers. Effectively a one-way door from Phase 5 onward.

### B11 — `entity_links` UNIQUE widened to include `link_label`, migration inserted at 0008 · `open — recommend keeping`

**Chosen:** `entity_links` from §0001 was `UNIQUE (source_type, source_id, target_type, target_id)` — one link per pair, full stop. The Projects → Team tab used `link_label` as a free-text role, so re-linking the same person under a second role hit `INSERT OR IGNORE` and silently did nothing; the bug was invisible because the route never checked `link.link()`'s return value and always flashed success. `0008_team_roles.sql` rebuilds the table with `link_label` folded into the constraint, so one person can hold several distinct roles on the same project, and seeds a `team_role` vocabulary so the field is a picker like every other categorical field, not free text. Everything from `0008_calendar.sql` onward shifted up one number again, to `0009` through `0025`.
**Alternative:** append the fix as `0025_team_roles.sql`, after everything already documented, to avoid renumbering. Rejected: migration numbers must stay strictly increasing in the order they are actually applied, and version 25 would permanently strand versions 8–24 the moment this migration runs against any database — Phase 5 onward would never re-apply once written, because `pending_migrations` only picks up versions greater than the current one.
**Why:** the same reasoning as B9 applies, and the same proof holds — none of `0008`–`0024` exist as files, so no database has ever recorded those version numbers, and `verify_docs.py` check 4 confirms the ownership table, section headers and `BUILD_SEQUENCE.md` still agree after the shift.
**Cost of reversal:** same shape as B9 — cheap now, a one-way door the moment any migration numbered 0008 or higher actually ships against a real database.

### B5 — Bootstrap fetched by a script rather than committed by hand · `open`

**Chosen:** `vendor_assets.py`, with `--from <folder>` as an equal path for a machine whose proxy blocks jsdelivr.
**Alternative:** commit the files, or use a CDN.
**Why:** a CDN breaks offline and behind a filtering proxy, which is the normal case here. Committing them is fine — and once fetched they *should* be committed, so the Windows copy gets them through git — but they could not be obtained from the environment this phase was built in. `personalos.css` therefore styles the whole shell unaided, and the icon font degrades to letter placeholders rather than breaking the layout.
**Cost of reversal:** none; the files are ordinary static assets either way.

---

## Modelling Restraint — things deliberately *not* built

| Not built | Why | If it becomes necessary |
|---|---|---|
| Validation checks as a table | A markdown checklist in the workstream charter does the job; checks vary too much by engagement type to model, and a table you can edit in ten seconds gets maintained where a form does not | Promote to tasks with a `validation` type |
| Structured fields for building access | `access_notes` and `logistics_notes` as free text — badge rules, escort policy and parking refuse to fit a schema | Add columns if a pattern emerges across many sites |
| `tasks.is_major` flag | The charter's task block can rank by priority and due date | One column, additive |
| Holiday calendar | See N3 | `holidays` table consulted by the date resolver |
| Multi-user, auth, roles | Single user by design | Out of scope entirely |
| Vector database | numpy brute force is sub-100ms for a personal vault | `sqlite-vec`, drop-in |
| Smartsheet write-back | Read-only keeps the blast radius at zero | Would need its own boundary review |
