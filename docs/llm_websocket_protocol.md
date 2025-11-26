# LLM WebSocket Protocol Specification

## Overview

This document specifies the WebSocket protocol for LLM agent communication between Game Arena and FreeCiv3D. The protocol enables reliable, bidirectional communication for LLM-driven gameplay.

**Version**: 2.0.0
**Date**: November 24, 2025

**Major Changes in v2.0**:
- Server-authoritative per-unit action queries (AGE-192)
- Action probability system with success/failure chances
- 100% accurate actions from FreeCiv server
- Real-time action availability based on game state

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
    "query_unit_actions": [42, 43, 44],
    "since_turn": 10
  }
}
```

**Format Options:**
- `full`: Complete game state with all details
- `delta`: Changes since last query
- `llm_optimized`: Compressed state optimized for LLM consumption

**Query Parameters:**
- `query_unit_actions` (array): List of unit IDs to query available actions for
- `action_target` (optional): Specific target for action queries (unit_id, city_id, or tile coordinates)

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
      "unit_actions": {
        "42": {
          "unit_id": 42,
          "available_actions": [
            {
              "action_id": 45,
              "action_type": "attack",
              "probability": 175,
              "probability_percent": 87.5,
              "target_required": true,
              "valid_targets": [43, 44]
            },
            {
              "action_id": 27,
              "action_type": "found_city",
              "probability": 200,
              "probability_percent": 100.0,
              "target_required": false
            }
          ],
          "queried_at": 1234567890.125
        }
      }
    }
  }
}
```

**Note**: The `players`, `units`, and `cities` fields are always returned as **dictionaries** (objects) keyed by ID, not arrays. This provides efficient O(1) lookups by ID.

### 2b. Per-Unit Action Queries (v2.0)

The protocol supports **server-authoritative action queries** that provide 100% accurate legal actions directly from the FreeCiv server, with real-time action availability based on current game state.

#### UNIT_ACTION_QUERY (Request)

Query available actions for specific units with optional target specification:

```json
{
  "type": "unit_action_query",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "action-query-1",
  "data": {
    "unit_id": 42,
    "target_unit_id": 0,
    "target_tile_id": 0,
    "target_extra_id": 0,
    "request_kind": 0
  }
}
```

**Request Fields:**
- `unit_id` (required): Unit to query actions for
- `target_unit_id` (optional, default 0): Specific target unit (0 = no target)
- `target_tile_id` (optional, default 0): Specific target tile (0 = actor's tile)
- `target_extra_id` (optional, default 0): Specific target extra/improvement (0 = none)
- `request_kind` (optional, default 0): Query type (0 = all actions, 1 = target-specific)

#### UNIT_ACTION_RESPONSE (Response)

Server responds with available actions and their success probabilities:

```json
{
  "type": "unit_action_response",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "action-query-1",
  "data": {
    "unit_id": 42,
    "target_unit_id": 43,
    "target_city_id": 0,
    "target_tile_id": 1523,
    "target_extra_id": 0,
    "request_kind": 0,
    "actions": [
      {
        "action_id": 45,
        "action_type": "attack",
        "action_name": "Attack",
        "probability": 175,
        "probability_percent": 87.5,
        "min_distance": 1,
        "max_distance": 1,
        "target_kind": "unit"
      },
      {
        "action_id": 27,
        "action_type": "found_city",
        "action_name": "Build City",
        "probability": 200,
        "probability_percent": 100.0,
        "min_distance": 0,
        "max_distance": 0,
        "target_kind": "self"
      },
      {
        "action_id": 53,
        "action_type": "bombard",
        "action_name": "Bombard",
        "probability": 0,
        "probability_percent": 0.0,
        "min_distance": 1,
        "max_distance": 2,
        "target_kind": "unit",
        "blocked_by": "lacks_range_attack"
      }
    ]
  }
}
```

**Action Probability Encoding:**

Probabilities are encoded in **half-percentage points** (0-200 range):
- `0` = 0% (impossible/blocked)
- `1` = 0.5% chance
- `100` = 50% chance  
- `175` = 87.5% chance
- `200` = 100% (guaranteed success)
- Special values:
  - `253` = Not yet known (server computing)
  - `254` = Unknown (requires server query)

**Action Fields:**
- `action_id`: FreeCiv internal action ID
- `action_type`: Machine-readable action type (e.g., "attack", "found_city")
- `action_name`: Human-readable action name
- `probability`: Raw probability (0-200, half-percentage points)
- `probability_percent`: Normalized percentage (0.0-100.0)
- `min_distance`/`max_distance`: Valid range for action
- `target_kind`: Required target type ("self", "unit", "city", "tile", "extra")
- `blocked_by` (optional): Reason action is unavailable (if probability = 0)

**Batch Queries:**

Query actions for multiple units in a single request:

```json
{
  "type": "unit_action_query_batch",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "data": {
    "queries": [
      {"unit_id": 42, "request_kind": 0},
      {"unit_id": 43, "target_unit_id": 50},
      {"unit_id": 44, "target_tile_id": 1600}
    ]
  }
}
```

**Performance Considerations:**
- Action queries are cached for 1 turn by default
- Batch queries are preferred for efficiency (single round-trip)
- Queries executed when unit gains focus or on explicit request
- Cache invalidated on game state changes affecting the unit

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
- `unit_clean_pollution`: Clean pollution at specified coordinates
- `unit_clean_fallout`: Clean nuclear fallout at specified coordinates
- `unit_transform_terrain`: Transform terrain type at specified coordinates
- `cultivate`: Cultivate terrain to remove vegetation (e.g., forest → plains)
- `plant`: Plant vegetation to add forests (e.g., plains → forest)
- `base`: Build military base (fortress/airbase) for defense and air operations
- `city_production`: Set city production
- `city_build_unit`: Build specific unit type
- `city_build_improvement`: Build city improvement
- `city_buy`: Rush production with gold
- `upgrade_unit`: Upgrade unit to newer type
- `bombard`: Ranged attack on target
- `pillage`: Destroy terrain improvement
- `transport_board`: Board a transport unit
- `transport_deboard`: Disembark from transport
- `transport_unload`: Unload cargo from transport
- `airlift`: Airlift unit between cities
- `establish_embassy`: Establish embassy in city
- `spy_investigate_city`: Spy investigates city details
- `spy_poison`: Poison city's food supply
- `spy_sabotage_city`: Sabotage city production
- `spy_steal_tech`: Steal technology from civilization
- `spy_bribe_unit`: Bribe enemy unit to defect
- `spy_steal_gold`: Steal gold from city treasury
- `spy_incite_city`: Incite city revolt to defect
- `trade_route`: Establish trade route with city
- `city_sell_improvement`: Sell an existing city improvement for gold refund
- `tech_research`: Research technology
- `diplomacy_message`: Send diplomatic message
- `help_wonder`: Add unit shields to wonder construction
- `conquer_city`: Military unit conquers enemy city
- `capture_units`: Capture defeated units instead of destroying
- `steal_maps`: Spy steals enemy civilization maps
- `convert`: Convert unit (religion, government, etc.)
- `home_city`: Change unit's home city for support
- `end_turn`: End current turn
- `player_ready`: Mark player slot ready in lobby (turn==0 only)

#### player_ready

Mark the connecting player slot as ready during the pre‑game lobby (before the game has started; `turn == 0`). When **all** connected players have selected nations and sent `player_ready`, the civserver (with autotoggle enabled) automatically starts the game. A separate `game_ready` broadcast (see Game Session Lifecycle) is then emitted to all agents.

This action is only valid while the session phase is one of:
- `waiting_for_players`
- `nations_selecting`

It becomes invalid once the phase transitions to `ready_to_start`, `starting`, `running`, or `ended` (the validation layer treats any non‑lobby phase as disallowed). The action is idempotent per player; sending it again after success returns an error.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "ready-1",
  "data": {
    "action_type": "player_ready",
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "ready-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "player_ready",
    "result": {
      "player_id": 1,
      "phase_before": "nations_selecting",
      "phase_after": "nations_selecting",
      "all_players_ready": false
    }
  }
}
```

When the final player sends `player_ready`:
```json
{
  "type": "action_result",
  "agent_id": "last-agent",
  "timestamp": 1234567890.125,
  "correlation_id": "ready-final",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "player_ready",
    "result": {
      "player_id": 2,
      "phase_before": "nations_selecting",
      "phase_after": "ready_to_start",
      "all_players_ready": true
    }
  }
}
```

**Validation Rules:**
1. `player_id` must match authenticated session
2. Game must be in lobby (turn == 0)
3. Session phase must be `waiting_for_players` or `nations_selecting`
4. Player must have selected a nation (if nation selection is enforced)
5. Player must not already be marked ready

**Error Codes (Session / Lifecycle Range E300–E309):**
- `E300`: Game not in lobby (turn > 0 or phase already progressed)
- `E301`: Player already marked ready
- `E302`: Invalid session phase for readiness
- `E303`: Nation not selected yet (precondition unmet)
- `E304`: Player record not found in session

**Notes:**
- Repeated calls after success return `E301` (idempotent handling)
- The server auto‑starts; no explicit `/start` command is sent
- Transition to `ready_to_start` then `starting` is asynchronous; agents should wait for `game_ready` instead of polling
- Do **not** send during or after `running` phase – use normal gameplay actions instead

#### city_buy

Rush production in a city by paying gold. This allows completing the current production item immediately at a significant gold cost. Available only when the city has sufficient gold in the treasury.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "buy-1",
  "data": {
    "action_type": "city_buy",
    "city_id": 5,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "buy-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "city_buy",
    "result": {
      "city_id": 5,
      "production_completed": "warrior",
      "gold_spent": 40,
      "treasury_remaining": 110
    }
  }
}
```

