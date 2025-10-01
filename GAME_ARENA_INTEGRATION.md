# game_arena Integration Guide - PACKET_PLAYER_READY Protocol

## Overview

This guide explains how to integrate game_arena with freeciv3d using the **PACKET_PLAYER_READY** protocol for starting games.

## ✅ What's Implemented

### 1. PACKET_PLAYER_READY Protocol
- **Location**: `freeciv-proxy/llm_handler.py` lines 450-503
- **Handler**: `_handle_player_ready()` method
- **Packet ID**: 11 (from packets.def:434)

### 2. LLM Gateway Forwarding
- **Location**: `llm-gateway/websocket_handlers.py` lines 290-293
- **Function**: `_transform_to_proxy_format()` forwards ready packets

### 3. Services Running
- **FreeCiv Proxy**: Port 8002 ✅
- **LLM Gateway**: Port 8003 ✅
- **Redis**: Port 6379 ✅

## 🎯 How to Use PACKET_PLAYER_READY

### Connection Flow

```
game_arena → LLM Gateway (8003) → FreeCiv Proxy (8002) → FreeCiv Server (6xxx)
```

### Message Protocol

#### 1. Connect to LLM Gateway
```python
import websockets
import json

# Connect to LLM Gateway
ws_url = "ws://localhost:8003/ws/agent/{agent_id}"
async with websockets.connect(ws_url) as websocket:
    # Send connection packet
    await websocket.send(json.dumps({
        "type": "llm_connect",
        "token": "your-llm-api-token",
        "port": 6001,  # Game server port
        "username": "agent_name"
    }))
```

#### 2. Wait for Login Confirmation
```python
# Receive login confirmation
response = await websocket.recv()
data = json.dumps(response)
# Expected: {"type": "login_confirmed", "player_no": 1, ...}
```

#### 3. Select Nation
```python
# Send nation selection
await websocket.send(json.dumps({
    "type": "chat_message",
    "message": "/take Aztec"  # Or any available nation
}))
```

#### 4. Send PACKET_PLAYER_READY (NEW!)
```python
# Mark player as ready
await websocket.send(json.dumps({
    "type": "player_ready",
    "is_ready": True  # Optional, defaults to True
}))

# Expected response:
# {
#     "type": "ready_confirmed",
#     "player_no": 1,
#     "is_ready": true,
#     "message": "Player 1 marked ready"
# }
```

#### 5. Game Auto-Starts
**IMPORTANT**: The game automatically starts when **ALL** players send `is_ready=True`.

No need to send `/start` command!

### Complete Example

```python
import asyncio
import websockets
import json

async def start_game():
    # Agent 1
    async with websockets.connect("ws://localhost:8003/ws/agent/agent1") as ws1:
        # Connect agent 1
        await ws1.send(json.dumps({
            "type": "llm_connect",
            "token": "test-token-fc3d-001",
            "port": 6001,
            "username": "Agent1"
        }))

        # Wait for login
        await ws1.recv()

        # Select nation
        await ws1.send(json.dumps({
            "type": "chat_message",
            "message": "/take Aztec"
        }))

        # Mark ready
        await ws1.send(json.dumps({
            "type": "player_ready",
            "is_ready": True
        }))

        ready_response = await ws1.recv()
        print(f"Agent 1 ready: {ready_response}")

    # Agent 2 (same flow)
    async with websockets.connect("ws://localhost:8003/ws/agent/agent2") as ws2:
        await ws2.send(json.dumps({
            "type": "llm_connect",
            "token": "test-token-fc3d-002",
            "port": 6001,
            "username": "Agent2"
        }))

        await ws2.recv()

        await ws2.send(json.dumps({
            "type": "chat_message",
            "message": "/take Romans"
        }))

        # When agent 2 marks ready, game auto-starts!
        await ws2.send(json.dumps({
            "type": "player_ready",
            "is_ready": True
        }))

        ready_response = await ws2.recv()
        print(f"Agent 2 ready: {ready_response}")
        print("Game should now be starting!")

# Run
asyncio.run(start_game())
```

## 📋 Error Handling

