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
    except ImportError as exc:
        check("create_app() succeeds", False, f"{exc} — install requirements.txt")
    except Exception as exc:
        check("create_app() succeeds", False, str(exc))

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
