-- 0002 — People & Org
-- docs/DATABASE_SCHEMA.md §0002
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

CREATE TABLE person_levels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    level_key    TEXT NOT NULL UNIQUE,
    label        TEXT NOT NULL,
    sort_order   INTEGER NOT NULL,
    is_on_ladder INTEGER NOT NULL DEFAULT 1 CHECK (is_on_ladder IN (0,1)),
    auto_promote_to_level_id  INTEGER REFERENCES person_levels(id),
    auto_promote_after_months INTEGER,
    created_at   DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE job_title_map (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_title  TEXT NOT NULL UNIQUE,
    level_id   INTEGER NOT NULL REFERENCES person_levels(id),
    function   TEXT,
    is_specialist INTEGER NOT NULL DEFAULT 0 CHECK (is_specialist IN (0,1)),
    created_at DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE people (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    external_ref      TEXT,
    first_name        TEXT NOT NULL,
    last_name         TEXT NOT NULL,
    preferred_name    TEXT,
    full_name         TEXT NOT NULL,
    email             TEXT UNIQUE,
    upn               TEXT,
    company           TEXT,
    department        TEXT,
    job_title         TEXT,
    level_id          INTEGER REFERENCES person_levels(id),
    level_start_date  DATE,
    last_promoted_on  DATE,
    function          TEXT,
    relationship_type TEXT NOT NULL DEFAULT 'colleague'
                      CHECK (relationship_type IN ('self','colleague','counselee','direct_report',
                                                   'client','vendor','stakeholder','mentor','other')),
    status            TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','inactive','departed')),
    business_phone    TEXT,
    home_phone        TEXT,
    mobile_phone      TEXT,
    city              TEXT,
    state_province    TEXT,
    location          TEXT,
    manager_email     TEXT,
    manager_person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    import_source     TEXT NOT NULL DEFAULT 'manual'
                      CHECK (import_source IN ('manual','excel_seed','gal_direct',
                                               'gal_manager_chain','email_scrape','smartsheet')),
    outlook_entry_id  TEXT,
    smartsheet_row_id TEXT,
    gal_synced_at     DATETIME,
    notes             TEXT,
    strengths         TEXT,
    development_areas TEXT,
    tags              TEXT,
    last_interaction_date DATE,
    next_follow_up_date   DATE,
    created_at        DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at        DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at       DATETIME
);

CREATE INDEX idx_people_email    ON people(email);

CREATE INDEX idx_people_manager  ON people(manager_person_id);

CREATE INDEX idx_people_level    ON people(level_id, level_start_date);

CREATE INDEX idx_people_company  ON people(company);

CREATE INDEX idx_people_archived ON people(archived_at);

CREATE TABLE person_level_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id      INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    level_id       INTEGER NOT NULL REFERENCES person_levels(id),
    effective_from DATE NOT NULL,
    effective_to   DATE,
    reason         TEXT NOT NULL DEFAULT 'annual'
                   CHECK (reason IN ('hire','annual','promotion','correction','departure')),
    note           TEXT,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_level_hist_person ON person_level_history(person_id, effective_from);

CREATE TABLE person_capacity (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id      INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    weekly_hours   REAL NOT NULL DEFAULT 40.0,
    fte            REAL NOT NULL DEFAULT 1.0,
    effective_from DATE NOT NULL,
    effective_to   DATE,
    note           TEXT,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_capacity_person ON person_capacity(person_id, effective_from);

CREATE TABLE person_status_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    disposition TEXT NOT NULL
                CHECK (disposition IN ('available','leave','sick','training',
                                       'rotation','loa','holiday','other')),
    start_date  DATE NOT NULL,
    end_date    DATE,
    detail      TEXT,
    source      TEXT NOT NULL DEFAULT 'manual'
                CHECK (source IN ('manual','smartsheet','outlook_oof')),
    created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at  DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_status_person ON person_status_events(person_id, start_date);

CREATE INDEX idx_status_dates  ON person_status_events(start_date, end_date);


-- ---------------------------------------------------------------------------
-- Seed: the rate card ladder
--
-- These nine levels (plus contractor, off ladder) are the rate-bearing rows.
-- Job title is deliberately not level — see job_title_map below and
-- docs/FINANCIAL_MODEL.md §2.
-- ---------------------------------------------------------------------------

INSERT INTO person_levels (level_key, label, sort_order, is_on_ladder) VALUES
 ('contractor',              'Contractor',                     5, 0),
 ('intern_paraprofessional', 'Intern / Paraprofessional',     10, 1),
 ('associate',               'Associate',                     20, 1),
 ('senior_associate',        'Senior Associate',              30, 1),
 ('manager',                 'Manager',                       40, 1),
 ('director_lt3',            'Director (< 3 years)',          50, 1),
 ('senior_director',         'Senior Director (3+ years)',    60, 1),
 ('managing_director',       'Managing Director',             70, 1),
 ('partner_lt5',             'Partner / Principal (< 5 years)', 80, 1),
 ('partner_gte5',            'Partner / Principal (5+ years)',  90, 1);

-- The two tenure splits. Applied as an UPDATE because the target row's id is
-- only known after insert. The application flags a due transition and asks;
-- it never promotes anybody on its own (DESIGN_DECISIONS.md F8).
UPDATE person_levels
   SET auto_promote_to_level_id = (SELECT id FROM person_levels WHERE level_key = 'senior_director'),
       auto_promote_after_months = 36
 WHERE level_key = 'director_lt3';

UPDATE person_levels
   SET auto_promote_to_level_id = (SELECT id FROM person_levels WHERE level_key = 'partner_gte5'),
       auto_promote_after_months = 60
 WHERE level_key = 'partner_lt5';


-- ---------------------------------------------------------------------------
-- Seed: directory job title → level and function
--
-- The 13 titles observed in AASppl.xlsx. Editable in Admin, because HR invents
-- new ones and an unmapped title must never silently price at zero.
--
-- Four of these are defaults awaiting confirmation — see DECISION_LOG.md §2.1.
-- Assistant Manager, Consultant and Contractor have no rate card row of their
-- own, and the two Specialist titles may carry their own rates.
-- ---------------------------------------------------------------------------

INSERT INTO job_title_map (job_title, level_id, function, is_specialist)
SELECT t.job_title, l.id, t.function, t.is_specialist
  FROM (
    SELECT 'Advisory Managing Director' AS job_title, 'managing_director' AS lk, 'Advisory'  AS function, 0 AS is_specialist
    UNION ALL SELECT 'Specialist MD, Advisory',    'managing_director', 'Advisory',  1
    UNION ALL SELECT 'Director Advisory',          'director_lt3',      'Advisory',  0
    UNION ALL SELECT 'Specialist Dir, Analytics',  'director_lt3',      'Analytics', 1
    UNION ALL SELECT 'Manager Advisory',           'manager',           'Advisory',  0
    UNION ALL SELECT 'Assistant Manager',          'manager',           'Advisory',  0
    UNION ALL SELECT 'Sr Associate Advisory',      'senior_associate',  'Advisory',  0
    UNION ALL SELECT 'Sr Associate Audit',         'senior_associate',  'Audit',     0
    UNION ALL SELECT 'Associate Advisory',         'associate',         'Advisory',  0
    UNION ALL SELECT 'Associate Audit',            'associate',         'Audit',     0
    UNION ALL SELECT 'Associate Consultant',       'associate',         'Advisory',  0
    UNION ALL SELECT 'Consultant',                 'associate',         'Advisory',  0
    UNION ALL SELECT 'Contractor',                 'contractor',        'Advisory',  0
  ) AS t
  JOIN person_levels AS l ON l.level_key = t.lk;


-- Phase 1 ships these modules; the registry is what puts them in the sidebar.
UPDATE module_registry SET is_enabled = 1 WHERE module_key IN ('people', 'org_chart');
