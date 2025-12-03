# LLM WebSocket Protocol Specification

## Overview

This document specifies the WebSocket protocol for LLM agent communication between Game Arena and FreeCiv3D. The protocol enables reliable, bidirectional communication for LLM-driven gameplay.

**Version**: 2.0.1
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

## Terminology

This section defines key terms used throughout the protocol specification.

| Term                           | Definition                                                                                                                                                                                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **actor_id**                   | The ID of the entity performing an action. For unit actions, this is the unit ID. For city actions (`city_production`, `city_buy`, `city_sell_improvement`), this is the city ID. For player-level actions (`end_turn`, diplomacy), this is typically the player ID or 0. |
| **agent_id**                   | Unique identifier for an LLM agent connection. Used in all messages to identify the sender/recipient. Format: alphanumeric with underscores/hyphens, max 50 characters.                                                                                                   |
| **building** / **improvement** | Used interchangeably to refer to city structures (e.g., Granary, Barracks, City Walls). The term "improvement" is used in `city_sell_improvement` action; "building" appears in `sub_target` for espionage.                                                               |
| **correlation_id**             | Optional field for matching requests to responses in async operations. Clients should include this for tracking; servers echo it back in responses.                                                                                                                       |
| **target**                     | Primary target of an action. Structure varies by action type: coordinates `{x, y}`, entity ID `{unit_id}`, `{city_id}`, `{player_id}`, or names `{production}`, `{improvement}`.                                                                                          |
| **sub_target**                 | Secondary target for targeted actions, currently used only for espionage. Contains `{type, name}` where type is `"building"` or `"tech"`.                                                                                                                                 |
| **session_id**                 | Server-assigned identifier for an authenticated session. HMAC-signed for security. Returned in auth response.                                                                                                                                                             |
| **player_id**                  | Integer identifier (0-29) for a player in the game. Assigned during authentication.                                                                                                                                                                                       |

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
    "game_id": "game-123"
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

### 3. Per-Entity Action Queries (Batch)

These query types allow clients to request available actions for multiple units or cities in a single request. The returned actions are complete and directly submittable—clients can send them back as ACTION requests without modification.

#### UNIT_ACTIONS_QUERY (Request)

Query all legal actions available for one or more units.

```json
{
  "type": "unit_actions_query",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "unit-query-001",
  "data": {
    "unit_ids": [42, 43, 44]
  }
}
```

| Field      | Type              | Required | Description                           |
| ---------- | ----------------- | -------- | ------------------------------------- |
| `unit_ids` | array of integers | Yes      | List of unit IDs to query (1 or more) |

#### UNIT_ACTIONS_RESPONSE (Response)

Returns actions grouped by unit ID. Each action object is complete and can be directly submitted as an ACTION request.

```json
{
  "type": "unit_actions_response",
  "agent_id": "my-agent",
  "timestamp": 1234567890.125,
  "correlation_id": "unit-query-001",
  "data": {
    "success": true,
    "units": {
      "42": {
        "unit_id": 42,
        "success": true,
        "actions": [
          {
            "action_type": "unit_move",
            "actor_id": 42,
            "target": {"x": 11, "y": 21}
          },
          {
            "action_type": "unit_fortify",
            "actor_id": 42
          }
        ]
      },
      "43": {
        "unit_id": 43,
        "success": true,
        "actions": [
          {
            "action_type": "unit_move",
            "actor_id": 43,
            "target": {"x": 15, "y": 25}
          }
        ]
      },
      "44": {
        "unit_id": 44,
        "success": false,
        "error": {
          "code": "E230",
          "message": "Unit not found"
        },
        "actions": []
      }
    },
    "errors": [
      {
        "unit_id": 44,
        "code": "E230",
        "message": "Unit not found"
      }
    ]
  }
}
```

**Response Fields:**

| Field               | Type    | Description                                                                 |
| ------------------- | ------- | --------------------------------------------------------------------------- |
| `success`           | boolean | `true` if at least one unit returned actions successfully                   |
| `units`             | object  | Dictionary of results keyed by unit ID (string keys for JSON compatibility) |
| `units[id].success` | boolean | Whether this specific unit query succeeded                                  |
| `units[id].actions` | array   | List of available actions for this unit (empty if error)                    |
| `units[id].error`   | object  | Error details if this unit query failed (optional)                          |
| `errors`            | array   | Summary list of all unit-level errors (for quick checking)                  |

