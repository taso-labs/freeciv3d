-- Migration: Add index on last_seen column for stale allocation cleanup
-- Purpose: The ServerAllocator.cleanupStaleAllocations() method queries
-- game_allocations WHERE last_seen < DATE_SUB(NOW(), INTERVAL X MINUTE)
-- Without an index, this causes a full table scan on every allocation request.
--
-- Note: Using a stored procedure to handle IF NOT EXISTS since MySQL doesn't
-- support CREATE INDEX IF NOT EXISTS directly. This makes the migration
-- idempotent in case it needs to be re-run or was applied manually.

DROP PROCEDURE IF EXISTS add_last_seen_index;

DELIMITER //

CREATE PROCEDURE add_last_seen_index()
BEGIN
    DECLARE index_exists INT DEFAULT 0;

    -- Check if index already exists
    SELECT COUNT(*) INTO index_exists
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'game_allocations'
      AND INDEX_NAME = 'idx_last_seen';

    -- Only create if it doesn't exist
    IF index_exists = 0 THEN
        CREATE INDEX idx_last_seen ON game_allocations(last_seen);
    END IF;
END //

DELIMITER ;

-- Execute the procedure
CALL add_last_seen_index();

-- Clean up the procedure
DROP PROCEDURE IF EXISTS add_last_seen_index;
