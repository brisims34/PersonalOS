# PersonalOS — Application Specification

**Version:** 1.0 · **Status:** Approved for build · **Owner:** Brian Sims

---

## 1. Purpose & Operating Model

PersonalOS is a local-first, single-user application for running an entire professional operating surface: client engagements, internal projects, innovation and development initiatives, and training — all modelled as **projects** with **workstreams**, **charge codes**, budgets, people, stakeholders and notes.

The organising goal is **proactive management of the whole landscape of stakeholders, projects and people.** That framing matters, because it makes PersonalOS an early-warning system rather than a task tracker with reports attached. Four views carry that weight:

| View | Question it answers |
|---|---|
| **Command Center** | What needs me today? |
| **Portfolio Timeline** | Are my projects on time, on budget, and about to lose people? |
| **Master Staffing Board** | Who is available, who is over-committed, and which projects are under-covered? |
| **Template Library** | How do I start a known engagement type fully scaffolded instead of empty? |

Everything else in the application exists to keep those four views true.

### Operating principles of the system

- **Local-first.** The application binds to `127.0.0.1`, stores everything in SQLite and the local filesystem, and runs without a network. Outbound calls exist only where explicitly specified (Smartsheet, optional AI providers, optional model downloads) and each is individually disableable.
- **Files where files belong.** Notes are markdown on disk. Templates are folders on disk. The database indexes them; it does not imprison them.
- **One unit of work.** Client, internal, innovation and training initiatives are all `projects`. There is no second hierarchy to keep in sync.
- **Computed, not entered.** Utilization, coverage, burn, margin, resource cliffs, availability dates and schedule variance are derived from source data. Nothing important is a field somebody has to remember to update.

---

## 2. Key Principles

*A living section. These govern every design decision and every phase's acceptance criteria. Each is written to be testable, because a principle you cannot fail is decoration.*

The four words that anchor everything: **consistency, clarity, efficiency, actionability.**

### Actionability

**P1 — Every screen answers "what do I do next."** No dead-end views. Every list has a primary action; every record has a next-step affordance.
*Violated when:* you can open a page and not name its primary action without hunting.

**P2 — The app says what it did and what follows.** Never a bare "Saved." Confirmations name the specific effect and link onward: *"Imported 47 time entries across 3 charge codes — 2 unmatched codes need review →"*
*Violated when:* a confirmation could be pasted onto a different feature and still read correctly.

**P3 — Numbers are traceable, never black boxes.** Click any computed figure — burn %, coverage %, utilization, EAC, margin — and see the rows behind it.
*Rationale:* this is the difference between a number you cite and a number you re-derive in Excel first. It is also the principle most often skipped, because it costs real effort per figure.

### Clarity

**P4 — Multi-step processes are wizards with visible progress and a dry run.** Template import, timesheet reconciliation, Smartsheet mapping, model install, Assign Team: stage N of M, an explicit statement of what will be created or changed, and a preview before commit.
*Violated by:* any silent bulk mutation.

**P5 — Nothing destructive without preview and a way back.** Archive over delete. Dry-run before commit. An activity log that makes any change reconstructable.

**P6 — Progressive disclosure.** Dense where you are working, summarised everywhere else.

### Consistency

**P7 — One object grammar, learned once.** Every entity page has the same shape: identity header with status chips → action bar → tabbed body → links/backlinks panel → activity trail.
*Violated when:* a new module needs a bespoke layout — which is a signal to reshape the module, not to grant an exception.

**P8 — Never re-ask what the app knows.** Creating a task from a project pre-fills project, workstream, charge code and rate card. Assigning from a staffing requirement pre-fills role, level and dates.
*Test:* count keystrokes for the ten most common flows and drive each toward the minimum.

**P9 — The vocabulary is Public Accounting, not software.** Engagement, charge code, WIP, realization, utilization, counselee, workpaper, RAG, EAC — never "entity," "record," "object." Numbers follow accounting convention: thousands separators, parentheses for negatives, consistent decimals, right-aligned numerics, unambiguous dates. **All money is USD** — no multi-currency handling anywhere.
*Test:* a colleague navigates it without a glossary.

