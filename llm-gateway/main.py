#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM API Gateway Server for FreeCiv3D Integration
Main FastAPI application with WebSocket and REST endpoints
"""

import asyncio
import json
import logging
import os
import random
import sys
import time
import uuid
from typing import TYPE_CHECKING, Dict, Any, Optional, Union
import websockets
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# Rate limiting imports
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    HAS_SLOWAPI = True
except ImportError:
    HAS_SLOWAPI = False

if TYPE_CHECKING:
    from .config import settings, get_cors_origins, get_freeciv_proxy_url, validate_settings
    from .connection_manager import connection_manager
    from .request_manager import request_manager
    from .connection_state_manager import connection_state_manager, ConnectionStatus
    from .security.token_manager import secure_token_manager
    from .utils.safe_access import get_agent_game_id
    from .utils.constants import *
    from .validation import sanitize_for_logging
    from .stream_manager import StreamManager, LocalStreamManager
    from .tracing import init_tracing, get_tracer
    from .structured_logging import configure_structured_logging
else:
    from config import settings, get_cors_origins, get_freeciv_proxy_url, validate_settings
    from connection_manager import connection_manager
    from request_manager import request_manager
    from connection_state_manager import connection_state_manager, ConnectionStatus
    from security.token_manager import secure_token_manager
    from utils.safe_access import get_agent_game_id
    from utils.constants import *
    from validation import sanitize_for_logging
    from stream_manager import StreamManager, LocalStreamManager
    from tracing import init_tracing, get_tracer
    from structured_logging import configure_structured_logging


# Streaming mode configuration
# "k8s" = use K8s StreamManager (production)
# "local" = use LocalStreamManager with Docker (development)
# "auto" = try K8s first, fall back to Docker
# "disabled" = no streaming
STREAMING_MODE = os.environ.get("STREAMING_MODE", "auto")


def create_stream_manager() -> Optional[Union[StreamManager, LocalStreamManager]]:
    """
    Create appropriate stream manager based on environment.

    Auto-detects K8s vs Docker environment and returns the appropriate manager.
    Returns None if streaming is disabled or no container runtime is available.
    """
    # Note: We use print() here because logging may not be configured yet at module load time
    # These messages will still appear in container logs via stdout

    if STREAMING_MODE == "disabled":
        print(f"[StreamManager] Streaming disabled via STREAMING_MODE=disabled")
        return None

    if STREAMING_MODE == "local":
        print(f"[StreamManager] Using LocalStreamManager (forced via STREAMING_MODE=local)")
        return LocalStreamManager()

    if STREAMING_MODE == "k8s":
        print(f"[StreamManager] Using StreamManager (forced via STREAMING_MODE=k8s)")
        return StreamManager()

    # Auto-detect: try K8s first, fall back to Docker
    try:
        import kubernetes
        try:
            kubernetes.config.load_incluster_config()
            print(f"[StreamManager] Detected in-cluster K8s, using StreamManager")
            return StreamManager()
        except kubernetes.config.ConfigException as e:
            print(f"[StreamManager] K8s in-cluster config not available: {e}")

        try:
            kubernetes.config.load_kube_config()
            print(f"[StreamManager] Detected kubeconfig, using StreamManager")
            return StreamManager()
        except kubernetes.config.ConfigException as e:
            print(f"[StreamManager] K8s kubeconfig not available: {e}")
    except ImportError:
        print(f"[StreamManager] kubernetes package not installed, skipping K8s detection")

    # No K8s available, check if Docker is available via SDK
    try:
        import docker
        client = docker.from_env()
        client.ping()  # Verify connection to Docker daemon
        version = client.version().get('Version', 'unknown')
        print(f"[StreamManager] Docker SDK connected (version {version}), using LocalStreamManager")
        return LocalStreamManager()
    except Exception as e:
        print(f"[StreamManager] Docker SDK not available: {e}")

    # No container runtime available
    print(f"[StreamManager] No container runtime available, streaming disabled")
    return None


# Configure logging to output to BOTH stdout (for GCloud) and file (for local debugging)
# GCloud Logging captures stdout from containers
os.makedirs("logs", exist_ok=True)

# Check if structured JSON logging with tracing should be enabled
ENABLE_CLOUD_TRACE = os.environ.get("ENABLE_CLOUD_TRACE", "false").lower() == "true"

if ENABLE_CLOUD_TRACE:
    # Use structured JSON logging for GCP Cloud Logging integration
    logger = configure_structured_logging(
        "llm-gateway",
        log_level=settings.log_level,
        use_json=True
    )
    logger.info("Structured JSON logging enabled for Cloud Logging integration")
else:
    # Use standard logging for local development
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format=settings.log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),  # GCloud captures stdout (not stderr)
            logging.FileHandler("logs/gateway.log"),  # File for local debugging
        ]
    )
    logger = logging.getLogger("llm-gateway")

# Create FastAPI app
app = FastAPI(
    title="FreeCiv LLM Gateway",
    description="API Gateway for LLM agent integration with FreeCiv3D",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting setup
if HAS_SLOWAPI:
    # Use Redis for distributed rate limiting if available, otherwise in-memory
    # TODO: Add test for Redis failure scenarios:
    #   - What happens when Redis connection fails during startup?
    #   - How does rate limiting degrade when Redis becomes unavailable?
    #   - Does the in-memory fallback work correctly under load?
    #   - Are rate limit counters properly synchronized after Redis reconnection?
    try:
        import redis
        redis_client = redis.from_url(settings.redis_url, db=settings.redis_db)
        limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
        logger.info("Rate limiting enabled with Redis backend")
    except Exception as e:
        logger.warning(f"Redis not available for rate limiting: {e}")
        limiter = Limiter(key_func=get_remote_address)
        logger.info("Rate limiting enabled with in-memory backend")

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
else:
    logger.warning("slowapi not installed - rate limiting disabled")
    limiter = None


class LLMGateway:
    """Simplified gateway class - pure pass-through between Game Arena and FreeCiv3D"""

    def __init__(self):
        # Minimal state - just track active agents for connection management
        self.active_agents: Dict[str, Dict[str, Any]] = {}
        # Keep game_sessions for health monitoring and API compatibility
        # Referenced by health endpoint and session status queries
        self.game_sessions: Dict[str, Dict[str, Any]] = {}
        # Lock for thread-safe access to game_sessions dict from multiple handlers
        # Issue #1 (PR Review): Prevents race conditions when concurrent agents update sessions
        self._sessions_lock = asyncio.Lock()
        self._running = False

        # Streaming manager (optional - graceful degradation if unavailable)
        # Uses factory function to auto-detect K8s vs Docker environment
        self.stream_manager = None
        if not settings.streaming_enabled:
            logger.info("Streaming disabled via GATEWAY_STREAMING_ENABLED=false")
        elif STREAMING_MODE == "disabled":
            logger.info("Streaming disabled via STREAMING_MODE=disabled")
        else:
            try:
                self.stream_manager = create_stream_manager()
                if self.stream_manager:
                    manager_type = type(self.stream_manager).__name__
                    logger.info(f"{manager_type} initialized (mode={STREAMING_MODE})")
                else:
                    logger.info(f"Streaming disabled - no container runtime available (mode={STREAMING_MODE})")
            except Exception as e:
                logger.warning(f"StreamManager initialization failed (streaming disabled): {e}")

        # Note: Complex state management removed - gateway acts as pure pass-through
        # The proxy's LLM handler manages game state, authentication, and actions
        # game_sessions is kept for health monitoring and basic session tracking

    async def start(self):
        """Start the gateway"""
        self._running = True

        # Start all managers
        await connection_manager.start()
        await request_manager.start()
        await connection_state_manager.start()
        await secure_token_manager.start()

        logger.info("LLM Gateway started")

    async def stop(self):
        """Stop the gateway"""
        self._running = False

        # Stop all managers
        await connection_manager.stop()
        await request_manager.stop()
        await connection_state_manager.stop()
        await secure_token_manager.stop()

        logger.info("LLM Gateway stopped")

    async def register_agent(self, agent_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Register agent connection - actual auth handled by proxy"""
        try:
            # Just track that the agent connected
            self.active_agents[agent_id] = {
                "connected_at": time.time(),
                "session_id": str(uuid.uuid4())
            }

            logger.info(f"Agent {agent_id} registered for pass-through")

            # Return success - proxy will handle actual authentication
            return {
                "success": True,
                "agent_id": agent_id,
                "session_id": self.active_agents[agent_id]["session_id"],
                "player_id": 1  # Proxy will assign actual player_id
            }

        except Exception as e:
            logger.error(f"Error registering agent {sanitize_for_logging(agent_id)}: {sanitize_for_logging(e)}")
            return {
                "success": False,
                "error": f"Registration failed: {str(e)}"
            }

    async def route_message(self, source: str, target: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Route message between agent-clash and FreeCiv"""
        try:
            if target == "freeciv":
                return await self._route_to_freeciv(message)
            elif target == "agent_clash":
                return await self._route_to_agent_clash(message)
            else:
                return {
                    "success": False,
                    "error": f"Unknown target: {target}"
                }

        except Exception as e:
            logger.error(f"Error routing message from {source} to {target}: {e}")
            return {
                "success": False,
                "error": f"Message routing failed: {str(e)}"
            }

    async def connect_to_freeciv_proxy(self, game_id: str) -> Dict[str, Any]:
        """Establish connection to FreeCiv proxy for a game"""
        try:
            # Check if already connected using connection state manager
            existing_connection = await connection_state_manager.get_connection(game_id)
            if existing_connection:
                return {"success": True, "message": "Already connected"}

            proxy_url = get_freeciv_proxy_url()

            # Connect to FreeCiv proxy with timeout parameters to detect dead connections
            # open_timeout addresses E999 "timed out during opening handshake" errors
            websocket = await websockets.connect(
                proxy_url,
                open_timeout=WEBSOCKET_OPEN_TIMEOUT,  # 30s for handshake under load
                ping_interval=WEBSOCKET_PING_INTERVAL,
                ping_timeout=WEBSOCKET_PING_TIMEOUT,
                close_timeout=WEBSOCKET_CLOSE_TIMEOUT
            )

            # Add to connection state manager (thread-safe)
            success = await connection_state_manager.add_connection(game_id, websocket)
            if not success:
                await websocket.close()
                return {
                    "success": False,
                    "error": "Connection capacity exceeded"
                }

            logger.info(f"Connected to FreeCiv proxy for game {game_id}")

            # Initialize the game after connection
            init_result = await self._initialize_freeciv_game(game_id, websocket)
            if not init_result["success"]:
                logger.warning(f"Failed to initialize FreeCiv game: {init_result.get('error')}")
            else:
                # Start background listener for proxy messages
                asyncio.create_task(self._listen_to_proxy_messages(game_id))
                logger.info(f"Started proxy message listener for game {game_id}")

            return {
                "success": True,
                "game_id": game_id,
                "proxy_url": proxy_url
            }

        except Exception as e:
            logger.error(f"Failed to connect to FreeCiv proxy for game {sanitize_for_logging(game_id)}: {sanitize_for_logging(e)}")
            await connection_state_manager.mark_connection_failed(game_id, str(e))
            return {
                "success": False,
                "error": f"Connection failed: {str(e)}"
            }

    async def forward_to_proxy(self, game_id: str, message: Dict[str, Any]) -> bool:
        """Forward message to FreeCiv proxy with retry logic"""
        try:
            # Atomically check if we have a healthy connection (prevents race conditions)
            proxy_ws = await connection_state_manager.get_healthy_connection(game_id)
            if not proxy_ws:
                # No healthy connection, try to establish one
                success = await self._ensure_proxy_connection(game_id)
                if not success:
                    logger.error(f"Failed to establish proxy connection for game {sanitize_for_logging(game_id)}")
                    return False
                # Retrieve the newly established connection atomically only if establishment succeeded
                proxy_ws = await connection_state_manager.get_healthy_connection(game_id)
                if not proxy_ws:
                    logger.error(f"No proxy connection available after establishment for game {sanitize_for_logging(game_id)}")
                    return False

            await proxy_ws.send(json.dumps(message))
            logger.debug(f"Message forwarded to proxy for game {game_id}")
            return True

        except Exception as e:
            logger.error(f"Error forwarding message to proxy for game {sanitize_for_logging(game_id)}: {sanitize_for_logging(e)}")
            # Mark connection as failed using connection state manager
            await connection_state_manager.mark_connection_failed(game_id, str(e))
            return False

    async def _ensure_proxy_connection(self, game_id: str) -> bool:
        """Ensure proxy connection exists with retry logic"""
        # Check if connection exists and get its info from state manager
        connections = await connection_state_manager.get_all_connections()
        connection_info = connections.get(game_id)

        # Check if connection is in cooldown period (recently failed)
        if connection_info and connection_info.status == ConnectionStatus.FAILED:
            if connection_info.last_error and time.time() - connection_info.last_used < COOLDOWN_PERIOD:
                logger.debug(f"Connection for game {game_id} in cooldown period")
                return False

        retry_count = connection_info.retry_count if connection_info else 0

        for attempt in range(settings.max_retry_attempts):
            try:
                logger.info(f"Attempting to connect to proxy for game {game_id} (attempt {attempt + 1})")

                success = await self.connect_to_freeciv_proxy(game_id)
                if success.get("success", False):
                    # Connection successful - state manager handles tracking
                    logger.info(f"Successfully connected to proxy for game {game_id}")
                    return True

            except Exception as e:
                logger.warning(f"Connection attempt {attempt + 1} failed for game {sanitize_for_logging(game_id)}: {sanitize_for_logging(e)}")

            # Calculate exponential backoff delay
            if attempt < settings.max_retry_attempts - 1:  # Don't wait after last attempt
                delay = min(
                    settings.initial_retry_delay * (settings.retry_backoff_multiplier ** attempt),
                    settings.max_retry_delay
                )
                # Add jitter to prevent thundering herd
                jitter = random.uniform(0.1, 0.3) * delay
                total_delay = delay + jitter

                logger.info(f"Waiting {total_delay:.2f}s before retry for game {game_id}")
                await asyncio.sleep(total_delay)

        # All attempts failed
        await self._handle_connection_failure(game_id)
        return False

    async def _is_connection_healthy(self, game_id: str) -> bool:
        """
        Check if connection is healthy

        DEPRECATED: Use connection_state_manager.is_connection_healthy() instead
        This method is kept for backward compatibility only.
        """
        # Delegate to connection state manager (thread-safe implementation)
        return await connection_state_manager.is_connection_healthy(game_id)

    async def _initialize_freeciv_game(self, game_id: str, websocket) -> Dict[str, Any]:
        """Initialize a FreeCiv game by sending necessary protocol messages"""
        # TODO: Add test for connection loss during authentication:
        #   - Proxy closes connection between sending auth and receiving response
        #   - Verify timeout handling works correctly (currently 5.0s)
        #   - Ensure connection cleanup happens on auth failure
        #   - Test partial authentication scenarios (sent but not confirmed)
        try:
            # Get API token for LLM authentication
            api_token = os.getenv("LLM_API_TOKENS", "test-token-fc3d-001").split(",")[0]

            # Send LLM authentication message to the LLM handler
            # Get default civserver port from environment variable (configurable via docker-compose.yml)
            default_port = int(os.getenv("DEFAULT_CIVSERVER_PORT", "6001"))

            # Get game config from session (contains max_turns, etc.)
            game_config = self.game_sessions.get(game_id, {}).get("config", {})

            auth_msg = {
                "type": "llm_connect",
                "agent_id": f"llm_player_{game_id[:8]}",
                "api_token": api_token,
                "port": default_port,
                "game_config": game_config
            }

            await websocket.send(json.dumps(auth_msg))
            logger.info(f"Sent LLM authentication message for game {game_id}")

            # Wait for response (with timeout)
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            response_data = json.loads(response)

            # Handle LLM handler authentication response
            if response_data.get("type") == "auth_success":
                # Store session info in game sessions
                if game_id not in self.game_sessions:
                    self.game_sessions[game_id] = {}

                self.game_sessions[game_id]["player_id"] = response_data.get("player_id")
                self.game_sessions[game_id]["session_id"] = response_data.get("session_id")
                self.game_sessions[game_id]["agent_id"] = response_data.get("agent_id")
                civserver_port = response_data.get("civserver_port", 6000)
                self.game_sessions[game_id]["port"] = civserver_port

                logger.info(
                    f"Successfully authenticated LLM agent for game {game_id}: "
                    f"player_id={response_data.get('player_id')}, port={civserver_port}"
                )

                # Warn if port is invalid - LLM games should use 6001-6009 (multiplayer ports)
                if not is_valid_civserver_port(civserver_port):
                    logger.warning(f"⚠️ Game {game_id} assigned invalid port {civserver_port} - expected multiplayer port (6001-6009)")
                return {"success": True, "player_id": response_data.get("player_id")}
            else:
                error_msg = response_data.get("message", "Authentication failed")
                logger.error(f"LLM authentication failed for game {game_id}: {error_msg}")
                return {"success": False, "error": error_msg}

        except asyncio.TimeoutError:
            return {"success": False, "error": "Game initialization timeout"}
        except Exception as e:
            logger.error(f"Error initializing FreeCiv game: {e}")
            return {"success": False, "error": str(e)}

    async def _listen_to_proxy_messages(self, game_id: str):
        """Background task to listen for messages from FreeCiv proxy"""
        try:
            proxy_ws = await connection_state_manager.get_connection(game_id)
            if not proxy_ws:
                logger.warning(f"No proxy connection found for game {game_id}")
                return

            logger.info(f"Starting proxy message listener for game {game_id}")

            while proxy_ws.close_code is None:
                try:
                    response = await asyncio.wait_for(proxy_ws.recv(), timeout=30.0)
                    messages = json.loads(response)

                    # Handle array format from FreeCiv proxy
                    if isinstance(messages, list):
                        for msg in messages:
                            await self._handle_freeciv_message(game_id, msg)
                    else:
                        await self._handle_freeciv_message(game_id, messages)

                except asyncio.TimeoutError:
                    # Timeout is normal, just continue listening
                    continue
                except Exception as e:
                    logger.error(f"Error receiving proxy message for {game_id}: {e}")
                    break

            logger.info(f"Proxy message listener stopped for game {game_id}")

        except Exception as e:
            logger.error(f"Proxy listener error for {game_id}: {e}")

    async def _handle_freeciv_message(self, game_id: str, message: Dict[str, Any]):
        """Process messages from LLM handler and forward to appropriate recipients"""
        try:
            msg_type = message.get("type")

            # Handle LLM handler message types
            if msg_type == "state_response":
                # State response from LLM handler
                logger.debug(f"Received state response for {game_id}: format={message.get('format')}")

                # Resolve any pending state query requests
                # The request manager expects a response format
                response_data = {
                    "success": True,
                    "data": message.get("data", {}),
                    "format": message.get("format", "llm_optimized"),
                    "cached": message.get("cached", False),
                    "timestamp": message.get("timestamp", time.time())
                }

                # Check if this is a response to a pending request
                correlation_id = message.get("correlation_id")
                if correlation_id:
                    await request_manager.resolve_request(correlation_id, response_data)

                # Store the state for future reference
                if game_id in self.game_sessions:
                    self.game_sessions[game_id]["last_state"] = message.get("data", {})
                    self.game_sessions[game_id]["last_state_time"] = message.get("timestamp", time.time())

                # Forward state to spectators if it contains map/game data
                state_data = message.get("data", {})
                if state_data:
                    await connection_manager.broadcast_to_spectators(game_id, {
                        "type": "state_update",
                        "game_id": game_id,
                        "turn": state_data.get("turn", 1),
                        "players": state_data.get("players", {}),
                        "units": state_data.get("units", []),
                        "cities": state_data.get("cities", []),
                        "visible_tiles": state_data.get("visible_tiles", []),
                        "timestamp": time.time()
                    })

            elif msg_type == "global_state_response":
                # Global state response from proxy
                logger.debug(f"Received global state response for {game_id}")

                response_data = {
                    "type": "global_state_response",
                    "success": True,
                    "data": message.get("data", {}),
                    "timestamp": message.get("timestamp", time.time())
                }

                correlation_id = message.get("correlation_id")
                if correlation_id:
                    await request_manager.resolve_request(correlation_id, response_data)

            elif msg_type == "action_accepted":
                # Action successfully executed
                logger.info(f"Action accepted for {game_id}: {message.get('action')}")

                # Notify spectators of successful action
                await connection_manager.broadcast_to_spectators(game_id, {
                    "type": "action_executed",
                    "game_id": game_id,
                    "action": message.get("action"),
                    "timestamp": message.get("timestamp", time.time())
                })

            elif msg_type == "action_rejected":
                # Action was rejected
                logger.warning(f"Action rejected for {game_id}: {message.get('error_message')}")
                # Note: action_rejected is automatically forwarded to agent via WebSocket pass-through

            elif msg_type == "error":
                # Error from LLM handler
                logger.error(f"LLM handler error for {game_id}: {message.get('message')}")

            elif msg_type == "welcome":
                # Initial welcome message, can be ignored
                logger.debug(f"Welcome message received for {game_id}")

            else:
                # Unknown message type or FreeCiv protocol message
                # Check if it's a FreeCiv protocol message (has pid field)
                msg_pid = message.get("pid")
                if msg_pid:
                    # Forward ALL FreeCiv protocol packets to spectators
                    # Spectator will use packet_handlers[] table to route them (just like normal clients)
                    # This matches how multiplayer observer mode works - no packet filtering
                    await connection_manager.broadcast_to_spectators(game_id, {
                        "type": "freeciv_update",
                        "game_id": game_id,
                        "packet_id": msg_pid,
                        "data": message,
                        "timestamp": time.time()
                    })

        except Exception as e:
            logger.error(f"Error handling FreeCiv message for {game_id}: {e}")

    async def _handle_connection_failure(self, game_id: str):
        """Handle connection failure"""
        logger.warning(f"Handling connection failure for game {game_id}")

        # Mark connection as failed (state manager records failure time)
        await connection_state_manager.mark_connection_failed(game_id, "Connection attempts exhausted")

        # Remove the failed connection using connection state manager (thread-safe)
        await connection_state_manager.remove_connection(game_id)

        # Implement circuit breaker pattern
        connections = await connection_state_manager.get_all_connections()
        connection_info = connections.get(game_id)
        retry_count = connection_info.retry_count if connection_info else 0

        if retry_count >= settings.max_retry_attempts:
            logger.error(f"Max retry attempts reached for game {game_id}. Implementing circuit breaker.")
            # Could trigger alerts, disable game, etc.

    async def _send_request_and_wait(self, game_id: str, message: Dict[str, Any], timeout: float = DEFAULT_REQUEST_TIMEOUT) -> Dict[str, Any]:
        """Send request to proxy and wait for response"""
        # FIXED: Use RequestManager to prevent memory leaks (addresses lines 336-367 issue)
        try:
            # Use RequestManager's send_request_and_wait method
            response = await request_manager.send_request_and_wait(
                send_callback=lambda msg: self.forward_to_proxy(game_id, msg),
                message=message,
                timeout=timeout,
                agent_id=f"gateway-{game_id}",
                request_type="proxy_request"
            )
            return response

        except asyncio.TimeoutError:
            logger.warning(f"Request to game {game_id} timed out after {timeout}s")
            return {
                "success": False,
                "error": "Request timed out"
            }
        except Exception as e:
            logger.error(f"Error sending request to game {game_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_game(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new game session"""
        try:
            game_id = f"game-{uuid.uuid4()}"

            # Check capacity
            if len(self.game_sessions) >= settings.max_concurrent_games:
                return {
                    "success": False,
                    "error": f"Maximum concurrent games ({settings.max_concurrent_games}) exceeded"
                }

            # Store game session
            self.game_sessions[game_id] = {
                "config": config,
                "created_at": time.time(),
                "status": "active",
                "players": {}
            }

            # Connect to FreeCiv proxy
            proxy_result = await self.connect_to_freeciv_proxy(game_id)
            if not proxy_result["success"]:
                del self.game_sessions[game_id]
                return proxy_result

            # NOTE: Streaming is started on-demand when agents authenticate via WebSocket
            # See websocket_handlers.py -> AgentWebSocketHandler -> auth_success handler
            # This ensures streaming starts only when the game is actually ready (agents connected)

            # Notify spectators that the game has started
            await self.notify_spectators_game_start(game_id)

            return {
                "success": True,
                "game_id": game_id,
                "connection_details": {
                    "ws_url": f"ws://localhost:{settings.port}/ws/agent/{{agent_id}}",
                    "game_port": settings.freeciv_proxy_port
                }
            }

        except Exception as e:
            logger.error(f"Error creating game: {e}")
            return {
                "success": False,
                "error": f"Game creation failed: {str(e)}"
            }

    async def get_game_state(self, game_id: str, player_id: int, format_type: str = "llm_optimized") -> Dict[str, Any]:
        """Get game state from FreeCiv proxy"""
        try:
            if game_id not in self.game_sessions:
                return {
                    "success": False,
                    "error": f"Game not found: {game_id}"
                }

            # Send state query to LLM handler
            state_request = {
                "type": "state_query",
                "format": format_type,
                "include_actions": True
            }

            # Send request and wait for response
            response = await self._send_request_and_wait(game_id, state_request, timeout=15.0)

            if response.get("success", False):
                return {
                    "success": True,
                    "format": format_type,
                    "data": response.get("data", {})
                }
            else:
                return {
                    "success": False,
                    "error": response.get("error", "Unknown error from proxy")
                }

        except Exception as e:
            logger.error(f"Error getting game state for {game_id}: {e}")
            return {
                "success": False,
                "error": f"State query failed: {str(e)}"
            }

    async def get_global_game_state(self, game_id: str) -> Dict[str, Any]:
        """Get authoritative global game state without fog of war filtering.

        Used by match orchestrator for stats collection. Unlike get_game_state(),
        this returns all units/cities from all players regardless of visibility.

        Note: No server-side rate limiting — the caller (agent-clash match_service)
        is expected to cache responses (1s TTL) to avoid excessive polling.
        """
        try:
            # Check both game_sessions (REST-created games) and
            # connection_manager (WebSocket-connected agents) for game existence.
            # Agent-clash connects via WebSocket, so games are only registered
            # in connection_manager — not in game_sessions.
            game_info = await connection_manager.get_game_info(game_id)
            if game_id not in self.game_sessions and game_info is None:
                return {
                    "success": False,
                    "error": f"Game not found: {game_id}"
                }

            state_request = {
                "type": "global_state_query",
            }

            response = await self._send_request_and_wait(game_id, state_request, timeout=15.0)

            if response.get("type") == "global_state_response":
                return {
                    "success": True,
                    "data": response.get("data", {}),
                    "timestamp": response.get("timestamp")
                }
            elif response.get("type") == "error":
                return {
                    "success": False,
                    "error": response.get("message", "Unknown error from proxy")
                }
            else:
                return {
                    "success": False,
                    "error": response.get("error", "Unknown error from proxy")
                }

        except Exception as e:
            logger.error(f"Error getting global game state for {game_id}: {e}")
            return {
                "success": False,
                "error": f"Global state query failed: {str(e)}"
            }

    async def submit_action(self, game_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
        """Submit action to FreeCiv proxy"""
        try:
            if game_id not in self.game_sessions:
                return {
                    "success": False,
                    "error": f"Game not found: {game_id}"
                }

            # Forward action to FreeCiv proxy
            action_message = {
                "type": "action",
                "agent_id": f"gateway-{uuid.uuid4()}",
                "timestamp": time.time(),
                "data": action
            }

            # Send action and wait for response
            response = await self._send_request_and_wait(game_id, action_message, timeout=10.0)

            if response.get("success", False):
                # Notify spectators of successful action
                await self._notify_spectators_action(game_id, action, response)

                return {
                    "success": True,
                    "action_id": response.get("action_id", str(uuid.uuid4())),
                    "result": response.get("result", "Action executed successfully")
                }
            else:
                return {
                    "success": False,
                    "error": response.get("error", "Action execution failed")
                }

        except Exception as e:
            logger.error(f"Error submitting action for {game_id}: {e}")
            return {
                "success": False,
                "error": f"Action submission failed: {str(e)}"
            }

    async def get_spectator_game_state(self, game_id: str) -> Dict[str, Any]:
        """Get game state for spectators (simplified view)"""
        try:
            if game_id not in self.game_sessions:
                return {
                    "turn": 1,
                    "players": {},
                    "game_info": {"status": "not_found", "turn": 1}
                }

            session = self.game_sessions[game_id]
            return {
                "turn": session.get("current_turn", 1),
                "players": session.get("players", {}),
                "game_info": {
                    "status": session.get("status", "running"),
                    "turn": session.get("current_turn", 1),
                    "game_id": game_id
                }
            }

        except Exception as e:
            logger.error(f"Error getting spectator game state for {game_id}: {e}")
            return {
                "turn": 1,
                "players": {},
                "game_info": {"status": "error", "turn": 1}
            }

    async def _notify_spectators_action(self, game_id: str, action: Dict[str, Any], response: Dict[str, Any]):
        """Notify spectators of player actions"""
        try:
            player_id = action.get("player_id")
            if not player_id:
                return

            action_data = {
                "type": action.get("action_type", "unknown"),
                "from": action.get("from"),
                "to": action.get("to"),
                "details": action.get("details", {}),
                "timestamp": time.time()
            }

            await connection_manager.broadcast_to_spectators(game_id, {
                "type": "player_action",
                "game_id": game_id,
                "player_id": player_id,
                "action": action_data,
                "timestamp": time.time()
            })

        except Exception as e:
            logger.error(f"Error notifying spectators of action in {game_id}: {e}")

    async def notify_spectators_turn_change(self, game_id: str, turn_number: int):
        """Notify spectators of turn changes"""
        try:
            # Update game session
            if game_id in self.game_sessions:
                self.game_sessions[game_id]["current_turn"] = turn_number

            await connection_manager.broadcast_to_spectators(game_id, {
                "type": "turn_update",
                "game_id": game_id,
                "turn": turn_number,
                "timestamp": time.time()
            })

        except Exception as e:
            logger.error(f"Error notifying spectators of turn change in {game_id}: {e}")

    async def notify_spectators_game_state(self, game_id: str, state_data: Dict[str, Any]):
        """Notify spectators of game state updates"""
        try:
            await connection_manager.broadcast_to_spectators(game_id, {
                "type": "game_state",
                "game_id": game_id,
                "data": state_data,
                "timestamp": time.time()
            })

        except Exception as e:
            logger.error(f"Error notifying spectators of game state in {game_id}: {e}")

    async def notify_spectators_game_start(self, game_id: str):
        """Notify spectators that a game has started"""
        try:
            initial_state = await self.get_spectator_game_state(game_id)

            await connection_manager.broadcast_to_spectators(game_id, {
                "type": "game_started",
                "game_id": game_id,
                "data": initial_state,
                "timestamp": time.time()
            })

        except Exception as e:
            logger.error(f"Error notifying spectators of game start in {game_id}: {e}")

    async def notify_spectators_game_end(self, game_id: str, result: Dict[str, Any]):
        """Notify spectators that a game has ended"""
        try:
            await connection_manager.broadcast_to_spectators(game_id, {
                "type": "game_ended",
                "game_id": game_id,
                "result": result,
                "timestamp": time.time()
            })

        except Exception as e:
            logger.error(f"Error notifying spectators of game end in {game_id}: {e}")

    async def end_game(self, game_id: str, result: Dict[str, Any] = None):
        """End a game session and clean up resources"""
        try:
            if game_id not in self.game_sessions:
                logger.warning(f"Attempted to end non-existent game: {game_id}")
                return

            # Notify spectators before cleanup
            end_result = result or {"reason": "Game ended", "winner": None}
            await self.notify_spectators_game_end(game_id, end_result)

            # Stop streaming (graceful degradation on failure)
            # Streaming may have been started via WebSocket auth_success handler
            session = self.game_sessions[game_id]
            if self.stream_manager:
                try:
                    await self.stream_manager.stop_stream(game_id)
                    logger.info(f"🎬 Stopped streaming for game {game_id}")
                except Exception as e:
                    # Streaming cleanup failure should not block game cleanup
                    logger.debug(f"Streaming cleanup for game {game_id}: {e}")

            # Clean up game session
            logger.info(f"Ending game {game_id} after {time.time() - session.get('created_at', time.time()):.1f}s")

            # Remove from active sessions
            del self.game_sessions[game_id]

            # Clean up any agent connections for this game
            agents_to_remove = []
            for agent_id, agent_data in self.active_agents.items():
                if agent_data.get("game_id") == game_id:
                    agents_to_remove.append(agent_id)

            for agent_id in agents_to_remove:
                del self.active_agents[agent_id]
                logger.info(f"Removed agent {agent_id} from ended game {game_id}")

            # Close proxy connection if it exists
            await connection_state_manager.remove_connection(game_id)

        except Exception as e:
            logger.error(f"Error ending game {game_id}: {e}")

    async def get_health_status(self) -> Dict[str, Any]:
        """Get gateway health status"""
        try:
            # Get stats from all managers - gracefully handle failures
            connection_stats = {}
            request_stats = {}
            connection_state_stats = {}
            token_stats = {}

            try:
                connection_stats = connection_manager.get_connection_stats()
            except Exception as e:
                logger.warning(f"Failed to get connection stats: {e}")

            try:
                request_stats = await request_manager.get_stats()
            except Exception as e:
                logger.warning(f"Failed to get request stats: {e}")

            try:
                connection_state_stats = await connection_state_manager.get_stats()
            except Exception as e:
                logger.warning(f"Failed to get connection state stats: {e}")

            try:
                token_stats = await secure_token_manager.get_stats()
            except Exception as e:
                logger.warning(f"Failed to get token stats: {e}")

            active_games = len(self.game_sessions)
            active_agents = len(self.active_agents)

            status = "healthy"
            issues = []

            # Check for issues
            if active_games >= settings.max_concurrent_games:
                status = "degraded"
                issues.append("At maximum game capacity")

            proxy_connections = connection_state_stats.get("active_connections", 0)
            if proxy_connections < active_games:
                status = "degraded"
                issues.append("Some FreeCiv proxy connections missing")

            # Check for high error rates
            if request_stats.get("timed_out_requests", 0) > MAX_TIMED_OUT_REQUESTS_WARNING:
                status = "degraded"
                issues.append("High request timeout rate")

            return {
                "status": status,
                "active_games": active_games,
                "active_agents": active_agents,
                "proxy_connections": proxy_connections,
                "connection_stats": connection_stats,
                "request_stats": request_stats,
                "connection_state_stats": connection_state_stats,
                "token_stats": token_stats,
                "uptime": time.time() - gateway_start_time,
                "issues": issues if issues else None
            }

        except Exception as e:
            logger.error(f"Error getting health status: {e}")
            return {
                "status": "unhealthy",
                "error": "Internal server error"
            }

    async def _route_to_freeciv(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Route message to FreeCiv proxy"""
        agent_id = message.get("agent_id")

        if not agent_id or agent_id not in self.active_agents:
            return {
                "success": False,
                "error": "Agent not registered"
            }

        # FIXED: Use safe dictionary access to prevent KeyError crashes (addresses line 538 issue)
        game_id = get_agent_game_id(self.active_agents, agent_id)
        if not game_id:
            return {
                "success": False,
                "error": "Game ID not found for agent"
            }

        # Use connection state manager instead of direct proxy_connections access
        connection = await connection_state_manager.get_connection(game_id)
        if not connection:
            result = await self.connect_to_freeciv_proxy(game_id)
            if not result["success"]:
                return result

        success = await self.forward_to_proxy(game_id, message)
        if not success:
            return {
                "success": False,
                "error": "Failed to forward message to proxy"
            }

        return {"success": True}

    async def _route_to_agent_clash(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Route message to agent-clash (not implemented in this scope)"""
        return {
            "success": False,
            "error": "agent-clash routing not implemented in this scope"
        }


# Global gateway instance
gateway = LLMGateway()
gateway_start_time = time.time()


# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Application startup"""
    if not validate_settings():
        raise RuntimeError("Invalid configuration settings")

    # Initialize distributed tracing if enabled
    if ENABLE_CLOUD_TRACE:
        init_tracing("llm-gateway", enable_cloud_trace=True)
        logger.info("OpenTelemetry tracing initialized with Cloud Trace exporter")
    else:
        logger.info("Distributed tracing disabled (set ENABLE_CLOUD_TRACE=true to enable)")

    await gateway.start()
    logger.info(f"LLM Gateway started on {settings.host}:{settings.port}")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown"""
    await gateway.stop()
    logger.info("LLM Gateway shutdown complete")


# Health check endpoint
@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint - no rate limiting for health checks"""
    try:
        health_status = await gateway.get_health_status()

        if health_status["status"] == "unhealthy":
            raise HTTPException(status_code=503, detail=health_status)

        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}


# Import API endpoints and WebSocket handlers after app creation
def setup_routes():
    """Setup API routes and WebSocket handlers"""
    try:
        from api_endpoints import router as api_router
        # Update the gateway reference in api_endpoints
        import api_endpoints
        api_endpoints.gateway = gateway
        app.include_router(api_router, prefix="/api")
        logger.info("API endpoints registered")
    except ImportError as e:
        logger.warning(f"API endpoints not available: {e}")

    try:
        from websocket_handlers import register_websocket_routes
        # Update the gateway reference in websocket_handlers
        import websocket_handlers
        websocket_handlers.gateway = gateway
        register_websocket_routes(app)
        logger.info("WebSocket handlers registered")
    except ImportError as e:
        logger.warning(f"WebSocket handlers not available: {e}")

# Setup routes after gateway is created
setup_routes()


if __name__ == "__main__":
    import uvicorn

    # CRITICAL: Configure WebSocket ping timeout for LLM agent connections
    # Default uvicorn ws_ping_timeout is 20s - way too short for LLM inference calls
    # that can take 60-120+ seconds. If agent is busy with LLM and can't respond to
    # WebSocket pings, uvicorn closes the connection (code 1000).
    #
    # IMPORTANT: Each ping is tracked individually! If ping #1 times out while
    # waiting for pong, connection closes - even if ping #2 was answered.
    # Therefore: timeout must be > interval + max_busy_time
    #
    # With interval=30s, timeout=180s:
    # - Pings sent at T=0, T=30, T=60, T=90...
    # - If agent is busy for 120s (T=5 to T=125), ping at T=0 must survive until T=125
    # - 180s timeout gives 55s safety margin
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=True,
        ws_ping_interval=30.0,  # Send ping every 30s for reasonable dead connection detection
        ws_ping_timeout=180.0,  # 3 min timeout handles LLM calls up to ~150s
    )