**Validation Rules:**
1. `city_id` must exist and belong to player
2. City must have production set
3. Player must have sufficient gold (cost varies by production item and progress)
4. Production cannot already be complete this turn
5. Cannot rush production on certain items (wonders in some rulesets)

**Error Codes (Economy Range E200–E299):**
- `E201`: City not found or not owned by player
- `E202`: No production set in city
- `E203`: Insufficient gold to rush production
- `E204`: Production cannot be rushed (e.g., wonder restrictions)
- `E205`: Production already complete this turn
- `E206`: Invalid city_id parameter

#### city_sell_improvement

Sell (liquidate) an existing improvement in a city for a partial gold refund (usually a fraction of its original build cost). This can be used to reclaim resources or remove obsolete infrastructure.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "sell-1",
  "data": {
    "action_type": "city_sell_improvement",
    "city_id": 5,
    "improvement_name": "Barracks",
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

Alternative (direct id):
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "sell-2",
  "data": {
    "action_type": "city_sell_improvement",
    "city_id": 5,
    "improvement_id": 7,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "sell-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "city_sell_improvement",
    "result": {
      "city_id": 5,
      "improvement_id": 7,
      "improvement_name": "Barracks",
      "gold_refunded": 20,
      "did_sell": true,
      "treasury_total": 130
    }
  }
}
```

**Validation Rules:**
1. `city_id` must exist and belong to player
2. Either `improvement_id` or `improvement_name` must be provided
3. Improvement must be present in the city
4. Improvement must be sellable (not marked `unsellable` in ruleset)
5. City cannot have already sold an improvement this turn (`did_sell` flag)

**Error Codes (Economy Extension E142–E149):**
- `E142`: Missing required fields (city_id + improvement identifier)
- `E143`: City not found or not owned by player
- `E144`: Improvement not present / unsellable / already sold this turn

**Usage Notes:**
- Gold refund is typically a portion of original cost (ruleset dependent)
- Common targets for selling: obsolete military buildings, redundant infrastructure
- Avoid selling essential economic buildings early (e.g., Granary) unless strategy shifts
- Use after capturing a city to remove mismatched infrastructure

**Prompt Examples:**
```
"Sell the barracks in city 5 to reclaim gold."
"Liquidate the granary in our frontier city (id 12)."
"Convert obsolete infrastructure to cash: sell Aqueduct in city 17."
```

#### upgrade_unit

Upgrade a unit to a newer, more advanced type. The unit must be in a city or on a tile with appropriate infrastructure (fortress/airbase for some units). Costs gold based on the upgrade path.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "upgrade-1",
  "data": {
    "action_type": "upgrade_unit",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "upgrade-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "upgrade_unit",
    "result": {
      "unit_id": 42,
      "old_type": "phalanx",
      "new_type": "musketeers",
      "gold_spent": 30,
      "treasury_remaining": 80
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have an available upgrade path
3. Player must have sufficient gold for upgrade
4. Unit must be in a city or appropriate tile
5. Unit must have full movement points (cannot have moved this turn)
6. Upgrade technology must be researched

**Error Codes (Economy Range E200–E299):**
- `E201`: Unit not found or not owned by player
- `E202`: No upgrade available for this unit type
- `E203`: Insufficient gold for upgrade
- `E204`: Unit not in valid location for upgrade
- `E205`: Unit has moved this turn (no movement points remaining)
- `E206`: Required technology not researched

#### bombard

Execute a ranged attack on a target unit or city. The attacking unit must have ranged attack capability and the target must be within range. Does not end the unit's turn, allowing subsequent moves.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "bombard-1",
  "data": {
    "action_type": "bombard",
    "unit_id": 42,
    "target_tile_x": 15,
    "target_tile_y": 20,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "bombard-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "bombard",
    "result": {
      "unit_id": 42,
      "target_x": 15,
      "target_y": 20,
      "damage_dealt": 25,
      "target_destroyed": false
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have bombard capability
3. Target tile must be within unit's bombard range
4. Unit must have movement points remaining
5. Target must be visible to player
6. Cannot bombard friendly units (unless special ruleset)

**Error Codes (Tactical Range E100–E199):**
- `E107`: Unit does not have bombard capability
- `E108`: Target out of range
- `E109`: Missing required field (unit_id or target coordinates)
- `E110`: Unit not found or invalid unit_id
- `E111`: Unit not owned by player
- `E112`: Insufficient movement points
- `E113`: Target not visible

#### pillage

Destroy a terrain improvement (road, irrigation, mine, etc.) at the unit's current location. Takes one turn to complete.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "pillage-1",
  "data": {
    "action_type": "pillage",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "pillage-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "pillage",
    "result": {
      "unit_id": 42,
      "activity_started": "pillage",
      "estimated_turns": 1
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Tile must have improvements that can be pillaged
3. Unit must have pillage capability
4. Unit must not be in a city
5. Tile must not be within player's own territory (in standard rules)

**Error Codes (Economy Range E200–E299):**
- `E201`: Unit not found or not owned by player
- `E202`: No improvements available to pillage at location
- `E203`: Unit lacks pillage capability
- `E204`: Cannot pillage in own territory
- `E205`: Unit is in a city

#### transport_board

Board a transport unit (ship, aircraft carrier, etc.). The transport must be on the same tile and have cargo capacity available.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "board-1",
  "data": {
    "action_type": "transport_board",
    "unit_id": 42,
    "target_unit_id": 50,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "board-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "transport_board",
    "result": {
      "unit_id": 42,
      "transport_id": 50,
      "cargo_count": 1,
      "cargo_capacity": 3
    }
  }
}
```

**Validation Rules:**
1. `unit_id` and `target_unit_id` must exist
2. Both units must belong to the same player
3. Units must be on the same tile
4. Target must be a transport unit with cargo capacity
5. Transport must have available cargo space
6. Unit must be compatible with transport type (land unit on ship, etc.)

**Error Codes (Transport Range E350–E399):**
- `E350`: Unit not found or not owned by player
- `E351`: Transport not found or not owned by player
- `E352`: Units not on same tile
- `E353`: Target is not a transport unit
- `E354`: Transport at full capacity
- `E355`: Unit type incompatible with transport
- `E356`: Missing target_unit_id parameter

#### transport_deboard

