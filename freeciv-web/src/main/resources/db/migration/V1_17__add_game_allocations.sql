-- Migration: Add game_allocations table for game-port persistence
-- Purpose: Enable reconnection to the same port by tracking game_id -> port mappings
-- This prevents the issue where reconnecting agents get assigned a different port
-- and connect to a fresh game instead of their ongoing game.

CREATE TABLE IF NOT EXISTS game_allocations (
  game_id VARCHAR(64) NOT NULL PRIMARY KEY,
  port INT NOT NULL,
  host VARCHAR(255) NOT NULL DEFAULT 'localhost',
  allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  released_at TIMESTAMP NULL,
  last_seen TIMESTAMP NULL,
  INDEX idx_port (port),
  INDEX idx_allocated_at (allocated_at),
  INDEX idx_released_at (released_at)
);

-- Comment on table explaining its purpose
-- game_allocations persists the mapping between game IDs (from LLM agent clients)
-- and the civserver port allocated for that game. When an agent reconnects,
-- ServerAllocator checks this table first to return the same port.
