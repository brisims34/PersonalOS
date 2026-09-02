-- 0001 — System
-- docs/DATABASE_SCHEMA.md §0001
--
-- These five tables have no foreign keys to anything, deliberately.
-- entity_links is polymorphic by design and activity_log must survive the
-- deletion of whatever it describes.
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

CREATE TABLE app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    value_type  TEXT NOT NULL DEFAULT 'string'
                CHECK (value_type IN ('string','int','float','bool','json')),
    description TEXT,
    updated_at  DATETIME NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE config_options (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    option_set TEXT NOT NULL,
    value      TEXT NOT NULL,
    label      TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_active  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    UNIQUE (option_set, value)
);
CREATE INDEX idx_config_options_set ON config_options(option_set, sort_order);

CREATE TABLE module_registry (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    module_key  TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL,
    nav_group   TEXT NOT NULL,
    url_prefix  TEXT NOT NULL,
    icon        TEXT,
    is_enabled  INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0,1)),
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   INTEGER,
    action      TEXT NOT NULL
                CHECK (action IN ('created','updated','deleted','archived',
                                  'restored','imported','exported','synced','ran')),
    summary     TEXT NOT NULL,
    detail_json TEXT,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_activity_entity  ON activity_log(entity_type, entity_id);
CREATE INDEX idx_activity_created ON activity_log(created_at DESC);

CREATE TABLE entity_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id   INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    link_label  TEXT,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source_type, source_id, target_type, target_id)
);
CREATE INDEX idx_links_source ON entity_links(source_type, source_id);
CREATE INDEX idx_links_target ON entity_links(target_type, target_id);


-- ---------------------------------------------------------------------------
-- Seed: application settings
-- ---------------------------------------------------------------------------

INSERT INTO app_settings (key, value, value_type, description) VALUES
 ('app_name',                    'PersonalOS', 'string', 'Shown in the title bar and browser tab'),
 ('owner_name',                  '',           'string', 'Your name, used on generated documents'),
 ('self_person_id',              NULL,         'int',    'Which people row is you — drives "my" views'),
 ('theme',                       'dark',       'string', 'dark or light'),
 ('fiscal_year_start',           '10-01',      'string', 'MM-DD — start of the firm fiscal year'),
 ('default_currency',            'USD',        'string', 'System managed. All amounts are USD'),
 ('vault_root',                  'projects',   'string', 'Notes vault root, relative to the app root'),
 ('template_library_root',       'template_library', 'string', 'Template pack root, relative to the app root'),
 ('backup_count_to_keep',        '20',         'int',    'Older backups are pruned beyond this count'),
 ('meeting_prep_lookahead_days', '2',          'int',    'How far ahead the Command Center flags prep'),
 ('resource_horizon_weeks',      '12',         'int',    'Default width of the Resource Horizon grid'),
 ('understaffed_threshold',      '1.0',        'float',  'Coverage below this marks a project understaffed'),
 ('utilization_bands',           '{"bench":60,"good":95,"full":110}', 'json', 'Upper bound of each capacity band, in percent'),
 ('manager_chain_depth_cap',     '10',         'int',    'How far the GAL manager walk may climb'),
 ('ai_enabled',                  '0',          'bool',   'Master switch for every AI feature'),
 ('ai_base_url',                 'http://127.0.0.1:5151/v1', 'string', 'Local model server'),
 ('sidebar_collapsed',           '0',          'bool',   'Sidebar rail state, persisted across sessions');


-- ---------------------------------------------------------------------------
-- Seed: dropdown vocabularies
--
-- Editable in Admin, so a taxonomy change needs no migration. Where a column
-- also carries a CHECK constraint, `value` matches the constrained token and
-- `label` carries the words a Public Accountant would use (P9).
-- ---------------------------------------------------------------------------