**Usage Pattern:**

```python
# 1. Query actions for multiple units at once
await ws.send(json.dumps({
    "type": "unit_actions_query",
    "agent_id": "my-agent",
    "timestamp": time.time(),
    "correlation_id": "batch-query-001",
    "data": {"unit_ids": [42, 43, 44]}
}))

response = json.loads(await ws.recv())
units_data = response['data']['units']

# 2. Process each unit's actions
for unit_id, unit_result in units_data.items():
    if unit_result['success']:
        actions = unit_result['actions']
        # Pick and submit an action
        if actions:
            chosen_action = actions[0]
            await ws.send(json.dumps({
                "type": "action",
                "agent_id": "my-agent",
                "timestamp": time.time(),
                "data": chosen_action
            }))
    else:
        print(f"Unit {unit_id} error: {unit_result['error']['message']}")
```

**Error Codes (per-unit):**

- `E230`: Unit not found
- `E231`: Unit not owned by player
- `E503`: Query timeout (server did not respond in time)

**Note:** Partial success is possible. If some units are valid and others are not, the response will include actions for valid units and errors for invalid ones.

#### CITY_ACTIONS_QUERY (Request)

Query all legal actions available for one or more cities.

```json
{
  "type": "city_actions_query",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "city-query-001",
  "data": {
    "city_ids": [5, 6]
  }
}
```

| Field      | Type              | Required | Description                           |
| ---------- | ----------------- | -------- | ------------------------------------- |
| `city_ids` | array of integers | Yes      | List of city IDs to query (1 or more) |

#### CITY_ACTIONS_RESPONSE (Response)

Returns actions grouped by city ID.

```json
{
  "type": "city_actions_response",
  "agent_id": "my-agent",
  "timestamp": 1234567890.125,
  "correlation_id": "city-query-001",
  "data": {
    "success": true,
    "cities": {
      "5": {
        "city_id": 5,
        "success": true,
        "actions": [
          {
            "action_type": "city_production",
            "actor_id": 5,
            "target": {"production": "Warrior"}
          },
          {
            "action_type": "city_buy",
            "actor_id": 5
          }
        ]
      },
      "6": {
        "city_id": 6,
        "success": true,
        "actions": [
          {
            "action_type": "city_production",
            "actor_id": 6,
            "target": {"production": "Granary"}
          }
        ]
      }
    },
    "errors": []
  }
}
```

**Response Fields:**

| Field                | Type    | Description                                                                 |
| -------------------- | ------- | --------------------------------------------------------------------------- |
| `success`            | boolean | `true` if at least one city returned actions successfully                   |
| `cities`             | object  | Dictionary of results keyed by city ID (string keys for JSON compatibility) |
| `cities[id].success` | boolean | Whether this specific city query succeeded                                  |
| `cities[id].actions` | array   | List of available actions for this city (empty if error)                    |
| `cities[id].error`   | object  | Error details if this city query failed (optional)                          |
| `errors`             | array   | Summary list of all city-level errors (for quick checking)                  |

**Error Codes (per-city):**

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

## Input Validation Rules

All user-provided input fields must adhere to validation constraints to ensure security and data integrity.

### String Field Validation

#### City Names

Used in `unit_found_city` action:

- **Max length**: 50 characters
- **Allowed characters**: Alphanumeric, spaces, underscores, hyphens `[a-zA-Z0-9 _-]`
- **Special character restrictions**: No control characters, null bytes, or SQL injection patterns
- **Example valid names**: `"New Rome"`, `"Capital_City"`, `"Settlement-01"`
- **Example invalid names**: `<script>alert(1)</script>`, `City'; DROP TABLE--`, names over 50 characters

#### Building and Improvement Names

Used in `city_production`, `city_sell_improvement` actions:

- **Max length**: 30 characters
- **Allowed characters**: Alphanumeric, spaces, underscores `[a-zA-Z0-9_ ]`
- **Case**: Case-insensitive matching
- **Examples**: `"Barracks"`, `"City Walls"`, `"Granary"`

#### Technology Names

Used in `tech_research` and espionage actions:

- **Max length**: 50 characters
- **Allowed characters**: Alphanumeric, spaces, underscores `[a-zA-Z0-9_ ]`
- **Case**: Case-insensitive matching
- **Examples**: `"Bronze Working"`, `"Iron Working"`, `"Pottery"`

#### Diplomatic Messages

Used in `diplomacy_message` action:

- **Max length**: 256 characters
- **Allowed characters**: `[a-zA-Z0-9 .,!?'"()-]` (alphanumeric, spaces, and common punctuation)
- **Sanitization**: Automatic removal of control characters and null bytes

#### Agent Identifiers

Used in all message types:

- **Max length**: 50 characters
- **Allowed characters**: Alphanumeric, underscores, hyphens `[a-zA-Z0-9_-]`
- **Example**: `"my-agent-123"`, `"llm_agent_alpha"`

#### Sub-Target Fields

Used in `sub_target` object for targeted espionage actions (`spy_targeted_sabotage_city`, `spy_targeted_steal_tech`):

**Building sub-target** (`sub_target.type` = `"building"`):

- **`name` max length**: 30 characters
- **Allowed characters**: `[a-zA-Z0-9_ ]` (alphanumeric, spaces, underscores)
- **Case**: Case-insensitive matching against ruleset building names
- **Examples**: `{"type": "building", "name": "Granary"}`, `{"type": "building", "name": "City Walls"}`

**Technology sub-target** (`sub_target.type` = `"tech"`):

- **`name` max length**: 50 characters
- **Allowed characters**: `[a-zA-Z0-9_ ]` (alphanumeric, spaces, underscores)
- **Case**: Case-insensitive matching against ruleset technology names
- **Examples**: `{"type": "tech", "name": "Bronze Working"}`, `{"type": "tech", "name": "Iron Working"}`

**Validation**: If `sub_target.name` does not match a valid building or technology in the current ruleset, the action fails with error **E130** (Action validation failed).

### Numeric Field Validation

#### Coordinates (x, y)

- **Range**: 0 to 9999 (inclusive); negative coordinates are rejected
- **Type**: Must be integers
- **Map bounds**: Server validates coordinates are within current map dimensions (typically 0 to map_width-1, 0 to map_height-1)
- **Error**: Out-of-range coordinates rejected with E251; coordinates outside map bounds rejected with E252

#### Unit IDs, City IDs

- **Range**: 0 to 999,999
- **Type**: Must be non-negative integers
- **Validation**: Server verifies entity exists and is accessible

#### Player IDs

- **Range**: 0 to 29 (FreeCiv supports maximum 30 players)
- **Type**: Must be non-negative integers
- **Validation**: Server verifies player exists in game

### Security Validation

#### SQL Injection Prevention

All string inputs are scanned for SQL injection patterns:

- **SQL keywords**: `SELECT`, `DROP`, `INSERT`, `UPDATE`, `DELETE`, `UNION`, `ALTER`, `CREATE`
- **Comment patterns**: `--`, `/*`, `*/`, `#`
- **Boolean conditions**: `OR 1=1`, `AND 1=1`, `' OR '`
- **Quoted literals**: Patterns like `'; DROP TABLE`
- **Error code**: **E223** (Invalid characters in string field)

#### Cross-Site Scripting (XSS) Prevention

- **HTML/JavaScript tags**: Stripped from all string inputs
- **Control characters**: Removed (except tabs, newlines, carriage returns in message fields)
- **Null bytes**: Removed (`\0`)
- **Unicode normalization**: Applied to prevent homograph attacks

#### Path Traversal Prevention

- No file path inputs accepted in protocol
- All resource references use IDs or validated names from fixed enumerations

### Validation Error Codes

- **E220**: Missing required field (action-specific)
- **E221**: Invalid field type (e.g., string provided where integer expected)
- **E222**: Field value out of valid range (e.g., coordinate > 9999)
- **E223**: Invalid characters in string field (SQL injection attempt, XSS pattern)
- **E224**: String exceeds maximum length

### Validation Examples

**Valid city name:**

```json
{
  "action_type": "unit_found_city",
  "actor_id": 456,
  "target": {"name": "New Rome"}
}
```

**Invalid city name (too long):**

```json
{
  "action_type": "unit_found_city",
  "actor_id": 456,
  "target": {"name": "This is a very long city name that exceeds the fifty character limit"}
}
```

**Error Response:**

