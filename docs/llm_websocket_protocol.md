# LLM WebSocket Protocol Specification

## Overview

This document specifies the WebSocket protocol for LLM agent communication between Game Arena and FreeCiv3D. The protocol enables reliable, bidirectional communication for LLM-driven gameplay.

**Version**: 1.0.0
**Date**: September 18, 2025

## Architecture

```
Game Arena → LLM Gateway (port 8003) → FreeCiv Proxy (port 8002) → FreeCiv Server
```

## Protocol Design

### Collection Format

All collections (units, cities, players) are returned as **dictionaries keyed by ID** for efficient access:

**Example State Response:**
```json
{
  "status": "success",
  "data": {
    "units": {
      "123": {"id": 123, "type": "Warrior", "owner": 0, "moves_left": 1},
      "456": {"id": 456, "type": "Settler", "owner": 0, "moves_left": 3}
    },
    "cities": {
      "1": {"id": 1, "name": "Capital", "owner": 0, "size": 5}
    },
    "players": {
      "0": {"id": 0, "name": "player1", "nation": "Romans", "gold": 50}
    }
  }
}
```

**Key Design Decisions:**

1. **Dictionary Keys are Strings**
   For JSON compatibility, all keys are strings (not integers).
   Example: Unit with `id: 123` is accessed via `state.units["123"]`

2. **O(1) Access by ID**
   Direct lookup by ID instead of O(n) array filtering:
   ```python
   # Efficient dictionary access
   warrior = state['units']['123']

   # vs slow list iteration
   warrior = next(u for u in state['units'] if u['id'] == 123)
   ```

3. **Type Normalization**
   Human-readable strings for LLM comprehension:
   - `nation`: "Romans" instead of integer ID `5`
   - `activity`: "idle" instead of enum value `0`

**Accessing Collections:**
```python
# Get specific unit
unit = state['units'].get('123')

# Iterate all units
for unit_id, unit in state['units'].items():
    process(unit)

# Get all units as list
all_units = list(state['units'].values())
```

## Connection Flow

1. **Agent Connection**: LLM agent connects to `/ws/agent/{agent_id}` on LLM Gateway
2. **Authentication**: Agent sends `llm_connect` message with API token
3. **Gateway Registration**: Gateway registers agent and connects to FreeCiv proxy
4. **Game Communication**: Agent can send state queries and actions
5. **Disconnection**: Graceful cleanup when agent disconnects

## Message Format

All messages follow this structure:

```json
{
  "type": "message_type",
  "agent_id": "agent_identifier",
  "timestamp": 1234567890.123,
  "data": { /* message-specific data */ },
  "correlation_id": "optional_correlation_id"
}
```

### Required Fields
- `type`: Message type (see Message Types below)
- `agent_id`: Unique identifier for the LLM agent
- `timestamp`: Unix timestamp with millisecond precision
- `data`: Message payload (structure varies by type)

### Optional Fields
- `correlation_id`: For request/response correlation in async operations

## Message Types

### 1. Connection Management

#### LLM_CONNECT (Request)
```json
{
  "type": "llm_connect",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "api_token": "secret_api_key",
    "model": "gpt-4",
    "game_id": "game-123",
    "capabilities": ["move", "build", "research"]
  }
}
```

#### AUTH_SUCCESS (Response)
```json
{
  "type": "llm_connect",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "data": {
    "type": "auth_success",
    "success": true,
    "session_id": "session-456",
    "player_id": 1,
    "game_id": "game-123",
    "session_expires_in": 3600
  }
}
```

### 2. Game State Queries

#### STATE_QUERY (Request)
```json
{
  "type": "state_query",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "query-789",
  "data": {
    "format": "llm_optimized",
    "include_legal_actions": true,
    "since_turn": 10
  }
}
```

**Format Options:**
- `full`: Complete game state with all details
- `delta`: Changes since last query
- `llm_optimized`: Compressed state optimized for LLM consumption

