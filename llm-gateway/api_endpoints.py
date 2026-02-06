#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
REST API endpoints for LLM Gateway
"""

import asyncio
import logging
import time
import traceback
from typing import Dict, Any, List, Literal, Optional
from urllib.parse import quote
import uuid
from fastapi import APIRouter, HTTPException, Query, Depends, Header, Request
from pydantic import BaseModel, Field, ValidationError

# Rate limiting imports
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    HAS_SLOWAPI = True
except ImportError:
    HAS_SLOWAPI = False

try:
    from .config import settings
    from .connection_manager import connection_manager
    from .utils.constants import (
        OBSERVER_URL_MAX_RETRY_ATTEMPTS,
        OBSERVER_URL_RETRY_DELAY_SECONDS,
        is_valid_civserver_port,
        ERROR_CODE_GAME_NOT_FOUND,
        ERROR_CODE_GAME_ALREADY_ENDED,
        ERROR_CODE_INTERNAL,
        MAP_SIZE_DIMENSIONS,
    )
except ImportError:
    from config import settings
    from connection_manager import connection_manager
    from utils.constants import (
        OBSERVER_URL_MAX_RETRY_ATTEMPTS,
        OBSERVER_URL_RETRY_DELAY_SECONDS,
        is_valid_civserver_port,
        ERROR_CODE_GAME_NOT_FOUND,
        ERROR_CODE_GAME_ALREADY_ENDED,
        ERROR_CODE_INTERNAL,
        MAP_SIZE_DIMENSIONS,
    )

# Gateway will be injected from main.py to avoid circular imports
gateway = None

def get_gateway():
    """Get the gateway instance (dependency injection)"""
    if gateway is None:
        raise HTTPException(status_code=500, detail="Gateway not initialized")
    return gateway

logger = logging.getLogger("llm-gateway")

# Create API router
router = APIRouter()

# Rate limiter setup
if HAS_SLOWAPI:
    try:
        from config import settings
        limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
    except:
        limiter = Limiter(key_func=get_remote_address)
else:
    limiter = None


def rate_limit(limit_string: str):
    """
    Rate limit decorator that gracefully handles missing slowapi.
    Returns no-op decorator if limiter is not available.
    """
    if limiter is not None:
        return limiter.limit(limit_string)
    else:
        # No-op decorator when rate limiting is not available
        def noop_decorator(func):
            return func
        return noop_decorator


# Pydantic models for request/response validation
class GameConfig(BaseModel):
    """Configuration for creating a new game

    Map configuration options for reducing fragmentation:
    - map_generator: FRACTAL creates large continents (recommended)
    - startpos: SINGLE ensures one player per continent
    - tinyisles: FALSE prevents 1x1 island fragments
    - landmass: Higher values = more connected land
    """
    ruleset: str = Field(default="classic", description="Game ruleset")
    map_size: Literal["tiny", "small", "medium", "large", "huge"] = Field(
        default="small", description="Map size (tiny=50x50, small=64x64, medium=80x80, large=96x96, huge=128x128)"
    )
    map_generator: Literal["FRACTAL", "ISLAND", "FAIR", "CONTINENTS"] = Field(
        default="FRACTAL", description="Map generation algorithm (FRACTAL=large continents, ISLAND=many islands, FAIR=identical islands per player)"
    )
    landmass: int = Field(default=85, ge=15, le=85, description="Percentage of map that is land (15-85)")
    startpos: Literal["DEFAULT", "SINGLE", "2or3", "ALL", "VARIABLE"] = Field(
        default="SINGLE", description="Player start position (SINGLE=one per continent recommended for 2-player)"
    )
    tinyisles: bool = Field(default=False, description="Allow 1x1 tile islands (False reduces fragmentation)")
    steepness: int = Field(default=25, ge=0, le=100, description="Amount of hills/mountains (0-100)")
    wetness: int = Field(default=30, ge=0, le=100, description="Amount of rivers/swamps (0-100)")
    max_players: int = Field(default=4, ge=2, le=8, description="Maximum players")
    ai_level: str = Field(default="easy", description="AI difficulty level")
    turn_timeout: Optional[int] = Field(default=120, ge=30, le=3600, description="Turn timeout in seconds")
    max_turns: int = Field(default=200, ge=10, le=5000, description="Maximum turns before game ends (winner determined by score)")

    class Config:
        schema_extra = {
            "example": {
                "ruleset": "classic",
                "map_size": "medium",
                "map_generator": "FRACTAL",
                "landmass": 85,
                "startpos": "SINGLE",
                "tinyisles": False,
                "steepness": 25,
                "wetness": 30,
                "max_players": 4,
                "ai_level": "easy",
                "turn_timeout": 120,
                "max_turns": 200
            }
        }


class FreeCivAction(BaseModel):
    """FreeCiv game action"""
    action_type: str = Field(description="Type of action")
    actor_id: int = Field(description="ID of the acting unit/city")
    target: Any = Field(description="Action target (coordinates, unit ID, etc.)")
    player_id: int = Field(description="Player ID performing the action")
    parameters: Optional[Dict[str, Any]] = Field(default={}, description="Additional parameters")

    class Config:
        schema_extra = {
            "example": {
                "action_type": "unit_move",
                "actor_id": 42,
                "target": {"x": 11, "y": 21},
                "player_id": 1,
                "parameters": {"validate": True}
            }
        }


class BatchActions(BaseModel):
    """Batch action submission"""
    actions: List[FreeCivAction] = Field(description="List of actions to execute")

    class Config:
        schema_extra = {
            "example": {
                "actions": [
                    {
                        "action_type": "unit_move",
                        "actor_id": 42,
                        "target": {"x": 11, "y": 21},
                        "player_id": 1
                    }
                ]
            }
        }


class StopGameRequest(BaseModel):
    """Request body for stopping a game (admin operation)"""
    reason: str = Field(
        default="admin_stop",
        description="Reason for stopping the game",
        example="admin_stop"
    )
    message: Optional[str] = Field(
        default=None,
        description="Optional human-readable message",
        example="Match stopped by administrator"
    )


class PlayerFinalStats(BaseModel):
    """Final statistics for a player at game end"""
    player_id: int = Field(description="Player ID (0-indexed)")
    agent_id: str = Field(description="Agent identifier")
    score: int = Field(default=0, description="Final score (cities*10 + units*2)")
    gold: int = Field(default=0, description="Gold reserves")
    cities: int = Field(default=0, description="Number of cities owned")
    units: int = Field(default=0, description="Number of units owned")


# Dependency for API key authentication
async def verify_api_key(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Verify API key from Authorization header"""
    if not settings.require_api_key:
        return {"valid": True, "agent_id": "anonymous"}

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    api_key = authorization[7:]  # Remove "Bearer " prefix

    # Simple API key validation (extend with proper validation)
    if len(api_key) < 10:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return {"valid": True, "agent_id": f"agent-{api_key[:8]}"}