### Efficiency

**P10 — Keyboard-first, mouse-optional.** A global command palette (`Ctrl-K`) that navigates, creates and searches across every entity. Consistent in-context keys (`n` new, `e` edit, `/` search, `g`+letter to go). A `?` overlay listing every binding.
*Violated by:* any action reachable only by mouse.

**P11 — Drag and drop where the mental model is spatial**, and **always as an accelerator, never the only path.** Every drag has a keyboard and menu equivalent, because drag-only interactions are unusable with assistive technology and awkward on a trackpad.

**P12 — Quick Steps: one click, many actions.** Named, saved action bundles in the Outlook sense, shipping with sensible defaults. *Later tier:* record what you just did and save it as a Quick Step.

**P13 — Speed is a feature.** Local SQLite should render pages well under 200ms; anything slower goes async with visible progress. No spinner without a cancel.

**Implementation note:** the command palette, hotkey layer and drag-and-drop all fit inside the no-build-step constraint. HTML5 drag-and-drop is native; a palette is roughly 200 lines of vanilla JS. P10 and P11 are foundational and built in Phase 0 — retrofitting a keyboard layer across thirty modules costs far more than building the shell with one. Only P12's *recorded* automations are deferred.

---

## 3. Scope & Non-Goals

### In scope

Client engagements · internal projects · innovation initiatives · training programmes · workstreams · charge codes · tasks · recurring reminders · meetings · email intake · contacts and org chart · markdown notes vault · project templates · time and materials budgets · timesheet actuals · rate cards · resource assignments and capacity · staffing coverage · skills · pipeline · RAID and decisions · stakeholder management · change control · status reporting · performance management · training compliance · innovation network · local and optional cloud AI assistance.

### Explicit non-goals

- **Multi-user.** Single user, single machine. No authentication, no roles, no concurrent write handling.
- **Being the system of record for the firm.** PersonalOS mirrors and reasons over firm data; it never becomes its authoritative source. It does not write back to Smartsheet, does not send email, and does not modify meetings it did not create.
- **Replacing Excel.** Where a spreadsheet is genuinely the better tool, PersonalOS imports from and exports to it rather than reimplementing it.
- **Cloud hosting, containers, build steps, SPA frameworks.** See §4.
- **Storing sensitive HR data.** No compensation, formal ratings, or disciplinary records. Performance items hold goals, wins, feedback, coaching notes and evidence only.

---

## 4. Stack & Runtime

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Web framework | Flask 3.x |
| Templates | Jinja2, autoescaping on |
| Database | SQLite via stdlib `sqlite3` — no ORM |
| CSS | Bootstrap 5.3, vendored locally, dark-first via `data-bs-theme` |
| JavaScript | Vanilla only. No framework, no bundler, no build step |
| Storage | Local filesystem |

**Required dependencies:** `Flask`, `Jinja2`, `Werkzeug`, `markdown`, `nh3`, `PyYAML`, `python-dateutil`, `openpyxl`, `requests`.
**Windows-only:** `pywin32` (Outlook). The app runs without it; Outlook features disable gracefully.
**Optional AI:** `onnxruntime-genai`, `fastembed`, `numpy`. All pre-built wheels, no compiler required. The Claude and Gemini adapters add no dependencies — both are plain REST via `requests`.

### Runtime host

PersonalOS runs on **Windows-native Python**, because Outlook COM automation is only reachable from a Windows process. Development happens in the WSL git repository; the tree is synced to a Windows path (`C:\Users\bsims\PersonalOS`) and run there.

