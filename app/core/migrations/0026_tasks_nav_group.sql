-- 0026 — Fix Tasks sidebar grouping
--
-- Tasks was seeded into the 'Command' nav_group alongside Command Center
-- (0001_init.sql), so it rendered as a sibling of Command Center in the
-- sidebar instead of under Work, where the hierarchy is Command Center >
-- Work (Portfolios > Projects & Workstreams > Tasks). Move it into 'Work'
-- with a sort_order after Portfolios (110) and Projects & Workstreams (120)
-- but before Portfolio Timeline (130).
--
-- The runner supplies BEGIN and COMMIT. Do not add transaction control here.

UPDATE module_registry
SET nav_group = 'Work', sort_order = 125
WHERE module_key = 'tasks';