-- Mirrors the template_library/ folder tree exactly.
INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('service_offering', 'Transaction Services', 'Transaction Services', 10),
 ('service_offering', 'Accounting Advisory',  'Accounting Advisory',  20),
 ('service_offering', 'Internal',             'Internal',             30);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('project_type', 'Sell Side',             'Sell Side',             10),
 ('project_type', 'Buy Side',              'Buy Side',              20),
 ('project_type', 'Restatement',           'Restatement',           30),
 ('project_type', 'Accounting Error',      'Accounting Error',      40),
 ('project_type', 'Internal Initiative',   'Internal Initiative',   50),
 ('project_type', 'Innovation Initiative', 'Innovation Initiative', 60),
 ('project_type', 'Training Programme',    'Training Programme',    70);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('portfolio_kind', 'client',     'Client Delivery',   10),
 ('portfolio_kind', 'internal',   'Internal',          20),
 ('portfolio_kind', 'innovation', 'Innovation',        30),
 ('portfolio_kind', 'training',   'Training',          40),
 ('portfolio_kind', 'admin',      'Administration',    50);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('task_type', 'my_task',    'My Task',    10),
 ('task_type', 'follow_up',  'Follow Up',  20),
 ('task_type', 'delegated',  'Delegated',  30),
 ('task_type', 'waiting_on', 'Waiting On', 40);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('priority', 'high',   'High',   10),
 ('priority', 'medium', 'Medium', 20),
 ('priority', 'low',    'Low',    30);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('rag_status', 'green', 'Green', 10),
 ('rag_status', 'amber', 'Amber', 20),
 ('rag_status', 'red',   'Red',   30);

-- Dependencies are a first-class table, not a RAID type. See §0004.
INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('raid_type', 'risk',       'Risk',       10),
 ('raid_type', 'assumption', 'Assumption', 20),
 ('raid_type', 'issue',      'Issue',      30);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('stakeholder_stance', 'champion',  'Champion',  10),
 ('stakeholder_stance', 'supporter', 'Supporter', 20),
 ('stakeholder_stance', 'neutral',   'Neutral',   30),
 ('stakeholder_stance', 'skeptic',   'Skeptic',   40),
 ('stakeholder_stance', 'blocker',   'Blocker',   50);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('disposition', 'available', 'Active & Ready',    10),
 ('disposition', 'leave',     'On Leave',          20),
 ('disposition', 'sick',      'Sick',              30),
 ('disposition', 'training',  'In Training',       40),
 ('disposition', 'rotation',  'On Rotation',       50),
 ('disposition', 'loa',       'Leave of Absence',  60),
 ('disposition', 'holiday',   'Public Holiday',    70),
 ('disposition', 'other',     'Other',             80);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('skill_category', 'Technical Accounting',    'Technical Accounting',    10),
 ('skill_category', 'Financial Due Diligence', 'Financial Due Diligence', 20),
 ('skill_category', 'Valuation',               'Valuation',               30),
 ('skill_category', 'Data & Analytics',        'Data & Analytics',        40),
 ('skill_category', 'Audit',                   'Audit',                   50),
 ('skill_category', 'Project Management',      'Project Management',      60),
 ('skill_category', 'Tooling',                 'Tooling',                 70),
 ('skill_category', 'Industry',                'Industry',                80);

-- Derived from job title alongside level. See job_title_map in §0002.
INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('function', 'Advisory',  'Advisory',  10),
 ('function', 'Audit',     'Audit',     20),
 ('function', 'Analytics', 'Analytics', 30);


-- ---------------------------------------------------------------------------
-- Seed: module registry
--
-- The full IA from docs/BUILD_SEQUENCE.md "Module Registry Map". A module is
-- registered disabled until its phase lands, so the sidebar only ever shows
-- what works, and every route checks is_module_enabled() (CLAUDE.md rule 14).
-- ---------------------------------------------------------------------------

