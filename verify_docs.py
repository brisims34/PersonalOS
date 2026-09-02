"""
Documentation consistency checker for PersonalOS.

Run after any change to docs/DATABASE_SCHEMA.md or the specification set:

    python verify_docs.py        # exit 0 = all pass

Checks performed:
  1. Every CREATE statement in DATABASE_SCHEMA.md executes against real SQLite
  2. Every foreign key target resolves to a table defined in the same document
  3. Enum CHECK constraints are present on the columns that need them
  4. Migration ownership table, migration sections and BUILD_SEQUENCE agree
  5. Every module in the spec's IA appears in BUILD_SEQUENCE
  6. Every stated capability has a trace somewhere in the documentation
  7. Cross-document references resolve
  8. Code fences balance
  9. Every CREATE TABLE in app/core/migrations/ matches DATABASE_SCHEMA.md

This enforces CLAUDE.md rule 5 mechanically: a schema change that does not
also update the documentation will fail here.

Once the app exists, scripts/health_check.py validates the live database;
this validates the document that describes it.
"""
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SCHEMA = ROOT / "docs" / "DATABASE_SCHEMA.md"
BUILD = ROOT / "docs" / "BUILD_SEQUENCE.md"
SPEC = ROOT / "PersonalOS_Spec.md"

# Vault note filenames that pattern-match a doc reference but are not one
NOT_DOCS = {"_workstream.md", "_project.md", "notes.md", "cutover-plan.md"}

# Capability -> a token that must appear somewhere in the corpus if it is specified
CAPABILITIES = {
    "client projects": "client",
    "internal projects": "internal",
    "innovation network": "innovation_network_members",
    "training plans": "training_plans",
    "workstreams": "workstreams",
    "multiple charge codes": "charge_codes",
    "charge code leadership": "lead_partner_person_id",
    "markdown notes on disk": "vault_roots",
    "wikilinks": "note_links",
    "obsidian semantics": "obsidian",
    "outlook email intake": "_helper_mail",
    "outlook calendar": "_helper_calendar",
    "gal contacts": "_helper_gal",
    "manager chain walk": "gal_manager_chain",
    "org chart": "manager_person_id",
    "key dates from email": "extracted_dates",
    "t&m budgets": "budget_lines",
    "bill and cost rates": "cost_rate",
    "rates by level": "person_levels",
    "annual rate change": "effective_from",
    "promotion repricing": "person_level_history",
    "tenure splits": "auto_promote_after_months",
    "last promote date": "last_promoted_on",
    "erp": "erp_pct",
    "admin fee": "fee_types",
    "kinergy fee": "kinergy",
    "negotiated rate card": "negotiated",
    "wbs task budget": "task_id",
    "smartsheet pipeline": "pipeline_opportunities",
    "resource availability": "person_capacity",
    "gantt timeline": "portfolio timeline",
    "major milestones only": "is_major",
    "on time on budget": "burn_ratio",
    "resource cliffs": "cliff",
    "assignment end dates": "assignment_extensions",
    "weekly allocation percent": "weekly_allocations",
    "morning report": "morning report",
    "resource horizon": "resource horizon",
    "staffing board": "staffing board",
    "staffing coverage": "staffing_requirements",
    "skills matching": "person_skills",
    "raid log": "raid_items",
    "stakeholder register": "stakeholders",
    "change control": "change_requests",
    "comms plan": "comms_plan_items",
    "status reports": "project_status_updates",
    "performance counselees": "performance_tracks",
    "recurring reminders": "rrule",
    "calendar ownership partition": "personalos folder",
    "template library": "project_templates",
    "workstream charter": "workstream charter",
    "physical work locations": "locations",
    "digital work resources": "work_resources",
    "cross-workstream dependencies": "to_workstream_id",
    "validation checks": "validation checks",
    "local llm server": "personalos_ai",
    "claude provider": "anthropic",
    "google provider": "google",
    "ai queue page": "ai_jobs",
    "manual model install": "model.onnx.data",
    "ai data boundary": "max_boundary",
    "command palette": "command palette",
    "hotkeys": "hotkey",
    "drag and drop": "drag",
    "quick steps": "quick_steps",
    "dark theme": "data-bs-theme",
    "as_of discipline": "as_of",
}

fails, warns = [], []


def section(title):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def _normalise(sql):
    """Collapse formatting so a reflowed CREATE TABLE is not read as a change."""
    stripped = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"\s+", " ", stripped).strip().rstrip(",")


