-- A card's fiscal year was implied by its entries' dates rather than recorded,
-- which is why the rates index groups entries by effective_from to make a year
-- read as one block. Recording it makes "which year is this card for" a
-- question the database can answer.
--
-- The card's range decides which entries apply: an entry's window is
-- intersected with its card's, so there is one window and not two competing
-- date filters. See docs/FINANCIAL_MODEL.md §2.
ALTER TABLE rate_cards ADD COLUMN fiscal_year    INTEGER;
ALTER TABLE rate_cards ADD COLUMN effective_from DATE;
ALTER TABLE rate_cards ADD COLUMN effective_to   DATE;

-- Backfill the year for display only, from the earliest entry on each card.
-- The fiscal year starts on the month-day in app_settings.fiscal_year_start
-- (seeded 10-01), so an entry dated on or after that belongs to the NEXT
-- numbered year: 1 Oct 2025 is the first day of FY2026.
UPDATE rate_cards
   SET fiscal_year = (
       SELECT CAST(strftime('%Y', MIN(e.effective_from)) AS INTEGER)
              + (CASE WHEN strftime('%m-%d', MIN(e.effective_from))
                           >= (SELECT value FROM app_settings
                                WHERE key = 'fiscal_year_start')
                      THEN 1 ELSE 0 END)
         FROM rate_card_entries e
        WHERE e.rate_card_id = rate_cards.id
   )
 WHERE fiscal_year IS NULL;

-- The date columns are deliberately left NULL. A NULL bound is unbounded, so
-- every card keeps pricing exactly what it priced before this ran. Setting a
-- real range is then a deliberate act, card by card.
