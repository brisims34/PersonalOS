"""PersonalOS health check.

    python health_check.py          exit 0 = every check passed

Run after every pull, and before declaring a phase complete. This validates
the live installation; `verify_docs.py` validates the documents that describe
it. The two are deliberately separate.
"""
import importlib
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

REQUIRED_PACKAGES = ("flask", "jinja2", "werkzeug", "markdown", "nh3", "yaml",
                     "dateutil", "openpyxl", "requests")
OPTIONAL_PACKAGES = ("win32com", "onnxruntime_genai", "fastembed", "numpy")

# Every table Milestone 1 depends on. Extended as each phase lands, so a
# half-applied migration chain is caught here rather than at a 500.
EXPECTED_TABLES = (
    # 0001 system
    "schema_migrations", "app_settings", "config_options", "module_registry",
    "activity_log", "entity_links",
    # 0002 people · 0003 rates
    "person_levels", "job_title_map", "people", "person_level_history",
    "person_capacity", "person_status_events",
    "rate_cards", "rate_card_entries", "person_rate_overrides",
    # 0004 work
    "portfolios", "projects", "workstreams", "charge_codes",
    "locations", "work_resources", "dependencies",
    # 0005 notes · 0006 tasks
    "vault_roots", "notes", "note_links", "notes_fts",
    "tasks", "task_recurrences",
    # 0007 imports
    "import_batches",
)

results = []


def check(name, passed, detail="", fatal=True):
    results.append({"name": name, "passed": bool(passed), "detail": detail, "fatal": fatal})
    return bool(passed)


def section(title):
    print(f"\n{title}\n{'-' * len(title)}")


def scratch_app():
    """An app bound to a throwaway copy of the database, seeded with rows.

    Two reasons this exists rather than checking against the real database.
    A check that writes — an inline edit, a created level — would mutate a
    live roster, and this file is run routinely. And a check over an empty
    table passes without proving anything, so the copy is seeded with enough
    people for the filter and sort checks to be able to fail.

    Returns (app, cleanup). The caller must call cleanup().
    """
    import shutil
    import tempfile

    from app import create_app
    from app.core import paths as core_paths

    workspace = tempfile.mkdtemp(prefix="personalos-healthcheck-")
    copy = Path(workspace) / "healthcheck.db"
    shutil.copy(core_paths.DB_PATH, copy)

    # The copy is migrated to head, so these checks exercise the schema the
    # code expects even when the live database has not been migrated yet.
    # No backup: the copy is disposable and about to be deleted.
    from app.core.database import apply_migrations

    apply_migrations(copy, backup=False)

    app = create_app(run_migrations=False)
    app.config["DATABASE_PATH"] = str(copy)

    conn = sqlite3.connect(copy)
    conn.row_factory = sqlite3.Row
    try:
        ladder = conn.execute(
            "SELECT id FROM person_levels ORDER BY sort_order LIMIT 2"
        ).fetchall()
        levels = [row["id"] for row in ladder] or [None, None]
        for n, (first, company, department, status, level) in enumerate((
            ("Hilda", "Acme", "Advisory", "active", levels[0]),
            ("Ivor", "Acme", "Tax", "active", levels[-1]),
            ("Juno", "Beta Corp", "Advisory", "inactive", levels[0]),
        )):
            conn.execute(
                "INSERT INTO people (first_name, last_name, full_name, email, "
                "company, department, status, level_id, city, state_province) "
                "VALUES (?, 'Healthcheck', ?, ?, ?, ?, ?, ?, 'Detroit', 'MI')",
                (first, f"{first} Healthcheck",
                 f"healthcheck-{n}@example.invalid", company, department,
                 status, level),
            )
        conn.commit()
    finally:
        conn.close()

    def cleanup():
        shutil.rmtree(workspace, ignore_errors=True)

    return app, cleanup


