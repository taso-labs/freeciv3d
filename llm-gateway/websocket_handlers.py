#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WebSocket handlers for LLM Gateway
"""

import asyncio
import json
import logging
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
        WEBSOCKET_PING_INTERVAL, WEBSOCKET_PING_TIMEOUT, WEBSOCKET_CLOSE_TIMEOUT
    )
except ImportError:
    from connection_manager import connection_manager
    from config import settings
    from utils.origin_validator import validate_websocket_origin, get_websocket_origin_info, create_origin_rejection_response
    from utils.rate_limiter import comprehensive_rate_limiter
    from utils.constants import (
        MAX_MESSAGE_SIZE_BYTES, ERROR_CODE_VALIDATION, ERROR_CODE_RATE_LIMIT,
        ERROR_CODE_NOT_AUTHENTICATED, ERROR_CODE_CONNECTION_LOST, ERROR_CODE_UNKNOWN,
        WEBSOCKET_PING_INTERVAL, WEBSOCKET_PING_TIMEOUT, WEBSOCKET_CLOSE_TIMEOUT
    )


# Gateway will be injected by main.py to avoid circular imports
gateway = None

logger = logging.getLogger("llm-gateway")


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
            # Cleanup proxy connection
            if self.proxy_connection:
                await self.proxy_connection.close()
                self.proxy_connection = None

            # Cleanup connection manager
            if self.connection_id:
                await connection_manager.handle_disconnect(self.connection_id)

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

        if message_type == "llm_connect":
            # First message - establish proxy connection and forward
            await self._connect_to_proxy_and_forward(message)
        elif self.authenticated and self.proxy_connection:
            # All other messages - forward directly to proxy
            await self._forward_to_proxy(message)
        elif message_type == "ping":
            # Handle pings locally for connection health
            await self._handle_ping(message)
        else:
            # Not authenticated or not connected
            await self._send_error(
                "Not authenticated - please send llm_connect message first",
                error_code=ERROR_CODE_NOT_AUTHENTICATED,
                details={
                    "authenticated": self.authenticated,
                    "proxy_connected": self.proxy_connection is not None,
                    "can_retry": True
                }
            )

    async def _connect_to_proxy_and_forward(self, message: Dict[str, Any]):
        """Connect to proxy LLM handler and forward the connect message"""
        try:
            # Connect to the freeciv-proxy LLM handler endpoint
            proxy_url = f"ws://{settings.freeciv_proxy_host}:{settings.freeciv_proxy_port}{settings.freeciv_proxy_ws_path}"
            logger.info(f"Connecting agent {self.agent_id} to proxy: {proxy_url}")

            # Set max_size to 100MB to handle large FreeCiv game state packets
            # FreeCiv sends packets with map data, player info, city data that exceed the default 1MB limit
            # This prevents "frame exceeds limit of 1048576 bytes" errors (close code 1009)
            # Add ping/timeout parameters to detect and close dead connections
            self.proxy_connection = await websockets.connect(
                proxy_url,
                max_size=100 * 1024 * 1024,  # 100MB for large game state packets
                max_queue=64,  # Increase queue size to handle multiple large frames
                ping_interval=WEBSOCKET_PING_INTERVAL,  # Ping every 20s to detect dead connections
                ping_timeout=WEBSOCKET_PING_TIMEOUT,  # Wait up to 10s for pong response
                close_timeout=WEBSOCKET_CLOSE_TIMEOUT  # Timeout for graceful close
            )
            logger.info(f"Connected to proxy for agent {self.agent_id} (max_size=100MB, ping_interval={WEBSOCKET_PING_INTERVAL}s)")

            # Start listening for proxy messages in background
            asyncio.create_task(self._listen_to_proxy())

            # Transform message format: flatten 'data' fields to top level for proxy
            proxy_message = self._transform_to_proxy_format(message)

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
                    proxy_message = await self.proxy_connection.recv()
                    logger.info(f"📥 Gateway received from proxy for agent {self.agent_id}: {proxy_message[:200]}")

                    # Transform proxy messages to agent format
                    try:
                        msg_data = json.loads(proxy_message)

                        # Handle both single objects and arrays of packets from FreeCiv protocol
                        if isinstance(msg_data, list):
                            # Check for PACKET_CONN_PING (pid:88) and transform it
                            # Civserver sends pings as raw packets, but agents expect {"type": "conn_ping"}
                            has_ping = any(packet.get("pid") == 88 for packet in msg_data if isinstance(packet, dict))

                            if has_ping:
                                logger.info(f"🏓 PING: Detected pid:88 in packet array for agent {self.agent_id} - sending transformed conn_ping")
                                # Send transformed ping message that agent can handle
                                ping_message = {"type": "conn_ping"}
                                await self.websocket.send_text(json.dumps(ping_message))
                                # Also forward raw packets for compatibility with other packet handlers
                                await self.websocket.send_text(proxy_message)
                                logger.debug(f"📤 Forwarded both conn_ping and raw packets to agent {self.agent_id}")
                                continue

                            # Raw FreeCiv packet array (no ping) - forward as-is
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
                            if self.player_id is not None:
                                await connection_manager.update_agent_auth(
                                    self.agent_id,
                                    self.player_id,
                                    game_id
                                )

                            logger.info(
                                f"🔑 Transforming auth_success for agent {self.agent_id}:\n"
                                f"   Player ID: {self.player_id}\n"
                                f"   Status: {msg_data.get('status', 'N/A')}"
                            )
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
                            logger.error(
                                f"❌ Error from proxy for agent {self.agent_id}:\n"
                                f"   Code: {msg_data.get('code')}\n"
                                f"   Message: {msg_data.get('message')}\n"
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
                        # Handle conn_ping - critical for keepalive
                        elif msg_type == "conn_ping":
                            logger.info(f"🏓 PING: Received conn_ping from proxy for agent {self.agent_id} - forwarding to agent")
                            # Forward as-is (no transformation needed)
                            # Agent must respond with conn_pong to keep connection alive
                        # Handle conn_pong - should not come from proxy, but log if it does
                        elif msg_type == "conn_pong":
                            logger.warning(f"🏓 PONG: Unexpected conn_pong from proxy for agent {self.agent_id} (pongs should come from agent)")
                        # Handle game_ready - important initialization signal
                        elif msg_type == "game_ready":
                            logger.info(f"🎮 GAME_READY: Received game_ready signal for agent {self.agent_id} - forwarding to agent")
                            # Forward as-is
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

    async def _forward_to_proxy(self, message: Dict[str, Any]):
        """Forward message from agent to proxy"""
        try:
            if self.proxy_connection:
                msg_type = message.get("type")

                # Add diagnostic logging for critical message types
                if msg_type == "conn_pong":
                    logger.info(f"🏓 PONG: Agent {self.agent_id} responding to ping - forwarding conn_pong to proxy")
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

                # Transform message format for proxy
                proxy_message = self._transform_to_proxy_format(message)
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
            # Proxy expects: type, agent_id, api_token, port (optional), nation (optional), leader_name (optional), game_id (optional)
            allowed_fields = {"type", "agent_id", "api_token", "port", "nation", "leader_name", "game_id"}
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
            # game_arena sends action_submit, transform to "action" for proxy
            # game_arena format: {type: "action_submit", action: "canonical_string", agent_id: "...", timestamp: ...}
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
            # game_arena sends: {type: "action", agent_id: "...", data: {...}}
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
