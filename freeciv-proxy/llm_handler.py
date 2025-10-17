#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM WebSocket Handler for FreeCiv proxy
Handles headless LLM agent connections without browser requirements
"""

import json
import logging
import time
import uuid
import asyncio
import socket
from tornado import websocket
from civcom import CivCom
from state_cache import state_cache
from state_extractor import StateExtractor, StateFormat, civcom_registry
from action_validator import LLMActionValidator, ActionType, ValidationResult
from config_loader import llm_config
from message_validator import MessageValidator, ValidationError
from security import InputSanitizer, SecurityError, SecurityLogger
from rate_limiter import DistributedRateLimiter
from session_manager import session_manager, SessionState
from error_handler import error_handler, ErrorSeverity, ErrorCategory
from game_session_manager import game_session_manager
from typing import Dict, Any, Optional, List

logger = logging.getLogger("freeciv-proxy")

# Add file handler for persistent debug logging
import os
try:
    debug_log_path = "/docker/logs/llm-handler-debug.log"
    os.makedirs(os.path.dirname(debug_log_path), exist_ok=True)
    file_handler = logging.FileHandler(debug_log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(file_handler)
    logger.info("=" * 80)
    logger.info("LLM Handler debug logging initialized")
    logger.info("=" * 80)
except Exception as e:
    print(f"WARNING: Could not initialize file logging: {e}", flush=True)

# Global registry for active LLM agents
llm_agents = {}
MAX_LLM_AGENTS = llm_config.get_max_agents()

# Nation ID mapping for common civilizations
# These IDs correspond to the FreeCiv nation definitions
NATION_MAP = {
    "Americans": 0,
    "Romans": 1,
    "Chinese": 2,
    "French": 3,
    "Germans": 4,
    "British": 5,
    "Japanese": 6,
    "Indians": 7,
    "Russians": 8,
    "Spanish": 9
}
DEFAULT_NATIONS = ["Americans", "Romans", "Chinese", "French", "Germans"]

# Global distributed rate limiter
distributed_rate_limiter = DistributedRateLimiter({
    'host': llm_config.get('redis.host', 'localhost'),
    'port': llm_config.get('redis.port', 6379),
    'password': llm_config.get('redis.password'),
    'db': llm_config.get('redis.db', 0)
})

class LLMWSHandler(websocket.WebSocketHandler):
    """
    WebSocket handler for LLM agents
    Bypasses browser authentication and provides optimized game state access

    NOTE: WebSocket max message size is configured at the Application level in freeciv-proxy.py
    (websocket_max_message_size=50MB) to handle large FreeCiv game state packets.
    """

    def __init__(self, application, request, **kwargs):
        super().__init__(application, request, **kwargs)

        # NOTE: IOStream buffer size configuration moved to open() method
        # At __init__ time, self.request.connection.stream is the HTTP request stream (pre-upgrade)
        # The actual WebSocket stream (self.ws_connection.stream) only exists after open() is called

        self.id = str(uuid.uuid4())
        self.is_llm_agent = False
        self.agent_id = None
        self.player_id = None
        self.civcom = None
        self.game_id = None
        self.capabilities = []
        self.last_state_query = 0
        self.action_validator = None
        self.connection_time = time.time()
        # Session management
        self.session_id = None
        self.session_info = None
        # Legacy fields (kept for backward compatibility)
        self.rate_limit_tokens = 100
        self.last_token_refill = time.time()

        # CRITICAL FIX: Add io_loop attribute for CivCom compatibility
        # CivCom uses conn.io_loop.add_callback() to send packets safely across threads
        # This must be the IOLoop instance that's handling this connection
        from tornado import ioloop
        self.io_loop = ioloop.IOLoop.current()

        # Initialize message validator with configurable size limit
        max_size_mb = llm_config.get('validation.max_message_size_mb', 1.0)
        self.message_validator = MessageValidator(max_message_size=int(max_size_mb * 1024 * 1024))

        # Initialize state extractor for proper state formatting
        self.state_extractor = StateExtractor()

    def open(self):
        """Handle WebSocket connection opening"""
        logger.info(f"LLM agent connection opened: {self.id}")
        self.set_nodelay(True)

        # CRITICAL FIX: Configure IOStream buffer sizes for large FreeCiv packets
        # Must be done in open() where ws_connection exists, NOT in __init__
        # FreeCiv sends large game state packets (>1MB) that need both:
        # 1. max_buffer_size - for READING incoming frames
        # 2. max_write_buffer_size - for WRITING outgoing frames to gateway
        if hasattr(self, 'ws_connection') and self.ws_connection and hasattr(self.ws_connection, 'stream'):
            self.ws_connection.stream.max_buffer_size = 100 * 1024 * 1024  # 100MB read buffer
            self.ws_connection.stream.max_write_buffer_size = 100 * 1024 * 1024  # 100MB write buffer
            logger.info(
                f"✓ IOStream buffers configured for {self.id}: "
                f"read={100}MB, write={100}MB"
            )
        else:
            logger.warning(
                f"⚠️ Could not configure IOStream buffers for {self.id}: "
                f"ws_connection={hasattr(self, 'ws_connection')}, "
                f"stream={hasattr(self.ws_connection, 'stream') if hasattr(self, 'ws_connection') and self.ws_connection else 'N/A'}"
            )

        # Check agent capacity
        if len(llm_agents) >= MAX_LLM_AGENTS:
            logger.warning(f"Maximum LLM agents ({MAX_LLM_AGENTS}) already connected")
            error_response = error_handler.handle_capacity_error(
                "LLM agents", len(llm_agents), MAX_LLM_AGENTS
            )
            self.write_message(error_response.to_json())
            self.close()
            return

        # Send welcome message
        logger.debug(f"Sending welcome message to {self.id}")
        self.write_message(json.dumps({
            'type': 'welcome',
            'handler_id': self.id,
            'message': 'LLM agent handler ready. Send llm_connect message to authenticate.'
        }))

    async def on_message(self, message):
        """Handle incoming WebSocket messages

        CRITICAL: This handler is async to properly support Tornado's async WebSocket pattern.
        Tornado 4.5+ allows on_message to be a coroutine, which keeps the connection alive
        until all async operations complete. This fixes the premature connection closure issue.
        """
        logger.debug(f"Received message from {self.agent_id or self.id}: {message[:200]}")
        try:
            # Session validation for authenticated agents
            if self.session_id and not self._validate_session():
                self.write_message(json.dumps({
                    'type': 'error',
                    'code': 'E102',
                    'message': 'Session expired or invalid',
                    'requires_reconnect': True
                }))
                self.close()
                return

            # Cleanup expired sessions periodically
            session_manager.cleanup_expired_sessions()

            # Distributed rate limiting by agent ID
            if self.agent_id and not distributed_rate_limiter.check_limit(self.agent_id, 'message'):
                error_response = error_handler.handle_rate_limit_error(
                    self.agent_id, 'message', 60
                )
                self.write_message(error_response.to_json())
                return

            # Check burst rate limit as well
            if self.agent_id and not distributed_rate_limiter.check_burst_limit(self.agent_id):
                error_response = error_handler.handle_rate_limit_error(
                    self.agent_id, 'burst', 60
                )
                self.write_message(error_response.to_json())
                return

            # Validate and parse message
            try:
                msg_data = self.message_validator.validate_message(message)
            except ValidationError as e:
                error_response = error_handler.handle_validation_error(
                    self.agent_id or "unknown", e.error_code, e.message,
                    self.session_id, message
                )
                self.write_message(error_response.to_json())
                return

            # Route message based on type
            msg_type = msg_data.get('type', '')

            if msg_type == 'llm_connect':
                await self._handle_llm_connect(msg_data)
            elif msg_type == 'state_query':
                self._handle_state_query(msg_data)
            elif msg_type == 'action':
                self._handle_action(msg_data)
            elif msg_type == 'ping':
                self._handle_ping(msg_data)
            elif msg_type == 'player_ready':
                self._handle_player_ready(msg_data)
            elif self.is_llm_agent:
                # Forward other messages to civcom if authenticated
                self._forward_to_civcom(message)
            else:
                self.write_message(json.dumps({
                    'type': 'error',
                    'code': 'E103',
                    'message': 'Unknown message type or not authenticated'
                }))

        except Exception as e:
            error_response = error_handler.handle_system_error(
                "message_handling", e, self.agent_id, self.session_id
            )
            self.write_message(error_response.to_json())

        # INVESTIGATION: Log when on_message completes
        try:
            ws_closed = self.ws_connection.stream.closed() if hasattr(self, 'ws_connection') and hasattr(self.ws_connection, 'stream') else 'NO_STREAM'
            logger.debug(
                f"✅ on_message COMPLETED for {self.agent_id}: "
                f"ws_closed={ws_closed}"
            )
        except Exception as log_err:
            logger.error(f"Error logging on_message completion: {log_err}")

    async def _handle_llm_connect(self, msg_data: Dict[str, Any]):
        """Handle LLM agent authentication with session management

        CRITICAL: This handler is async and directly awaits player_id assignment.
        The handler blocks until auth_success is sent, keeping the WebSocket connection
        alive. This replaces the previous pattern of spawning a detached async task.
        """
        logger.debug(f"_handle_llm_connect called for {self.id}")
        try:
            # Extract agent info
            self.agent_id = msg_data.get('agent_id', f'agent-{self.id[:8]}')
            api_token = msg_data.get('api_token', '')
            requested_capabilities = msg_data.get('capabilities', [])

            # Token validation using config
            if not llm_config.validate_token(api_token):
                error_response = error_handler.handle_authentication_error(
                    self.agent_id, "Invalid API token"
                )
                self.write_message(error_response.to_json())
                return

            # Set up capabilities
            capability_set = {cap for cap in requested_capabilities
                            if cap in [t.value for t in ActionType]}

            if not capability_set:
                capability_set = {cap.value for cap in LLMActionValidator.DEFAULT_CAPABILITIES}

            # Create session
            self.session_info = session_manager.create_session(
                self.agent_id,
                api_token,
                capability_set
            )

            if not self.session_info:
                error_response = error_handler.handle_authentication_error(
                    self.agent_id, "Failed to create session - server capacity exceeded"
                )
                self.write_message(error_response.to_json())
                return

            self.session_id = self.session_info.session_id

            # Set up capabilities for action validator
            self.capabilities = [ActionType(cap) for cap in capability_set]
            self.action_validator = LLMActionValidator(self.capabilities)

            # Register agent first (needed for player_id calculation)
            llm_agents[self.agent_id] = self
            self.is_llm_agent = True

            # CRITICAL FIX: Get game_id FIRST, then allocate/lookup civserver port
            # This ensures both players in the same game connect to the SAME multiplayer server
            # LLM Gateway flattens nested 'data' field to top level before sending to proxy
            game_id = msg_data.get('game_id', f'game_{uuid.uuid4().hex[:8]}')
            self.game_id = game_id

            # Allocate a multiplayer civserver port (6001-6009) for this game_id
            # First player: allocates new port (e.g., 6001)
            # Second player: reuses the same port (6001)
            # Multiplayer servers use pubscript_multiplayer.serv with aifill=2 (AI*1, AI*2)
            civserver_port = await game_session_manager.allocate_civserver_port(game_id)
            logger.info(
                f"Agent {self.agent_id} assigned to multiplayer server:\n"
                f"   Game ID: {game_id}\n"
                f"   Civserver Port: {civserver_port} (multiplayer, aifill=2)\n"
                f"   This server has exactly 2 AI players (AI*1, AI*2) for /take commands"
            )

            # Connect to civserver
            logger.info(f"🔌 Connecting agent {self.agent_id} to civserver port {civserver_port} (game: {game_id})")
            try:
                self._connect_to_civserver(civserver_port, game_id)
                logger.info(f"✓ Agent {self.agent_id} civcom connection established to port {civserver_port}")
            except Exception as e:
                logger.error(
                    f"❌ Agent {self.agent_id}: failed to establish civserver connection: {e}\n"
                    f"   Port: {civserver_port}\n"
                    f"   Game ID: {game_id}"
                )
                # Registration failed; cleanup and abort authentication response
                if self.session_id:
                    session_manager.terminate_session(self.session_id, "civserver_connection_failed")
                    self.session_id = None
                if self.agent_id in llm_agents:
                    del llm_agents[self.agent_id]
                self.is_llm_agent = False
                return

            # CRITICAL FIX: Self-assign player_id (restores pre-GameSessionManager behavior)
            # The original working implementation assigned player_id client-side
            # and told civserver "I am player X" via nation selection packet
            # This avoids the timeout issue with waiting for server-side assignment
            logger.info(
                f"⏳ Starting player registration and nation selection for {self.agent_id}\n"
                f"   Session ID: {self.session_id}\n"
                f"   Game ID: {game_id}\n"
                f"   Capabilities: {list(capability_set)}"
            )

            try:
                # Register with game session manager for coordination
                game_session = await game_session_manager.get_or_create_session(game_id, civserver_port, min_players=2)
                logger.debug(f"Got game session for {game_id}")

                # CRITICAL FIX: Use /take command to control AI player (proper FreeCiv protocol)
                # This replaces self-assignment with server-validated player_id
                # Step 1: Wait for PACKET_CONN_INFO from server (assigns observer status player_num=512)
                logger.info(f"⏳ Waiting for PACKET_CONN_INFO for {self.agent_id}...")
                waited = 0.0
                max_wait = 3.0
                while (not hasattr(self.civcom, 'player_id') or self.civcom.player_id is None) and waited < max_wait:
                    await asyncio.sleep(0.2)
                    waited += 0.2
                    logger.debug(f"   Waited {waited:.1f}s for PACKET_CONN_INFO...")

                if not hasattr(self.civcom, 'player_id') or self.civcom.player_id is None:
                    logger.error(f"❌ Failed to receive PACKET_CONN_INFO from server after {max_wait}s")
                    raise RuntimeError(f"Failed to receive PACKET_CONN_INFO - civserver not responding")

                logger.info(f"✅ Received PACKET_CONN_INFO: {self.agent_id} → player_num={self.civcom.player_id}")

                # Step 2: Send /take command to control an AI player
                # AI slots are AI*1, AI*2, ... created by aifill setting
                # CRITICAL: Use a unique identifier per agent to avoid race conditions
                # Generate ai_slot based on agent_id hash to ensure uniqueness
                import hashlib
                agent_hash = int(hashlib.md5(self.agent_id.encode()).hexdigest(), 16)
                ai_slot_index = agent_hash % 2  # 0 or 1 for 2-player games
                ai_slot = ai_slot_index + 1  # AI slots are 1-indexed: AI*1, AI*2

                # Alternative: Use incrementing slot per game session
                # Add to game_session to track next available slot
                if not hasattr(game_session, '_next_ai_slot'):
                    game_session._next_ai_slot = 1
                ai_slot = game_session._next_ai_slot
                game_session._next_ai_slot += 1

                take_command = f"/take \"AI*{ai_slot}\""  # Quote the name to avoid ambiguity
                logger.info(f"📤 Sending {take_command} for {self.agent_id} (slot {ai_slot})")
                self.civcom.queue_to_civserver(json.dumps({"pid": 26, "message": take_command}))
                self.civcom.send_packets_to_civserver()

                # Step 3: Wait for /take to complete and server to update player_id
                # Server sends PACKET_CONN_INFO again with the new player_id after /take succeeds
                logger.info(f"⏳ Waiting for /take to complete...")
                await asyncio.sleep(1.5)  # Allow time for server to process /take and send update

                # Step 4: Get the assigned player_id from civcom (updated after /take)
                self.player_id = self.civcom.player_id
                if self.player_id is None or self.player_id >= 512:
                    logger.error(
                        f"❌ /take failed for {self.agent_id}:\n"
                        f"   Still observer (player_id={self.player_id})\n"
                        f"   AI slot requested: AI*{ai_slot}\n"
                        f"   This usually means AI player doesn't exist or is already taken"
                    )
                    raise RuntimeError(f"/take AI*{ai_slot} failed - player_id={self.player_id} (expected < 512)")

                self.session_info.player_id = self.player_id
                logger.info(f"✅ {self.agent_id} successfully took AI*{ai_slot} → player_id={self.player_id}")

                # Step 5: Register player with game session using server-assigned player_id
                game_session.add_player(self.agent_id, self.player_id, self)
                logger.info(f"Registered agent {self.agent_id} with game session {game_id} (server-assigned player_id={self.player_id})")

                # Get nation preference from message or use default
                nation_name = msg_data.get('nation', 'random')
                leader_name = msg_data.get('leader_name', self.agent_id)
                nation_id = self._get_nation_id(nation_name)
                if nation_id is None:
                    logger.error(f"Failed to find nation '{nation_name}' for {self.agent_id}")
                    return

                # Wait briefly for connection to stabilize
                await asyncio.sleep(0.5)

                # Send PACKET_NATION_SELECT_REQ immediately with self-assigned player_id
                logger.debug(f"Sending PACKET_NATION_SELECT_REQ for {self.agent_id}: nation={nation_name} (id={nation_id})")
                nation_packet = json.dumps({
                    "pid": 10,  # PACKET_NATION_SELECT_REQ from packets.def:426
                    "player_no": self.player_id,
                    "nation_no": nation_id,
                    "is_male": True,
                    "name": leader_name,
                    "style": 0
                })
                self.civcom.queue_to_civserver(nation_packet)
                logger.info(f"Sent PACKET_NATION_SELECT_REQ for {nation_name} (player_id={self.player_id}) - Leader: {leader_name}")

                # Mark nation selected in game session
                game_session.mark_nation_selected(self.agent_id)

                # Wait briefly for nation selection to process
                await asyncio.sleep(0.5)

                # Send PACKET_PLAYER_READY immediately after nation selection
                logger.info(
                    f"✅ Nation selected for {self.agent_id} - sending PACKET_PLAYER_READY\n"
                    f"   Player ID: {self.player_id}"
                )

                ready_packet = {
                    "pid": 11,  # PACKET_PLAYER_READY from packets.def:434
                    "player_no": self.player_id,
                    "is_ready": True
                }

                # Send PACKET_PLAYER_READY to civserver
                self.civcom.queue_to_civserver(json.dumps(ready_packet))
                self.civcom.send_packets_to_civserver()

                # Mark player as ready in game session (triggers game start when all ready)
                game_session.mark_player_ready(self.agent_id)

                logger.info(f"📤 PACKET_PLAYER_READY sent for {self.agent_id} (player_no={self.player_id})")

                # Send auth_success immediately - don't wait for server confirmation!
                # This restores the original working behavior
                self.write_message(json.dumps({
                    'type': 'auth_success',
                    'agent_id': self.agent_id,
                    'session_id': self.session_id,
                    'player_id': self.player_id,
                    'capabilities': list(capability_set),
                    'session_expires_in': int(self.session_info.expires_at - time.time()),
                    'message': 'LLM agent authenticated successfully',
                    'status': 'authenticated',
                    'game_ready': False  # Game state not yet fully initialized
                }))
                logger.info(f"📤 Sent auth_success with player_id={self.player_id} to agent {self.agent_id}")

            except Exception as e:
                logger.exception(f"Error in player registration and nation selection: {e}")
                self.write_message(json.dumps({
                    'type': 'error',
                    'code': 'E142',
                    'message': 'Failed during player registration or nation selection'
                }))
                return

            SecurityLogger.log_authentication_attempt(self.agent_id, True)
            SecurityLogger.log_connection_event(self.agent_id, "AUTHENTICATED",
                                              f"player_id={self.player_id}, session_id={self.session_id}")
            logger.info(f"LLM agent authenticated: {self.agent_id} (player {self.player_id}, session {self.session_id})")

            # INVESTIGATION: Log WebSocket state after authentication completes
            try:
                ws_closed = self.ws_connection.stream.closed() if hasattr(self, 'ws_connection') and hasattr(self.ws_connection, 'stream') else 'NO_STREAM'
                logger.warning(
                    f"🔍 WEBSOCKET STATE after authentication for {self.agent_id}:\n"
                    f"   ws_connection exists: {hasattr(self, 'ws_connection')}\n"
                    f"   stream closed: {ws_closed}\n"
                    f"   civcom alive: {self.civcom.is_alive() if self.civcom else 'NO_CIVCOM'}\n"
                    f"   civcom stopped: {self.civcom.stopped if self.civcom else 'NO_CIVCOM'}"
                )
            except Exception as log_err:
                logger.error(f"Error logging WebSocket state: {log_err}")

        except Exception as e:
            error_response = error_handler.handle_system_error(
                "authentication", e, self.agent_id, self.session_id
            )
            self.write_message(error_response.to_json())

    def _handle_state_query(self, msg_data: Dict[str, Any]):
        """Handle optimized state query for LLM"""
        logger.info(f"🔍 STATE_QUERY received from agent {self.agent_id}")

        if not self.is_llm_agent:
            logger.warning(f"❌ Agent {self.agent_id} not authenticated for state_query")
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E120',
                'message': 'Not authenticated as LLM agent'
            }))
            return

        # Update session activity
        if self.session_id:
            session_manager.update_session_activity(self.session_id)

        # Check if player_id is assigned
        if self.player_id is None:
            logger.error(
                f"❌ STATE_QUERY FAILED for {self.agent_id}: player_id is None\n"
                f"   Civcom exists: {self.civcom is not None}\n"
                f"   Game ID: {self.game_id}\n"
                f"   Session ID: {self.session_id}\n"
                f"   This means the civserver hasn't assigned a player slot yet or connection failed"
            )
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E122',
                'message': 'Player not assigned yet - game not ready. Wait for authentication to complete.',
                'details': {
                    'agent_id': self.agent_id,
                    'game_id': self.game_id,
                    'civcom_connected': self.civcom is not None,
                    'suggestion': 'Retry after receiving auth_success with valid player_id'
                }
            }))
            return

        # Check if civcom is connected
        if not self.civcom or self.civcom.stopped:
            logger.error(
                f"❌ STATE_QUERY FAILED for {self.agent_id}: civcom not connected\n"
                f"   Player ID: {self.player_id}\n"
                f"   Civcom stopped: {self.civcom.stopped if self.civcom else 'N/A'}"
            )
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E123',
                'message': 'Connection to game server lost',
                'details': {
                    'agent_id': self.agent_id,
                    'player_id': self.player_id,
                    'suggestion': 'Reconnect to game server'
                }
            }))
            return

        try:
            query_format = msg_data.get('format', 'llm_optimized')
            include_actions = msg_data.get('include_actions', True)

            logger.info(
                f"📊 Building state for agent {self.agent_id}:\n"
                f"   Player ID: {self.player_id}\n"
                f"   Format: {query_format}\n"
                f"   Include actions: {include_actions}\n"
                f"   Game ID: {self.game_id}"
            )

            # Generate cache key with session info for security
            cache_key = f"state_{self.player_id}_{query_format}_{int(time.time() // 5)}"  # 5-second granularity

            # Try cache first
            cached_state = state_cache.get(cache_key)
            if cached_state:
                logger.debug(f"✓ Cache hit for agent {self.agent_id}")
                self.write_message(json.dumps({
                    'type': 'state_response',
                    'format': query_format,
                    'data': cached_state,
                    'cached': True,
                    'session_id': self.session_id,
                    'timestamp': time.time()
                }))
                return

            # Generate fresh state
            logger.debug(f"⚙️ Generating fresh state for agent {self.agent_id}")
            state_data = self._build_optimized_state(query_format, include_actions)

            logger.info(
                f"✓ STATE_QUERY SUCCESS for agent {self.agent_id}:\n"
                f"   Turn: {state_data.get('turn', 'N/A')}\n"
                f"   Phase: {state_data.get('phase', 'N/A')}\n"
                f"   Units: {len(state_data.get('units', []))}\n"
                f"   Cities: {len(state_data.get('cities', []))}\n"
                f"   Players: {len(state_data.get('players', []))}\n"
                f"   Legal actions: {len(state_data.get('legal_actions', []))}\n"
                f"   State keys: {list(state_data.keys())}"
            )

            # Cache the result
            state_cache.set(cache_key, state_data, self.player_id)

            # Send response
            self.write_message(json.dumps({
                'type': 'state_response',
                'format': query_format,
                'data': state_data,
                'cached': False,
                'timestamp': time.time()
            }))

            self.last_state_query = time.time()

        except Exception as e:
            logger.exception(
                f"❌ STATE_QUERY EXCEPTION for agent {self.agent_id}:\n"
                f"   Player ID: {self.player_id}\n"
                f"   Game ID: {self.game_id}\n"
                f"   Error: {e}"
            )
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E121',
                'message': f'State query failed: {str(e)}',
                'details': {
                    'agent_id': self.agent_id,
                    'player_id': self.player_id,
                    'error': str(e)
                }
            }))

    def _normalize_game_arena_action(self, action_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize game_arena action format to proxy format.

        game_arena sends:
            {"action_type": "tech_research", "actor_id": 1, "target": {"value": "Alphabet"}}

        Proxy expects:
            {"type": "tech_research", "tech_name": "alphabet", "player_id": 1}

        Args:
            action_data: game_arena format action dict

        Returns:
            Normalized action dict for validation

        Raises:
            ValueError: If action format cannot be normalized
        """
        action_type = action_data.get("action_type")
        if not action_type:
            raise ValueError("Missing action_type field")

        logger.debug(f"Normalizing game_arena action: {action_type}")

        # Build normalized action
        normalized = {"type": action_type}

        # Map actor_id to player_id if present
        if "actor_id" in action_data:
            normalized["player_id"] = action_data["actor_id"]

        # Action-specific field mappings
        if action_type == "tech_research":
            # Extract tech name from target field
            target = action_data.get("target", {})
            if isinstance(target, dict) and "value" in target:
                tech_name = target["value"]
            elif isinstance(target, str):
                tech_name = target
            else:
                raise ValueError(f"Cannot extract tech_name from target: {target}")

            # Normalize to lowercase
            normalized["tech_name"] = str(tech_name).lower()
            logger.info(f"Normalized tech_research: target={target} → tech_name={normalized['tech_name']}")

        elif action_type == "unit_move":
            # Extract unit_id and destination
            if "unit_id" in action_data:
                normalized["unit_id"] = action_data["unit_id"]

            target = action_data.get("target", {})
            if isinstance(target, dict):
                if "x" in target and "y" in target:
                    normalized["dest_x"] = target["x"]
                    normalized["dest_y"] = target["y"]
                elif "dest_x" in target and "dest_y" in target:
                    normalized["dest_x"] = target["dest_x"]
                    normalized["dest_y"] = target["dest_y"]

            # Also check for direct dest_x/dest_y fields
            if "dest_x" in action_data:
                normalized["dest_x"] = action_data["dest_x"]
            if "dest_y" in action_data:
                normalized["dest_y"] = action_data["dest_y"]

        elif action_type == "city_production":
            # Extract city_id and production type
            if "city_id" in action_data:
                normalized["city_id"] = action_data["city_id"]

            target = action_data.get("target", {})
            if isinstance(target, dict) and "value" in target:
                production = target["value"]
            elif isinstance(target, str):
                production = target
            else:
                production = action_data.get("production_type", "")

            normalized["production_type"] = str(production).lower()

        elif action_type == "unit_build_city":
            # Extract unit_id
            if "unit_id" in action_data:
                normalized["unit_id"] = action_data["unit_id"]

        # Copy any parameters field
        if "parameters" in action_data:
            for key, value in action_data["parameters"].items():
                if key not in normalized:
                    normalized[key] = value

        return normalized

    def _parse_canonical_action(self, action_str: str) -> Dict[str, Any]:
        """Parse game_arena canonical format strings to JSON objects.

        Canonical format: "action_type_param1(value1)_param2(value2)..."

        Examples:
            "tech_research_player(1)_target(Alphabet)"
            → {type: "tech_research", tech_name: "alphabet", player_id: 1}

            "unit_move_unit_id(42)_dest_x(10)_dest_y(20)"
            → {type: "unit_move", unit_id: 42, dest_x: 10, dest_y: 20}

        Args:
            action_str: Canonical format action string

        Returns:
            Dict with normalized action structure for validation

        Raises:
            ValueError: If action format cannot be parsed
        """
        import re

        logger.debug(f"Parsing canonical action: {action_str}")

        # Extract action type (everything before first parameter or end of string)
        # Match pattern: word characters up to first opening parenthesis or underscore followed by param
        match = re.match(r'^([a-z_]+?)(?:_[a-z_]+\(|$)', action_str)
        if not match:
            raise ValueError(f"Cannot parse action type from: {action_str}")

        action_type = match.group(1)
        logger.debug(f"Extracted action type: {action_type}")

        # Extract all key-value pairs: param(value)
        params = {}
        for match in re.finditer(r'(\w+)\(([^)]+)\)', action_str):
            key, value = match.groups()
            # Try to convert to int if possible
            try:
                params[key] = int(value)
            except ValueError:
                params[key] = value

        logger.debug(f"Extracted params: {params}")

        # Map to proxy-expected format
        result = {"type": action_type}

        # Action-specific field mappings
        if action_type == "tech_research":
            # target → tech_name, lowercase
            if "target" in params:
                result["tech_name"] = str(params["target"]).lower()
            if "player" in params:
                result["player_id"] = params["player"]
            logger.info(f"Parsed tech_research: {result}")

        elif action_type == "unit_move":
            # Map unit movement fields
            if "actor_id" in params:
                result["unit_id"] = params["actor_id"]
            elif "unit_id" in params:
                result["unit_id"] = params["unit_id"]

            if "dest_x" in params:
                result["dest_x"] = params["dest_x"]
            if "dest_y" in params:
                result["dest_y"] = params["dest_y"]

            # Alternative: target as tuple (x,y)
            if "target" in params and "," in str(params["target"]):
                coords = str(params["target"]).split(",")
                result["dest_x"] = int(coords[0].strip())
                result["dest_y"] = int(coords[1].strip())

            logger.info(f"Parsed unit_move: {result}")

        elif action_type == "city_production":
            # Map city production fields
            if "actor_id" in params:
                result["city_id"] = params["actor_id"]
            elif "city_id" in params:
                result["city_id"] = params["city_id"]

            if "target" in params:
                result["production_type"] = str(params["target"]).lower()
            elif "production_type" in params:
                result["production_type"] = str(params["production_type"]).lower()

            logger.info(f"Parsed city_production: {result}")

        elif action_type == "unit_build_city":
            # Map unit build city fields
            if "actor_id" in params:
                result["unit_id"] = params["actor_id"]
            elif "unit_id" in params:
                result["unit_id"] = params["unit_id"]

            if "player" in params:
                result["player_id"] = params["player"]

            logger.info(f"Parsed unit_build_city: {result}")

        else:
            # For unknown action types, copy all params as-is
            for key, value in params.items():
                if key not in result:
                    result[key] = value

        return result

    def _handle_action(self, msg_data: Dict[str, Any]):
        """Handle and validate LLM action"""
        logger.info(f"🎯 _handle_action ENTRY: agent={self.agent_id}")
        logger.info(f"🎯 msg_data keys: {list(msg_data.keys())}")
        logger.info(f"🎯 msg_data: {msg_data}")

        if not self.is_llm_agent:
            logger.warning(f"❌ Agent {self.agent_id} not authenticated for actions")
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E130',
                'message': 'Not authenticated as LLM agent'
            }))
            return

        # Update session activity for actions
        if self.session_id:
            session_manager.update_session_activity(self.session_id)

        try:
            action_data = msg_data.get('action', {})
            logger.info(f"🎯 Extracted action_data: {action_data}")
            logger.info(f"🎯 action_data type: {type(action_data).__name__}")
            if isinstance(action_data, dict):
                logger.info(f"🎯 action_data has 'action_type': {'action_type' in action_data}")
                logger.info(f"🎯 action_data has 'type': {'type' in action_data}")

            # NEW: Handle canonical string format from game_arena
            if isinstance(action_data, str):
                logger.info(f"📝 Received canonical action string: {action_data}")
                try:
                    action_data = self._parse_canonical_action(action_data)
                    logger.info(f"✅ Parsed to: {action_data}")
                except Exception as e:
                    logger.error(f"❌ Failed to parse canonical action '{action_data}': {e}")
                    self.write_message(json.dumps({
                        'type': 'action_rejected',
                        'error_code': 'E134',
                        'error_message': f'Invalid action format: {e}. Expected canonical format like "tech_research_player(1)_target(Alphabet)" or JSON object.',
                        'action': action_data,
                        'example_formats': {
                            'canonical': 'tech_research_player(1)_target(Alphabet)',
                            'json': '{"type": "tech_research", "tech_name": "alphabet", "player_id": 1}'
                        }
                    }))
                    return

            # NEW: Handle game_arena dict format with "action_type" instead of "type"
            if isinstance(action_data, dict) and "action_type" in action_data and "type" not in action_data:
                logger.info(f"📝 NORMALIZATION TRIGGERED: game_arena format detected")
                logger.info(f"📝 Original action_data: {action_data}")
                try:
                    action_data = self._normalize_game_arena_action(action_data)
                    logger.info(f"✅ NORMALIZATION SUCCESS: {action_data}")
                    logger.info(f"✅ Normalized action has 'type': {'type' in action_data}")
                    logger.info(f"✅ Normalized action has 'tech_name': {'tech_name' in action_data if action_data.get('type') == 'tech_research' else 'N/A'}")
                except Exception as e:
                    logger.error(f"❌ Failed to normalize game_arena action: {e}")
                    self.write_message(json.dumps({
                        'type': 'action_rejected',
                        'error_code': 'E135',
                        'error_message': f'Failed to normalize action format: {e}',
                        'action': action_data
                    }))
                    return

            # Sanitize action data to prevent injection attacks
            try:
                logger.info(f"🧹 Sanitizing action_data: {action_data}")
                sanitized_action = InputSanitizer.sanitize_action_data(action_data)
                logger.info(f"✓ Sanitized action: {sanitized_action}")
            except SecurityError as e:
                SecurityLogger.log_security_violation(self.agent_id, "INPUT_SANITIZATION", str(e))
                self.write_message(json.dumps({
                    'type': 'action_rejected',
                    'error_code': 'S001',
                    'error_message': f'Input sanitization failed: {e}',
                    'action': action_data
                }))
                return

            # Add player_id to action if not present
            if 'player_id' not in sanitized_action:
                sanitized_action['player_id'] = self.player_id

            logger.info(f"🔍 Validating action: {sanitized_action}")

            # Validate action
            validation_result = self.action_validator.validate_action(
                sanitized_action, self.player_id, self._get_current_game_state()
            )

            if not validation_result.is_valid:
                # Enhanced error response with format documentation
                action_type = sanitized_action.get('type', 'unknown')
                expected_format = self._get_expected_format(action_type)

                self.write_message(json.dumps({
                    'type': 'action_rejected',
                    'error_code': validation_result.error_code,
                    'error_message': validation_result.error_message,
                    'action': action_data,
                    'expected_format': expected_format,
                    'player_id': self.player_id,
                    'timestamp': time.time()
                }))
                logger.warning(
                    f"❌ Action validation failed for {self.agent_id}:\n"
                    f"   Error: {validation_result.error_message}\n"
                    f"   Action: {action_data}\n"
                    f"   Expected: {expected_format.get('json_example', {})}"
                )
                return

            # Forward validated and sanitized action to civcom
            if self.civcom:
                action_packet = self._convert_action_to_packet(sanitized_action)
                self.civcom.queue_to_civserver(json.dumps(action_packet))

                SecurityLogger.log_connection_event(self.agent_id, "ACTION_EXECUTED",
                                                  f"type={sanitized_action.get('type')}")

                self.write_message(json.dumps({
                    'type': 'action_accepted',
                    'action': sanitized_action,
                    'timestamp': time.time()
                }))
            else:
                self.write_message(json.dumps({
                    'type': 'error',
                    'code': 'E131',
                    'message': 'No connection to game server'
                }))

        except Exception as e:
            logger.exception(f"Error handling action: {e}")
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E132',
                'message': 'Action processing failed'
            }))

    def _handle_ping(self, msg_data: Dict[str, Any]):
        """Handle ping message"""
        self.write_message(json.dumps({
            'type': 'pong',
            'timestamp': time.time(),
            'agent_id': self.agent_id
        }))

    def _handle_player_ready(self, msg_data: Dict[str, Any]):
        """Handle player ready status from LLM agent"""
        if not self.is_llm_agent:
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E401',
                'message': 'Not authenticated as LLM agent'
            }))
            return

        if self.player_id is None:
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E402',
                'message': 'No player ID assigned yet'
            }))
            return

        # Get ready status from message (default to True)
        is_ready = msg_data.get('is_ready', True)

        # Create PACKET_PLAYER_READY packet
        ready_packet = {
            "pid": 11,  # PACKET_PLAYER_READY from packets.def:434
            "player_no": self.player_id,
            "is_ready": is_ready
        }

        # Send to civcom
        if self.civcom:
            try:
                # Queue packet for sending to civserver
                self.civcom.queue_to_civserver(json.dumps(ready_packet))
                self.civcom.send_packets_to_civserver()
                logger.info(f"Agent {self.agent_id} marked ready={is_ready} (player_no={self.player_id})")

                # Send confirmation back to agent
                self.write_message(json.dumps({
                    'type': 'ready_confirmed',
                    'player_no': self.player_id,
                    'is_ready': is_ready,
                    'message': f'Player {self.player_id} marked {"ready" if is_ready else "not ready"}'
                }))
            except Exception as e:
                logger.error(f"Failed to send ready packet: {e}")
                self.write_message(json.dumps({
                    'type': 'error',
                    'code': 'E403',
                    'message': f'Failed to send ready packet: {str(e)}'
                }))
        else:
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E404',
                'message': 'Not connected to game server'
            }))

    def _build_optimized_state(self, format_type: str, include_actions: bool) -> Dict[str, Any]:
        """Build optimized game state for LLM consumption using StateExtractor"""
        logger.debug(f"🏗️ _build_optimized_state called for agent {self.agent_id}, player_id={self.player_id}")

        # Get actual game state from civcom if available
        if self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                logger.debug(f"📥 Fetching full state from civcom for player {self.player_id}")
                full_state = self.civcom.get_full_state(self.player_id)
                logger.info(
                    f"✓ Received full state from civcom:\n"
                    f"   Turn: {full_state.get('turn', 'N/A')}\n"
                    f"   Players: {len(full_state.get('players', {}))}\n"
                    f"   Units: {len(full_state.get('units', {}))}\n"
                    f"   Cities: {len(full_state.get('cities', {}))}\n"
                    f"   Map tiles: {len(full_state.get('map', {}).get('tiles', []))}"
                )
            except Exception as e:
                logger.warning(f"⚠️ Failed to get game state from civcom: {e}, using fallback")
                full_state = self._get_fallback_state()
        else:
            logger.warning(
                f"⚠️ Civcom not available or missing get_full_state method:\n"
                f"   Civcom exists: {self.civcom is not None}\n"
                f"   Has get_full_state: {hasattr(self.civcom, 'get_full_state') if self.civcom else False}\n"
                f"   Using fallback state"
            )
            full_state = self._get_fallback_state()

        # Map format_type to StateFormat enum
        format_map = {
            'llm_optimized': StateFormat.LLM_OPTIMIZED,
            'full': StateFormat.FULL,
            'delta': StateFormat.DELTA
        }
        state_format = format_map.get(format_type, StateFormat.LLM_OPTIMIZED)

        # Use StateExtractor to format the state - this ensures map validation and proper structure
        try:
            if not self.game_id:
                raise ValueError("Game ID not set on handler; cannot extract state")

            since_turn = None
            if state_format == StateFormat.DELTA:
                since_turn = full_state.get('turn')

            logger.debug(f"🔄 Calling StateExtractor for game {self.game_id}, agent {self.agent_id}, format {state_format}")
            state = self.state_extractor.extract_state(
                self.game_id,
                self.player_id,
                state_format,
                since_turn=since_turn,
                agent_id=self.agent_id
            )
            logger.debug(f"✓ StateExtractor completed successfully")
        except Exception as e:
            logger.error(
                f"❌ StateExtractor failed: {e}, falling back to manual construction\n"
                f"   Game ID: {self.game_id}\n"
                f"   Player ID: {self.player_id}\n"
                f"   Format: {state_format}"
            )
            import traceback
            logger.error(f"StateExtractor traceback: {traceback.format_exc()}")
            state = self._build_fallback_state_from_full(full_state)

        # Add player_id and timestamp which are handler-specific
        state['player_id'] = self.player_id
        state['timestamp'] = time.time()

        # Normalise players to list form for downstream processing
        state['players'] = self._normalize_players_list(state.get('players', []))

        # NEW: Send game_ready signal after first successful state with turn > 0
        # This indicates the game is fully initialized and ready to accept actions
        if not hasattr(self, '_game_ready_sent'):
            current_turn = state.get('turn', 0)
            players_count = len(state.get('players', []))

            # Check if game has meaningful state (not just initialization)
            if current_turn > 0 and players_count > 0:
                self._game_ready_sent = True
                self.write_message(json.dumps({
                    'type': 'game_ready',
                    'agent_id': self.agent_id,
                    'player_id': self.player_id,
                    'turn': current_turn,
                    'players': players_count,
                    'message': 'Game fully initialized - ready to accept actions',
                    'timestamp': time.time()
                }))
                logger.info(
                    f"🎮 GAME_READY signal sent for agent {self.agent_id}:\n"
                    f"   Turn: {current_turn}\n"
                    f"   Players: {players_count}\n"
                    f"   Game is now ready for actions"
                )

        # For llm_optimized format, add AI analysis layers
        if format_type == 'llm_optimized':
            state['strategic_summary'] = self._get_strategic_summary()
            state['immediate_priorities'] = self._get_immediate_priorities()
            state['threats'] = self._assess_threats()
            state['opportunities'] = self._identify_opportunities()

            if include_actions:
                legal_actions = self._get_legal_actions_optimized(full_state)
                logger.info(f"✓ Generated {len(legal_actions)} legal actions for agent {self.agent_id}")
                state['legal_actions'] = legal_actions

        # For delta format, add change tracking
        elif format_type == 'delta':
            state['changes_since'] = self.last_state_query

        return state

    def _get_fallback_state(self) -> Dict[str, Any]:
        """Fallback state when civcom is not available"""
        return {
            'turn': 1,
            'phase': 'movement',
            'units': [],
            'cities': [],
            'visible_tiles': [],
            'players': [],
            'techs': [],
            'map_info': {}
        }

    def _build_fallback_state_from_full(self, full_state: Dict[str, Any]) -> Dict[str, Any]:
        """Construct a minimally useful state payload from a civcom snapshot."""
        units = full_state.get('units', [])
        if isinstance(units, dict):
            units = list(units.values())

        cities = full_state.get('cities', [])
        if isinstance(cities, dict):
            cities = list(cities.values())

        map_info = full_state.get('map') or full_state.get('map_info') or {
            'width': 80,
            'height': 50,
            'tiles': [],
            'visibility': {}
        }

        fallback_state = {
            'turn': full_state.get('turn', 1),
            'phase': full_state.get('phase', 'movement'),
            'player_id': self.player_id,
            'timestamp': time.time(),
            'game': {
                'turn': full_state.get('turn', 1),
                'phase': full_state.get('phase', 'movement')
            },
            'map': map_info,
            'players': self._normalize_players_list(full_state.get('players', [])),
            'units': units,
            'cities': cities
        }

        return fallback_state

    def _normalize_players_list(self, players: Any) -> List[Dict[str, Any]]:
        """Return a list of player dicts regardless of original collection type."""
        normalized: List[Dict[str, Any]] = []

        if isinstance(players, dict):
            for player_id, pdata in players.items():
                if isinstance(pdata, dict):
                    entry = dict(pdata)
                    entry.setdefault('id', player_id)
                    normalized.append(entry)
        elif isinstance(players, list):
            for pdata in players:
                if isinstance(pdata, dict):
                    entry = dict(pdata)
                    pid = entry.get('id') or entry.get('player_id')
                    if pid is not None:
                        entry.setdefault('id', pid)
                    normalized.append(entry)

        return normalized

    def _get_strategic_summary(self) -> Dict[str, Any]:
        """Get high-level strategic situation"""
        if self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                state = self.civcom.get_full_state(self.player_id)
                units = state.get('units', [])
                cities = state.get('cities', [])
                techs = state.get('techs', [])

                # Calculate military strength based on units
                military_units = [u for u in units if u.get('type', '').lower() in ['warriors', 'archers', 'legion', 'cavalry']]
                military_strength = 'strong' if len(military_units) > 3 else 'medium' if len(military_units) > 1 else 'weak'

                # Assess tech progress
                tech_count = len(techs)
                tech_progress = 'advanced' if tech_count > 10 else 'developing' if tech_count > 5 else 'early'

                return {
                    'score': state.get('score', 100),
                    'cities_count': len(cities),
                    'units_count': len(units),
                    'tech_progress': tech_progress,
                    'military_strength': military_strength,
                    'tech_count': tech_count,
                    'turn': state.get('turn', 1)
                }
            except Exception as e:
                logger.warning(f"Failed to get strategic summary from civcom: {e}")

        # Fallback values
        return {
            'score': 100,
            'cities_count': 1,
            'units_count': 2,
            'tech_progress': 'early',
            'military_strength': 'weak',
            'tech_count': 0,
            'turn': 1
        }

    def _get_immediate_priorities(self) -> List[str]:
        """Get current game priorities for LLM"""
        return [
            'explore_nearby_areas',
            'build_first_city',
            'research_basic_tech'
        ]

    def _assess_threats(self) -> List[Dict[str, Any]]:
        """Assess current threats"""
        threats = []

        if self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                state = self.civcom.get_full_state(self.player_id)
                units = state.get('units', [])
                players = self._normalize_players_list(state.get('players', []))
                visible_tiles = state.get('visible_tiles', [])

                # Check for enemy units near our cities
                our_cities = [c for c in state.get('cities', []) if c.get('owner') == self.player_id]
                enemy_units = [u for u in units if u.get('owner') != self.player_id and u.get('type', '').lower() in ['warriors', 'archers', 'legion']]

                for city in our_cities:
                    nearby_enemies = [
                        u for u in enemy_units
                        if abs(u.get('x', 0) - city.get('x', 0)) <= 3 and abs(u.get('y', 0) - city.get('y', 0)) <= 3
                    ]

                    if nearby_enemies:
                        threats.append({
                            'type': 'military',
                            'description': f"Enemy units near {city.get('name', 'city')}",
                            'severity': 'high',
                            'location': {'x': city.get('x'), 'y': city.get('y')},
                            'enemy_count': len(nearby_enemies)
                        })

                # Check for aggressive players in normalised collection
                for player_data in players:
                    player_id = player_data.get('id') or player_data.get('player_id')
                    if player_id is None:
                        continue
                    if str(player_id) == str(self.player_id):
                        continue
                    if player_data.get('attitude') == 'hostile':
                        threats.append({
                            'type': 'diplomatic',
                            'description': f"Hostile relations with {player_data.get('name', 'unknown')}",
                            'severity': 'medium',
                            'player_id': player_id
                        })

            except Exception as e:
                logger.warning(f"Failed to assess threats from civcom: {e}")

        return threats

    def _identify_opportunities(self) -> List[Dict[str, Any]]:
        """Identify current opportunities"""
        opportunities = []

        if self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                state = self.civcom.get_full_state(self.player_id)
                units = state.get('units', [])
                visible_tiles = state.get('visible_tiles', [])
                cities = state.get('cities', [])

                # Find good settlement locations
                resource_tiles = [t for t in visible_tiles if t.get('resource') and not t.get('city_id')]
                if resource_tiles:
                    opportunities.append({
                        'type': 'expansion',
                        'description': f"Found {len(resource_tiles)} resource tiles for new cities",
                        'priority': 'high',
                        'locations': [{'x': t.get('x'), 'y': t.get('y'), 'resource': t.get('resource')} for t in resource_tiles[:3]]
                    })

                # Check for undefended enemy cities
                our_military = [u for u in units if u.get('owner') == self.player_id and u.get('type', '').lower() in ['warriors', 'archers', 'legion']]
                enemy_cities = [c for c in cities if c.get('owner') != self.player_id]

                for city in enemy_cities:
                    nearby_defenders = [
                        u for u in units
                        if u.get('owner') == city.get('owner') and
                           abs(u.get('x', 0) - city.get('x', 0)) <= 2 and
                           abs(u.get('y', 0) - city.get('y', 0)) <= 2
                    ]

                    if len(nearby_defenders) == 0 and len(our_military) > 1:
                        opportunities.append({
                            'type': 'military',
                            'description': f"Undefended enemy city at ({city.get('x')}, {city.get('y')})",
                            'priority': 'high',
                            'location': {'x': city.get('x'), 'y': city.get('y')},
                            'city_name': city.get('name', 'unknown')
                        })

                # Trading opportunities
                players = self._normalize_players_list(state.get('players', []))
                friendly_players = [
                    p for p in players
                    if str(p.get('id') or p.get('player_id')) != str(self.player_id)
                    and p.get('attitude') == 'friendly'
                ]
                if friendly_players:
                    opportunities.append({
                        'type': 'diplomatic',
                        'description': f"Trade opportunities with {len(friendly_players)} friendly civilizations",
                        'priority': 'medium',
                        'partners': [p.get('name', 'unknown') for p in friendly_players]
                    })

            except Exception as e:
                logger.warning(f"Failed to identify opportunities from civcom: {e}")

        return opportunities

    def _get_legal_actions_optimized(self, game_state: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Get top legal actions for LLM (limited to ~20 most important)"""
        actions = []

        if not game_state and self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                game_state = self.civcom.get_full_state(self.player_id)
            except Exception as e:
                logger.warning(f"Failed to get legal actions from civcom: {e}")
                game_state = {}

        if game_state:
            units = game_state.get('units', [])
            cities = game_state.get('cities', [])
            techs = game_state.get('techs', [])

            # Get our units that can move
            our_units = [u for u in units if u.get('owner') == self.player_id and u.get('moves_left', 0) > 0]

            # Add unit movement actions
            for unit in our_units[:10]:  # Limit to 10 units
                # Handle unit type - can be int (type ID) or string (type name)
                unit_type_raw = unit.get('type', '')
                if isinstance(unit_type_raw, str):
                    unit_type = unit_type_raw.lower()
                else:
                    # Type is an integer ID - use generic name
                    unit_type = f"unit_{unit_type_raw}"

                current_x, current_y = unit.get('x', 0), unit.get('y', 0)

                # Check if unit can build cities (type 0 is usually Settlers in FreeCiv)
                if unit_type in ['settlers', 'engineer'] or unit_type_raw == 0:
                    # Settlement/construction actions
                    actions.append({
                        'type': 'unit_build_city',
                        'unit_id': unit.get('id'),
                        'priority': 'high',
                        'description': f"Build city with {unit_type}"
                    })

                # Movement actions (explore nearby)
                for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:  # Adjacent tiles
                    actions.append({
                        'type': 'unit_move',
                        'unit_id': unit.get('id'),
                        'dest_x': current_x + dx,
                        'dest_y': current_y + dy,
                        'priority': 'medium',
                        'description': f"Move {unit_type} to explore"
                    })

            # Add city production actions
            our_cities = [c for c in cities if c.get('owner') == self.player_id]
            for city in our_cities[:5]:  # Limit to 5 cities
                city_id = city.get('id')

                # Basic production options
                productions = ['Warriors', 'Granary', 'Barracks']
                if 'Bronze Working' in techs:
                    productions.append('Spearmen')
                if 'Pottery' in techs:
                    productions.append('Granary')

                for production in productions[:3]:  # Limit options
                    actions.append({
                        'type': 'city_production',
                        'city_id': city_id,
                        'production_type': production,
                        'priority': 'medium',
                        'description': f"Produce {production} in {city.get('name', 'city')}"
                    })

            # Add research actions
            available_techs = ['Alphabet', 'Bronze Working', 'Pottery', 'Animal Husbandry', 'Agriculture']
            researched_techs = set(techs)

            for tech in available_techs:
                if tech not in researched_techs:
                    actions.append({
                        'type': 'tech_research',
                        'tech_name': tech,
                        'priority': 'medium',
                        'description': f"Research {tech} technology"
                    })
                    break  # Only suggest one tech at a time

        # Fallback actions if no game state
        if not actions:
            actions = [
                {
                    'type': 'unit_move',
                    'unit_id': 1,
                    'dest_x': 10,
                    'dest_y': 20,
                    'priority': 'medium',
                    'description': 'Explore nearby area'
                },
                {
                    'type': 'city_production',
                    'city_id': 1,
                    'production_type': 'Warriors',
                    'priority': 'medium',
                    'description': 'Build military unit'
                }
            ]

        # Sort by priority and limit to top 15 actions
        priority_order = {'high': 3, 'medium': 2, 'low': 1}
        actions.sort(key=lambda x: priority_order.get(x.get('priority', 'low'), 1), reverse=True)

        return actions[:15]

    def _get_current_game_state(self) -> Optional[Dict[str, Any]]:
        """Get current game state for validation"""
        if self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                return self.civcom.get_full_state(self.player_id)
            except Exception as e:
                logger.warning(f"Failed to get current game state: {e}")
        return None

    def _get_expected_format(self, action_type: str) -> Dict[str, Any]:
        """Get expected format documentation for an action type

        Args:
            action_type: The action type to get format for

        Returns:
            Dict with examples and field descriptions
        """
        format_docs = {
            'tech_research': {
                'required_fields': ['type', 'tech_name'],
                'optional_fields': ['player_id'],
                'canonical_example': 'tech_research_player(1)_target(Alphabet)',
                'json_example': {
                    'type': 'tech_research',
                    'tech_name': 'alphabet',
                    'player_id': 1
                },
                'notes': 'tech_name must be lowercase. Available techs: alphabet, pottery, bronze_working, etc.'
            },
            'unit_move': {
                'required_fields': ['type', 'unit_id', 'dest_x', 'dest_y'],
                'optional_fields': ['player_id'],
                'canonical_example': 'unit_move_unit_id(42)_dest_x(10)_dest_y(20)',
                'json_example': {
                    'type': 'unit_move',
                    'unit_id': 42,
                    'dest_x': 10,
                    'dest_y': 20
                },
                'notes': 'Coordinates must be within map bounds'
            },
            'city_production': {
                'required_fields': ['type', 'city_id', 'production_type'],
                'optional_fields': ['player_id'],
                'canonical_example': 'city_production_city_id(1)_target(Warriors)',
                'json_example': {
                    'type': 'city_production',
                    'city_id': 1,
                    'production_type': 'warriors'
                },
                'notes': 'production_type should be lowercase. Options: warriors, settlers, granary, etc.'
            },
            'unit_build_city': {
                'required_fields': ['type', 'unit_id'],
                'optional_fields': ['player_id'],
                'canonical_example': 'unit_build_city_unit_id(42)_player(1)',
                'json_example': {
                    'type': 'unit_build_city',
                    'unit_id': 42,
                    'player_id': 1
                },
                'notes': 'Unit must be a settler or similar unit capable of founding cities'
            }
        }

        return format_docs.get(action_type, {
            'canonical_example': f'{action_type}_param(value)',
            'json_example': {'type': action_type},
            'notes': 'Refer to FreeCiv documentation for this action type'
        })

    def _convert_action_to_packet(self, action: Dict[str, Any]) -> Dict[str, Any]:
        """Convert LLM action to FreeCiv packet format"""
        action_type = action.get('type')

        if action_type == 'unit_move':
            return {
                'pid': 31,  # PACKET_UNIT_ORDERS
                'unit_id': action['unit_id'],
                'dest_x': action['dest_x'],
                'dest_y': action['dest_y']
            }
        elif action_type == 'city_production':
            return {
                'pid': 45,  # Example packet ID for city production
                'city_id': action['city_id'],
                'production_type': action['production_type']
            }
        elif action_type == 'tech_research':
            # PACKET_PLAYER_RESEARCH requires tech ID, not tech name
            # TODO: Load tech IDs dynamically from PACKET_RULESET_TECH packets
            # Map common tech names to IDs (hardcoded for now)
            tech_name_to_id = {
                'alphabet': 1,
                'pottery': 2,
                'bronze working': 3,
                'animal husbandry': 4,
                'agriculture': 5,
                'writing': 6,
                'code of laws': 7,
                'mysticism': 8,
                'ceremonial burial': 9,
                'masonry': 10,
                'the wheel': 11,
                'warrior code': 12,
                'iron working': 13,
                'horseback riding': 14,
                'map making': 15
            }
            tech_name_lower = action['tech_name'].lower()
            tech_id = tech_name_to_id.get(tech_name_lower)

            if tech_id is None:
                # Unknown tech name - this indicates validator/converter mismatch
                available_techs = sorted(tech_name_to_id.keys())
                error_msg = (
                    f"Unknown technology '{action['tech_name']}' cannot be mapped to FreeCiv tech ID. "
                    f"Available techs: {', '.join(available_techs[:10])}..."
                )
                logger.error(f"Tech mapping error: {error_msg}")
                raise ValueError(error_msg)

            return {
                'pid': 55,  # PACKET_PLAYER_RESEARCH
                'tech': tech_id  # Field name is 'tech', not 'tech_name'!
            }
        elif action_type == 'unit_build_city':
            return {
                'pid': 35,  # PACKET_UNIT_BUILD_CITY
                'unit_id': action['unit_id'],
                'player_id': action.get('player_id', self.player_id)
            }
        elif action_type == 'unit_explore':
            return {
                'pid': 32,  # PACKET_UNIT_AUTO
                'unit_id': action['unit_id'],
                'auto_type': 'explore'
            }

        return action  # Fallback

    def _get_nation_id(self, nation_name: str) -> int:
        """Get nation ID from nation name using dynamically received nation list.

        Args:
            nation_name: Name of the nation (e.g., "Americans", "Romans")

        Returns:
            Nation ID integer from civserver's PACKET_RULESET_NATION
        """
        if not nation_name or nation_name.lower() == 'random':
            # Select random nation from defaults
            import random
            nation_name = random.choice(DEFAULT_NATIONS)
            logger.info(f"Auto-selecting random nation: {nation_name}")

        # Wait for civcom to receive nation list from PACKET_RULESET_NATION (pid=148)
        import time
        max_wait = 2.0  # 2 second timeout
        waited = 0.0
        while (not hasattr(self.civcom, 'nations') or not self.civcom.nations) and waited < max_wait:
            time.sleep(0.05)
            waited += 0.05

        # Try to get nation ID from dynamically built nations dict
        if hasattr(self.civcom, 'nations') and self.civcom.nations:
            # Try exact match first
            nation_id = self.civcom.nations.get(nation_name)
            if nation_id is not None:
                logger.info(f"Nation '{nation_name}' -> ID {nation_id} (from civserver)")
                return nation_id

            # Try without 's' suffix (e.g., "Americans" → "American")
            if nation_name.endswith('s'):
                nation_singular = nation_name[:-1]
                nation_id = self.civcom.nations.get(nation_singular)
                if nation_id is not None:
                    logger.info(f"Nation '{nation_name}' -> '{nation_singular}' -> ID {nation_id}")
                    return nation_id

            # Nation not found - list available nations
            available = list(self.civcom.nations.keys())[:5]
            logger.warning(f"Nation '{nation_name}' not found. Available: {available}...")

        # Fallback: use first nation (usually index 0)
        logger.warning(f"Using fallback nation ID 0 for '{nation_name}'")
        return 0

    def _connect_to_civserver(self, port: int, game_id: str):
        """Connect to civserver (registration handled separately async)"""
        try:
            host = '127.0.0.1'
            max_attempts = llm_config.get('civserver.connection_retries', 5)
            retry_delay = llm_config.get('civserver.retry_delay_seconds', 1.0)
            last_error = None

            for attempt in range(1, int(max_attempts) + 1):
                try:
                    with socket.create_connection((host, port), timeout=2):
                        logger.info(
                            f"Civserver {host}:{port} reachable (attempt {attempt})"
                        )
                        break
                except OSError as conn_err:
                    last_error = conn_err
                    logger.warning(
                        f"Attempt {attempt} to reach civserver {host}:{port} failed: {conn_err}"
                    )
                    if attempt < int(max_attempts):
                        time.sleep(float(retry_delay))
            else:
                error_msg = (
                    f"Unable to reach civserver at {host}:{port} after {max_attempts} attempts"
                )
                raise ConnectionError(error_msg) from last_error

            # Create proper FreeCiv login packet (PACKET_SERVER_JOIN_REQ)
            # Must include pid=4 and version fields for server to parse it
            login_packet = json.dumps({
                'pid': 4,  # PACKET_SERVER_JOIN_REQ
                'username': self.agent_id,
                'capability': '+Freeciv.Web.Devel-3.3',
                'version_label': '-dev',
                'major_version': 3,
                'minor_version': 3,
                'patch_version': 0,
                'port': port
            })

            # Set loginpacket on the handler first (CivCom expects civwebserver.loginpacket)
            self.loginpacket = login_packet

            # Create CivCom connection
            self.civcom = CivCom(self.agent_id, port, f"{self.agent_id}_{self.id}", self)
            logger.debug(f"Created CivCom instance for {self.agent_id}")
            self.civcom.start()
            logger.debug(f"CivCom thread started: is_alive={self.civcom.is_alive()}, daemon={self.civcom.daemon}")

            logger.info(f"LLM agent {self.agent_id} connected to civserver on port {port}")

            # Give thread a moment to initialize and detect any immediate crashes
            import time
            time.sleep(0.2)
            logger.debug(f"After initialization delay: CivCom thread is_alive={self.civcom.is_alive()}")

            logger.debug(f"Checking game_id for CivCom registration: game_id='{game_id}'")
            if game_id:
                logger.debug(f"Registering CivCom for game_id='{game_id}', agent='{self.agent_id}'")
                existing_civcom = civcom_registry.get_civcom(game_id, self.agent_id)
                if existing_civcom and existing_civcom is not self.civcom:
                    logger.info(f"Replacing CivCom registration for agent {self.agent_id} in game {game_id}")

                civcom_registry.register_game(
                    game_id,
                    self.agent_id,
                    self.civcom,
                    metadata={
                        'agent_id': self.agent_id,
                        'player_id': self.player_id,
                        'port': port
                    }
                )
                logger.info(f"CivCom registered for agent {self.agent_id} in game {game_id}")
            else:
                logger.warning(f"game_id is empty/None, skipping CivCom registration")

        except Exception as e:
            logger.exception(f"Failed to connect LLM agent to civserver: {e}")
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E140',
                'message': 'Failed to connect to game server'
            }))
            raise

    # Old _start_game_after_delay() method removed - now handled by GameSessionManager
    # The GameSessionManager coordinates game start when all players are ready

    def _forward_to_civcom(self, message: str):
        """Forward message to civcom"""
        if self.civcom:
            self.civcom.queue_to_civserver(message)

    def _check_rate_limit(self) -> bool:
        """Legacy rate limiting method - now uses distributed rate limiter"""
        if not self.agent_id:
            return True  # Allow if no agent ID set yet

        return distributed_rate_limiter.check_limit(self.agent_id, 'legacy')

    def on_close(self):
        """Handle WebSocket connection close"""
        # INVESTIGATION: Log detailed closure information
        import traceback
        import inspect

        close_code = getattr(self, 'close_code', None)
        close_reason = getattr(self, 'close_reason', None)

        logger.warning(
            f"🔴 WEBSOCKET CLOSED for {self.agent_id}:\n"
            f"   Close code: {close_code}\n"
            f"   Close reason: {close_reason}\n"
            f"   Authenticated: {self.is_llm_agent}\n"
            f"   Player ID: {self.player_id}\n"
            f"   Session ID: {self.session_id}\n"
            f"   CivCom alive: {self.civcom.is_alive() if self.civcom and hasattr(self.civcom, 'is_alive') else 'N/A'}\n"
            f"   CivCom stopped: {self.civcom.stopped if self.civcom else 'N/A'}\n"
            f"   Call stack:\n{''.join(traceback.format_stack())}"
        )

        # Terminate session
        if self.session_id:
            session_manager.terminate_session(self.session_id, "connection_closed")

        # Clean up civcom connection
        if self.civcom:
            self.civcom.stopped = True
            self.civcom.close_connection()

        if self.game_id and self.agent_id:
            registered_civcom = civcom_registry.get_civcom(self.game_id, self.agent_id)
            if registered_civcom is self.civcom:
                civcom_registry.unregister_game(self.game_id, self.agent_id)

        self.civcom = None

        # Remove from agent registry
        if self.agent_id and self.agent_id in llm_agents:
            del llm_agents[self.agent_id]

        # Invalidate cache for this player
        if self.player_id:
            state_cache.invalidate(player_id=self.player_id)

        SecurityLogger.log_connection_event(self.agent_id, "DISCONNECTED",
                                          f"session_id={self.session_id}")

    def _validate_session(self) -> bool:
        """Validate current session"""
        if not self.session_id:
            return True  # No session to validate yet

        session = session_manager.validate_session(self.session_id)
        if session:
            self.session_info = session
            return True

        # Session invalid/expired
        self.session_id = None
        self.session_info = None
        self.is_llm_agent = False
        return False

    def check_origin(self, origin):
        """Validate WebSocket origin for security"""
        # Get allowed origins from config
        allowed_origins = llm_config.get('allowed_origins', [
            'http://localhost:8080',
            'https://localhost:8080',
            'http://127.0.0.1:8080',
            'https://127.0.0.1:8080'
        ])

        # Allow null origin for non-browser clients (LLM agents)
        if origin is None:
            logger.debug("Allowing null origin for LLM agent")
            return True

        # Check against allowed origins list
        if origin in allowed_origins:
            logger.debug(f"Allowing origin: {origin}")
            return True

        # Log unauthorized origin attempts with helpful debugging info
        SecurityLogger.log_security_violation(
            self.agent_id or "unknown",
            "INVALID_ORIGIN",
            f"Rejected origin: {origin}"
        )
        logger.warning(f"Rejected WebSocket connection from unauthorized origin: {origin}. Allowed origins: {allowed_origins}")
        return False

    def get_compression_options(self):
        """Enable WebSocket compression"""
        return {'compression_level': 9, 'mem_level': 9}

    # NOTE: Removed get_websocket_max_message_size() method
    # Tornado does NOT call this method - it reads 'websocket_max_message_size' from Application settings
    # The correct configuration is in freeciv-proxy.py: websocket_max_message_size=50 * 1024 * 1024
    # IOStream buffer sizes are configured in open() method: max_buffer_size and max_write_buffer_size
