# FreeCiv3D ↔ Game Arena Integration - Implementation Summary

## Overview

This document summarizes the changes made to enable proper end-to-end integration between game_arena and freeciv3d for LLM-driven gameplay.

## Root Causes Identified

### 1. **Port Conflict on 8002**
**Problem**: Both `start-freeciv-web.sh` and publite2's per-game proxies tried to bind to port 8002.
**Impact**: Proxy crashed, breaking LLM agent connections.

### 2. **Missing Metaserver API**
**Problem**: game_arena connected directly to hardcoded ports without metaserver coordination.
**Impact**: No mechanism to allocate fresh servers or track server state.

### 3. **Game Start Command Issues**
**Problem**: `/start` sent via PACKET_CHAT_MSG_REQ (chat) was processed but validation checks failed.
**Impact**: Games stayed in "Pregame" state. Validation requires:
  - At least `minplayers` human players
  - All players must have selected nations
  - Sufficient start units/cities configured

### 4. **Proxy Architecture Mismatch**
**Problem**: Single shared proxy on 8002 instead of per-game proxies (7000-7009).
**Impact**: Proxy instances killed when publite2 spawned games.

### 5. **Missing Redis**
**Problem**: State caching and rate limiting relied on Redis which wasn't running.
**Impact**: Performance degradation, no distributed rate limiting.

### 6. **MySQL Socket Permissions**
**Problem**: Docker user couldn't access MySQL socket.
**Impact**: Database queries failed intermittently.

---

## Changes Implemented

### Phase 1: Fix Proxy Architecture ✅

#### 1.1 `/docker/scripts/start-freeciv-web.sh`
- **Removed**: Startup of freeciv-proxy on port 8002
- **Reason**: Let publite2 manage per-game proxies (7000-7009)
- **Change**: Commented out proxy startup, added note about docker-entrypoint.sh

#### 1.2 `/docker/docker-entrypoint.sh`
- **Added**: Dedicated LLM Gateway proxy startup on port 8002
- **Added**: LLM Gateway (uvicorn) startup on port 8003
- **Process Isolation**: Each service runs in background with PID tracking
- **Startup Verification**: Health checks confirm services started

### Phase 2: Implement Metaserver Integration ✅

#### 2.1 New Java Servlets

**`/freeciv-web/src/main/java/org/freeciv/servlet/ServerAllocator.java`**
- **Endpoint**: `POST /freeciv-web/meta/allocate?type=multiplayer`
- **Function**: Allocates available server from pool
- **Returns**: `{host, port, proxy_port, type}`
- **Database**: Updates `servers` table to mark server unavailable

**`/freeciv-web/src/main/java/org/freeciv/servlet/ServerRelease.java`**
- **Endpoint**: `POST /freeciv-web/meta/release?host=localhost&port=6001`
- **Function**: Releases server back to available pool
- **Returns**: `{success: true}`
- **Database**: Updates `servers` table to mark server available

#### 2.2 `/llm-gateway/metaserver_client.py`
- **Class**: `MetaserverClient` for metaserver API communication
- **Methods**:
  - `allocate_server(game_type)` - Request server allocation
  - `release_server(host, port)` - Release server when game ends
  - `get_server_status()` - Query available server count
  - `allocate_with_retry()` - Allocation with exponential backoff
- **Error Handling**: Comprehensive timeout and retry logic

#### 2.3 `/llm-gateway/main.py`
- **Added**: Import of `metaserver_client`
- **Integration Point**: Gateway can now request servers dynamically
- **Next Step**: Update `connect_to_freeciv_proxy()` to use metaserver allocation

### Phase 3: Game Start Command ✅

#### Analysis Completed
- **Command Path**: PACKET_CHAT_MSG_REQ → `handle_chat_msg_req()` → `handle_stdin_input()` → `start_command()`
- **Validation Checks** in `/freeciv/freeciv/server/stdinhand.c:6144`:
  1. `minplayers` check: Must have ≥ N human players
  2. Nation check: All players must have selected nations
  3. Start units/city check: Must have valid starting conditions

