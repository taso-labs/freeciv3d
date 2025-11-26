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
from itertools import chain
from tornado import websocket, ioloop
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
from ruleset_mapper import RulesetMapper, clean_production_name
from unit_action_cache import get_unit_action_cache, invalidate_unit_actions
from probability_utils import encode_probability, decode_probability_to_percent
from typing import Dict, Any, Optional, List
from fc_constants import (
    VUT_ADVANCE,
    VUT_IMPROVEMENT,
    VUT_MINSIZE,
    ACTIVITY_IDLE,
    ACTIVITY_POLLUTION,
    ACTIVITY_MINE,
    ACTIVITY_IRRIGATE,
    ACTIVITY_FORTIFIED,
    ACTIVITY_SENTRY,
    ACTIVITY_PILLAGE,
    ACTIVITY_GOTO,
    ACTIVITY_EXPLORE,
    ACTIVITY_TRANSFORM,
    ACTIVITY_FORTIFYING,
    ACTIVITY_FALLOUT,
    ACTIVITY_BASE,
    ACTIVITY_GEN_ROAD,
    BUSY_ACTIVITIES,
    ACTION_TRANSPORT_BOARD,
    ACTION_TRANSPORT_DEBOARD,
    ACTION_TRANSPORT_EMBARK,
    ACTION_TRANSPORT_UNLOAD,
    ACTION_AIRLIFT,
    ACTION_ESTABLISH_EMBASSY,
    ACTION_SPY_INVESTIGATE_CITY,
    ACTION_SPY_POISON,
    ACTION_SPY_SABOTAGE_CITY,
    ACTION_SPY_STEAL_TECH,
    ACTION_SPY_BRIBE_UNIT,
    ACTION_SPY_STEAL_GOLD,
    ACTION_SPY_INCITE_CITY,
    ACTION_TRADE_ROUTE,
    ACTION_HELP_WONDER,
    ACTION_MARKETPLACE,
    ACTION_CAPTURE_UNITS,
    ACTION_SPY_SABOTAGE_UNIT,
    ACTION_STEAL_MAPS,
    ACTION_EXPEL_UNIT,
    ACTION_CONQUER_CITY,
    ACTION_STRIKE_BUILDING,
    ACTION_STRIKE_PRODUCTION,
    ACTION_CONVERT,
    ACTION_HOME_CITY
)
from packet_constants import (
    PACKET_CITY_CHANGE,
    PACKET_DIPLOMACY_INIT_MEETING_REQ,
    PACKET_UNIT_DO_ACTION,
    PACKET_PLAYER_RATES
)

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