### Error Responses

```python
# Not authenticated
{
    "type": "error",
    "code": "E401",
    "message": "Not authenticated as LLM agent"
}

# No player ID assigned yet
{
    "type": "error",
    "code": "E402",
    "message": "No player ID assigned yet"
}

# Packet sending failed
{
    "type": "error",
    "code": "E403",
    "message": "Failed to send ready packet: <error details>"
}

# Not connected to game server
{
    "type": "error",
    "code": "E404",
    "message": "Not connected to game server"
}
```

## 🔧 Optional: Server Settings

If needed, you can still send server configuration commands before marking players ready:

```python
# Configure server (optional)
await websocket.send(json.dumps({
    "type": "chat_message",
    "message": "/set minplayers 0"
}))

await websocket.send(json.dumps({
    "type": "chat_message",
    "message": "/set aifill 0"
}))

# Then mark ready
await websocket.send(json.dumps({
    "type": "player_ready",
    "is_ready": True
}))
```

## 🚀 Testing the Integration

### 1. Start FreeCiv3D
```bash
cd /path/to/freeciv3d
docker-compose up -d
```

### 2. Verify Services
```bash
# Check services are running
docker-compose ps

# Check logs
docker logs fciv-net | tail -50

# Expected output:
# ✓ FreeCiv proxy started on port 8002 (PID: XXX)
# ✓ LLM Gateway started on port 8003 (PID: XXX)
```

### 3. Test WebSocket Connection
```bash
# Install wscat if needed: npm install -g wscat

# Test connection
wscat -c "ws://localhost:8003/ws/agent/test_agent"

# Send test packet
> {"type":"llm_connect","token":"test-token-fc3d-001","port":6001,"username":"TestAgent"}
```

## 📊 Monitoring

### Check Service Status
```bash
# Inside container
docker exec fciv-net bash -c "ps aux | grep -E '(proxy|uvicorn)'"

# Check ports
docker exec fciv-net bash -c "ss -tupln | grep -E '(8002|8003)'"
```

### View Logs
```bash
# Proxy logs
docker exec fciv-net bash -c "tail -f /docker/logs/freeciv-proxy-PORT6000.log"

# Gateway logs
docker exec fciv-net bash -c "tail -f /docker/logs/llm-gateway.log"
```

## ⚠️ Known Issues & Solutions

### Issue: "Address already in use" on port 8002
**Solution**: Container fixed - docker-entrypoint.sh now properly starts only one proxy on 8002

### Issue: LLM Gateway fails to start
**Solution**: All dependencies (aiohttp, etc.) now installed in Dockerfile

### Issue: Game doesn't start after ready packets
**Possible causes**:
1. Not all players sent ready packets
2. Players haven't selected nations
3. Server validation checks failing (check server logs)

**Debug**:
```bash
# Check game server logs
docker exec fciv-net bash -c "tail -f /docker/logs/freeciv-web-log-6001.log"
```

## 🔗 References

- **Packet Definition**: `freeciv/freeciv/common/networking/packets.def` line 434
- **Server Handler**: `freeciv/freeciv/server/srv_main.c` lines 2399-2439
- **Browser Client Example**: `freeciv-web/src/main/webapp/javascript/pregame.js` line 38
- **Integration Summary**: `INTEGRATION_SUMMARY.md`

## 💡 Tips

1. **Always wait for login confirmation** before sending nation selection
2. **Select nations before** sending ready packets
3. **Monitor server logs** if game doesn't start
4. **Use proper authentication tokens** from LLM_API_TOKENS environment variable
5. **Test with 2 agents minimum** - single player games need different configuration

## 🎮 Next Steps

1. Implement the connection flow in game_arena
2. Test with 2+ agents connecting simultaneously
3. Add error recovery logic for failed connections
4. Monitor game state transitions
5. Implement cleanup when games end

## 📞 Support

If issues persist:
- Check `docker logs fciv-net` for startup errors
- Verify Redis is running: `docker logs fciv-redis`
- Ensure all environment variables are set in docker-compose.yml
- Review `INTEGRATION_SUMMARY.md` for architecture details
