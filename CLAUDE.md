# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Note**: For broader project context, roadmap, and technical specifications, refer to `Technical Spec.md` in the root directory.

## Development Commands

### Docker Development (Recommended)
- **Start services**: `docker-compose up -d`
- **Stop services**: `docker-compose down`
- **Access locally**: http://localhost:8080/

### Manual Build Commands
- **Build entire project**: `./build.sh`
- **Build Freeciv web client**: `cd freeciv-web && ./build.sh`
- **Build Freeciv C server**: `cd freeciv && ./prepare_freeciv.sh`
- **Maven build (web client)**: `cd freeciv-web && mvn -Dflyway.configFiles=./flyway.properties flyway:migrate package`

### Service Management Scripts
- **Start all services**: `./scripts/start-freeciv-web.sh`
- **Stop all services**: `./scripts/stop-freeciv-web.sh` 
- **Check status**: `./scripts/status-freeciv-web.sh`

### Web-LLM Component
The web-LLM component provides AI chat functionality using WebLLM (runs locally in browser):
- **Start dev server**: `cd freeciv-web/src/main/webapp/web-llm && npm start`
- **Start with MLC local config**: `cd freeciv-web/src/main/webapp/web-llm && npm run mlc-local`
- **Build for production**: `cd freeciv-web/src/main/webapp/web-llm && npm run build`

## Architecture Overview

Freeciv3D is a multi-component web-based strategy game with the following architecture:

### Core Components
1. **freeciv-web/**: Java web application (JSP/Javascript/HTML/CSS)
   - Client-side game interface using Three.js for 3D rendering
   - Runs on Tomcat with nginx proxy
   - Built with Maven
   
2. **freeciv/**: C server application 
   - Patched Freeciv server with WebSocket/JSON protocol support
   - Built with Meson build system
   - Handles game logic and state

3. **freeciv-proxy/**: Python WebSocket proxy
   - Tornado-based proxy server (port 8002)
   - Bridges WebSocket clients to Freeciv C server sockets
   - Handles protocol translation

4. **publite2/**: Python process launcher
   - Manages multiple Freeciv server instances
   - Monitors capacity through metaserver
   - Launches games on demand

5. **llm-gateway/**: Python FastAPI gateway (2 components)
   - **Dedicated FreeCiv Proxy** (port 8002) with `/llmsocket/8002` endpoint
   - **LLM Gateway API** (port 8003) - WebSocket API for LLM agent integration
   - Pass-through architecture with message transformation
   - Connection management, rate limiting, authentication
   - Enables agent-clash to control FreeCiv games
   - **Both components start automatically** with defaults from docker-compose.yml

### Communication Flow

**Standard Browser Flow:**
```
Browser (WebGL/WebGPU) → nginx → freeciv-web (Tomcat) → freeciv-proxy (WebSocket) → freeciv (C server)
```

**LLM Agent Flow:**
```
agent-clash → llm-gateway (8003) → freeciv-proxy (8002) → freeciv server (6000-6009)
```

### Server Allocation System

The LLM Gateway integration includes **dynamic server pool management** to prevent port conflicts in concurrent games:

- **ServerAllocator** (`POST /freeciv-web/meta/allocate`) - Allocates an available game server from the pool (ports 6000-6009), marks it as unavailable, and returns port information including the calculated proxy port (game_port + 1000).

- **ServerRelease** (`POST /freeciv-web/meta/release`) - Returns a game server to the available pool after game completion, resetting its state to 'Pregame'.

- **MetaserverClient** (`llm-gateway/metaserver_client.py`) - Python client for calling the allocation/release servlets from agent-clash or other Python components.

These servlets enable concurrent LLM games by treating the 10 game servers as a shared resource pool. The allocation system is documented in the `servers` MySQL table and managed through Java servlets in `freeciv-web/src/main/java/org/freeciv/servlet/`. For complete API documentation and usage examples, see [llm-gateway/README.md](llm-gateway/README.md).

### Technology Stack
- **Frontend**: JavaScript, Three.js, WebGL 2/WebGPU
- **Backend**: Java servlets (Jakarta), Python (Tornado), C
- **Database**: MySQL with Flyway migrations  
- **Build**: Maven (Java), Meson (C), npm (Node components)
- **Container**: Docker with multi-service orchestration

## Key Directories
- `config/`: Configuration templates and settings
- `scripts/`: Deployment and management scripts
- `doc/`: Documentation and screenshots  
- `logs/`: Application logs (created at runtime)

## Database
- Uses MySQL with Flyway for schema migrations
- Database configuration in `freeciv-web/flyway.properties`
- Migrations applied during Maven build process

## 3D Rendering
The game features both 2D and 3D modes, with the 3D version requiring WebGL 2 or WebGPU support for the Three.js rendering engine.

### 3D Implementation Details
- **WebGL Version**: Uses Three.js WebGL 2 renderer (legacy support)
- **WebGPU Version**: Uses Three.js WebGPU renderer (modern, experimental)
- **3D Assets**: Models and textures located in freeciv-web webapp structure
- **Renderer Selection**: Client automatically detects browser capabilities

## Development Notes

### Port Configuration
- **Web Application**: 8080 (nginx proxy to Tomcat)
- **LLM Gateway Proxy**: 8002 (dedicated freeciv-proxy for LLM agents, starts automatically)
- **LLM Gateway API**: 8003 (llm-gateway WebSocket API, starts automatically)
- **Game Servers**: 6000-6009 (Freeciv C servers)
- **Per-Game Proxies**: 7000-7009 (managed by publite2, one per game server)
- **AI Chat (dev)**: 8888 (web-llm development server)

### Build System Integration
- **Java Web App**: Maven build with Flyway database migrations
- **C Server**: Meson build system via prepare_freeciv.sh
- **JavaScript**: Bundled and minified during Maven build process
- **Web-LLM**: Separate Parcel build system for AI components

### Packet Handler Generation
The JavaScript packet handlers are **auto-generated** from the C server protocol definition and should NOT be manually edited:

**Source of Truth**: `freeciv/freeciv/common/networking/packets.def`

**Generated Files** (not tracked in git):
- `freeciv-web/src/main/webapp/javascript/packets.js` - Client-to-server packet constants
- `freeciv-web/src/main/webapp/javascript/packhand_gen.js` - Packet dispatcher table

**When to Regenerate**:
- After modifying `packets.def` (adding/removing/changing packet definitions)
- After pulling changes that modify the C server protocol
- During full project builds (happens automatically via `install.sh`)

**Manual Generation**:
```bash
# Generate just the packet handlers
./scripts/generate_js_hand/generate_js_hand.py \
  -f ./freeciv/freeciv \
  -o ./freeciv-web/src/main/webapp

# Or run the full sync script (recommended - also syncs help data, sprites, sounds)
./scripts/sync-js-hand.sh \
  -f ./freeciv/freeciv \
  -i ./freeciv/freeciv/install \
  -o ./freeciv-web/src/main/webapp \
  -d ./freeciv-web/src/main/webapp
```

**Build Integration**:
- Docker builds automatically run `sync-js-hand.sh` during the build process
- Local Maven builds call the generation scripts via `install.sh`
- The generated files are required for the JavaScript client to communicate with the C server

### Python Development Guidelines
For any Python development work (freeciv-proxy, publite2 components):
- **ALWAYS** use the python-dev-expert agent to plan Python changes before beginning development
- Use the agent for code review, architecture decisions, and best practices guidance
- Python components use Tornado framework (freeciv-proxy) and require careful async handling