> **Do not run SQLite over `\\wsl$\`.** The 9p share does not honour file locking reliably and will corrupt the database. `app/data/` is gitignored and lives only on the Windows side.

### Layout

```
PersonalOS/
├── run.py                      # entry point; opens 127.0.0.1:5000
├── personalos_ai.py            # optional AI model server (separate process)
├── requirements.txt
├── Start PersonalOS.bat        # double-click launcher
│
│   # Maintenance scripts, at the root so each is `python <name>.py`
├── health_check.py             # DB, tables, config, blueprints, bindings
├── apply_migrations.py         # backup → migrate → verify
├── verify_docs.py              # the schema doc's DDL still executes
├── vendor_assets.py            # fetch or place Bootstrap into static/vendor/
├── reindex_notes.py            # Phase 3
├── reindex_templates.py        # Phase 16
├── sync_smartsheet.py          # Phase 10
├── preflight.py                # Phase 20 — AI backend capability probe
├── app/
│   ├── __init__.py             # create_app()
│   ├── core/                   # database, backup, config, registry, links,
│   │                           # activity, rates, health, resourcing, paths,
│   │                           # markdown, notes_index, ai/
│   ├── integrations/           # outlook/, smartsheet/, timesheet/
│   ├── modules/<name>/         # routes.py + models.py per module
│   ├── templates/              # Jinja2 — base, partials, modules/<name>/
│   ├── static/                 # css/, js/, vendor/
│   └── data/                   # personalos.db, backups/, inbox/, models/,
│                               # secrets.json  — ALL GITIGNORED
├── projects/                   # notes vault root (markdown)
├── template_library/           # project template packs
└── docs/                       # this spec and companions
```

---

## 5. Information Architecture

Vocabulary and grouping follow §2/P9 — a Public Accountant should recognise every label.

| Group | Modules |
|---|---|
| **Command** | Command Center · Tasks · Calendar |
| **Work** | Portfolios · Projects & Workstreams · Portfolio Timeline · Milestones · Template Library |
| **Governance** | RAID & Decisions · Stakeholders · Change Control · Status Reports |
| **Money** | Charge Codes · Budgets & Rates · Time Import · Financial Analysis |
| **Resources** | Staffing Board · Morning Report · Resource Horizon · Assignments · Skills · Pipeline & Demand |
| **Knowledge** | Notes Vault · Search |
| **People** | Contacts · Org Chart · Performance · Training · Innovation Network |
| **Intake** | Email Intake · Meeting Import · GAL Sync · Smartsheet Sync · Draft Center |
| **System** | Admin · AI Providers & Models · AI Queue · Backups · Activity Log · Help |

Modules register in a `module_registry` table and can be disabled from Admin without code changes. Every route checks enablement and returns 404 when disabled.

---

## 6. Flagship Views

### 6.1 Command Center

Read-only. Every number is a live query; the page stores nothing.

**Action strip:** overdue · due today · meetings today · need prep · budget alerts · resource cliffs · stakeholder contact overdue · training overdue · untriaged intake.

**Zones:** Needs Attention Now · Today & Tomorrow · Project Health (RAG, schedule, burn) · Chase & Follow Up · Pipeline & Availability · My Active Charge Codes · Recent Notes.

*My Active Charge Codes* deserves special mention: it answers "where do I book this hour" without opening anything, which is the single most frequent daily question this application can retire.

### 6.2 Portfolio Timeline (Gantt)

Server-rendered SVG — no charting library, because the RAG, budget and cliff overlays are the point and a generic library would fight them.

Rows are projects, expandable to workstreams. Each row carries a two-tone bar for **baseline versus forecast**, diamonds for **major milestones only** (`milestones.is_major`), and three status chips: **on-time**, **on-budget**, **resource-cliff** (naming the cliff week). Adjustable horizon, today line, portfolio and status filters, print-friendly.

### 6.3 Master Staffing Board

```
┌─ breadcrumbs · search · 🔔 · profile ──────────────────────────────┐
├────────────────┬───────────────────────────────────────────────────┤
│ DAILY SUMMARY  │  PROJECT GRID                                     │
│  Active    24  │  ┌──────────────┐ ┌──────────────┐ ┌───────────┐  │
│  OOO        3  │  │ [header img] │ │ [header img] │ │╌╌╌╌╌╌╌╌╌╌╌│  │
│  Capacity ▓▓▓░ │  │ Acme Sell    │ │ Beta Restate │ │╌Understaff╌│  │
│                │  │ In Progress  │ │ In Progress  │ │╌ warning  ╌│  │
│ MORNING REPORT │  │ ● High       │ │ ● Medium     │ │╌╌╌╌╌╌╌╌╌╌╌│  │
│ ┌────────────┐ │  │ Timeline ──▶ │ │ Timeline ──▶ │ └───────────┘  │
│ │ JS ▓▓▓▓ 92%│ │  │ #FDD #Val    │ │ #TechAcct    │                │
│ │ Avail Nov 3│ │  │ Coverage ▓▓▓ │ │ Coverage ▓▓░ │                │
│ ├────────────┤ │  │ JS50 KP75 +2 │ │ MR100 +1     │                │
│ │ KP ▓▓▓▓▓118│ │  │ [Assign Team]│ │ [Assign Team]│                │
│ │ Over        │ │  └──────────────┘ └──────────────┘               │
└────────────────┴───────────────────────────────────────────────────┘
```

**Left rail:** daily summary (active / OOO / total capacity bar) over condensed staff cards — avatar, colour-coded capacity bar, availability date.

**Project tiles:** header image with deterministic colour fallback · name and client · status and priority badges · timeline strip · required-skill tags · staffing coverage bar · assigned avatars with allocation percentages · budget-burn chip · **Assign Team** action. Understaffed projects carry a dashed border and warning label.

A **scenario selector** drives what-if comparison (§9.4).

**Capacity colour bands.** Four bands, not three: under 60% blue-grey (bench), 60–95% green (good), 95–110% amber (warning), over 110% red (over-capacity). The fourth band exists because someone at 30% is a *bench* problem — actionable, and precisely the person you are hunting for when staffing. Collapsing that into "green — good capacity" would hide it.

### 6.4 Template Library

Browse by service offering and project type, preview a pack's contents, import into a new or existing project through a five-stage wizard, and save an existing project back as a pack.

---

## 7. Core Subsystems

Each has a companion document; summarised here for orientation.

### 7.1 Hybrid relational model

A deliberate two-mode approach:

- **Hard foreign keys for containment and money** — `workstream.project_id`, `charge_code.project_id`, `task.workstream_id`, `time_entry.charge_code_id`, `assignment.project_id`. Budget rollups and utilization math are the core of this application and need real joins with real integrity.
- **`entity_links` for cross-cutting many-to-many** — notes ↔ anything, people ↔ anything, meetings ↔ anything, emails ↔ anything, performance items ↔ anything.

### 7.2 Charge codes — the financial reconciliation key

A project has **one or more** charge codes. The charge code, not the project, is what time is booked against, what the timesheet export carries, and what external reporting rolls up by.

`time_entries.charge_code_id` is the foreign key; project and workstream are **derived** from it. Import reconciles on code; unknown codes enter a reconciliation queue rather than being dropped. Lead partner and engagement manager live on the charge code, falling back to project defaults when null — distinct leadership across codes on one project is normal and supported.

→ `docs/FINANCIAL_MODEL.md`

### 7.3 Rates, ERP and fees — the single source of budget truth

```
rate card (by level, by year)  →  standard rate
                               ×  ERP %          (or a negotiated card instead)
                               =  ENGAGEMENT RATE
                               ×  hours by task from the WBS
                               =  labour revenue
                               +  admin 12% · tech 3% · Kinergy 8%/5%
                               =  total engagement value