```json
{
  "type": "error",
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

**Invalid city name (SQL injection attempt):**

```json
{
  "action_type": "unit_found_city",
  "actor_id": 456,
  "target": {"name": "City'; DROP TABLE cities--"}
}
```

**Error Response:**

```json
{
  "type": "error",
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

---

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

### Timeout Specifications

#### Query Timeouts

**State Query Timeout**: 15 seconds

- Maximum time allowed for `state_query` requests to complete
- Server must respond within this window or client receives timeout error
- Error code: **E503** (Query timeout)
- **Retry strategy**: Exponential backoff starting at 1 second, maximum 3 attempts
  - First retry: Immediate (timeout may have been transient)
  - Second retry: 2 seconds delay
  - Third retry: 4 seconds delay
  - After 3 failures: Log error and notify user

**Action Query Timeout**: 10 seconds (applies to `unit_actions_query`, `city_actions_query`)

- Maximum time to enumerate and return legal actions for an entity
- Includes time for game state validation and action generation
- Error code: **E503** (Query timeout)
- **Retry strategy**: Single retry after 2 seconds
  - If second attempt fails, entity may be in invalid state
  - Recommend querying full game state to verify entity status

**Action Execution Timeout**: 10 seconds

- Maximum time for action validation and execution on game server
- Covers action submission, validation, execution, and result return
- Error code: **E503** (Query timeout)
- **Behavior**: Action may have been executed despite timeout; query state to verify
- **Retry strategy**: Do NOT automatically retry action execution
  - Query game state first to check if action was applied
  - Only resubmit if confirmed not executed

**Connection Initialization Timeout**: 5 seconds

- Time allowed for initial WebSocket handshake and authentication
- Includes TLS negotiation (if using `wss://`)
- **Retry strategy**: Up to 3 attempts with 1-second delay between attempts
  - Total connection attempt window: ~15 seconds
  - If all attempts fail, report connection error to user

#### Session Timeouts

**Session Idle Timeout**: 600 seconds (10 minutes)

- Configurable via `SESSION_TIMEOUT_SECONDS` environment variable
- Automatic session cleanup after idle period with no messages
- Idle timer resets on any valid message from client
- Error code: **E120** (Not authenticated - session expired)
- **Recovery**: Client must reconnect and reauthenticate

**Session Resumption Window**: 60 seconds

- Time allowed to reconnect and resume expired session after disconnect
- Session state preserved during this window
- After window expires, new authentication required
- **Behavior**: Same `agent_id` can reconnect and continue game

**Heartbeat Interval**: 30 seconds

- Clients should send `ping` messages every 30 seconds during idle periods
- Gateway disconnects after 2 missed heartbeats (60 seconds of silence)
- Heartbeat prevents false session expiration during long computations
- **Recommendation**: Send heartbeat between turns or during long planning phases

#### Recommended Client Retry Strategies

**For E503 Timeout Errors:**

1. **State queries**: Exponential backoff (1s, 2s, 4s), max 3 attempts
2. **Action queries**: Single retry after 2s delay
3. **Action execution**: Never auto-retry; query state first to check if action applied
4. **After all retries fail**: Log error, display user notification, allow manual retry

**For Connection Failures:**

- **Strategy**: Exponential backoff with maximum delay cap
  - Delays: 1s, 2s, 4s, 8s, 16s, 30s (max)
  - Maximum retry attempts: 10
  - Total retry window: ~2 minutes before permanent failure
- **Connection lost mid-game**: Attempt reconnection with same `agent_id`
  - If within 60-second resumption window, session preserved
  - If beyond window, full reauthentication required

**For Rate Limit Errors (E429):**

- **Strategy**: Honor `retry_after` value in error response
  - Wait for specified seconds before next attempt
  - Monitor `grace_period.remaining_violations` field
  - Reduce request rate if `remaining_violations < 2`
- **Grace period exhausted**: Wait full 60 seconds before resuming

#### Client Implementation Example

```python
import asyncio
import time

async def query_with_retry(websocket, query_data, max_attempts=3):
    """Query with exponential backoff retry strategy."""
    delays = [0, 1, 2, 4]  # First attempt immediate, then backoff
    
    for attempt in range(max_attempts):
        try:
            await asyncio.sleep(delays[attempt])
            
            await websocket.send(json.dumps({
                "type": "state_query",
                "agent_id": "my-agent",
                "timestamp": time.time(),
                "data": query_data
            }))
            
            # Wait for response with timeout
            response = await asyncio.wait_for(
                websocket.recv(), 
                timeout=15.0
            )
            
            return json.loads(response)
            
        except asyncio.TimeoutError:
            if attempt == max_attempts - 1:
                raise Exception("Query timeout after 3 attempts")
            continue
        except Exception as e:
            raise

async def execute_action_safely(websocket, action_data):
    """Execute action with state verification (no auto-retry)."""
    try:
        await websocket.send(json.dumps({
            "type": "action",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": action_data
        }))
        
        response = await asyncio.wait_for(
            websocket.recv(),
            timeout=10.0
        )
        
        return json.loads(response)
        
    except asyncio.TimeoutError:
        # DO NOT retry - query state to check if action applied
        state = await query_with_retry(websocket, {"format": "full"})
        # Verify if action was executed by checking state changes
        return {"timeout": True, "state": state}
```

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

Rate limiting protects server resources and prevents abuse while accommodating legitimate gameplay patterns.

#### Rate Limit Configuration

- **Messages per minute**: 300 (configurable, increased for 2-4 player games)
- **Burst limit**: 80 messages per second (handles turn-start message spikes)
- **Bytes per minute**: 2MB (accommodates large state queries)
- **Grace period duration**: 30 seconds before enforcement begins
- **Max violations**: 3 violations within grace period before blocking
- **Block duration**: 60 seconds after exceeding max violations
- **Grace period reset**: Counter resets after 30 seconds of compliant behavior

**Message Types Subject to Rate Limiting:**

All message types count against the rate limit, including:

- `state_query`, `unit_actions_query`, `city_actions_query` (queries)
- `action` (action submissions)
- `ping` (heartbeat messages)

**Recommendation**: Cache query responses locally and avoid repeated queries for the same entity within a turn. Use `state_query` with `delta` format to reduce response size.

#### Grace Period Behavior

The rate limiter uses a grace period system to accommodate temporary spikes while blocking sustained abuse:

**Violation 1**: First rate limit exceeded

- **Action**: Warning logged, connection continues normally
- **Client experience**: No error returned, requests processed successfully
- **Internal state**: Violation counter increments to 1
- **Grace period**: 30-second timer starts
- **Logging**: `INFO: Agent my-agent rate limit violation 1/3`

**Violation 2**: Second rate limit exceeded (within 30-second window)

- **Action**: Warning logged, connection still continues
- **Client experience**: No error returned, requests still processed
- **Internal state**: Violation counter increments to 2
- **Grace period**: Timer resets to 30 seconds
- **Logging**: `WARN: Agent my-agent rate limit violation 2/3`

**Violation 3**: Third rate limit exceeded (final warning)

- **Action**: Final warning logged, connection continues
- **Client experience**: Requests processed, but `remaining_violations: 0` in next error
- **Internal state**: Violation counter increments to 3
- **Grace period**: Timer resets to 30 seconds
- **Logging**: `WARN: Agent my-agent rate limit violation 3/3 - next violation will block`
- **Recommendation**: Client should slow request rate immediately

**Violation 4+**: Grace period exhausted

- **Action**: Connection blocked for 60 seconds
- **Client experience**: All requests return **E429** error for 60 seconds
- **Internal state**: Block timer starts at 60 seconds
- **Grace period**: Resets after block expires
- **Logging**: `ERROR: Agent my-agent blocked for rate limit violations`
- **Recovery**: Client must wait for `retry_after` duration specified in error

#### Grace Period Reset Conditions

**Automatic Reset** (no violations for 30 seconds):

- Violation counter resets to 0
- Client returns to good standing
- Full grace period available again
- **Logging**: `INFO: Agent my-agent grace period reset - violations cleared`

**Partial Reset** (compliant behavior after violations):

- Timer continues counting down from last violation
- If 30 seconds elapse with no new violations, counter resets
- New violations restart the 30-second timer

**No Reset** (persistent violations):

- Violations within 30-second window keep grace period active
- Counter continues incrementing until reaching max (3)
- Block applied on 4th violation

#### Rate Limit Error Response Structure

When rate limit is exceeded (violation 4+), clients receive detailed error information:

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
        },
        "bytes_per_minute": {
          "remaining": 512000,
          "reset_time": 1234567950.0
        }
      }
    }
  }
}
```

**Response Fields Explained**:

- `retry_after`: Seconds to wait before next request attempt
- `grace_period.violations`: Total violations in current window
- `grace_period.remaining_violations`: How many more violations before block (0 = already blocked)
- `grace_period.will_reset_in`: Seconds until grace period resets (0 = already expired)
- `remaining_limits`: Current usage for each rate limit type

#### Client Monitoring Recommendations

**Proactive Monitoring**:

1. **Track request rate**: Monitor outgoing message frequency
2. **Watch for warnings**: Log files will show violation warnings (violations 1-3)
3. **Implement backoff**: Slow request rate if approaching limits
4. **Parse error details**: Check `remaining_violations` field in any E429 errors

**Response to Violations**:

```python
# Example: Client-side rate limit monitoring
class RateLimitMonitor:
    def __init__(self):
        self.request_times = []
        self.last_violation_warning = None
    
    def before_request(self):
        """Check rate before sending request."""
        now = time.time()
        # Remove requests older than 60 seconds
        self.request_times = [t for t in self.request_times if now - t < 60]
        
        # Check if approaching limit (80% of 300/minute = 240)
        if len(self.request_times) > 240:
            # Slow down - wait before next request
            time.sleep(0.5)
        
        self.request_times.append(now)
    
    def handle_error(self, error):
        """Handle rate limit error response."""
        if error.get('code') == 'E429':
            details = error.get('details', {})
            retry_after = details.get('retry_after', 60)
            remaining = details.get('grace_period', {}).get('remaining_violations', 0)
            
            if remaining == 0:
                # Blocked - must wait full duration
                print(f"BLOCKED: Waiting {retry_after} seconds")
                time.sleep(retry_after)
            else:
                # Warning - slow down immediately
                print(f"WARNING: {remaining} violations remaining before block")
                time.sleep(1)  # Brief pause to reduce rate
