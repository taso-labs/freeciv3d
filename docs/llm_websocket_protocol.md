# LLM WebSocket Protocol Specification

## Overview

This document specifies the WebSocket protocol for LLM agent communication between Game Arena and FreeCiv3D. The protocol enables reliable, bidirectional communication for LLM-driven gameplay.

**Version**: 2.0.0
**Date**: November 29, 2025

## Architecture

```text
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

### 3. Per-Entity Action Queries

These query types allow clients to request available actions for a specific unit or city. The returned actions are complete and directly submittable—clients can send them back as ACTION requests without modification.

#### UNIT_ACTIONS_QUERY (Request)

Query all legal actions available for a specific unit.

```json
{
  "type": "unit_actions_query",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "unit-query-001",
  "data": {
    "unit_id": 42
  }
}
```

#### UNIT_ACTIONS_RESPONSE (Response)

Returns a flat list of all legal actions the unit can perform. Each action object is complete and can be directly submitted as an ACTION request.

```json
{
  "type": "unit_actions_response",
  "agent_id": "my-agent",
  "timestamp": 1234567890.125,
  "correlation_id": "unit-query-001",
  "data": {
    "success": true,
    "unit_id": 42,
    "actions": [
      {
        "action_type": "unit_move",
        "actor_id": 42,
        "target": {"x": 11, "y": 21}
      },
      {
        "action_type": "unit_move",
        "actor_id": 42,
        "target": {"x": 10, "y": 21}
      },
      {
        "action_type": "unit_fortify",
        "actor_id": 42
      },
      {
        "action_type": "unit_sentry",
        "actor_id": 42
      },
      {
        "action_type": "unit_attack",
        "actor_id": 42,
        "target": {"unit_id": 99}
      }
    ]
  }
}
```

**Usage Pattern:**

```python
# 1. Query actions for a unit
await ws.send(json.dumps({
    "type": "unit_actions_query",
    "agent_id": "my-agent",
    "timestamp": time.time(),
    "data": {"unit_id": 42}
}))

response = json.loads(await ws.recv())
actions = response['data']['actions']

# 2. Pick an action and submit it directly
chosen_action = actions[0]  # e.g., {"action_type": "unit_move", "actor_id": 42, "target": {"x": 11, "y": 21}}

await ws.send(json.dumps({
    "type": "action",
    "agent_id": "my-agent",
    "timestamp": time.time(),
    "data": chosen_action  # Send directly without modification
}))
```

**Error Codes:**

- `E230`: Unit not found
- `E231`: Unit not owned by player
- `E503`: Query timeout (server did not respond in time)

#### CITY_ACTIONS_QUERY (Request)

Query all legal actions available for a specific city.

```json
{
  "type": "city_actions_query",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "city-query-001",
  "data": {
    "city_id": 5
  }
}
```

#### CITY_ACTIONS_RESPONSE (Response)

Returns a flat list of all legal actions for the city.

```json
{
  "type": "city_actions_response",
  "agent_id": "my-agent",
  "timestamp": 1234567890.125,
  "correlation_id": "city-query-001",
  "data": {
    "success": true,
    "city_id": 5,
    "actions": [
      {
        "action_type": "city_production",
        "actor_id": 5,
        "target": {"production": "Warrior"}
      },
      {
        "action_type": "city_production",
        "actor_id": 5,
        "target": {"production": "Settler"}
      },
      {
        "action_type": "city_production",
        "actor_id": 5,
        "target": {"production": "Granary"}
      },
      {
        "action_type": "city_buy",
        "actor_id": 5
      },
      {
        "action_type": "city_sell_improvement",
        "actor_id": 5,
        "target": {"improvement": "Barracks"}
      }
    ]
  }
}
```

**Error Codes:**

- `E240`: City not found
- `E241`: City not owned by player
- `E503`: Query timeout (server did not respond in time)

### 4. Action Submission

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
    "target": {"x": 11, "y": 21}
  }
}
```

#### Action Request Fields

