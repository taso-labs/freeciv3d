-- Migration: Add agent_sessions table for session persistence
-- Purpose: Enable session recovery after freeciv-proxy restarts
-- Previously sessions were stored only in-memory, meaning a proxy restart
-- would lose all active sessions and force agents to re-authenticate.

CREATE TABLE IF NOT EXISTS agent_sessions (
  session_id VARCHAR(64) NOT NULL PRIMARY KEY,
  agent_id VARCHAR(64) NOT NULL,
  game_id VARCHAR(64),
  api_token_hash VARCHAR(256) NOT NULL,
  player_id INT,
  civserver_port INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  state ENUM('active', 'suspended', 'expired', 'terminated') DEFAULT 'active',
  connection_count INT DEFAULT 0,
  resume_attempts INT DEFAULT 0,

  -- Indexes for common query patterns
  INDEX idx_agent_id (agent_id),
  INDEX idx_game_id (game_id),
  INDEX idx_expires_at (expires_at),
  INDEX idx_state (state)

  -- NOTE: No FK constraint on game_id intentionally.
  -- game_id is a soft reference to game_allocations.game_id.
  -- This allows session creation even when allocation fails (404, 503, etc.)
  -- The application code handles the relationship, enabling graceful degradation.
);

-- NOTE: Automatic cleanup via MySQL Event Scheduler was removed because:
-- 1. Cloud SQL requires special configuration to enable Event Scheduler
-- 2. The EVENT privilege may not be available in all environments
-- 3. Application-level cleanup in session_manager.py handles this already
-- The Python cleanup_expired_sessions() method runs periodically and removes:
--   - Sessions past their expiration time
--   - Sessions marked as expired or terminated
