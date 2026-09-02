"""Contact seed import from a directory extract such as AASppl.xlsx.

**This is a one-time load, run by hand.** Nothing here executes at startup;
the application never reads a spreadsheet unless you ask it to on
`/people/import`. Two independent things make a repeat load harmless:

1. `import_batches` has `UNIQUE (batch_type, file_sha256)`, and the ledger row
   is written in the same transaction as the people rows — so loading the same
   file twice is refused by the database and rolls back entirely.
2. `people.email` is unique, so even a *different* file containing the same
   people updates rather than duplicates them.

Label-driven, deduplicated on email, preview before commit, and safe to re-run
against a genuinely refreshed extract.

The two columns that are empty in the seed file — Home Phone and Manager Email
— import without complaint. Manager Email is precisely what GAL enrichment
fills in later.
"""
import sqlite3

from app.core.database import get_db
from app.core.xlsx import file_sha256, read_sheet

# Spreadsheet header → conformed snake_case column. Several spellings are
# accepted per field because directory exports are not consistent between runs.
COLUMN_MAP = {
    "external_ref":   ["ID", "Person ID", "Employee ID"],
    "company":        ["Company", "Legal Entity"],
    "last_name":      ["Last Name", "Surname"],
    "first_name":     ["First Name", "Given Name"],
    "email":          ["Email Address", "Email", "Primary SMTP Address"],
    "job_title":      ["Job Title", "Title"],
    "department":     ["Department", "Dept"],
    "business_phone": ["Business Phone", "Work Phone", "Office Phone"],
    "home_phone":     ["Home Phone"],
    "mobile_phone":   ["Mobile Phone", "Mobile", "Cell Phone"],
    "city":           ["City"],
    "state_province": ["State_Province", "State", "State/Province", "Province"],
    "manager_email":  ["Manager Email", "Manager", "Manager SMTP"],
}

REQUIRED = ("first_name", "last_name", "email")

# Fields a refreshed extract is allowed to update on an existing person. Notes,
# strengths, development areas and relationship type are yours — an import must
# never overwrite what you wrote about someone.
UPDATABLE = (
    "external_ref", "company", "department", "job_title", "business_phone",
    "home_phone", "mobile_phone", "city", "state_province", "manager_email",
)


BATCH_TYPE = "people"


def previous_batch(digest):
    """The committed batch for this exact file, if there is one.

    `import_batches` has UNIQUE (batch_type, file_sha256), so this is the
    durable answer to "has this already been loaded" — not an inference from
    the activity log, and not something the importer has to remember.
    """
    return get_db().execute(
        "SELECT * FROM import_batches WHERE batch_type = ? AND file_sha256 = ?",
        (BATCH_TYPE, digest),
    ).fetchone()


def history(limit=20):
    return get_db().execute(
        "SELECT * FROM import_batches WHERE batch_type = ? "
        "ORDER BY imported_at DESC LIMIT ?",
        (BATCH_TYPE, limit),
    ).fetchall()