```

**Nine rate card levels:** Intern/Paraprofessional · Associate · Senior Associate · Manager · Director (<3 yrs) · Senior Director (3+ yrs) · Managing Director · Partner/Principal (<5 yrs) · Partner/Principal (5+ yrs).

Two of those split on **tenure**, not title, so `job_title_map` gives only a default and `person_level_history` is authoritative. The application flags a due transition at 36 and 60 months rather than applying one — missing a tenure step means billing at the junior rate for months with nothing announcing it.

`app/core/rates.py` → `resolve_rates(person_id, work_date, project_id, charge_code_id)` returns **standard rate, ERP %, engagement rate and cost rate** — all four, so the derivation stays auditable rather than collapsing to a single number. Resolution order: person override → level-at-date on the card → default card. **ERP never touches cost rates**; applying a realization discount to cost would inflate margin and look like good news.

**Fees are data, not code.** `fee_types` + `fee_type_rules` + `project_fees` means adding a fee is a row, and rates vary by project type without a branch anywhere. Resolved rates are copied onto the project so a firm-wide fee change next year cannot restate a signed engagement.

Rate cards are scoped by **company/entity** — KPMG US and KPMG Global Services cost rates differ by a large multiple, and mis-scoping understates cost on every blended engagement.

→ `docs/FINANCIAL_MODEL.md`

### 7.4 Notes vault — Obsidian semantics bound to records

Markdown files on disk are canonical; SQLite holds a rebuildable index. YAML frontmatter, `[[wikilinks]]` with `|aliases`, `#tags`, and the key extension — **typed record links**: `[[project:acme-sell-side]]`, `[[task:412]]`, `[[person:Jane Doe]]`, `[[charge:ABC-1234]]`, `[[risk:88]]`. Backlinks render on notes *and* on structured record pages.