| Field         | Type    | Required | Description                                                  |
| ------------- | ------- | -------- | ------------------------------------------------------------ |
| `action_type` | string  | Yes      | The type of action to perform                                |
| `actor_id`    | integer | Yes      | ID of the unit or city performing the action                 |
| `target`      | object  | Varies   | Target of the action (coordinates, unit, city, or player)    |
| `sub_target`  | object  | No       | Secondary target for targeted actions (building, tech, etc.) |

#### Target Field Structures

Depending on the action type, the `target` field uses different structures:

- **Tile target**: `{"x": int, "y": int}` — for movement, terrain improvements
- **Unit target**: `{"unit_id": int}` — for attacks, bribes, healing
- **City target**: `{"city_id": int}` — for trade routes, espionage
- **Player target**: `{"player_id": int}` — for diplomacy actions
- **Production target**: `{"production": string}` — for city production (unit or building name)
- **Improvement target**: `{"improvement": string}` — for selling city improvements

#### Sub-Target Field (for Targeted Actions)

Some espionage actions allow targeting specific buildings or technologies:

```json
{
  "action_type": "spy_targeted_sabotage_city",
  "actor_id": 42,
  "target": {"city_id": 5},
  "sub_target": {"type": "building", "name": "Granary"}
}
```

```json
{
  "action_type": "spy_targeted_steal_tech",
  "actor_id": 42,
  "target": {"city_id": 5},
  "sub_target": {"type": "tech", "name": "Bronze Working"}
}
```

---

## Action Types Reference

All available action types organized by category. Actions returned from `unit_actions_query` and `city_actions_query` use these exact formats.

### Diplomacy Actions

Player-to-player diplomatic interactions. These actions enable declaring war, making peace, and managing alliances.

| Action Type                   | Description                                         | Target                                  |
| ----------------------------- | --------------------------------------------------- | --------------------------------------- |
| `diplomacy_declare_war`       | Declare war on another player                       | `{"player_id": int}`                    |
| `diplomacy_cancel_treaty`     | Cancel existing treaty (peace, alliance, ceasefire) | `{"player_id": int}`                    |
| `diplomacy_propose_ceasefire` | Propose a ceasefire                                 | `{"player_id": int}`                    |
| `diplomacy_propose_peace`     | Propose peace treaty                                | `{"player_id": int}`                    |
| `diplomacy_propose_alliance`  | Propose an alliance                                 | `{"player_id": int}`                    |
| `diplomacy_accept_treaty`     | Accept a pending treaty proposal                    | `{"player_id": int}`                    |
| `diplomacy_reject_treaty`     | Reject a pending treaty proposal                    | `{"player_id": int}`                    |
| `diplomacy_share_vision`      | Share map vision with ally                          | `{"player_id": int}`                    |
| `diplomacy_withdraw_vision`   | Stop sharing vision                                 | `{"player_id": int}`                    |
| `diplomacy_message`           | Send diplomatic message                             | `{"player_id": int, "message": string}` |

**Example — Declare War:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "diplomacy_declare_war",
    "actor_id": 0,
    "target": {"player_id": 2}
  }
}
```

**Example — Propose Peace:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "diplomacy_propose_peace",
    "actor_id": 0,
    "target": {"player_id": 2}
  }
}
```

### Espionage Actions (Diplomat/Spy Units)

Actions performed by Diplomat and Spy units for intelligence and sabotage.

