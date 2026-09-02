"""Database backups.

Uses SQLite's online backup API rather than a file copy: it is safe while the
database is open, and it checkpoints WAL content into the copy. A file copy of
a WAL-mode database can miss committed transactions still sitting in the -wal
file, which produces a backup that restores to the wrong state — the worst
possible failure for a backup.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from app.core import paths

FILENAME_FORMAT = "personalos-{stamp}-{reason}.db"
_STAMP = "%Y%m%d-%H%M%S"


class BackupError(RuntimeError):
    """A backup was requested and could not be produced."""


def create_backup(reason: str, db_path=None, backups_dir=None) -> Path:
    """Write a point-in-time copy and return its path. Raises on any failure.

    Callers must not swallow BackupError. Migration is gated on this
    succeeding (CLAUDE.md rule 5).
    """
    db_path = Path(db_path or paths.DB_PATH)
    backups_dir = Path(backups_dir or paths.BACKUPS_DIR)
    safe_reason = "".join(c if c.isalnum() or c == "-" else "-" for c in reason)[:40]

    if not db_path.exists():
        raise BackupError(f"nothing to back up — no database at {db_path}")

    try:
        backups_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"cannot create backup directory {backups_dir}: {exc}") from exc

    target = backups_dir / FILENAME_FORMAT.format(
        stamp=datetime.now().strftime(_STAMP), reason=safe_reason or "manual"
    )

    source = dest = None
    try:
        source = sqlite3.connect(db_path)
        dest = sqlite3.connect(target)
        source.backup(dest)
        dest.commit()
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"backup to {target} failed: {exc}") from exc
    finally:
        for conn in (dest, source):
            if conn is not None:
                conn.close()

    # An empty or missing file means the backup silently did nothing.
    if not target.exists() or target.stat().st_size == 0:
        raise BackupError(f"backup at {target} is missing or empty")

    return target


def list_backups(backups_dir=None):
    backups_dir = Path(backups_dir or paths.BACKUPS_DIR)
    if not backups_dir.exists():
        return []
    files = [p for p in backups_dir.glob("personalos-*.db") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def latest_backup(backups_dir=None):
    found = list_backups(backups_dir)
    return found[0] if found else None


def backup_age_hours(backups_dir=None):
    """Hours since the most recent backup, or None if there has never been one."""
    newest = latest_backup(backups_dir)
    if newest is None:
        return None
    delta = datetime.now() - datetime.fromtimestamp(newest.stat().st_mtime)
    return delta.total_seconds() / 3600.0


def prune_backups(keep: int, backups_dir=None):
    """Delete all but the newest `keep` backups. Returns the paths removed."""
    if keep < 1:
        raise ValueError("keep must be at least 1 — pruning to zero backups is never correct")
    removed = []
    for stale in list_backups(backups_dir)[keep:]:
        try:
            stale.unlink()
            removed.append(stale)
        except OSError:
            # A locked or already-removed file is not worth failing a request over.
            pass
    return removed
