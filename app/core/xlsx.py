"""Label-driven spreadsheet reading.

Columns are found by their header text, never by position, so a spreadsheet
that gains a column, loses one, or has them reordered still imports. That is
the difference between an importer that survives contact with real exports and
one that silently shifts every field by one.

Used by the contact seed import (Phase 1) and the timesheet import (Phase 9).
"""
import hashlib
import re
from pathlib import Path


class SpreadsheetError(RuntimeError):
    pass


def file_sha256(path, chunk=1 << 20):
    """Content hash, so re-importing the same file can be a no-op that says so."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalise(label):
    """'State_Province ' and 'state province' are the same column."""
    return re.sub(r"[^a-z0-9]+", "", str(label or "").strip().lower())


def find_header_row(rows, wanted, max_scan=20):
    """The first row that matches at least two wanted labels.

    Real exports put a title, a run date and a blank line above the header.
    Assuming row 1 is the header is the most common way this breaks.
    """
    targets = {_normalise(label) for labels in wanted.values() for label in labels}
    best_index, best_hits = None, 0
    for index, row in enumerate(rows[:max_scan]):
        hits = sum(1 for cell in row if _normalise(cell) in targets)
        if hits > best_hits:
            best_index, best_hits = index, hits
    if best_hits < 2:
        raise SpreadsheetError(
            "could not find a header row in the first "
            f"{max_scan} rows — looked for {sorted(targets)[:6]}…"
        )
    return best_index


def read_sheet(path, column_map, sheet=None, required=(), header_row=None):
    """Read a worksheet into dicts keyed by the names in `column_map`.

    `column_map` is {field_name: [acceptable header labels]}. Returns
    (records, report) where report names the columns matched, the columns
    ignored, and any required field that was not found — so the import wizard
    can show it before anything is written.
    """
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise SpreadsheetError(
            "openpyxl is not installed — pip install -r requirements.txt"
        ) from exc

    path = Path(path)
    if not path.exists():
        raise SpreadsheetError(f"no such file: {path}")

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet] if sheet else workbook[workbook.sheetnames[0]]
        rows = [list(r) for r in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()

    if not rows:
        raise SpreadsheetError(f"{path.name} has no rows")

    index = find_header_row(rows, column_map) if header_row is None else header_row
    header = rows[index]

    lookup = {}
    for position, cell in enumerate(header):
        key = _normalise(cell)
        if key and key not in lookup:
            lookup[key] = position

    resolved, unmatched = {}, []
    for field, labels in column_map.items():
        for label in labels:
            position = lookup.get(_normalise(label))
            if position is not None:
                resolved[field] = position
                break
        else:
            unmatched.append(field)

    missing_required = [field for field in required if field not in resolved]

    claimed = set(resolved.values())
    ignored = [
        str(cell).strip()
        for position, cell in enumerate(header)
        if cell and position not in claimed
    ]

    records = []
    for row in rows[index + 1:]:
        if not any(cell not in (None, "") for cell in row):
            continue  # blank separator rows are common and harmless
        record = {}
        for field, position in resolved.items():
            value = row[position] if position < len(row) else None
            if isinstance(value, str):
                value = value.strip() or None
            record[field] = value
        records.append(record)

    report = {
        "sheet": worksheet.title,
        "header_row": index + 1,
        "matched": sorted(resolved),
        "unmatched_fields": unmatched,
        "missing_required": missing_required,
        "ignored_columns": ignored,
        "row_count": len(records),
        "sheet_names": workbook.sheetnames,
    }
    return records, report
