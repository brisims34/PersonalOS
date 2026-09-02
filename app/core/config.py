"""Application settings, dropdown vocabularies and secrets.

Settings live in `app_settings` and are read many times per request, so they
are cached on `g` for the life of the request and invalidated on write.

Secrets live in `app/data/secrets.json`, which is gitignored. They are never
logged and never rendered — `mask()` is the only way one reaches a template.
"""
import json

from app.core import paths
from app.core.database import get_db

_TRUE = frozenset(["1", "true", "yes", "on"])

# Anything whose name matches must never appear in a log line, an activity
# detail blob, or a rendered page.
SENSITIVE_KEY_HINTS = ("password", "secret", "token", "api_key", "apikey", "credential")


class SettingError(KeyError):
    pass


def _cache():
    from flask import g

    if not hasattr(g, "_settings_cache"):
        rows = get_db().execute("SELECT key, value, value_type FROM app_settings").fetchall()
        g._settings_cache = {r["key"]: (r["value"], r["value_type"]) for r in rows}
    return g._settings_cache


def _invalidate():
    from flask import g

    if hasattr(g, "_settings_cache"):
        del g._settings_cache


def get_setting(key, default=None):
    entry = _cache().get(key)
    if entry is None:
        return default
    value = entry[0]
    return default if value is None else value


def get_int(key, default=None):
    raw = get_setting(key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_float(key, default=None):
    raw = get_setting(key)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def get_bool(key, default=False):
    raw = get_setting(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUE


def get_json(key, default=None):
    raw = get_setting(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def all_settings():
    return get_db().execute(
        "SELECT key, value, value_type, description, updated_at "
        "FROM app_settings ORDER BY key"
    ).fetchall()


def set_setting(key, value, value_type=None):
    """Upsert a setting. Callers are responsible for the activity log entry."""
    db = get_db()
    existing = db.execute(
        "SELECT value_type FROM app_settings WHERE key = ?", (key,)
    ).fetchone()
    resolved_type = value_type or (existing["value_type"] if existing else "string")

    if isinstance(value, bool):
        stored = "1" if value else "0"
    elif isinstance(value, (dict, list)):
        stored = json.dumps(value)
    elif value is None:
        stored = None
    else:
        stored = str(value)

    db.execute(
        "INSERT INTO app_settings (key, value, value_type, updated_at) "
        "VALUES (?, ?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET "
        "value = excluded.value, value_type = excluded.value_type, "
        "updated_at = excluded.updated_at",
        (key, stored, resolved_type),
    )
    db.commit()
    _invalidate()
    return stored


# --- dropdown vocabularies --------------------------------------------------


def options(option_set, include_inactive=False):
    sql = "SELECT value, label, sort_order, is_active FROM config_options WHERE option_set = ?"
    if not include_inactive:
        sql += " AND is_active = 1"
    sql += " ORDER BY sort_order, label"
    return get_db().execute(sql, (option_set,)).fetchall()


def option_label(option_set, value, default=None):
    """Display text for a stored token — 'available' renders as 'Active & Ready'."""
    if value is None:
        return default
    row = get_db().execute(
        "SELECT label FROM config_options WHERE option_set = ? AND value = ?",
        (option_set, value),
    ).fetchone()
    return row["label"] if row else (default if default is not None else value)


# --- secrets ----------------------------------------------------------------


def load_secrets():
    if not paths.SECRETS_PATH.exists():
        return {}
    try:
        return json.loads(paths.SECRETS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A malformed secrets file must not take the application down; the
        # features that need it report themselves unconfigured instead.
        return {}


def get_secret(name, default=None):
    return load_secrets().get(name, default)


def has_secret(name):
    return bool(load_secrets().get(name))


def mask(value):
    """Render-safe form of a secret: last four characters only."""
    if not value:
        return ""
    text = str(value)
    return "•" * max(len(text) - 4, 4) + text[-4:] if len(text) > 4 else "•" * len(text)


def is_sensitive_key(name):
    lowered = str(name).lower()
    return any(hint in lowered for hint in SENSITIVE_KEY_HINTS)