```

**Best Practices**:

- **Batch operations**: Combine multiple queries when possible
- **Cache responses**: Store state locally, query only when needed
- **Respect `retry_after`**: Always wait the specified duration
- **Implement exponential backoff**: If violations persist, increase delays
- **Monitor `remaining_violations`**: React before reaching block threshold

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

        # 3. Query available actions for multiple units at once
        unit_ids = [123, 456]  # warrior and settler
        await ws.send(json.dumps({
            "type": "unit_actions_query",
            "agent_id": "my-agent",
            "timestamp": time.time(),
            "data": {"unit_ids": unit_ids}
        }))

        actions_response = json.loads(await ws.recv())
        units_actions = actions_response['data']['units']

        # 4. Process warrior's actions
        warrior_data = units_actions.get('123')
        if warrior_data and warrior_data['success']:
            for action in warrior_data['actions']:
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

### Transport Layer Security

#### TLS Requirements

**Production Environments:**

- **REQUIRED**: Use `wss://` (WebSocket Secure) protocol for all connections
- **TLS Version**: TLS 1.2 or higher required
- **Certificates**: Valid SSL/TLS certificates required (no self-signed in production)
- **Critical**: API tokens are transmitted in plaintext over WebSocket connection
  - **TLS is mandatory** to prevent token interception
  - Tokens sent in `llm_connect` message `api_token` field
  - Without TLS, tokens are visible to network observers

