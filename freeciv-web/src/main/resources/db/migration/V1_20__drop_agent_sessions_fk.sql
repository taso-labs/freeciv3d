-- Migration: Remove FK constraint from agent_sessions (if it exists)
-- Purpose: Allow session creation even when game allocation fails
--
-- The FK constraint (agent_sessions_ibfk_1) caused connection failures when:
-- 1. /meta/allocate returns 404/503 (no game_allocations record created)
-- 2. Proxy tries to create agent_sessions with that game_id
-- 3. FK constraint fails → session creation fails → E120 error
--
-- game_id is now a soft reference - application code handles the relationship.
--
-- NOTE: This migration is idempotent. The FK may not exist if:
-- - Fresh install with updated V1_18 (no FK created)
-- - FK was already manually dropped

-- Use a procedure to conditionally drop the FK
DELIMITER //
CREATE PROCEDURE drop_fk_if_exists()
BEGIN
    DECLARE fk_exists INT DEFAULT 0;

    SELECT COUNT(*) INTO fk_exists
    FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'agent_sessions'
      AND CONSTRAINT_NAME = 'agent_sessions_ibfk_1'
      AND CONSTRAINT_TYPE = 'FOREIGN KEY';

    IF fk_exists > 0 THEN
        ALTER TABLE agent_sessions DROP FOREIGN KEY agent_sessions_ibfk_1;
    END IF;
END //
DELIMITER ;

CALL drop_fk_if_exists();
DROP PROCEDURE IF EXISTS drop_fk_if_exists;