#### STATE_UPDATE (Response)
```json
{
  "type": "state_update",
  "agent_id": "my-agent",
  "timestamp": 1234567890.125,
  "correlation_id": "query-789",
  "data": {
    "type": "state_response",
    "format": "llm_optimized",
    "data": {
      "turn": 15,
      "phase": "movement",
      "strategic_summary": {
        "cities_count": 3,
        "units_count": 8,
        "tech_progress": "developing"
      },
      "immediate_priorities": ["explore", "build_military"],
      "threats": [],
      "opportunities": [
        {
          "type": "expansion",
          "description": "Good settlement location at (25, 30)",
          "priority": "high"
        }
      ],
      "players": {
        "1": {
          "id": 1,
          "name": "Player 1",
          "nation": "Romans",
          "score": 150
        }
      },
      "units": {
        "42": {
          "id": 42,
          "type": "warrior",
          "activity": "idle",
          "x": 10,
          "y": 20
        }
      },
      "cities": {
        "1": {
          "id": 1,
          "name": "Capital",
          "population": 3
        }
      },
      "legal_actions": [
        {
          "type": "unit_move",
          "unit_id": 42,
          "target": {"x": 11, "y": 21},
          "priority": "medium"
        }
      ]
    }
  }
}
```

**Note**: The `players`, `units`, and `cities` fields are always returned as **dictionaries** (objects) keyed by ID, not arrays. This provides efficient O(1) lookups by ID.

### 3. Action Submission

#### ACTION (Request)
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "action-456",
  "data": {
    "action_type": "unit_move",
    "actor_id": 42,
    "target": {"x": 11, "y": 21},
    "parameters": {"validate": true}
  }
}
```

**Action Types:**
- `unit_move`: Move unit to coordinates
- `unit_attack`: Attack target unit/city
- `unit_build_city`: Build city at current location
- `unit_explore`: Set unit to auto-explore
- `unit_fortify`: Fortify unit for defensive bonus
- `unit_sentry`: Put unit on sentry mode (skip turn until enemy nearby)
- `unit_build_road`: Build road at specified coordinates
- `unit_build_irrigation`: Build irrigation at specified coordinates
- `unit_build_mine`: Build mine at specified coordinates
- `city_production`: Set city production
- `city_build_unit`: Build specific unit type
- `city_build_improvement`: Build city improvement
- `tech_research`: Research technology
- `diplomacy_message`: Send diplomatic message
- `end_turn`: End current turn

#### ACTION_RESULT (Response)
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.126,
  "correlation_id": "action-456",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "unit_move",
    "result": {
      "action_id": "exec-789",
      "state_change": {
        "unit_moved": true,
        "new_position": {"x": 11, "y": 21}
      }
    }
  }
}
```

### 4. Turn Management

#### TURN_START
```json
{
  "type": "turn_start",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "turn": 16,
    "phase": "movement",
    "time_limit": 300,
    "active_player": 1
  }
}
```

#### TURN_END
```json
{
  "type": "turn_end",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "turn": 15,
    "next_player": 2,
    "turn_summary": {
      "actions_taken": 5,
      "units_moved": 3
    }
  }
}
```

### 5. Heartbeat

#### PING
```json
{
  "type": "ping",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {}
}
```

#### PONG (Response)
```json
{
  "type": "pong",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124
}
```

### 6. Error Handling

#### ERROR (Response)
```json
{
  "type": "error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "original-request-id",
  "data": {
    "type": "error",
    "success": false,
    "code": "E120",
    "message": "Session expired - please reauthenticate",
    "details": {
      "session_valid": false,
      "civserver_connected": true,
      "player_id": null,
      "reason": "session_expired_after_disconnect",
      "can_retry": true
    }
  }
}
```

**Enhanced Error Response Fields:**
- `code`: Specific error code (E120, E123, E429, E999, etc.)
- `message`: Human-readable error description
- `details`: Context object with diagnostic information:
  - `session_valid`: Whether the session is still valid
  - `civserver_connected`: Whether connected to game server
  - `player_id`: Current player ID (if assigned)
  - `reason`: Machine-readable reason code
  - `can_retry`: Whether the operation can be retried
  - `exception_type`: Type of exception (for E999 errors)

**Rate Limit Error Example:**
```json
{
  "type": "rate_limit_error",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "type": "error",
    "success": false,
    "code": "E429",
    "message": "Rate limit exceeded: Request rate limit exceeded",
    "details": {
      "reason": "Request rate limit exceeded",
      "retry_after": 1.0,
      "grace_period": {
        "violations": 2,
        "max_violations": 3,
        "remaining_violations": 1,
        "will_reset_in": 15.3
      },
      "remaining_limits": {
        "requests_per_minute": {
          "remaining": 45,
          "reset_time": 1234567920.0
        }
      }
    }
  }
}
```

