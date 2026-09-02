-- 0005 — Notes Vault
-- docs/DATABASE_SCHEMA.md §0005
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

CREATE TABLE vault_roots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    root_key    TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL,
    abs_path    TEXT NOT NULL,
    is_readonly INTEGER NOT NULL DEFAULT 0 CHECK (is_readonly IN (0,1)),
    is_enabled  INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0,1)),
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE notes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id        INTEGER NOT NULL REFERENCES vault_roots(id) ON DELETE CASCADE,
    rel_path       TEXT NOT NULL,
    title          TEXT NOT NULL,
    note_type      TEXT,
    project_id     INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    workstream_id  INTEGER REFERENCES workstreams(id) ON DELETE SET NULL,
    frontmatter_json TEXT,
    tags           TEXT,
    content_hash   TEXT NOT NULL,
    mtime          DATETIME NOT NULL,
    size_bytes     INTEGER NOT NULL DEFAULT 0,
    indexed_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    created_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    UNIQUE (root_id, rel_path)
);

CREATE INDEX idx_notes_project ON notes(project_id);

CREATE INDEX idx_notes_hash    ON notes(content_hash);

CREATE TABLE note_links (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    from_note_id   INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    link_text      TEXT NOT NULL,
    target_kind    TEXT NOT NULL CHECK (target_kind IN ('note','record','external')),
    target_note_id INTEGER REFERENCES notes(id) ON DELETE SET NULL,
    target_type    TEXT,
    target_id      INTEGER,
    is_resolved    INTEGER NOT NULL DEFAULT 0 CHECK (is_resolved IN (0,1)),
    created_at     DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_note_links_from   ON note_links(from_note_id);

CREATE INDEX idx_note_links_target ON note_links(target_type, target_id);

CREATE INDEX idx_note_links_note   ON note_links(target_note_id);

CREATE VIRTUAL TABLE notes_fts USING fts5(
    title,
    body,
    tokenize = 'porter unicode61'
);


-- Phase 3 modules.
UPDATE module_registry SET is_enabled = 1 WHERE module_key IN ('notes', 'search');
