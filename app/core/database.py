"""SQLite access and the migration runner.

Two layers, deliberately separated:

* Module-level functions (`connect`, `apply_migrations`, …) take an explicit
  path and know nothing about Flask, so `apply_migrations.py` and
  `health_check.py` can use them with no application context.
* `get_db()` / `init_app()` bind one connection per request via Flask's `g`.

Never open a second connection inside a request.
"""
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core import paths
from app.core.backup import BackupError, create_backup

MIGRATION_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

# Created by the runner, not by a migration file — it has to exist before the
# first migration can be recorded. See docs/DATABASE_SCHEMA.md §0001.
SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    migration    TEXT NOT NULL UNIQUE,
    applied_at   DATETIME NOT NULL DEFAULT (datetime('now')),
    version_from INTEGER NOT NULL DEFAULT 0,
    version_to   INTEGER NOT NULL DEFAULT 0
);
"""


class MigrationError(RuntimeError):
    """A migration could not be applied. The database is unchanged."""


class Migration:
    __slots__ = ("version", "name", "path")

    def __init__(self, version, name, path):
        self.version = version
        self.name = name
        self.path = path

    @property
    def filename(self):
        return self.path.name

    def __repr__(self):
        return f"<Migration {self.filename}>"


# --- connection -------------------------------------------------------------


def connect(db_path=None) -> sqlite3.Connection:
    db_path = Path(db_path or paths.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    # NORMAL is safe under WAL and avoids an fsync per commit, which matters
    # because imports write thousands of rows.
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def schema_version(conn) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


# --- migrations -------------------------------------------------------------


def discover_migrations(migrations_dir=None):
    """Every well-named migration on disk, ordered by version."""
    migrations_dir = Path(migrations_dir or paths.MIGRATIONS_DIR)
    if not migrations_dir.exists():
        raise MigrationError(f"migrations directory not found: {migrations_dir}")

    found, seen = [], {}
    for path in sorted(migrations_dir.glob("*.sql")):
        match = MIGRATION_FILENAME.match(path.name)
        if not match:
            raise MigrationError(
                f"{path.name} does not match NNNN_lowercase_name.sql — "
                "rename it or move it out of the migrations directory"
            )
        version = int(match.group(1))
        if version in seen:
            raise MigrationError(
                f"two migrations claim version {version:04d}: "
                f"{seen[version]} and {path.name}"
            )
        seen[version] = path.name
        found.append(Migration(version, match.group(2), path))

    return sorted(found, key=lambda m: m.version)


def pending_migrations(conn, migrations_dir=None):
    current = schema_version(conn)
    return [m for m in discover_migrations(migrations_dir) if m.version > current]


def apply_migrations(db_path=None, migrations_dir=None, *, backup=True, log=None):
    """Bring the database up to the highest migration on disk.

    Returns a summary dict. Raises MigrationError without changing anything if
    a backup was required and could not be taken (CLAUDE.md rule 5).
    """
    db_path = Path(db_path or paths.DB_PATH)
    log = log or (lambda _message: None)
    fresh = not db_path.exists()

    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA_MIGRATIONS_DDL)
        start_version = schema_version(conn)
        pending = pending_migrations(conn, migrations_dir)

        if not pending:
            return {
                "applied": [],
                "version_from": start_version,
                "version_to": start_version,
                "backup": None,
                "fresh": fresh,
            }

        # A brand-new database holds no data, so there is nothing to lose and
        # nothing to back up. Any existing schema means real rows might exist.
        backup_path = None
        if backup and start_version > 0:
            try:
                backup_path = create_backup(f"premigration-v{start_version:04d}", db_path)
                log(f"Backup written: {backup_path}")
            except BackupError as exc:
                raise MigrationError(
                    f"Migration aborted — the pre-migration backup failed: {exc}\n"
                    "No migration has been applied and the database is unchanged. "
                    "Fix the backup location and try again."
                ) from exc

        applied = []
        for migration in pending:
            log(f"Applying {migration.filename} …")
            _apply_one(conn, migration, schema_version(conn))
            applied.append(migration.filename)

        end_version = schema_version(conn)
        log(f"Schema version {start_version} → {end_version}")
        return {
            "applied": applied,
            "version_from": start_version,
            "version_to": end_version,
            "backup": str(backup_path) if backup_path else None,
            "fresh": fresh,
        }
    finally:
        conn.close()


def _apply_one(conn, migration, version_from):
    sql = migration.path.read_text(encoding="utf-8")

    # Comments mentioning BEGIN or COMMIT are fine — and common, since every
    # migration file says the runner supplies them. Only statements count.
    uncommented = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    uncommented = re.sub(r"--[^\n]*", " ", uncommented)
    # `BEGIN ... END` inside a trigger body is legitimate, so only a BEGIN that
    # starts a transaction counts.
    if re.search(r"\bBEGIN\s+TRANSACTION\b|\bBEGIN\s*;|\bCOMMIT\b|\bROLLBACK\b",
                 uncommented, re.IGNORECASE):
        raise MigrationError(
            f"{migration.filename} contains its own transaction control; "
            "the runner supplies BEGIN and COMMIT"
        )

    # The filename is interpolated rather than bound because executescript()
    # takes no parameters. It is safe by construction: MIGRATION_FILENAME has
    # already restricted it to digits, lowercase letters and underscores, so it
    # cannot carry a quote. This is a developer constant read off disk, not
    # request data (CLAUDE.md rule 2).
    script = (
        "BEGIN;\n"
        f"{sql}\n"
        f"PRAGMA user_version = {migration.version:d};\n"
        "INSERT INTO schema_migrations (migration, version_from, version_to) "
        f"VALUES ('{migration.filename}', {version_from:d}, {migration.version:d});\n"
        "COMMIT;"
    )
    try:
        conn.executescript(script)
    except sqlite3.Error as exc:
        conn.rollback()
        raise MigrationError(f"{migration.filename} failed and was rolled back: {exc}") from exc


# --- Flask binding ----------------------------------------------------------


def get_db():
    from flask import current_app, g

    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exception=None):
    from flask import g

    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def transaction():
    """Wrap several statements so a half-finished mutation cannot be committed."""
    conn = get_db()
    try:
        conn.execute("BEGIN")
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