#### Root Cause of Start Failure
**Issue**: game_arena sends `/start` correctly, but validation fails because:
1. LLM agents may not be marked as "human" players
2. Players haven't selected nations before `/start` is sent
3. `minplayers` setting may be > actual human player count

#### Solution Strategy
**For game_arena to implement**:
1. Send nation selection for each agent **before** sending `/start`
2. Send ready status for each player
3. Optionally: adjust server settings via `/set minplayers 0` before start
4. Monitor for game state transition from "Pregame" to "Running"

### Phase 4: Infrastructure Improvements ✅

#### 4.1 `/docker-compose.yml`
- **Added**: Redis service (redis:7-alpine)
- **Port**: 6379
- **Persistence**: Volume `redis_data` for append-only file
- **Health Check**: `redis-cli ping` every 10s
- **Dependency**: fciv-net waits for Redis to be healthy
- **Environment Variables**: Added `REDIS_HOST=redis` and `REDIS_PORT=6379`

#### 4.2 `/docker/docker-entrypoint.sh`
- **Fixed**: MySQL connection to use `sudo mysql` for root access
- **Added**: TCP fallback if socket connection fails
- **Improved**: Connection testing with proper error messages

---

## Testing Guide

### Step 1: Rebuild and Start Services

```bash
# Stop existing containers
docker-compose down -v

# Rebuild with fixes
docker-compose build

# Start services
docker-compose up -d

# Check service health
docker-compose ps
docker logs fciv-net | tail -50
```

### Step 2: Verify Service Startup

**Expected output in logs**:
```
✓ FreeCiv proxy started on port 8002 (PID: XXXX)
✓ LLM Gateway started on port 8003 (PID: XXXX)
```

**Check ports**:
```bash
docker exec fciv-net bash -c "ss -tuln | grep -E '(8002|8003|6379)'"
```

Should see:
- 8002 (freeciv-proxy)
- 8003 (LLM Gateway)
- 6379 (Redis - via redis container)

### Step 3: Test Metaserver API

**Allocate a server**:
```bash
curl -X POST "http://localhost:8080/freeciv-web/meta/allocate?type=multiplayer"
```

Expected response:
```json
{
  "success": true,
  "host": "localhost",
  "port": 6001,
  "proxy_port": 7001,
  "type": "multiplayer"
}
```

**Release the server**:
```bash
curl -X POST "http://localhost:8080/freeciv-web/meta/release?port=6001"
```

### Step 4: game_arena Integration Testing

**Sequence to test**:

1. **Allocate Server** (game_arena → metaserver):
   ```python
   response = requests.post(
       "http://localhost:8080/freeciv-web/meta/allocate",
       data={"type": "multiplayer"}
   )
   server_info = response.json()
   # Use server_info['port'] and server_info['proxy_port']
   ```

2. **Connect Agents** (game_arena → LLM Gateway → proxy):
   ```
   ws://localhost:8003/ws/agent/{agent_id}
   # Gateway will forward to ws://localhost:7001/llmsocket/7001
   ```

3. **Login and Join**:
   - Send `llm_connect` with game details
   - Wait for login confirmation
   - Select nation: Send nation selection packet
   - Mark ready: Send player ready packet

4. **Configure Game** (optional but recommended):
   ```
   /set minplayers 0
   /set aifill 0
   ```

5. **Start Game**:
   ```
   /start
   ```

6. **Monitor State**:
   - Watch for state transition: "Pregame" → "Running"
   - If start fails, check error message for specific validation failure

7. **Release Server** (when game ends):
   ```python
   requests.post(
       "http://localhost:8080/freeciv-web/meta/release",
       data={"port": server_info['port']}
   )
   ```

---

## Known Issues & Next Steps

### Remaining Issues

1. **Nation Selection Packet**: game_arena needs to send proper nation selection before `/start`
2. **Player Ready State**: Agents should mark themselves as ready
3. **LLM Agent Classification**: May need to mark LLM agents as "human" players for validation

### Recommended game_arena Changes

1. **Add Metaserver Client**:
   ```python
   class FreecivMetaserverClient:
       def allocate_server(self, game_type="multiplayer"):
           # Call /meta/allocate API
       def release_server(self, port):
           # Call /meta/release API
   ```