**Development/Testing Environments:**

- `ws://` (unencrypted) permitted for **local development only**
- **WARNING**: Never use `ws://` in production - API tokens will be exposed
- Localhost/127.0.0.1 connections only for unencrypted development
- Consider using `wss://` even in development to match production behavior

**Example URLs:**

```text
Production:  wss://gateway.example.com:8003/ws/agent/my-agent
Development: ws://localhost:8003/ws/agent/my-agent (local only)
```

**Deployment Recommendations:**

- Use reverse proxy (nginx, Apache) to handle TLS termination
- Enable HTTP Strict Transport Security (HSTS)
- Configure strong cipher suites (disable weak ciphers)
- Rotate TLS certificates before expiration (recommend 90-day certs)

### API Token Management

#### Token Requirements

- **Format**: Alphanumeric string, minimum 32 characters recommended
- **Generation**: Use cryptographically secure random number generator
- **Storage**: Store securely using:
  - Environment variables (recommended)
  - Secrets management service (AWS Secrets Manager, HashiCorp Vault)
  - Encrypted configuration files
- **Transmission**: Sent only in `llm_connect` message `api_token` field
- **Lifetime**: 90 days recommended, configurable per deployment
- **Never**:
  - Hard-code tokens in source code
  - Commit tokens to version control
  - Log tokens in plaintext
  - Share tokens between environments