Additional vault roots are configurable, so `docs/*.md` — including this specification — are browsable, searchable and editable in the same in-app editor.

→ `docs/NOTES_VAULT_SPEC.md`

### 7.5 Template library

Folder tree at `template_library/<Service Offering>/<Project Type>/`, mirroring the taxonomy on `projects`. Packs author as either an `.xlsx` workbook or YAML/CSV files.

Three rules make templates genuinely reusable:
- **All dates are relative** — day offsets from project start or a named anchor, with durations and dependencies. Absolute dates never appear in a pack.
- **Resources are planned by level, not person.** Unstaffed template roles feed the Resource Horizon as *demand*, which is what surfaces a resource cliff before the job is staffed.
- **Budgets price at import** through `resolve_rates()`.

**Workstream start-up packs** are a second pack kind, applicable to any workstream in any project. Their central artifact is the **workstream charter** — generated automatically when a workstream is created — covering objective, people, timeline, major tasks, dependencies (inbound and outbound), assumptions, physical and digital work locations, validation checks and context. Live sections refresh from the database via managed blocks; prose sections hold the judgement a database cannot. It exists so someone joining mid-flight can get productive without a handover call.

→ `docs/TEMPLATE_LIBRARY.md`

### 7.6 Health computation

`app/core/health.py` answers on-time / on-budget / resource-cliff for any project; every other view reads it.

- **On time** — forecast end versus baseline end; milestones forecast past baseline; overdue milestones. Requires baselines, which is why change control is in scope: variance measured against an *approved* baseline, not a moving target.
- **On budget** — actual plus committed cost versus budget; burn % versus elapsed %; EAC; margin %.
- **Resource cliff** — earliest week where assigned capacity drops below required coverage, or where a key assignment ends before the project's forecast end.

### 7.7 Resource model

`capacity` = effective-dated weekly hours minus out-of-office. `allocated` = Σ (allocation % × capacity) across overlapping assignments. `coverage` = Σ assigned FTE ÷ Σ required FTE. Demand = committed projects + unstaffed template roles + probability-weighted pipeline, by week **and by level**.

Assignments carry an extendable `end_date`; every extension writes an `assignment_extensions` row, giving the audit trail of how a three-month assignment became eleven.

→ `docs/RESOURCE_MODEL.md`

### 7.8 People, GAL and the org chart

Seeded from `AASppl.xlsx` (450 people). GAL enrichment fills every attribute, resolves `manager_email` to `manager_person_id`, and **auto-imports missing managers up a bounded chain** (depth cap, cycle detection, boundary stop, `import_source` tagging, executed as a queued job).

**Job title is not level.** The seed contains 13 titles encoding ladder rank, function and specialist status simultaneously. `job_title_map` resolves each to a level and a function; rates hang off level, never title.