Disembark from a transport unit to an adjacent tile. The destination tile must be valid terrain for the unit type.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "deboard-1",
  "data": {
    "action_type": "transport_deboard",
    "unit_id": 42,
    "target_tile_x": 10,
    "target_tile_y": 20,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "deboard-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "transport_deboard",
    "result": {
      "unit_id": 42,
      "new_x": 10,
      "new_y": 20,
      "transport_id": 50
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must currently be loaded on a transport
3. Target tile must be adjacent to transport's location
4. Target tile must be valid terrain for unit type
5. Target tile must not be occupied by enemy units

**Error Codes (Transport Range E350–E399):**
- `E350`: Unit not found or not owned by player
- `E351`: Unit not currently loaded on transport
- `E352`: Target tile not adjacent to transport
- `E353`: Invalid terrain for unit type
- `E354`: Target tile occupied by enemy units
- `E355`: Missing target coordinates

#### transport_unload

Unload a specific cargo unit from a transport. The cargo unit will be placed on the transport's current tile.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "unload-1",
  "data": {
    "action_type": "transport_unload",
    "unit_id": 50,
    "target_unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "unload-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "transport_unload",
    "result": {
      "transport_id": 50,
      "unloaded_unit_id": 42,
      "remaining_cargo": 2
    }
  }
}
```

**Validation Rules:**
1. `unit_id` (transport) must exist and belong to player
2. `target_unit_id` (cargo) must exist and belong to player
3. Cargo unit must be loaded on the specified transport
4. Transport's current tile must be valid terrain for cargo unit
5. Tile must not be occupied by maximum units

**Error Codes (Transport Range E350–E399):**
- `E350`: Transport not found or not owned by player
- `E351`: Cargo unit not found or not owned by player
- `E352`: Cargo unit not loaded on this transport
- `E353`: Cannot unload on current terrain
- `E354`: Tile at maximum unit capacity
- `E355`: Missing target_unit_id parameter

#### airlift

Airlift a unit from one city to another. Both cities must have airports and be controlled by the player.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "airlift-1",
  "data": {
    "action_type": "airlift",
    "unit_id": 42,
    "target_city_id": 8,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "airlift-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "airlift",
    "result": {
      "unit_id": 42,
      "from_city_id": 3,
      "to_city_id": 8,
      "new_x": 25,
      "new_y": 30
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must be in a city with an airport
3. `target_city_id` must exist, belong to player, and have an airport
4. Unit must not have moved this turn
5. Cities must not be in the same location
6. Airlift capacity not exceeded (ruleset-dependent)

**Error Codes (Transport Range E350–E399):**
- `E350`: Unit not found or not owned by player
- `E351`: Unit not in a city
- `E352`: Source city lacks airport
- `E353`: Target city not found or not owned
- `E354`: Target city lacks airport
- `E355`: Unit has already moved this turn
- `E356`: Airlift capacity exceeded

#### establish_embassy

Establish an embassy in a foreign city. Requires a diplomat or spy unit adjacent to or in the target city.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "embassy-1",
  "data": {
    "action_type": "establish_embassy",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "embassy-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "establish_embassy",
    "result": {
      "unit_id": 42,
      "city_id": 10,
      "target_player_id": 2,
      "embassy_established": true
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must be a diplomat or spy
3. `target_city_id` must exist and not belong to player
4. Unit must be adjacent to or in the target city
5. Embassy must not already exist with target civilization
6. Unit must have movement points

**Error Codes (Diplomacy Range E310–E349):**
- `E310`: Unit not found or not owned by player
- `E311`: Unit is not a diplomat/spy
- `E312`: Target city not found or is own city
- `E313`: Unit not adjacent to target city
- `E314`: Embassy already exists with this civilization
- `E315`: Insufficient movement points

#### spy_investigate_city

Spy investigates a foreign city to reveal detailed information (production, units, buildings, etc.).

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spy-investigate-1",
  "data": {
    "action_type": "spy_investigate_city",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "spy-investigate-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "spy_investigate_city",
    "result": {
      "unit_id": 42,
      "city_id": 10,
      "investigation_successful": true,
      "unit_consumed": false
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist, belong to player, and be a spy
2. `target_city_id` must exist and not belong to player
3. Unit must be adjacent to or in target city
4. Unit must have movement points

**Error Codes (Espionage Range E400–E449):**
- `E400`: Unit not found or not owned by player
- `E401`: Unit is not a spy
- `E402`: Target city not found or is own city
- `E403`: Unit not adjacent to target city
- `E404`: Insufficient movement points

#### spy_poison

Spy poisons a city's food supply, reducing food storage and potentially causing starvation.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spy-poison-1",
  "data": {
    "action_type": "spy_poison",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "spy-poison-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "spy_poison",
    "result": {
      "unit_id": 42,
      "city_id": 10,
      "poisoning_successful": true,
      "unit_consumed": true
    }
  }
}
```

**Validation Rules:**
(Same validation rules as spy_investigate_city)

**Error Codes:** Same as spy_investigate_city (E400–E404)

#### spy_sabotage_city

Spy sabotages city production or destroys a random building.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spy-sabotage-1",
  "data": {
    "action_type": "spy_sabotage_city",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "spy-sabotage-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "spy_sabotage_city",
    "result": {
      "unit_id": 42,
      "city_id": 10,
      "sabotage_successful": true,
      "building_destroyed": "barracks",
      "unit_consumed": true
    }
  }
}
```

**Validation Rules:**
(Same validation rules as spy_investigate_city)

**Error Codes:** Same as spy_investigate_city (E400–E404)

#### spy_steal_tech

Spy attempts to steal a technology from target civilization.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spy-steal-1",
  "data": {
    "action_type": "spy_steal_tech",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "spy-steal-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "spy_steal_tech",
    "result": {
      "unit_id": 42,
      "city_id": 10,
      "tech_stolen": "gunpowder",
      "unit_consumed": true
    }
  }
}
```

**Validation Rules:**
(Same validation rules as spy_investigate_city)

**Error Codes:** Same as spy_investigate_city (E400–E404)

#### spy_bribe_unit

