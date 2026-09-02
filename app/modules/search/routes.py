"""Full-text search across the vault, and record lookup alongside it.

FTS5 for note bodies; a plain LIKE sweep for records. Semantic search joins
this at Phase 21 and merges with these results rather than replacing them.
"""
from flask import Blueprint, render_template, request

from app.core import notes_index
from app.core.database import get_db
from app.core.module_registry import guard_blueprint

bp = Blueprint("search", __name__, url_prefix="/search")
guard_blueprint(bp, "search")


def _records(query, limit=10):
    """Matching records, grouped by type, so search is not notes-only."""
    if not query:
        return {}
    db = get_db()
    like = f"%{query}%"
    return {
        "Projects": db.execute(
            "SELECT id, name AS label, client_org AS detail FROM projects "
            "WHERE archived_at IS NULL AND (name LIKE ? OR client_org LIKE ? OR code LIKE ?) "
            "ORDER BY name LIMIT ?",
            (like, like, like, limit),
        ).fetchall(),
        "Contacts": db.execute(
            "SELECT id, full_name AS label, job_title AS detail FROM people "
            "WHERE archived_at IS NULL AND (full_name LIKE ? OR email LIKE ? OR job_title LIKE ?) "
            "ORDER BY full_name LIMIT ?",
            (like, like, like, limit),
        ).fetchall(),
        "Charge codes": db.execute(
            "SELECT id, code AS label, name AS detail FROM charge_codes "
            "WHERE archived_at IS NULL AND (code LIKE ? OR name LIKE ?) "
            "ORDER BY code LIMIT ?",
            (like, like, limit),
        ).fetchall(),
        "Tasks": db.execute(
            "SELECT id, title AS label, status AS detail FROM tasks "
            "WHERE archived_at IS NULL AND title LIKE ? ORDER BY due_date LIMIT ?",
            (like, limit),
        ).fetchall(),
    }


URL_FOR_TYPE = {
    "Projects": "/projects/{}",
    "Contacts": "/people/{}",
    "Charge codes": "/charge-codes/{}",
    "Tasks": "/tasks/{}",
}


@bp.get("/")
def index():
    query = (request.args.get("q") or "").strip()
    return render_template(
        "modules/search/index.html",
        query=query,
        notes=notes_index.search_notes(query) if query else [],
        records=_records(query),
        url_patterns=URL_FOR_TYPE,
        stats=notes_index.stats(),
        crumbs=["Search"],
    )
