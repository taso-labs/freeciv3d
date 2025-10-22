# FreeCiv Protocol Packet IDs Reference

This document provides the **authoritative packet ID mappings** for the FreeCiv protocol used in FreeCiv3D.

## ⚠️ CRITICAL: Spectator Architecture

**Spectators receive ALL packets** - just like normal FreeCiv clients and multiplayer observers.

**DO NOT filter packets** in the LLM Gateway. The spectator client will route packets using the standard `packet_handlers[]` table.

## Authoritative Source

Packet IDs are defined in: `freeciv/freeciv/common/networking/packets.def`

**JavaScript handlers are auto-generated** in: `freeciv-web/src/main/webapp/javascript/packhand_gen.js`

## Core Packet IDs

These packets are critical for game initialization and spectator mode:

| PID | Packet Name | Description | Required For |
|-----|-------------|-------------|--------------|
| **5** | `PACKET_SERVER_JOIN_REPLY` | Server confirms client connection | Connection establishment |
| **15** | `PACKET_TILE_INFO` | Tile terrain and visibility data | Map rendering |
| **16** | `PACKET_GAME_INFO` | Game settings and rules | Game initialization |
| **17** | `PACKET_MAP_INFO` | **Map dimensions and topology** | **Map rendering (CRITICAL)** |
| **31** | `PACKET_CITY_INFO` | City data | City display |
| **51** | `PACKET_PLAYER_INFO` | Player status and attributes | Player tracking |
| **63** | `PACKET_UNIT_INFO` | Unit position and properties | Unit display |
| **126** | `PACKET_START_PHASE` | Game phase start signal | Triggers renderer init |

## Initialization Sequence

For proper game initialization, packets must arrive in this dependency order:

```
1. PACKET_SERVER_JOIN_REPLY (PID 5)
   └─> Establishes connection

2. PACKET_MAP_INFO (PID 17)
   └─> Sets global `map` variable with xsize/ysize
   └─> Allocates tiles array
   └─> MUST come before renderer init

3. PACKET_GAME_INFO (PID 16)
   └─> Initializes game rules and settings

4. PACKET_TILE_INFO (PID 15)
   └─> Populates terrain data for each tile

5. PACKET_PLAYER_INFO (PID 51)
   └─> Sets up player state

6. PACKET_START_PHASE (PID 126)
   └─> Triggers client state = C_S_RUNNING
   └─> Calls renderer_init()
   └─> REQUIRES map variable already set
```

## Common Mistakes

### ❌ WRONG (October 2025 Bug)
These PIDs were incorrectly used in initial spectator implementation:

```python
# WRONG - DO NOT USE
[15, 25, 55, 75, 85, 95]  # These were guessed, not correct!
```

**Impact**:
- PID 17 (PACKET_MAP_INFO) was filtered out
- Spectators never received map data
- Map rendering failed with black screen

### ✅ CORRECT
```python
# Correct PIDs from packets.def
[15, 16, 17, 31, 51, 63]
```

## Spectator Architecture Details

### How Normal Clients Work
```
FreeCiv Server → WebSocket → client_handle_packet() → packet_handlers[PID]()
                                                            ↓
                                                    Handles ALL packets
```

### How Spectators Work (Correctly)
```
FreeCiv Server → LLM Gateway (forwards ALL packets) → Spectator → packet_handlers[PID]()
                                                                        ↓
                                                                Handles ALL packets
```

### Python (LLM Gateway)
**DO NOT filter packets**. Forward everything:

```python
# Forward ALL FreeCiv protocol packets to spectators
msg_pid = message.get("pid")
if msg_pid:
    await connection_manager.broadcast_to_spectators(game_id, {
        "type": "freeciv_update",
        "game_id": game_id,
        "packet_id": msg_pid,
        "data": message,
        "timestamp": time.time()
    })
```

### JavaScript (Spectator Client)
The spectator client has explicit handlers for common packets, with a **fallback to packet_handlers[]**:

```javascript
function handle_spectator_freeciv_message(message) {
  switch (message.pid) {
    case 5:   // PACKET_SERVER_JOIN_REPLY
    case 16:  // PACKET_GAME_INFO
    case 17:  // PACKET_MAP_INFO
    case 15:  // PACKET_TILE_INFO
    case 51:  // PACKET_PLAYER_INFO
    case 31:  // PACKET_CITY_INFO
    case 63:  // PACKET_UNIT_INFO
      // Special handling for these packets
      break;

    default:
      // Route ALL other packets to standard handlers
      if (typeof packet_handlers !== 'undefined' && packet_handlers[message.pid]) {
        packet_handlers[message.pid](message);
      }
      break;
  }
}
```

The `default` case ensures **all packets** are processed, even if not explicitly listed.

## Verification

To verify packet handler mappings:

```bash
# Check JavaScript handler registration
grep "handle_map_info" freeciv-web/src/main/webapp/javascript/packhand_gen.js

# Should show:
#   17:      handle_map_info,
```

## Additional Packet IDs

For complete packet ID listings, refer to:
- `freeciv/freeciv/common/networking/packets.def` (authoritative C source)
- `freeciv-web/src/main/webapp/javascript/packhand_gen.js` (generated JavaScript)

## Maintenance

**When FreeCiv is upgraded:**
1. Check if `packets.def` has changed
2. Regenerate `packhand_gen.js` using FreeCiv build tools
3. Update this documentation if PIDs changed
4. Update all hardcoded PID references in:
   - `llm-gateway/main.py`
   - `spectator_client.js`

---

**Last Updated**: January 2025
**FreeCiv Version**: Based on FreeCiv 3.x fork for FreeCiv3D