def preview(path):
    """Read the file and work out what committing would do. Writes nothing."""
    records, report = read_sheet(path, COLUMN_MAP, required=REQUIRED)
    digest = file_sha256(path)

    db = get_db()
    prior = previous_batch(digest)

    existing = {
        r["email"].lower(): r
        for r in db.execute(
            "SELECT id, email, job_title, company, department, business_phone, "
            "       mobile_phone, home_phone, city, state_province, manager_email, external_ref "
            "FROM people WHERE email IS NOT NULL"
        ).fetchall()
    }
    titles = {r["job_title"] for r in db.execute("SELECT job_title FROM job_title_map")}

    to_create, to_update, unchanged, problems = [], [], [], []
    within_file = set()

    for line, record in enumerate(records, start=report["header_row"] + 1):
        email = (record.get("email") or "").strip().lower()
        if not email:
            problems.append({"line": line, "issue": "no email address",
                             "detail": _label(record)})
            continue
        if "@" not in email:
            problems.append({"line": line, "issue": "email is not an address",
                             "detail": email})
            continue
        if email in within_file:
            problems.append({"line": line, "issue": "duplicate inside the file",
                             "detail": email})
            continue
        within_file.add(email)

        record["email"] = email
        current = existing.get(email)
        if current is None:
            to_create.append(record)
            continue

        changes = {
            field: record.get(field)
            for field in UPDATABLE
            if record.get(field) is not None
            and str(record.get(field)) != str(current[field] or "")
        }
        if changes:
            to_update.append({"person_id": current["id"], "email": email,
                              "changes": changes, "record": record})
        else:
            unchanged.append(email)

    unmapped_titles = sorted(
        {r["job_title"] for r in records if r.get("job_title") and r["job_title"] not in titles}
    )

    return {
        "path": str(path),
        "file_name": str(path).rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        "sha256": digest,
        "prior": prior,
        "already_imported": prior is not None and prior["status"] == "committed",
        "report": report,
        "create": to_create,
        "update": to_update,
        "unchanged": unchanged,
        "problems": problems,
        "unmapped_titles": unmapped_titles,
        "counts": {
            "read": len(records),
            "create": len(to_create),
            "update": len(to_update),
            "unchanged": len(unchanged),
            "problems": len(problems),
        },
    }


def _label(record):
    parts = [record.get("first_name"), record.get("last_name")]
    return " ".join(p for p in parts if p) or "(blank row)"


class AlreadyImported(RuntimeError):
    """This exact file has already been loaded. Nothing was written."""


def commit(plan, import_source="excel_seed", apply_titles=True):
    """Write the previewed plan, and the ledger row, in one transaction.

    Takes the plan the user actually saw rather than re-reading the file, so
    what gets written is what the preview promised.

    The `import_batches` insert is inside the same transaction as the people
    rows. If the file was already loaded, the UNIQUE constraint fires and the
    whole thing rolls back — so "one-time" is enforced by the database rather
    than by a check that could be skipped.
    """
    import json

    from app.modules.people import models

    db = get_db()
    created = updated = 0
    try:
        db.execute("BEGIN")

        db.execute(
            "INSERT INTO import_batches (batch_type, file_name, file_sha256, rows_read, "
            "rows_imported, rows_skipped, status, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?, 'committed', ?)",
            (BATCH_TYPE, plan["file_name"], plan["sha256"], plan["counts"]["read"],
             plan["counts"]["create"] + plan["counts"]["update"],
             plan["counts"]["problems"],
             json.dumps({"source": import_source, "path": plan["path"],
                         "counts": plan["counts"]})),
        )

        for record in plan["create"]:
            payload = {k: v for k, v in record.items() if v is not None}
            payload["import_source"] = import_source
            models_insert(db, payload)
            created += 1

        for item in plan["update"]:
            changes = item["changes"]
            assignments = ", ".join(f"{column} = ?" for column in changes)
            db.execute(
                f"UPDATE people SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                list(changes.values()) + [item["person_id"]],
            )
            updated += 1
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        if "import_batches" in str(exc) or "file_sha256" in str(exc):
            raise AlreadyImported(
                "this file has already been loaded — nothing was written"
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise

    mapped = models.apply_title_map(only_unmapped=True) if apply_titles else 0
    linked, unresolved = models.resolve_manager_links()

    return {
        "created": created,
        "updated": updated,
        "unchanged": len(plan["unchanged"]),
        "levels_mapped": mapped,
        "managers_linked": linked,
        "managers_unresolved": len(unresolved),
        "sha256": plan["sha256"],
    }


def models_insert(db, payload):
    """Insert one person on an open transaction.

    Separate from models.create_person because that commits per row, and a
    450-row import must be one transaction — a half-written roster is worse
    than none.
    """
    from app.modules.people.models import WRITABLE, _full_name

    fields = {k: v for k, v in payload.items() if k in WRITABLE}
    fields["full_name"] = _full_name(fields)
    columns = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    db.execute(
        f"INSERT INTO people ({columns}) VALUES ({placeholders})", list(fields.values())
    )
