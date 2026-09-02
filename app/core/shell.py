"""Application chrome endpoints.

These belong to no module and are deliberately not guarded by the module
registry — the theme toggle and the command palette must keep working no
matter which modules are switched off.
"""
from flask import Blueprint, jsonify, redirect, request, url_for

from app.core import activity, config
from app.core.module_registry import all_modules, nav_tree

shell_bp = Blueprint("shell", __name__, url_prefix="/shell")

# Bound to `g` + letter in static/js/app.js. Only the targets whose module is
# enabled are sent to the client, so a hotkey never lands on a 404.
GO_TO_KEYS = {
    "c": "command_center",
    "p": "projects",
    "s": "staffing_board",
    "t": "tasks",
    "n": "notes",
    "a": "activity",
}


@shell_bp.post("/theme")
def set_theme():
    requested = request.form.get("theme", "").strip().lower()
    if requested not in ("dark", "light"):
        requested = "light" if config.get_setting("theme", "dark") == "dark" else "dark"
    config.set_setting("theme", requested, "string")
    return redirect(request.form.get("next") or request.referrer or url_for("command_center.index"))


@shell_bp.post("/sidebar")
def set_sidebar():
    collapsed = request.form.get("collapsed") == "1"
    config.set_setting("sidebar_collapsed", collapsed, "bool")
    return ("", 204)


@shell_bp.get("/palette.json")
def palette_index():
    """Everything the command palette can reach right now.

    Each phase adds its records to `entries` through this one endpoint, so the
    palette never needs to know which modules exist.
    """
    modules = {m["module_key"]: m for m in all_modules(include_disabled=False)}

    navigation = [
        {
            "type": "nav",
            "label": module["label"],
            "group": module["nav_group"],
            "url": module["url_prefix"],
            "key": module["module_key"],
        }
        for _group, members in nav_tree()
        for module in members
    ]

    commands = []
    if "activity" in modules:
        commands.append(
            {"type": "command", "label": "View activity log", "url": "/activity", "verb": "go"}
        )

    goto = {
        key: modules[module_key]["url_prefix"]
        for key, module_key in GO_TO_KEYS.items()
        if module_key in modules
    }

    return jsonify(
        {
            "navigation": navigation,
            "commands": commands,
            "entries": [],  # records, contributed by later phases
            "goto": goto,
        }
    )


@shell_bp.get("/activity.json")
def recent_activity():
    """Small feed used by the topbar; kept separate so the page never blocks on it."""
    rows = activity.recent(limit=10)
    return jsonify(
        [
            {
                "id": r["id"],
                "summary": r["summary"],
                "action": r["action"],
                "entity_type": r["entity_type"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    )