`manager_person_id` is the administrative reporting line. It is deliberately distinct from the counselee relationship in `performance_tracks` — people frequently report to one person and are counselled by another.

→ `docs/INTEGRATION_RULES.md`, `docs/RESOURCE_MODEL.md`

---

## 8. Integrations

### 8.1 Outlook — ownership-partitioned calendar sync

The trap in two-way calendar sync is that if both sides can edit an item you get duplicates, ghosts and clobbered events forever. The escape is that **no item ever has two owners**:

```
Outlook Calendar
├─ Calendar (default)      ← PersonalOS READS ONLY
│    real meetings, invites      dedup by EntryID
│                                change-detect by LastModificationTime
└─ PersonalOS              ← PersonalOS WRITES ONLY (folder it creates)
     recurring reminders · comms touchpoints · milestone markers
     meeting-prep blocks · stakeholder contact reminders
```

PersonalOS-owned items are **zero-attendee appointments**, so a write can never email anyone. That is the hard safety property that makes write-back acceptable. Native `ReminderMinutesBeforeStart` means reminders fire whether or not PersonalOS is open.

All COM runs in **subprocesses**, never inside a Flask request. Drafts use `Display()`, never `Send()`. No Microsoft Graph.

→ `docs/CALENDAR_SYNC.md`, `docs/INTEGRATION_RULES.md`

### 8.2 Smartsheet — read-only REST

Four source kinds: pipeline, roster, allocations, resources. Token in gitignored `secrets.json`. `GET` only against `api.smartsheet.com`; V1 never writes back. Per-sheet column maps configured in Admin so sheet edits do not break the sync. Rows upsert by `smartsheet_row_id`; local edits to synced fields are **flagged as divergent rather than overwritten**.

### 8.3 Timesheet / WIP import

Watched inbox, label-driven `.xlsx` parsing (columns found by header text, not position). Idempotent by file SHA-256. Preview-then-commit; unmatched charge codes and unknown people surface in a reconciliation screen.

---

## 9. AI Subsystem

### 9.1 Architecture

A **separate local process speaking an OpenAI-compatible API**, not a model embedded in Flask:

```
┌─ personalos-ai serve ──────────────┐      ┌─ PersonalOS (Flask) ─┐
│  127.0.0.1:5151                    │◀─────│  app/core/ai/client  │
│  /v1/models · /v1/chat/completions  │ HTTP │  (base_url setting)  │
│  /v1/embeddings · /healthz          │      └──────────────────────┘
│  ── ONNX Runtime GenAI ─────────────│
│     Phi-4-mini INT4 ~2.5GB          │      Model stays resident
│     bge-small-en-v1.5 ~130MB        │      across Flask restarts
└─────────────────────────────────────┘
```

A 2.5GB model load would block Flask's worker threads and a runaway generation would take the app down with it. Separation also means the model stays warm across restarts — and because it speaks a standard API, approving Ollama or LM Studio later changes one `base_url` setting and deletes no code.

### 9.2 Providers and data boundary

Adapters: local/OpenAI-compatible · Anthropic (Claude) · Google (Gemini) · null. Cloud adapters are **built but dormant** until keys are configured.

**Policy: local-only by default, per-feature opt-in.** Every feature declares a `max_boundary`; features touching client data default to `local`. Embeddings are hard-pinned local — the operation by definition ships the entire vault. A boundary badge appears before every run, and `ai_runs` records provider, boundary and vendor per request.

> **Fallback chains never cross a boundary.** If the local provider is down and the feature is local-only, the job fails visibly. Silent escalation from a dead local model to a cloud provider is the one failure mode that would quietly turn a confidentiality guarantee into a breach, so the code path does not exist.

### 9.3 Rules

- **The model never writes to the database.** Every output is a proposal in a review screen with per-item accept/reject. A hallucinated milestone date written silently into a baseline would do real damage, so the path does not exist.
- **Nothing blocks a request.** Generation runs through a durable `ai_jobs` queue with a worker.
- **Grounded where numbers are involved.** The status report generator assembles RAG, milestones, budget variance and RAID from live queries; the model turns assembled facts into prose and is never asked to source a number.
- **Off by default, degrades to nothing.** Every AI-assisted flow has a working manual path.

