-- Migration: Add index on last_seen column for stale allocation cleanup
-- Purpose: The ServerAllocator.cleanupStaleAllocations() method queries
-- game_allocations WHERE last_seen < DATE_SUB(NOW(), INTERVAL X MINUTE)
-- Without an index, this causes a full table scan on every allocation request.

CREATE INDEX idx_last_seen ON game_allocations(last_seen);