2. **Update Connection Flow**:
   - Request server from metaserver BEFORE connecting agents
   - Use dynamic ports from allocation response
   - Track server allocation per game instance

3. **Add Pre-Start Sequence**:
   ```python
   # After agents connect:
   for agent in agents:
       agent.select_nation(nation_name)  # Send nation selection packet
       agent.mark_ready()  # Send ready packet

   # Configure server
   game.send_command("/set minplayers 0")

   # Start game
   game.send_command("/start")

   # Wait for state transition
   game.wait_for_state("Running", timeout=30)
   ```

4. **Add State Monitoring**:
   - Listen for game state changes in packet stream
   - Detect "Pregame" → "Running" transition
   - Handle start failures gracefully

---

## File Modification Summary

### Modified Files
1. `/docker/scripts/start-freeciv-web.sh` - Removed port 8002 proxy
2. `/docker/docker-entrypoint.sh` - Added LLM Gateway + proxy startup, MySQL fixes
3. `/docker-compose.yml` - Added Redis service
4. `/llm-gateway/main.py` - Added metaserver client import

### New Files
1. `/freeciv-web/src/main/java/org/freeciv/servlet/ServerAllocator.java` - Server allocation API
2. `/freeciv-web/src/main/java/org/freeciv/servlet/ServerRelease.java` - Server release API
3. `/llm-gateway/metaserver_client.py` - Metaserver API client

### Configuration Changes
- Redis now required for state caching
- MySQL connection uses TCP fallback
- Environment variables added for Redis

---

## API Reference

### Metaserver Allocation API

**Allocate Server**
```
POST /freeciv-web/meta/allocate
Content-Type: application/x-www-form-urlencoded

type=multiplayer

Response 200:
{
  "success": true,
  "host": "localhost",
  "port": 6001,
  "proxy_port": 7001,
  "type": "multiplayer"
}

Response 503:
{
  "error": "No available servers of type 'multiplayer'. Please wait and retry."
}
```

**Release Server**
```
POST /freeciv-web/meta/release
Content-Type: application/x-www-form-urlencoded

host=localhost&port=6001

Response 200:
{
  "success": true,
  "host": "localhost",
  "port": 6001,
  "message": "Server released and available"
}
```

**Check Status**
```
GET /freeciv-web/meta/status

Response 200:
meta-status;0;0;0

Format: meta-status;total;singleplayer;multiplayer
```

---

## Success Criteria

✅ **Phase 1**: Proxy architecture fixed - no more port conflicts
✅ **Phase 2**: Metaserver API implemented and tested
✅ **Phase 3**: Game start command path analyzed and documented
✅ **Phase 4**: Redis and MySQL infrastructure fixed

🔲 **Integration Test**: End-to-end game from game_arena allocation to game completion
🔲 **Performance Test**: Multiple concurrent games with proper server allocation/release
🔲 **Error Recovery**: Server allocation retry logic tested

---

## Support & Debugging

### Check Service Status
```bash
# All services
docker-compose ps

# Specific logs
docker logs fciv-net
docker logs fciv-redis

# Inside container
docker exec -it fciv-net bash
ps aux | grep -E '(proxy|uvicorn|redis)'
```

### Common Issues

**Port 8002 still in use**:
- Check for old proxy processes: `docker exec fciv-net pkill -f freeciv-proxy`
- Restart container: `docker-compose restart fciv-net`

**Redis connection failed**:
- Verify Redis is running: `docker logs fciv-redis`
- Test connection: `docker exec fciv-redis redis-cli ping`

**MySQL socket error**:
- Use TCP connection in code: `-h 127.0.0.1 -P 3306`
- Verify permissions: `docker exec fciv-net sudo mysql -u root -e "SELECT user, host FROM mysql.user;"`

**Game won't start**:
1. Check server logs: `docker exec fciv-net tail -f /docker/logs/freeciv-web-log-6001.log`
2. Verify minplayers: `/show minplayers`
3. Check nations selected: `/list players`
4. Look for validation error in server output

---

## Contact

For issues or questions about this integration:
- Review logs in `/docker/logs/` directory
- Check Docker container status
- Verify all services are healthy before testing
- See Technical Spec.md for architecture details