def main():
    from app.core import paths

    # --- 1. runtime ---------------------------------------------------------
    section("Runtime")
    version = sys.version_info
    check(
        "Python 3.11 or newer",
        version >= (3, 11),
        f"found {version.major}.{version.minor}.{version.micro}",
    )

    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package)
            check(f"import {package}", True)
        except ImportError as exc:
            check(f"import {package}", False, str(exc))

    for package in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(package)
            check(f"import {package} (optional)", True, "available", fatal=False)
        except ImportError:
            reason = "Windows only" if package == "win32com" else "AI subsystem, Phase 20"
            check(f"import {package} (optional)", False, f"absent — {reason}", fatal=False)

    # --- 2. filesystem ------------------------------------------------------
    section("Filesystem")
    for directory in paths.RUNTIME_DIRS:
        exists = directory.exists()
        writable = exists and os.access(directory, os.W_OK)
        check(
            f"{directory.relative_to(ROOT) if directory.is_relative_to(ROOT) else directory} writable",
            writable,
            "missing" if not exists else ("not writable" if not writable else ""),
        )

    check(
        "app/data is gitignored",
        "app/data/" in (ROOT / ".gitignore").read_text(encoding="utf-8"),
        "the database and secrets must never be committed",
    )

    if paths.SECRETS_PATH.exists():
        check("secrets.json is inside app/data", True, "gitignored by the app/data/ rule", fatal=False)

    # --- 3. localhost binding ----------------------------------------------
    section("Network posture")
    run_source = (ROOT / "run.py").read_text(encoding="utf-8")
    check(
        "run.py fixes the host at 127.0.0.1",
        re.search(r'^HOST\s*=\s*"127\.0\.0\.1"', run_source, re.MULTILINE) is not None,
        "CLAUDE.md rule 1",
    )
    check(
        "run.py passes host=HOST to app.run",
        "app.run(host=HOST" in run_source,
        "a literal or configurable host would defeat the rule",
    )

    offenders = []
    for source in list(ROOT.glob("*.py")) + list((ROOT / "app").rglob("*.py")):
        if source.name == Path(__file__).name:
            continue  # this file names the address in order to look for it
        if "0.0.0.0" in source.read_text(encoding="utf-8"):
            offenders.append(str(source.relative_to(ROOT)))
    check(
        "no source file mentions 0.0.0.0",
        not offenders,
        ", ".join(offenders),
    )

    # --- 4. database --------------------------------------------------------
    section("Database")
    if not paths.DB_PATH.exists():
        check("personalos.db exists", False, f"not found at {paths.DB_PATH} — run `python run.py` once")
        return report()

    conn = sqlite3.connect(paths.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        check("journal mode is WAL", journal.lower() == "wal", f"found {journal}")

        conn.execute("PRAGMA foreign_keys=ON")
        check("foreign keys enforceable", conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1)

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        check("integrity check", integrity == "ok", integrity)

        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        check("no foreign key violations", not violations, f"{len(violations)} row(s)")

        present = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = [t for t in EXPECTED_TABLES if t not in present]
        check(f"all {len(EXPECTED_TABLES)} expected tables present", not missing,
              ", ".join(missing))

        # --- 5. migration state --------------------------------------------
        section("Migrations")
        from app.core.database import discover_migrations

        on_disk = discover_migrations(paths.MIGRATIONS_DIR)
        highest = max((m.version for m in on_disk), default=0)
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        check(
            "schema version matches the newest migration",
            user_version == highest,
            f"user_version={user_version}, newest on disk={highest:04d}",
        )

        recorded = {
            r["migration"]
            for r in conn.execute("SELECT migration FROM schema_migrations").fetchall()
        }
        unrecorded = [m.filename for m in on_disk if m.version <= user_version
                      and m.filename not in recorded]
        check(
            "every applied migration is recorded",
            not unrecorded,
            ", ".join(unrecorded),
        )

        # --- 6. registry and settings ---------------------------------------
        section("Configuration")
        module_count = conn.execute("SELECT COUNT(*) FROM module_registry").fetchone()[0]
        check("module registry seeded", module_count >= 40, f"{module_count} modules")

        enabled = conn.execute(
            "SELECT COUNT(*) FROM module_registry WHERE is_enabled = 1"
        ).fetchone()[0]
        check("at least one module enabled", enabled >= 1, f"{enabled} enabled", fatal=False)

        settings = conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0]
        check("app settings seeded", settings >= 15, f"{settings} keys")

        options = conn.execute(
            "SELECT COUNT(DISTINCT option_set) FROM config_options"
        ).fetchone()[0]
        check("config option sets seeded", options >= 11, f"{options} sets")
    finally:
        conn.close()

    # --- 7. application -----------------------------------------------------
    section("Application")
    try:
        from app import create_app

        app = create_app(run_migrations=False)
        check("create_app() succeeds", True, f"{len(app.blueprints)} blueprint(s)")

        with app.test_client() as client:
            routes = [
                ("/", 200), ("/tasks/", 200), ("/projects/", 200),
                ("/portfolios/", 200), ("/charge-codes/", 200), ("/people/", 200),
                ("/people/titles", 200), ("/people/import", 200),
                ("/org-chart/", 200), ("/rates/", 200), ("/rates/calculator", 200),
                ("/rates/levels", 200),
                ("/notes/", 200), ("/notes/reports/unresolved", 200),
                ("/search/", 200), ("/activity/", 200),
                ("/shell/palette.json", 200), ("/no-such-page", 404),
            ]
            for path, expected in routes:
                response = client.get(path)
                check(f"GET {path} → {expected}", response.status_code == expected,
                      f"got {response.status_code}")

            # The cross-origin guard must refuse a foreign write and pass a
            # native one. A browser only sends a usable Origin on a form POST
            # if the app's own Referrer-Policy permits it, so the header is
            # checked alongside the guard: with `no-referrer` the browser
            # sends `Origin: null` and every form in the application 403s.
            from app import SECURITY_HEADERS

            check(
                "Referrer-Policy leaves the Origin header populated",
                SECURITY_HEADERS["Referrer-Policy"] != "no-referrer",
                "`no-referrer` makes browsers serialise the Origin of a form "
                "POST as null, which the same-origin guard then rejects",
            )
            native = client.post(
                "/people/import/preview", headers={"Origin": "http://localhost"}
            )
            check("a same-origin POST is allowed through", native.status_code != 403,
                  f"got {native.status_code}")
            foreign = client.post(
                "/people/import/preview", headers={"Origin": "http://evil.example"}
            )
            check("a cross-origin POST is refused", foreign.status_code == 403,
                  f"got {foreign.status_code}")
            opaque = client.post(
                "/people/import/preview", headers={"Origin": "null"}
            )
            check("an opaque (null) Origin is refused", opaque.status_code == 403,
                  f"got {opaque.status_code}")

            # A disabled module must 404, not render. This is rule 14 tested
            # rather than asserted.
            with app.app_context():
                from app.core.module_registry import set_enabled

                set_enabled("search", False)
            check("a disabled module 404s", client.get("/search/").status_code == 404)
            with app.app_context():
                set_enabled("search", True)
            check("re-enabling restores it", client.get("/search/").status_code == 200)

            # The roster's list controls are a URL contract: anything a user
            # can type has to come out of the parser as a legal value, because
            # both the index and the CSV export are built from what it returns.
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

            check("the roster sorts in both directions",
                  client.get("/people/?sort=name&dir=asc").status_code == 200
                  and client.get("/people/?sort=name&dir=desc").status_code == 200)

            # Paging must not drop the view. A next-page link that loses the
            # filter is how you silently page into the unfiltered roster.
            # Asserted against the parser, so it holds on any database.
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

    except ImportError as exc:
        check("create_app() succeeds", False, f"{exc} — install requirements.txt")
    except Exception as exc:
        check("create_app() succeeds", False, str(exc))

    # --- 7b. the roster, against a seeded throwaway copy ---------------------
    section("Contacts roster")
    try:
        from app.modules.people import models as people_models

        scratch, cleanup = scratch_app()
        try:
            with scratch.app_context():
                # A column's own filter is excluded from its own counts, so
                # the menu still shows what else you could switch to.
                everything = people_models.column_values("company")
                narrowed = people_models.column_values("company", status="active")
                level_menu = people_models.column_values("level")

            check("column_values returns value/label/count rows",
                  len(everything) >= 2
                  and all({"value", "label", "n"} <= set(r.keys()) for r in everything),
                  f"{len(everything)} companies")
            check("a column's menu counts honour the other filters",
                  sum(r["n"] for r in narrowed) < sum(r["n"] for r in everything),
                  f"{sum(r['n'] for r in narrowed)} active of "
                  f"{sum(r['n'] for r in everything)}")
            check("the level menu keys on id, not label",
                  level_menu and all(isinstance(r["value"], int) for r in level_menu),
                  f"{len(level_menu)} level(s)")

            # The bug this fixes: the old export walked the rendered DOM and
            # so returned one page. Counts come from the count query rather
            # than a fixed number, so these hold on any database.
            with scratch.app_context():
                everyone = people_models.count_people()
                actives = people_models.count_people(status="active")

            with scratch.test_client() as roster:
                dump = roster.get("/people/export.csv?per_page=25")
                lines = dump.data.decode("utf-8").strip().splitlines()
                check("export.csv returns a CSV attachment",
                      dump.headers.get("Content-Disposition", "").startswith("attachment"),
                      dump.headers.get("Content-Disposition", "(none)"))
                check("export ignores pagination and returns every row",
                      len(lines) - 1 == everyone,
                      f"{len(lines) - 1} rows for {everyone} contacts")
                check("export carries columns the table does not show",
                      "Mobile phone" in lines[0], lines[0][:60])

                narrowed_dump = roster.get("/people/export.csv?status=active")
                narrowed_lines = narrowed_dump.data.decode("utf-8").strip().splitlines()
                check("export honours the screen's filters",
                      len(narrowed_lines) - 1 == actives and actives < everyone,
                      f"{len(narrowed_lines) - 1} rows for {actives} active "
                      f"of {everyone}")

                # Inline editing is allowlisted server-side; the grid's
                # attributes are convenience, not the security boundary.
                with scratch.app_context():
                    subject = people_models.list_people(limit=1)[0]["id"]
                origin = {"Origin": "http://localhost"}

                for field, value in (("company", "Edited Co"),
                                     ("city", "Ann Arbor"),
                                     ("state_province", "MI"),
                                     ("function", "Delivery"),
                                     ("job_title", "Edited Title")):
                    saved = roster.post(f"/people/{subject}/field",
                                        data={"field": field, "value": value},
                                        headers=origin)
                    check(f"{field} edits inline",
                          saved.get_json().get("ok") is True, str(saved.get_json()))

                refused = roster.post(f"/people/{subject}/field",
                                      data={"field": "notes", "value": "nope"},
                                      headers=origin)
                check("a field outside the allowlist is refused",
                      refused.get_json().get("ok") is False, str(refused.get_json()))
                email_refused = roster.post(f"/people/{subject}/field",
                                            data={"field": "email",
                                                  "value": "new@example.invalid"},
                                            headers=origin)
                check("email stays off the grid — it is the import's dedup key",
                      email_refused.get_json().get("ok") is False,
                      str(email_refused.get_json()))

            # Retiring a level must not unprice history, so archiving hides it
            # from the pickers while every row referencing it stays as it was.
            with scratch.app_context():
                from app.core import rates as core_rates
                from app.core.database import get_db

                visible_before = len(core_rates.levels())
                retired = core_rates.levels()[-1]["id"]
                get_db().execute(
                    "UPDATE person_levels SET archived_at = datetime('now') WHERE id = ?",
                    (retired,),
                )
                get_db().commit()
                visible_after = len(core_rates.levels())
                everything = len(core_rates.levels(include_archived=True))
            check("levels() hides an archived level",
                  visible_after == visible_before - 1,
                  f"{visible_before} → {visible_after}")
            check("include_archived still returns it",
                  everything == visible_before, f"{everything} of {visible_before}")

            with scratch.test_client() as ladder_client:
                check("GET /rates/levels → 200",
                      ladder_client.get("/rates/levels").status_code == 200,
                      f"got {ladder_client.get('/rates/levels').status_code}")

                with scratch.app_context():
                    usage = core_rates.level_usage(core_rates.list_levels()[0]["id"])
                check("level_usage counts all four dependants",
                      {"people", "rate_entries", "title_maps", "history"} <= set(usage),
                      str(sorted(usage)))

                origin = {"Origin": "http://localhost"}
                made = ladder_client.post(
                    "/rates/levels",
                    data={"label": "Health Check Level", "sort_order": 9999},
                    headers=origin, follow_redirects=True)
                with scratch.app_context():
                    fresh = [l for l in core_rates.list_levels()
                             if l["label"] == "Health Check Level"]
                check("a level can be created", len(fresh) == 1,
                      f"{len(fresh)} found, status {made.status_code}")

                if fresh:
                    new_id = fresh[0]["id"]
                    check("a created level gets a generated key it never shows",
                          bool(fresh[0]["level_key"]) and fresh[0]["level_key"] != "",
                          fresh[0]["level_key"])

                    dupe = ladder_client.post(
                        "/rates/levels",
                        data={"label": "Health Check Level", "sort_order": 8888},
                        headers=origin, follow_redirects=True)
                    check("a duplicate label is refused, and says so",
                          "already called" in dupe.get_data(as_text=True))
                    clash = ladder_client.post(
                        "/rates/levels",
                        data={"label": "Another Level", "sort_order": 9999},
                        headers=origin, follow_redirects=True)
                    check("a duplicate sort order is refused, and says so",
                          "already sorts at" in clash.get_data(as_text=True))

                    ladder_client.post(f"/rates/levels/{new_id}/archive",
                                       headers=origin)
                    with scratch.app_context():
                        labels = [l["label"] for l in core_rates.levels()]
                    check("archiving takes a level out of the pickers",
                          "Health Check Level" not in labels)

                    ladder_client.post(f"/rates/levels/{new_id}/delete", headers=origin)
                    with scratch.app_context():
                        remaining = [l["id"] for l in core_rates.list_levels()]
                    check("an unreferenced level can be deleted",
                          new_id not in remaining)

                # A level something references must survive a delete attempt,
                # and the refusal has to say what is holding it.
                with scratch.app_context():
                    referenced = next(
                        (l["id"] for l in core_rates.list_levels()
                         if any(core_rates.level_usage(l["id"]).values())), None)
                if referenced:
                    refusal = ladder_client.post(
                        f"/rates/levels/{referenced}/delete",
                        headers=origin, follow_redirects=True)
                    with scratch.app_context():
                        survived = referenced in [l["id"] for l in core_rates.list_levels()]
                    check("deleting a level in use is refused", survived)
                    check("and the refusal names what still references it",
                          "cannot be deleted" in refusal.get_data(as_text=True))

                # A level change is a money event, not a text edit: it has to
                # write history, and a correction must not read as a promotion
                # or it silently resets somebody's tenure clock.
                with scratch.app_context():
                    target = core_rates.levels()[0]["id"]
                    was = people_models.get_person(subject)["last_promoted_on"]
                    history_before = len(people_models.level_history(subject))

                changed = ladder_client.post(
                    f"/people/{subject}/level/inline",
                    data={"level_id": target, "effective_from": "2026-01-01",
                          "reason": "correction"},
                    headers=origin)
                check("an inline level change succeeds",
                      changed.get_json().get("ok") is True, str(changed.get_json()))

                with scratch.app_context():
                    now = people_models.get_person(subject)
                    history_after = len(people_models.level_history(subject))
                check("it writes a level-history row",
                      history_after > history_before,
                      f"{history_before} → {history_after}")
                check("a correction leaves last_promoted_on alone",
                      now["last_promoted_on"] == was,
                      f"{was} → {now['last_promoted_on']}")

                promoted = ladder_client.post(
                    f"/people/{subject}/level/inline",
                    data={"level_id": target, "effective_from": "2026-02-01",
                          "reason": "promotion"},
                    headers=origin)
                with scratch.app_context():
                    after_promotion = people_models.get_person(subject)
                check("a promotion does move the tenure clock",
                      promoted.get_json().get("ok") is True
                      and after_promotion["last_promoted_on"] == "2026-02-01",
                      str(after_promotion["last_promoted_on"]))

                nonsense = ladder_client.post(
                    f"/people/{subject}/level/inline",
                    data={"level_id": target, "effective_from": "2026-03-01",
                          "reason": "whatever"},
                    headers=origin)
                check("an unknown reason is refused",
                      nonsense.get_json().get("ok") is False,
                      str(nonsense.get_json()))

            with scratch.app_context():
                columns = {row["name"] for row in
                           get_db().execute("PRAGMA table_info(rate_cards)")}
            check("rate_cards records its fiscal year and dates",
                  {"fiscal_year", "effective_from", "effective_to"} <= columns,
                  "missing " + ", ".join(sorted(
                      {"fiscal_year", "effective_from", "effective_to"} - columns)))

            # The card's range decides, but as one window intersected with the
            # entry's — two competing date filters is how a rate resolves to
            # the wrong fiscal year. The entries below are deliberately wider
            # than their cards on both sides.
            with scratch.app_context():
                db = get_db()
                level_id = core_rates.levels()[0]["id"]
                bounded = db.execute(
                    "INSERT INTO rate_cards (name, company, scope, fiscal_year, "
                    "effective_from, effective_to) VALUES "
                    "('Health Check FY26', 'HC', 'standard', 2026, "
                    "'2025-10-01', '2026-09-30')"
                ).lastrowid
                unbounded = db.execute(
                    "INSERT INTO rate_cards (name, company, scope) "
                    "VALUES ('Health Check Undated', 'HC', 'standard')"
                ).lastrowid
                for card in (bounded, unbounded):
                    db.execute(
                        "INSERT INTO rate_card_entries (rate_card_id, level_id, "
                        "bill_rate, cost_rate, effective_from, effective_to) "
                        "VALUES (?, ?, 500, 250, '2020-01-01', '2030-01-01')",
                        (card, level_id),
                    )
                db.commit()

                inside = core_rates.entry_for(bounded, level_id, "2026-01-15")
                before = core_rates.entry_for(bounded, level_id, "2025-06-15")
                after = core_rates.entry_for(bounded, level_id, "2026-12-15")
                # The same date the bounded card refuses. Inside the entry,
                # outside any card range — so only the card's bounds could
                # exclude it, and an undated card has none.
                undated = core_rates.entry_for(unbounded, level_id, "2026-12-15")

            check("a date inside the card prices", inside is not None)
            check("a date before the card does not price, though the entry covers it",
                  before is None)
            check("a date after the card does not price, though the entry covers it",
                  after is None)
            check("a card with no dates is unbounded — nothing repriced by 0028",
                  undated is not None)

            # fiscal_year_start is seeded 10-01, so FY2026 runs 1 Oct 2025 to
            # 30 Sep 2026 — the year is named for the one it ends in.
            with scratch.app_context():
                check("a date in October belongs to the next fiscal year",
                      core_rates.fiscal_year_for("2025-10-01") == 2026,
                      str(core_rates.fiscal_year_for("2025-10-01")))
                check("a date in September belongs to the current one",
                      core_rates.fiscal_year_for("2026-09-30") == 2026,
                      str(core_rates.fiscal_year_for("2026-09-30")))
                check("a fiscal year maps back to its dates",
                      core_rates.dates_for_fiscal_year(2026)
                      == ("2025-10-01", "2026-09-30"),
                      str(core_rates.dates_for_fiscal_year(2026)))

                # The levels screen has to be able to show what a level bills
                # at, and must read it through the same window resolve_rates
                # uses or the screen and the money would disagree.
                # A fresh handle: the connection from the previous app context
                # is closed with it.
                fresh_db = get_db()
                fresh_db.execute(
                    "UPDATE rate_cards SET is_default = 1, company = NULL WHERE id = ?",
                    (bounded,))
                fresh_db.commit()
                priced = core_rates.rate_for_level(level_id, "2026-01-15")
                out_of_year = core_rates.rate_for_level(level_id, "2025-06-15")

            check("a level shows the rate in force on the date",
                  priced is not None and priced["bill_rate"] == 500,
                  str(dict(priced)) if priced else "none")
            check("and shows nothing outside the card's fiscal year",
                  out_of_year is None)
        finally:
            cleanup()
    except Exception as exc:
        check("the roster checks run", False, str(exc))

    # --- 8. vendored assets -------------------------------------------------
    section("Vendored assets")
    vendor = paths.APP_DIR / "static" / "vendor"
    check(
        "Bootstrap 5.3 vendored",
        (vendor / "bootstrap" / "bootstrap.min.css").exists(),
        "run `python vendor_assets.py` — the shell renders without it, "
        "but Bootstrap components will not",
        fatal=False,
    )

    return report()


def report():
    failures = [r for r in results if not r["passed"] and r["fatal"]]
    warnings = [r for r in results if not r["passed"] and not r["fatal"]]

    section("Results")
    for entry in results:
        if entry["passed"]:
            mark = "PASS"
        elif entry["fatal"]:
            mark = "FAIL"
        else:
            mark = "warn"
        detail = f"  ({entry['detail']})" if entry["detail"] else ""
        print(f"  [{mark}] {entry['name']}{detail}")

    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} checks passed, "
          f"{len(failures)} failure(s), {len(warnings)} warning(s)")

    if failures:
        print("\nNot healthy. Fix the failures above before continuing.")
        return 1
    print("\nHealthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