# Packet buffer limits to prevent unbounded memory growth
# These protect against memory exhaustion if authentication hangs or fails
MAX_PACKET_BUFFER_SIZE = 200  # Maximum number of packets to buffer (typical game sends ~150 RULESET packets)
MAX_PACKET_BUFFER_BYTES = 5 * 1024 * 1024  # 5MB maximum buffer size (typical game ~1.2MB)

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

    This is the PRODUCTION WebSocket handler for LLM agents.
    Endpoint: /llmsocket/8002
    Architecture: game_arena → llm-gateway (port 8003) → LLMWSHandler → GameSession

    Player ID assignment uses GameSession.allocate_ai_slot() for sequential, thread-safe
    allocation (see game_session_manager.py).

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

        # Packet buffering during authentication
        # FreeCiv sends ~1.2MB of PACKET_RULESET_NATION packets immediately upon connection
        # These must be buffered until auth_success is sent to maintain protocol order
        self.packet_buffer = []  # List of JSON packet strings to buffer
        self.auth_complete = False  # Flag: has authentication completed?
        self.buffer_enabled = False  # Flag: should CivCom buffer packets?

        # Add io_loop attribute for CivCom compatibility
        # CivCom uses conn.io_loop.add_callback() to send packets safely across threads
        # This must be the IOLoop instance that's handling this connection
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

        # Configure IOStream buffer sizes for large FreeCiv packets
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
            elif msg_type == 'unit_action_query':
                # v2.0 server-authoritative per-unit action query
                await self._handle_unit_action_query(msg_data)
            elif msg_type == 'unit_action_query_batch':
                # v2.0 batch query - iterate queries and respond individually for now
                await self._handle_unit_action_query_batch(msg_data)
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

        Enable packet buffering during authentication to solve protocol packet ordering
        race condition. FreeCiv sends ~1.2MB of PACKET_RULESET_NATION packets immediately
        when connection is established, which arrive BEFORE auth_success is generated.
        We buffer these packets and flush after auth_success.
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

            # Register agent first (needed for player_id calculation)
            llm_agents[self.agent_id] = self
            self.is_llm_agent = True

            # Get game_id FIRST, then allocate/lookup civserver port
            # This ensures both players in the same game connect to the SAME server
            # LLM Gateway flattens nested 'data' field to top level before sending to proxy
            game_id = msg_data.get('game_id', f'game_{uuid.uuid4().hex[:8]}')
            self.game_id = game_id

            # Allocate a multiplayer civserver port via metaserver query
            # Strategy: Query metaserver for pregame servers with 0 players, select lowest port
            # First player: allocates new pregame server (e.g., port 6001)
            # Second player: reuses the same port (6001)
            # See game_session_manager.py for detailed allocation logic and fallback strategies
            try:
                civserver_port = await game_session_manager.allocate_civserver_port(game_id)
            except Exception as alloc_err:
                logger.error(
                    f"❌ Agent {self.agent_id}: failed to allocate civserver port via metaserver: {alloc_err}\n"
                    f"   Game ID: {game_id}"
                )
                self.write_message(json.dumps({
                    'type': 'error',
                    'code': 'E140',
                    'message': 'Failed to connect to game server',
                    'details': {
                        'reason': 'no_multiplayer_server_available'
                    }
                }))
                # Cleanup partial registration state
                if self.agent_id in llm_agents:
                    del llm_agents[self.agent_id]
                self.is_llm_agent = False
                return
            logger.info(
                f"🎮 Agent {self.agent_id} assigned to civserver:\n"
                f"   Game ID: {game_id}\n"
                f"   Civserver Port: {civserver_port}\n"
            )

            # Enable packet buffering IMMEDIATELY before connecting to civserver
            # The civserver sends ~1.2MB of PACKET_RULESET_NATION packets as soon as we connect
            # We MUST enable buffering BEFORE _connect_to_civserver() to capture these packets
            self.buffer_enabled = True
            logger.info(f"🔒 Packet buffering ENABLED for {self.agent_id} before civserver connection")

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

            # Set up capabilities for action validator
            self.capabilities = [ActionType(cap) for cap in capability_set]
            self.action_validator = LLMActionValidator(self.capabilities, civcom=self.civcom)

            # Self-assign player_id (restores pre-GameSessionManager behavior)
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
                logger.info(
                    f"📋 Got GameSession for {self.agent_id}:\n"
                    f"   Game ID: {game_id}\n"
                    f"   Port: {game_session.civserver_port}\n"
                    f"   Current players: {len(game_session.players)}/{game_session.min_players}\n"
                    f"   Phase: {game_session.phase.value}\n"
                    f"   Game started: {game_session.game_started}"
                )

                logger.info(f"⏳ Waiting for PACKET_CONN_INFO for {self.agent_id}...")
                waited = 0.0
                # Increase wait time to accommodate slow civserver initialization under load
                # Previously 5.0s; empirically, second player can take >5s to receive PACKET_CONN_INFO
                max_wait = 15.0
                while (not hasattr(self.civcom, 'player_id') or self.civcom.player_id is None) and waited < max_wait:
                    await asyncio.sleep(0.2)
                    waited += 0.2
                    if waited % 1.0 < 0.3:
                        logger.info(f"   {self.agent_id}: Still waiting for PACKET_CONN_INFO... ({waited:.1f}s/{max_wait}s)")

                if not hasattr(self.civcom, 'player_id') or self.civcom.player_id is None:
                    logger.error(
                        f"❌ {self.agent_id}: Failed to receive PACKET_CONN_INFO after {max_wait}s\n"
                        f"   This usually means civserver is not responding or is overloaded\n"
                        f"   Check civserver logs at /docker/logs/freeciv-web-log-{game_session.civserver_port}.log"
                    )
                    raise RuntimeError(f"Failed to receive PACKET_CONN_INFO - civserver not responding")

                logger.info(f"✅ Received PACKET_CONN_INFO: {self.agent_id} → player_num={self.civcom.player_id}")

                ai_slot = game_session.allocate_ai_slot()
                self.player_id = self.civcom.player_id

                if self.player_id is None or self.player_id >= 512:
                    logger.error(
                        f"❌ Invalid player_id received for {self.agent_id}:\n"
                        f"   Player ID: {self.player_id}\n"
                        f"   AI Slot: {ai_slot}\n"
                        f"   This usually means civserver is not responding correctly"
                    )
                    raise RuntimeError(f"Invalid player_id={self.player_id} (expected < 512)")

                self.session_info.player_id = self.player_id
                logger.info(f"✅ {self.agent_id} assigned player_id={self.player_id} (AI slot {ai_slot})")

                game_session.add_player(self.agent_id, self.player_id, self)
                logger.info(f"Registered agent {self.agent_id} with game session {game_id} (player_id={self.player_id})")

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

                # DEFER PLAYER READY: Do not immediately ready up the first player.
                # We will send PACKET_PLAYER_READY only when both players have connected,
                # or after a short grace period if starting vs AI is intended.
                logger.info(
                    f"✅ Nation selected for {self.agent_id} - deferring PACKET_PLAYER_READY until session conditions met"
                )

                # Send auth_success in FLAT format (Gateway will transform to nested for agent)
                # Game will start when all players are ready (~5-7 seconds after last player joins)
                # Architecture: Proxy sends flat → Gateway transforms → Agent receives nested
                self.write_message(json.dumps({
                    'type': 'auth_success',  # Flat format - Gateway expects this
                    'agent_id': self.agent_id,
                    'session_id': self.session_id,
                    'player_id': self.player_id,
                    'game_id': self.game_id,
                    'civserver_port': game_session.civserver_port,  # SPECTATOR FIX: Port for spectator URL generation
                    'capabilities': list(capability_set),
                    'session_expires_in': int(self.session_info.expires_at - time.time()),
                    'message': 'Player authenticated successfully. Waiting for all players to join.',
                    'status': 'authenticated',
                    'game_ready': False,  # Game not started yet
                    'waiting_for': 'game_ready',  # Signal to wait for
                    'expected_wait_seconds': '5-7',  # Typical initialization time
                    'instructions': 'Wait for game_ready message before querying state or submitting actions'
                }))
                logger.info(f"📤 Sent auth_success with player_id={self.player_id} to agent {self.agent_id}")

                # Flush buffered packets immediately after auth_success
                # This solves the protocol packet ordering race condition by ensuring:
                # 1. auth_success is sent first (client expects this)
                # 2. Buffered PACKET_RULESET_NATION packets are sent second (game state)
                # 3. Future packets flow normally (buffer_enabled=False)
                self.auth_complete = True
                self.buffer_enabled = False
                buffer_count = len(self.packet_buffer)
                logger.info(f"🔓 Packet buffering DISABLED for {self.agent_id} - flushing {buffer_count} packets")
                self._flush_packet_buffer()
                self.packet_buffer.clear()  # Ensure buffer is empty after flush

                # CONDITIONAL AUTO-READY LOGIC
                try:
                    # Defensive fetch of session state
                    session_players = getattr(game_session, 'players', {}) or {}
                    players_count = len(session_players)
                    min_players = getattr(game_session, 'min_players', 2) or 2

                    if players_count >= min_players:
                        # Cancel any pending auto-ready timers and send ready for all not-yet-ready players
                        logger.info(
                            f"🟢 Session ready to start: players={players_count}/{min_players}. Sending PACKET_PLAYER_READY for all."
                        )

                        # Helper to send ready for a handler if not already marked
                        def _send_ready_for_handler(handler):
                            info = session_players.get(getattr(handler, 'agent_id', None))
                            already_ready = getattr(info, 'marked_ready', False) if info else False
                            if not info or already_ready:
                                return
                            ready_packet_local = {
                                "pid": 11,
                                "player_no": getattr(handler, 'player_id', None),
                                "is_ready": True
                            }
                            handler.civcom.queue_to_civserver(json.dumps(ready_packet_local))
                            handler.civcom.send_packets_to_civserver()
                            game_session.mark_player_ready(handler.agent_id)
                            logger.info(f"📤 PACKET_PLAYER_READY sent for {handler.agent_id} (player_no={handler.player_id})")

                            # Cancel any pending timer on the handler
                            if hasattr(handler, "_auto_ready_timer") and handler._auto_ready_timer:
                                try:
                                    handler._auto_ready_timer.cancel()
                                except Exception:
                                    pass
                                handler._auto_ready_timer = None

                        # Send ready for this handler
                        _send_ready_for_handler(self)

                        # And for any other players not yet marked
                        for pinfo in list(session_players.values()):
                            try:
                                if getattr(pinfo, 'agent_id', None) != self.agent_id and hasattr(pinfo, 'handler'):
                                    _send_ready_for_handler(pinfo.handler)
                            except Exception as e_loop:
                                logger.debug(f"Skip ready for other handler due to: {e_loop}")
                    else:
                        # Defer: schedule auto-ready after a grace period if no second agent joins
                        # Support both flat and nested config keys, sanitize to int
                        cfg_val = (
                            llm_config.get('autostart.wait_for_second_agent_seconds')
                            or llm_config.get('autostart_wait_for_second_agent_seconds')
                            or 12
                        )
                        try:
                            wait_seconds = int(cfg_val)  # type: ignore[arg-type]
                        except Exception:
                            wait_seconds = 12
                        logger.info(
                            f"⏳ Waiting up to {wait_seconds}s for second agent before auto-ready: "
                            f"players={players_count}/{min_players}"
                        )

                        async def _auto_ready_after_delay(handler_self, session_obj, delay_s: int):
                            try:
                                await asyncio.sleep(delay_s)
                                # If still not enough players and not ready, start vs AI by marking ready
                                cur_players = getattr(session_obj, 'players', {}) or {}
                                cur_info = cur_players.get(getattr(handler_self, 'agent_id', None))
                                cur_min_players = getattr(session_obj, 'min_players', 2) or 2
                                already_ready = getattr(cur_info, 'marked_ready', False) if cur_info else False
                                if (cur_info and not already_ready and len(cur_players) < cur_min_players):
                                    logger.info(
                                        f"🟡 Auto-readying {handler_self.agent_id} after {delay_s}s (starting vs AI)."
                                    )
                                    ready_packet_local = {
                                        "pid": 11,
                                        "player_no": getattr(handler_self, 'player_id', None),
                                        "is_ready": True
                                    }
                                    handler_self.civcom.queue_to_civserver(json.dumps(ready_packet_local))
                                    handler_self.civcom.send_packets_to_civserver()
                                    session_obj.mark_player_ready(handler_self.agent_id)
                                    logger.info(
                                        f"📤 PACKET_PLAYER_READY sent (auto) for {handler_self.agent_id} (player_no={handler_self.player_id})"
                                    )
                            except asyncio.CancelledError:
                                logger.debug(f"Auto-ready timer cancelled for {handler_self.agent_id}")
                            except Exception as e2:
                                logger.error(f"Auto-ready timer error for {handler_self.agent_id}: {e2}")

                        # Store and start timer on handler
                        self._auto_ready_timer = asyncio.create_task(_auto_ready_after_delay(self, game_session, int(wait_seconds)))
                except Exception as ready_err:
                    logger.error(f"Conditional ready logic failed: {ready_err}")

            except Exception as e:
                logger.exception(f"Error in player registration and nation selection: {e}")

                # CRITICAL: Disable buffering on error to prevent packet accumulation
                # Also clear buffer to prevent memory leak
                self.buffer_enabled = False
                buffer_count = len(self.packet_buffer)
                self.packet_buffer.clear()
                logger.warning(f"🔓 Packet buffering DISABLED due to error for {self.agent_id} - cleared {buffer_count} buffered packets")

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
            # CRITICAL: Disable buffering on any authentication error
            # Also clear buffer to prevent memory leak
            self.buffer_enabled = False
            buffer_count = len(self.packet_buffer)
            self.packet_buffer.clear()
            logger.warning(f"🔓 Packet buffering DISABLED due to exception for {self.agent_id} - cleared {buffer_count} buffered packets")

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

        elif action_type == "end_turn":
            # end_turn is simple - just needs player_id (already mapped above)
            # No additional fields required
            logger.info(f"Normalized end_turn action for player {normalized.get('player_id')}")

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

        elif action_type == "end_turn":
            # end_turn only needs player_id
            if "player" in params:
                result["player_id"] = params["player"]
            elif "actor_id" in params:
                result["player_id"] = params["actor_id"]

            logger.info(f"Parsed end_turn: {result}")

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

                # Get current game state for debugging
                game_state = self._get_current_game_state()
                current_turn = game_state.get('turn', 'unknown') if game_state else 'unknown'

                self.write_message(json.dumps({
                    'type': 'action_rejected',
                    'error_code': validation_result.error_code,
                    'error_message': validation_result.error_message,
                    'action': action_data,
                    'expected_format': expected_format,
                    'player_id': self.player_id,
                    'turn': current_turn,
                    'timestamp': time.time()
                }))
                logger.warning(
                    f"❌ Action validation failed for {self.agent_id}:\n"
                    f"   Error Code: {validation_result.error_code}\n"
                    f"   Error: {validation_result.error_message}\n"
                    f"   Action: {action_data}\n"
                    f"   Player ID: {self.player_id}\n"
                    f"   Turn: {current_turn}\n"
                    f"   Expected: {expected_format.get('json_example', {})}"
                )
                return

            # Forward validated and sanitized action to civcom
            if self.civcom:
                action_packet = self._convert_action_to_packet(sanitized_action)
                self.civcom.queue_to_civserver(json.dumps(action_packet))
                # CRITICAL: Must call send_packets_to_civserver() to actually send queued packets!
                # Without this, actions are queued but never transmitted to civserver
                self.civcom.send_packets_to_civserver()

                SecurityLogger.log_connection_event(self.agent_id, "ACTION_EXECUTED",
                                                  f"type={sanitized_action.get('type')}")

                # Protocol v2.0: Return action_result structure instead of simple action_accepted
                action_result = {
                    'type': 'action_result',
                    'success': True,  # Optimistic success - actual result comes from server packets
                    'action_type': sanitized_action.get('type'),
                    'result': {
                        'action': sanitized_action,
                        'timestamp': time.time(),
                        'status': 'queued'  # Will update to 'confirmed' or 'failed' upon server response
                    }
                }
                
                # Preserve correlation_id if present (for batch tracking)
                if 'correlation_id' in msg_data:
                    action_result['correlation_id'] = msg_data['correlation_id']
                
                self.write_message(json.dumps(action_result))
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

        return

    # ---------------------------------------------------------------------
    # Server-Authoritative Action Query (v2.0) - INITIAL STUB IMPLEMENTATION
    # ---------------------------------------------------------------------
    async def _handle_unit_action_query(self, msg_data: Dict[str, Any]):
        """Handle per-unit action query (stub - returns empty action list until integrated with CivCom).

        Protocol spec fields:
          Request: unit_id (required), optional target_* fields, request_kind
          Response: actions[] with probability metadata

        This initial version validates basic connectivity and returns an empty
        actions array so client logic can be developed incrementally.
        """
        correlation_id = msg_data.get('correlation_id')
        unit_id = msg_data.get('unit_id')
        target_unit_id = msg_data.get('target_unit_id', 0)
        target_tile_id = msg_data.get('target_tile_id', 0)
        target_extra_id = msg_data.get('target_extra_id', 0)
        request_kind = msg_data.get('request_kind', 0)

        # Basic validation
        if not self.is_llm_agent or self.player_id is None:
            self.write_message(json.dumps({
                'type': 'error',
                'correlation_id': correlation_id,
                'data': {
                    'type': 'error',
                    'success': False,
                    'code': 'E500',  # action query unit/player context failure
                    'message': 'Unit action query rejected - not authenticated or player not assigned'
                }
            }))
            return

        if unit_id is None:
            self.write_message(json.dumps({
                'type': 'error',
                'correlation_id': correlation_id,
                'data': {
                    'type': 'error',
                    'success': False,
                    'code': 'E500',
                    'message': 'Missing unit_id field in unit_action_query'
                }
            }))
            return

        # Check cache first
        cache = get_unit_action_cache()
        game_state = self._get_current_game_state()
        current_turn = game_state.get('turn', 1) if game_state else 1
        
        cached_actions = cache.get(unit_id, current_turn)
        if cached_actions is not None:
            logger.debug(f"Using cached actions for unit {unit_id} turn {current_turn}")
            response_payload = cached_actions
        else:
            # FUTURE: Integrate with CivCom to send PACKET_UNIT_GET_ACTIONS / PACKET_UNIT_ACTION_QUERY
            # and parse PACKET_UNIT_ACTIONS for server authoritative probabilities.
            # For now, return stub with empty actions list and metadata.
            response_payload = {
                'unit_id': unit_id,
                'target_unit_id': target_unit_id,
                'target_tile_id': target_tile_id,
                'target_extra_id': target_extra_id,
                'request_kind': request_kind,
                'actions': [],  # Empty until server integration
                'queried_at': time.time()
            }
            
            # Cache the result
            cache.set(unit_id, current_turn, response_payload)

        response = {
            'type': 'unit_action_response',
            'agent_id': self.agent_id,
            'timestamp': time.time(),
            'correlation_id': correlation_id,
            'data': response_payload
        }
        self.write_message(json.dumps(response))

    async def _handle_unit_action_query_batch(self, msg_data: Dict[str, Any]):
        """Handle batch unit action queries (stub).

        Strategy: respond with multiple unit_action_response messages (one per query)
        so clients can reuse single response handler. Future optimization may
        bundle into a single batch response type.
        """
        correlation_id = msg_data.get('correlation_id')
        queries = msg_data.get('queries', [])

        if not isinstance(queries, list):
            self.write_message(json.dumps({
                'type': 'error',
                'correlation_id': correlation_id,
                'data': {
                    'type': 'error',
                    'success': False,
                    'code': 'E500',
                    'message': 'Invalid queries field (expected list)'
                }
            }))
            return

        # Sequentially process each query (stubbed)
        for q in queries:
            if not isinstance(q, dict):
                continue
            single_msg = {'type': 'unit_action_query', **q}
            # Reuse single query handler; ensure correlation id chains
            if correlation_id and 'correlation_id' not in single_msg:
                single_msg['correlation_id'] = correlation_id
            await self._handle_unit_action_query(single_msg)

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

        # NOTE: Players, units, and cities are kept in dict format (keyed by ID) for efficiency
        # No normalization needed - dict format is now the standard

        # NOTE: game_ready signal is now sent by GameSessionManager when game actually starts
        # Removed duplicate logic that sent game_ready during state query (chicken-and-egg problem fixed)

        # For llm_optimized format, add AI analysis layers
        if format_type == 'llm_optimized':
            state['strategic_summary'] = self._get_strategic_summary()
            state['immediate_priorities'] = self._get_immediate_priorities()
            state['threats'] = self._assess_threats()
            state['opportunities'] = self._identify_opportunities()

            if include_actions:
                # NEW v2.0: Use unit_actions dict keyed by unit_id instead of flat legal_actions list
                unit_actions_dict = self._get_unit_actions_dict(full_state)
                logger.info(f"✓ Generated unit_actions dict for {len(unit_actions_dict)} units")
                state['unit_actions'] = unit_actions_dict

        # For delta format, add change tracking
        elif format_type == 'delta':
            state['changes_since'] = self.last_state_query

        return state

    def _get_fallback_state(self) -> Dict[str, Any]:
        """Fallback state when civcom is not available - returns dict format"""
        return {
            'turn': 1,
            'phase': 'movement',
            'units': {},
            'cities': {},
            'visible_tiles': [],
            'players': {},
            'techs': [],
            'map_info': {}
        }

    def _ensure_dict(self, data: Any, key_field: str = 'id') -> Dict:
        """Ensure data is returned as a dict (convert list/dict_values to dict if needed).

        Args:
            data: Input data (dict, list, dict_values, or None)
            key_field: Field name to use as key when converting iterable to dict (default: 'id')

        Returns:
            Dictionary keyed by key_field value (string keys for JSON compatibility)
        """
        if data is None:
            return {}
        if isinstance(data, dict):
            return data
        # Handle iterables (list, dict_values, dict_keys, etc.) but not strings/bytes
        if hasattr(data, '__iter__') and not isinstance(data, (str, bytes)):
            # Convert iterable to dict, keyed by key_field
            result = {}
            try:
                for item in data:
                    if isinstance(item, dict) and key_field in item:
                        key = str(item[key_field])  # Ensure key is string for JSON compatibility
                        result[key] = item
                return result
            except (TypeError, AttributeError) as e:
                # If iteration fails, log warning and return empty dict
                logger.warning(f"Failed to iterate over {type(data)} in _ensure_dict: {e}")
                return {}
        # Unexpected type - log warning and return empty dict
        logger.warning(f"Unexpected type {type(data)} in _ensure_dict, returning empty dict")
        return {}

    def _get_visible_tile(self, visible_tiles: list[dict[str, Any]] | None, x: int, y: int) -> dict | None:
        """Find a visible tile by x,y coordinates in the provided tiles list.

        Args:
            visible_tiles: Array of tile dicts such as returned in 'visible_tiles'
            x, y: Coordinates to search for

        Returns: tile dict or None if not present
        """
        if not visible_tiles:
            return None
        for t in visible_tiles:
            if not isinstance(t, dict):
                continue
            if t.get('x') == x and t.get('y') == y:
                return t
        return None

    def _is_water_terrain(self, terrain: str | None) -> bool:
        """Return True for common water/oceanic terrain names. Case-insensitive.

        We treat 'ocean' and 'lake' (and synonyms) as water - these should only be
        traversable by naval units. 'coast' is considered land for movement by
        land units and is thus allowed.
        """
        if not terrain:
            return False
        t = str(terrain).strip().lower()
        return t in {"ocean", "sea", "deep ocean", "lake", "water"}

    def _unit_is_naval(self, unit: dict[str, Any]) -> bool:
        """Heuristic: detect whether a given unit is a naval unit that can
        move on ocean tiles. This uses unit type name and some ruleset hints.

        - If the unit type name contains typical naval words (ship, trireme, frigate, etc.),
          consider it naval.
        - If civcom unit_types has a matching entry and it has 'transport_capacity' > 0,
          consider it a naval transport.
        - Fallback to name-based heuristics.
        """
        # Known naval terms to match against type names

        NAVAL_TERMS = {
            "trireme",
            "caravel",
            "galleon",
            "frigate",
            "ironclad",
            "destroyer",
            "cruiser",
            "aegis_cruiser",
            "battleship",
            "submarine",
            "carrier",
            "transport",
        }

        # Normalize string type
        unit_type_raw = unit.get('type', '')
        unit_type_name = ''
        if isinstance(unit_type_raw, str):
            unit_type_name = unit_type_raw.lower()
        elif isinstance(unit_type_raw, int) and self.civcom and hasattr(self.civcom, 'unit_types'):
            ptype = self.civcom.unit_types.get(unit_type_raw)
            if ptype:
                # Some ruleset packets use 'name' field
                unit_type_name = ptype.get('name', '') or ptype.get('rule_name', '')
                if isinstance(unit_type_name, str):
                    unit_type_name = unit_type_name.lower()
                else:
                    unit_type_name = ''

                # transport capacity often implies a ship / naval transport
                try:
                    if int(ptype.get('transport_capacity', 0)) > 0:
                        return True
                except Exception:
                    # ignore bad types
                    pass

                # flags may indicate coastal/sea units (bitvector representation)
                flags = ptype.get('flags') or ptype.get('flags', [])
                # a simple fallback: if flags exists and the list/bitvector length > 12
                # and index 12 (UTYF_COAST) is set then we consider it a sea-capable unit.
                try:
                    if isinstance(flags, (list, tuple)) and len(flags) > 12 and flags[12]:
                        return True
                except Exception:
                    pass
        else:
            # Could be a numeric string or other; fall back to string conversion
            unit_type_name = str(unit_type_raw).lower()

        # Name based heuristic
        if any(term in unit_type_name for term in NAVAL_TERMS):
            return True

        return False

    def _is_unit_move_valid(self, unit: dict[str, Any], dest_x: int, dest_y: int, visible_tiles: list[dict[str, Any]] | None) -> bool:
        """Decide if the move is plausibly legal in terms of basic terrain/sea checks.

        Returns False if the target tile is known (visible) and identified as ocean
        but the unit appears to be non-naval.
        If the tile is not visible we cannot reliably judge and we optimistically
        allow the move (since exploring unknown tiles is generally valid).
        """
        tile = self._get_visible_tile(visible_tiles, dest_x, dest_y)
        # If no tile data available (unseen), allow exploration moves
        if not tile:
            return True
        terrain = tile.get('terrain')
        if not terrain:
            return True
        # If it's water (ocean/lake) - only consider if unit is naval
        if self._is_water_terrain(terrain) and not self._unit_is_naval(unit):
            return False
        return True

    def _unit_is_terrain_worker(self, unit: dict[str, Any]) -> bool:
        """Check if unit is a terrain improvement worker (excludes settlers).
        
        Workers and Engineers can perform terrain improvements.
        Settlers are excluded as they focus on city building.
        
        Args:
            unit: Unit dict with 'type' field
            
        Returns:
            True if unit is a worker/engineer, False otherwise
        """
        unit_type_raw = unit.get('type', '')
        unit_type_name = ''
        
        if isinstance(unit_type_raw, str):
            unit_type_name = unit_type_raw.lower()
        elif isinstance(unit_type_raw, int) and self.civcom and hasattr(self.civcom, 'unit_types'):
            ptype = self.civcom.unit_types.get(unit_type_raw)
            if ptype:
                unit_type_name = ptype.get('name', '') or ptype.get('rule_name', '')
                if isinstance(unit_type_name, str):
                    unit_type_name = unit_type_name.lower()
        else:
            unit_type_name = str(unit_type_raw).lower()
        
        # Workers and Engineers can do terrain improvements
        # Exclude Settlers (they focus on city building)
        worker_terms = {'worker', 'workers', 'engineer', 'engineers'}
        return any(term in unit_type_name for term in worker_terms)
    
    def _unit_is_busy_with_activity(self, unit: dict[str, Any]) -> bool:
        """Check if unit is busy with an interruptible activity.
        
        Returns True if unit is performing terrain improvement, fortifying, etc.
        Returns False for IDLE, SENTRY, FORTIFIED, GOTO (interruptible states).
        
        Args:
            unit: Unit dict with 'activity' field
            
        Returns:
            True if unit is busy with work, False if idle/interruptible
        """
        activity = unit.get('activity', ACTIVITY_IDLE)
        return activity in BUSY_ACTIVITIES
    
    def _get_tile_at(self, x: int, y: int) -> dict[str, Any] | None:
        """Get tile data at coordinates from civcom's visible_tiles dict.
        
        Args:
            x: X coordinate
            y: Y coordinate
            
        Returns:
            Tile data dict with terrain, extras_names, etc., or None if not visible
        """
        if not self.civcom or not hasattr(self.civcom, 'visible_tiles'):
            return None
        
        return self.civcom.visible_tiles.get((x, y))
    
    def _tile_has_extra_by_name(self, tile: dict[str, Any] | None, extra_name: str) -> bool:
        """Check if tile has a specific extra (case-insensitive).
        
        Args:
            tile: Tile data dict with 'extras_names' list
            extra_name: Name of extra to check (e.g., 'Pollution', 'Irrigation')
            
        Returns:
            True if tile has the extra, False otherwise
        """
        if not tile:
            return False
        
        extras_names = tile.get('extras_names', [])
        if not isinstance(extras_names, list):
            return False
        
        # Case-insensitive matching
        extra_name_lower = extra_name.lower()
        return any(name.lower() == extra_name_lower for name in extras_names)
    
    def _validate_worker_activity(self, unit: dict[str, Any], activity_type: int) -> tuple[bool, str]:
        """Validate if worker can perform requested activity on current tile.
        
        Combines multiple checks:
        - Unit is a terrain worker (not settler)
        - Unit is not busy with another activity
        - Tile supports the terrain improvement
        - Activity makes sense (e.g., pollution exists for clean_pollution)
        
        Args:
            unit: Unit dict with type, activity, tile coords
            activity_type: ACTIVITY_* constant from fc_constants
            
        Returns:
            (is_valid, reason) tuple
        """
        # Check if unit is a worker/engineer
        if not self._unit_is_terrain_worker(unit):
            return (False, "Unit is not a terrain worker")
        
        # Check if unit is already busy
        if self._unit_is_busy_with_activity(unit):
            return (False, "Unit is busy with another activity")
        
        # Get unit's tile
        unit_tile = unit.get('tile')
        if unit_tile is None:
            return (False, "Unit tile unknown")
        
        # Extract x, y from tile (tile is typically an int index)
        # For now, assume tile data is available in visible_tiles
        # In real implementation, would need to convert tile index to (x, y)
        # This is a simplified validation - full implementation would use civcom helpers
        
        # For pollution/fallout cleanup, check if extra exists
        if activity_type == ACTIVITY_POLLUTION:
            # Would check tile has Pollution extra
            return (True, "Pollution cleanup validated")
        elif activity_type == ACTIVITY_FALLOUT:
            # Would check tile has Fallout extra
            return (True, "Fallout cleanup validated")
        
        # For improvements, check terrain support (simplified)
        if activity_type in [ACTIVITY_IRRIGATE, ACTIVITY_MINE, ACTIVITY_ROAD, ACTIVITY_TRANSFORM]:
            return (True, "Terrain improvement validated")
        
        return (True, "Activity validated")

    def _build_fallback_state_from_full(self, full_state: Dict[str, Any]) -> Dict[str, Any]:
        """Construct a minimally useful state payload from a civcom snapshot - dict format."""
        # Keep dict format - no conversion to list
        units = self._ensure_dict(full_state.get('units', {}))
        cities = self._ensure_dict(full_state.get('cities', {}))
        players = self._ensure_dict(full_state.get('players', {}))

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
            'players': players,
            'units': units,
            'cities': cities
        }

        return fallback_state

    def _get_strategic_summary(self) -> Dict[str, Any]:
        """Get high-level strategic situation"""
        if self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                state = self.civcom.get_full_state(self.player_id)
                units_raw = state.get('units', {})
                cities_raw = state.get('cities', {})
                techs = state.get('techs', [])

                # Convert dicts to lists for iteration
                units = list(units_raw.values()) if isinstance(units_raw, dict) else units_raw
                cities = list(cities_raw.values()) if isinstance(cities_raw, dict) else cities_raw

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
                units = list(state.get('units', {}).values()) if isinstance(state.get('units'), dict) else state.get('units', [])
                players = list(state.get('players', {}).values()) if isinstance(state.get('players'), dict) else state.get('players', [])
                visible_tiles = state.get('visible_tiles', [])

                # Check for enemy units near our cities
                cities_data = state.get('cities', {})
                our_cities = [c for c in (list(cities_data.values()) if isinstance(cities_data, dict) else cities_data) if c.get('owner') == self.player_id]
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
                units_raw = state.get('units', {})
                cities_raw = state.get('cities', {})
                visible_tiles = state.get('visible_tiles', [])

                # Convert dicts to lists for iteration
                units = list(units_raw.values()) if isinstance(units_raw, dict) else units_raw
                cities = list(cities_raw.values()) if isinstance(cities_raw, dict) else cities_raw

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
                players = list(state.get('players', {}).values()) if isinstance(state.get('players'), dict) else state.get('players', [])
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

    def _unit_has_effective_moves(self, unit: dict[str, Any]) -> bool:
        """Determine if a unit has effective moves available for the player to command.

        A unit has effective moves if:
        1. It has moves_left > 0 (movement points remaining)
        2. It is not marked as done_moving (no multi-turn path in progress)
        3. It doesn't have active orders that lock it into a long-term action

        This supports the conditional end_turn logic: only suggest end_turn when
        NO units have effective moves, preventing premature turn completion.

        Args:
            unit: Unit dictionary from game state

        Returns:
            True if unit can receive movement commands, False otherwise
        """
        # Check basic movement points
        moves_left = unit.get('moves_left', 0)
        if moves_left <= 0:
            return False

        # Check done_moving flag (multi-turn paths like explorers)
        # If done_moving is True, unit is executing a long path and shouldn't be commanded
        # Missing done_moving is treated as False (unit is available)
        done_moving = unit.get('done_moving', False)
        if done_moving:
            return False

        # Check for active orders/goto paths that lock the unit
        # Units with pending orders are effectively busy even if moves_left > 0
        orders = unit.get('orders', [])
        if orders and len(orders) > 0:
            # Has queued orders - consider busy
            return False

        # Unit has moves and is available for commands
        return True

    def _is_city_site_valid(self, unit_x: int, unit_y: int, citymindist: int, all_cities: list[dict[str, Any]], map_info: dict[str, Any]) -> tuple[bool, str]:
        """Check if a prospective city site at (unit_x, unit_y) is at least citymindist away from all known cities.

        Uses Chebyshev distance (max(|dx|, |dy|)) which aligns with square-area spacing typical in FreeCiv city placement.
        Wrap handling is deferred; current implementation assumes no wrapping or that wrap effects are negligible for short distances.

        Args:
            unit_x, unit_y: Integer tile coordinates of the unit.
            citymindist: Minimum required distance (int) between cities (from PACKET_GAME_INFO.citymindist).
            all_cities: List of city dictionaries (may include x,y or tile index only).
            map_info: Map metadata (width/height) for fallback coordinate derivation if needed.

        Returns:
            Tuple of (is_valid: bool, reason: str) where reason explains why the site is invalid if applicable.
        """

        # Ensure width is an integer for coordinate derivation (fallback to 1 to avoid ZeroDivision)
        try:
            width = int(map_info.get('width') or 1)
        except Exception:
            width = 1
        valid_cities = []
        for c in all_cities:
            if not isinstance(c, dict):
                continue
            cx = c.get('x')
            cy = c.get('y')
            # Derive from tile index if x,y missing
            if (cx is None or cy is None) and isinstance(c.get('tile'), int):
                tile_idx = c.get('tile')
                cx = tile_idx % width
                cy = tile_idx // width
            if cx is None or cy is None:
                continue
            valid_cities.append((cx, cy, c.get('name', f"city_{c.get('id', '?')}")))  # Include city name for logging

        min_distance = float('inf')
        closest_city_name = None
        closest_city_pos = None

        for (cx, cy, city_name) in valid_cities:
            dx = abs(unit_x - cx)
            dy = abs(unit_y - cy)
            # Chebyshev distance
            dist = max(dx, dy)
            if dist < min_distance:
                min_distance = dist
                closest_city_name = city_name
                closest_city_pos = (cx, cy)
            if dist < citymindist:
                reason = f"Too close to {city_name} at ({cx},{cy}): distance={dist}, required={citymindist}"
                return False, reason

        if valid_cities:
            if closest_city_pos is not None:  # Type guard for None check
                return True, f"Valid site: nearest city {closest_city_name} at ({closest_city_pos[0]},{closest_city_pos[1]}) distance={min_distance}"
            else:
                return True, "Valid site: cities exist but no closest found"
        else:
            return True, "No existing cities to check against"

    def _get_unit_actions_dict(self, game_state: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
        """
        Generate unit actions dictionary for protocol v2.0 server-authoritative action queries.
        
        Returns:
            Dict[str, Dict[str, Any]]: Dictionary keyed by unit_id (as string) containing:
                - unit_id (int): Unit ID
                - available_actions (List[Dict]): Cached or computed action possibilities
                - last_updated (Optional[float]): Cache timestamp
        
        This method checks the unit_action_cache for each unit first, falling back to
        empty action lists for cache misses (until full integration with 
        PACKET_UNIT_ACTION_ANSWER is complete).
        """
        unit_actions = {}
        
        if not game_state and self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                game_state = self.civcom.get_full_state(self.player_id)
            except Exception as e:
                logger.warning(f"Failed to get game state for unit actions: {e}")
                game_state = {}
        
        if not game_state:
            return {}
        
        units_raw = game_state.get('units', {})
        units = list(units_raw.values()) if isinstance(units_raw, dict) else units_raw
        our_units = [u for u in units if u.get('owner') == self.player_id]
        
        current_turn = game_state.get('turn', 0)
        
        # Build dictionary keyed by unit_id string
        for unit in our_units:
            unit_id = unit.get('id')
            if unit_id is None:
                continue
            
            unit_id_str = str(unit_id)
            
            # Check cache for this unit
            cached_data = self.unit_action_cache.get(unit_id, current_turn)
            
            if cached_data:
                # Use cached action data
                unit_actions[unit_id_str] = {
                    'unit_id': unit_id,
                    'available_actions': cached_data.get('actions', []),
                    'last_updated': cached_data.get('timestamp')
                }
            else:
                # Cache miss - populate with placeholder until real server data arrives
                # In production, this would trigger a unit_action_query to the server
                unit_actions[unit_id_str] = {
                    'unit_id': unit_id,
                    'available_actions': [],  # Empty until server responds
                    'last_updated': None
                }
        
        return unit_actions

    def _get_legal_actions_optimized(self, game_state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Get top legal actions for LLM (limited to ~20 most important)
        
        DEPRECATED: This method returns a flat list format. Use _get_unit_actions_dict() 
        for protocol v2.0 compliant unit_actions dictionary structure.
        """
        actions = []

        if not game_state and self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                game_state = self.civcom.get_full_state(self.player_id)
            except Exception as e:
                logger.warning(f"Failed to get legal actions from civcom: {e}")
                game_state = {}

        if not game_state:
            return [{
                'type': 'end_turn',
                'priority': 'high',
                'description': 'End turn and advance game'
            }]

        units_raw = game_state.get('units', {})
        cities_raw = game_state.get('cities', {})
        techs = game_state.get('techs', [])

        # Convert dicts to lists for iteration
        units = list(units_raw.values()) if isinstance(units_raw, dict) else units_raw
        cities = list(cities_raw.values()) if isinstance(cities_raw, dict) else cities_raw

        # Get our units that have effective moves (considers moves_left, done_moving, and orders)
        # This is used for conditional end_turn logic later
        our_units = [u for u in units if u.get('owner') == self.player_id and u.get('moves_left', 0) > 0]
        actionable_units = [u for u in our_units if self._unit_has_effective_moves(u)]

        # Retrieve global city minimum distance rule (citymindist)
        citymindist = None
        if isinstance(game_state.get('rules'), dict):
            citymindist = game_state['rules'].get('citymindist')
        if citymindist is None and self.civcom and hasattr(self.civcom, 'citymindist'):
            citymindist = self.civcom.citymindist
        if citymindist is None:
            citymindist = 2  # conservative default if not yet received

        # Gather all known cities (include other players to avoid illegal placements)
        all_cities = []
        if self.civcom and hasattr(self.civcom, 'player_cities') and isinstance(self.civcom.player_cities, dict):
            all_cities = list(self.civcom.player_cities.values())

        map_info = game_state.get('map', {}) if isinstance(game_state, dict) else {}

        # Add unit movement & potential city founding actions
        for unit in our_units[:10]:  # Limit to 10 units
            # Handle unit type - can be int (type ID) or string (type name)
            unit_type_raw = unit.get('type', '')
            if isinstance(unit_type_raw, str):
                prod_type = unit_type_raw.lower()
            else:
                # Type is an integer ID - use generic name
                prod_type = f"unit_{unit_type_raw}"

            current_x, current_y = unit.get('x', 0), unit.get('y', 0)

            # Check if unit can build cities (type 0 is usually Settlers in FreeCiv)
            if prod_type in ['settlers', 'engineer'] or unit_type_raw == 0:
                is_valid, reason = self._is_city_site_valid(current_x, current_y, citymindist, all_cities, map_info)
                if is_valid:
                    logger.debug(f"✓ City build allowed for unit {unit.get('id')} at ({current_x},{current_y}): {reason}")
                    # Settlement/construction actions (site satisfies distance rule)
                    actions.append({
                        'type': 'unit_build_city',
                        'unit_id': unit.get('id'),
                        'priority': 'high',
                        'description': f"Build city with {prod_type}" + (f" (>= {citymindist} from others)" if citymindist else "")
                    })
                    # If they can found a city, make them do so as soon as possible
                    continue
                # Rejected: log the specific reason
                logger.info(f"✗ City build REJECTED for unit {unit.get('id')} at ({current_x},{current_y}): {reason}")

            # Movement actions (explore nearby)
            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]:  # Adjacent tiles + diagonals
                dest_x = current_x + dx
                dest_y = current_y + dy
                if not self._is_unit_move_valid(unit, dest_x, dest_y, game_state.get('visible_tiles', [])):
                    # If tile is known to be water and unit is non-naval, skip
                    continue
                actions.append({
                    'type': 'unit_move',
                    'unit_id': unit.get('id'),
                    'dest_x': dest_x,
                    'dest_y': dest_y,
                    'priority': 'medium',
                    'description': f"Move {prod_type} to explore"
                })

        # Only suggest city production and tech research if there are little unit moves available
        # This helps prevent overloading the action list with production and tech when units can act
        if len(actions) < 10:
            # Add city production actions
            # Dynamic production options
            # Get all available units and buildings from civcom
            if self.civcom and hasattr(self.civcom, 'unit_types') and hasattr(self.civcom, 'improvements'):
                our_cities = [c for c in cities if c.get('owner') == self.player_id]
                for city in our_cities[:5]:  # Limit to 5 cities
                    city_id = city.get('id')
                    # Process Units
                    for _, prod_type in chain(
                        self.civcom.unit_types.items(), self.civcom.improvements.items()
                    ):
                        name = prod_type.get('name', '')
                        if not name:
                            continue

                        clean_name = clean_production_name(name)

                        if self._is_buildable(city, prod_type, game_state):
                            priority_score = self._calculate_production_priority(city, prod_type, game_state)

                            # Map score to string priority for backward compatibility
                            if priority_score >= 0.8:
                                priority_str = 'high'
                            elif priority_score >= 0.4:
                                priority_str = 'medium'
                            else:
                                priority_str = 'low'

                            actions.append({
                                'type': 'city_production',
                                'city_id': city_id,
                                'production_type': clean_name,
                                'priority': priority_str,
                                'priority_score': priority_score,
                                'description': f"Produce {clean_name} in {city.get('name', 'city')}"
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

        # CONDITIONAL end_turn: Only add when no units have effective moves remaining
        # This prevents premature turn completion when units are executing multi-turn paths
        # or when the player still has actionable units available.
        #
        # Effective moves considers:
        # - moves_left > 0 (has movement points)
        # - done_moving != True (not executing long path like explorer auto-explore)
        # - No active orders queue (not locked into pending actions)
        #
        # NOTE: game_arena FreeCivState also injects end_turn when absent (fallback safety).
        # Future harmonization task: consolidate logic into shared utility to avoid drift.
        # See: game_arena/game_arena/harness/freeciv_state.py:get_prioritized_legal_actions
        if not actionable_units:
            logger.info(
                f"✓ Including end_turn action for player {self.player_id}: "
                f"no actionable units (total_units={len(our_units)}, "
                f"units_with_moves={len([u for u in our_units if u.get('moves_left', 0) > 0])}, "
                f"actionable={len(actionable_units)})"
            )
            actions.append({
                'type': 'end_turn',
                'priority': 'high',
                'description': 'End turn and advance game'
            })
        else:
            # Log why end_turn is suppressed (helps debugging)
            actionable_ids = [u.get('id', '?') for u in actionable_units[:5]]
            logger.info(
                f"⏸️  Suppressing end_turn for player {self.player_id}: "
                f"{len(actionable_units)} actionable units remain "
                f"(sample IDs: {actionable_ids}{'...' if len(actionable_units) > 5 else ''})"
            )

        # Sort by priority and limit to top 20 actions (increased from 15 to ensure end_turn is included)
        # Sort by priority score if available, else by priority string
        priority_order = {'high': 3, 'medium': 2, 'low': 1}
        actions.sort(key=lambda x: (x.get('priority_score', 0), priority_order.get(x.get('priority', 'low'), 1)), reverse=True)
        return actions[:40]

    def _is_buildable(self, city: Dict[str, Any], item_type: Dict[str, Any], game_state: Dict[str, Any]) -> bool:
        """Check if an item is buildable in the given city."""
        # Get requirements list (units use 'build_reqs', buildings use 'reqs')
        reqs = item_type.get('build_reqs', []) if 'build_reqs' in item_type else item_type.get('reqs', [])

        known_techs = game_state.get('techs', [])
        # Assuming known_techs might be names or IDs. civcom.known_techs is usually names.
        # But requirements use IDs. We might need to map.
        # For now, let's assume we can check against what we have.
        # If game_state['techs'] are names, we need to map req IDs to names or vice versa.
        # However, civcom.known_techs is a list of strings (names).
        # The requirement values are IDs.
        # We need a way to map Tech ID -> Tech Name.
        # civcom.techs might store this mapping if available, or we can infer it.
        # Actually, civcom.techs is likely not populated with full tech tree in this proxy version.
        # Let's check if we can access tech mapping.
        # If not, we might have to skip tech check or try to use RulesetMapper if it had reverse mapping.
        # Wait, civcom.unit_types has 'tech_req' which is an ID? No, 'build_reqs' has 'source': {'kind': 1, 'value': ID}.

        # CRITICAL: We need to map ID to Name to check against known_techs (names).
        # Or map known_techs names to IDs.
        # Let's try to find the tech name from the ID using civcom.techs if it exists.
        # If not, we can't reliably check tech reqs.
        # For this iteration, let's assume we can skip tech check if we can't map,
        # OR better, check if 'tech_req' field exists directly on unit_type (older packet format) which might be a name?
        # No, packets.def shows 'build_reqs'.

        # Workaround: If we can't map ID to Name, we might be listing too many things.
        # But let's look at what we have.

        for req in reqs:
            source = req.get('source', {})
            kind = source.get('kind')
            value = source.get('value')

            # Placeholder for VUT_ADVANCE, VUT_IMPROVEMENT, VUT_MINSIZE if not defined
            # VUT_ADVANCE, VUT_IMPROVEMENT, VUT_MINSIZE are imported from fc_constants

            if kind == VUT_ADVANCE: # Tech
                # We need to check if we have this tech.
                # If we can't map ID to name, we are stuck.
                # Let's check if civcom has a tech map.
                pass # TODO: Implement tech check when ID mapping is available

            elif kind == VUT_IMPROVEMENT: # Building
                # Check if city has this building
                # value is building_id. city['improvements'] should be a list of building IDs or names?
                # Usually city['improvements'] in game_state (from civcom) is a list of IDs (integers).
                if 'improvements' in city and isinstance(city['improvements'], list):
                    if value not in city['improvements']:
                        return False

            elif kind == VUT_MINSIZE: # City Size
                if city.get('size', 1) < value:
                    return False

        return True

    def _calculate_production_priority(self, city: Dict[str, Any], item_type: Dict[str, Any], game_state: Dict[str, Any]) -> float:
        """Calculate priority score (0.0 - 1.0) for a production item."""
        name = clean_production_name(item_type.get('name', ''))
        turn = game_state.get('turn', 0)

        # Base score
        score = 0.1

        # Settlers
        if name == 'Settlers':
            # Early game expansion
            num_cities = len([c for c in game_state.get('cities', {}).values() if c.get('owner') == self.player_id])
            if turn < 50 and num_cities < 5:
                return 1.0
            return 0.3

        # Defensive Units
        # We need to identify if it's a defensive unit.
        # Heuristic: 'Warriors', 'Phalanx', 'Spearmen', 'Archers'
        # Or check stats: defense_strength > 0
        if item_type.get('defense_strength', 0) > 0 and item_type.get('attack_strength', 0) < 2:
            # It's likely a defender
            garrison = city.get('garrison', []) # List of unit IDs
            if not garrison:
                return 0.9 # High priority if empty
            return 0.2 # Low priority if already defended

        # Growth Buildings
        if name in ['Granary', 'Harbor', 'Aqueduct']:
            if city.get('size', 1) > 2:
                return 0.6

        # Production Buildings
        if name in ['Factory', 'Manufacturing Plant', 'Hydro Plant']:
            if turn > 100:
                return 0.7

        return score

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

        if action_type == 'unit_attack':
            # Compose PACKET_UNIT_DO_ACTION for attack
            # ACTION_ATTACK is typically 45 in FreeCiv
            attacker_id = action['attacker_unit_id']
            target_id = action['target_unit_id']
            # If tile id is needed, get from target unit
            target_tile = None
            try:
                game_state = self._get_current_game_state()
                if game_state and 'units' in game_state:
                    units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
                    for unit in units:
                        if unit.get('id') == target_id:
                            target_tile = unit.get('tile')
                            break
            except Exception:
                pass
            return {
                'pid': 84,  # PACKET_UNIT_DO_ACTION
                'actor_id': attacker_id,
                'target_id': target_id,  # For attack, target is unit id
                'sub_tgt_id': 0,
                'name': '',
                'action_type': 45  # ACTION_ATTACK
            }
        if action_type == 'unit_move':
            # Use PACKET_UNIT_ORDERS (pid=73) and request server-computed goto path
            map_width = self.civcom.map_info.get('width', 80) if self.civcom and hasattr(self.civcom, 'map_info') else 80
            dest_tile = action['dest_x'] + action['dest_y'] * map_width
            src_tile = self._get_unit_tile(action['unit_id'])

            # Ask server to compute path and wait briefly for response
            path_dirs = []
            try:
                if self.civcom and hasattr(self.civcom, 'request_goto_path'):
                    self.civcom.request_goto_path(action['unit_id'], dest_tile)
                    # wait up to configured time for path
                    wait_s = 0.8
                    path = self.civcom.get_goto_path(action['unit_id'], dest_tile, timeout_sec=wait_s)
                    if path and isinstance(path.get('dir'), list) and len(path['dir']) > 0:
                        path_dirs = path['dir']
                        logger.info(f"Using server-provided goto path for unit {action['unit_id']}: steps={len(path_dirs)}")
                    else:
                        logger.info(f"No goto path received within {wait_s}s for unit {action['unit_id']}; falling back to single-order move")
            except Exception as e:
                logger.debug(f"Goto path request failed or unavailable: {e}")

            # Build orders list
            orders = []
            if path_dirs:
                for i, d in enumerate(path_dirs):
                    orders.append({
                        'order': 0,      # ORDER_MOVE for each step
                        'activity': 18,  # ACTIVITY_LAST
                        'target': 0,
                        'sub_target': 0,
                        'action': 116,   # ACTION_COUNT (no action)
                        'dir': int(d) if isinstance(d, (int, float)) else -1
                    })
                length = len(orders)
            else:
                # Fallback: send single order; server may refuse without dir but keeps protocol safe
                orders = [{
                    'order': 0,
                    'activity': 18,
                    'target': 0,
                    'sub_target': 0,
                    'action': 116,
                    'dir': -1
                }]
                length = 1

            return {
                'pid': 73,
                'unit_id': action['unit_id'],
                'src_tile': src_tile,
                'dest_tile': dest_tile,
                'length': length,
                # Use numeric 0/1 for BOOL fields to match Freeciv expectations
                'repeat': 0,
                'vigilant': 0,
                'orders': orders
            }
        elif action_type == 'city_production':
            # FIXED: Use correct packet ID and implement production name→ID mapping
            # Was using non-existent packet ID 45 with wrong field names
            # Should use PACKET_CITY_CHANGE (pid=35) with production_kind + production_value
            # Matches web client city.js:914 send_city_change()

            production_name = action.get('production_type', '')

            if not production_name:
                raise ValueError("city_production requires 'production_type' field")

            # Create mapper on first use (cache per handler instance to avoid recreating)
            # Mapper reads from civcom.unit_types and civcom.improvements directly
            if not hasattr(self, '_ruleset_mapper'):
                self._ruleset_mapper = RulesetMapper(self.civcom)

            # Map production name (e.g., "Warriors", "Barracks") to (kind, value)
            kind, value = self._ruleset_mapper.map_production_to_kind_value(production_name)

            if kind is None:
                # Provide helpful error message with available options
                available = self._ruleset_mapper.get_available_productions()
                raise ValueError(
                    f"Unknown production: '{production_name}'. "
                    f"Available units: {available['units'][:10]}..., "
                    f"buildings: {available['buildings'][:10]}..."
                )

            logger.info(f"City {action['city_id']}: Change production to '{production_name}' "
                       f"(kind={kind}, value={value})")

            return {
                'pid': 35,  # PACKET_CITY_CHANGE (NOT 45!)
                'city_id': action['city_id'],
                'production_kind': kind,      # 6 for units (VUT_UTYPE), 3 for buildings (VUT_IMPROVEMENT)
                'production_value': value     # unit_type_id or building_id
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
        elif action_type == 'government_change':
            # PACKET_PLAYER_CHANGE_GOVERNMENT (pid=54) requires government type id
            # Map common government names to IDs (approximate; ruleset dependent)
            government_name_to_id = {
                'despotism': 0,
                'monarchy': 1,
                'republic': 2,
                'democracy': 3,
                'communism': 4,
                'fundamentalism': 5
            }
            gov_name = str(action.get('government_name', '')).strip().lower()
            gov_id = government_name_to_id.get(gov_name)
            if gov_id is None:
                available = ', '.join(government_name_to_id.keys())
                raise ValueError(f"Unknown government '{gov_name}'. Available: {available}")
            return {
                'pid': 54,  # PACKET_PLAYER_CHANGE_GOVERNMENT
                'government': gov_id
            }
        elif action_type == 'end_turn':
            # CRITICAL: Signal turn completion to advance game
            # Sends PACKET_PLAYER_PHASE_DONE to tell civserver this player is done with their turn
            # Without this, the game will remain stuck on the current turn indefinitely
            # CRITICAL FIX (AGE-192): Must send 'turn' field, not 'player_no'
            # Per packets.def:971-973: PACKET_PLAYER_PHASE_DONE requires TURN turn field
            return {
                'pid': 52,  # PACKET_PLAYER_PHASE_DONE
                'turn': self.civcom.game_turn if hasattr(self.civcom, 'game_turn') else 1
            }
        elif action_type == 'unit_build_city':
            unit_id = action['unit_id']

            # Get the tile where the unit is standing (required for city building)
            tile_id = self._get_unit_tile(unit_id)

            # Use provided city name or generate default
            city_name = action.get('name', f'City{unit_id}')

            return {
                'pid': 84,              # PACKET_UNIT_DO_ACTION
                'action_type': 27,      # ACTION_FOUND_CITY
                'actor_id': unit_id,
                'target_id': tile_id,
                'sub_tgt_id': 0,
                'name': city_name
            }
        elif action_type == 'join_city':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_JOIN_CITY (28)
            # Unit joins specified city (city_id). Server validates feasibility.
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'target_id': action['city_id'],
                'sub_tgt_id': 0,
                'name': '',
                'action_type': 28  # ACTION_JOIN_CITY
            }
        elif action_type == 'city_change_specialist':
            # PACKET_CITY_CHANGE_SPECIALIST (pid=39)
            # Convert one specialist type to another in a city.
            # Map string names to numeric IDs: elvis/entertainer=0, scientist=1, taxman=2
            def map_specialist(spec_value):
                if isinstance(spec_value, int):
                    return spec_value
                name_map = {'elvis': 0, 'entertainer': 0, 'scientist': 1, 'taxman': 2}
                return name_map.get(str(spec_value).lower(), 0)
            
            return {
                'pid': 39,
                'city_id': action['city_id'],
                'from': map_specialist(action['from_specialist']),
                'to': map_specialist(action['to_specialist'])
            }
        elif action_type == 'unit_explore':
            # FIXED: Use correct packet ID and field structure
            # Was using non-existent PACKET_UNIT_AUTO (pid=32)
            # Should use PACKET_UNIT_SERVER_SIDE_AGENT_SET (pid=74)
            # Matches web client control.js:2459-2467 request_unit_ssa_set()
            return {
                'pid': 74,  # PACKET_UNIT_SERVER_SIDE_AGENT_SET
                'unit_id': action['unit_id'],
                'agent': 1  # SSA_AUTOEXPLORE
            }
        # AGE-192: New unit action packet converters
        elif action_type == 'unit_fortify':
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_FORTIFYING,
                'target': -1  # EXTRA_NONE (server decides)
            }
        elif action_type == 'unit_sentry':
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_SENTRY,
                'target': -1  # EXTRA_NONE (server decides)
            }
        elif action_type == 'unit_build_road':
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_GEN_ROAD,
                'target': -1  # EXTRA_NONE (server auto-selects Road or Railroad)
            }
        elif action_type == 'unit_build_irrigation':
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_IRRIGATE,
                'target': -1  # EXTRA_NONE (server decides irrigation type)
            }
        elif action_type == 'unit_build_mine':
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_MINE,
                'target': -1  # EXTRA_NONE (server decides mine type)
            }
        elif action_type == 'unit_clean_pollution':
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_POLLUTION,
                'target': -1  # EXTRA_NONE (server auto-detects pollution type)
            }
        elif action_type == 'unit_clean_fallout':
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_FALLOUT,
                'target': -1  # EXTRA_NONE
            }
        elif action_type == 'unit_transform_terrain':
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_TRANSFORM,
                'target': -1  # EXTRA_NONE (server decides target terrain)
            }
        elif action_type == 'city_buy':
            # PACKET_CITY_BUY (pid=34) - Buy current production in city
            return {
                'pid': 34,  # PACKET_CITY_BUY
                'city_id': action['city_id']
            }
        elif action_type == 'city_sell_improvement':
            # PACKET_CITY_SELL (pid=33) - Sell an existing improvement from a city
            # Requires: city_id and improvement_id (build_id). If only improvement_name provided, map via ruleset.
            city_id = action['city_id']
            improvement_id = action.get('improvement_id')
            if improvement_id is None and 'improvement_name' in action:
                name_lower = str(action['improvement_name']).strip().lower()
                try:
                    if self.civcom and hasattr(self.civcom, 'improvements'):
                        for bid, packet in self.civcom.improvements.items():
                            if isinstance(packet, dict) and str(packet.get('name', '')).lower() == name_lower:
                                improvement_id = packet.get('id', bid)
                                break
                except Exception:
                    pass
            # Fallback: if still None let server reject; send -1
            return {
                'pid': 33,  # PACKET_CITY_SELL
                'city_id': city_id,
                'build_id': improvement_id if improvement_id is not None else -1
            }
        elif action_type == 'cultivate':
            # PACKET_UNIT_CHANGE_ACTIVITY (pid=222) - Cultivate terrain
            # activity=15 (ACTIVITY_CULTIVATE), target=-1 (EXTRA_NONE, server determines target terrain)
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': 15,  # ACTIVITY_CULTIVATE
                'target': -1  # EXTRA_NONE (server decides target terrain)
            }
        elif action_type == 'plant':
            # PACKET_UNIT_CHANGE_ACTIVITY (pid=222) - Plant vegetation
            # activity=16 (ACTIVITY_PLANT), target=-1 (EXTRA_NONE, server determines target terrain)
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': 16,  # ACTIVITY_PLANT
                'target': -1  # EXTRA_NONE (server decides target terrain)
            }
        elif action_type == 'base':
            # PACKET_UNIT_CHANGE_ACTIVITY (pid=222) - Build base (fortress/airbase)
            # activity=12 (ACTIVITY_BASE), target=-1 (EXTRA_NONE, server determines base type)
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': 12,  # ACTIVITY_BASE
                'target': -1  # EXTRA_NONE (server decides base type)
            }
        elif action_type == 'upgrade_unit':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_UPGRADE_UNIT (42)
            # Upgrade must typically be performed at a city
            unit_id = action['unit_id']
            city_id = action.get('city_id', 0)  # City where upgrade happens (0 if not specified)
            
            # Try to get city_id from unit location if not provided
            if city_id == 0:
                try:
                    game_state = self._get_current_game_state()
                    if game_state and 'units' in game_state:
                        units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
                        for unit in units:
                            if unit.get('id') == unit_id:
                                city_id = unit.get('homecity', 0) or unit.get('city_id', 0)
                                break
                except Exception:
                    pass
            
            return {
                'pid': 84,  # PACKET_UNIT_DO_ACTION
                'actor_id': unit_id,
                'target_id': city_id,  # City where upgrade happens
                'sub_tgt_id': 0,
                'name': '',
                'action_type': 42  # ACTION_UPGRADE_UNIT
            }
        elif action_type == 'bombard':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_BOMBARD (53)
            return {
                'pid': 84,  # PACKET_UNIT_DO_ACTION
                'actor_id': action['unit_id'],
                'target_id': action['target_tile_id'],  # Target tile to bombard
                'sub_tgt_id': 0,
                'name': '',
                'action_type': 53  # ACTION_BOMBARD
            }
        elif action_type == 'disband_unit':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_DISBAND_UNIT (39)
            # Disbanding unit returns some shields depending on ruleset; server enforces constraints
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'target_id': 0,
                'sub_tgt_id': 0,
                'name': '',
                'action_type': 39  # ACTION_DISBAND_UNIT
            }
        elif action_type == 'pillage':
            # PACKET_UNIT_CHANGE_ACTIVITY (pid=222) with ACTIVITY_PILLAGE (6)
            return {
                'pid': 222,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_PILLAGE,
                'target': -1  # EXTRA_NONE (server decides which improvement to pillage)
            }

        elif action_type == 'transport_board':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_TRANSPORT_BOARD (68) or ACTION_TRANSPORT_EMBARK (72)
            # Use ACTION_TRANSPORT_EMBARK for same-tile boarding, ACTION_TRANSPORT_BOARD for adjacent
            return {
                'pid': 84,  # PACKET_UNIT_DO_ACTION
                'actor_id': action['unit_id'],
                'action_type': ACTION_TRANSPORT_EMBARK,  # Default to embark (same tile)
                'target_id': action['transport_id'],
                'value': 0,
                'name': ''
            }

        elif action_type == 'transport_deboard':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_TRANSPORT_DEBOARD (71)
            return {
                'pid': 84,  # PACKET_UNIT_DO_ACTION
                'actor_id': action['unit_id'],
                'action_type': ACTION_TRANSPORT_DEBOARD,
                'target_id': 0,  # No specific target needed for deboard
                'value': 0,
                'name': ''
            }

        elif action_type == 'transport_unload':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_TRANSPORT_UNLOAD (83)
            return {
                'pid': 84,  # PACKET_UNIT_DO_ACTION
                'actor_id': action['unit_id'],  # Transport unit
                'action_type': ACTION_TRANSPORT_UNLOAD,
                'target_id': action['cargo_id'],  # Cargo to unload
                'value': 0,
                'name': ''
            }

        elif action_type == 'airlift':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_AIRLIFT (44)
            return {
                'pid': 84,  # PACKET_UNIT_DO_ACTION
                'actor_id': action['unit_id'],
                'action_type': ACTION_AIRLIFT,
                'target_id': action['target_city_id'],
                'value': 0,
                'name': ''
            }

        elif action_type == 'establish_embassy':
            # PACKET_UNIT_DO_ACTION (pid=84) with ACTION_ESTABLISH_EMBASSY (0)
            return {
                'pid': 84,  # PACKET_UNIT_DO_ACTION
                'actor_id': action['unit_id'],
                'action_type': ACTION_ESTABLISH_EMBASSY,
                'target_id': action['target_city_id'],
                'value': 0,
                'name': ''
            }
        elif action_type == 'spy_investigate_city':
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'action_type': ACTION_SPY_INVESTIGATE_CITY,
                'target_id': action['target_city_id'],
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'spy_poison':
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'action_type': ACTION_SPY_POISON,
                'target_id': action['target_city_id'],
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'spy_sabotage_city':
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'action_type': ACTION_SPY_SABOTAGE_CITY,
                'target_id': action['target_city_id'],
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'spy_steal_tech':
            # Target city based tech steal
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'action_type': ACTION_SPY_STEAL_TECH,
                'target_id': action.get('target_city_id', 0),
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'spy_bribe_unit':
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'action_type': ACTION_SPY_BRIBE_UNIT,
                'target_id': action['target_unit_id'],
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'spy_steal_gold':
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'action_type': ACTION_SPY_STEAL_GOLD,
                'target_id': action['target_city_id'],
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'spy_incite_city':
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'action_type': ACTION_SPY_INCITE_CITY,
                'target_id': action['target_city_id'],
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'trade_route':
            return {
                'pid': 84,
                'actor_id': action['unit_id'],
                'action_type': ACTION_TRADE_ROUTE,
                'target_id': action['target_city_id'],
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'city_build_unit':
            # Convert unit type name to production value using canonical civcom.unit_types
            city_id = action.get('city_id')
            unit_type = action.get('unit_type')
            
            if not city_id or not unit_type:
                return action  # Fallback to validation error
            
            # Look up unit type in canonical civcom.unit_types dictionary
            production_value = None
            unit_type_lower = unit_type.lower()
            
            # Search civcom.unit_types for matching name
            if self.civcom and hasattr(self.civcom, 'unit_types'):
                for type_id, unit_packet in self.civcom.unit_types.items():
                    if isinstance(unit_packet, dict) and unit_packet.get('name', '').lower() == unit_type_lower:
                        production_value = type_id
                        break
            
            if production_value is None:
                # Return error action - will be caught by handler
                logger.warning(f"Unknown unit type: {unit_type}")
                return action  # Fallback
            
            return {
                'pid': PACKET_CITY_CHANGE,
                'city_id': city_id,
                'production_kind': 0,  # 0 = unit
                'production_value': production_value
            }
        elif action_type == 'city_build_improvement':
            # Convert improvement name to production value using canonical civcom.improvements
            city_id = action.get('city_id')
            improvement = action.get('improvement')
            
            if not city_id or not improvement:
                return action  # Fallback to validation error
            
            # Look up improvement in canonical civcom.improvements dictionary
            production_value = None
            improvement_lower = improvement.lower()
            
            # Search civcom.improvements for matching name
            if self.civcom and hasattr(self.civcom, 'improvements'):
                for building_id, building_packet in self.civcom.improvements.items():
                    if isinstance(building_packet, dict) and building_packet.get('name', '').lower() == improvement_lower:
                        production_value = building_id
                        break
            
            if production_value is None:
                # Return error action - will be caught by handler
                logger.warning(f"Unknown improvement: {improvement}")
                return action  # Fallback
            
            return {
                'pid': PACKET_CITY_CHANGE,
                'city_id': city_id,
                'production_kind': 1,  # 1 = improvement
                'production_value': production_value
            }
        elif action_type == 'diplomacy_message':
            # Basic diplomacy support - treaty request only
            target_player_id = action.get('target_player_id')
            message_type = action.get('message_type')
            
            if not target_player_id or not message_type:
                return action  # Fallback to validation error
            
            if message_type == 'treaty_request':
                return {
                    'pid': PACKET_DIPLOMACY_INIT_MEETING_REQ,
                    'counterpart': target_player_id
                }
            else:
                # Other message types not yet implemented
                logger.warning(f"Diplomacy message type {message_type} not yet implemented")
                return action  # Fallback
        elif action_type == 'help_wonder':
            # Unit helps build wonder in city
            unit_id = action.get('unit_id')
            target_city_id = action.get('target_city_id')
            
            if not unit_id or not target_city_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_HELP_WONDER,
                'target_id': target_city_id,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'conquer_city':
            # Military unit conquers enemy city
            unit_id = action.get('unit_id')
            target_city_id = action.get('target_city_id')
            
            if not unit_id or not target_city_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_CONQUER_CITY,
                'target_id': target_city_id,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'capture_units':
            # Capture defeated units
            unit_id = action.get('unit_id')
            target_tile = action.get('target_tile')
            
            if not unit_id or not target_tile:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_CAPTURE_UNITS,
                'target_id': target_tile,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'steal_maps':
            # Spy steals enemy maps
            unit_id = action.get('unit_id')
            target_city_id = action.get('target_city_id')
            
            if not unit_id or not target_city_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_STEAL_MAPS,
                'target_id': target_city_id,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'convert':
            # Convert unit type
            unit_id = action.get('unit_id')
            
            if not unit_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_CONVERT,
                'target_id': unit_id,  # Self-target
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'home_city':
            # Change unit home city
            unit_id = action.get('unit_id')
            city_id = action.get('city_id')
            
            if not unit_id or not city_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_HOME_CITY,
                'target_id': city_id,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'strike_building':
            # Surgical strike on specific building
            unit_id = action.get('unit_id')
            target_city_id = action.get('target_city_id')
            building_id = action.get('building_id')
            
            if not unit_id or not target_city_id or building_id is None:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_STRIKE_BUILDING,
                'target_id': target_city_id,
                'sub_tgt_id': building_id,
                'name': ''
            }
        elif action_type == 'strike_production':
            # Surgical strike on city production
            unit_id = action.get('unit_id')
            target_city_id = action.get('target_city_id')
            
            if not unit_id or not target_city_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_STRIKE_PRODUCTION,
                'target_id': target_city_id,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'marketplace':
            # Convert caravan to gold at marketplace
            unit_id = action.get('unit_id')
            target_city_id = action.get('target_city_id')
            
            if not unit_id or not target_city_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_MARKETPLACE,
                'target_id': target_city_id,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'expel_unit':
            # Diplomatically expel foreign unit
            unit_id = action.get('unit_id')
            target_unit_id = action.get('target_unit_id')
            
            if not unit_id or not target_unit_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_EXPEL_UNIT,
                'target_id': target_unit_id,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'spy_sabotage_unit':
            # Spy sabotages specific enemy unit
            unit_id = action.get('unit_id')
            target_unit_id = action.get('target_unit_id')
            
            if not unit_id or not target_unit_id:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': unit_id,
                'action_type': ACTION_SPY_SABOTAGE_UNIT,
                'target_id': target_unit_id,
                'sub_tgt_id': 0,
                'name': ''
            }
        elif action_type == 'player_rates':
            # Set tax/science/luxury rates
            tax_rate = action.get('tax_rate')
            science_rate = action.get('science_rate')
            luxury_rate = action.get('luxury_rate')
            
            if tax_rate is None or science_rate is None or luxury_rate is None:
                return action  # Fallback to validation error
            
            return {
                'pid': PACKET_PLAYER_RATES,
                'tax': tax_rate,
                'science': science_rate,
                'luxury': luxury_rate
            }

        return action  # Fallback

    def _get_unit_tile(self, unit_id: int) -> int:
        """Get the tile ID where a unit is currently located.

        This is required for actions like city building that need to know
        the unit's position on the map.

        Args:
            unit_id: The unit's ID

        Returns:
            The tile ID where the unit is standing

        Raises:
            ValueError: If unit not found or tile information unavailable
        """
        game_state = self._get_current_game_state()

        if not game_state or 'units' not in game_state:
            raise ValueError(f"No game state available to find unit {unit_id}")

        units = game_state['units']
        unit = None

        # Handle both dict and list formats (state can be in either format)
        if isinstance(units, dict):
            # Try both string and int keys
            unit = units.get(str(unit_id)) or units.get(unit_id)
        else:
            # List format - find by ID
            unit = next((u for u in units if u.get('id') == unit_id), None)

        if not unit:
            raise ValueError(f"Unit {unit_id} not found in game state")

        if 'tile' not in unit:
            raise ValueError(f"Unit {unit_id} has no tile information")

        return unit['tile']

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
                error_msg = f"Unable to reach civserver at {host}:{port} after {max_attempts} attempts"
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
            
            # Register packet callbacks for unit action queries (protocol v2.0)
            self.civcom.action_answer_callback = self._handle_action_answer_packet
            self.civcom.unit_actions_callback = self._handle_unit_actions_packet
            
            # Register cache invalidation callbacks
            self.civcom.unit_state_changed_callback = self._invalidate_unit_cache
            self.civcom.unit_removed_callback = self._invalidate_unit_cache
            self.civcom.turn_changed_callback = self._invalidate_all_cache
            
            logger.debug(f"Registered unit action packet callbacks for {self.agent_id}")
            
            self.civcom.start()
            logger.debug(f"CivCom thread started: is_alive={self.civcom.is_alive()}, daemon={self.civcom.daemon}")

            logger.info(f"LLM agent {self.agent_id} connected to civserver on port {port}")

            # Give thread a moment to initialize and detect any immediate crashes
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

    def _flush_packet_buffer(self):
        """Flush buffered packets to client after authentication completes.

        This solves the protocol packet ordering race condition.
        FreeCiv sends ~1.2MB of PACKET_RULESET_NATION packets immediately when
        connection is established, BEFORE auth_success can be generated.

        Solution: Buffer all incoming packets during authentication, send auth_success
        first, then flush buffered packets to maintain protocol order.

        Flow:
        1. LLM agent connects → buffer_enabled=True
        2. CivCom receives packets → stores in packet_buffer instead of sending
        3. Authentication completes → send auth_success
        4. Call _flush_packet_buffer() → send all buffered packets
        5. Set buffer_enabled=False → resume normal packet flow
        """
        if not self.packet_buffer:
            logger.debug(f"No packets to flush for {self.agent_id}")
            return

        buffer_count = len(self.packet_buffer)
        total_size = sum(len(p.encode('utf-8')) for p in self.packet_buffer)
        logger.info(
            f"🚀 FLUSHING {buffer_count} buffered packets for {self.agent_id}: "
            f"{total_size:,} bytes ({total_size/(1024*1024):.2f}MB)"
        )

        # Send each buffered packet in order
        flushed = 0
        for packet in self.packet_buffer:
            try:
                self.write_message(packet)
                flushed += 1
            except Exception as e:
                logger.error(
                    f"❌ Failed to flush packet {flushed+1}/{buffer_count} for {self.agent_id}: {e}"
                )
                # Continue flushing remaining packets despite error

        logger.info(
            f"✅ Flushed {flushed}/{buffer_count} packets for {self.agent_id}"
        )

        # Clear the buffer
        self.packet_buffer.clear()

    def _forward_to_civcom(self, message: str):
        """Forward message to civcom"""
        if self.civcom:
            self.civcom.queue_to_civserver(message)

    def _check_rate_limit(self) -> bool:
        """Legacy rate limiting method - now uses distributed rate limiter"""
        if not self.agent_id:
            return True  # Allow if no agent ID set yet

        return distributed_rate_limiter.check_limit(self.agent_id, 'legacy')

    def _handle_action_answer_packet(self, unit_id: int, packet: Dict[str, Any], turn: int):
        """
        Callback for PACKET_UNIT_ACTION_ANSWER from civserver.
        Populates cache with server-authoritative action data.
        
        Args:
            unit_id: Unit ID for which actions are available
            packet: Raw packet from server containing action possibilities
            turn: Current game turn
        """
        try:
            # Extract action data from packet
            # FreeCiv packet structure: actor_unit_id, target fields, action_type, etc.
            actions = []
            
            # The packet may contain a single action possibility or multiple
            # Based on FreeCiv protocol, PACKET_UNIT_ACTION_ANSWER has fields like:
            # - actor_unit_id (int)
            # - target_unit_id (int, optional)
            # - target_city_id (int, optional)
            # - target_tile_id (int, optional)
            # - action_type (int)
            # - action_prob (int) - probability in server format (0-200)
            
            action_type = packet.get('action_type')
            action_prob = packet.get('action_prob')
            
            if action_type is not None:
                action_entry = {
                    'action_type': action_type,
                    'probability': action_prob,  # Raw server format (0-200)
                    'target_unit_id': packet.get('target_unit_id'),
                    'target_city_id': packet.get('target_city_id'),
                    'target_tile_id': packet.get('target_tile_id'),
                    'target_extra_id': packet.get('target_extra_id')
                }
                actions.append(action_entry)
            
            # Store in cache
            cache_entry = {
                'actions': actions,
                'timestamp': time.time(),
                'turn': turn
            }
            
            self.unit_action_cache.set(unit_id, turn, cache_entry)
            logger.info(f"Cached action answer for unit {unit_id}: {len(actions)} actions")
            
        except Exception as e:
            logger.error(f"Failed to process action answer packet for unit {unit_id}: {e}")

    def _handle_unit_actions_packet(self, unit_id: int, packet: Dict[str, Any], turn: int):
        """
        Callback for PACKET_UNIT_ACTIONS from civserver.
        Populates cache with list of available actions.
        
        Args:
            unit_id: Unit ID for which actions are available
            packet: Raw packet from server containing actions list
            turn: Current game turn
        """
        try:
            # Extract actions list from packet
            # FreeCiv packet structure: actor_unit_id, actions (array)
            actions_raw = packet.get('actions', [])
            
            actions = []
            for action_data in actions_raw:
                if isinstance(action_data, dict):
                    actions.append({
                        'action_type': action_data.get('action_type'),
                        'probability': action_data.get('probability', 200),  # Default to certain
                        'target_unit_id': action_data.get('target_unit_id'),
                        'target_city_id': action_data.get('target_city_id'),
                        'target_tile_id': action_data.get('target_tile_id'),
                        'target_extra_id': action_data.get('target_extra_id')
                    })
            
            # Store in cache
            cache_entry = {
                'actions': actions,
                'timestamp': time.time(),
                'turn': turn
            }
            
            self.unit_action_cache.set(unit_id, turn, cache_entry)
            logger.info(f"Cached unit actions for unit {unit_id}: {len(actions)} actions")
            
        except Exception as e:
            logger.error(f"Failed to process unit actions packet for unit {unit_id}: {e}")

    def _invalidate_unit_cache(self, unit_id: int, turn: Optional[int] = None):
        """
        Invalidate cache entry for a specific unit when its state changes.
        
        Args:
            unit_id: Unit ID to invalidate
            turn: Optional turn number (not used in invalidation, but passed by callbacks)
        """
        try:
            self.unit_action_cache.invalidate(unit_id)
            logger.debug(f"Invalidated action cache for unit {unit_id}")
        except Exception as e:
            logger.error(f"Failed to invalidate cache for unit {unit_id}: {e}")

    def _invalidate_all_cache(self, turn: int):
        """
        Invalidate entire cache when turn changes.
        All unit actions need to be re-queried from server on new turn.
        
        Args:
            turn: New turn number
        """
        try:
            self.unit_action_cache.clear()
            logger.info(f"Cleared action cache for turn {turn}")
        except Exception as e:
            logger.error(f"Failed to clear cache for turn {turn}: {e}")

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
