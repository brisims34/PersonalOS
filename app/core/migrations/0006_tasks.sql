-- 0006 — Tasks
-- docs/DATABASE_SCHEMA.md §0006
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

CREATE TABLE tasks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    description    TEXT,
    task_type      TEXT NOT NULL DEFAULT 'my_task'
                   CHECK (task_type IN ('my_task','follow_up','delegated','waiting_on')),
    status         TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open','in_progress','blocked','completed','cancelled')),
    priority       TEXT NOT NULL DEFAULT 'medium'
                   CHECK (priority IN ('high','medium','low')),
    due_date       DATE,
    start_date     DATE,
    completed_at   DATETIME,
    project_id     INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    workstream_id  INTEGER REFERENCES workstreams(id) ON DELETE SET NULL,
    charge_code_id INTEGER REFERENCES charge_codes(id) ON DELETE SET NULL,
    assignee_person_id INTEGER REFERENCES people(id) ON DELETE SET NULL,
    estimate_hours REAL,
    source         TEXT NOT NULL DEFAULT 'manual'
                   CHECK (source IN ('manual','email','meeting','template','quick_step','ai_proposal')),
    source_ref     TEXT,
    recurrence_id  INTEGER,
    sort_order     INTEGER NOT NULL DEFAULT 0,
    created_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    updated_at     DATETIME NOT NULL DEFAULT (datetime('now')),
    archived_at    DATETIME
);

CREATE INDEX idx_tasks_status   ON tasks(status);

CREATE INDEX idx_tasks_due      ON tasks(due_date);

CREATE INDEX idx_tasks_project  ON tasks(project_id);

CREATE INDEX idx_tasks_assignee ON tasks(assignee_person_id);

CREATE INDEX idx_tasks_archived ON tasks(archived_at);

CREATE TABLE task_recurrences (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    template_title TEXT NOT NULL,
    rrule         TEXT NOT NULL,
    next_due      DATE,
    until_date    DATE,
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    payload_json  TEXT NOT NULL,
    created_at    DATETIME NOT NULL DEFAULT (datetime('now'))
);


-- Phase 4 modules.
UPDATE module_registry SET is_enabled = 1 WHERE module_key = 'tasks';
