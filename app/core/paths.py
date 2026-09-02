"""Filesystem locations and the path-confinement guard.

Every path that originates in a request passes through `confine()` before any
filesystem call. See CLAUDE.md rule 7 and docs/NOTES_VAULT_SPEC.md §2.
"""
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]

APP_DIR = APP_ROOT / "app"
DATA_DIR = APP_DIR / "data"
MIGRATIONS_DIR = APP_DIR / "core" / "migrations"

DB_PATH = DATA_DIR / "personalos.db"
BACKUPS_DIR = DATA_DIR / "backups"
INBOX_DIR = DATA_DIR / "inbox"
EXPORTS_DIR = DATA_DIR / "exports"
MODELS_DIR = DATA_DIR / "models"
SECRETS_PATH = DATA_DIR / "secrets.json"

VAULT_ROOT = APP_ROOT / "projects"
TEMPLATE_LIBRARY_ROOT = APP_ROOT / "template_library"
DOCS_ROOT = APP_ROOT / "docs"

# Created on startup if absent. Everything under app/data/ is gitignored.
RUNTIME_DIRS = (
    DATA_DIR,
    BACKUPS_DIR,
    INBOX_DIR,
    EXPORTS_DIR,
    MODELS_DIR,
    VAULT_ROOT,
    TEMPLATE_LIBRARY_ROOT,
)

MAX_SLUG_LENGTH = 60
MAX_PATH_LENGTH = 240  # leaves headroom inside the Windows 260-character limit

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_NON_SLUG = re.compile(r"[^a-z0-9-]+")
_REPEATED_HYPHEN = re.compile(r"-{2,}")

_WINDOWS_RESERVED = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{n}" for n in range(1, 10)]
    + [f"lpt{n}" for n in range(1, 10)]
)


class PathConfinementError(ValueError):
    """A path resolved outside the root it was required to stay within."""


def ensure_runtime_dirs():
    for directory in RUNTIME_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


def confine(root, candidate) -> Path:
    """Resolve `candidate` against `root` and prove it stayed inside.

    `resolve()` runs before the comparison so `..` segments and symlinks are
    collapsed first — checking the unresolved string is the classic way this
    guard gets defeated.

    Backslashes are treated as separators regardless of platform. The
    application runs on Windows, where `..\\..\\etc` is a traversal, but is
    developed and inspected from WSL, where the same string is one legal
    filename. Normalising here means the guard cannot behave differently on
    the two machines that touch the same vault.
    """
    root_resolved = Path(root).resolve()

    normalised = str(candidate).replace("\\", "/")
    if any(part == ".." for part in normalised.split("/")):
        raise PathConfinementError(f"path contains a parent segment: {candidate!r}")

    target = Path(normalised)
    if target.is_absolute():
        resolved = target.resolve()
    else:
        resolved = (root_resolved / target).resolve()

    if resolved != root_resolved and not resolved.is_relative_to(root_resolved):
        raise PathConfinementError(
            f"path escapes its root: {candidate!r} resolved outside {root_resolved}"
        )
    if len(str(resolved)) > MAX_PATH_LENGTH:
        raise PathConfinementError(
            f"path is {len(str(resolved))} characters, over the {MAX_PATH_LENGTH} limit"
        )
    return resolved


def safe_slug(name: str, taken=(), max_length: int = MAX_SLUG_LENGTH) -> str:
    """Folder-safe slug per docs/NOTES_VAULT_SPEC.md §2.

    `taken` is the set of sibling slugs already in use; a collision appends
    -2, -3, … rather than silently overwriting somebody's folder.
    """
    slug = _ILLEGAL_CHARS.sub("", (name or "").strip().lower())
    slug = slug.replace("_", "-").replace(" ", "-")
    slug = _NON_SLUG.sub("-", slug)
    slug = _REPEATED_HYPHEN.sub("-", slug).strip("-. ")
    slug = slug[:max_length].strip("-. ")

    if not slug:
        slug = "untitled"
    # Dots are already gone by this point, so "CON", "CON.md" and "con.txt" all
    # arrive here as bare words and are caught by the same comparison.
    if slug in _WINDOWS_RESERVED:
        slug = f"{slug}-1"

    taken = {t.lower() for t in taken}
    if slug not in taken:
        return slug
    stem = slug[: max_length - 3].strip("-. ") or "untitled"
    for n in range(2, 1000):
        candidate = f"{stem}-{n}"
        if candidate not in taken:
            return candidate
    raise ValueError(f"could not find a free slug for {name!r}")