**Error Codes:**
- `E101`: Missing required field
- `E102`: Authentication Session Expired
- `E103`: Unknown message type
- `E120`: Not authenticated (session expired or not yet authenticated)
- `E121`: State query failed
- `E123`: Connection to game server lost
- `E130`: Action validation failed
- `E131`: Action execution failed
- `E429`: Rate limit exceeded (with grace period details)
- `E500`: Internal server error
- `E999`: Unknown error (with diagnostic context)

## Connection Management

### Endpoints

#### LLM Gateway (port 8003)
- **Agent WebSocket**: `ws://localhost:8003/ws/agent/{agent_id}`
- **REST API**: `http://localhost:8003/api/`

#### FreeCiv Proxy (port 8002)
- **LLM WebSocket**: `ws://localhost:8002/llmsocket/8002`

### Authentication

1. **API Token**: Required in `llm_connect` message
2. **Session Management**: Gateway maintains sessions with expiration
3. **Player Assignment**: Gateway assigns player ID upon authentication

### Connection Limits

- **Max Connections per Agent**: 2
- **Max Concurrent Games**: 10 (configurable)
- **Session Timeout**: 600 seconds (10 minutes, configurable)
- **Session Resumption Window**: 60 seconds (after disconnect)
- **Heartbeat Interval**: 30 seconds

## State Formats

### LLM Optimized Format

Compressed state designed for LLM consumption:

```json
{
  "turn": 15,
  "phase": "movement",
  "strategic_summary": {
    "cities_count": 3,
    "units_count": 8,
    "tech_progress": "developing",
    "military_strength": "medium"
  },
  "immediate_priorities": [
    "explore_nearby_areas",
    "build_military_units",
    "research_bronze_working"
  ],
  "threats": [
    {
      "type": "military",
      "description": "Enemy units near Capital",
      "severity": "high",
      "location": {"x": 10, "y": 20}
    }
  ],
  "opportunities": [
    {
      "type": "expansion",
      "description": "Resource tiles available",
      "priority": "high",
      "locations": [{"x": 25, "y": 30, "resource": "wheat"}]
    }
  ]
}
```

### Full Format

Complete game state with all details. **Note**: `players`, `units`, and `cities` are returned as **dictionaries** keyed by ID (not arrays) for efficient lookups:

```json
{
  "turn": 15,
  "phase": "movement",
  "player_id": 1,
  "units": {
    "42": {
      "id": 42,
      "type": "warrior",
      "x": 10, "y": 20,
      "moves_left": 1,
      "hp": 10,
      "owner": 1,
      "activity": "idle",
      "done_moving": false,
      "orders": []
    }
  },
  "cities": {
    "1": {
      "id": 1,
      "name": "Capital",
      "x": 15, "y": 25,
      "population": 3,
      "production": "warrior",
      "owner": 1
    }
  },
  "visible_tiles": [
    {
      "x": 10, "y": 20,
      "terrain": "grassland",
      "resource": "wheat"
    }
  ],
  "players": {
    "1": {
      "id": 1,
      "name": "Player 1",
      "nation": "Romans",
      "score": 150
    },
    "2": {
      "id": 2,
      "name": "Player 2",
      "nation": "Greeks",
      "score": 120
    }
  },
  "technologies": ["pottery", "animal_husbandry"]
}
```

**Field Types**:
- `units[].type`: string (e.g., `"warrior"`, `"settler"`)
- `units[].activity`: string or null (e.g., `"idle"`, `"sentry"`, `"fortified"`, or `null` for no activity)
- `units[].done_moving`: boolean (optional, default `false`). When `true`, unit is executing a multi-turn path (e.g., explorer auto-explore, long goto) and should not be commanded until path completes. Used for conditional `end_turn` logic.
- `units[].orders`: array (optional, default `[]`). List of pending orders/commands for the unit. Non-empty indicates unit is locked into queued actions.
- `players[].nation`: string (e.g., `"Romans"`, `"Americans"`, `"Greeks"`)
- All dictionary keys are strings for JSON compatibility

## Error Handling

### Reconnection Strategy

1. **Automatic Reconnection**: Gateway attempts reconnection on connection loss
2. **Exponential Backoff**: Increasing delays between reconnection attempts
3. **State Preservation**: Session state maintained during brief disconnections

### Validation

1. **Message Validation**: JSON schema validation for all messages
2. **Action Validation**: Game rule validation before execution
3. **Authentication**: Token and session validation for all requests

