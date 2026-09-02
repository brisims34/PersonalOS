"""Apply pending schema migrations: backup, migrate, verify.

    python apply_migrations.py            show the plan, then ask
    python apply_migrations.py --yes      no prompt
    python apply_migrations.py --dry-run  show the plan and stop

The migration runner takes the backup itself and refuses to proceed if it
fails (CLAUDE.md rule 5). This script exists so migrating is a deliberate act
you can run before starting the app, rather than something that happens to you
on startup.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402
from app.core.backup import list_backups  # noqa: E402
from app.core.database import (  # noqa: E402
    MigrationError,
    apply_migrations,
    connect,
    discover_migrations,
    pending_migrations,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply pending PersonalOS migrations.")
    parser.add_argument("--yes", action="store_true", help="do not prompt")
    parser.add_argument("--dry-run", action="store_true", help="show the plan and stop")
    parser.add_argument("--no-backup", action="store_true",
                        help="skip the pre-migration backup (development only)")
    args = parser.parse_args(argv)

    # The backup directory has to exist before the runner tries to write into
    # it, and a first run against an empty checkout has nothing at all.
    paths.ensure_runtime_dirs()

    print(f"Database:   {paths.DB_PATH}")
    print(f"Migrations: {paths.MIGRATIONS_DIR}")

    if not paths.DB_PATH.exists():
        print("\nNo database yet — it will be created and every migration applied.")
        current, pending = 0, discover_migrations(paths.MIGRATIONS_DIR)
    else:
        conn = connect(paths.DB_PATH)
        try:
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            pending = pending_migrations(conn, paths.MIGRATIONS_DIR)
        finally:
            conn.close()

    print(f"\nCurrent schema version: {current}")

    if not pending:
        print("Nothing to apply — the database is up to date.")
        return 0

    print(f"\nThis will apply {len(pending)} migration(s):")
    for migration in pending:
        print(f"    {migration.filename}")
    print(f"\nSchema version {current} → {pending[-1].version}")

    if not args.no_backup and current > 0:
        print(f"A backup is written to {paths.BACKUPS_DIR} first.")
        print("If the backup fails, nothing is applied.")

    if args.dry_run:
        print("\nDry run — nothing was changed.")
        return 0

    if not args.yes:
        answer = input("\nProceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled. Nothing was changed.")
            return 1

    print()
    try:
        summary = apply_migrations(
            paths.DB_PATH,
            paths.MIGRATIONS_DIR,
            backup=not args.no_backup,
            log=lambda message: print(f"  {message}"),
        )
    except MigrationError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1

    print(
        f"\nApplied {len(summary['applied'])} migration(s). "
        f"Schema version {summary['version_from']} → {summary['version_to']}."
    )

    conn = sqlite3.connect(paths.DB_PATH)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
    finally:
        conn.close()

    print(f"Integrity: {integrity} · foreign key violations: {len(violations)} · tables: {tables}")

    kept = list_backups()
    if kept:
        print(f"Most recent backup: {kept[0].name}")

    if integrity != "ok" or violations:
        print("\nThe database reports a problem. Restore the backup above.", file=sys.stderr)
        return 1

    print("\nRun `python health_check.py` to confirm the application still starts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
