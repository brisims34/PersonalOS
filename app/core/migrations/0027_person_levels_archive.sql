-- Retiring a level must never unprice history. Archiving hides it from the
-- pickers while every rate_card_entry and person_level_history row that
-- references it stays exactly as it was, so a card written last year still
-- prices last year's hours. Deletion stays available only for a level
-- nothing has ever referenced.
ALTER TABLE person_levels ADD COLUMN archived_at DATETIME;
