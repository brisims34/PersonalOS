-- 0007 — Imports
-- docs/DATABASE_SCHEMA.md §0007
--
-- One ledger for every file the application loads. UNIQUE (batch_type,
-- file_sha256) is what makes a load one-time: importing the same file twice is
-- refused by the database rather than by a convention somebody has to remember.
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

CREATE TABLE import_batches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_type   TEXT NOT NULL CHECK (batch_type IN ('timesheet','people','template','generic_csv')),
    file_name    TEXT NOT NULL,
    file_sha256  TEXT NOT NULL,
    rows_read    INTEGER NOT NULL DEFAULT 0,
    rows_imported INTEGER NOT NULL DEFAULT 0,
    rows_skipped INTEGER NOT NULL DEFAULT 0,
    rows_unmatched INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'previewed'
                 CHECK (status IN ('previewed','committed','failed','rolled_back')),
    detail_json  TEXT,
    imported_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    UNIQUE (batch_type, file_sha256)
);
