# Game Start Race Condition Fix

## Problem Summary

LLM matches via game_arena were failing to start properly due to a race condition in the game initialization logic:

- **Symptom**: Games stuck in "connecting" state, no units/cities visible
- **Root Cause**: Multiple players independently trying to start the game before all were ready
- **Result**: civserver rejected /start command, game never initialized

## Solution

Implemented a centralized **GameSessionManager** to coordinate multi-player game initialization:

### Files Modified

1. **freeciv-proxy/game_session_manager.py** (NEW)
   - Centralized coordinator for game sessions
   - Tracks player connections, nation selection, and ready status
   - Ensures single /start command sent only when ALL players ready
   - Implements proper phase transitions (WAITING → NATIONS_SELECTING → READY_TO_START → STARTING → RUNNING)

2. **freeciv-proxy/llm_handler.py**
   - Removed individual `_start_game_after_delay()` method (race condition source)
   - Integrated with GameSessionManager for coordinated startup
   - Register players with session on connect
   - Notify session manager when nation selected and player ready

3. **freeciv-proxy/civcom.py**
   - Enhanced packet logging for /start commands and responses
   - Added tracking for PACKET_UNIT_INFO (95) and PACKET_CITY_INFO (85)
   - Better diagnostics for debugging game start issues

## How It Works

### Before (Race Condition)
```
Player 1 connects → waits 10s → checks if 2 players → sends /start
Player 2 connects → waits 10s → checks if 2 players → sends /start
Result: Both send /start, civserver confused, game fails
```

### After (Coordinated)
```
Player 1 connects → registers with session → selects nation → marks ready
Player 2 connects → registers with session → selects nation → marks ready
Session detects all ready → ONE /start command → game starts successfully
```

### Coordination Flow

1. **Player Connection**: Each player registers with `GameSessionManager` for their game_id
2. **Nation Selection**: Players send PACKET_NATION_SELECT_REQ, session tracks completion
3. **Ready Signal**: Players send PACKET_PLAYER_READY, session tracks ready status
4. **Game Start**: When ALL players ready, session's `_initiate_game_start()` triggers:
   - Configures game settings (/set minplayers, /set aifill, etc.)
   - Sends single /start command
   - Transitions to RUNNING phase

## Testing Instructions

### 1. Start FreeCiv3D Server
```bash
cd /Users/matan/Developer/freeciv3d
docker-compose up -d
```

### 2. Run Game Arena Test
```bash
docker exec game-arena python3 run_freeciv_game.py \
    --turns 10 \
    --auto_select_nations \
    --player1_nation="Americans" \
    --player2_nation="Romans" \
    --player1_leader="George Washington" \
    --player2_leader="Julius Caesar"
```

### 3. Monitor Logs for Success Indicators

**Look for these log messages in order:**

```
# Initial Connection
[INFO] Agent <agent_id> joining game session '<game_id>' on port 6000
[INFO] Registered agent <agent_id> with game session <game_id>

# Nation Selection
[INFO] Sent PACKET_NATION_SELECT_REQ for Americans (ID 0) - Leader: George Washington
[INFO] Game <game_id>: Player <agent_id> selected nation (1/2)
[INFO] Game <game_id>: Player <agent_id> selected nation (2/2)

# Ready Status
[INFO] Sent PACKET_PLAYER_READY for player 1
[INFO] Game <game_id>: Player <agent_id> marked ready (1/2)
[INFO] Game <game_id>: Player <agent_id> marked ready (2/2)

# Game Start Coordination
[INFO] Game <game_id>: ✓ All 2 players ready! Scheduling game start...
[INFO] Game <game_id>: 🎮 Starting game with 2 players!
[INFO] Game <game_id>: Configuring game settings...
[INFO] 🚀 Sent /start command to civserver on port 6000
[INFO] Game <game_id>: ✅ Game is now running!

# Game State Packets
[DEBUG] ← Received PACKET_UNIT_INFO (pid=95) for <agent>
[DEBUG] ← Received PACKET_CITY_INFO (pid=85) for <agent>
```

### 4. Verify Spectator Mode

Open the spectator URL (displayed in game-arena output):
```
http://localhost:8080/webclient/spectator.jsp?game_id=<game_id>&port=8003
```

**Expected**: Map visible with starting units and cities for both players

### 5. Check for Issues

**If game still doesn't start:**

```bash
# Check freeciv-proxy logs
docker exec fciv-net cat /docker/logs/freeciv-proxy-8002.log | grep -A5 -B5 "/start"

# Check civserver status
docker exec fciv-net ps aux | grep civserver

# Check if /start reached civserver
docker logs fciv-net 2>&1 | grep "SENDING /START"
```

## Expected Behavior

✅ **Success Indicators**:
- Both players connect within 5-10 seconds
- Nation selection completes for both players
- Session manager logs "All 2 players ready!"
- Single /start command sent
- PACKET_UNIT_INFO and PACKET_CITY_INFO received
- Spectator mode shows map with units/cities

❌ **Failure Indicators**:
- "Only 1 agents connected, waiting for more..." (timeout/network issue)
- No /start command sent (coordination logic broken)
- /start sent but no unit/city packets (civserver rejected start)
- Empty spectator view (game state not propagating)

## Debugging Tips

### Enable Debug Logging
In freeciv-proxy logs, look for `[DEBUG civcom]` and `[DEBUG GameSession]` messages.

### Check Session State
The GameSessionManager tracks:
- `game_id`: Unique identifier for the match
- `phase`: Current phase (WAITING_FOR_PLAYERS → RUNNING)
- `player_count`: Number of connected players
- `nations_selected`: Number of players who picked nations
- `players_ready`: Number of players who sent READY packet

### Common Issues

1. **"Units: 0, Cities: 0"** → /start command never sent or rejected
2. **Map not visible** → WebSocket connection to spectator failed
3. **Timeout waiting for players** → Network connectivity or Docker issues
4. **Multiple /start commands** → Race condition still present (check code)

## Rollback Plan

If this fix causes issues, revert with:
```bash
git checkout HEAD~1 freeciv-proxy/llm_handler.py freeciv-proxy/civcom.py
rm freeciv-proxy/game_session_manager.py
docker-compose restart fciv-net
```

## Next Steps

After successful test:
1. Monitor game progression (turns advance, units move)
2. Verify both players can take actions
3. Check performance with longer games (50+ turns)
4. Test with 3+ players if needed
