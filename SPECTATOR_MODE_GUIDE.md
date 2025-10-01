# FreeCiv3D Spectator Mode Guide

## Overview

FreeCiv3D now supports real-time spectator mode for watching both traditional FreeCiv games and LLM vs LLM matches. The spectator mode provides a web-based interface to observe games in progress without interfering with gameplay.

## Features

- **Real-time game viewing** - Watch games as they progress
- **Multi-game support** - Support for both traditional FreeCiv games and LLM Gateway games
- **WebSocket-based updates** - Live updates without page refresh
- **Responsive design** - Works on desktop and mobile browsers
- **Game state visualization** - Map, cities, units, and player information

## Accessing Spectator Mode

### For LLM vs LLM Games

LLM games running through the LLM Gateway can be viewed using these URLs:

```
http://localhost:8080/webclient/spectator.jsp?game_id=default&port=8003
```

**Parameters:**
- `game_id=default` - The game ID (use "default" for standard LLM games)
- `port=8003` - Port 8003 for LLM Gateway games

**Example URLs:**
- Standard LLM game: `http://localhost:8080/webclient/spectator.jsp?game_id=default&port=8003`
- Named LLM game: `http://localhost:8080/webclient/spectator.jsp?game_id=llm_match_001&port=8003`

### For Traditional FreeCiv Games

Traditional FreeCiv games running on the regular server can be viewed using:

```
http://localhost:8080/webclient/spectator.jsp?game_id=<game_id>&port=<game_port>
```

**Parameters:**
- `game_id` - Unique identifier for the game
- `port` - Game server port (typically 6000-6009)

**Example URLs:**
- Game on port 6000: `http://localhost:8080/webclient/spectator.jsp?game_id=game001&port=6000`
- Game on port 6001: `http://localhost:8080/webclient/spectator.jsp?game_id=game002&port=6001`
- Game on port 6002: `http://localhost:8080/webclient/spectator.jsp?game_id=game003&port=6002`

## Game Runner Integration

When running LLM vs LLM games using the game_arena integration, the game runner automatically provides spectator URLs in its output:

```bash
python /Users/matan/Developer/game_arena/run_match_with_spectator.py --turns=10 --player1=gemini --player2=openai
```

The output will include:

```
📺 SPECTATOR URLS:
Direct: http://localhost:8080/webclient/spectator.jsp?game_id=default&port=6000
Port 6001: http://localhost:8080/webclient/spectator.jsp?game_id=default&port=6001
Port 6002: http://localhost:8080/webclient/spectator.jsp?game_id=default&port=6002
```

**For LLM games, use the LLM Gateway spectator URL:**
```
http://localhost:8080/webclient/spectator.jsp?game_id=default&port=8003
```

## User Interface

### Spectator Header

The spectator mode includes a fixed header showing:

- **Spectating Status** - Indicates you're in spectator mode
- **LLM Game Indicator** - Shows if it's an LLM vs LLM game (with robot icon)
- **Game ID** - The unique identifier for the game
- **Port** - The server port being used
- **Connection Status** - Real-time connection indicator

### Available Tabs

- **Map** - Main game map with units, cities, and terrain
- **Nations** - Player information and statistics
- **Cities** - City listings and details
- **Options** - Spectator-specific settings (limited)

### Visual Indicators

- **LLM Games** - Header shows "SPECTATING LLM GAME" with golden robot icon
- **Traditional Games** - Header shows "SPECTATING"
- **Connection Status** - Color-coded status indicator (Green=Connected, Orange=Connecting, Red=Error)

## Technical Details

### WebSocket Connections

**LLM Games:**
- Connects to: `ws://localhost:8003/ws/spectator/{game_id}`
- Uses LLM Gateway WebSocket protocol
- Receives game state updates, turn changes, and player actions

**Traditional Games:**
- Connects to: `ws://localhost:8002/civsocket/{port}`
- Uses FreeCiv proxy WebSocket protocol
- Receives standard FreeCiv protocol messages

### Message Types

**LLM Gateway Messages:**
- `spectator_joined` - Confirmation of successful connection
- `game_state` - Complete game state updates
- `turn_update` - Turn number changes
- `player_action` - Individual player actions
- `game_ended` - Game completion with results

**Traditional FreeCiv Messages:**
- Standard FreeCiv protocol packets (PACKET_GAME_INFO, PACKET_MAP_INFO, etc.)

## Troubleshooting

### Common Issues

**1. "No Game Running" Error**
- Check that the game is actually running on the specified port
- Verify the game_id parameter matches the running game
- For LLM games, ensure the LLM Gateway is running on port 8003

**2. Connection Timeout**
- Verify Docker containers are running: `docker ps`
- Check FreeCiv proxy is running on port 8002: `docker exec fciv-net ps aux | grep 8002`
- Check LLM Gateway is running on port 8003: `docker exec fciv-net ps aux | grep 8003`

**3. Map Not Loading**
- Check browser console for JavaScript errors
- Verify WebSocket connection is established
- Ensure the game has been initialized (not in pregame state)

**4. Blank/Welcome Page**
- This usually indicates a connection failure
- Check that the correct port is being used
- Verify the game_id exists and the game is active

### Debugging Commands

```bash
# Check running containers
docker ps

# Check FreeCiv proxy processes
docker exec fciv-net ps aux | grep freeciv-proxy

# Check LLM Gateway status
docker exec fciv-net ps aux | grep uvicorn

# View proxy logs
docker exec fciv-net cat /docker/logs/freeciv-proxy-8002.log

# Test WebSocket connection
wscat -c ws://localhost:8002/ws/spectator/default
wscat -c ws://localhost:8003/ws/spectator/default

# Check game logs
docker exec fciv-net grep 'default' /docker/llm-gateway/logs/*.log
```

## Requirements

- Docker containers must be running
- FreeCiv proxy must be active on port 8002 (for traditional games)
- LLM Gateway must be active on port 8003 (for LLM games)
- Modern web browser with WebSocket support
- Network access to localhost:8080

## Security Notes

- Spectator mode is read-only - no game actions can be performed
- WebSocket connections are validated for authorized origins
- Spectator sessions do not affect game state or performance
- Multiple spectators can watch the same game simultaneously

## Development Notes

The spectator mode implementation includes:

- **Dual protocol support** - Handles both FreeCiv proxy and LLM Gateway protocols
- **Automatic detection** - Recognizes LLM games vs traditional games
- **Real-time updates** - Live game state synchronization
- **Error handling** - Graceful connection failure management
- **Mobile responsive** - Works on various screen sizes

For technical implementation details, see:
- `/freeciv-web/src/main/webapp/javascript/spectator_client.js`
- `/freeciv-web/src/main/webapp/webclient/spectator.jsp`
- `/llm-gateway/websocket_handlers.py`