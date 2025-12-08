# LLM WebSocket Protocol - Error Code Reference

Quick reference for all error codes in the LLM WebSocket Protocol. For full protocol documentation, see [llm_websocket_protocol.md](llm_websocket_protocol.md).

**Version**: 2.0.1 | **Last Updated**: November 29, 2025

## Error Response Format

All errors follow this structure:

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "original-request-id",
  "data": {
    "code": "E1XX",
    "message": "Human-readable error description",
    "details": {
      "field": "specific_field",
      "reason": "machine_readable_reason",
      "can_retry": true
    }
  }
}
```

---

## Error Code Summary

### System & Connection Errors (E1xx)

| Code | Name                   | Description                                  | Retry?                             |
| ---- | ---------------------- | -------------------------------------------- | ---------------------------------- |
| E101 | Missing Required Field | A required field is missing from the message | No - fix request                   |
| E102 | Invalid API Token      | The provided API token is invalid or expired | No - get new token                 |
| E103 | Unknown Message Type   | The message type is not recognized           | No - fix request                   |
| E120 | Not Authenticated      | Session expired or not yet authenticated     | Yes - reconnect and reauthenticate |
| E121 | State Query Failed     | Failed to retrieve game state                | Yes - retry with backoff           |
| E123 | Connection Lost        | Connection to game server was lost           | Yes - reconnect                    |

### Action Validation Errors (E13x)

| Code | Name                     | Description                           | Retry?                    |
| ---- | ------------------------ | ------------------------------------- | ------------------------- |
| E130 | Action Validation Failed | Action failed game rule validation    | No - action not allowed   |
| E131 | Action Execution Failed  | Action was valid but execution failed | Maybe - query state first |

### Input Validation Errors (E22x)

| Code | Name                   | Description                                            | Retry?              |
| ---- | ---------------------- | ------------------------------------------------------ | ------------------- |
| E220 | Missing Required Field | Action-specific required field missing                 | No - fix request    |
| E221 | Invalid Field Type     | Wrong data type provided (e.g., string instead of int) | No - fix request    |
| E222 | Value Out of Range     | Numeric value outside valid range                      | No - fix request    |
| E223 | Invalid Characters     | Dangerous characters detected (SQL injection, XSS)     | No - sanitize input |
| E224 | String Too Long        | String exceeds maximum length                          | No - shorten string |

### Unit Validation Errors (E23x)

| Code | Name                  | Description                            | Retry?                           |
| ---- | --------------------- | -------------------------------------- | -------------------------------- |
| E230 | Unit Not Found        | The specified unit does not exist      | No - query state for valid units |
| E231 | Unit Not Owned        | Unit exists but is not owned by player | No - check ownership             |
| E232 | Unit Busy             | Unit is busy or has no moves remaining | No - wait for next turn          |
| E233 | Insufficient Movement | Unit lacks movement points for action  | No - wait for next turn          |
| E234 | Missing Capability    | Unit lacks capability for this action  | No - use different unit type     |

### City Validation Errors (E24x)

| Code | Name             | Description                                    | Retry?                            |
| ---- | ---------------- | ---------------------------------------------- | --------------------------------- |
| E240 | City Not Found   | The specified city does not exist              | No - query state for valid cities |
| E241 | City Not Owned   | City exists but is not owned by player         | No - check ownership              |
| E242 | City at Capacity | City cannot accept more (e.g., max population) | No - city limit reached           |

### Target Validation Errors (E25x)

| Code | Name                   | Description                               | Retry?                         |
| ---- | ---------------------- | ----------------------------------------- | ------------------------------ |
| E250 | Insufficient Resources | Not enough gold or resources              | No - wait for more resources   |
| E251 | Invalid Coordinates    | Coordinates are malformed or out of range | No - fix coordinates           |
| E252 | Target Out of Range    | Target is too far from actor              | No - move actor closer         |
| E253 | Target Not Visible     | Target is in fog of war                   | No - explore first             |
| E254 | Terrain Incompatible   | Terrain doesn't support this action       | No - choose different location |

### Diplomacy Errors (E26x)

| Code | Name                      | Description                               | Retry?                       |
| ---- | ------------------------- | ----------------------------------------- | ---------------------------- |
| E260 | Player Not Found          | Target player does not exist              | No - query state for players |
| E261 | Diplomatic Action Invalid | Action not allowed (e.g., already at war) | No - check diplomatic state  |
| E262 | Treaty Exists             | Treaty already exists with this player    | No - cancel existing first   |
| E263 | No Pending Treaty         | No treaty proposal to accept/reject       | No - wait for proposal       |
| E264 | Invalid Diplomatic State  | Current state doesn't allow this action   | No - check prerequisites     |

### Server Errors (E4xx, E5xx)

| Code | Name                  | Description                                | Retry?                       |
| ---- | --------------------- | ------------------------------------------ | ---------------------------- |
| E429 | Rate Limit Exceeded   | Too many requests; honor `retry_after`     | Yes - wait for `retry_after` |
| E500 | Internal Server Error | Unexpected server error                    | Yes - retry with backoff     |
| E503 | Query Timeout         | Server didn't respond in time              | Yes - retry with backoff     |
| E999 | Unknown Error         | Unclassified error with diagnostic context | Maybe - check details        |

---

## Common Error Examples

### E102 - Invalid API Token

**Cause**: Authentication failed due to invalid, expired, or missing token.

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "code": "E102",
    "message": "Invalid API token",
    "details": {
      "reason": "token_expired",
      "can_retry": false
    }
  }
}
```