### 9.4 Features

Email and meeting triage · meeting-notes → structured records · semantic vault search · status and comms drafting.

**Honest expectation on CPU-only / 16GB at ~5–15 tok/s with a 3–4B model:** semantic search is excellent, extraction and classification are good, long-form drafting is the weak spot — a 500-token status report takes 30–100 seconds and will need editing. Retrieval and extraction will earn their keep first.

### 9.5 Model acquisition

**Manual placement is the primary path**, on the assumption that huggingface.co is proxy-blocked. A curated catalog ships with exact file lists, sizes, checksums and generated install sheets. Drop files into `app/data/models/<model-id>/` and scan.

GGUF is a single file; ONNX Runtime GenAI models are **directories** — the validator names the specific missing file rather than failing generically, because `model.onnx.data` is multi-gigabyte and the easiest to miss.

→ `docs/AI_SUBSYSTEM.md`, `docs/MODEL_INSTALL_GUIDE.md`

---

## 10. Security & Privacy

| Concern | Control |
|---|---|
| Network exposure | Binds `127.0.0.1` only; asserted by `health_check.py` |
| SQL injection | Parameterised queries exclusively; no string interpolation of user input |
| XSS | Jinja2 autoescaping on; `nh3` sanitisation for rendered markdown; never `\| safe` on user content |
| CSRF / state change | POST for every create, update, delete, archive, link and unlink |
| Path traversal | Vault and template paths must satisfy `Path.resolve().is_relative_to(root)` |
| Secrets | `app/data/secrets.json`, gitignored, never logged, masked in UI |
| Data egress | AI boundary policy (§9.2); Smartsheet is `GET`-only to one host |
| Destructive actions | Archive over delete; pre-migration backup that aborts migration on failure |
| Auditability | `activity_log` for every mutation; `ai_runs` for every model call |
| Sensitive HR data | Out of scope by policy — no compensation, ratings or disciplinary records |

---

## 11. Build Sequence

24 phases. Phases 0–4 deliver a genuinely usable application; everything after layers on.

→ `docs/BUILD_SEQUENCE.md`

---

## 12. Document Map

| Document | Covers |
|---|---|
| `PersonalOS_Spec.md` | This document — purpose, principles, IA, subsystem overview |
| `docs/DATABASE_SCHEMA.md` | Complete DDL, enums, indexes, migration ownership |
| `docs/TEMPLATE_LIBRARY.md` | Pack formats, relative dates, import wizard, save-as-template |
| `docs/FINANCIAL_MODEL.md` | Charge codes, ERP and engagement rates, the fee model, budget-to-actual |
| `docs/RESOURCE_MODEL.md` | Capacity, coverage, cliffs, staffing board, org chart |
| `docs/CALENDAR_SYNC.md` | Ownership partition, RRULE, occurrences, write rules |
| `docs/NOTES_VAULT_SPEC.md` | Vault layout, link grammar, indexer, editor |
| `docs/INTEGRATION_RULES.md` | Outlook, GAL, Smartsheet, timesheet boundaries |
| `docs/UI_DESIGN_SYSTEM.md` | Theme, tokens, object grammar, palette, hotkeys, accessibility |
| `docs/AI_SUBSYSTEM.md` | Providers, boundary policy, queue, prompts, audit |
| `docs/MODEL_INSTALL_GUIDE.md` | Manual model installation, troubleshooting |
| `docs/BUILD_SEQUENCE.md` | 24 phases with acceptance criteria |
| `docs/TEMPORAL_MODEL.md` | Effective-dated truth, threshold transitions, the `as_of` discipline |
| `docs/DESIGN_DECISIONS.md` | Judgement calls made during specification, with reversal cost — revisit as needed |
| `CLAUDE.md` | Build rules for future development sessions |
