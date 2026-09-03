-- 0008 — Team Roles
-- docs/DATABASE_SCHEMA.md §0008
--
-- The Projects → Team tab links a person to a project through entity_links
-- (source_type='project', target_type='person'), using link_label as the
-- role. The original UNIQUE (source_type, source_id, target_type, target_id)
-- from §0001 treated link_label as irrelevant, so re-linking the same person
-- under a second role hit INSERT OR IGNORE and silently did nothing — one
-- person could hold at most one role, ever, on a given project. This widens
-- the constraint so the same pair of entities can carry more than one link,
-- each with a distinct link_label, and seeds a controlled vocabulary for the
-- role field in place of free text.
--
-- SQLite has no ALTER TABLE ... ADD CONSTRAINT, so this is the standard
-- table-rebuild pattern: build the new shape under a temporary name, copy
-- every row across unchanged, drop the old table, rename the new one into
-- place, then recreate its indexes. No row is dropped or altered — only the
-- constraint they are checked against.
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

CREATE TABLE entity_links_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id   INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    link_label  TEXT,
    created_at  DATETIME NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source_type, source_id, target_type, target_id, link_label)
);

INSERT INTO entity_links_new (id, source_type, source_id, target_type, target_id, link_label, created_at)
SELECT id, source_type, source_id, target_type, target_id, link_label, created_at FROM entity_links;

DROP TABLE entity_links;

ALTER TABLE entity_links_new RENAME TO entity_links;

CREATE INDEX IF NOT EXISTS idx_links_source ON entity_links(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_links_target ON entity_links(target_type, target_id);

INSERT INTO config_options (option_set, value, label, sort_order) VALUES
 ('team_role', 'Project Lead Partner',  'Project Lead Partner',  10),
 ('team_role', 'Project Lead Director', 'Project Lead Director', 20),
 ('team_role', 'Engagement Manager',    'Engagement Manager',    30),
 ('team_role', 'Workstream Lead',       'Workstream Lead',       40),
 ('team_role', 'Task Owner',            'Task Owner',            50),
 ('team_role', 'Other',                 'Other',                 60);