### Rate Limiting

- **Messages per minute**: 200 (configurable, increased for 2-4 player games)
- **Burst limit**: 40 messages per second (increased to handle turn spikes)
- **Bytes per minute**: 2MB (increased for larger state queries)
- **Grace period**: 30 seconds before blocking
- **Max violations**: 3 violations within grace period before blocking
- **Block duration**: 60 seconds after exceeding max violations

## Usage Examples

### Basic Agent Connection

```python
import asyncio
import websockets
import json

async def connect_agent():
    uri = "ws://localhost:8003/ws/agent/my-agent"

    async with websockets.connect(uri) as websocket:
        # Receive welcome message
        welcome = await websocket.recv()
        print(f"Welcome: {welcome}")

        # Authenticate
        auth_message = {
            "type": "llm_connect",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {
                "api_token": "your_api_token_here",
                "model": "gpt-4",
                "game_id": "game-123"
            }
        }

        await websocket.send(json.dumps(auth_message))
        auth_response = await websocket.recv()
        print(f"Auth: {auth_response}")

        # Query game state
        state_query = {
            "type": "state_query",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "correlation_id": "query-1",
            "data": {
                "format": "llm_optimized",
                "include_legal_actions": True
            }
        }

        await websocket.send(json.dumps(state_query))
        state_response = await websocket.recv()
        print(f"State: {state_response}")

asyncio.run(connect_agent())
```

### Action Submission

```python
async def submit_action(websocket):
    action = {
        "type": "action",
        "agent_id": "my-agent",
        "timestamp": time.time(),
        "correlation_id": "action-1",
        "data": {
            "action_type": "unit_move",
            "actor_id": 42,
            "target": {"x": 11, "y": 21}
        }
    }

    await websocket.send(json.dumps(action))
    result = await websocket.recv()
    print(f"Action result: {result}")
```

### New Unit Actions (v2.0)

The following unit actions were added to provide richer gameplay capabilities:

#### unit_fortify

Fortify a unit to increase defensive strength. Fortified units cannot move but receive defense bonuses.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_fortify",
    "unit_id": 123,
    "player_id": 0
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "data": {
    "success": true,
    "action_type": "unit_fortify",
    "unit_id": 123
  }
}
```

**Error Codes:**
- `E050`: Missing required field `unit_id`
- `E051`: Unit not found
- `E052`: Player does not own this unit

**Notes:**
- Unit must have movement points remaining
- Some unit types cannot fortify (e.g., settlers)
- Fortified units must be unfortified before moving

#### unit_sentry

Put unit on sentry mode. Unit will skip turns until enemy units are nearby.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_sentry",
    "unit_id": 456,
    "player_id": 0
  }
}
```

**Error Codes:**
- `E060`: Missing required field `unit_id`
- `E061`: Unit not found
- `E062`: Player does not own this unit

**Notes:**
- Sentry mode automatically wakes unit when enemies approach
- Useful for border patrol and defensive positions

#### unit_build_road

Build a road at specified coordinates to improve movement speed.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_build_road",
    "unit_id": 789,
    "player_id": 0,
    "x": 10,
    "y": 15
  }
}
```

**Required Fields:**
- `unit_id`: ID of the worker/engineer unit
- `player_id`: Player ID (must match authenticated player)
- `x`: X coordinate (0-199 for default 200x200 map)
- `y`: Y coordinate (0-199 for default 200x200 map)

**Error Codes:**
- `E070`: Missing required field (unit_id, x, or y)
- `E071`: Coordinates must be integers
- `E072`: Coordinates out of bounds
- `E073`: Player does not own this unit
- `E074`: Unit not found

**Notes:**
- Only worker/engineer units can build roads
- Building takes multiple turns depending on terrain
- Roads increase unit movement speed

#### unit_build_irrigation

Build irrigation at specified coordinates to improve food production.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_build_irrigation",
    "unit_id": 789,
    "player_id": 0,
    "x": 12,
    "y": 18
  }
}
```

**Required Fields:**
- `unit_id`: ID of the worker/engineer unit
- `player_id`: Player ID
- `x`, `y`: Coordinates for irrigation

**Error Codes:**
- `E080`: Missing required field
- `E081`: Coordinates must be integers
- `E082`: Coordinates out of bounds
- `E083`: Player does not own this unit
- `E084`: Unit not found

**Notes:**
- Requires water source nearby (river or ocean)
- Increases food output of tile
- Building takes multiple turns