INSERT INTO module_registry (module_key, label, nav_group, url_prefix, icon, is_enabled, sort_order) VALUES
 ('command_center', 'Command Center',        'Command',    '/',              'bi-speedometer2',      1,  10),
 ('tasks',          'Tasks',                 'Command',    '/tasks',         'bi-check2-square',     0,  20),
 ('calendar',       'Calendar',              'Command',    '/calendar',      'bi-calendar-week',     0,  30),

 ('portfolios',     'Portfolios',            'Work',       '/portfolios',    'bi-collection',        0, 110),
 ('projects',       'Projects & Workstreams','Work',       '/projects',      'bi-diagram-3',         0, 120),
 ('timeline',       'Portfolio Timeline',    'Work',       '/timeline',      'bi-bar-chart-steps',   0, 130),
 ('milestones',     'Milestones',            'Work',       '/milestones',    'bi-flag',              0, 140),
 ('templates',      'Template Library',      'Work',       '/templates',     'bi-file-earmark-plus', 0, 150),

 ('raid',           'RAID & Decisions',      'Governance', '/raid',          'bi-shield-exclamation',0, 210),
 ('stakeholders',   'Stakeholders',          'Governance', '/stakeholders',  'bi-people',            0, 220),
 ('changes',        'Change Control',        'Governance', '/changes',       'bi-arrow-left-right',  0, 230),
 ('status_reports', 'Status Reports',        'Governance', '/status',        'bi-journal-text',      0, 240),

 ('charge_codes',   'Charge Codes',          'Money',      '/charge-codes',  'bi-upc-scan',          0, 310),
 ('rates',          'Budgets & Rates',       'Money',      '/rates',         'bi-cash-stack',        0, 320),
 ('time_import',    'Time Import',           'Money',      '/time-import',   'bi-stopwatch',         0, 330),
 ('financials',     'Financial Analysis',    'Money',      '/financials',    'bi-graph-up',          0, 340),

 ('staffing_board', 'Staffing Board',        'Resources',  '/staffing',      'bi-grid-1x2',          0, 410),
 ('morning_report', 'Morning Report',        'Resources',  '/morning-report','bi-sunrise',           0, 420),
 ('horizon',        'Resource Horizon',      'Resources',  '/horizon',       'bi-calendar3-range',   0, 430),
 ('assignments',    'Assignments',           'Resources',  '/assignments',   'bi-person-badge',      0, 440),
 ('skills',         'Skills',                'Resources',  '/skills',        'bi-award',             0, 450),
 ('pipeline',       'Pipeline & Demand',     'Resources',  '/pipeline',      'bi-funnel',            0, 460),

 ('notes',          'Notes Vault',           'Knowledge',  '/notes',         'bi-journals',          0, 510),
 ('search',         'Search',                'Knowledge',  '/search',        'bi-search',            0, 520),

 ('people',         'Contacts',              'People',     '/people',        'bi-person-lines-fill', 0, 610),
 ('org_chart',      'Org Chart',             'People',     '/org-chart',     'bi-diagram-2',         0, 620),
 ('performance',    'Performance',           'People',     '/performance',   'bi-clipboard-check',   0, 630),
 ('training',       'Training',              'People',     '/training',      'bi-mortarboard',       0, 640),
 ('innovation',     'Innovation Network',    'People',     '/innovation',    'bi-lightbulb',         0, 650),

 ('email_intake',   'Email Intake',          'Intake',     '/intake',        'bi-envelope',          0, 710),
 ('meeting_import', 'Meeting Import',        'Intake',     '/meetings',      'bi-camera-video',      0, 720),
 ('gal_sync',       'GAL Sync',              'Intake',     '/gal',           'bi-person-rolodex',    0, 730),
 ('smartsheet_sync','Smartsheet Sync',       'Intake',     '/smartsheet',    'bi-table',             0, 740),
 ('drafts',         'Draft Center',          'Intake',     '/drafts',        'bi-pencil-square',     0, 750),

 ('admin',          'Admin',                 'System',     '/admin',         'bi-sliders',           0, 810),
 ('ai_models',      'AI Providers & Models', 'System',     '/ai/models',     'bi-cpu',               0, 820),
 ('ai_queue',       'AI Queue',              'System',     '/ai/queue',      'bi-list-task',         0, 830),
 ('backups',        'Backups',               'System',     '/backups',       'bi-archive',           0, 840),
 ('activity',       'Activity Log',          'System',     '/activity',      'bi-clock-history',     1, 850),
 ('help',           'Help',                  'System',     '/help',          'bi-question-circle',   0, 860);