# Game management endpoints
@router.post("/game/create")
async def create_game(
    config: GameConfig,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Create a new game session"""
    try:
        # Validate configuration
        if config.ruleset not in ["classic", "civ2civ3", "experimental"]:
            raise HTTPException(status_code=400, detail=f"Invalid ruleset: {config.ruleset}")

        if config.map_size not in ["tiny", "small", "medium", "large", "huge"]:
            raise HTTPException(status_code=400, detail=f"Invalid map size: {config.map_size}")

        # Create game via gateway
        if gateway is None:
            raise HTTPException(status_code=500, detail="Gateway not initialized")

        result = await gateway.create_game(config.dict())

        if not result["success"]:
            if "capacity" in result["error"].lower():
                raise HTTPException(status_code=503, detail=result["error"])
            else:
                raise HTTPException(status_code=500, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating game: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/game/{game_id}/state")
async def get_game_state(
    game_id: str,
    player_id: int = Query(description="Player ID for perspective"),
    format_type: str = Query(default="llm_optimized", alias="format", description="State format"),
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get current game state"""
    try:
        # Validate format
        if format_type not in ["full", "delta", "llm_optimized"]:
            raise HTTPException(status_code=400, detail=f"Invalid format: {format_type}")

        # Validate player_id
        if not (1 <= player_id <= 8):
            raise HTTPException(status_code=400, detail="Player ID must be between 1 and 8")

        # Get state via gateway
        if gateway is None:
            raise HTTPException(status_code=500, detail="Gateway not initialized")

        result = await gateway.get_game_state(game_id, player_id, format_type)

        if not result["success"]:
            if "not found" in result["error"].lower():
                raise HTTPException(status_code=404, detail=result["error"])
            elif "not authorized" in result["error"].lower():
                raise HTTPException(status_code=403, detail=result["error"])
            else:
                raise HTTPException(status_code=500, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting game state for {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/game/{game_id}/global-state")
async def get_global_game_state(
    game_id: str,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get authoritative global game state without fog of war.

    Returns all units, cities, and players from the game server's in-memory
    state. Used by match orchestrator for stats collection.
    """
    try:
        if gateway is None:
            raise HTTPException(status_code=500, detail="Gateway not initialized")

        result = await gateway.get_global_game_state(game_id)

        if not result["success"]:
            if "not found" in result["error"].lower():
                raise HTTPException(status_code=404, detail=result["error"])
            else:
                raise HTTPException(status_code=500, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting global game state for {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/game/{game_id}/action")
async def submit_action(
    game_id: str,
    action: FreeCivAction,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Submit a game action"""
    try:
        # Validate action type
        valid_actions = [
            "unit_move", "unit_attack", "unit_build_city", "unit_explore",
            "city_production", "city_build_unit", "city_build_improvement",
            "tech_research", "diplomacy_message", "end_turn"
        ]

        if action.action_type not in valid_actions:
            raise HTTPException(status_code=400, detail=f"Invalid action type: {action.action_type}")

        # Submit action via gateway
        if gateway is None:
            raise HTTPException(status_code=500, detail="Gateway not initialized")

        result = await gateway.submit_action(game_id, action.dict())

        if not result["success"]:
            if "not found" in result["error"].lower():
                raise HTTPException(status_code=404, detail=result["error"])
            elif "unit" in result["error"].lower() and "does not exist" in result["error"].lower():
                raise HTTPException(status_code=400, detail=result["error"])
            else:
                raise HTTPException(status_code=500, detail=result["error"])

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting action for {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/game/{game_id}/actions")
async def submit_actions_batch(
    game_id: str,
    batch: BatchActions,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Submit multiple actions in a batch"""
    try:
        if not settings.enable_batch_actions:
            raise HTTPException(status_code=403, detail="Batch actions are disabled")

        if len(batch.actions) > 10:  # Limit batch size
            raise HTTPException(status_code=400, detail="Too many actions in batch (max 10)")

        results = []

        for i, action in enumerate(batch.actions):
            try:
                result = await submit_action(game_id, action, auth)
                results.append({"index": i, "action_id": result.get("action_id"), "success": True})
            except HTTPException as e:
                results.append({
                    "index": i,
                    "success": False,
                    "error": e.detail,
                    "status_code": e.status_code
                })

        return {
            "success": True,
            "batch_size": len(batch.actions),
            "results": results
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting batch actions for {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Game information endpoints
@router.get("/game/{game_id}/info")
async def get_game_info(
    game_id: str,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """Get game information"""
    try:
        if gateway is None:
            raise HTTPException(status_code=500, detail="Gateway not initialized")

        if game_id not in gateway.game_sessions:
            raise HTTPException(status_code=404, detail=f"Game not found: {game_id}")

        game_session = gateway.game_sessions[game_id]

        return {
            "game_id": game_id,
            "config": game_session["config"],
            "status": game_session["status"],
            "created_at": game_session["created_at"],
            "players": game_session.get("players", {}),
            "spectators": len(await connection_manager.get_spectator_connections(game_id))
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting game info for {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/games")
@rate_limit(f"{settings.rate_limit_requests_per_minute}/minute")
async def list_games(
    request: Request,
    auth: Dict[str, Any] = Depends(verify_api_key),
    gateway_instance = Depends(get_gateway)
) -> Dict[str, Any]:
    """List all active games"""
    try:

        games = []
        for game_id, session in gateway_instance.game_sessions.items():
            games.append({
                "game_id": game_id,
                "status": session["status"],
                "created_at": session["created_at"],
                "player_count": len(session.get("players", {})),
                "config": session["config"]
            })

        return {
            "games": games,
            "total": len(games),
            "capacity": settings.max_concurrent_games
        }

    except Exception as e:
        logger.error(f"Error listing games: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Game lifecycle endpoints
async def _capture_final_state(
    gw,
    game_id: str,
    session: Dict[str, Any],
    request_body: StopGameRequest
) -> Dict[str, Any]:
    """
    Capture final game state before cleanup.

    Extracts player statistics from the cached last_state in the session.
    Falls back to basic player info if no state is cached.
    Also extracts winner information from session if game ended naturally.
    """
    # Calculate duration
    created_at = session.get("created_at", time.time())
    duration_seconds = time.time() - created_at

    # Get final turn from session
    final_turn = session.get("current_turn", 1)

    # Get winner information from session (set by game_ended handler in websocket_handlers.py)
    # This is populated when the game ends naturally (turn limit, conquest, space race, etc.)
    session_winners = session.get("winners", [])
    session_end_reason = session.get("end_reason", request_body.reason)

    # Get connected players from connection manager
    connected_players = await connection_manager.get_players_for_game(game_id)

    # Try to get player stats from last cached state
    last_state = session.get("last_state", {})
    players_data = []

    if last_state:
        # Extract collections from cached state
        cities = last_state.get("cities", {})
        units = last_state.get("units", {})
        players_raw = last_state.get("players", {})

        # Convert to list if dict (state_extractor returns dicts keyed by ID)
        cities_list = list(cities.values()) if isinstance(cities, dict) else (cities or [])
        units_list = list(units.values()) if isinstance(units, dict) else (units or [])
        players_list = list(players_raw.values()) if isinstance(players_raw, dict) else (players_raw or [])

        for player in connected_players:
            player_id = player["player_id"]
            agent_id = player["agent_id"]

            # Count cities and units for this player
            player_cities = [c for c in cities_list if c.get("owner") == player_id]
            player_units = [u for u in units_list if u.get("owner") == player_id]

            # Get player gold from players data
            player_info = next((p for p in players_list if p.get("id") == player_id), {})
            gold = player_info.get("gold", 0)

            # Simple score calculation (matches StateExtractor._calculate_player_score)
            score = len(player_cities) * 10 + len(player_units) * 2

            # Check if this player is a winner
            is_winner = player_id in session_winners

            players_data.append({
                "player_id": player_id,
                "agent_id": agent_id,
                "score": score,
                "gold": gold,
                "cities": len(player_cities),
                "units": len(player_units),
                "winner": is_winner
            })
    else:
        # Fallback: include connected players without stats
        for player in connected_players:
            player_id = player["player_id"]
            is_winner = player_id in session_winners
            players_data.append({
                "player_id": player_id,
                "agent_id": player["agent_id"],
                "score": 0,
                "gold": 0,
                "cities": 0,
                "units": 0,
                "winner": is_winner
            })

    # If no explicit winners from game_ended, determine winner by score
    # (This handles admin_stop case where game didn't end naturally)
    winners = session_winners
    if not winners and players_data:
        # Determine winner by highest score
        max_score = max(p["score"] for p in players_data)
        if max_score > 0:
            winners = [p["player_id"] for p in players_data if p["score"] == max_score]
            # Update winner flags
            for p in players_data:
                p["winner"] = p["player_id"] in winners

    return {
        "success": True,
        "final_turn": final_turn,
        "duration_seconds": round(duration_seconds, 2),
        "winners": winners,
        "players": players_data,
        "end_reason": session_end_reason,
        "end_message": request_body.message
    }


@router.post("/games/{game_id}/stop")
async def stop_game(
    game_id: str,
    request_body: StopGameRequest,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Stop a game session and return final state.

    Called by AgentClash gateway when an admin stops a match.
    Captures final game statistics before cleanup.

    Error codes:
    - E010: Game not found
    - E011: Game already ended
    - E500: Internal server error
    """
    try:
        gw = get_gateway()

        # Check if game exists
        if game_id not in gw.game_sessions:
            return {
                "type": "error",
                "data": {
                    "code": ERROR_CODE_GAME_NOT_FOUND,
                    "message": f"Game not found: {game_id}"
                }
            }

        session = gw.game_sessions[game_id]

        # Check if game is already ended
        if session.get("status") == "ended":
            return {
                "type": "error",
                "data": {
                    "code": ERROR_CODE_GAME_ALREADY_ENDED,
                    "message": f"Game {game_id} has already ended"
                }
            }

        # Capture final state BEFORE cleanup
        final_state = await _capture_final_state(gw, game_id, session, request_body)

        # End the game (notifies spectators, cleans up sessions/agents/connections)
        await gw.end_game(game_id, {
            "reason": request_body.reason,
            "message": request_body.message,
            "final_state": final_state
        })

        logger.info(f"Game {game_id} stopped via API: reason={request_body.reason}")

        return {
            "type": "game_ended",
            "game_id": game_id,
            "data": final_state
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping game {game_id}: {e}")
        return {
            "type": "error",
            "data": {
                "code": ERROR_CODE_INTERNAL,
                "message": f"Internal error stopping game: {str(e)}"
            }
        }


# Spectator endpoints
@router.get("/games/{game_id}/spectate")
async def get_spectator_url(
    game_id: str,
    request: Request
) -> Dict[str, Any]:
    """Get spectator URL for viewing a game"""
    try:
        gw = get_gateway()

        # Check if game exists
        if game_id not in gw.game_sessions:
            raise HTTPException(status_code=404, detail="Game not found")

        game_session = gw.game_sessions[game_id]

        # Get the game port - MUST be set (no default to 6000)
        # LLM games always use multiplayer ports (6001-6009), never 6000
        game_port = game_session.get("port")

        if not is_valid_civserver_port(game_port):
            # This shouldn't happen - indicates authentication bug or timing issue
            logger.warning(f"Game {game_id} has invalid port {game_port}. Status: {game_session.get('status')}")
            raise HTTPException(
                status_code=409,  # Conflict
                detail="Game port not assigned. Agents may still be connecting/authenticating. Wait a few seconds and try again."
            )

        # Generate spectator URL using configured base URL
        base_url = settings.freeciv_web_base_url.rstrip("/")
        spectator_url = f"{base_url}/webclient/spectator.jsp?game_id={game_id}&port={game_port}&mode=full"
        logger.info(f"Generated spectator URL for game {game_id}: port={game_port}")

        return {
            "success": True,
            "game_id": game_id,
            "spectator_url": spectator_url,
            "websocket_url": f"ws://localhost:{game_port}/ws",
            "game_info": {
                "port": game_port,
                "status": game_session.get("status", "unknown"),
                "players": len(game_session.get("agents", {})),
                "created_at": game_session.get("created_at"),
                "turn": game_session.get("turn", 0)
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting spectator URL for game {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/games/{game_id}/observer-urls")
@rate_limit(f"{settings.rate_limit_requests_per_minute}/minute")
async def get_observer_urls(
    game_id: str,
    request: Request
) -> Dict[str, Any]:
    """
    Get observer URLs for embedding game views in agent-clash-client.

    Returns 3 observer URLs:
    - global: Bird's eye view with strategic camera preset
    - player1: AI*1's perspective with fog-of-war and cinematic camera
    - player2: AI*2's perspective with fog-of-war and cinematic camera

    All URLs include embed=1 and autojoin=1 for seamless iframe embedding.
    """
    try:
        # Poll for game info with timeout to handle race condition where
        # agent-clash requests observer URLs before auth_success is processed.
        max_attempts = OBSERVER_URL_MAX_RETRY_ATTEMPTS
        attempt_delay = OBSERVER_URL_RETRY_DELAY_SECONDS
        max_wait_seconds = max_attempts * attempt_delay

        game_info = None
        game_port = None

        for attempt in range(max_attempts):
            game_info = await connection_manager.get_game_info(game_id)

            if game_info is not None:
                game_port = game_info.get("civserver_port")
                if is_valid_civserver_port(game_port):
                    if attempt > 0:
                        logger.info(
                            f"Observer URLs: Found game {game_id} after {attempt + 1} attempts "
                            f"({attempt * attempt_delay:.1f}s)"
                        )
                    else:
                        logger.debug(f"Observer URLs: Game {game_id} immediately available")
                    break  # Got valid game info

            if attempt < max_attempts - 1:
                logger.debug(
                    f"Observer URLs: Waiting for game {game_id} auth "
                    f"(attempt {attempt + 1}/{max_attempts})"
                )
                await asyncio.sleep(attempt_delay)

        # After all attempts, raise appropriate error
        if game_info is None:
            raise HTTPException(
                status_code=404,
                detail=f"Game not found after waiting {max_wait_seconds:.0f}s. "
                       "Ensure agent has connected with this game_id."
            )

        if not is_valid_civserver_port(game_port):
            logger.warning(
                f"Game {game_id} has invalid port {game_port} after waiting {max_wait_seconds:.0f}s. "
                f"Agent may have disconnected."
            )
            raise HTTPException(
                status_code=409,
                detail=f"Game port not assigned after waiting {max_wait_seconds:.0f}s. "
                       "Agent may have disconnected or authentication failed."
            )

        # Build observer URLs using configured base URL
        base_url = settings.freeciv_web_base_url.rstrip("/")
        webclient_path = f"{base_url}/webclient/"

        # Get actual player names from connected agents
        # The webclient expects player names (agent_id) for observe_player/follow params
        players = await connection_manager.get_players_for_game(game_id)

        # Log player discovery for debugging observer URL issues
        if len(players) < 2:
            logger.warning(
                f"Observer URLs: Only found {len(players)} player(s) for game {game_id}. "
                f"Players: {players}. Expected 2 players for proper observer views."
            )
        else:
            logger.info(
                f"Observer URLs: Found {len(players)} players for game {game_id}: "
                f"{[p['agent_id'] for p in players]}"
            )

        player1_name = quote(players[0]["agent_id"], safe="") if len(players) > 0 else "0"
        player2_name = quote(players[1]["agent_id"], safe="") if len(players) > 1 else "1"

        logger.debug(
            f"Observer URLs for game {game_id}: player1={player1_name}, player2={player2_name}"
        )

        # Generate unique viewer names to prevent WebSocket conflicts
        # when multiple viewers connect to the same game
        # URL-encode for consistency (even though these names are alphanumeric)
        unique_suffix = uuid.uuid4().hex[:8]
        global_viewer_name = quote(f"global_view_{unique_suffix}", safe="")
        player1_viewer_name = quote(f"player1_view_{unique_suffix}", safe="")
        player2_viewer_name = quote(f"player2_view_{unique_suffix}", safe="")

        # Stagger connection delays to prevent race conditions (production stability fix)
        #
        # Race condition: When 3 observer iframes load simultaneously, they each:
        # 1. Establish a WebSocket connection to freeciv-proxy
        # 2. Send authentication/join packets to civserver
        # 3. Register as observers and receive initial game state
        #
        # In production (with network latency, load balancers), simultaneous connections
        # can overwhelm the civserver's connection handling, causing:
        # - Connection rejections (server busy)
        # - Observer registration failures
        # - Incomplete game state synchronization
        #
        # Connection delays removed - Option B (lazy loading in agent-clash-client) handles
        # loading iframes one at a time when user selects them, eliminating the need for stagger.
        observer_urls = {
            "global": (
                f"{webclient_path}?action=observe&civserverport={game_port}"
                f"&embed=1&autojoin=1&name={global_viewer_name}&camera=strategic"
            ),
            "player1": (
                f"{webclient_path}?action=observe&civserverport={game_port}"
                f"&observe_player={player1_name}&follow={player1_name}"
                f"&embed=1&autojoin=1&name={player1_viewer_name}&camera=cinematic"
            ),
            "player2": (
                f"{webclient_path}?action=observe&civserverport={game_port}"
                f"&observe_player={player2_name}&follow={player2_name}"
                f"&embed=1&autojoin=1&name={player2_viewer_name}&camera=cinematic"
            )
        }

        logger.info(f"Generated observer URLs for game {game_id}: port={game_port}")

        # Include YouTube URLs if streaming is active
        youtube_urls = None
        local_stream_urls = None

        if gateway and game_id in gateway.game_sessions:
            session = gateway.game_sessions[game_id]
            youtube_urls = session.get("youtube_urls")

        # Provide local MediaMTX URLs only when:
        # 1. YouTube streaming is not active (no youtube_urls)
        # 2. Streaming is enabled (stream_manager exists)
        # 3. Local stream base URL is configured
        # This ensures observer mode works even when STREAMING_MODE=disabled
        if (youtube_urls is None and
                gateway and gateway.stream_manager and
                settings.local_stream_base_url):
            base = settings.local_stream_base_url.rstrip("/")
            # WebRTC is on port 8891 (one port higher than HLS 8890)
            webrtc_base = base.replace(":8890", ":8891")
            local_stream_urls = {
                "global": f"{base}/stream/global/index.m3u8",
                "player1": f"{base}/stream/player1/index.m3u8",
                "player2": f"{base}/stream/player2/index.m3u8",
                "webrtc": {
                    "global": f"{webrtc_base}/stream/global",
                    "player1": f"{webrtc_base}/stream/player1",
                    "player2": f"{webrtc_base}/stream/player2",
                },
                "note": "Local streams via MediaMTX (STREAMING_MODE=local)"
            }

        return {
            "game_id": game_id,
            "civserver_port": game_port,
            "observer_urls": observer_urls,
            "youtube_urls": youtube_urls,
            "local_stream_urls": local_stream_urls
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting observer URLs for game {game_id}: {e}\n"
            f"Traceback: {traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# Streaming endpoints
@router.get("/games/{game_id}/stream/status")
async def get_stream_status(
    game_id: str,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Get the status of a YouTube stream for a game.

    Returns stream information if active, or 404 if no stream exists.
    """
    try:
        gw = get_gateway()

        # Check if StreamManager exists
        if not hasattr(gw, 'stream_manager') or gw.stream_manager is None:
            raise HTTPException(
                status_code=501,
                detail="Streaming not enabled on this gateway instance"
            )

        status = await gw.stream_manager.get_stream_status(game_id)

        if status is None:
            raise HTTPException(
                status_code=404,
                detail=f"No active stream for game {game_id}"
            )

        return {
            "success": True,
            **status
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stream status for {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/games/{game_id}/stream/stop")
async def stop_stream(
    game_id: str,
    auth: Dict[str, Any] = Depends(verify_api_key)
) -> Dict[str, Any]:
    """
    Manually stop streaming a game.

    Stops the K8s Job and transitions the YouTube broadcast to complete.
    The VOD will remain available at the same YouTube URL.
    """
    try:
        gw = get_gateway()

        # Check if StreamManager exists
        if not hasattr(gw, 'stream_manager') or gw.stream_manager is None:
            raise HTTPException(
                status_code=501,
                detail="Streaming not enabled on this gateway instance"
            )

        # Check if stream exists before stopping
        status = await gw.stream_manager.get_stream_status(game_id)
        if status is None:
            raise HTTPException(
                status_code=404,
                detail=f"No active stream for game {game_id}"
            )

        await gw.stream_manager.stop_stream(game_id)

        logger.info(f"Stream manually stopped for game {game_id}")

        return {
            "success": True,
            "game_id": game_id,
            "message": "Stream stopped successfully",
            "youtube_url": status.get("youtube_url")
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping stream for {game_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Metrics and monitoring endpoints
@router.get("/metrics")
async def get_metrics(auth: Dict[str, Any] = Depends(verify_api_key)) -> Dict[str, Any]:
    """Get gateway metrics"""
    try:
        if not settings.enable_metrics:
            raise HTTPException(status_code=403, detail="Metrics are disabled")

        if gateway is None:
            raise HTTPException(status_code=500, detail="Gateway not initialized")

        health_status = gateway.get_health_status()

        return {
            "timestamp": time.time(),
            "metrics": {
                "active_games": health_status["active_games"],
                "active_agents": health_status["active_agents"],
                "proxy_connections": health_status["proxy_connections"],
                "uptime": health_status["uptime"],
                "connection_stats": health_status["connection_stats"]
            },
            "status": health_status["status"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Debug endpoints
@router.get("/debug/connections")
async def debug_connections() -> Dict[str, Any]:
    """
    Debug endpoint to inspect connection manager state.

    Returns detailed information about all connections for troubleshooting
    why observer-urls can't find game_id.
    """
    connections_data = []
    for conn_id, conn_info in connection_manager.connections.items():
        connections_data.append({
            "connection_id": conn_id,
            "type": conn_info.connection_type,
            "identifier": conn_info.identifier,
            "game_id": conn_info.game_id,
            "player_id": conn_info.player_id,
            "civserver_port": conn_info.civserver_port,
            "authenticated": conn_info.authenticated,
            "session_id": conn_info.session_id,
            "connected_at": conn_info.connected_at,
            "last_seen": conn_info.last_seen,
        })

    return {
        "total_connections": len(connection_manager.connections),
        "agent_connections_by_id": {
            agent_id: list(conn_ids)
            for agent_id, conn_ids in connection_manager.agent_connections.items()
        },
        "spectator_connections_by_game": {
            game_id: list(conn_ids)
            for game_id, conn_ids in connection_manager.spectator_connections.items()
        },
        "disconnected_sessions": list(connection_manager.disconnected_sessions.keys()),
        "connections": connections_data,
    }


# Helper functions
def authenticate_api_key(api_key: str) -> Dict[str, Any]:
    """Authenticate API key (extend with proper implementation)"""
    # Simple validation for now
    if len(api_key) >= 10:
        return {"valid": True, "agent_id": f"agent-{api_key[:8]}"}
    else:
        return {"valid": False, "error": "Invalid API key"}


def check_rate_limit(agent_id: str) -> Dict[str, Any]:
    """Check rate limit for agent (extend with proper implementation)"""
    # Placeholder implementation
    return {"allowed": True}


