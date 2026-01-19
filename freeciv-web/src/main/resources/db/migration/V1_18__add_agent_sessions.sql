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

-- Auto-cleanup expired sessions every 5 minutes
-- This mirrors the in-memory cleanup_expired_sessions() behavior
-- Removes sessions that are:
--   1. Past their expiration time
--   2. Already marked as expired or terminated
CREATE EVENT IF NOT EXISTS agent_sessions_cleanup
  ON SCHEDULE EVERY 5 MINUTE
  DO DELETE FROM agent_sessions
     WHERE expires_at < NOW()
     OR state IN ('expired', 'terminated');
