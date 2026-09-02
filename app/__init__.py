"""Application factory.

`create_app()` is the only way the app is constructed — run.py, health_check.py
and any future script all go through it, so there is one definition of what a
configured PersonalOS is.

Flask is imported inside the functions that need it rather than at module
level. Importing `app.core.paths` pulls this module in as the parent package,
and `apply_migrations.py` has to keep working when the environment is only
half-installed — a half-finished `pip install` is exactly when you most need
the migration and diagnostic tooling to still run.
"""
import json
import logging
import secrets as _secrets
from urllib.parse import urlparse

from app.core import backup, config, database, formatting, paths
from app.core.database import apply_migrations
from app.core.module_registry import nav_tree

# Every module that has a blueprint today. Later phases append here.
# Registration order is irrelevant; whether a module *responds* is decided by
# `module_registry.is_enabled`, checked on every request (CLAUDE.md rule 14).
MODULE_BLUEPRINTS = (
    "app.modules.command_center",
    "app.modules.tasks",
    "app.modules.portfolios",
    "app.modules.projects",
    "app.modules.charge_codes",
    "app.modules.people",
    "app.modules.org_chart",
    "app.modules.rates",
    "app.modules.notes",
    "app.modules.search",
    "app.modules.activity",
)

SECURITY_HEADERS = {
    # No inline scripts anywhere — it keeps business logic on the server and
    # makes "no client-side templating of business data" enforceable rather
    # than aspirational. Inline *styles* are permitted because capacity and
    # coverage bars need a computed width.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def create_app(config_overrides=None, run_migrations=True):
    from flask import Flask

    from app.core.shell import shell_bp

    app = Flask(__name__)
    app.config.update(
        DATABASE_PATH=str(paths.DB_PATH),
        MIGRATIONS_DIR=str(paths.MIGRATIONS_DIR),
        SECRET_KEY=_load_or_create_secret_key(),
        MAX_CONTENT_LENGTH=64 * 1024 * 1024,  # timesheet and template workbooks
        SEND_FILE_MAX_AGE_DEFAULT=0,
    )
    # Flask 3 moved this off app.config; JSON_SORT_KEYS there is silently ignored.
    app.json.sort_keys = False

    if config_overrides:
        app.config.update(config_overrides)

    paths.ensure_runtime_dirs()

    # Bootstrap is vendored rather than loaded from a CDN, so it may legitimately
    # be absent until `vendor_assets.py` has run. Checked once here rather than
    # per request; personalos.css styles the shell either way.
    vendor = paths.APP_DIR / "static" / "vendor"
    app.config["HAS_BOOTSTRAP"] = (vendor / "bootstrap" / "bootstrap.min.css").exists()
    app.config["HAS_BOOTSTRAP_ICONS"] = (
        vendor / "bootstrap-icons" / "bootstrap-icons.css"
    ).exists()

    if run_migrations:
        summary = apply_migrations(
            app.config["DATABASE_PATH"],
            app.config["MIGRATIONS_DIR"],
            log=app.logger.info,
        )
        if summary["applied"]:
            app.logger.info(
                "Applied %d migration(s): %s",
                len(summary["applied"]),
                ", ".join(summary["applied"]),
            )

    database.init_app(app)
    formatting.register(app)

    # Vault roots carry absolute paths, which depend on where the tree is
    # installed — so they are reconciled at startup rather than seeded in a
    # migration that cannot know whether it is on WSL or Windows.
    with app.app_context():
        from app.core.notes_index import ensure_roots

        try:
            ensure_roots()
        except Exception:
            app.logger.exception("Could not reconcile vault roots")

    app.register_blueprint(shell_bp)
    for module_path in MODULE_BLUEPRINTS:
        module = __import__(module_path, fromlist=["bp"])
        app.register_blueprint(module.bp)

    _register_request_hooks(app)
    _register_context(app)
    _register_error_handlers(app)

    return app


def _load_or_create_secret_key():
    """Read the session key from secrets.json, creating one on first run.

    Generated rather than hard-coded so the file that must never be committed
    is the only place it exists.
    """
    existing = config.load_secrets()
    key = existing.get("flask_secret_key")
    if key:
        return key

    key = _secrets.token_hex(32)
    existing["flask_secret_key"] = key
    paths.SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    paths.SECRETS_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    try:
        paths.SECRETS_PATH.chmod(0o600)
    except OSError:
        pass  # Windows ACLs; the file is inside the gitignored data directory
    return key


def _register_request_hooks(app):
    from flask import render_template, request

    @app.before_request
    def _reject_cross_origin_writes():
        """Same-origin check on every state change.

        The app has no login because it is single-user on localhost, which
        means any page in the browser could otherwise POST to it. Comparing
        the Origin against the request host costs nothing and closes that.
        """
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin:
            return None  # curl and the maintenance scripts send neither
        if urlparse(origin).netloc != request.host:
            app.logger.warning("Rejected cross-origin %s to %s", request.method, request.path)
            return render_template("errors/403.html"), 403
        return None

    @app.after_request
    def _security_headers(response):
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def _register_context(app):
    from flask import request

    @app.context_processor
    def _inject_chrome():
        theme = config.get_setting("theme", "dark")
        blueprint = request.blueprint or ""
        return {
            "app_name": config.get_setting("app_name", "PersonalOS"),
            "theme": theme if theme in ("dark", "light") else "dark",
            "nav_groups": nav_tree(),
            "current_module": blueprint,
            "sidebar_collapsed": config.get_bool("sidebar_collapsed", False),
            "backup_age_hours": backup.backup_age_hours(),
            "has_bootstrap": app.config["HAS_BOOTSTRAP"],
            "has_bootstrap_icons": app.config["HAS_BOOTSTRAP_ICONS"],
        }

    @app.template_global()
    def breadcrumbs(crumbs):
        """Normalise a view's `crumbs` list.

        Accepts ('Work', '/portfolios') pairs and bare strings interchangeably,
        so a view never has to build dictionaries by hand.
        """
        trail = []
        for crumb in crumbs or []:
            if crumb is None:
                continue
            if isinstance(crumb, (tuple, list)):
                trail.append({"label": crumb[0], "url": crumb[1] if len(crumb) > 1 else None})
            else:
                trail.append({"label": str(crumb), "url": None})
        return trail


def _register_error_handlers(app):
    from flask import render_template, request

    @app.errorhandler(404)
    def _not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def _forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def _server_error(error):
        app.logger.exception("Unhandled error on %s", request.path)
        return render_template("errors/500.html", error=error), 500


def configure_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
