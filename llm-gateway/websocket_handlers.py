#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WebSocket handlers for LLM Gateway
"""

import asyncio
import json
import logging
import random
import time
from typing import Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect, FastAPI
import websockets

try:
    from .connection_manager import connection_manager
    from .config import settings
    from .utils.origin_validator import validate_websocket_origin, get_websocket_origin_info, create_origin_rejection_response
    from .utils.rate_limiter import comprehensive_rate_limiter
    from .utils.constants import (
        MAX_MESSAGE_SIZE_BYTES, ERROR_CODE_VALIDATION, ERROR_CODE_RATE_LIMIT,
        ERROR_CODE_NOT_AUTHENTICATED, ERROR_CODE_CONNECTION_LOST, ERROR_CODE_UNKNOWN,
        WEBSOCKET_PING_INTERVAL, WEBSOCKET_PING_TIMEOUT, WEBSOCKET_CLOSE_TIMEOUT,
        WEBSOCKET_OPEN_TIMEOUT
    )
    from .tracing import extract_trace_context, inject_trace_context, create_child_span
except ImportError:
    from connection_manager import connection_manager
    from config import settings
    from utils.origin_validator import validate_websocket_origin, get_websocket_origin_info, create_origin_rejection_response
    from utils.rate_limiter import comprehensive_rate_limiter
    from utils.constants import (
        MAX_MESSAGE_SIZE_BYTES, ERROR_CODE_VALIDATION, ERROR_CODE_RATE_LIMIT,
        ERROR_CODE_NOT_AUTHENTICATED, ERROR_CODE_CONNECTION_LOST, ERROR_CODE_UNKNOWN,
        WEBSOCKET_PING_INTERVAL, WEBSOCKET_PING_TIMEOUT, WEBSOCKET_CLOSE_TIMEOUT,
        WEBSOCKET_OPEN_TIMEOUT
    )
    from tracing import extract_trace_context, inject_trace_context, create_child_span

# Gateway will be injected by main.py to avoid circular imports
gateway = None

logger = logging.getLogger("llm-gateway")

# FreeCiv packet IDs for turn change detection (Issue #2: Turn Desync Fix)
# Source of truth: freeciv/freeciv/common/networking/packets.def
PACKET_BEGIN_TURN = 15   # Signals start of a new turn
PACKET_GAME_INFO = 16    # Contains game state including turn number


class AgentWebSocketHandler:
    """Handler for agent WebSocket connections - pure pass-through to proxy"""

    def __init__(self, websocket: WebSocket, agent_id: str):
        self.websocket = websocket
        self.agent_id = agent_id
        self.connection_id: Optional[str] = None
        self.authenticated = False
        self.player_id: Optional[int] = None
        self.game_id: Optional[str] = None
        self.proxy_connection: Optional[WebSocket] = None  # Connection to freeciv-proxy LLM handler
        self._last_known_turn = 0  # Track turn number for desync detection
        # Issue #6 Fix: Track proxy listener task to prevent multiple recv() coroutines
        # Without this, reconnection creates duplicate tasks that both call recv(),
        # causing "cannot call recv while another coroutine is already running recv"
        self._proxy_listener_task: Optional[asyncio.Task] = None

    async def handle_connection(self):
        """Handle the WebSocket connection lifecycle"""
        # Validate origin before accepting connection
        if not self._validate_origin():
            await self.websocket.close(code=1008, reason="Unauthorized origin")
            return

        await self.websocket.accept()

        try:
            # Check connection limits
            if not await comprehensive_rate_limiter.track_connection(self.agent_id):
                await self._send_error("Connection limit exceeded for agent")
                return

            # Add to connection manager
            self.connection_id = await connection_manager.add_connection(
                self.websocket, "agent", self.agent_id
            )

            # Send welcome message
            await self._send_welcome()

            # Message handling loop
            while True:
                try:
                    data = await self.websocket.receive_text()

                    # WebSocket-level message size enforcement
                    # TODO: Add test for accumulated buffer scenarios:
                    #   - Multiple large messages sent rapidly (within rate limit window)
                    #   - Combined buffer size exceeding MAX_MESSAGE_SIZE_BYTES across pending messages
                    #   - Memory pressure from buffered messages in WebSocket queue
                    #   - Behavior when buffer fills and new messages arrive
                    message_size = len(data.encode('utf-8'))
                    if message_size > MAX_MESSAGE_SIZE_BYTES:
                        await self._send_error(
                            f"Message size {message_size} bytes exceeds limit of {MAX_MESSAGE_SIZE_BYTES} bytes",
                            error_code=ERROR_CODE_VALIDATION
                        )
                        logger.warning(
                            f"Agent {self.agent_id} sent oversized message: {message_size} bytes"
                        )
                        continue

                    # Rate limiting and message size validation
                    is_allowed, reason = await comprehensive_rate_limiter.check_rate_limits(
                        self.agent_id,
                        message_size=message_size,
                        message_content=data
                    )

                    if not is_allowed:
                        await self._send_rate_limit_error(reason)
                        continue

                    message = json.loads(data)
                    await self._handle_message(message)

                except WebSocketDisconnect:
                    logger.info(f"Agent {self.agent_id} disconnected")
                    break

                except json.JSONDecodeError:
                    await self._send_error("Invalid JSON format")

                except Exception as e:
                    logger.error(f"Error handling message from {self.agent_id}: {e}")
                    await self._send_error("Message processing failed")

        except Exception as e:
            logger.error(f"Error in agent connection {self.agent_id}: {e}")

        finally:
            # Issue #6 Fix: Cancel listener task before closing connection
            if self._proxy_listener_task and not self._proxy_listener_task.done():
                self._proxy_listener_task.cancel()
                try:
                    await self._proxy_listener_task
                except asyncio.CancelledError:
                    pass

            # Cleanup proxy connection
            if self.proxy_connection:
                await self.proxy_connection.close()
                self.proxy_connection = None

            # Cleanup connection manager
            if self.connection_id:
                await connection_manager.handle_disconnect(self.connection_id)

            # NOTE: Stream is NOT stopped here on agent disconnect.
            # The game pauses (handled by freeciv-proxy) and the stream continues
            # showing the paused game state. Stream only stops when the game
            # actually terminates (via LLMGateway.end_game()).
            # This allows agents to reconnect while viewers see the paused game.

            # Release connection tracking
            await comprehensive_rate_limiter.release_connection(self.agent_id)

    async def _send_welcome(self):
        """Send welcome message"""
        welcome = {
            "type": "welcome",
            "handler_id": self.connection_id,
            "message": "LLM agent gateway ready. Send llm_connect message to authenticate."
        }
        await self.websocket.send_text(json.dumps(welcome))

    async def _handle_message(self, message: Dict[str, Any]):
        """Handle incoming message from agent - pass through to proxy"""
        message_type = message.get("type")

        # Extract trace context from incoming message (if present)
        parent_ctx = extract_trace_context(message)

        # Create a span for this message handling operation
        with create_child_span(
            f"gateway.handle_{message_type or 'unknown'}",
            parent_ctx,
            {"agent_id": self.agent_id, "message_type": message_type}
        ) as span:
            if message_type == "llm_connect":
                # First message - establish proxy connection and forward
                await self._connect_to_proxy_and_forward(message, span)
            elif self.authenticated and self.proxy_connection:
                # All other messages - forward directly to proxy
                await self._forward_to_proxy(message, span)
            elif message_type == "ping":
                # Handle pings locally for connection health
                await self._handle_ping(message)
            else:
                # Not authenticated or not connected
                span.set_attribute("error", True)
                span.set_attribute("error.reason", "not_authenticated")
                await self._send_error(
                    "Not authenticated - please send llm_connect message first",
                    error_code=ERROR_CODE_NOT_AUTHENTICATED,
                    details={
                        "authenticated": self.authenticated,
                        "proxy_connected": self.proxy_connection is not None,
                        "can_retry": True
                    }
                )

    async def _connect_to_proxy_with_retry(self, proxy_url: str) -> websockets.WebSocketClientProtocol:
        """
        Connect to proxy with retry logic and exponential backoff.

        Addresses E999 "timed out during opening handshake" errors by:
        1. Using explicit open_timeout (30s default)
        2. Retrying with exponential backoff on transient failures
        3. Adding jitter to prevent thundering herd on reconnects

        Args:
            proxy_url: WebSocket URL to connect to

        Returns:
            WebSocket connection on success

        Raises:
            Exception: After all retry attempts exhausted
        """
        last_error: Optional[Exception] = None

        for attempt in range(settings.max_retry_attempts):
            try:
                logger.info(
                    f"Agent {self.agent_id} connecting to proxy (attempt {attempt + 1}/{settings.max_retry_attempts}): {proxy_url}"
                )

                # Set max_size to 100MB to handle large FreeCiv game state packets
                # FreeCiv sends packets with map data, player info, city data that exceed default 1MB
                # Add open_timeout to prevent "timed out during opening handshake" errors
                connection = await websockets.connect(
                    proxy_url,
                    max_size=100 * 1024 * 1024,  # 100MB for large game state packets
                    max_queue=64,  # Increase queue size to handle multiple large frames
                    open_timeout=WEBSOCKET_OPEN_TIMEOUT,  # 30s for handshake under load
                    ping_interval=WEBSOCKET_PING_INTERVAL,  # Ping every 20s to detect dead connections
                    ping_timeout=WEBSOCKET_PING_TIMEOUT,  # Wait up to 60s for pong response (matches proxy)
                    close_timeout=WEBSOCKET_CLOSE_TIMEOUT  # Timeout for graceful close
                )

                logger.info(
                    f"Connected to proxy for agent {self.agent_id} on attempt {attempt + 1} "
                    f"(max_size=100MB, open_timeout={WEBSOCKET_OPEN_TIMEOUT}s, ping_interval={WEBSOCKET_PING_INTERVAL}s)"
                )
                return connection

            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(
                    f"Agent {self.agent_id} proxy connection timed out (attempt {attempt + 1}/{settings.max_retry_attempts})"
                )
            except websockets.exceptions.WebSocketException as e:
                last_error = e
                logger.warning(
                    f"Agent {self.agent_id} WebSocket error (attempt {attempt + 1}/{settings.max_retry_attempts}): {e}"
                )
            except ConnectionRefusedError as e:
                last_error = e
                logger.warning(
                    f"Agent {self.agent_id} connection refused (attempt {attempt + 1}/{settings.max_retry_attempts}): {e}"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Agent {self.agent_id} unexpected error (attempt {attempt + 1}/{settings.max_retry_attempts}): {type(e).__name__}: {e}"
                )

            # Calculate exponential backoff delay with jitter
            if attempt < settings.max_retry_attempts - 1:  # Don't wait after last attempt
                base_delay = settings.initial_retry_delay * (settings.retry_backoff_multiplier ** attempt)
                delay = min(base_delay, settings.max_retry_delay)
                # Add 10-30% random jitter to prevent thundering herd
                jitter = random.uniform(0.1, 0.3) * delay
                total_delay = delay + jitter

                logger.info(f"Agent {self.agent_id} waiting {total_delay:.2f}s before retry")
                await asyncio.sleep(total_delay)

        # All attempts exhausted
        error_type = type(last_error).__name__ if last_error else "Unknown"
        logger.error(
            f"Agent {self.agent_id} failed to connect after {settings.max_retry_attempts} attempts. "
            f"Last error type: {error_type}"
        )
        if last_error:
            raise last_error
        raise ConnectionError(
            f"Connection failed after {settings.max_retry_attempts} retry attempts "
            f"(no specific error captured)"
        )

    async def _connect_to_proxy_and_forward(self, message: Dict[str, Any], span=None):
        """Connect to proxy LLM handler and forward the connect message"""
        try:
            # Connect to the freeciv-proxy LLM handler endpoint
            proxy_url = f"ws://{settings.freeciv_proxy_host}:{settings.freeciv_proxy_port}{settings.freeciv_proxy_ws_path}"
            if span:
                span.set_attribute("proxy.url", proxy_url)

            # Use retry logic for resilient connection establishment
            # IMPORTANT: Store in local variable first to avoid race condition
            # The old listener's finally block sets self.proxy_connection = None
            new_connection = await self._connect_to_proxy_with_retry(proxy_url)

            # Issue #6 Fix: Cancel any existing listener task before creating new one
            # This prevents "cannot call recv while another coroutine is running recv" error
            # that occurs when reconnection creates duplicate listener tasks
            if self._proxy_listener_task and not self._proxy_listener_task.done():
                logger.info(f"Cancelling existing proxy listener for agent {self.agent_id}")
                self._proxy_listener_task.cancel()
                try:
                    await self._proxy_listener_task
                except asyncio.CancelledError:
                    pass  # Expected when cancelling

            # Now safe to assign the new connection (after old listener's finally block ran)
            self.proxy_connection = new_connection

            # Start listening for proxy messages in background
            self._proxy_listener_task = asyncio.create_task(self._listen_to_proxy())

            # Transform message format: flatten 'data' fields to top level for proxy
            proxy_message = self._transform_to_proxy_format(message)

            # Inject trace context into forwarded message for distributed tracing
            if span:
                trace_ctx = inject_trace_context(span)
                if trace_ctx:
                    proxy_message["trace_context"] = trace_ctx

            # Forward the connect message to proxy
            await self.proxy_connection.send(json.dumps(proxy_message))
            logger.info(f"Forwarded llm_connect message for agent {self.agent_id}")

            # Mark as authenticated to allow further pass-through
            self.authenticated = True

            # Extract game_id for connection tracking
            if "data" in message:
                self.game_id = message["data"].get("game_id")

        except websockets.ConnectionClosed as e:
            logger.error(f"Proxy connection closed during connection for agent {self.agent_id}: {e}")
            await self._send_error(
                "Failed to establish connection to game server - connection closed",
                error_code=ERROR_CODE_CONNECTION_LOST,
                details={
                    "session_valid": False,
                    "civserver_connected": False,
                    "player_id": None,
                    "reason": "proxy_connection_failed",
                    "can_retry": True
                }
            )
        except Exception as e:
            logger.error(f"Failed to connect to proxy for agent {self.agent_id}: {e}")
            await self._send_error(
                f"Failed to connect to game server: {str(e)}",
                error_code=ERROR_CODE_UNKNOWN,
                details={
                    "session_valid": False,
                    "civserver_connected": False,
                    "player_id": None,
                    "reason": "proxy_connection_exception",
                    "exception_type": type(e).__name__,
                    "can_retry": True
                }
            )

    async def _listen_to_proxy(self):
        """Listen for messages from proxy and forward to agent"""
        try:
            while self.proxy_connection:
                try:
                    # Receive message from proxy
                    # Note: websockets >= 10.0 is safe for concurrent send/recv from different tasks
                    # (one task can call recv() while another calls send() on the same connection)
                    # See: https://websockets.readthedocs.io/en/stable/faq/common.html#are-websocket-objects-thread-safe
                    proxy_message = await self.proxy_connection.recv()
                    # Issue #13 (PR Review): Use DEBUG for hot path logging to avoid string formatting overhead
                    logger.debug(f"📥 Gateway received from proxy for agent {self.agent_id}: {proxy_message[:200]}")

                    # Transform proxy messages to agent format
                    try:
                        msg_data = json.loads(proxy_message)

                        # Handle both single objects and arrays of packets from FreeCiv protocol
                        if isinstance(msg_data, list):
                            # NOTE: PACKET_CONN_PING (pid:88) is now filtered in civcom.py
                            # CivCom handles civserver keep-alive internally, so pings should never reach here
                            # We no longer forward conn_ping to agents since:
                            # 1. CivCom handles the pong response to civserver
                            # 2. WebSocket-level ping/pong handles connection health
                            # 3. Forwarding caused E101 errors when agents responded with {"pid": 89}

                            # Issue #2 (Turn Desync): Detect turn changes in packet arrays
                            for packet in msg_data:
                                if isinstance(packet, dict):
                                    pid = packet.get('pid')
                                    # PACKET_BEGIN_TURN signals new turn
                                    if pid == PACKET_BEGIN_TURN:
                                        new_turn = packet.get('turn')
                                        if new_turn and new_turn > self._last_known_turn:
                                            self._last_known_turn = new_turn
                                            await self._notify_turn_change(new_turn)
                                    # PACKET_GAME_INFO contains turn in game state
                                    elif pid == PACKET_GAME_INFO:
                                        new_turn = packet.get('turn')
                                        if new_turn and new_turn > self._last_known_turn:
                                            self._last_known_turn = new_turn
                                            await self._notify_turn_change(new_turn)

                            # Raw FreeCiv packet array - forward as-is
                            logger.debug(f"📦 Forwarding packet array ({len(msg_data)} packets) to agent {self.agent_id}")
                            await self.websocket.send_text(proxy_message)
                            logger.debug(f"📤 Forwarded packet array to agent {self.agent_id}")
                            continue

                        msg_type = msg_data.get("type")

                        # Filter out welcome message - agent doesn't expect it
                        if msg_type == "welcome":
                            logger.debug(f"🚫 Filtered welcome message for agent {self.agent_id}")
                            continue

                        # Transform auth_success from proxy to agent format
                        if msg_type == "auth_success":
                            # Extract player_id from auth_success for packet routing
                            self.player_id = msg_data.get('player_id')

                            # CRITICAL FIX (AGE-192): Update ConnectionInfo with player_id for session persistence
                            # This enables session resumption to work correctly after disconnects
                            game_id = msg_data.get('game_id')
                            civserver_port = msg_data.get('civserver_port')  # For observer URL generation
                            if self.player_id is not None:
                                await connection_manager.update_agent_auth(
                                    self.agent_id,
                                    self.player_id,
                                    game_id,
                                    civserver_port
                                )

                            logger.info(
                                f"🔑 Transforming auth_success for agent {self.agent_id}:\n"
                                f"   Player ID: {self.player_id}\n"
                                f"   Status: {msg_data.get('status', 'N/A')}"
                            )

                            # Start streaming on-demand when agent authenticates
                            # This triggers LocalStreamManager (local) or StreamManager (k8s) to
                            # create streaming containers with observer URLs for this game
                            if gateway and gateway.stream_manager and game_id and civserver_port:
                                try:
                                    # Only start streaming for the first player (avoid duplicate streams)
                                    if self.player_id == 0:
                                        player_names = {
                                            "player1": self.agent_id,
                                            "player2": None  # Will be populated by second agent
                                        }
                                        stream_result = await gateway.stream_manager.start_stream(
                                            game_id=game_id,
                                            civserver_port=civserver_port,
                                            player_names=player_names
                                        )
                                        logger.info(
                                            f"🎬 Started streaming for game {game_id}:\n"
                                            f"   Port: {civserver_port}\n"
                                            f"   Streams: {list(stream_result.get('local_stream_urls', {}).keys())}"
                                        )
                                except ValueError as e:
                                    # Stream already active for this game (expected for second player)
                                    logger.debug(f"Stream already active for game {game_id}: {e}")
                                except Exception as e:
                                    # Streaming failure should not block gameplay
                                    logger.warning(f"Failed to start streaming for game {game_id}: {e}")

                            # Agent expects: {type: "llm_connect", data: {type: "auth_success", ...}}
                            agent_message = {
                                "type": "llm_connect",
                                "agent_id": self.agent_id,
                                "timestamp": time.time(),
                                "data": {**msg_data, "success": True}
                            }
                            proxy_message = json.dumps(agent_message)
                        # Transform error messages
                        elif msg_type == "error":
                            error_code = msg_data.get('code', '')
                            is_recoverable = msg_data.get('recoverable', True)

                            logger.error(
                                f"❌ Error from proxy for agent {self.agent_id}:\n"
                                f"   Code: {error_code}\n"
                                f"   Message: {msg_data.get('message')}\n"
                                f"   Recoverable: {is_recoverable}\n"
                                f"   Details: {msg_data.get('details', {})}"
                            )
                            # Forward error as-is but nest in 'data' for consistency
                            agent_message = {
                                "type": "error",
                                "agent_id": self.agent_id,
                                "timestamp": time.time(),
                                "data": msg_data
                            }
                            proxy_message = json.dumps(agent_message)

                            # Terminal errors: close proxy connection to prevent futile retries
                            if not is_recoverable:
                                logger.warning(
                                    f"🔴 Terminal error for agent {self.agent_id} (code={error_code}). "
                                    f"Closing proxy connection — game state is irrecoverable."
                                )
                                try:
                                    await self.websocket.send_text(proxy_message)
                                except Exception as send_err:
                                    logger.warning(f"Failed to send terminal error to agent {self.agent_id}: {send_err}")
                                break  # Exits proxy listener loop → finally block closes connection
                        # Transform action_rejected messages
                        elif msg_type == "action_rejected":
                            logger.warning(
                                f"⚠️ Action rejected for agent {self.agent_id}:\n"
                                f"   Error Code: {msg_data.get('error_code')}\n"
                                f"   Error Message: {msg_data.get('error_message')}\n"
                                f"   Action: {msg_data.get('action')}"
                            )
                            # Forward action_rejected with consistent format
                            agent_message = {
                                "type": "action_rejected",
                                "agent_id": self.agent_id,
                                "timestamp": time.time(),
                                "data": msg_data
                            }
                            proxy_message = json.dumps(agent_message)
                        # Transform action_accepted messages
                        elif msg_type == "action_accepted":
                            logger.info(
                                f"✅ Action accepted for agent {self.agent_id}:\n"
                                f"   Action: {msg_data.get('action')}"
                            )
                            # Forward action_accepted with consistent format
                            agent_message = {
                                "type": "action_accepted",
                                "agent_id": self.agent_id,
                                "timestamp": time.time(),
                                "data": msg_data
                            }
                            proxy_message = json.dumps(agent_message)
                        # Handle conn_ping - now filtered at civcom.py level
                        elif msg_type == "conn_ping":
                            # NOTE: CivCom handles civserver keep-alive internally (responds with pong directly)
                            # and filters out PACKET_CONN_PING before forwarding to WebSocket clients.
                            # So we should never receive conn_ping here. If we do, log it but DON'T forward
                            # to agents (this caused E101 errors when agents responded with {"pid": 89})
                            logger.warning(f"🏓 PING: Unexpected conn_ping from proxy for agent {self.agent_id} (should be filtered by civcom)")
                            continue  # Don't forward to agent
                        # Handle conn_pong - should not come from proxy, but log if it does
                        elif msg_type == "conn_pong":
                            logger.warning(f"🏓 PONG: Unexpected conn_pong from proxy for agent {self.agent_id} (pongs should come from agent)")
                            continue  # Don't forward to agent
                        # Handle game_ready - important initialization signal
                        elif msg_type == "game_ready":
                            logger.info(f"🎮 GAME_READY: Received game_ready signal for agent {self.agent_id} - forwarding to agent")
                            # Forward as-is
                        # Handle game_ended - game over notification with winner info
                        elif msg_type == "game_ended":
                            logger.info(
                                f"🏁 GAME_ENDED: Received game_ended signal for agent {self.agent_id}\n"
                                f"   Winners: {msg_data.get('data', {}).get('winners', [])}\n"
                                f"   Is Winner: {msg_data.get('data', {}).get('is_winner', False)}"
                            )

                            # Update gateway session to mark game as ended
                            if self.game_id and gateway:
                                if self.game_id in gateway.game_sessions:
                                    gateway.game_sessions[self.game_id]["status"] = "ended"
                                    gateway.game_sessions[self.game_id]["winners"] = msg_data.get('data', {}).get('winners', [])
                                    gateway.game_sessions[self.game_id]["end_reason"] = msg_data.get('data', {}).get('reason', 'game_over')

                                # Notify spectators that game has ended
                                try:
                                    await gateway.notify_spectators_game_end(
                                        self.game_id,
                                        msg_data.get('data', {})
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to notify spectators of game end: {e}")

                            # Forward game_ended message to agent with consistent format
                            agent_message = {
                                "type": "game_ended",
                                "agent_id": self.agent_id,
                                "timestamp": time.time(),
                                "data": msg_data.get("data", {})
                            }
                            proxy_message = json.dumps(agent_message)
                        # Transform state_response to state_update
                        elif msg_type == "state_response":
                            # Proxy sends: {type: "state_response", data: {...state...}, format: "llm_optimized", ...}
                            # Agent expects: {type: "state_update", turn: 1, players: {}, ...state data at top level...}
                            state_data = msg_data.get("data", {})
                            # Debug logging to verify game dict structure
                            game_dict = state_data.get('game', {})
                            logger.info(
                                f"📊 Transforming state_response for agent {self.agent_id}:\n"
                                f"   Turn: {state_data.get('turn', 'N/A')}\n"
                                f"   Players: {len(state_data.get('players', []))}\n"
                                f"   Units: {len(state_data.get('units', []))}\n"
                                f"   Cities: {len(state_data.get('cities', []))}"
                            )
                            logger.debug(
                                f"📊 Game dict for agent {self.agent_id}:\n"
                                f"   Keys: {list(game_dict.keys())}\n"
                                f"   has current_player: {'current_player' in game_dict}\n"
                                f"   current_player value: {game_dict.get('current_player', 'MISSING')}"
                            )

                            # Extract state data from nested 'data' field and flatten to top level
                            agent_message = {
                                "type": "state_update",
                                **state_data,  # Flatten state data to top level
                                "format": msg_data.get("format"),
                                "cached": msg_data.get("cached"),
                                "timestamp": msg_data.get("timestamp")
                            }
                            proxy_message = json.dumps(agent_message)

                    except json.JSONDecodeError:
                        logger.warning(f"⚠️ Non-JSON message from proxy for agent {self.agent_id}")
                        pass  # Forward non-JSON messages as-is

                    # Forward to agent
                    await self.websocket.send_text(proxy_message)
                    logger.debug(f"📤 Forwarded message to agent {self.agent_id}")

                except websockets.ConnectionClosed:
                    logger.info(f"Proxy connection closed for agent {self.agent_id}")
                    break
                except Exception as e:
                    logger.error(f"Error forwarding proxy message to agent {self.agent_id}: {e}")

        except Exception as e:
            logger.error(f"Error in proxy listener for agent {self.agent_id}: {e}")
        finally:
            # Clean up proxy connection
            if self.proxy_connection:
                await self.proxy_connection.close()
                self.proxy_connection = None

    async def _notify_turn_change(self, new_turn: int):
        """Update gateway session with new turn number (Issue #2: Turn Desync Fix).

        This method synchronizes the gateway's session tracking with the actual
        turn number from the FreeCiv server. Previously, gateway.game_sessions[game_id]["current_turn"]
        was never updated after initialization, causing the Stats API to return stale turn data.

        Thread-safety: Uses gateway._sessions_lock to prevent race conditions when
        multiple agent handlers update game_sessions concurrently.
        """
        if self.game_id and gateway:
            # Issue #1 (PR Review): Lock protects against concurrent dict modification
            async with gateway._sessions_lock:
                if self.game_id in gateway.game_sessions:
                    gateway.game_sessions[self.game_id]["current_turn"] = new_turn
                    logger.info(f"🔄 Turn sync: game {self.game_id} advanced to turn {new_turn}")

            # Notify spectators outside the lock to avoid holding it during I/O
            try:
                await gateway.notify_spectators_turn_change(self.game_id, new_turn)
            except Exception as e:
                logger.warning(f"Failed to notify spectators of turn change: {e}")

    async def _forward_to_proxy(self, message: Dict[str, Any], span=None):
        """Forward message from agent to proxy"""
        try:
            if self.proxy_connection:
                msg_type = message.get("type")

                # Add diagnostic logging for critical message types
                if msg_type == "conn_pong":
                    # Agent sent conn_pong - acknowledge but don't forward (handled locally)
                    # CivCom handles civserver keep-alive internally
                    logger.info(f"🏓 PONG: Agent {self.agent_id} sent conn_pong - acknowledging locally (not forwarded)")
                elif msg_type == "action":
                    action_data = message.get("action", {})
                    action_type = action_data.get("action_type", "unknown")
                    actor_id = action_data.get("actor_id", "unknown")
                    target = action_data.get("target", "none")
                    logger.info(
                        f"🎮 ACTION: Agent {self.agent_id} sending action:\n"
                        f"   Type: {action_type}\n"
                        f"   Actor: {actor_id}\n"
                        f"   Target: {target}"
                    )
                    # Add action details to span for tracing
                    if span:
                        span.set_attribute("action.type", action_type)
                        span.set_attribute("action.actor_id", str(actor_id))

                # Transform message format for proxy
                proxy_message = self._transform_to_proxy_format(message)

                # Handle messages that should not be forwarded (e.g., conn_pong)
                if proxy_message is None:
                    logger.debug(f"Message type {msg_type} handled locally, not forwarding to proxy")
                    return

                # Inject trace context into forwarded message for distributed tracing
                if span:
                    trace_ctx = inject_trace_context(span)
                    if trace_ctx:
                        proxy_message["trace_context"] = trace_ctx

                # Note: websockets >= 10.0 is safe for concurrent send/recv from different tasks
                await self.proxy_connection.send(json.dumps(proxy_message))
                logger.debug(f"Forwarded agent message to proxy: {msg_type}")
            else:
                await self._send_error(
                    "Connection to game server lost",
                    error_code=ERROR_CODE_CONNECTION_LOST,
                    details={
                        "session_valid": self.authenticated,
                        "civserver_connected": False,
                        "player_id": self.player_id,
                        "reason": "proxy_connection_closed",
                        "can_retry": True
                    }
                )
        except websockets.ConnectionClosed as e:
            logger.error(f"Proxy connection closed while forwarding: {e}")
            await self._send_error(
                "Connection to game server lost",
                error_code=ERROR_CODE_CONNECTION_LOST,
                details={
                    "session_valid": self.authenticated,
                    "civserver_connected": False,
                    "player_id": self.player_id,
                    "reason": "connection_closed_during_send",
                    "can_retry": True
                }
            )
        except Exception as e:
            logger.error(f"Failed to forward message to proxy: {e}")
            await self._send_error(
                f"Failed to forward message: {str(e)}",
                error_code=ERROR_CODE_UNKNOWN,
                details={
                    "session_valid": self.authenticated,
                    "civserver_connected": self.proxy_connection is not None,
                    "player_id": self.player_id,
                    "reason": "message_forward_exception",
                    "exception_type": type(e).__name__,
                    "can_retry": False
                }
            )

    def _transform_to_proxy_format(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Transform agent message format to proxy format by flattening 'data' fields"""
        msg_type = message.get("type")

        # If message has 'data' field, flatten it to top level
        if "data" in message:
            transformed = {**message}  # Copy message
            data_fields = transformed.pop("data")
            transformed.update(data_fields)  # Merge data fields to top level
        else:
            transformed = {**message}

        # Filter fields based on proxy's schema for each message type
        if msg_type == "llm_connect":
            # Proxy expects: type, agent_id, api_token, port (optional), nation (optional), leader_name (optional), game_id (optional), auto_ready (optional, defaults to True), game_config (optional), player_id (optional for late reconnection), expected_turn (optional for state verification on reconnection)
            allowed_fields = {"type", "agent_id", "api_token", "port", "nation", "leader_name", "game_id", "auto_ready", "game_config", "player_id", "expected_turn"}
            transformed = {k: v for k, v in transformed.items() if k in allowed_fields}
        elif msg_type == "state_query":
            # Proxy expects: type, format (opt), include_actions (opt), player_id (opt)
            allowed_fields = {"type", "format", "include_actions", "player_id"}
            transformed = {k: v for k, v in transformed.items() if k in allowed_fields}
        elif msg_type == "ping":
            # Proxy expects: type, timestamp (opt)
            allowed_fields = {"type", "timestamp"}
            transformed = {k: v for k, v in transformed.items() if k in allowed_fields}
        elif msg_type == "player_ready":
            # Proxy expects: type, is_ready (opt, defaults to True)
            allowed_fields = {"type", "is_ready"}
            transformed = {k: v for k, v in transformed.items() if k in allowed_fields}
        elif msg_type == "action_submit":
            # agent-clash sends action_submit, transform to "action" for proxy
            # agent-clash format: {type: "action_submit", action: "canonical_string", agent_id: "...", timestamp: ...}
            # Proxy expects: {type: "action", action: {...action data...}, timestamp (opt)}

            # Get the action field (could be string or dict)
            action_data = message.get("action")

            # If action is missing, collect from flattened fields
            if action_data is None and "data" in message:
                action_data = message["data"]

            # Rebuild message with "action" type (not "action_submit")
            transformed = {
                "type": "action",
                "action": action_data
            }

            # Preserve optional timestamp
            if "timestamp" in message:
                transformed["timestamp"] = message["timestamp"]

        elif msg_type == "action":
            # Proxy expects: {type: "action", action: {...action data...}, timestamp (opt)}
            # agent-clash sends: {type: "action", agent_id: "...", data: {...}}
            # After flattening (lines 305-308), data fields are at top level

            # Collect action data from either original 'data' field or flattened fields
            if "data" in message:
                # Original message had 'data' field - use it directly
                action_data = message["data"]
            else:
                # Data was already flattened - collect all non-metadata fields
                action_data = {k: v for k, v in transformed.items()
                              if k not in {"type", "agent_id", "timestamp"}}

            # Rebuild message with nested "action" field as proxy expects
            transformed = {
                "type": "action",
                "action": action_data
            }

            # Preserve optional timestamp
            if "timestamp" in message:
                transformed["timestamp"] = message["timestamp"]
        elif msg_type == "chat":
            # Proxy expects: {type: "chat", message: "...", correlation_id (opt)}
            # Gateway format: {type: "chat", data: {message: "..."}, ...}
            chat_message = None
            if "data" in message and isinstance(message["data"], dict):
                chat_message = message["data"].get("message")
            if chat_message is None:
                chat_message = message.get("message")
            
            transformed = {
                "type": "chat",
                "message": chat_message
            }
            
            # Preserve optional fields
            if "correlation_id" in message:
                transformed["correlation_id"] = message["correlation_id"]
        elif msg_type == "global_state_query":
            # Pass through with type and correlation_id
            allowed_fields = {"type", "correlation_id"}
            transformed = {k: v for k, v in transformed.items() if k in allowed_fields}
        elif msg_type == "conn_pong":
            # Agent is responding to a conn_ping we may have sent earlier
            # However, CivCom already handles civserver keep-alive internally (PACKET_CONN_PING/PONG)
            # and WebSocket-level ping/pong handles connection health
            # So we just acknowledge the pong and DON'T forward it to the proxy
            # (Forwarding {"pid": 89} causes E101 errors since proxy expects {"type": ...} format)
            logger.debug(f"🏓 Received conn_pong from agent {self.agent_id} - acknowledging (not forwarding)")
            return None  # Signal to not forward this message
        # For other types, pass through as-is

        return transformed

    # Removed complex state query and action handlers - now handled by pass-through

    async def _handle_ping(self, message: Dict[str, Any]):
        """Handle ping message"""
        pong = {
            "type": "pong",
            "agent_id": self.agent_id,
            "timestamp": time.time()
        }
        await self.websocket.send_text(json.dumps(pong))

    async def _send_error(
        self,
        error_message: str,
        error_code: str = "E500",
        details: Optional[Dict[str, Any]] = None
    ):
        """
        Send detailed error message with optional context

        Args:
            error_message: Human-readable error description
            error_code: Specific error code (E120, E123, E999, etc.)
            details: Additional context about the error
        """
        error_data = {
            "type": "error",
            "success": False,
            "code": error_code,
            "message": error_message
        }

        # Add details if provided
        if details:
            error_data["details"] = details

        error = {
            "type": "error",
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "data": error_data
        }
        await self.websocket.send_text(json.dumps(error))

    async def _send_rate_limit_error(self, reason: str):
        """Send rate limit error message with grace period info"""
        # Get detailed rate limit status
        rate_limit_status = await comprehensive_rate_limiter.get_identifier_status(self.agent_id)

        # Build detailed error response
        details = {
            "reason": reason,
            "retry_after": 1.0,  # Suggest 1 second backoff
            "active_connections": rate_limit_status.get("active_connections", 0),
            "is_blocked": rate_limit_status.get("is_blocked", False)
        }

        # Add grace period info if available
        grace_period_info = rate_limit_status.get("grace_period", {})
        if grace_period_info:
            details["grace_period"] = {
                "violations": grace_period_info.get("violations", 0),
                "max_violations": grace_period_info.get("max_violations", 3),
                "remaining_violations": grace_period_info.get("remaining_violations", 0),
                "will_reset_in": grace_period_info.get("will_reset_in", 0)
            }

        # Add remaining limits info
        remaining_limits = rate_limit_status.get("remaining_limits", {})
        if remaining_limits:
            details["remaining_limits"] = remaining_limits

        error = {
            "type": "rate_limit_error",
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "data": {
                "type": "error",
                "success": False,
                "code": ERROR_CODE_RATE_LIMIT,
                "message": f"Rate limit exceeded: {reason}",
                "details": details
            }
        }
        await self.websocket.send_text(json.dumps(error))

    def _validate_origin(self) -> bool:
        """
        Validate WebSocket origin for security

        Returns:
            bool: True if origin is allowed, False otherwise
        """
        try:
            # Get origin info for logging
            origin_info = get_websocket_origin_info(self.websocket)
            logger.debug(f"Agent {self.agent_id} connection from: {origin_info}")

            # For LLM agents, allow null origins (non-browser clients)
            # but validate against allowed origins if present
            is_valid = validate_websocket_origin(
                self.websocket,
                settings.allowed_origins,
                strict_mode=False  # Allow null origins for LLM agents
            )

            if not is_valid:
                logger.warning(
                    f"Rejected agent {self.agent_id} connection from unauthorized origin: "
                    f"{origin_info.get('origin', 'null')}"
                )

            return is_valid

        except Exception as e:
            logger.error(f"Error validating origin for agent {self.agent_id}: {e}")
            return False



# WebSocket route registration
def register_websocket_routes(app: FastAPI):
    """Register WebSocket routes with the FastAPI app"""

    @app.websocket("/ws/agent/{agent_id}")
    async def agent_websocket_endpoint(websocket: WebSocket, agent_id: str):
        """WebSocket endpoint for LLM agents"""
        handler = AgentWebSocketHandler(websocket, agent_id)
        await handler.handle_connection()

    logger.info("WebSocket routes registered")