| Action Type                  | Description                       | Target             | Sub-Target                             |
| ---------------------------- | --------------------------------- | ------------------ | -------------------------------------- |
| `unit_establish_embassy`     | Establish embassy in city         | `{"city_id": int}` | —                                      |
| `spy_investigate_city`       | Investigate city (view details)   | `{"city_id": int}` | —                                      |
| `spy_poison`                 | Poison city water supply          | `{"city_id": int}` | —                                      |
| `spy_sabotage_city`          | Random sabotage in city           | `{"city_id": int}` | —                                      |
| `spy_targeted_sabotage_city` | Sabotage specific building        | `{"city_id": int}` | `{"type": "building", "name": string}` |
| `spy_steal_tech`             | Steal random technology           | `{"city_id": int}` | —                                      |
| `spy_targeted_steal_tech`    | Steal specific technology         | `{"city_id": int}` | `{"type": "tech", "name": string}`     |
| `spy_incite_city`            | Incite city to revolt             | `{"city_id": int}` | —                                      |
| `spy_steal_gold`             | Steal gold from city              | `{"city_id": int}` | —                                      |
| `spy_steal_maps`             | Steal enemy maps                  | `{"city_id": int}` | —                                      |
| `spy_nuke`                   | Suitcase nuke (destroy city)      | `{"city_id": int}` | —                                      |
| `spy_spread_plague`          | Spread plague in city             | `{"city_id": int}` | —                                      |
| `spy_bribe_unit`             | Bribe enemy unit to defect        | `{"unit_id": int}` | —                                      |
| `spy_sabotage_unit`          | Sabotage enemy unit               | `{"unit_id": int}` | —                                      |
| `spy_attack`                 | Spy attacks defending spy         | `{"unit_id": int}` | —                                      |
| `unit_expel`                 | Expel foreign unit from territory | `{"unit_id": int}` | —                                      |

**Example — Steal Technology:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "spy_targeted_steal_tech",
    "actor_id": 42,
    "target": {"city_id": 5},
    "sub_target": {"type": "tech", "name": "Iron Working"}
  }
}
```

### Combat Actions

Military and offensive actions.

| Action Type           | Description                             | Target                                       |
| --------------------- | --------------------------------------- | -------------------------------------------- |
| `unit_attack`         | Attack enemy unit or city               | `{"unit_id": int}` or `{"x": int, "y": int}` |
| `unit_suicide_attack` | Attack with unit destruction guaranteed | `{"unit_id": int}` or `{"x": int, "y": int}` |
| `unit_bombard`        | Artillery bombardment (no retaliation)  | `{"x": int, "y": int}`                       |
| `unit_capture`        | Capture enemy units                     | `{"x": int, "y": int}`                       |
| `unit_wipe`           | Wipe all units on tile                  | `{"x": int, "y": int}`                       |
| `unit_conquer_city`   | Conquer enemy city                      | `{"city_id": int}`                           |
| `unit_nuke`           | Nuclear strike on tile                  | `{"x": int, "y": int}`                       |
| `unit_nuke_city`      | Nuclear strike on city                  | `{"city_id": int}`                           |
| `unit_nuke_units`     | Nuclear strike on units                 | `{"x": int, "y": int}`                       |

**Example — Attack:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_attack",
    "actor_id": 42,
    "target": {"unit_id": 99}
  }
}
```

### Movement & Transport Actions

Unit movement, transportation, and logistics.

| Action Type      | Description                                 | Target                 |
| ---------------- | ------------------------------------------- | ---------------------- |
| `unit_move`      | Move unit to adjacent tile                  | `{"x": int, "y": int}` |
| `unit_teleport`  | Teleport to location (if capability exists) | `{"x": int, "y": int}` |
| `unit_airlift`   | Airlift unit between cities                 | `{"city_id": int}`     |
| `unit_paradrop`  | Paradrop to location                        | `{"x": int, "y": int}` |
| `unit_embark`    | Embark onto transport                       | `{"unit_id": int}`     |
| `unit_disembark` | Disembark from transport to tile            | `{"x": int, "y": int}` |
| `unit_board`     | Board transport (same tile)                 | `{"unit_id": int}`     |
| `unit_deboard`   | Deboard from transport (same tile)          | —                      |
| `unit_load`      | Load cargo onto transport                   | `{"unit_id": int}`     |
| `unit_unload`    | Unload cargo from transport                 | `{"unit_id": int}`     |

**Example — Move:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_move",
    "actor_id": 42,
    "target": {"x": 11, "y": 21}
  }
}
```

### City Foundation & Management

City creation and unit-city interactions.

| Action Type       | Description                        | Target                        |
| ----------------- | ---------------------------------- | ----------------------------- |
| `unit_found_city` | Found new city at current location | `{"name": string}` (optional) |
| `unit_join_city`  | Join city to add population        | `{"city_id": int}`            |
| `unit_home_city`  | Change unit's home city            | `{"city_id": int}`            |

**Example — Found City:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_found_city",
    "actor_id": 456,
    "target": {"name": "New Rome"}
  }
}
```