#### Token Rotation

**Recommended Schedule**: Every 90 days

**Rotation Process:**

1. Generate new token via admin API or deployment interface
2. Update client configuration with new token
3. **Grace period**: Old token remains valid for 24 hours after new token issued
4. Clients can connect with either old or new token during grace period
5. After 24 hours, old token automatically revoked

**Session Handling During Rotation:**

- Active sessions continue with old token until disconnect
- New connections must use new token after grace period
- No forced disconnection of active sessions
- Recommend coordinated rotation during low-activity periods

### Session Security

#### HMAC-Signed Session IDs

- All session IDs are HMAC-signed using server secret key
- Signature validation occurs on every request
- Prevents session hijacking and tampering
- Session format: `<session_data>.<hmac_signature>`
- **Algorithm**: HMAC-SHA256

**Signature Validation Failures:**

- Invalid signature: Immediate disconnection, no error sent
- Expired signature: Error E120 (session expired)
- Logging: All validation failures logged for security monitoring

#### Session Monitoring

The system logs authentication and session events for security monitoring:

**Logged Events:**

- Failed authentication attempts (E102 - Invalid API token)
- Expired sessions (E120 - Session expired)
- Rate limit violations (E429 - Rate limit exceeded)
- Suspicious patterns:
  - Multiple failed authentication attempts from same IP
  - Rapid connection/disconnection cycles
  - Unusual request patterns or volumes
  - Token reuse across multiple IPs (possible token sharing)

**Alert Thresholds** (configurable):

- 5+ failed authentication attempts in 5 minutes: Admin alert
- 10+ rate limit violations in 1 hour: Connection blocked, admin notified
- Token used from 3+ different IPs simultaneously: Security review triggered

### Input Sanitization

All inputs are validated and sanitized before processing. See **Input Validation Rules** section for complete specifications.

#### SQL Injection Detection and Prevention

All string inputs automatically scanned for SQL injection patterns:

- **SQL keywords**: `SELECT`, `DROP`, `INSERT`, `UPDATE`, `DELETE`, `UNION`, `ALTER`, `CREATE`, `EXEC`, `EXECUTE`
- **Comment patterns**: `--`, `/*`, `*/`, `#`, `;--`
- **Boolean conditions**: `OR 1=1`, `AND 1=1`, `' OR '`, `" OR "`
- **Quoted literals**: Patterns like `'; DROP TABLE`, `"); DELETE FROM`
- **Error code**: **E223** (Invalid characters in string field)
- **Logging**: All SQL injection attempts logged with source IP and agent ID

**Implementation**: Case-insensitive pattern matching with regex validation

#### XSS Attack Prevention

- **HTML/JavaScript tags**: Stripped from all string inputs
  - Tags removed: `<script>`, `<iframe>`, `<object>`, `<embed>`, `<img>`, etc.
  - Attributes removed: `onclick`, `onerror`, `onload`, event handlers
- **Control characters**: Removed (except tabs, newlines, carriage returns in message fields)
- **Null bytes**: Removed (`\0`, `\x00`)
- **Unicode normalization**: NFC normalization applied to prevent homograph attacks
  - Prevents visual spoofing using similar-looking Unicode characters
  - Example: Cyrillic 'а' (U+0430) normalized to Latin 'a' (U+0061)

#### Path Traversal Attack Prevention

- **No file paths**: Protocol does not accept file path inputs
- **Resource references**: All resources referenced by ID or validated name
  - Unit IDs, City IDs: Integer validation (0 to 999,999)
  - Building/Tech names: Enumeration from fixed ruleset
