-- Migration: Add composite index for agent_id + state queries
-- Purpose: Optimize common query pattern in get_session_by_agent() and similar
--
-- The existing V1_18 migration created separate indexes on agent_id and state,
-- but queries like:
--   SELECT ... WHERE agent_id = ? AND state IN ('active', 'suspended')
-- benefit more from a composite index that can be scanned in a single operation
-- rather than requiring MySQL to do index intersection.

CREATE INDEX idx_agent_state ON agent_sessions(agent_id, state);