### Trade Actions

Economic and trade-related unit actions.

| Action Type        | Description                               | Target             |
| ------------------ | ----------------------------------------- | ------------------ |
| `unit_trade_route` | Establish trade route with city           | `{"city_id": int}` |
| `unit_marketplace` | Enter marketplace (sell goods)            | `{"city_id": int}` |
| `unit_help_wonder` | Contribute shields to wonder construction | `{"city_id": int}` |

### Terrain Improvement Actions

Worker/Engineer actions for tile improvements.

| Action Type             | Description                                | Target                       |
| ----------------------- | ------------------------------------------ | ---------------------------- |
| `unit_build_road`       | Build road on tile                         | — (uses unit's current tile) |
| `unit_build_irrigation` | Build irrigation on tile                   | —                            |
| `unit_build_mine`       | Build mine on tile                         | —                            |
| `unit_build_base`       | Build fortress or airbase                  | —                            |
| `unit_pillage`          | Pillage tile improvements                  | — or `{"extra": string}`     |
| `unit_clean`            | Clean pollution or fallout                 | —                            |
| `unit_transform`        | Transform terrain type                     | —                            |
| `unit_cultivate`        | Cultivate terrain (e.g., forest to plains) | —                            |
| `unit_plant`            | Plant forest or jungle                     | —                            |

**Note:** Terrain improvement actions operate on the unit's current tile. No target coordinates needed.

**Example — Build Road:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_build_road",
    "actor_id": 789
  }
}
```

### Unit Status Actions

Unit state and capability management.

| Action Type    | Description                                    | Target             |
| -------------- | ---------------------------------------------- | ------------------ |
| `unit_fortify` | Fortify unit for defense bonus                 | —                  |
| `unit_sentry`  | Put on sentry (wake on enemy approach)         | —                  |
| `unit_explore` | Auto-explore unknown territory                 | —                  |
| `unit_disband` | Disband unit (recover some shields if in city) | —                  |
| `unit_upgrade` | Upgrade unit type (costs gold)                 | —                  |
| `unit_convert` | Convert unit to different type                 | —                  |
| `unit_heal`    | Heal nearby friendly unit                      | `{"unit_id": int}` |

**Example — Fortify:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "unit_fortify",
    "actor_id": 123
  }
}
```

### City Actions

City production and management (actor_id is the city ID).

| Action Type             | Description                      | Target                    |
| ----------------------- | -------------------------------- | ------------------------- |
| `city_production`       | Change city production           | `{"production": string}`  |
| `city_buy`              | Buy current production with gold | —                         |
| `city_sell_improvement` | Sell city improvement for gold   | `{"improvement": string}` |

**Example — Set Production:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "city_production",
    "actor_id": 5,
    "target": {"production": "Warrior"}
  }
}
```

**Example — Buy Production:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "city_buy",
    "actor_id": 5
  }
}
```

### Research & Game Control

| Action Type     | Description           | Target             |
| --------------- | --------------------- | ------------------ |
| `tech_research` | Research a technology | `{"tech": string}` |
| `end_turn`      | End current turn      | —                  |