**Resolution**: Obtain a new API token and reconnect.

---

### E120 - Session Expired

**Cause**: Session timed out due to inactivity or server restart.

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "code": "E120",
    "message": "Session expired - please reauthenticate",
    "details": {
      "session_valid": false,
      "civserver_connected": true,
      "reason": "session_expired_after_disconnect",
      "can_retry": true
    }
  }
}
```

**Resolution**: Reconnect with the same `agent_id` and send `llm_connect` message. If within 60-second resumption window, session state is preserved.

---

### E223 - Invalid Characters (Security)

**Cause**: Input contains SQL injection or XSS patterns.

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "code": "E223",
    "message": "Invalid characters in string field",
    "details": {
      "field": "target.name",
      "reason": "SQL injection pattern detected",
      "detected_patterns": ["DROP", "--"]
    }
  }
}
```

**Resolution**: Sanitize input. Allowed characters vary by field—see Input Validation Rules in main protocol doc.

---

### E224 - String Too Long

**Cause**: String exceeds maximum allowed length.

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "code": "E224",
    "message": "String exceeds maximum length",
    "details": {
      "field": "target.name",
      "max_length": 50,
      "actual_length": 68
    }
  }
}
```

**Resolution**: Shorten the string. Max lengths: city names (50), buildings (30), tech (50), messages (256), agent_id (50).

---

### E230 - Unit Not Found

**Cause**: The specified `unit_id` does not exist or is no longer valid.

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "action-123",
  "data": {
    "code": "E230",
    "message": "Unit not found",
    "details": {
      "unit_id": 999,
      "reason": "unit_does_not_exist"
    }
  }
}
```

**Resolution**: Query current game state to get valid unit IDs. Units may have been destroyed or disbanded.

---

### E251 - Invalid Coordinates

**Cause**: Coordinates are out of valid range or malformed.

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "code": "E251",
    "message": "Invalid coordinates",
    "details": {
      "field": "target",
      "x": -5,
      "y": 20,
      "reason": "negative_coordinate_not_allowed",
      "valid_range": "0 to map_width-1"
    }
  }
}
```

**Resolution**: Use non-negative coordinates within map bounds. Query state to determine map dimensions.

---

### E429 - Rate Limit Exceeded

**Cause**: Too many messages sent within the rate limit window.

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "code": "E429",
    "message": "Rate limit exceeded",
    "details": {
      "reason": "Request rate limit exceeded",
      "retry_after": 58.5,
      "grace_period": {
        "violations": 4,
        "max_violations": 3,
        "remaining_violations": 0,
        "will_reset_in": 0
      },
      "remaining_limits": {
        "requests_per_minute": {
          "remaining": 0,
          "reset_time": 1234567950.0
        }
      }
    }
  }
}
```

**Resolution**: Wait for `retry_after` seconds before sending more requests. Implement request batching and caching.

---

### E503 - Query Timeout

**Cause**: Server didn't respond within the timeout window.

```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "query-456",
  "data": {
    "code": "E503",
    "message": "Query timeout - server did not respond in time",
    "details": {
      "timeout_seconds": 15,
      "query_type": "state_query",
      "can_retry": true
    }
  }
}
```

**Resolution**: Retry with exponential backoff. For state queries: 3 attempts (0s, 2s, 4s delay). For action queries: single retry after 2s. For action execution: do NOT auto-retry—query state first to check if action was applied.

---

## Retry Strategy Quick Reference

| Error Type         | Strategy                                                        |
| ------------------ | --------------------------------------------------------------- |
| E120 (Session)     | Reconnect immediately, reauthenticate                           |
| E429 (Rate Limit)  | Wait `retry_after` seconds exactly                              |
| E503 (Timeout)     | Exponential backoff: 0s, 2s, 4s (max 3 attempts)                |
| E500 (Server)      | Exponential backoff: 1s, 2s, 4s (max 3 attempts)                |
| E123 (Connection)  | Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (max 10 attempts) |
| E22x (Validation)  | Do not retry—fix the request                                    |
| E23x/E24x (Entity) | Do not retry—query state for valid entities                     |
| E25x (Target)      | Do not retry—change target or wait                              |
| E26x (Diplomacy)   | Do not retry—check diplomatic state                             |

---

## See Also

- [LLM WebSocket Protocol Specification](llm_websocket_protocol.md) - Full protocol documentation
- Input Validation Rules section for field constraints
- Rate Limiting section for limit configuration
- Timeout Specifications for retry strategies