#### unit_build_mine

Build a mine at specified coordinates to improve production.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_build_mine",
    "unit_id": 789,
    "player_id": 0,
    "x": 25,
    "y": 30
  }
}
```

**Required Fields:**
- `unit_id`: ID of the worker/engineer unit
- `player_id`: Player ID
- `x`, `y`: Coordinates for mine

**Error Codes:**
- `E090`: Missing required field
- `E091`: Coordinates must be integers
- `E092`: Coordinates out of bounds
- `E093`: Player does not own this unit
- `E094`: Unit not found

**Notes:**
- Works best on hills and mountains
- Increases production output of tile
- Cannot mine ocean tiles

### Complete Multi-Turn Game Flow Example

This example demonstrates a typical LLM agent gameplay session using the new actions:

```python
import asyncio
import websockets
import json
import time

async def play_game():
    uri = "ws://localhost:8003/ws/agent/my-agent"

    async with websockets.connect(uri) as ws:
        # 1. Authenticate
        await ws.send(json.dumps({
            "type": "llm_connect",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {
                "api_token": "my_secret_key",
                "game_id": "game-123"
            }
        }))

        auth_response = json.loads(await ws.recv())
        print(f"Authenticated: {auth_response['data']['success']}")

        # 2. Get current state
        await ws.send(json.dumps({
            "type": "state_query",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {"format": "llm_optimized"}
        }))

        state = json.loads(await ws.recv())
        units = state['data']['units']  # Dict format: {"123": {...}, "456": {...}}

        # 3. Access specific unit by ID (O(1) lookup)
        settler = units.get('456')
        if settler:
            # Build city with settler
            await ws.send(json.dumps({
                "type": "action",
                "agent_id": "my-agent",
                "timestamp": time.time(),
                "data": {
                    "action_type": "unit_build_city",
                    "unit_id": 456,
                    "player_id": 0,
                    "city_name": "NewCity"
                }
            }))

        # 4. Use worker to build road
        worker = units.get('789')
        if worker:
            await ws.send(json.dumps({
                "type": "action",
                "agent_id": "my-agent",
                "timestamp": time.time(),
                "data": {
                    "action_type": "unit_build_road",
                    "unit_id": 789,
                    "player_id": 0,
                    "x": 10,
                    "y": 15
                }
            }))

        # 5. Fortify warrior for defense
        warrior = units.get('123')
        if warrior:
            await ws.send(json.dumps({
                "type": "action",
                "agent_id": "my-agent",
                "timestamp": time.time(),
                "data": {
                    "action_type": "unit_fortify",
                    "unit_id": 123,
                    "player_id": 0
                }
            }))

        # 6. End turn
        await ws.send(json.dumps({
            "type": "action",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {
                "action_type": "end_turn",
                "player_id": 0
            }
        }))

        # 7. Process state updates
        while True:
            message = json.loads(await ws.recv())
            if message['type'] == 'state_update':
                # Analyze new state (dict format)
                new_units = message['data']['units']
                for unit_id, unit in new_units.items():
                    print(f"Unit {unit_id}: {unit['type']} at ({unit.get('x')}, {unit.get('y')})")
                break

asyncio.run(play_game())
```

## Security Considerations

1. **API Token Authentication**: Required for all agent connections
2. **Origin Validation**: WebSocket origin checking for browser clients
3. **Input Sanitization**: All inputs validated and sanitized
4. **Rate Limiting**: Protection against abuse and DoS attacks
5. **Session Management**: Secure session handling with expiration

## Performance Guidelines

1. **Message Size**: Keep messages under 1MB for optimal performance
2. **Query Frequency**: Limit state queries to essential updates
3. **Batch Actions**: Use batch endpoints for multiple actions
4. **Connection Reuse**: Maintain persistent connections when possible

## Monitoring and Debugging

### Health Check Endpoint
```http
GET http://localhost:8003/health
```

### Metrics Endpoint
```http
GET http://localhost:8003/api/metrics
```

### Log Levels
- `DEBUG`: Detailed protocol messages
- `INFO`: Connection events and state changes
- `WARN`: Validation failures and retries
- `ERROR`: Connection failures and system errors

## Version History

- **1.0.0** (Sept 2025): Initial protocol specification
  - Basic message types for connection, state, and actions
  - WebSocket transport with JSON messaging
  - Authentication and session management
  - Error handling and rate limiting
