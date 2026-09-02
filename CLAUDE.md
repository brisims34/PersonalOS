# PersonalOS — Development Rules

## What This Is

A local-first, single-user productivity and engagement-management application. Flask + SQLite, running on Windows-native Python, opening in the local browser. Single user, single machine.

Read `PersonalOS_Spec.md` before making any non-trivial change.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ (Windows-native — required for Outlook COM) |
| Web framework | Flask 3.x |
| Templates | Jinja2, autoescaping on |
| Database | SQLite via stdlib `sqlite3` — no ORM |
| CSS | Bootstrap 5.3, vendored locally, dark-first via `data-bs-theme` |
| JavaScript | Vanilla only — no framework, no bundler, no build step |

## Commands

```bash
# First-time setup
python -m venv .venv
.venv\Scripts\activate.bat          # Windows (WSL/macOS: source .venv/bin/activate)
pip install -r requirements.txt
pip install pywin32                 # Windows only — Outlook features

# Run (DB created and migrated automatically on first run)
python run.py                       # http://127.0.0.1:5000

# Optional AI model server — separate process, keeps the model resident
python personalos_ai.py serve       # http://127.0.0.1:5151

# Maintenance — all at the repo root, so each is `python <name>.py`
python health_check.py              # exit 0 = all pass; run after every pull
python verify_docs.py               # schema DDL executes + docs are consistent
python apply_migrations.py          # backup → migrate → verify
python vendor_assets.py             # fetch Bootstrap, or --from a folder
python reindex_notes.py             # Phase 3
python reindex_templates.py         # Phase 16
python sync_smartsheet.py           # Phase 10
python preflight.py                 # Phase 20 — which AI backends work here
```

There is no automated test suite. Validation is `health_check.py` plus the manual checklist for the relevant phase in `docs/BUILD_SEQUENCE.md`.

## Where Things Live

```
app/core/           shared engines — database, backup, config, module_registry,
                    links, activity, rates, health, resourcing, paths,
                    markdown, notes_index, ai/
app/integrations/   outlook/ · smartsheet/ · timesheet/
app/modules/<name>/ routes.py (Blueprint) + models.py (all SQL)
app/templates/      base.html · partials/ · modules/<name>/
app/static/         css/personalos.css · js/ · vendor/ (Bootstrap — committed,
                    so a machine that cannot reach a CDN still gets it)
app/data/           personalos.db · backups/ · inbox/ · models/ · secrets.json
                    — ALL GITIGNORED, lives only on the Windows side
projects/           notes vault root (markdown on disk)
template_library/   project template packs
*.py at root        maintenance scripts (health_check, apply_migrations, …)
```

## Non-Negotiable Rules

1. **Local only.** Bind `host='127.0.0.1'`. The only permitted outbound calls are Smartsheet (`GET` to `api.smartsheet.com`), configured AI providers, and explicit model downloads. Nothing else.
2. **Parameterised queries only.** Never interpolate user input into SQL. Table and column names built into query strings must be developer constants, never request data.
3. **Autoescaping stays on.** Never `| safe` on user content. Rendered markdown passes through `nh3`.
4. **POST for every state change.** Create, update, delete, archive, link, unlink. Never GET.
5. **Schema changes require a migration.** A new numbered file in `app/core/migrations/`, an update to `docs/DATABASE_SCHEMA.md` — **including the section's mermaid ER diagram** — and a pre-migration backup that **aborts the migration if the backup fails**. Never drop a user table. Never overwrite user-entered data.
6. **Files are the truth for notes and templates.** The database indexes them and must be rebuildable by rescanning. Never store note content only in SQLite.
7. **Path confinement.** Every vault or template path must satisfy `Path.resolve().is_relative_to(root)` before use, or the request is rejected.
8. **All money math goes through `resolve_rates()`.** No inline rate lookups. This is what keeps plan and actual priced identically.
9. **Hard FKs for containment and money; `entity_links` for cross-cutting relationships.** See `PersonalOS_Spec.md` §7.1. Do not add a polymorphic link where a real foreign key belongs, or a foreign key where a many-to-many belongs.
10. **Outlook COM only in subprocesses.** Never `import win32com` inside a Flask request. Writes are confined to the `PersonalOS` calendar folder. Written items carry **zero attendees**. Drafts use `Display()`, never `Send()`.
11. **AI output is always a proposal, never a direct write.** No request blocks on a model. The model is never asked to source a number. Fallback never crosses a data boundary. Embeddings are always local.
12. **Secrets are never logged or rendered.** `app/data/secrets.json` only; masked in the UI.
13. **Activity log every mutation.** No passwords, file contents, or sensitive values in log entries.
14. **Module registry.** Every module registers and every route checks `is_module_enabled()`, aborting 404 when disabled.
15. **No overbuild.** No React, TypeScript, Docker, ORM, message queue, CSS framework beyond Bootstrap, or build step of any kind.
16. **Comments explain non-obvious WHY only.** No docstrings on self-evident functions.
17. **`as_of` is a parameter, never an assumption.** No function in `app/core/` calls `date.today()` — the evaluation date is passed in and routes supply the default. See `docs/TEMPORAL_MODEL.md` §3. This is what makes forward views ("what will be overdue in March?") and backdated imports possible at all, and it cannot be retrofitted cheaply.

