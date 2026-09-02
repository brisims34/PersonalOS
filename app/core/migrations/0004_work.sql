-- 0004 — Work
-- docs/DATABASE_SCHEMA.md §0004
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

CREATE TABLE portfolios (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    portfolio_kind TEXT NOT NULL DEFAULT 'client'
                 CHECK (portfolio_kind IN ('client','internal','innovation','training','admin')),
    description  TEXT,
    folder_slug  TEXT NOT NULL UNIQUE,
    sort_order   INTEGER NOT NULL DEFAULT 0,
    created_at   DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at  DATETIME
);

CREATE TABLE projects (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id          INTEGER NOT NULL REFERENCES portfolios(id),
    name                  TEXT NOT NULL,
    code                  TEXT UNIQUE,
    client_org            TEXT,
    description           TEXT,
    service_offering      TEXT,
    project_type          TEXT,
    status                TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('pipeline','active','on_hold','completed','cancelled')),
    priority              TEXT NOT NULL DEFAULT 'medium'
                          CHECK (priority IN ('high','medium','low')),
    rag_status            TEXT CHECK (rag_status IN ('green','amber','red')),
    baseline_start        DATE,
    baseline_end          DATE,
    forecast_start        DATE,
    forecast_end          DATE,
    actual_start          DATE,
    actual_end            DATE,
    rate_card_id          INTEGER REFERENCES rate_cards(id),
    erp_pct               REAL NOT NULL DEFAULT 100.0,
    currency              TEXT NOT NULL DEFAULT 'USD',
    budget_hours          REAL,
    budget_fees           REAL,
    budget_expenses       REAL,
    lead_partner_person_id       INTEGER REFERENCES people(id),
    engagement_manager_person_id INTEGER REFERENCES people(id),
    project_lead_person_id       INTEGER REFERENCES people(id),
    folder_path           TEXT,
    cover_image           TEXT,
    smartsheet_row_id     TEXT,
    template_key          TEXT,
    template_version      TEXT,
    created_at            DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at            DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at           DATETIME
);

CREATE INDEX idx_projects_portfolio ON projects(portfolio_id);

CREATE INDEX idx_projects_status    ON projects(status);

CREATE INDEX idx_projects_archived  ON projects(archived_at);

CREATE TABLE workstreams (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,
    description    TEXT,
    lead_person_id INTEGER REFERENCES people(id),
    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('planned','active','on_hold','completed','cancelled')),
    baseline_start DATE,
    baseline_end   DATE,
    forecast_start DATE,
    forecast_end   DATE,
    budget_hours   REAL,
    folder_path    TEXT,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at    DATETIME
);

CREATE INDEX idx_workstreams_project ON workstreams(project_id);

CREATE TABLE charge_codes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    workstream_id INTEGER REFERENCES workstreams(id) ON DELETE SET NULL,
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','inactive','closed')),
    opened_on     DATE,
    closed_on     DATE,
    lead_partner_person_id       INTEGER REFERENCES people(id),
    engagement_manager_person_id INTEGER REFERENCES people(id),
    rate_card_id  INTEGER REFERENCES rate_cards(id),
    erp_pct       REAL,
    currency      TEXT NOT NULL DEFAULT 'USD',
    budget_hours  REAL,
    budget_fees   REAL,
    external_ref  TEXT,
    is_default    INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    notes         TEXT,
    created_at    DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at    DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at   DATETIME
);

CREATE INDEX idx_charge_project ON charge_codes(project_id);

CREATE INDEX idx_charge_status  ON charge_codes(status);

CREATE TABLE locations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    location_kind  TEXT NOT NULL DEFAULT 'client_site'
                   CHECK (location_kind IN ('client_site','firm_office','coworking','remote','other')),
    organization   TEXT,
    address_line1  TEXT,
    address_line2  TEXT,
    city           TEXT,
    state_province TEXT,
    postal_code    TEXT,
    country        TEXT,
    building       TEXT,
    floor          TEXT,
    room           TEXT,
    access_notes   TEXT,
    logistics_notes TEXT,
    site_contact_person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    map_url        TEXT,
    notes          TEXT,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at    DATETIME
);

CREATE INDEX idx_locations_kind ON locations(location_kind);

CREATE TABLE work_resources (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    workstream_id  INTEGER REFERENCES workstreams(id) ON DELETE CASCADE,
    label          TEXT NOT NULL,
    resource_kind  TEXT NOT NULL DEFAULT 'folder'
                   CHECK (resource_kind IN ('folder','file','script','repo','chat_channel',
                                            'email_thread','url','dashboard','mailbox','other')),
    resource_role  TEXT NOT NULL DEFAULT 'reference'
                   CHECK (resource_role IN ('input','working','output','reference','communication')),
    path_or_url    TEXT NOT NULL,
    description    TEXT,
    access_notes   TEXT,
    owner_person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    last_verified_at DATETIME,
    verify_status  TEXT CHECK (verify_status IN ('ok','missing','unchecked','not_verifiable')),
    sort_order     INTEGER NOT NULL DEFAULT 0,
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at     DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_resources_workstream ON work_resources(workstream_id, resource_role);

CREATE INDEX idx_resources_project    ON work_resources(project_id);

CREATE TABLE dependencies (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id         INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    from_workstream_id INTEGER REFERENCES workstreams(id) ON DELETE CASCADE,
    to_workstream_id   INTEGER REFERENCES workstreams(id) ON DELETE SET NULL,
    external_party     TEXT,
    title              TEXT NOT NULL,
    description        TEXT,
    dependency_type    TEXT NOT NULL DEFAULT 'blocks'
                       CHECK (dependency_type IN ('blocks','provides_data','requires_signoff',
                                                  'informs','shares_resource')),
    criticality        TEXT NOT NULL DEFAULT 'important'
                       CHECK (criticality IN ('critical','important','minor')),
    needed_by_date     DATE,
    status             TEXT NOT NULL DEFAULT 'identified'
                       CHECK (status IN ('identified','confirmed','at_risk','satisfied','broken')),
    owner_person_id    INTEGER REFERENCES people(id) ON DELETE SET NULL,
    notes              TEXT,
    created_at         DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at         DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at        DATETIME
);

CREATE INDEX idx_deps_from ON dependencies(from_workstream_id, status);

CREATE INDEX idx_deps_to   ON dependencies(to_workstream_id, status);

CREATE INDEX idx_deps_due  ON dependencies(needed_by_date);


-- ---------------------------------------------------------------------------
-- Seed: the four portfolios
--
-- Everything is a project — client engagements, internal work, innovation and
-- training. The portfolio is what separates them (PersonalOS_Spec.md §7.2).
-- folder_slug is the directory name under projects/ and is title case on
-- purpose: it is a heading a human reads in Explorer, not a URL slug.
-- ---------------------------------------------------------------------------

INSERT INTO portfolios (name, portfolio_kind, folder_slug, sort_order, description) VALUES
 ('Client Delivery', 'client',     'Client Delivery', 10, 'Billable client engagements'),
 ('Internal',        'internal',   'Internal',        20, 'Practice and firm initiatives'),
 ('Innovation',      'innovation', 'Innovation',      30, 'Innovation and development work'),
 ('Training',        'training',   'Training',        40, 'Training programmes and curricula');


-- Phase 2 modules.
UPDATE module_registry SET is_enabled = 1 WHERE module_key IN ('portfolios', 'projects', 'charge_codes');
