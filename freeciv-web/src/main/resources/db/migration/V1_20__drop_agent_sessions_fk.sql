-- Migration: Remove FK constraint from agent_sessions
-- Purpose: Allow session creation even when game allocation fails
--
-- The FK constraint (agent_sessions_ibfk_1) caused connection failures when:
-- 1. /meta/allocate returns 404/503 (no game_allocations record created)
-- 2. Proxy tries to create agent_sessions with that game_id
-- 3. FK constraint fails → session creation fails → E120 error
--
-- game_id is now a soft reference - application code handles the relationship.

ALTER TABLE agent_sessions DROP FOREIGN KEY agent_sessions_ibfk_1;
