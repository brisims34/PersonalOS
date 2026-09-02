"""Which modules exist, which are on, and the sidebar they generate.

Every route in every module checks `is_module_enabled()` and aborts 404 when
its module is off (CLAUDE.md rule 14). A module registers as disabled until
its build phase lands, so the sidebar only ever shows what works.
"""
from functools import wraps

from app.core.database import get_db

# Rendered in this order. A group with no enabled modules is not rendered.
NAV_GROUP_ORDER = (
    "Command",
    "Work",
    "Governance",
    "Money",
    "Resources",
    "Knowledge",
    "People",
    "Intake",
    "System",
)


def _cache():
    from flask import g

    if not hasattr(g, "_module_cache"):
        rows = get_db().execute(
            "SELECT module_key, label, nav_group, url_prefix, icon, is_enabled, sort_order "
            "FROM module_registry ORDER BY sort_order, label"
        ).fetchall()
        g._module_cache = {r["module_key"]: r for r in rows}
    return g._module_cache


def _invalidate():
    from flask import g

    if hasattr(g, "_module_cache"):
        del g._module_cache


def all_modules(include_disabled=True):
    modules = list(_cache().values())
    if include_disabled:
        return modules
    return [m for m in modules if m["is_enabled"]]


def get_module(module_key):
    return _cache().get(module_key)


def is_module_enabled(module_key):
    module = _cache().get(module_key)
    return bool(module and module["is_enabled"])


def set_enabled(module_key, enabled):
    db = get_db()
    cursor = db.execute(
        "UPDATE module_registry SET is_enabled = ? WHERE module_key = ?",
        (1 if enabled else 0, module_key),
    )
    db.commit()
    _invalidate()
    return cursor.rowcount == 1


def nav_tree():
    """Enabled modules grouped for the sidebar, in NAV_GROUP_ORDER."""
    grouped = {}
    for module in all_modules(include_disabled=False):
        grouped.setdefault(module["nav_group"], []).append(module)

    ordered = [(name, grouped.pop(name)) for name in NAV_GROUP_ORDER if name in grouped]
    # A group added later without touching this constant still renders, at the
    # end, rather than silently disappearing.
    ordered.extend(sorted(grouped.items()))
    return ordered


def require_module(module_key):
    """Guard every route in a module's blueprint.

    Registered as a `before_request` on the blueprint rather than decorating
    each view, so a new route cannot be added without the check.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            from flask import abort

            if not is_module_enabled(module_key):
                abort(404)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def guard_blueprint(blueprint, module_key):
    """Attach the enabled check to every route on a blueprint."""

    @blueprint.before_request
    def _check_module_enabled():
        from flask import abort

        if not is_module_enabled(module_key):
            abort(404)
