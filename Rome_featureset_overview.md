# Rome — Feature List (MECE)

## Tech Stack & Requirements

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Web framework | Flask 3.x (`Flask>=3.0.0`, `Werkzeug>=3.0.0`) |
| Templates | Jinja2 (`Jinja2>=3.1.0`), auto-escaping on |
| Database | SQLite via `sqlite3` (Python stdlib) — no ORM |
| CSS | Bootstrap 5, loaded from CDN (not vendored) |
| JavaScript | Minimal vanilla JS only — no framework, no build step |
| Storage | Local filesystem only — `app/data/rome.db`, backups, and (for the Vault) a separate SQLite file outside the project directory |

**Required libraries** (`requirements.txt`):
- `Flask>=3.0.0`
- `Werkzeug>=3.0.0`
- `Jinja2>=3.1.0`
- `openpyxl>=3.1.0` — reads the weekly WIP `.xlsx` export (Import WIP module)

**Optional library:**
- `pywin32>=306` — Windows-only, required only for Outlook calendar/email import (Meetings, Email Intake, Draft Center). The app runs without it; those Outlook-specific actions are simply unavailable.

No cloud services, external APIs, Docker, React, TypeScript, or message queues — Rome is a local-first, single-user, Windows-desktop app that binds to `127.0.0.1` only.

Grouped using the app's own sidebar taxonomy (`NAV_GROUPS` in `app/core/module_registry.py`) — each module belongs to exactly one group, and together they're all of Rome's enabled functionality. Retired modules are called out separately since their code still exists but they're hidden from navigation.

### Command — daily operating surface
- **Cockpit** — Read-only "Today" action list: an action strip (Overdue · Due today · Meetings today · Need prep · To chase) over three zones — Needs Attention Now, Today's Meetings & Prep, Chase & Follow Up. Stores nothing; every number is a live query against other modules. Includes quick-capture shortcuts and the backup-age chip.
- **Tasks** — Single action-item store for to-dos, follow-ups, delegated items, and waiting-on items. Supports recurrence, bulk multi-select actions, and linking to projects/meetings/references/people.
- **Meetings** — Meeting records with HBR-style prep fields, notes, decisions, and follow-up generation (creates a linked Task). Default view is a 7-day calendar; a List view keeps tabs/search. One-click Outlook calendar import (dedups recurring series on subject+date+time+organizer).

### Work — client/engagement delivery
- **Engagement** (module key `projects`, URL `/projects`) — Merged Projects+Engagements record: status/RAG updates, budget tracking, fees, delivery, and a WIP-driven Billing tab (Total Fee, Invoiced, Paid, AR/bill-allocation tables). Opens on its own mini-cockpit (KPIs, tasks, meetings, people, notes, WIP hours).
- **Import WIP** (module key `financials`) — Imports the weekly WIP `.xlsx` export (label-driven parsing, survives column shifts), then links each WIP project to an Engagement (or creates one). The shared `core/wip.py` engine computes hours, margin %, revenue, and unbilled WIP used by both this module and the Engagement's WIP Hours tab.

### Knowledge — reference & learning material
- **Knowledge Base** — Curated learning/reference library (courses, articles, books) with progress/status/rating tracking, markdown takeaways, and FTS5 full-text search.
- **Notes** — Quick notes, decision records, and learning notes with a rich-text editor (bold/italic/lists/color), sanitized via an allow-list HTML sanitizer. Links to projects/tasks/meetings/references/people.
- **References** — Pointers only (file/folder paths, links, email metadata) — never file contents. Includes a folder browser (read-only directory listing) seeded from an admin-configurable root path.

### Relationships — people context
- **People** — Relationship context on colleagues/clients/vendors: role, org, notes, strengths, development areas, follow-up dates. Every other module can link to a person; name fields elsewhere are dropdowns sourced from here (no free-text names).
- **Performance Management** — Fiscal-year cycles, tracks (self/counselee/promotion), and items (goals, wins, feedback, 1:1 notes). Includes a filterable Review Builder that generates copy-paste review sections.

### Personal
- **Habits** — Daily/weekly habit definitions with one completion log per habit per day and streak calculation.

### Intake / Output — email-adjacent workflows
- **Email Intake** — Metadata-only email records (subject, sender, summary, extracted action) pulled from Outlook over a date range, or entered manually. Triage actions convert an item into a Task, Note, Reference, or a prefilled Draft reply.
- **Draft Center** — Drafts (email / reply / meeting invite) composed in Rome and opened in Outlook for the user to review and send manually — Rome never calls `Send()`.
- **Bulk Import** — Additive-only CSV import into Tasks, Projects, People, Meetings, References, or Notes.

### System — administration & infrastructure
- **Admin** — Module registry (enable/disable), config option values, app settings (app name, owner name, theme, mantras), template management, activity log viewer, backup management.
- **Credential Vault** — Password/credential storage in a separate, unencrypted SQLite file kept outside the project directory; never touches `rome.db` or normal backups.
- **Help** — Static onboarding guide and per-module usage reference; no data of its own.

### Retired (code + tables kept, disabled in registry)
- **Daily Plan** (migration 0027) — per-date focus/schedule/reflection planner; superseded by the Cockpit redesign.
- **Engagements** (migration 0028) — standalone engagement module; merged into "Engagement" (Projects).

### Cross-cutting mechanisms (not features of any one module)
- **entity_links** — the single join table used for every cross-module relationship (no hard-coded foreign keys between modules).
- **Activity log** — every create/update/delete/archive/restore across all modules is recorded centrally.
- **Startup/manual/full backups** of `rome.db`, with retention via `backup_count_to_keep`.