**Example — Research Technology:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "tech_research",
    "actor_id": 0,
    "target": {"tech": "Bronze Working"}
  }
}
```

**Example — End Turn:**

```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "action_type": "end_turn",
    "actor_id": 0
  }
}
```

---

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

### 5. Turn Management

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

### 6. Heartbeat

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

### 7. Error Handling

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

**System & Connection:**

- `E101`: Missing required field
- `E102`: Invalid API token
- `E103`: Unknown message type
- `E120`: Not authenticated (session expired or not yet authenticated)
- `E121`: State query failed
- `E123`: Connection to game server lost
- `E429`: Rate limit exceeded (with grace period details)
- `E500`: Internal server error
- `E503`: Query timeout (server did not respond in time)
- `E999`: Unknown error (with diagnostic context)

**Action Validation:**

- `E130`: Action validation failed (generic)
- `E131`: Action execution failed
- `E220`: Missing required field (action-specific)
- `E221`: Invalid field type
- `E222`: Field value out of valid range

**Unit Validation:**

- `E230`: Unit not found
- `E231`: Unit not owned by player
- `E232`: Unit is busy or has no moves left
- `E233`: Insufficient movement points
- `E234`: Unit lacks required capability

**City Validation:**

- `E240`: City not found
- `E241`: City not owned by player
- `E242`: City at maximum capacity

**Target Validation:**

- `E250`: Insufficient gold or resources
- `E251`: Invalid coordinates
- `E252`: Target out of range
- `E253`: Target not visible
- `E254`: Terrain incompatible with action

**Diplomacy:**

- `E260`: Target player not found
- `E261`: Cannot perform diplomatic action (e.g., already at war)
- `E262`: Treaty already exists
- `E263`: No pending treaty to accept/reject
- `E264`: Invalid diplomatic state for action

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
      "activity": "idle"
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

### Complete Multi-Turn Game Flow Example

This example demonstrates a typical LLM agent gameplay session using per-unit action queries and diplomacy:

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
        player_id = auth_response['data']['player_id']
        print(f"Authenticated as player {player_id}")

        # 2. Get current state
        await ws.send(json.dumps({
            "type": "state_query",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {"format": "full", "include_legal_actions": True}
        }))

        state = json.loads(await ws.recv())
        units = state['data']['data']['units']  # Dict: {"123": {...}, "456": {...}}

        # 3. Query available actions for a specific unit
        warrior_id = 123
        await ws.send(json.dumps({
            "type": "unit_actions_query",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {"unit_id": warrior_id}
        }))

        actions_response = json.loads(await ws.recv())
        available_actions = actions_response['data']['actions']
        print(f"Unit {warrior_id} has {len(available_actions)} available actions")

        # 4. Pick and submit an action directly (no modification needed)
        for action in available_actions:
            if action['action_type'] == 'unit_move':
                await ws.send(json.dumps({
                    "type": "action",
                    "agent_id": "my-agent",
                    "timestamp": time.time(),
                    "data": action  # Submit directly as returned
                }))
                break

        # 5. Declare war on another player (diplomacy)
        enemy_player_id = 2
        await ws.send(json.dumps({
            "type": "action",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {
                "action_type": "diplomacy_declare_war",
                "actor_id": player_id,
                "target": {"player_id": enemy_player_id}
            }
        }))

        # 6. Found a city with settler
        settler = units.get('456')
        if settler:
            await ws.send(json.dumps({
                "type": "action",
                "agent_id": "my-agent",
                "timestamp": time.time(),
                "data": {
                    "action_type": "unit_found_city",
                    "actor_id": 456,
                    "target": {"name": "New Rome"}
                }
            }))

        # 7. Build road with worker
        await ws.send(json.dumps({
            "type": "action",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {
                "action_type": "unit_build_road",
                "actor_id": 789
            }
        }))

        # 8. End turn
        await ws.send(json.dumps({
            "type": "action",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {
                "action_type": "end_turn",
                "actor_id": player_id
            }
        }))

        # 9. Wait for next turn
        while True:
            message = json.loads(await ws.recv())
            if message['type'] == 'turn_start':
                print(f"Turn {message['data']['turn']} started")
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

- **2.0.0** (Nov 2025): Per-entity action queries and comprehensive action types
  - Added `unit_actions_query` and `city_actions_query` for per-entity action discovery
  - Returned actions are directly submittable without modification
  - Comprehensive action types covering all FreeCiv gameplay actions
  - Priority on diplomacy actions: declare war, propose peace, alliances, treaties
  - Full espionage action support for Diplomat/Spy units
  - Combat, movement, transport, terrain improvement actions
  - Consolidated error codes with semantic groupings (E2xx for validation, etc.)
  - Updated section numbering (7 message type sections)

- **1.0.0** (Sept 2025): Initial protocol specification
  - Basic message types for connection, state, and actions
  - WebSocket transport with JSON messaging
  - Authentication and session management
  - Error handling and rate limiting