## Key Principles Checklist — verify before completing any UI work

From `PersonalOS_Spec.md` §2. These are gates, not aspirations.

- [ ] **Primary action nameable** — you can state this page's primary action without hunting (P1)
- [ ] **Confirmation is specific** — it names the actual effect and links onward; it could not be pasted onto another feature and still read correctly (P2)
- [ ] **Computed numbers are traceable** — clicking any derived figure shows the rows behind it (P3)
- [ ] **Multi-step work is a wizard** — stage N of M, stated effect, dry-run preview before commit (P4)
- [ ] **Destructive actions preview and archive** rather than delete (P5)
- [ ] **Page conforms to the object grammar** — identity header → action bar → tabbed body → links panel → activity trail (P7)
- [ ] **Context is pre-filled** — nothing re-asked that the app already knows (P8)
- [ ] **Accounting vocabulary and number formatting** — thousands separators, parentheses for negatives, right-aligned numerics, USD only (no currency selectors or codes rendered), unambiguous dates (P9)
- [ ] **A keyboard path exists** for every action; no mouse-only interactions (P10)
- [ ] **Every drag has a keyboard and menu equivalent** (P11)
- [ ] **No state encoded by colour alone** — every RAG chip, capacity bar and coverage indicator carries a label or numeral

## Module Structure

```
app/modules/<name>/
├── __init__.py     # from .routes import bp
├── routes.py       # Blueprint, url_prefix='/<name>'
└── models.py       # all DB queries — no ORM, no cross-module imports

app/templates/modules/<name>/*.html
```

Modules must not import from each other. Shared queries belong in `app/core/`.

## Database Access

```python
from app.core.database import get_db

db = get_db()
rows = db.execute("SELECT * FROM tasks WHERE status = ?", ("open",)).fetchall()
```

Request-scoped connection, WAL mode, `PRAGMA foreign_keys=ON`. Never open a second connection.

## What to Read Before Changing What

| Task | Read first |
|---|---|
| Anything non-trivial | `PersonalOS_Spec.md` |
| New table or column | `docs/DATABASE_SCHEMA.md` |
| Any UI work | `docs/UI_DESIGN_SYSTEM.md` |
| Rates, budgets, charge codes | `docs/FINANCIAL_MODEL.md` |
| Capacity, coverage, staffing, org chart | `docs/RESOURCE_MODEL.md` |
| Notes, markdown, wikilinks | `docs/NOTES_VAULT_SPEC.md` |
| Template packs | `docs/TEMPLATE_LIBRARY.md` |
| Calendar or recurrence | `docs/CALENDAR_SYNC.md` |
| Outlook, GAL, Smartsheet, timesheet | `docs/INTEGRATION_RULES.md` |
| AI features or providers | `docs/AI_SUBSYSTEM.md` |
| Installing a model | `docs/MODEL_INSTALL_GUIDE.md` |
| Phase planning | `docs/BUILD_SEQUENCE.md` |
| Anything involving dates, expiry, tenure or "due" | `docs/TEMPORAL_MODEL.md` |
| Wondering why something was designed this way | `docs/DESIGN_DECISIONS.md` |
| What still needs Brian's answer, and by when | `docs/DECISION_LOG.md` |

## Before Completing a Phase

0. `python verify_docs.py` exits 0 — proves the schema doc's DDL still executes and every capability is still traceable
1. `python health_check.py` exits 0
2. `python run.py` starts with no traceback
3. Affected pages load and show correct data; no 500s in the log
4. The phase's manual checklist in `docs/BUILD_SEQUENCE.md` is walked
5. The Key Principles checklist above passes for any new UI
6. Docs updated: `DATABASE_SCHEMA.md` if schema changed, `PersonalOS_Spec.md` if behaviour changed, `BUILD_SEQUENCE.md` phase marked complete

## Environment Note

Development happens in the WSL repository at `/home/bsims/00_AI_Dev_Projects/PersonalOS`. The application **runs** on Windows-native Python from a synced copy at `C:\Users\bsims\PersonalOS`, because Outlook COM is unreachable from WSL.

> Never run SQLite over `\\wsl$\`. The 9p share does not honour file locking reliably and will corrupt the database. `app/data/` is gitignored and exists only on the Windows side.