- **No directory traversal**: Patterns like `../`, `..\`, `/etc/`, `C:\` rejected immediately

### Rate Limiting Security

Rate limiting serves as both performance protection and security defense against DoS attacks.

#### Grace Period Protection

**Purpose**: Allow legitimate traffic spikes (turn processing) while blocking sustained abuse

**Behavior**:

- First 3 violations within 30-second window: Warning only, connection continues
- Violations 4+: Connection blocked for 60 seconds
- Grace period resets after 30 seconds of compliant behavior
- Persistent violations across multiple sessions: Escalation to admin review

#### DDoS Protection Limits

- **Per-connection burst limit**: 80 messages per second
  - Handles legitimate turn-start message bursts
  - Blocks rapid-fire attack attempts
- **Per-minute limit**: 300 messages
  - Sustained rate for normal gameplay
  - Prevents slow-rate DoS attacks
- **Byte limit**: 2MB per minute
  - Protects against large payload attacks
  - Includes all WebSocket frame data
- **Automatic termination**: Connection terminated on sustained abuse
  - No grace period for extreme violations (>200 msg/sec)
  - IP address may be temporarily blocked (deployment-specific)

**Attack Mitigation**:

- **Connection flooding**: Max 2 connections per agent ID
- **State query spam**: 15-second timeout prevents query stacking
- **Action spam**: Action validation rate limited separately
- **Slowloris protection**: Heartbeat requirement (30s) with 60s timeout

### Origin Validation

#### WebSocket Origin Checking

**Browser Clients**: Origin header validated against allowlist

- Browser automatically sends `Origin` header in WebSocket handshake
- Gateway validates origin matches configured allowlist
- Rejected origins receive HTTP 403 Forbidden response
- **Error**: Connection refused before WebSocket upgrade

**Non-Browser Clients** (Python, Node.js, etc.):

- Origin validation skipped (no browser to send Origin header)
- API token authentication sufficient for non-browser clients
- Can optionally send `Origin` header for logging purposes

**Allowed Origins Configuration**:

```bash
# Environment variable (comma-separated list)
GATEWAY_ALLOWED_ORIGINS="https://app.example.com,https://app2.example.com"
```

**Default Allowed Origins** (development only):

```text
http://localhost:3000
http://localhost:8080
https://localhost:3000
https://localhost:8080
```

**Production Recommendation**:

- Use explicit domain allowlist
- Avoid wildcard origins (`*`) - security risk
- Include all legitimate frontend domains
- Update allowlist when deploying new frontends

### Security Headers

Recommended HTTP headers for gateway deployment (configure in reverse proxy):

```text
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'
Referrer-Policy: strict-origin-when-cross-origin
```

**Header Purposes**:

- **HSTS**: Forces HTTPS for all connections (prevents downgrade attacks)
- **X-Content-Type-Options**: Prevents MIME sniffing attacks
- **X-Frame-Options**: Prevents clickjacking attacks
- **X-XSS-Protection**: Browser XSS filter (defense in depth)
- **CSP**: Restricts resource loading (if serving web content)
- **Referrer-Policy**: Limits referrer information leakage

### Security Monitoring and Logging

**Recommended Logging**:

- All authentication attempts (success and failure)
- Session creation, expiration, and termination events
- Rate limit violations with agent ID and IP
- Input validation failures (E223, E224) with sanitized input samples
- Administrative actions (configuration changes)

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

- **2.0.1** (Nov 2025): Enhanced documentation and security specifications
  - Added comprehensive input validation rules section
    - String field validation (city names, building/tech names, diplomatic messages)
    - Numeric field validation (coordinates, IDs with specific ranges)
    - Security validation (SQL injection prevention with E223, XSS protection)
    - Validation error codes (E220-E224) with detailed examples
  - Added detailed timeout specifications
    - Query timeouts (15s state, 10s actions) with retry strategies
    - Session timeouts (600s idle, 60s resumption window)
    - Client implementation examples with exponential backoff
  - Expanded security considerations section
    - TLS requirements (mandatory wss:// for production)
    - API token lifecycle (90-day rotation, 24-hour grace period)
    - Session security (HMAC-signed IDs, monitoring, attack detection)
    - Input sanitization details (SQL injection, XSS, path traversal prevention)
    - Rate limiting as DDoS protection
    - Origin validation and security headers
  - Enhanced rate limiting documentation
    - Detailed grace period behavior (violations 1-2 warning, 3 final warning, 4+ block)
    - Grace period reset conditions (30-second timer)
    - Client monitoring recommendations with code examples
    - Rate limit error response structure explanation

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