Spy attempts to bribe an enemy unit to defect to the player's civilization.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spy-bribe-1",
  "data": {
    "action_type": "spy_bribe_unit",
    "unit_id": 42,
    "target_unit_id": 55,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "spy-bribe-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "spy_bribe_unit",
    "result": {
      "unit_id": 42,
      "bribed_unit_id": 55,
      "gold_spent": 150,
      "unit_consumed": false
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist, belong to player, and be a diplomat/spy
2. `target_unit_id` must exist and not belong to player
3. Units must be adjacent or on same tile
4. Player must have sufficient gold for bribe cost
5. Unit must have movement points

**Error Codes (Espionage Range E400–E449):**
- `E400`: Unit not found or not owned by player
- `E401`: Unit is not a diplomat/spy
- `E402`: Target unit not found or is own unit
- `E403`: Units not adjacent
- `E404`: Insufficient gold for bribe
- `E405`: Insufficient movement points

#### spy_steal_gold

Spy attempts to steal gold from the target city's treasury. The amount stolen is determined by the server based on the city's wealth, spy experience, and game difficulty.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spy-gold-1",
  "data": {
    "action_type": "spy_steal_gold",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "spy-gold-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "spy_steal_gold",
    "result": {
      "unit_id": 42,
      "target_city_id": 10,
      "gold_stolen": 75,
      "detected": false,
      "unit_consumed": false
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist, belong to player, and be a diplomat/spy
2. `target_city_id` must exist and not belong to player
3. Spy must be adjacent to or inside the target city
4. Unit must have movement points and not be busy
5. Mission may be detected (server-determined probability)

**Error Codes (Generic Spy Validation):**
- `E109`: Unit not found
- `E110`: Unit busy
- `E111`: Insufficient movement points
- `E113`: Player does not own spy unit
- `E115`: Target city not found or missing target_city_id
- `E116`: Action not possible per server
- `E402`: Unit is not a diplomat/spy

**Usage Notes:**
- Gold stolen scales with city wealth and spy experience
- Higher difficulty = lower steal amounts
- Risk of spy detection and capture
- Can be used repeatedly if not detected
- No gold cost to attempt (unlike bribe/incite)

**Prompt Example:**
```
"Send spy unit 42 to steal gold from enemy city 10."
```

#### spy_incite_city

Spy or diplomat attempts to incite a city revolt, causing it to defect to the player's civilization. The server calculates the gold cost based on city defenses, distance from capital, garrison strength, and diplomatic relations.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spy-incite-1",
  "data": {
    "action_type": "spy_incite_city",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "spy-incite-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "spy_incite_city",
    "result": {
      "unit_id": 42,
      "target_city_id": 10,
      "gold_spent": 500,
      "city_revolted": true,
      "new_owner": 1,
      "unit_consumed": true
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist, belong to player, and be a diplomat/spy
2. `target_city_id` must exist and not belong to player
3. Spy must be adjacent to or inside the target city
4. Player must have sufficient gold for incite cost (if known)
5. Unit must have movement points and not be busy
6. Capital cities typically cannot be incited

**Error Codes (Generic Spy Validation):**
- `E109`: Unit not found
- `E110`: Unit busy
- `E111`: Insufficient movement points
- `E113`: Player does not own spy unit
- `E115`: Target city not found or missing target_city_id
- `E116`: Action not possible per server
- `E402`: Unit is not a diplomat/spy
- `E403`: Insufficient gold for incitement

**Usage Notes:**
- Cost varies dramatically: 100-5000+ gold depending on city
- Capital cities usually immune or prohibitively expensive
- Strong garrison and nearby units increase cost
- Distance from target capital reduces cost
- Friendly diplomatic relations increase cost
- Mission typically consumes the spy/diplomat unit
- Query action availability first to get cost estimate
- One of the most expensive spy operations

**Prompt Example:**
```
"Use diplomat unit 42 to incite city 10 to revolt and join our civilization."
```

#### help_wonder

A unit adds its production shields to speed up wonder construction in a target city. The unit is consumed in the process, converting its production value into shields for the wonder.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "wonder-1",
  "data": {
    "action_type": "help_wonder",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "wonder-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "help_wonder",
    "result": {
      "unit_id": 42,
      "target_city_id": 10,
      "shields_added": 40,
      "wonder_name": "Great Library",
      "unit_consumed": true
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. `target_city_id` must exist and belong to player
3. Target city must be building a wonder
4. Unit must be in or adjacent to the target city
5. Unit must have movement points available

**Error Codes (Strategic Actions Range E600–E655):**
- `E600`: Missing unit_id field
- `E601`: Missing target_city_id field
- `E602`: Unit not found
- `E603`: Player does not own unit
- `E604`: City not found
- `E605`: Player does not own city
- `E116`: Action not possible (city not building wonder)

**Usage Notes:**
- Particularly effective with high-production units (Settlers, Engineers)
- Shields added equal unit's production cost
- Unit is always consumed when helping wonder
- Can significantly accelerate wonder completion
- Strategic for competitive wonder races
- More efficient than disbanding unit in city

**Prompt Example:**
```
"Send unit 42 to help complete the Great Library wonder in city 10."
```

#### conquer_city

A military unit conquers an enemy city through combat. The city is captured and becomes part of the conquering player's civilization. Population and improvements may be lost in the conquest.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "conquer-1",
  "data": {
    "action_type": "conquer_city",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "conquer-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "conquer_city",
    "result": {
      "unit_id": 42,
      "target_city_id": 10,
      "city_conquered": true,
      "new_owner": 1,
      "population_after": 3,
      "improvements_destroyed": 2
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must be a military unit (can_attack = true)
3. `target_city_id` must exist and not belong to player
4. Unit must be adjacent to target city
5. City defenses must be depleted (garrison defeated)
6. Unit must have movement points

**Error Codes (Strategic Actions Range E610–E616):**
- `E610`: Missing unit_id field
- `E611`: Missing target_city_id field
- `E612`: Unit not found
- `E613`: Player does not own unit
- `E614`: Unit cannot attack (not a military unit)
- `E615`: Target city not found
- `E616`: Cannot conquer own city

**Usage Notes:**
- Requires defeating city garrison first through unit_attack
- Population typically reduced by 1-2 citizens
- Some city improvements may be destroyed
- Palace/capital status preserved or reset
- Cultural borders may shift after conquest
- Unhappiness from conquest affects initial turns
- Strategic for territorial expansion and military victory

**Prompt Example:**
```
"Use warrior unit 42 to conquer the defenseless enemy city 10."
```

#### capture_units

A unit with capture capability (e.g., certain naval units) captures defeated enemy units instead of destroying them, converting them to the player's control.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "capture-1",
  "data": {
    "action_type": "capture_units",
    "unit_id": 42,
    "target_tile": 1234,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "capture-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "capture_units",
    "result": {
      "unit_id": 42,
      "target_tile": 1234,
      "units_captured": 1,
      "captured_unit_ids": [50]
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. `target_tile` must be specified
3. Unit must have capture capability (can_capture flag)
4. Target tile must contain defeatable enemy units
5. Unit must have movement points

**Error Codes (Strategic Actions Range E620–E624):**
- `E620`: Missing unit_id field
- `E621`: Missing target_tile field
- `E622`: Unit not found
- `E623`: Player does not own unit
- `E624`: Unit cannot capture (lacks capture capability)

**Usage Notes:**
- Typically available to naval units (privateers, cruisers)
- Captured units immediately join your civilization
- Maintains unit type and experience level
- More valuable than destroying enemy units
- Useful for building navy without production cost
- Ruleset-dependent: not all unit types can capture

**Prompt Example:**
```
"Use privateer unit 42 to capture the enemy ships at tile 1234."
```

#### steal_maps

A spy or diplomat steals map knowledge from an enemy civilization, revealing all terrain and cities they have explored. Provides significant intelligence advantage.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "maps-1",
  "data": {
    "action_type": "steal_maps",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "maps-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "steal_maps",
    "result": {
      "unit_id": 42,
      "target_city_id": 10,
      "tiles_revealed": 523,
      "detected": false,
      "unit_consumed": false
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must be a spy or diplomat
3. `target_city_id` must exist and not belong to player
4. Unit must be in or adjacent to target city
5. Unit must have movement points

**Error Codes (Strategic Actions Range E630–E636):**
- `E630`: Missing unit_id field
- `E631`: Missing target_city_id field
- `E632`: Unit not found
- `E633`: Player does not own unit
- `E634`: Unit must be spy or diplomat
- `E635`: Target city not found
- `E636`: Cannot steal maps from own city

**Usage Notes:**
- Reveals all terrain enemy has explored
- Shows enemy city locations and borders
- Does not reveal unit positions
- Relatively low-risk spy mission
- Can be repeated as enemy explores more
- Useful for military planning and strategy
- May be detected with small probability

**Prompt Example:**
```
"Send spy unit 42 to steal maps from enemy city 10 to reveal their territory."
```

#### convert

Converts a unit to a different type, religion, or government affiliation. The specific conversion depends on the unit type and ruleset configuration.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "convert-1",
  "data": {
    "action_type": "convert",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "convert-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "convert",
    "result": {
      "unit_id": 42,
      "converted": true,
      "unit_type_before": "Fanatics",
      "unit_type_after": "Riflemen"
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have conversion capability (can_convert flag)
3. Conversion must be allowed by ruleset
4. Unit must not be busy or in combat

**Error Codes (Strategic Actions Range E640–E643):**
- `E640`: Missing unit_id field
- `E641`: Unit not found
- `E642`: Player does not own unit
- `E643`: Unit cannot be converted

**Usage Notes:**
- Common use: government change converts fanatics
- Religious units may convert between religions
- Maintains unit experience and location
- Free conversion (no gold cost typically)
- Ruleset-specific availability
- Useful for adapting to government changes

**Prompt Example:**
```
"Convert fanatics unit 42 to regular riflemen after government change."
```

#### home_city

Changes a unit's home city for support and production purposes. The unit will now be supported by and upgrade in the new home city.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "home-1",
  "data": {
    "action_type": "home_city",
    "unit_id": 42,
    "city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "home-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "home_city",
    "result": {
      "unit_id": 42,
      "old_home_city_id": 5,
      "new_home_city_id": 10
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. `city_id` must exist and belong to player
3. Unit must not be busy or in combat
4. New home city must be able to support unit

**Error Codes (Strategic Actions Range E650–E655):**
- `E650`: Missing unit_id field
- `E651`: Missing city_id field
- `E652`: Unit not found
- `E653`: Player does not own unit
- `E654`: City not found
- `E655`: Player does not own city

**Usage Notes:**
- Redistributes unit support costs between cities
- Useful for managing city happiness and production
- Military units benefit from home city improvements
- Unit upgrades will happen in new home city
- Can reduce unhappiness in overcrowded cities
- Strategic for optimizing empire economy
- Free action (no gold cost)

**Prompt Example:**
```
"Change unit 42's home city to city 10 to balance support costs."
```

#### trade_route

Establish a trade route between two cities using a caravan or freight unit.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "trade-1",
  "data": {
    "action_type": "trade_route",
    "unit_id": 42,
    "target_city_id": 10,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "trade-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "trade_route",
    "result": {
      "unit_id": 42,
      "home_city_id": 5,
      "target_city_id": 10,
      "trade_value": 8,
      "unit_consumed": true
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist, belong to player, and be a caravan/freight
2. Unit must be in the target city
3. `target_city_id` must exist
4. Cities must not already have maximum trade routes
5. Trade route must be profitable (distance and size requirements)
6. Cities cannot already be connected by trade route

**Error Codes (Espionage/Trade Range E400–E449):**
- `E410`: Unit not found or not owned by player
- `E411`: Unit is not a caravan/freight
- `E412`: Unit not in target city
- `E413`: Target city not found
- `E414`: Maximum trade routes already established
- `E415`: Trade route not profitable (distance/size requirements)
- `E416`: Cities already connected by trade route

### Validation Error Codes

Error codes are grouped by action for fast triage:

| Range | Action | Notes |
|-------|--------|-------|
| E001-E005 | General | Structure, unknown type, capability, player mismatch |
| E010-E014 | unit_move | Missing fields, bad coords, ownership, unit not found |
| E020-E023 | unit_build_city | Missing unit, ownership, wrong unit type, not found |
| E030-E033 | city_production | Missing fields, invalid production, ownership, city not found |
| E040-E041 | tech_research | Missing tech_name, invalid tech |
| E050-E052 | unit_fortify | Missing unit_id, unit not found, ownership |
| E060-E062 | unit_sentry | Same pattern as fortify |
| E070-E072 | unit_build_road | Missing unit, ownership, not found |
| E080-E082 | unit_build_irrigation | Missing unit, ownership, not found |
| E090-E092 | unit_build_mine | Missing unit, ownership, not found |
| E100-E102 | unit_clean_pollution | Missing unit, ownership, not found |
| E103-E105 | unit_clean_fallout | Missing unit, ownership, not found |
| E106-E108 | unit_transform_terrain | Missing unit, ownership, not found |
| E145-E147 | cultivate | Missing unit_id, unit not found/not owned, busy/no moves/cannot cultivate |
| E148-E150 | plant | Missing unit_id, unit not found/not owned, busy/no moves/cannot plant |
| E151-E153 | base | Missing unit_id, unit not found/not owned, busy/no moves/cannot build base |
| E117-E122 | government_change | Missing field, invalid, already active, unavailable, cooldown, missing data |
| E123-E125 | disband_unit | Missing unit, ownership, not found |
| E126-E130 | join_city | Missing field, ownership, unit not found, invalid unit type, city not found/ownership |
| E131-E135 | city_change_specialist | Missing field, city not found, not owned, invalid from_specialist, invalid to_specialist |
| E300-E304 | player_ready | Session/lifecycle validation failures (see player_ready section) |
| E109 | unit_attack | Missing required field (unit_id/target_id) |
| E110-E116 | unit_attack | Attacker missing, ownership, target missing, friendly target, adjacency/movement, server reports attack unavailable |

Server authoritative action availability check (when cached actions present):
If an ACTION_ATTACK (id=45) is not listed in the unit's cached `unit_action_cache`, validation fails with `E116`.

Additional codes for future diplomacy / transport tiers will extend into E150+ ranges to avoid overlap.

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

### 7. Action System Architecture (v2.0)

#### Server-Authoritative Action Model

The protocol uses server-authoritative action queries for 100% accuracy:

```
LLM Agent → Unit Action Query → FreeCiv Server computes → Proxy returns actions → Agent decides → Submit action
                                  ↑ Server-authoritative (100% accuracy)
```



**Server-Authoritative Action System Benefits:**

| Aspect | Implementation |
|--------|----------------|
| Accuracy | 100% (matches FreeCiv rules exactly) |
| Coverage | All 60+ action types |
| Tech Requirements | Dynamic from ruleset |
| Terrain Restrictions | Complete validation |
| Diplomatic Rules | Fully enforced |
| Special Abilities | All included |
| Success Probabilities | Attack chances, diplomatic success rates |
| Ruleset Updates | Automatic with FreeCiv updates |

**Action Query Best Practices:**

1. **Lazy Loading**: Query actions only when needed (unit selected, planning phase)
2. **Batch Queries**: Use `unit_action_query_batch` for multiple units
3. **Cache Awareness**: Actions cached for 1 turn; re-query if game state changes
4. **Target Specification**: Specify targets for context-specific actions (attack, trade)
5. **Probability Thresholds**: Filter actions by `probability_percent >= threshold`

**Action Query Example:**

```python
# Query available actions for a unit
action_response = await query_unit_actions(unit_id=42, request_kind=0)

# Filter and execute based on probabilities
for action in action_response['data']['actions']:
    if action['action_type'] == 'attack' and action['probability_percent'] >= 70.0:
        # High confidence attack - proceed
        await submit_action(unit_id=42, action_type='attack', target_id=43)
    elif action['action_type'] == 'found_city' and action['probability'] == 200:
        # Guaranteed success - build city
        await submit_action(unit_id=42, action_type='unit_build_city')
```

### 8. Game Session Lifecycle

The multiplayer session progresses through discrete phases managed by the Game Session Manager (`waiting_for_players → nations_selecting → ready_to_start → starting → running → ended`). These phases gate which actions are valid:

| Phase | Description | Allowed Special Actions |
|-------|-------------|--------------------------|
| waiting_for_players | Fewer than min players have joined | `player_ready` (after nation selection where applicable) |
| nations_selecting | Min players reached; players picking nations | `player_ready` |
| ready_to_start | All players ready; civserver auto‑start pending | (No new readiness; await start) |
| starting | Civserver starting; turn still 0 | (All gameplay actions blocked) |
| running | Game active (turn ≥ 1) | All gameplay actions; `player_ready` invalid |
| ended | Game over | Only meta / summary queries |

#### GAME_READY (Broadcast)

Emitted once per session after the civserver confirms the game has begun (turn incremented to 1). This message signals agents that full state queries and gameplay actions are now valid.

**Example:**
```json
{
  "type": "game_ready",
  "agent_id": "agent-1",
  "timestamp": 1234567890.130,
  "data": {
    "type": "game_ready",
    "game_id": "game-123",
    "player_id": 1,
    "turn": 1,
    "players": 2,
    "message": "Game fully initialized - ready for state queries and actions"
  }
}
```

**Lifecycle Notes:**
- Agents should defer strategic planning until `game_ready` to avoid acting on incomplete state.
- The `player_ready` action never directly produces `game_ready`; it only contributes to readiness aggregation.
- If `game_ready` is not received within the expected window, agents may issue a lightweight `state_query` to confirm `turn >= 1`.
- Validation for actions during lobby phases returns `E300` (game not yet active).

### 8. Extended Validation Error Code Ranges

The error code system is segmented for clarity:

| Range | Category | Example Codes |
|-------|----------|---------------|
| E001–E099 | Core / common | Structural, capability, lookup failures |
| E100–E199 | Unit / city tactical | Movement, build, combat (e.g., attack adjacency) |
| E200–E299 | Economy / production | Rush buy, upgrade, trade route |
| E300–E309 | Session / lifecycle | `player_ready` phase and lobby validations |
| E310–E349 | Diplomacy / relations | Future embassy & spy prerequisites |
| E350–E399 | Transport / logistics | Boarding, airlift, capacity checks |
| E400–E449 | Espionage / covert | Spy action success/failure gates |
| E500–E549 | Action queries | Unit action query failures, invalid targets |
| E900–E999 | System / internal | Rate limit, auth, unknown errors |

**Action Query Error Codes (E500–E549):**
- `E500`: Unit not found for action query
- `E501`: Unit action query failed (server error)
- `E502`: Invalid target specified for action query
- `E503`: Action query timeout (server did not respond)
- `E504`: Unit action cache unavailable
- `E505`: Batch action query partial failure

Codes are documented in their respective action sections as they are added. Undocumented codes should be considered reserved.

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

#### unit_clean_pollution

Clean pollution from a tile. Worker or engineer units can remove pollution that appears on tiles due to industrial activity or overpopulation. This is essential for maintaining city productivity and preventing environmental degradation.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "clean-1",
  "data": {
    "action_type": "unit_clean_pollution",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "clean-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "unit_clean_pollution",
    "result": {
      "unit_id": 42,
      "activity_started": "clean_pollution",
      "estimated_turns": 3
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have pollution cleanup capability (Worker, Engineers)
3. Unit must be on a tile with pollution
4. Unit must have movement points remaining

**Error Codes (Terrain Management Range E100–E108):**
- `E100`: Missing unit_id field
- `E101`: Player does not own unit
- `E102`: Unit not found

**Notes:**
- Pollution appears on tiles with high production or overpopulation
- Cleaning takes multiple turns depending on unit type
- Engineers clean faster than Workers
- Pollution reduces tile output significantly

#### unit_clean_fallout

Clean nuclear fallout from a tile. This is critical after nuclear attacks or reactor meltdowns. Only units with fallout cleanup capability can perform this action.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "fallout-1",
  "data": {
    "action_type": "unit_clean_fallout",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "fallout-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "unit_clean_fallout",
    "result": {
      "unit_id": 42,
      "activity_started": "clean_fallout",
      "estimated_turns": 5
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have fallout cleanup capability (typically Engineers)
3. Unit must be on a tile with nuclear fallout
4. Unit must have movement points remaining

**Error Codes (Terrain Management Range E100–E108):**
- `E103`: Missing unit_id field
- `E104`: Player does not own unit
- `E105`: Unit not found

**Notes:**
- Fallout appears after nuclear weapon detonations
- Fallout makes tiles completely unusable until cleaned
- Cleaning fallout takes longer than cleaning pollution
- Only Engineers typically have this capability

#### unit_transform_terrain

Transform terrain from one type to another (e.g., plains to grassland, desert to plains). This powerful terraforming capability allows reshaping the landscape for optimal city placement and resource generation.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "transform-1",
  "data": {
    "action_type": "unit_transform_terrain",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "transform-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "unit_transform_terrain",
    "result": {
      "unit_id": 42,
      "activity_started": "transform",
      "from_terrain": "plains",
      "to_terrain": "grassland",
      "estimated_turns": 24
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have terrain transformation capability (typically Engineers)
3. Current terrain must have a valid transformation target per ruleset
4. Unit must have movement points remaining
5. Transformation rules determined by server/ruleset

**Error Codes (Terrain Management Range E100–E108):**
- `E106`: Missing unit_id field
- `E107`: Player does not own unit
- `E108`: Unit not found

**Notes:**
- Only Engineers typically can transform terrain
- Transformation takes many turns (often 20-30)
- Not all terrain types can be transformed
- Server determines valid transformations based on ruleset
- Examples: desert→plains, plains→grassland, swamp→grassland
- Strategic for optimizing city placement and resource output

#### cultivate

Cultivate terrain to change its type by removing vegetation or altering soil composition (e.g., forest → plains, jungle → grassland). This is a specialized terrain transformation that typically makes tiles more suitable for agriculture and development.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "cultivate-1",
  "data": {
    "action_type": "cultivate",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "cultivate-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "cultivate",
    "result": {
      "unit_id": 42,
      "activity_started": "cultivate",
      "from_terrain": "forest",
      "to_terrain": "plains",
      "estimated_turns": 8
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have cultivation capability (typically Workers/Engineers)
3. Current terrain must be cultivatable per ruleset rules
4. Unit must have movement points remaining
5. Unit must not be busy with another activity
6. Target terrain determined by server based on current tile

**Error Codes (Phase 6 Terrain Range E145–E147):**
- `E145`: Missing unit_id field
- `E146`: Unit not found or not owned by player
- `E147`: Unit busy, insufficient moves, or cannot cultivate

**Notes:**
- Cultivate removes vegetation, making land more farmable
- Common transformations: forest→plains, jungle→grassland
- Takes fewer turns than general terrain transformation
- Server determines exact target terrain based on ruleset
- Different from plant (which adds vegetation)

#### plant

Plant vegetation on terrain to change its type by adding trees or undergrowth (e.g., plains → forest, grassland → jungle). This adds natural resources and can provide strategic benefits like defense bonuses.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "plant-1",
  "data": {
    "action_type": "plant",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "plant-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "plant",
    "result": {
      "unit_id": 42,
      "activity_started": "plant",
      "from_terrain": "plains",
      "to_terrain": "forest",
      "estimated_turns": 10
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have planting capability (typically Workers/Engineers)
3. Current terrain must be plantable per ruleset rules
4. Unit must have movement points remaining
5. Unit must not be busy with another activity
6. Target terrain determined by server based on current tile

**Error Codes (Phase 6 Terrain Range E148–E150):**
- `E148`: Missing unit_id field
- `E149`: Unit not found or not owned by player
- `E150`: Unit busy, insufficient moves, or cannot plant

**Notes:**
- Plant adds vegetation, creating forests and jungle
- Common transformations: plains→forest, grassland→jungle
- Takes moderate turns to complete
- Forests provide production bonuses and strategic defense
- Opposite of cultivate action
- Server determines exact target terrain based on ruleset

#### base

Build a military base (fortress or airbase) on the current tile. Bases provide defense bonuses, allow aircraft operations, or serve as fortified positions for ground units.

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "base-1",
  "data": {
    "action_type": "base",
    "unit_id": 42,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "base-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "base",
    "result": {
      "unit_id": 42,
      "activity_started": "base",
      "base_type": "fortress",
      "estimated_turns": 6
    }
  }
}
```

**Validation Rules:**
1. `unit_id` must exist and belong to player
2. Unit must have base building capability (typically Settlers/Engineers)
3. Terrain must support base construction
4. Unit must have movement points remaining
5. Unit must not be busy with another activity
6. Base type determined by server based on unit capabilities and ruleset

**Error Codes (Phase 6 Terrain Range E151–E153):**
- `E151`: Missing unit_id field
- `E152`: Unit not found or not owned by player
- `E153`: Unit busy, insufficient moves, or cannot build base

**Notes:**
- Fortresses provide significant defense bonuses
- Airbases allow aircraft to land and refuel
- Construction takes several turns (typically 3-6)
- Server determines base type (fortress vs airbase) based on unit
- Bases persist after completion and benefit all friendly units
- Strategic for defending territory and supporting air power

#### government_change

Change the player's form of government. Governments affect empire-wide modifiers: corruption, unit upkeep, trade bonuses, happiness, and military support. This action sends a `PACKET_PLAYER_CHANGE_GOVERNMENT` (pid=54) with the target government ID.

LLM agents initiate the change; the server decides if an anarchy period occurs. The validator performs lightweight client-side checks; the server remains authoritative.

**Error Codes (Government Range E117–E122):**
- `E117`: Missing `government_name` field or empty value
- `E118`: Unrecognized government name (not present in game state lists)
- `E119`: Target government already active
- `E120`: Government recognized but not yet available (tech/prereq unmet)
- `E121`: Revolution/anarchy cooldown active – cannot change now
- `E122`: Government data missing from provided game state

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "gov-1",
  "data": {
    "action_type": "government_change",
    "player_id": 1,
    "government_name": "republic",
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "gov-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "government_change",
    "result": {
      "from_government": "despotism",
      "to_government": "republic",
      "turns_of_anarchy": 0
    }
  }
}
```

**Game State Fields (if available):**
```jsonc
{
  "player": {
    "current_government": "despotism",
    "revolution_active": false
  },
  "available_governments": ["despotism", "monarchy", "republic"]
}
```

**Government Name → ID Mapping (classic ruleset approximation):**
| Name | ID |
|------|----|
| despotism | 0 |
| monarchy | 1 |
| republic | 2 |
| democracy | 3 |
| communism | 4 |
| fundamentalism | 5 |

**Validation Rules:**
1. `government_name` must be provided and non-empty.
2. Government must be recognized (in available list or current).
3. Government must differ from current government.
4. Government must be in `available_governments` (prerequisites satisfied) or server will reject.
5. If `revolution_active` is true, reject with `E121`.
6. If no government data present, return `E122` but allow optimistic send.

**Usage Notes:**
- Some rulesets impose an anarchy period; server will report `turns_of_anarchy`.
- Switching too frequently may incur stability penalties (ruleset dependent).
- Advanced governments (e.g., Democracy) may require multiple techs; absence in `available_governments` triggers `E120`.
- LLM agents should plan large production or war shifts around stable governments.

**Prompt Examples:**
- "Adopt Republic to increase trade output."
- "Switch to Monarchy for better unit support before expansion."
- "Transition from Despotism to Democracy for long-term growth."

### Complete Multi-Turn Game Flow Example
#### disband_unit

Disband a unit to recover part of its production (shields) and remove upkeep. This is useful when modernizing forces or reducing maintenance costs.

Packet: `PACKET_UNIT_DO_ACTION` (pid=84) with `action_type=39` (`ACTION_DISBAND_UNIT`).

**Error Codes (E123–E125):**
- `E123`: Missing `unit_id` field
- `E124`: Player does not own unit
- `E125`: Unit not found

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "disband-1",
  "data": {
    "action_type": "disband_unit",
    "unit_id": 7,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "disband-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "disband_unit",
    "result": {
      "unit_id": 7,
      "disbanded": true,
      "shields_recovered": 10
    }
  }
}
```

#### join_city

Add a population point to a city by merging a worker/settler/engineer unit into it. Useful in early game for accelerating growth or consolidating surplus workers.

Packet: `PACKET_UNIT_DO_ACTION` (pid=84) with `action_type=28` (`ACTION_JOIN_CITY`).

**Error Codes (E126–E130):**
- `E126`: Missing `unit_id` or `city_id` field
- `E127`: Player does not own unit
- `E128`: Unit not found in provided game state
- `E129`: Unit type cannot join city (must contain one of: worker, settler, engineer)
- `E130`: City not found or not owned by player

**Request:**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "join-1",
  "data": {
    "action_type": "join_city",
    "unit_id": 101,
    "city_id": 55,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "join-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "join_city",
    "result": {
      "unit_id": 101,
      "city_id": 55,
      "joined": true,
      "population_added": 1
    }
  }
}
```

**Validation Rules:**
1. `unit_id` and `city_id` must be present.
2. Unit must exist and be owned by the player.
3. Unit type name must include one of: `worker`, `settler`, `engineer`.
4. City must exist and be owned by the player if city list provided; otherwise optimistic pass.
5. If game state omitted, validator allows optimistic send (server authoritative).

**Usage Notes:**
- Joining cities reduces unit upkeep and accelerates growth.
- Best used when a worker is no longer needed (e.g., terrain fully improved).
- Avoid joining during food scarcity—growth may stall.
- High-food cities benefit more from added population (can work additional tiles sooner).

**Prompt Examples:**
- "Merge an idle worker into the capital to boost population."
- "Join the frontier engineer to the newly founded city to speed growth."
- "Consolidate surplus settlers by adding them to the largest city." 

#### city_change_specialist

Convert one specialist type to another within a city. Specialists are citizens not working tiles—they provide flat bonuses (e.g., scientists generate research, entertainers provide happiness, taxmen generate gold). This action enables micromanagement of citizen allocation for optimizing city output.

Packet: `PACKET_CITY_CHANGE_SPECIALIST` (pid=39) with fields `city_id`, `from` (specialist type ID), `to` (specialist type ID).

**Error Codes (E131–E135):**
- `E131`: Missing `city_id`, `from_specialist`, or `to_specialist` field
- `E132`: City not found in game state
- `E133`: City not owned by player
- `E134`: Invalid `from_specialist` type (negative number or unrecognized name)
- `E135`: Invalid `to_specialist` type (negative number or unrecognized name)

**Specialist Types (Standard Ruleset):**
| Name | ID | Provides |
|------|----|-----------|
| elvis (entertainer) | 0 | Happiness (reduces unhappiness) |
| scientist | 1 | Research (beakers) |
| taxman | 2 | Gold (coins) |

**Request (using string names):**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spec-1",
  "data": {
    "action_type": "city_change_specialist",
    "city_id": 10,
    "from_specialist": "elvis",
    "to_specialist": "scientist",
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Request (using numeric IDs):**
```json
{
  "type": "action",
  "agent_id": "my-agent",
  "timestamp": 1234567890.123,
  "correlation_id": "spec-2",
  "data": {
    "action_type": "city_change_specialist",
    "city_id": 10,
    "from_specialist": 0,
    "to_specialist": 1,
    "player_id": 1,
    "game_id": "game-123"
  }
}
```

**Success Response:**
```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "spec-1",
  "data": {
    "type": "action_result",
    "success": true,
    "action_type": "city_change_specialist",
    "result": {
      "city_id": 10,
      "from_specialist": "elvis",
      "to_specialist": "scientist",
      "specialists_updated": true
    }
  }
}
```

**Validation Rules:**
1. `city_id`, `from_specialist`, and `to_specialist` must be present.
2. Specialist types can be specified as:
   - **String names**: `'elvis'`, `'entertainer'` (alias), `'scientist'`, `'taxman'` (case-insensitive)
   - **Numeric IDs**: `0`, `1`, `2` (non-negative integers)
3. City must exist and be owned by the player if game state provided.
4. Server validates that city has at least one specialist of `from` type and can use `to` type.
5. If game state omitted, validator allows optimistic send (server authoritative).

**Usage Notes:**
- Convert entertainers to scientists when happiness is stable and research is priority.
- Use taxmen when immediate gold is needed (e.g., for rush buying or unit upgrades).
- Entertainers are useful during We Love the Leader Day celebrations or when disorder threatens.
- Changing specialists is instantaneous (no build queue delay).
- Most efficient in large cities with many citizens available for reassignment.
- Server rejects if city has 0 specialists of `from` type or if `to` type unavailable (requires tech/building).

**Prompt Examples:**
- "Convert an entertainer to a scientist in the capital to prioritize research."
- "Switch a scientist to a taxman in the border city to fund unit upgrades."
- "Reassign entertainers to scientists once the temple provides sufficient happiness."

**Validation Rules:**
1. `unit_id` must be provided.
2. Unit must belong to the player.
3. Unit must exist in game state (if provided).
4. Additional constraints (cargo, last defender, city size) enforced by server.

**Notes:**
- Recover percentage varies by ruleset.
- Use before upgrading en masse to avoid upkeep on obsolete units.
- Consider strategic defense before disbanding frontline units.

**Prompt Examples:**
- "Disband obsolete warrior in the core city to recover shields."
- "Reduce maintenance by disbanding extra scouts."


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

- **2.0.0** (Nov 2025): Server-authoritative action system
  - Per-unit action queries with probability encoding
  - 100% accurate legal actions from FreeCiv server
  - Action probability system (success/failure chances)
  - Batch action query support
  - Real-time action availability based on game state

## Appendix: Complete v2.0 Workflow Example

### Server-Authoritative Action Query Pattern

```python
import asyncio
import websockets
import json
import time

async def intelligent_agent_v2():
    """Example agent using v2.0 per-unit action queries for 100% accuracy"""
    
    uri = "ws://localhost:8003/ws/agent/strategic-agent"
    
    async with websockets.connect(uri) as ws:
        # 1. Authenticate
        await ws.send(json.dumps({
            "type": "llm_connect",
            "agent_id": "strategic-agent",
            "timestamp": time.time(),
            "data": {
                "api_token": "secret_key",
                "game_id": "game-456"
            }
        }))
        
        auth = json.loads(await ws.recv())
        player_id = auth['data']['player_id']
        print(f"✅ Authenticated as player {player_id}")
        
        # 2. Query game state
        await ws.send(json.dumps({
            "type": "state_query",
            "agent_id": "strategic-agent",
            "timestamp": time.time(),
            "correlation_id": "state-1",
            "data": {
                "format": "llm_optimized"
            }
        }))
        
        state = json.loads(await ws.recv())
        units = state['data']['data']['units']
        
        # 3. Query actions for each unit (server-authoritative)
        for unit_id, unit in units.items():
            print(f"🔍 Querying actions for {unit['type']} (id={unit_id})")
            
            await ws.send(json.dumps({
                "type": "unit_action_query",
                "agent_id": "strategic-agent",
                "timestamp": time.time(),
                "correlation_id": f"query-{unit_id}",
                "data": {
                    "unit_id": int(unit_id),
                    "request_kind": 0  # All available actions
                }
            }))
            
            action_response = json.loads(await ws.recv())
            actions = action_response['data']['actions']
            
            print(f"  Available actions for unit {unit_id}:")
            for action in actions:
                if action['probability'] > 0:
                    print(f"    - {action['action_name']}: "
                          f"{action['probability_percent']:.1f}% success")
            
            # 4. Make intelligent decisions based on probabilities
            
            # Example: Attack if high success probability
            attack_actions = [a for a in actions 
                             if a['action_type'] == 'attack' 
                             and a['probability_percent'] >= 70.0]
            
            if attack_actions:
                print(f"  🎯 High-confidence attack available!")
                # Submit attack action...
            
            # Example: Build city if guaranteed success
            city_actions = [a for a in actions 
                           if a['action_type'] == 'found_city' 
                           and a['probability'] == 200]
            
            if city_actions:
                print(f"  🏛️ Can build city with 100% success!")
                await ws.send(json.dumps({
                    "type": "action",
                    "agent_id": "strategic-agent",
                    "timestamp": time.time(),
                    "data": {
                        "action_type": "unit_build_city",
                        "unit_id": int(unit_id),
                        "player_id": player_id
                    }
                }))
                
                result = json.loads(await ws.recv())
                if result['data']['success']:
                    print(f"  ✅ City built successfully!")
            
            # Example: Fortify if no better options
            fortify_actions = [a for a in actions 
                              if a['action_type'] == 'fortify']
            
            if fortify_actions and not attack_actions and not city_actions:
                print(f"  🛡️ Fortifying for defense")
                # Submit fortify action...
        
        # 5. Batch query for efficiency (multiple units)
        unit_ids = list(units.keys())[:5]  # First 5 units
        
        await ws.send(json.dumps({
            "type": "unit_action_query_batch",
            "agent_id": "strategic-agent",
            "timestamp": time.time(),
            "correlation_id": "batch-1",
            "data": {
                "queries": [
                    {"unit_id": int(uid), "request_kind": 0} 
                    for uid in unit_ids
                ]
            }
        }))
        
        batch_response = json.loads(await ws.recv())
        print(f"📦 Batch query returned actions for {len(unit_ids)} units")
        
        # 6. End turn
        await ws.send(json.dumps({
            "type": "action",
            "agent_id": "strategic-agent",
            "timestamp": time.time(),
            "data": {
                "action_type": "end_turn",
                "player_id": player_id
            }
        }))
        
        print("✅ Turn completed with server-authoritative actions!")

asyncio.run(intelligent_agent_v2())
```

### Key Advantages Demonstrated

1. **100% Accuracy**: Actions come directly from FreeCiv server, no rule mismatches
2. **Probability-Based Decisions**: Agent can evaluate success chances before committing
3. **Target Validation**: Server confirms valid targets, eliminating invalid attacks
4. **Ruleset Independence**: Works with any FreeCiv ruleset without proxy updates
5. **Performance**: Batch queries reduce round-trips for multi-unit planning

---

**End of Protocol Specification v2.0**

---

## Error Code Reference

This section provides a comprehensive reference of all validation error codes used in the LLM Gateway.

### General Validation (E001–E099)

| Code | Description |
|------|-------------|
| E001 | Action must be a dictionary |
| E002 | Action must specify a type |
| E003 | Unknown action type |
| E004 | Too many parameters (>20) |

### Movement & Basic Actions (E100–E149)

| Code | Description |
|------|-------------|
| E100 | Missing unit_id field |
| E101 | Unit not found |
| E102 | Player does not own unit |
| E103 | Unit is busy |
| E104 | Insufficient movement points |
| E105 | Invalid coordinates |
| E106 | Target coordinates out of bounds |
| E107 | Cannot move to target tile (terrain restriction) |
| E108 | Unit cannot perform this action |

### Combat Actions (E109–E119)

| Code | Description |
|------|-------------|
| E109 | Attacker unit not found |
| E110 | Unit busy |
| E111 | Insufficient movement points for attack |
| E112 | Target too far (not in range) |
| E113 | Player does not own attacker unit |
| E114 | Unit cannot attack (not a military unit) |
| E115 | Target not found or invalid |
| E116 | Action not possible (server-determined) |

### City Actions (E030–E041, E200–E249)

| Code | Description |
|------|-------------|
| E030 | city_build_unit requires city_id |
| E031 | city_build_unit requires unit_type |
| E032 | City not found |
| E033 | Player does not own city |
| E034 | unit_type must be a string |
| E035 | Unknown unit type |
| E036 | city_build_improvement requires city_id |
| E037 | city_build_improvement requires improvement |
| E038 | City not found |
| E039 | Player does not own city |
| E040 | improvement must be a string |
| E041 | Unknown improvement type |
| E200 | Missing city_id field |
| E201 | City not owned by player |
| E202 | Invalid production target |
| E203 | Insufficient gold for city_buy |

### Technology Research (E250–E299)

| Code | Description |
|------|-------------|
| E250 | Missing tech_name field |
| E251 | Unknown technology |
| E252 | Technology already researched |
| E253 | Technology prerequisites not met |

### Session & Lifecycle (E300–E309)

| Code | Description |
|------|-------------|
| E300 | Game not in lobby (turn > 0) |
| E301 | Player already marked ready |
| E302 | Invalid session phase for readiness |
| E303 | Nation not selected yet |
| E304 | Player record not found in session |

### Espionage & Trade (E400–E449)

| Code | Description |
|------|-------------|
| E400 | Missing target_city_id |
| E401 | Target city not found |
| E402 | Unit is not a diplomat/spy |
| E403 | Insufficient gold for operation |
| E404 | Mission failed (server-determined) |
| E410 | Trade route unit not found |
| E411 | Invalid trade route (cities too close) |
| E412 | Maximum trade routes reached |
| E413 | Cities already connected |

### Diplomacy (E500–E549)

| Code | Description |
|------|-------------|
| E500 | diplomacy_message requires target_player_id |
| E501 | diplomacy_message requires message_type |
| E502 | Invalid message_type |
| E503 | Cannot send diplomacy message to self |
| E504 | Target player not found |
| E505 | Message type not implemented |

### Strategic Actions (E600–E655)

| Code | Description |
|------|-------------|
| E600 | help_wonder requires unit_id |
| E601 | help_wonder requires target_city_id |
| E602 | Unit not found |
| E603 | Player does not own unit |
| E604 | City not found |
| E605 | Player does not own city |
| E610 | conquer_city requires unit_id |
| E611 | conquer_city requires target_city_id |
| E612 | Unit not found |
| E613 | Player does not own unit |
| E614 | Unit cannot attack (not a military unit) |
| E615 | Target city not found |
| E616 | Cannot conquer own city |
| E620 | capture_units requires unit_id |
| E621 | capture_units requires target_tile |
| E622 | Unit not found |
| E623 | Player does not own unit |
| E624 | Unit cannot capture (lacks capture capability) |
| E630 | steal_maps requires unit_id |
| E631 | steal_maps requires target_city_id |
| E632 | Unit not found |
| E633 | Player does not own unit |
| E634 | Unit must be spy or diplomat |
| E635 | Target city not found |
| E636 | Cannot steal maps from own city |
| E640 | convert requires unit_id |
| E641 | Unit not found |
| E642 | Player does not own unit |
| E643 | Unit cannot be converted |
| E650 | home_city requires unit_id |
| E651 | home_city requires city_id |
| E652 | Unit not found |
| E653 | Player does not own unit |
| E654 | City not found |
| E655 | Player does not own city |

### Error Response Format

All validation errors follow this structure:

```json
{
  "type": "action_result",
  "agent_id": "my-agent",
  "timestamp": 1234567890.124,
  "correlation_id": "action-123",
  "data": {
    "type": "action_result",
    "success": false,
    "action_type": "help_wonder",
    "error": {
      "code": "E602",
      "message": "Unit not found",
      "details": "Unit 999 does not exist in game state"
    }
  }
}
```

---
