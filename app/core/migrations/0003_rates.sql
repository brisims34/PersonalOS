-- 0003 — Rates
-- docs/DATABASE_SCHEMA.md §0003
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

CREATE TABLE rate_cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    company     TEXT,
    currency    TEXT NOT NULL DEFAULT 'USD',
    scope       TEXT NOT NULL DEFAULT 'standard'
                CHECK (scope IN ('standard','negotiated','internal','offshore')),
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    is_default  INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    note        TEXT,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at DATETIME,
    UNIQUE (name, company)
);

CREATE TABLE rate_card_entries (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    rate_card_id   INTEGER NOT NULL REFERENCES rate_cards(id) ON DELETE CASCADE,
    level_id       INTEGER NOT NULL REFERENCES person_levels(id),
    bill_rate      REAL,
    cost_rate      REAL,
    effective_from DATE NOT NULL,
    effective_to   DATE,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_rate_entries ON rate_card_entries(rate_card_id, level_id, effective_from);

CREATE TABLE person_rate_overrides (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id      INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    rate_card_id   INTEGER REFERENCES rate_cards(id) ON DELETE CASCADE,
    bill_rate      REAL,
    cost_rate      REAL,
    effective_from DATE NOT NULL,
    effective_to   DATE,
    reason         TEXT,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_rate_override ON person_rate_overrides(person_id, effective_from);


UPDATE module_registry SET is_enabled = 1 WHERE module_key = 'rates';
