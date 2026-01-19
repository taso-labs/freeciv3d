-- Migration: Add cleanup event and composite index for game_allocations
-- Purpose:
--   1. Add composite index for the common query pattern (game_id + released_at)
--   2. Add scheduled cleanup for old released allocation records
--
-- The composite index improves performance for:
--   SELECT ... WHERE game_id = ? AND released_at IS NULL (reconnection check)
--   UPDATE ... WHERE game_id = ? AND released_at IS NULL (release by game_id)
--
-- IMPORTANT: MySQL Event Scheduler must be enabled for cleanup events to work.
-- Check status:  SHOW VARIABLES LIKE 'event_scheduler';
-- Enable:        SET GLOBAL event_scheduler = ON;
-- Grant perms:   GRANT EVENT ON freeciv_web.* TO 'your_user'@'localhost';
-- The Docker setup enables this automatically via init scripts.

-- Add composite index for common query pattern
-- This is more efficient than using two separate indexes for multi-column conditions
CREATE INDEX IF NOT EXISTS idx_game_released
ON game_allocations(game_id, released_at);

-- Cleanup old released allocations (older than 7 days)
-- This mirrors the agent_sessions_cleanup pattern from V1_18
-- Released records are kept for debugging but don't need to persist indefinitely
CREATE EVENT IF NOT EXISTS game_allocations_cleanup
  ON SCHEDULE EVERY 1 HOUR
  DO DELETE FROM game_allocations
     WHERE released_at IS NOT NULL
     AND released_at < DATE_SUB(NOW(), INTERVAL 7 DAY);