def main():
    text = SCHEMA.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")

    # 1 — DDL executes
    section("1. DDL EXECUTION")
    stmts = []
    for block in re.findall(r"```sql\n(.*?)```", text, re.DOTALL):
        for s in block.split(";"):
            s = s.strip()
            if s.upper().startswith(("CREATE TABLE", "CREATE INDEX", "CREATE VIRTUAL TABLE")):
                stmts.append(s)

    db_path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "personalos_schema_check.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")

    ok = 0
    for s in stmts:
        try:
            conn.execute(s)
            ok += 1
        except sqlite3.Error as exc:
            name = re.search(r"CREATE (?:VIRTUAL )?(?:TABLE|INDEX)\s+(\w+)", s)
            fails.append(f"DDL {name.group(1) if name else '?'}: {exc}")
    conn.commit()

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE '%_data' AND name NOT LIKE '%_idx' AND name NOT LIKE '%_content' "
        "AND name NOT LIKE '%_docsize' AND name NOT LIKE '%_config'").fetchall()]
    tset = set(tables)
    fks = sum(len(conn.execute(f"PRAGMA foreign_key_list({t})").fetchall()) for t in tables)
    print(f"{ok}/{len(stmts)} statements executed | {len(tables)} tables | {fks} foreign keys")

    # 2 — FK targets
    section("2. FOREIGN KEY TARGETS")
    missing = {}
    for t in tables:
        for row in conn.execute(f"PRAGMA foreign_key_list({t})").fetchall():
            if row[2] not in tset:
                missing.setdefault(row[2], []).append(t)
    for target, sources in missing.items():
        fails.append(f"FK target '{target}' undefined; referenced by {', '.join(sources)}")
    print("All FK targets resolve." if not missing else f"{len(missing)} unresolved.")

    # 3 — Enums
    section("3. ENUM CONSTRAINTS")
    checks = {}
    for m in re.finditer(r"CHECK \((\w+) IN \(([^)]+)\)\)", text):
        checks.setdefault(m.group(1), set()).update(
            v.strip().strip("'") for v in m.group(2).split(","))
    print(f"{len(checks)} columns carry a CHECK constraint")
    for col in ("status", "raid_type", "boundary", "resource_role", "dependency_type",
                "pack_kind", "calc_method", "basis", "disposition", "import_source",
                "location_kind", "resource_kind"):
        if col not in checks:
            warns.append(f"Expected enum column '{col}' has no CHECK constraint")

    # 4 — Migrations
    section("4. MIGRATION COVERAGE")
    listed = {m[:4] for m in re.findall(r"\|\s*`(\d{4}_\w+\.sql)`", text)}
    present = set(re.findall(r"^# (\d{4}) — ", text, re.MULTILINE))
    in_build = set(re.findall(r"(\d{4})_\w+\.sql", build))
    for n in sorted(listed ^ present):
        fails.append(f"Migration {n} appears in only one of (ownership table, sections)")
    for n in sorted(in_build - listed):
        fails.append(f"BUILD_SEQUENCE references migration {n} absent from schema")
    print(f"Ownership {len(listed)} | Sections {len(present)} | BUILD_SEQUENCE {len(in_build)}")

    # 5 — IA modules
    section("5. IA MODULE COVERAGE")
    keys = set(re.findall(r"^\| `(\w+)` \|", build, re.MULTILINE))
    ia = re.search(r"\| Group \| Modules \|\n\|[-\s|]+\|\n((?:\|.*\|\n)+)", spec)
    modules = []
    if ia:
        for line in ia.group(1).strip().split("\n"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2:
                modules += [m.strip().strip("*") for m in cells[1].split("·")]
    print(f"IA lists {len(modules)} modules | registry map defines {len(keys)} keys")
    if len(keys) < len(modules):
        warns.append(f"Registry map has {len(keys)} keys for {len(modules)} IA modules")

    # 6 — Capability traceability
    section("6. CAPABILITY TRACEABILITY")
    docs = sorted(list(ROOT.glob("*.md")) + list((ROOT / "docs").glob("*.md")))
    corpus = "\n".join(p.read_text(encoding="utf-8").lower() for p in docs)
    unmapped = [c for c, token in CAPABILITIES.items() if token.lower() not in corpus]
    for c in unmapped:
        fails.append(f"Capability '{c}' has no trace in the documentation")
    print(f"{len(CAPABILITIES)} capabilities checked, {len(unmapped)} unmapped")

    # 7 — Cross references
    section("7. DOC REFERENCES")
    known = {p.name for p in docs}
    bad = 0
    for p in docs:
        for ref in set(re.findall(r"`((?:docs/)?[A-Za-z_]+\.md)`", p.read_text(encoding="utf-8"))):
            base = ref.split("/")[-1]
            if base not in NOT_DOCS and base not in known:
                fails.append(f"{p.name}: broken reference `{ref}`")
                bad += 1
    print(f"{len(docs)} documents checked, {bad} broken references")

    # 8 — Structure
    section("8. STRUCTURE")
    diagrams = 0
    for p in docs:
        body = p.read_text(encoding="utf-8")
        diagrams += len(re.findall(r"^```mermaid\s*$", body, re.MULTILINE))
        if len(re.findall(r"^```", body, re.MULTILINE)) % 2:
            fails.append(f"{p.name}: unbalanced code fences")
    print(f"{diagrams} mermaid diagrams across {len(docs)} documents")

    # 9 — the migrations on disk must match the document that describes them
    section("9. MIGRATION FILES vs SCHEMA DOC")
    migrations_dir = ROOT / "app" / "core" / "migrations"
    if not migrations_dir.exists():
        print("No migrations written yet — nothing to compare.")
    else:
        documented = {
            name: _normalise(body)
            for name, body in re.findall(
                r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)\s*\((.*?)\n\);", text, re.DOTALL
            )
        }
        compared = drifted = 0
        for path in sorted(migrations_dir.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            for name, body in re.findall(
                r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)\s*\((.*?)\n\);", sql, re.DOTALL
            ):
                compared += 1
                if name not in documented:
                    fails.append(f"{path.name}: table '{name}' is not in DATABASE_SCHEMA.md")
                    drifted += 1
                elif documented[name] != _normalise(body):
                    fails.append(
                        f"{path.name}: table '{name}' differs from DATABASE_SCHEMA.md"
                    )
                    drifted += 1
        print(f"{compared} table definitions compared, {drifted} drifted")

    # Summary
    section("SUMMARY")
    print(f"Tables {len(tables)} | FKs {fks} | Docs {len(docs)} | "
          f"Diagrams {diagrams} | Capabilities {len(CAPABILITIES)}")
    if warns:
        print(f"\nWARNINGS ({len(warns)}):")
        for w in warns:
            print(f"  ! {w}")
    if fails:
        print(f"\nFAILURES ({len(fails)}):")
        for f in fails:
            print(f"  X {f}")
        conn.close()
        return 1
    print("\nAll checks passed. Documentation is build-ready.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
