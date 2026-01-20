-- Migration: Add composite index for game_allocations
-- Purpose: Add composite index for the common query pattern (game_id + released_at)
--
-- The composite index improves performance for:
--   SELECT ... WHERE game_id = ? AND released_at IS NULL (reconnection check)
--   UPDATE ... WHERE game_id = ? AND released_at IS NULL (release by game_id)

-- Add composite index for common query pattern
-- This is more efficient than using two separate indexes for multi-column conditions
CREATE INDEX idx_game_released ON game_allocations(game_id, released_at);

-- NOTE: Automatic cleanup via MySQL Event Scheduler was removed because:
-- 1. Cloud SQL requires special configuration to enable Event Scheduler
-- 2. The EVENT privilege may not be available in all environments
-- 3. Old released allocations are harmless - they're just historical records
-- If cleanup is needed, it can be done via a scheduled Cloud Function or
-- manual SQL: DELETE FROM game_allocations WHERE released_at < DATE_SUB(NOW(), INTERVAL 7 DAY);
