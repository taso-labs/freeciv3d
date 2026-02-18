#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
LLM WebSocket Handler for FreeCiv proxy
Handles headless LLM agent connections without browser requirements
"""

import json
import logging
import sys
import time
import uuid
import asyncio
import socket
from tornado import websocket
from tornado.ioloop import IOLoop
from civcom import CivCom
from state_cache import state_cache
from state_extractor import StateExtractor, StateFormat, civcom_registry
from observer_civcom import OBSERVER_AGENT_ID, stop_observer_civcom
from action_validator import LLMActionValidator, ActionType, ValidationResult
from config_loader import llm_config
from message_validator import MessageValidator, ValidationError
from security import InputSanitizer, SecurityError, SecurityLogger
from rate_limiter import DistributedRateLimiter
from session_manager import session_manager, SessionState, start_periodic_cleanup
from error_handler import error_handler, ErrorSeverity, ErrorCategory
from game_session_manager import game_session_manager
from ruleset_mapper import RulesetMapper
from typing import Dict, Any, Optional, List
from packet_constants import (
    PACKET_CHAT_MSG_REQ,
    PACKET_SERVER_JOIN_REQ,
    PACKET_UNIT_ORDERS,
    PACKET_CITY_CHANGE,
    PACKET_PLAYER_RESEARCH,
    PACKET_NATION_SELECT_REQ,
    PACKET_PLAYER_READY,
    PACKET_PLAYER_PHASE_DONE,
    PACKET_UNIT_DO_ACTION,
    PACKET_UNIT_SERVER_SIDE_AGENT_SET,
    PACKET_UNIT_CHANGE_ACTIVITY,
    PACKET_CITY_BUY,
    PACKET_CITY_SELL,
    PACKET_CITY_RENAME,
    PACKET_CITY_WORKLIST,
    PACKET_DIPLOMACY_INIT_MEETING_REQ,
    PACKET_DIPLOMACY_CANCEL_MEETING_REQ,
    PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
    PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ,
    PACKET_DIPLOMACY_ACCEPT_TREATY_REQ,
    PACKET_DIPLOMACY_CANCEL_PACT,
    PACKET_CHAT_MSG_REQ,
)
from action_constants import *
from activity_constants import *
from order_constants import *
from packet_converter import convert_action_to_packet
from tracing import init_tracing, extract_trace_context, inject_trace_context, create_child_span

# Configure logging to output to BOTH stdout (for GCloud) and file (for local debugging)
# GCloud Logging captures stdout from containers, but not file logs
import os

# Set up root logger for freeciv-proxy with stdout handler
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),  # GCloud captures stdout
    ]
)

logger = logging.getLogger("freeciv-proxy")
logger.setLevel(logging.DEBUG)  # Allow DEBUG level for file handler

# Add file handler for detailed debug logging (if directory exists)
try:
    debug_log_path = "/docker/logs/llm-handler-debug.log"
    log_dir = os.path.dirname(debug_log_path)
    if os.path.exists(log_dir):
        file_handler = logging.FileHandler(debug_log_path)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(file_handler)
        logger.info("LLM Handler file logging enabled: %s", debug_log_path)
    else:
        logger.debug("File logging disabled: directory %s does not exist (using stdout only)", log_dir)
except Exception as e:
    logger.warning("Could not initialize file logging: %s", e)

# Initialize distributed tracing (gracefully degrades if OpenTelemetry not available)
ENABLE_CLOUD_TRACE = os.getenv("ENABLE_CLOUD_TRACE", "false").lower() == "true"
init_tracing("freeciv-proxy", enable_cloud_trace=ENABLE_CLOUD_TRACE)

# Start periodic session cleanup (runs every 5 minutes via Tornado PeriodicCallback)
# This ensures expired sessions are cleaned up regardless of traffic patterns
start_periodic_cleanup(interval_ms=300000)  # 5 minutes

# Global registry for active LLM agents
llm_agents = {}
MAX_LLM_AGENTS = llm_config.get_max_agents()

# Packet buffer limits to prevent unbounded memory growth
# These protect against memory exhaustion if authentication hangs or fails
MAX_PACKET_BUFFER_SIZE = 200  # Maximum number of packets to buffer (typical game sends ~150 RULESET packets)
MAX_PACKET_BUFFER_BYTES = 5 * 1024 * 1024  # 5MB maximum buffer size (typical game ~1.2MB)

# Reconnection state verification constants
GAME_INFO_WAIT_TIMEOUT_SEC = 2.0  # Max wait for PACKET_GAME_INFO
GAME_INFO_POLL_INTERVAL_SEC = 0.1  # Polling interval
GAME_INFO_LOG_INTERVAL_SEC = 0.5  # Debug log frequency
TURN_DRIFT_TOLERANCE = llm_config.get('reconnection.turn_drift_tolerance', 5)  # Max acceptable turn drift during reconnection

# Stale connection retry constants — when civserver rejects join with "already connected"
STALE_CONN_HANDSHAKE_WAIT_SEC = 5.0  # Max wait for handshake reply from civserver
STALE_CONN_DISCONNECT_WAIT_SEC = 2.0  # Wait after force-closing old connection before retry

# Connection health monitoring - threshold for marking connection as dead
# After this many consecutive send failures, the connection is marked dead and game is paused
# Higher values provide more tolerance for transient network issues
CONNECTION_DEAD_FAILURE_THRESHOLD = llm_config.get('connection.dead_failure_threshold', 20)

# Unit actions that require movement points
# Used for local moves tracking in pre-submission validation
UNIT_ACTIONS_REQUIRING_MOVES = frozenset([
    'unit_move', 'unit_sentry', 'unit_fortify', 'unit_board',
    'unit_unload', 'unit_build_road', 'unit_build_mine',
    'unit_build_irrigation', 'unit_pillage', 'unit_explore'
])

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

# Global distributed rate limiter with config from llm_config.json
distributed_rate_limiter = DistributedRateLimiter(
    redis_config={
        'host': llm_config.get('redis.host', 'localhost'),
        'port': llm_config.get('redis.port', 6379),
        'password': llm_config.get('redis.password'),
        'db': llm_config.get('redis.db', 0)
    },
    rate_limit_config=llm_config.get('validation.rate_limit', {})
)

class LLMWSHandler(websocket.WebSocketHandler):
    """
    WebSocket handler for LLM agents
    Bypasses browser authentication and provides optimized game state access

    This is the PRODUCTION WebSocket handler for LLM agents.
    Endpoint: /llmsocket/8002
    Architecture: agent-clash → llm-gateway (port 8003) → LLMWSHandler → GameSession

    Player ID assignment uses GameSession.allocate_ai_slot() for sequential, thread-safe
    allocation (see game_session_manager.py). This integrates with civserver via /take commands.

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
        self.auto_ready = True
        self.last_state_query = 0
        self.action_validator = LLMActionValidator()
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
        from tornado import ioloop
        self.io_loop = ioloop.IOLoop.current()

        # Initialize message validator with configurable size limit
        max_size_mb = llm_config.get('validation.max_message_size_mb', 1.0)
        self.message_validator = MessageValidator(max_message_size=int(max_size_mb * 1024 * 1024))

        # Initialize state extractor for proper state formatting
        self.state_extractor = StateExtractor()

        # Local moves tracking for pre-submission validation
        # Tracks moves consumed per unit this turn to catch stale actions before server roundtrip
        # Format: {unit_id: moves_consumed_this_turn}
        # Reset on turn change
        self.unit_moves_consumed: Dict[int, int] = {}
        self.last_tracked_turn: Optional[int] = None

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

    def _abort_with_state_mismatch(
        self,
        expected_turn: int,
        actual_turn: int,
        hint: str,
        correlation_id: Optional[str] = None,
        waited: Optional[float] = None
    ) -> None:
        """Send state mismatch error and cleanup connection."""
        wait_info = f"\n   Waited: {waited:.1f}s for PACKET_GAME_INFO" if waited else ""
        logger.error(
            f"❌ STATE MISMATCH for {self.agent_id}:\n"
            f"   Expected turn: {expected_turn}\n"
            f"   Actual turn: {actual_turn}{wait_info}\n"
            f"   {hint}"
        )
        error_response = {
            'type': 'error',
            'code': 'E_STATE_MISMATCH',
            'message': f'Expected turn {expected_turn}, got turn {actual_turn}. Civserver game state was lost.',
            'expected_turn': expected_turn,
            'actual_turn': actual_turn,
            'recoverable': False,
            'hint': hint
        }
        if correlation_id:
            error_response['correlation_id'] = correlation_id
        self.write_message(json.dumps(error_response))
        self.buffer_enabled = False
        self.packet_buffer.clear()

    async def on_message(self, message):
        """Handle incoming WebSocket messages

        CRITICAL: This handler is async to properly support Tornado's async WebSocket pattern.
        Tornado 4.5+ allows on_message to be a coroutine, which keeps the connection alive
        until all async operations complete. This fixes the premature connection closure issue.
        """
        logger.debug(f"Received message from {self.agent_id or self.id}: {message[:200]}")

        # Parse message early to extract trace context
        try:
            msg_data_for_trace = json.loads(message)
        except json.JSONDecodeError:
            msg_data_for_trace = {}

        # Extract trace context from incoming message (propagated from llm-gateway)
        parent_ctx = extract_trace_context(msg_data_for_trace)
        msg_type = msg_data_for_trace.get('type', 'unknown')

        # Create a span for this message handling operation
        with create_child_span(
            f"proxy.handle_{msg_type}",
            parent_ctx,
            {"agent_id": self.agent_id or self.id, "message_type": msg_type}
        ) as span:
            try:
                # Session validation for authenticated agents
                if self.session_id and not self._validate_session():
                    span.set_attribute("error", True)
                    span.set_attribute("error.reason", "session_invalid")
                    self.write_message(json.dumps({
                        'type': 'error',
                        'code': 'E102',
                        'message': 'Session expired or invalid',
                        'requires_reconnect': True
                    }))
                    self.close()
                    return

                # NOTE: Session cleanup is now handled by PeriodicCallback (see start_periodic_cleanup)
                # rather than on every message, to ensure consistent cleanup regardless of traffic

                # Distributed rate limiting by agent ID
                if self.agent_id and not distributed_rate_limiter.check_limit(self.agent_id, 'message'):
                    span.set_attribute("error", True)
                    span.set_attribute("error.reason", "rate_limited")
                    error_response = error_handler.handle_rate_limit_error(
                        self.agent_id, 'message', 60
                    )
                    self.write_message(error_response.to_json())
                    return

                # Check burst rate limit as well
                if self.agent_id and not distributed_rate_limiter.check_burst_limit(self.agent_id):
                    span.set_attribute("error", True)
                    span.set_attribute("error.reason", "burst_limited")
                    error_response = error_handler.handle_rate_limit_error(
                        self.agent_id, 'burst', 60
                    )
                    self.write_message(error_response.to_json())
                    return

                # Validate and parse message
                try:
                    msg_data = self.message_validator.validate_message(message)
                except ValidationError as e:
                    span.set_attribute("error", True)
                    span.set_attribute("error.reason", "validation_failed")
                    span.set_attribute("error.code", e.error_code)
                    error_response = error_handler.handle_validation_error(
                        self.agent_id or "unknown", e.error_code, e.message,
                        self.session_id, message
                    )
                    self.write_message(error_response.to_json())
                    return

                # Store span reference for response injection
                self._current_span = span

                # Route message based on type
                msg_type = msg_data.get('type', '')

                if msg_type == 'llm_connect':
                    await self._handle_llm_connect(msg_data)
                elif msg_type == 'state_query':
                    await self._handle_state_query(msg_data)
                elif msg_type == 'action':
                    self._handle_action(msg_data)
                elif msg_type == 'ping':
                    self._handle_ping(msg_data)
                elif msg_type == 'player_ready':
                    self._handle_player_ready(msg_data)
                elif msg_type == 'unit_actions_query':
                    self._handle_unit_actions_query(msg_data)
                elif msg_type == 'city_actions_query':
                    self._handle_city_actions_query(msg_data)
                elif msg_type == 'chat':
                    self._handle_chat(msg_data)
                elif msg_type == 'global_state_query':
                    await self._handle_global_state_query(msg_data)
                elif self.is_llm_agent:
                    # Enhanced message forwarding with validation logging
                    # Log messages without "pid" field for debugging, but still forward them
                    # (Don't block - some control messages legitimately lack "pid")
                    try:
                        if "pid" not in msg_data:
                            # Log for debugging/metrics, but don't reject
                            logger.debug(
                                f"📋 Forwarding non-protocol message from {self.agent_id}: "
                                f"type={msg_data.get('type', 'unknown')}, keys={list(msg_data.keys())[:10]}"
                            )
                            span.set_attribute("message.has_pid", False)
                            span.set_attribute("message.keys", str(list(msg_data.keys())[:5]))
                        else:
                            # Standard FreeCiv protocol packet with pid
                            logger.debug(f"📋 Forwarding protocol packet pid={msg_data.get('pid')} from {self.agent_id}")
                            span.set_attribute("message.has_pid", True)
                            span.set_attribute("message.pid", msg_data.get('pid'))

                        # Always forward - let the C server decide if it's valid
                        self._forward_to_civcom(message)

                    except Exception as e:
                        logger.error(f"❌ Error processing message from {self.agent_id}: {e}")
                        span.set_attribute("error", True)
                        span.set_attribute("error.reason", "message_processing_exception")
                        # Still try to forward despite error
                        self._forward_to_civcom(message)
                else:
                    span.set_attribute("error", True)
                    span.set_attribute("error.reason", "unknown_message_type")
                    self.write_message(json.dumps({
                        'type': 'error',
                        'code': 'E103',
                        'message': 'Unknown message type or not authenticated'
                    }))

            except Exception as e:
                span.set_attribute("error", True)
                span.set_attribute("error.reason", "exception")
                span.set_attribute("error.message", str(e))
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
        
        # Extract correlation_id for request/response matching
        correlation_id = msg_data.get('correlation_id')

        try:
            # Extract agent info
            self.agent_id = msg_data.get('agent_id', f'agent-{self.id[:8]}')
            api_token = msg_data.get('api_token', '')

            # Extract expected_turn for state verification on reconnection
            # If provided, we'll verify the game state matches after reconnection
            expected_turn = msg_data.get('expected_turn')
            if expected_turn is not None:
                try:
                    expected_turn = int(expected_turn)
                    if expected_turn < 0:
                        logger.warning(f"Negative expected_turn={expected_turn} for {self.agent_id}, treating as None")
                        expected_turn = None
                except (ValueError, TypeError):
                    expected_turn = None
                    logger.warning(f"Invalid expected_turn value for {self.agent_id}, ignoring state verification")

            # Token validation using config
            if not llm_config.validate_token(api_token):
                error_response = error_handler.handle_authentication_error(
                    self.agent_id, "Invalid API token"
                )
                self.write_message(error_response.to_json())
                return

            # Extract game_id BEFORE session resume/creation
            # This is critical for:
            # 1. Validating session resume against the correct game (prevents E142 errors)
            # 2. Persisting game_id with new sessions for MySQL session persistence
            # LLM Gateway flattens nested 'data' field to top level before sending to proxy
            game_id = msg_data.get('game_id', f'game_{uuid.uuid4().hex[:8]}')

            # Check for existing suspended session to resume (reconnection support)
            # Uses atomic try_resume_session_for_agent with proper locking and token verification
            # IMPORTANT: Pass game_id to prevent resuming sessions from a different game
            is_reconnecting = False
            previous_player_id = None
            previous_civserver_port = None
            resumed_session = session_manager.try_resume_session_for_agent(self.agent_id, api_token, game_id)
            if resumed_session:
                self.session_info = resumed_session
                self.session_id = resumed_session.session_id
                is_reconnecting = True
                # Restore player_id and civserver_port from previous session
                previous_player_id = resumed_session.player_id
                previous_civserver_port = resumed_session.civserver_port
                if previous_player_id is not None:
                    self.player_id = previous_player_id
                logger.info(
                    f"Resumed suspended session {self.session_id} for {self.agent_id}\n"
                    f"   Restored player_id: {previous_player_id}\n"
                    f"   Restored civserver_port: {previous_civserver_port}\n"
                    f"   Game ID: {game_id}"
                )
            self.game_id = game_id

            # Fallback: Accept player_id from message for late reconnection
            # This handles the case where session expired but client retained player_id
            if not is_reconnecting:
                provided_player_id = msg_data.get('player_id')
                if provided_player_id is not None:
                    try:
                        provided_player_id = int(provided_player_id)
                        if 0 <= provided_player_id < 512:  # Valid player range (not observer)
                            previous_player_id = provided_player_id
                            is_reconnecting = True
                            logger.info(
                                f"🔄 Late reconnection for {self.agent_id} with provided player_id={provided_player_id}\n"
                                f"   Session expired but client retained player_id for game {game_id}"
                            )
                    except (ValueError, TypeError):
                        logger.warning(f"Invalid player_id provided by {self.agent_id}: {provided_player_id}")

            # Create new session if we don't have one from resume
            # Late reconnection (player_id provided, session expired) still needs a
            # fresh session for tracking, expiry, and activity management.
            if self.session_info is None:
                self.session_info = session_manager.create_session(
                    self.agent_id,
                    api_token,
                    game_id=game_id  # Link session to game for persistence
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

            # Allocate or reuse civserver port for this game_id
            # Reconnection: use stored port from session (game is still running there)
            # New connection: allocate new port from pool
            if is_reconnecting and previous_civserver_port is not None:
                civserver_port = previous_civserver_port
                logger.info(
                    f"Agent {self.agent_id} reconnecting to existing civserver:\n"
                    f"   Game ID: {game_id}\n"
                    f"   Civserver Port: {civserver_port} (restored from session)"
                )
            else:
                # First player: allocates new port (e.g., 6001)
                # Second player: reuses the same port (6001)
                # Players are automatically assigned slots by civserver when they connect
                civserver_port = await game_session_manager.allocate_civserver_port(game_id)
                port_type = (
                    "MULTIPLAYER (6001-6009)" if 6001 <= civserver_port <= 6009
                    else "SINGLEPLAYER (6000)" if civserver_port == 6000
                    else "UNKNOWN PORT"
                )
                logger.info(
                    f"Agent {self.agent_id} assigned to civserver:\n"
                    f"   Game ID: {game_id}\n"
                    f"   Civserver Port: {civserver_port}\n"
                    f"   Port Type: {port_type}"
                )

            # Store civserver_port in session for reconnection
            if self.session_info:
                self.session_info.civserver_port = civserver_port

            # Enable packet buffering IMMEDIATELY before connecting to civserver
            # The civserver sends ~1.2MB of PACKET_RULESET_NATION packets as soon as we connect
            # We MUST enable buffering BEFORE _connect_to_civserver() to capture these packets
            self.buffer_enabled = True
            logger.info(f"🔒 Packet buffering ENABLED for {self.agent_id} before civserver connection")

            # Connect to civserver - try to reuse existing CivCom on reconnection
            logger.info(f"🔌 Connecting agent {self.agent_id} to civserver port {civserver_port} (game: {game_id})")
            try:
                # CRITICAL: On reconnection, try to reuse existing CivCom (preserves game state)
                existing_civcom = civcom_registry.get_civcom(game_id, self.agent_id) if game_id else None
                if is_reconnecting and existing_civcom and not existing_civcom.stopped:
                    # Reuse existing CivCom - it has all the game state (units, cities, etc.)
                    self.civcom = existing_civcom
                    self.civcom.civwebserver = self  # Reconnect CivCom to new WebSocket handler
                    self.state_extractor.civcom = self.civcom  # Update StateExtractor reference

                    # Clear stale outbound packets from previous session
                    stale_count = len(self.civcom.civserver_messages)
                    if stale_count > 0:
                        logger.warning(
                            f"Clearing {stale_count} stale civserver_messages "
                            f"for {self.agent_id} on reconnect"
                        )
                        self.civcom.civserver_messages = []

                    logger.info(
                        f"♻️ REUSING existing CivCom for {self.agent_id} on reconnection:\n"
                        f"   Units preserved: {len(getattr(self.civcom, 'player_units', {}))}\n"
                        f"   Cities preserved: {len(getattr(self.civcom, 'player_cities', {}))}\n"
                        f"   Player ID: {self.civcom.player_id}\n"
                        f"   CivCom thread alive: {self.civcom.is_alive()}"
                    )

                    # STATE VERIFICATION: Check if expected_turn matches actual game state
                    # This catches the case where reconnection went to a different/reset game
                    # Allow ±TURN_DRIFT_TOLERANCE turn tolerance for reused CivCom: pod restart
                    # + recovery can take minutes, during which AI players advance turns.
                    # Session resumption already proves game identity, so the turn check is
                    # a secondary sanity check here. expected_turn=0 means "client doesn't
                    # know the turn yet" (pregame only), so skip verification like None.
                    if expected_turn is not None and expected_turn > 0:
                        current_turn = getattr(self.civcom, 'game_turn', 0)
                        turn_drift = abs(current_turn - expected_turn)
                        if turn_drift > TURN_DRIFT_TOLERANCE:
                            self._abort_with_state_mismatch(
                                expected_turn, current_turn,
                                'Game state lost — connected to reset or different civserver instance',
                                correlation_id
                            )
                            return
                        elif turn_drift >= 1:
                            logger.warning(
                                f"⚠️ Turn drift of {turn_drift} for {self.agent_id} (reused CivCom): "
                                f"expected={expected_turn}, actual={current_turn}. "
                                f"Allowed: within tolerance ({TURN_DRIFT_TOLERANCE})."
                            )
                        else:
                            logger.info(
                                f"✅ State verification passed for {self.agent_id} (reused CivCom): turn={current_turn}"
                            )
                    else:
                        if expected_turn == 0:
                            logger.info(
                                f"Skipping state verification for {self.agent_id} "
                                f"(expected_turn=0 indicates client doesn't know current turn)"
                            )
                        # else: expected_turn is None, no logging needed
                else:
                    # New connection or no existing CivCom - create fresh
                    if is_reconnecting and not existing_civcom:
                        logger.warning(f"⚠️ Reconnecting but no existing CivCom found for {self.agent_id} - creating new")
                    self._connect_to_civserver(civserver_port, game_id)
                    logger.info(f"✓ Agent {self.agent_id} civcom connection established to port {civserver_port}")

                    # FIX: Detect "already connected" rejection and retry after cleanup
                    # When civserver still has a stale TCP connection for this username,
                    # it rejects the new join. We force-close the old connection and retry once.
                    if is_reconnecting and self.civcom:
                        # Wait for handshake to complete (PACKET_SERVER_JOIN_REPLY)
                        # Uses asyncio.to_thread to bridge threading.Event → async without polling
                        try:
                            await asyncio.wait_for(
                                asyncio.to_thread(self.civcom.handshake_complete.wait),
                                timeout=STALE_CONN_HANDSHAKE_WAIT_SEC
                            )
                        except asyncio.TimeoutError:
                            logger.warning(f"Handshake timeout for {self.agent_id} after {STALE_CONN_HANDSHAKE_WAIT_SEC}s")

                        if self.civcom.join_rejected and 'already connected' in (self.civcom.join_rejection_reason or ''):
                            logger.warning(
                                f"🔄 Stale connection detected for {self.agent_id}: "
                                f"{self.civcom.join_rejection_reason}\n"
                                f"   Force-closing stale connection and retrying..."
                            )

                            # 1. Stop the rejected CivCom cleanly
                            self.civcom.cleanup()

                            # 2. Force-close any old CivCom still registered for this agent
                            old_civcom = civcom_registry.get_civcom(game_id, self.agent_id)
                            if old_civcom and old_civcom is not self.civcom:
                                logger.info(f"   Force-closing stale CivCom for {self.agent_id}")
                                old_civcom.cleanup()
                            civcom_registry.unregister_game(game_id, self.agent_id)

                            # 3. Wait for civserver to process the disconnect
                            await asyncio.sleep(STALE_CONN_DISCONNECT_WAIT_SEC)

                            # 4. Retry: _connect_to_civserver creates a NEW CivCom instance
                            #    with fresh state (join_rejected=False, new handshake_complete Event),
                            #    so the wait below is against the retry CivCom, not the failed one.
                            logger.info(f"   Retrying civserver connection for {self.agent_id}...")
                            self._connect_to_civserver(civserver_port, game_id)

                            # Wait for retry handshake
                            try:
                                await asyncio.wait_for(
                                    asyncio.to_thread(self.civcom.handshake_complete.wait),
                                    timeout=STALE_CONN_HANDSHAKE_WAIT_SEC
                                )
                            except asyncio.TimeoutError:
                                logger.warning(f"Retry handshake timeout for {self.agent_id}")

                            if self.civcom.join_rejected:
                                logger.error(
                                    f"❌ Retry failed for {self.agent_id}: "
                                    f"{self.civcom.join_rejection_reason}\n"
                                    f"   Civserver still rejecting connection after stale cleanup"
                                )
                                # Clean up the failed retry CivCom to prevent resource leaks
                                self.civcom.cleanup()
                                civcom_registry.unregister_game(game_id, self.agent_id)
                                error_response = {
                                    'type': 'error',
                                    'code': 'E_STALE_CONNECTION',
                                    'message': (
                                        f"Civserver rejected reconnection: {self.civcom.join_rejection_reason}. "
                                        f"The stale connection could not be cleared."
                                    ),
                                    'recoverable': False,
                                }
                                if correlation_id:
                                    error_response['correlation_id'] = correlation_id
                                self.write_message(json.dumps(error_response))
                                self.close()
                                return
                            else:
                                logger.info(f"✅ Retry succeeded for {self.agent_id} — stale connection cleared")

                    # FIX: State verification for fresh CivCom on reconnection (E120 detection)
                    # When we can't reuse CivCom and create a new one, verify the civserver
                    # hasn't lost game state (e.g., due to --quitidle timeout)
                    # expected_turn=0 means "client doesn't know the turn yet", skip like None.
                    if is_reconnecting and expected_turn is not None and expected_turn > 0:
                        # Wait for PACKET_GAME_INFO to set game_turn with retry loop
                        # This is more robust than a fixed sleep - handles network latency variations
                        start_time = time.monotonic()
                        last_log_time = start_time
                        current_turn = 0
                        while (time.monotonic() - start_time) < GAME_INFO_WAIT_TIMEOUT_SEC:
                            if getattr(self.civcom, 'game_info_received', False):
                                current_turn = getattr(self.civcom, 'game_turn', 0)
                                break
                            now = time.monotonic()
                            if (now - last_log_time) >= GAME_INFO_LOG_INTERVAL_SEC:
                                logger.debug(f"Waiting for PACKET_GAME_INFO... ({now - start_time:.1f}s)")
                                last_log_time = now
                            await asyncio.sleep(GAME_INFO_POLL_INTERVAL_SEC)

                        waited = time.monotonic() - start_time
                        turn_drift = abs(current_turn - expected_turn)
                        if turn_drift > TURN_DRIFT_TOLERANCE:
                            self._abort_with_state_mismatch(
                                expected_turn, current_turn,
                                'Game state lost — civserver restarted (pod eviction, OOM, or --quitidle timeout)',
                                correlation_id, waited
                            )
                            return
                        elif turn_drift >= 1:
                            logger.warning(
                                f"⚠️ Turn drift of {turn_drift} for {self.agent_id} (new CivCom): "
                                f"expected={expected_turn}, actual={current_turn} (waited {waited:.1f}s). "
                                f"Allowed: within tolerance ({TURN_DRIFT_TOLERANCE})."
                            )
                        else:
                            logger.info(
                                f"✅ State verification passed for {self.agent_id} (new CivCom): turn={current_turn} (waited {waited:.1f}s)"
                            )
                    elif is_reconnecting and expected_turn == 0:
                        logger.info(
                            f"Skipping state verification for {self.agent_id} "
                            f"(expected_turn=0 indicates client doesn't know current turn)"
                        )

                # If reconnecting, send /take command to reclaim player slot from AI
                # The civserver converts disconnected players to AI, so we need to take back our slot
                # Validate player_id is an integer to prevent command injection
                if is_reconnecting and isinstance(previous_player_id, int) and previous_player_id >= 0:
                    take_command = f"/take {previous_player_id}"  # FreeCiv /take accepts player number
                    take_packet = json.dumps({"pid": PACKET_CHAT_MSG_REQ, "message": take_command})
                    self.civcom.queue_to_civserver(take_packet)
                    self.civcom.send_packets_to_civserver()  # Actually send the /take command
                    logger.info(
                        f"Sent '{take_command}' to reclaim player slot for {self.agent_id}\n"
                        f"   Reclaiming player_id={previous_player_id}"
                    )
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

            # Self-assign player_id (restores pre-GameSessionManager behavior)
            # The original working implementation assigned player_id client-side
            # and told civserver "I am player X" via nation selection packet
            # This avoids the timeout issue with waiting for server-side assignment
            logger.info(
                f"⏳ Starting player registration and nation selection for {self.agent_id}\n"
                f"   Session ID: {self.session_id}\n"
                f"   Game ID: {game_id}"
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

                # For reconnection, use restored player_id directly
                # For new connections, wait for PACKET_CONN_INFO from server
                if is_reconnecting and isinstance(previous_player_id, int) and previous_player_id >= 0:
                    # During reconnection, we already have player_id from suspended session
                    # The /take command (sent earlier) reclaims the slot from AI
                    # No need to wait for PACKET_CONN_INFO - it won't be sent after /take
                    self.player_id = previous_player_id
                    self.civcom.player_id = previous_player_id  # Sync civcom state for consistency
                    logger.info(
                        f"✅ Reconnecting with restored player_id: {self.agent_id} → player_id={self.player_id}\n"
                        f"   Session resumed from suspended state"
                    )
                else:
                    # New connection - wait for PACKET_CONN_INFO from server
                    logger.info(f"⏳ Waiting for PACKET_CONN_INFO for {self.agent_id}...")
                    waited = 0.0
                    max_wait = 15.0  # Increased from 5s to match client timeout (defense-in-depth)
                    while (not hasattr(self.civcom, 'player_id') or self.civcom.player_id is None) and waited < max_wait:
                        await asyncio.sleep(0.2)
                        waited += 0.2
                        if waited % 1.0 < 0.3:  # Log every ~1 second
                            logger.info(f"   {self.agent_id}: Still waiting for PACKET_CONN_INFO... ({waited:.1f}s/{max_wait}s)")

                    if not hasattr(self.civcom, 'player_id') or self.civcom.player_id is None:
                        logger.error(
                            f"❌ {self.agent_id}: Failed to receive PACKET_CONN_INFO after {max_wait}s\n"
                            f"   This usually means civserver is not responding or is overloaded\n"
                            f"   Check civserver logs at /docker/logs/freeciv-web-log-{game_session.civserver_port}.log"
                        )
                        raise RuntimeError(f"Failed to receive PACKET_CONN_INFO - civserver not responding")

                    # Server automatically assigns player_id when we connect
                    self.player_id = self.civcom.player_id
                    logger.info(f"✅ Received player assignment: {self.agent_id} → player_id={self.player_id}")

                # Verify we got a valid player slot (not observer)
                if self.player_id >= 512:
                    logger.error(
                        f"❌ {self.agent_id}: Assigned observer slot (player_id={self.player_id})\n"
                        f"   This means no player slots are available\n"
                        f"   Game may already be full or not accepting new players"
                    )
                    raise RuntimeError(f"No player slots available - got observer slot {self.player_id}")

                self.session_info.player_id = self.player_id
                logger.info(f"✅ {self.agent_id} assigned player_id={self.player_id}")

                # Register player with game session using server-assigned player_id
                game_session.add_player(self.agent_id, self.player_id, self)
                logger.info(f"Registered agent {self.agent_id} with game session {game_id} (server-assigned player_id={self.player_id})")

                # Apply game configuration if provided (first player only)
                # Must be done BEFORE nation selection to avoid resetting ready flags
                game_config = msg_data.get('game_config', {})
                config_applied = False
                if game_config and not game_session.config_applied:
                    logger.info(
                        f"🎮 {self.agent_id}: Applying game configuration (first player)\n"
                        f"   Config: {game_config}"
                    )
                    config_applied = await game_session.configure_game_settings(game_config, self.civcom)
                elif game_config and game_session.config_applied:
                    logger.info(
                        f"🎮 {self.agent_id}: Game config ignored (already configured by first player)\n"
                        f"   Requested: {game_config}\n"
                        f"   Applied: {game_session.game_config}"
                    )

                # FIX: Skip nation selection during mid-game reconnection (E142 fix)
                # If game has already started, sending PACKET_NATION_SELECT_REQ is invalid and causes E142
                # Instead, we just need to register the player back with the game session
                #
                # Two scenarios where we skip nation selection:
                #
                # Scenario 1: Normal reconnection to a running game
                # The GameSession correctly tracks that the game has started
                skip_for_running_game = is_reconnecting and game_session.game_started

                # Scenario 2: Reconnection after GameSession was lost (E142 fix)
                # When GameSession is recreated (proxy restart, session expiry), game_started=False
                # But previous_player_id from Redis session resumption proves we already selected
                # a nation in a previous session - you can't have a player_id without completing
                # nation selection first
                skip_for_session_recovery = (
                    is_reconnecting and
                    previous_player_id is not None and
                    not game_session.game_started
                )

                skip_nation_selection = skip_for_running_game or skip_for_session_recovery

                # Log when we detect mid-game reconnection via session recovery path
                if skip_for_session_recovery:
                    logger.info(
                        f"🔄 Mid-game reconnection detected for {self.agent_id} via previous_player_id={previous_player_id}\n"
                        f"   (game_session.game_started=False but previous_player_id exists, indicating session recovery)"
                    )

                if not skip_nation_selection:
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
                        "pid": PACKET_NATION_SELECT_REQ,  # PACKET_NATION_SELECT_REQ from packets.def:426
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

                    # Check auto_ready flag
                    # When auto_ready=False, agent must explicitly send player_ready message
                    auto_ready = msg_data.get('auto_ready', True)
                    self.auto_ready = auto_ready  # Store for auth_success response

                    if auto_ready:
                        # Send PACKET_PLAYER_READY immediately after nation selection
                        logger.info(
                            f"✅ Nation selected for {self.agent_id} - sending PACKET_PLAYER_READY (auto_ready=True)\n"
                            f"   Player ID: {self.player_id}"
                        )

                        ready_packet = {
                            "pid": PACKET_PLAYER_READY,  # PACKET_PLAYER_READY from packets.def:434
                            "player_no": self.player_id,
                            "is_ready": True
                        }

                        # Send PACKET_PLAYER_READY to civserver
                        self.civcom.queue_to_civserver(json.dumps(ready_packet))
                        self.civcom.send_packets_to_civserver()

                        # Mark player as ready in game session (triggers game start when all ready)
                        game_session.mark_player_ready(self.agent_id)

                        logger.info(f"📤 PACKET_PLAYER_READY sent for {self.agent_id} (player_no={self.player_id})")
                    else:
                        logger.info(
                            f"⏸️ Nation selected for {self.agent_id} - NOT sending PACKET_PLAYER_READY (auto_ready=False)\n"
                            f"   Player ID: {self.player_id}\n"
                            f"   Agent must send 'player_ready' message to mark ready and start game"
                        )
                else:
                    # Mid-game reconnection: skip nation selection entirely
                    # The player already has a nation and the game is running
                    civcom_status = "reused" if (existing_civcom and self.civcom is existing_civcom) else "new"
                    logger.info(
                        f"🔄 Skipping nation selection for {self.agent_id} (mid-game reconnection)\n"
                        f"   Game already started: {game_session.game_started}\n"
                        f"   CivCom connection: {civcom_status}\n"
                        f"   Restored player_id: {self.player_id}"
                    )
                    # Re-register player with game session (handles both new and existing cases)
                    game_session.add_player(self.agent_id, self.player_id, self)
                    # For mid-game reconnection, auto_ready is irrelevant (game already running)
                    auto_ready = True
                    self.auto_ready = auto_ready

                # Send auth_success in FLAT format (Gateway will transform to nested for agent)
                # Game will start when all players are ready (~5-7 seconds after last player joins)
                # Architecture: Proxy sends flat → Gateway transforms → Agent receives nested
                auth_response = {
                    'type': 'auth_success',  # Flat format - Gateway expects this
                    'agent_id': self.agent_id,
                    'session_id': self.session_id,
                    'player_id': self.player_id,
                    'game_id': self.game_id,
                    'civserver_port': game_session.civserver_port,  # SPECTATOR FIX: Port for spectator URL generation
                    'server_turn': getattr(self.civcom, 'game_turn', 0) if self.civcom else 0,
                    'session_expires_in': int(self.session_info.expires_at - time.time()),
                    'status': 'authenticated',
                    'auto_ready': auto_ready,  # Indicates if player was auto-marked ready
                    'game_ready': False,  # Game not started yet
                    'game_config_applied': config_applied,  # True if this player's config was applied
                    'game_config': game_session.game_config,  # The applied game config (from first player)
                }

                if auto_ready:
                    auth_response.update({
                        'message': 'Player authenticated successfully. Waiting for all players to join.',
                        'waiting_for': 'game_ready',  # Signal to wait for
                        'expected_wait_seconds': '5-7',  # Typical initialization time
                        'instructions': 'Wait for game_ready message before querying state or submitting actions'
                    })
                else:
                    auth_response.update({
                        'message': 'Player authenticated successfully. Send player_ready message when ready to start.',
                        'waiting_for': 'player_ready',  # Signal that agent must send ready
                        'instructions': 'Send player_ready message to mark ready. Game starts when all players are ready.'
                    })

                if correlation_id:
                    auth_response['correlation_id'] = correlation_id
                self.write_message(json.dumps(auth_response))
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

                # CHECK IF GAME SHOULD BE RESUMED after successful reconnection
                # This handles the case where both agents reconnect after a coordinated disconnect
                self._check_and_resume_game()

            except Exception as e:
                logger.exception(f"Error in player registration and nation selection: {e}")

                # CRITICAL: Disable buffering on error to prevent packet accumulation
                # Also clear buffer to prevent memory leak
                self.buffer_enabled = False
                buffer_count = len(self.packet_buffer)
                self.packet_buffer.clear()
                logger.warning(f"🔓 Packet buffering DISABLED due to error for {self.agent_id} - cleared {buffer_count} buffered packets")

                # FIX: Clean up stale CivCom to prevent "Duplicate login name" loop
                # When E142 occurs (e.g., civserver rejects with "Duplicate login name"),
                # there may be a stale CivCom still connected to civserver from a previous
                # failed reconnection attempt. Kill it so the next attempt can succeed.
                # Game state is preserved in civserver - client passes player_id on reconnect.
                try:
                    stale_civcom = civcom_registry.get_civcom(game_id, self.agent_id)
                    if stale_civcom and stale_civcom is not self.civcom:
                        logger.warning(
                            f"🧹 Cleaning up STALE CivCom for {self.agent_id} after E142:\n"
                            f"   Stale CivCom alive: {stale_civcom.is_alive() if hasattr(stale_civcom, 'is_alive') else 'N/A'}\n"
                            f"   Stale CivCom stopped: {stale_civcom.stopped if hasattr(stale_civcom, 'stopped') else 'N/A'}\n"
                            f"   This allows next reconnection attempt to succeed"
                        )
                        stale_civcom.stopped = True
                        stale_civcom.close_connection()
                        civcom_registry.unregister_game(game_id, self.agent_id)
                    # Also clean up our own civcom if it exists
                    if self.civcom:
                        self.civcom.stopped = True
                        self.civcom.close_connection()
                except Exception as cleanup_err:
                    logger.error(f"Error cleaning up stale CivCom for {self.agent_id}: {cleanup_err}")

                error_response = {
                    'type': 'error',
                    'code': 'E142',
                    'message': 'Failed during player registration or nation selection'
                }
                if correlation_id:
                    error_response['correlation_id'] = correlation_id
                self.write_message(json.dumps(error_response))
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

            # FIX: Clean up stale CivCom to prevent "Duplicate login name" loop
            # Same as E142 handler - kill any stale connections so next attempt succeeds
            try:
                if 'game_id' in locals() and game_id and self.agent_id:
                    stale_civcom = civcom_registry.get_civcom(game_id, self.agent_id)
                    if stale_civcom and stale_civcom is not self.civcom:
                        logger.warning(
                            f"🧹 Cleaning up STALE CivCom for {self.agent_id} after auth exception:\n"
                            f"   Exception: {e}\n"
                            f"   This allows next reconnection attempt to succeed"
                        )
                        stale_civcom.stopped = True
                        stale_civcom.close_connection()
                        civcom_registry.unregister_game(game_id, self.agent_id)
                if self.civcom:
                    self.civcom.stopped = True
                    self.civcom.close_connection()
            except Exception as cleanup_err:
                logger.error(f"Error cleaning up stale CivCom for {self.agent_id}: {cleanup_err}")

            error_response = error_handler.handle_system_error(
                agent_id=self.agent_id,
                operation="authentication",
                error=e,
                session_id=self.session_id
            )
            self.write_message(error_response.to_json())

    async def _handle_state_query(self, msg_data: Dict[str, Any]):
        """Handle optimized state query for LLM (async to support turn advance wait)"""
        # Get resume context for debugging post-recovery issues
        game_session = game_session_manager.sessions.get(self.game_id) if self.game_id else None
        resume_context = ""
        if game_session:
            time_since_resume = ""
            if game_session.last_resumed_at:
                seconds_since = time.time() - game_session.last_resumed_at
                time_since_resume = f" | seconds_since_resume={seconds_since:.1f}"
            resume_context = f" | resume_count={game_session.resume_count}{time_since_resume}"

        current_turn = getattr(self.civcom, 'turn', 'unknown') if self.civcom else 'unknown'
        logger.info(
            f"🔍 STATE_QUERY received: agent={self.agent_id} | turn={current_turn} | "
            f"game_id={self.game_id}{resume_context}"
        )
        
        # Extract correlation_id for request/response matching
        correlation_id = msg_data.get('correlation_id')

        if not self.is_llm_agent:
            logger.warning(f"❌ Agent {self.agent_id} not authenticated for state_query")
            error_response = {
                'type': 'error',
                'code': 'E120',
                'message': 'Not authenticated as LLM agent'
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))
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
            error_response = {
                'type': 'error',
                'code': 'E122',
                'message': 'Player not assigned yet - game not ready. Wait for authentication to complete.',
                'details': {
                    'agent_id': self.agent_id,
                    'game_id': self.game_id,
                    'civcom_connected': self.civcom is not None,
                    'suggestion': 'Retry after receiving auth_success with valid player_id'
                }
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))
            return

        # Check if civcom is connected
        if not self.civcom or self.civcom.stopped:
            logger.error(
                f"❌ STATE_QUERY FAILED for {self.agent_id}: civcom not connected\n"
                f"   Player ID: {self.player_id}\n"
                f"   Civcom stopped: {self.civcom.stopped if self.civcom else 'N/A'}"
            )
            error_response = {
                'type': 'error',
                'code': 'E123',
                'message': 'Connection to game server lost',
                'details': {
                    'agent_id': self.agent_id,
                    'player_id': self.player_id,
                    'suggestion': 'Reconnect to game server'
                }
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))
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

            # Wait for new turn to start if we've ended our turn (PACKET_BEGIN_TURN fix)
            # After end_turn, wait for server's authoritative BEGIN_TURN signal
            # This ensures all players have finished before we return fresh state
            # Uses asyncio.Event for efficient blocking instead of polling
            if self.civcom and not self.civcom.turn_started:
                logger.info(f"⏳ Waiting for new turn to begin (current: {self.civcom.game_turn})...")
                wait_start = time.time()
                try:
                    # Event-based wait is more efficient than polling - wakes immediately when signaled
                    await asyncio.wait_for(self.civcom.turn_advance_event.wait(), timeout=10.0)
                    elapsed_ms = (time.time() - wait_start) * 1000
                    logger.info(f"✓ Turn {self.civcom.game_turn} started in {elapsed_ms:.0f}ms")
                except asyncio.TimeoutError:
                    elapsed_ms = (time.time() - wait_start) * 1000
                    logger.warning(f"⚠️ Turn start timeout after {elapsed_ms/1000:.1f}s - returning current state")

            # Generate cache key with turn number to prevent stale state
            # Using turn-based key instead of time-based to handle fast turn progression
            current_turn = self.civcom.game_turn if self.civcom and hasattr(self.civcom, 'game_turn') else 0
            cache_key = f"state_{self.player_id}_{query_format}_turn_{current_turn}"

            # Try cache first
            cached_state = state_cache.get(cache_key)
            if cached_state:
                logger.debug(f"✓ Cache hit for agent {self.agent_id}")
                response = {
                    'type': 'state_response',
                    'format': query_format,
                    'data': cached_state,
                    'cached': True,
                    'session_id': self.session_id,
                    'timestamp': time.time()
                }
                if correlation_id:
                    response['correlation_id'] = correlation_id
                self.write_message(json.dumps(response))
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
                f"   Legal actions: {sum(len(v) for v in state_data.get('legal_actions', {}).values()) if isinstance(state_data.get('legal_actions'), dict) else len(state_data.get('legal_actions', []))}\n"
                f"   State keys: {list(state_data.keys())}"
            )

            # Cache the result
            state_cache.set(cache_key, state_data, self.player_id)

            # Send response
            response = {
                'type': 'state_response',
                'format': query_format,
                'data': state_data,
                'cached': False,
                'timestamp': time.time()
            }
            if correlation_id:
                response['correlation_id'] = correlation_id
            self.write_message(json.dumps(response))

            self.last_state_query = time.time()

        except Exception as e:
            logger.exception(
                f"❌ STATE_QUERY EXCEPTION for agent {self.agent_id}:\n"
                f"   Player ID: {self.player_id}\n"
                f"   Game ID: {self.game_id}\n"
                f"   Error: {e}"
            )
            error_response = {
                'type': 'error',
                'code': 'E121',
                'message': f'State query failed: {str(e)}',
                'details': {
                    'agent_id': self.agent_id,
                    'player_id': self.player_id,
                    'error': str(e)
                }
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))

    async def _handle_global_state_query(self, msg_data: Dict[str, Any]):
        """Handle global state query - returns full state without fog of war filtering.

        Unlike state_query (which returns a single player's fog-of-war view),
        this returns the authoritative global state from CivCom for stats/observer use.
        """
        correlation_id = msg_data.get('correlation_id')

        if not self.is_llm_agent:
            logger.warning(f"Agent {self.agent_id} not authenticated for global_state_query")
            error_response = {
                'type': 'error',
                'code': 'E120',
                'message': 'Not authenticated as LLM agent'
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))
            return

        if not self.civcom or self.civcom.stopped:
            logger.error(
                f"GLOBAL_STATE_QUERY FAILED for {self.agent_id}: civcom not connected"
            )
            error_response = {
                'type': 'error',
                'code': 'E123',
                'message': 'Connection to game server lost',
                'details': {
                    'agent_id': self.agent_id,
                    'suggestion': 'Reconnect to game server'
                }
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))
            return

        try:
            # Try observer CivCom first — single source of truth, no fog-of-war
            observer = None
            if self.game_id:
                observer = civcom_registry.get_civcom(self.game_id, OBSERVER_AGENT_ID)

            if observer and not observer.stopped and observer.is_alive():
                full_state = observer.get_full_state_global()
                logger.debug(
                    f"Using observer CivCom for global state (game {self.game_id})"
                )
            else:
                # Fallback: aggregate state from ALL player CivCom instances.
                # Each CivCom only receives packets for units/cities visible to
                # its player (fog-of-war).  Merging across all players produces
                # a complete view.
                if observer:
                    logger.debug(
                        f"Observer CivCom unavailable (stopped={getattr(observer, 'stopped', '?')}, "
                        f"alive={observer.is_alive() if observer else '?'}), falling back to aggregation"
                    )
                full_state = self.civcom.get_full_state_global()

                if self.game_id:
                    all_civcoms = civcom_registry.get_all_for_game(self.game_id)
                    for key, other_civcom in all_civcoms.items():
                        if other_civcom is self.civcom or other_civcom.stopped:
                            continue
                        # Skip the observer entry in aggregation loop
                        if key[1] == OBSERVER_AGENT_ID:
                            continue
                        try:
                            other_state = other_civcom.get_full_state_global()
                            # Merge units — keyed by unit id, so duplicates are harmless
                            for uid, udata in other_state.get('units', {}).items():
                                if uid not in full_state.get('units', {}):
                                    full_state['units'][uid] = udata
                            # Merge cities — keyed by city id
                            for cid, cdata in other_state.get('cities', {}).items():
                                if cid not in full_state.get('cities', {}):
                                    full_state['cities'][cid] = cdata
                            # Merge techs — keyed by player label
                            for pkey, techs in other_state.get('techs', {}).items():
                                if pkey not in full_state.get('techs', {}):
                                    full_state['techs'][pkey] = techs
                            # Merge players — each CivCom has accurate gold/score
                            # only for its own player (other players' gold is hidden
                            # by fog-of-war and reported as 0).  Use this CivCom's
                            # data for its own player_id entry.
                            other_pid = getattr(other_civcom, 'player_id', None)
                            if other_pid is not None:
                                pid_key = str(other_pid)
                                other_players = other_state.get('players', {})
                                if pid_key in other_players:
                                    full_state.setdefault('players', {})[pid_key] = (
                                        other_players[pid_key]
                                    )
                                # Merge wonders — derived from player_cities which is
                                # fog-of-war limited.  Each CivCom's own player wonders
                                # are authoritative.
                                pkey = f'player{other_pid}'
                                other_wonders = other_state.get('wonders', {})
                                if pkey in other_wonders:
                                    full_state.setdefault('wonders', {})[pkey] = (
                                        other_wonders[pkey]
                                    )
                            # Merge spaceship — keyed by player label, merge missing entries
                            for skey, sdata in other_state.get('spaceship', {}).items():
                                if skey not in full_state.get('spaceship', {}):
                                    full_state.setdefault('spaceship', {})[skey] = sdata
                        except Exception as merge_err:
                            logger.warning(
                                f"Failed to merge state from civcom {key}: {merge_err}"
                            )

            logger.debug(
                f"GLOBAL_STATE_QUERY SUCCESS for agent {self.agent_id}: "
                f"turn={full_state.get('turn', 'N/A')}, "
                f"units={len(full_state.get('units', {}))}, "
                f"cities={len(full_state.get('cities', {}))}, "
                f"players={len(full_state.get('players', {}))}"
            )

            response = {
                'type': 'global_state_response',
                'data': full_state,
                'timestamp': time.time()
            }
            if correlation_id:
                response['correlation_id'] = correlation_id
            self.write_message(json.dumps(response))

        except Exception as e:
            logger.exception(
                f"GLOBAL_STATE_QUERY EXCEPTION for agent {self.agent_id}: {e}"
            )
            error_response = {
                'type': 'error',
                'code': 'E121',
                'message': f'Global state query failed: {str(e)}',
                'details': {
                    'agent_id': self.agent_id,
                    'error': str(e)
                }
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))

    def _normalize_agent_clash_action(self, action_data: Dict[str, Any], player_id: int = None, game_id: str = None) -> Dict[str, Any]:
        """Normalize agent-clash action format to proxy format.

        agent-clash sends:
            {"action_type": "tech_research", "actor_id": 1, "target": {"value": "Alphabet"}}

        Proxy expects:
            {"type": "tech_research", "tech_name": "alphabet", "player_id": 1}

        Args:
            action_data: agent-clash format action dict
            player_id: Optional player ID for looking up legal_actions (for target inference)
            game_id: Optional game ID for looking up legal_actions (for target inference)

        Returns:
            Normalized action dict for validation

        Raises:
            ValueError: If action format cannot be normalized
        """
        action_type = action_data.get("action_type")
        if not action_type:
            raise ValueError("Missing action_type field")

        logger.debug(f"Normalizing agent-clash action: {action_type}")

        # Build normalized action
        normalized = {"type": action_type}

        # Map actor_id based on action type
        # NOTE: agent-clash uses actor_id for different meanings:
        # - unit actions: actor_id is a unit ID
        # - city actions: actor_id is a city ID
        # - player-level actions: actor_id is a player ID
        # Map to the appropriate normalized key and don't overwrite explicit fields
        if "actor_id" in action_data:
            # Prefer explicit unit_id/city_id/player_id if provided
            if action_data.get("unit_id") is not None:
                normalized["unit_id"] = action_data["unit_id"]
            elif action_data.get("city_id") is not None:
                normalized["city_id"] = action_data["city_id"]
            elif action_data.get("player_id") is not None:
                normalized["player_id"] = action_data["player_id"]
            else:
                # Heuristics: decide mapping based on action type
                if action_type.startswith("unit_"):
                    normalized["unit_id"] = action_data["actor_id"]
                elif action_type.startswith("city_"):
                    normalized["city_id"] = action_data["actor_id"]
                elif action_type in ("tech_research", "end_turn") or action_type.startswith("diplomacy_"):
                    normalized["player_id"] = action_data["actor_id"]
                else:
                    # Fallback: if unknown action type, leave as player_id to be conservative
                    normalized["player_id"] = action_data["actor_id"]

        # Action-specific field mappings
        if action_type == "tech_research":
            # Extract tech name from target field
            # Supports multiple formats: {"value": "tech"}, {"tech": "tech"}, {"tech_name": "tech"}, or "tech"
            target = action_data.get("target", {})
            if isinstance(target, dict) and "value" in target:
                tech_name = target["value"]
            elif isinstance(target, dict) and "tech" in target:
                tech_name = target["tech"]
            elif isinstance(target, dict) and "tech_name" in target:
                tech_name = target["tech_name"]
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

        elif action_type in ("city_production", "city_change_production"):
            # Extract city_id and production type (both action names are aliases)
            if "city_id" in action_data:
                normalized["city_id"] = action_data["city_id"]

            # Extract production_type from target dict
            # Support both 'production_type' (canonical) and 'value' (agent-clash format) field names
            target = action_data.get("target", {})
            if isinstance(target, dict):
                production = target.get("production_type") or target.get("value", "")
            elif isinstance(target, str):
                production = target
            else:
                production = ""

            # Issue #3 Fix: Only set production_type if we have a non-empty value
            # If production is empty, don't set the field - let action_validator E030 handle it
            # with a clearer "Missing required field" error instead of cryptic S001 format error
            if production:
                normalized["production_type"] = str(production).lower()

        elif action_type == "unit_build_city":
            # Extract unit_id
            if "unit_id" in action_data:
                normalized["unit_id"] = action_data["unit_id"]

            # Extract city name from target dict (agent-clash sends target.name)
            target = action_data.get("target", {})
            if isinstance(target, dict) and "name" in target:
                normalized["name"] = target["name"]

        elif action_type in ("unit_attack", "unit_suicide_attack", "unit_bombard",
                             "unit_capture", "unit_wipe", "unit_conquer_city",
                             "unit_nuke", "unit_nuke_city", "unit_nuke_units"):
            # Extract target coordinates and IDs for combat actions
            # Agent-clash sends target as: {"x": 33, "y": 35} or {"target_unit_id": 99}
            target = action_data.get("target", {})
            if isinstance(target, dict):
                # Extract coordinates
                if "x" in target and "y" in target:
                    normalized["target_x"] = target["x"]
                    normalized["target_y"] = target["y"]
                # Extract specific target IDs
                if "target_unit_id" in target:
                    normalized["target_unit_id"] = target["target_unit_id"]
                if "target_city_id" in target:
                    normalized["target_city_id"] = target["target_city_id"]

            # Also support direct fields in action_data
            if "target_x" in action_data:
                normalized["target_x"] = action_data["target_x"]
            if "target_y" in action_data:
                normalized["target_y"] = action_data["target_y"]
            if "target_unit_id" in action_data:
                normalized["target_unit_id"] = action_data["target_unit_id"]
            if "target_city_id" in action_data:
                normalized["target_city_id"] = action_data["target_city_id"]

        elif action_type.startswith("diplomacy_"):
            # Diplomacy actions use different structure than unit/city actions
            # They require target_player_id (for validation) and message (for diplomacy_message)
            # Target dict contains {'player_id': int, 'player_name': str, 'message': str (optional)}
            target = action_data.get("target", {})
            if isinstance(target, dict):
                if "player_id" in target:
                    normalized["target_player_id"] = target["player_id"]
                if "message" in target:
                    normalized["message"] = target["message"]

            # Also check for target_player_id directly in action_data or params
            if "target_player_id" not in normalized:
                if "target_player_id" in action_data:
                    normalized["target_player_id"] = action_data["target_player_id"]
                elif "params" in action_data and isinstance(action_data["params"], dict):
                    if "player_id" in action_data["params"]:
                        normalized["target_player_id"] = action_data["params"]["player_id"]

            # SMART TARGET INFERENCE: If target still missing, look it up from legal_actions
            if "target_player_id" not in normalized and player_id is not None and game_id is not None:
                try:
                    logger.info(f"🔎 TARGET INFERENCE: Attempting for {action_type}, player={player_id}, game={game_id}")
                    civcom = self._get_civcom_for_player(player_id, game_id=game_id)
                    if civcom:
                        legal_actions = civcom._get_legal_actions_optimized(player_id)
                        logger.info(f"   Found {len(legal_actions)} legal_actions, searching for {action_type}")
                        found = False
                        for legal_action in legal_actions:
                            action_type_in_legal = legal_action.get('action')
                            if action_type_in_legal == action_type:
                                params = legal_action.get('params', {})
                                if 'player_id' in params:
                                    inferred_target = params['player_id']
                                    normalized["target_player_id"] = inferred_target
                                    logger.info(f"✅ INFERRED target_player_id={inferred_target}")
                                    found = True
                                    break
                        if not found:
                            logger.warning(f"   No {action_type} found in legal_actions")
                    else:
                        logger.warning(f"   civcom is None for player={player_id}, game={game_id}")
                except Exception as e:
                    logger.warning(f"Target inference failed: {e}", exc_info=True)

            # Validate that target_player_id is set and different from actor (player_id)
            target_id = normalized.get("target_player_id")
            actor_id = normalized.get("player_id")
            if target_id is None:
                logger.warning(f"Diplomacy action missing target_player_id: {action_type}")
            elif target_id == actor_id:
                logger.warning(f"Diplomacy action {action_type} targets self (actor={actor_id}, target={target_id})")

            logger.info(f"Normalized diplomacy action: {action_type} targeting player {normalized.get('target_player_id')}")

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
        """Parse agent-clash canonical format strings to JSON objects.

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

        elif action_type in ("city_production", "city_change_production"):
            # Map city production fields (both action names are aliases)
            if "actor_id" in params:
                result["city_id"] = params["actor_id"]
            elif "city_id" in params:
                result["city_id"] = params["city_id"]

            # Extract production_type from target dict or direct field
            target = params.get("target", {})
            if isinstance(target, dict) and "production_type" in target:
                result["production_type"] = str(target["production_type"]).lower()
            elif isinstance(target, str):
                result["production_type"] = target.lower()
            elif "production_type" in params:
                result["production_type"] = str(params["production_type"]).lower()

            logger.info(f"Parsed {action_type}: {result}")

        elif action_type == "unit_build_city":
            # Map unit build city fields
            if "actor_id" in params:
                result["unit_id"] = params["actor_id"]
            elif "unit_id" in params:
                result["unit_id"] = params["unit_id"]

            # Extract city name from target dict (agent-clash sends target.name)
            target = params.get("target", {})
            if isinstance(target, dict) and "name" in target:
                result["name"] = target["name"]

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
        # Get resume context for debugging post-recovery issues
        game_session = game_session_manager.sessions.get(self.game_id) if self.game_id else None
        resume_context = ""
        if game_session:
            time_since_resume = ""
            if game_session.last_resumed_at:
                seconds_since = time.time() - game_session.last_resumed_at
                time_since_resume = f" | seconds_since_resume={seconds_since:.1f}"
            resume_context = f" | resume_count={game_session.resume_count}{time_since_resume}"

        current_turn = getattr(self.civcom, 'turn', 'unknown') if self.civcom else 'unknown'
        action_type = msg_data.get('action', {}).get('type', msg_data.get('type', 'unknown'))
        logger.info(
            f"🎯 ACTION_RECEIVED: agent={self.agent_id} | turn={current_turn} | "
            f"action_type={action_type} | game_id={self.game_id}{resume_context}"
        )
        
        # Extract correlation_id for request/response matching
        correlation_id = msg_data.get('correlation_id')

        if not self.is_llm_agent:
            logger.warning(f"❌ Agent {self.agent_id} not authenticated for actions")
            error_response = {
                'type': 'error',
                'code': 'E130',
                'message': 'Not authenticated as LLM agent'
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))
            return

        # Update session activity for actions
        if self.session_id:
            session_manager.update_session_activity(self.session_id)

        try:
            # Extract action data from either 'data' (agent-clash format) or 'action' (legacy format)
            # Use explicit check to avoid falsy value issues (empty dict, 0, False, etc.)
            action_data = msg_data.get('data') if 'data' in msg_data else msg_data.get('action', {})
            logger.info(f"🎯 Extracted action_data: {action_data}")
            logger.info(f"🎯 action_data type: {type(action_data).__name__}")
            if isinstance(action_data, dict):
                logger.info(f"🎯 action_data has 'action_type': {'action_type' in action_data}")
                logger.info(f"🎯 action_data has 'type': {'type' in action_data}")

            # NEW: Handle canonical string format from agent-clash
            if isinstance(action_data, str):
                logger.info(f"📝 Received canonical action string: {action_data}")
                try:
                    action_data = self._parse_canonical_action(action_data)
                    logger.info(f"✅ Parsed to: {action_data}")
                except Exception as e:
                    logger.error(f"❌ Failed to parse canonical action '{action_data}': {e}")
                    error_response = {
                        'type': 'action_rejected',
                        'error_code': 'E134',
                        'error_message': f'Invalid action format: {e}. Expected canonical format like "tech_research_player(1)_target(Alphabet)" or JSON object.',
                        'action': action_data,
                        'example_formats': {
                            'canonical': 'tech_research_player(1)_target(Alphabet)',
                            'json': '{"type": "tech_research", "tech_name": "alphabet", "player_id": 1}'
                        }
                    }
                    if correlation_id:
                        error_response['correlation_id'] = correlation_id
                    self.write_message(json.dumps(error_response))
                    return

            # NEW: Handle agent-clash dict format with "action_type" instead of "type"
            if isinstance(action_data, dict) and "action_type" in action_data and "type" not in action_data:
                logger.info(f"📝 NORMALIZATION TRIGGERED: agent-clash format detected")
                logger.info(f"📝 Original action_data: {action_data}")
                try:
                    action_data = self._normalize_agent_clash_action(action_data, self.player_id, self.game_id)
                    logger.info(f"✅ NORMALIZATION SUCCESS: {action_data}")
                    logger.info(f"✅ Normalized action has 'type': {'type' in action_data}")
                    logger.info(f"✅ Normalized action has 'tech_name': {'tech_name' in action_data if action_data.get('type') == 'tech_research' else 'N/A'}")
                except Exception as e:
                    logger.error(f"❌ Failed to normalize agent-clash action: {e}")
                    error_response = {
                        'type': 'action_rejected',
                        'error_code': 'E135',
                        'error_message': f'Failed to normalize action format: {e}',
                        'action': action_data
                    }
                    if correlation_id:
                        error_response['correlation_id'] = correlation_id
                    self.write_message(json.dumps(error_response))
                    return

            # Sanitize action data to prevent injection attacks
            try:
                logger.info(f"🧹 Sanitizing action_data: {action_data}")
                sanitized_action = InputSanitizer.sanitize_action_data(action_data)
                logger.info(f"✓ Sanitized action: {sanitized_action}")
            except SecurityError as e:
                SecurityLogger.log_security_violation(self.agent_id, "INPUT_SANITIZATION", str(e))
                error_response = {
                    'type': 'action_rejected',
                    'error_code': 'S001',
                    'error_message': f'Input sanitization failed: {e}',
                    'action': action_data
                }
                if correlation_id:
                    error_response['correlation_id'] = correlation_id
                self.write_message(json.dumps(error_response))
                return

            # Add player_id to action if not present
            if 'player_id' not in sanitized_action:
                sanitized_action['player_id'] = self.player_id

            # Pre-submission validation with LOCAL MOVES TRACKING
            # This MUST run BEFORE action_validator to catch stale actions using local tracking
            # action_validator also checks moves_left but uses cached state which may be stale
            action_type = sanitized_action.get('type')

            if action_type in UNIT_ACTIONS_REQUIRING_MOVES and self.civcom:
                unit_id = sanitized_action.get('unit_id') or sanitized_action.get('actor_id')
                if unit_id:
                    game_state = self._get_current_game_state()
                    current_turn = game_state.get('turn') if game_state else None

                    # Reset local tracking on turn change using atomic update pattern
                    # Cache old_turn first to avoid race condition where multiple threads
                    # could check the same stale value and all proceed to reset
                    old_turn = self.last_tracked_turn
                    if current_turn is not None and current_turn != old_turn:
                        self.last_tracked_turn = current_turn
                        self.unit_moves_consumed.clear()
                        logger.debug(
                            f"Reset moves tracking: turn {old_turn} → {current_turn}, agent={self.agent_id}"
                        )

                    if game_state:
                        units = game_state.get('units', {})
                        if isinstance(units, list):
                            # Store as int keys for consistent lookup
                            units = {int(u.get('id')): u for u in units if isinstance(u, dict) and u.get('id') is not None}

                        if units:
                            try:
                                unit_id_int = int(unit_id)
                            except (TypeError, ValueError):
                                logger.warning(f"Invalid unit_id format: {unit_id}")
                                unit_id_int = None

                            unit = units.get(unit_id_int) if unit_id_int is not None else None
                            if unit:
                                cached_moves_left = unit.get('moves_left', 0)

                                # Calculate effective moves using local tracking
                                consumed = self.unit_moves_consumed.get(unit_id_int, 0)
                                effective_moves = cached_moves_left - consumed

                                logger.debug(
                                    f"Pre-submission validation check: agent={self.agent_id}, "
                                    f"action_type={action_type}, unit_id={unit_id}, "
                                    f"cached_moves={cached_moves_left}, consumed={consumed}, effective={effective_moves}"
                                )

                                if effective_moves <= 0:
                                    error_response = {
                                        'type': 'action_rejected',
                                        'error_code': 'E024',
                                        'error_message': f'Unit {unit_id} has no moves remaining (pre-submission validation)',
                                        'action': action_data,
                                        'player_id': self.player_id,
                                        'turn': current_turn,
                                        'timestamp': time.time()
                                    }
                                    if correlation_id:
                                        error_response['correlation_id'] = correlation_id
                                    self.write_message(json.dumps(error_response))
                                    logger.warning(
                                        f"PRE-SUBMISSION BLOCKED: Stale action prevented: "
                                        f"agent={self.agent_id}, unit_id={unit_id}, "
                                        f"cached_moves={cached_moves_left}, consumed={consumed}, effective={effective_moves}, "
                                        f"action_type={action_type}"
                                    )
                                    return

            logger.info(f"🔍 Validating action: {sanitized_action}")

            # Validate action (additional checks beyond moves_left)
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

                # Extract actor_id from action if present (for cache eviction debugging)
                actor_id = sanitized_action.get('unit_id') or sanitized_action.get('actor_id') or 'N/A'

                error_response = {
                    'type': 'action_rejected',
                    'error_code': validation_result.error_code,
                    'error_message': validation_result.error_message,
                    'action': action_data,
                    'expected_format': expected_format,
                    'player_id': self.player_id,
                    'turn': current_turn,
                    'timestamp': time.time()
                }
                if correlation_id:
                    error_response['correlation_id'] = correlation_id
                self.write_message(json.dumps(error_response))

                # Strategic logging for AGE-299 debugging
                logger.warning(
                    f"Action rejected: agent={self.agent_id}, turn={current_turn}, "
                    f"error_code={validation_result.error_code}, action_type={action_type}, "
                    f"actor_id={actor_id}, message={validation_result.error_message}"
                )
                return

            # Forward validated and sanitized action to civcom
            if self.civcom:
                action_packet = self._convert_action_to_packet(sanitized_action)
                self.civcom.queue_to_civserver(json.dumps(action_packet))
                # CRITICAL: Must call send_packets_to_civserver() to actually send queued packets!
                # Without this, actions are queued but never transmitted to civserver
                self.civcom.send_packets_to_civserver()

                # Track consumed moves locally after successful submission
                # This prevents rapid successive actions from bypassing stale cache
                action_type = sanitized_action.get('type')
                if action_type in UNIT_ACTIONS_REQUIRING_MOVES:
                    unit_id = sanitized_action.get('unit_id') or sanitized_action.get('actor_id')
                    if unit_id is not None:
                        try:
                            unit_id_int = int(unit_id)
                        except (TypeError, ValueError):
                            logger.warning(f"Invalid unit_id format: {unit_id}")
                            unit_id_int = None
                    else:
                        unit_id_int = None
                    if unit_id_int is not None:
                        # Increment consumed moves (conservative tracking: always increment by 1)
                        # NOTE: Some actions consume more than 1 move (e.g., moving through difficult terrain).
                        # This conservative approach may allow actions that will be rejected by the server,
                        # but ensures we never incorrectly block valid actions. The server is authoritative.
                        self.unit_moves_consumed[unit_id_int] = self.unit_moves_consumed.get(unit_id_int, 0) + 1
                        logger.debug(
                            f"Tracked move consumed: agent={self.agent_id}, unit_id={unit_id}, "
                            f"total_consumed={self.unit_moves_consumed[unit_id_int]}"
                        )

                # Extract actor_id for logging
                actor_id = sanitized_action.get('unit_id') or sanitized_action.get('actor_id') or 'N/A'
                game_state = self._get_current_game_state()
                current_turn = game_state.get('turn', 'unknown') if game_state else 'unknown'

                # Strategic logging for AGE-299 debugging
                logger.warning(
                    f"Action accepted: agent={self.agent_id}, turn={current_turn}, "
                    f"action_type={sanitized_action.get('type')}, actor_id={actor_id}"
                )

                # Handle end_turn: mark turn as ended and reset rate limits
                if sanitized_action.get('type') == 'end_turn' and self.agent_id:
                    # Mark turn as ended - state_query will wait for PACKET_BEGIN_TURN
                    # This ensures we don't return stale state while waiting for all players
                    if self.civcom:
                        self.civcom.turn_started = False
                        self.civcom.turn_advance_event.clear()  # Clear event to block waiters
                        logger.info(f"🛑 Turn {self.civcom.game_turn} ended, waiting for PACKET_BEGIN_TURN")

                    # Reset rate limits to give agent fresh quota for next turn
                    reset_on_turn_end = llm_config.get('validation.rate_limit.reset_on_turn_end', True)
                    if reset_on_turn_end:
                        distributed_rate_limiter.reset_limits(self.agent_id)
                        logger.info(f"Rate limits reset for {self.agent_id} after end_turn")

                SecurityLogger.log_connection_event(self.agent_id, "ACTION_EXECUTED",
                                                  f"type={sanitized_action.get('type')}")

                response = {
                    'type': 'action_accepted',
                    'action': sanitized_action,
                    'timestamp': time.time()
                }
                if correlation_id:
                    response['correlation_id'] = correlation_id
                self.write_message(json.dumps(response))
            else:
                error_response = {
                    'type': 'error',
                    'code': 'E131',
                    'message': 'No connection to game server'
                }
                if correlation_id:
                    error_response['correlation_id'] = correlation_id
                self.write_message(json.dumps(error_response))

        except Exception as e:
            logger.exception(f"Error handling action: {e}")
            error_response = {
                'type': 'error',
                'code': 'E132',
                'message': 'Action processing failed'
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))

    def _handle_ping(self, msg_data: Dict[str, Any]):
        """Handle ping message"""
        correlation_id = msg_data.get('correlation_id')
        response = {
            'type': 'pong',
            'timestamp': time.time(),
            'agent_id': self.agent_id
        }
        if correlation_id:
            response['correlation_id'] = correlation_id
        self.write_message(json.dumps(response))

    def send_game_ended(self, winners: List[int], endgame_players: Dict[int, Dict[str, Any]]) -> None:
        """Notify agent that game has ended with winner information.

        Called by CivCom when PACKET_ENDGAME_PLAYER packets are received.
        Sends a 'game_ended' message to the agent with winner info and final scores.

        Args:
            winners: List of player_ids who won (usually 1, but could be multiple for allied victory)
            endgame_players: Dict of {player_id: {score, winner, category_scores}}
        """
        if not self.is_llm_agent:
            return

        # Determine if THIS agent won
        is_winner = self.player_id in winners if self.player_id is not None else False

        # Build player results with string keys for JSON compatibility
        player_results = {}
        for pid, data in endgame_players.items():
            player_results[str(pid)] = data

        game_ended_msg = {
            'type': 'game_ended',
            'timestamp': time.time(),
            'data': {
                'winners': winners,
                'is_winner': is_winner,
                'player_results': player_results,
                'reason': 'game_over'  # Could be enhanced to include specific reason (turn_limit, conquest, etc.)
            }
        }

        try:
            self.write_message(json.dumps(game_ended_msg))
            logger.info(
                f"🏁 Sent game_ended to {self.agent_id}:\n"
                f"   Winners: {winners}\n"
                f"   Is Winner: {is_winner}\n"
                f"   Total Players: {len(endgame_players)}"
            )
        except Exception as e:
            logger.error(f"Failed to send game_ended to {self.agent_id}: {e}")

    def _handle_chat(self, msg_data: Dict[str, Any]):
        """Handle chat message from LLM agent

        Sends chat messages/commands to the FreeCiv server via PACKET_CHAT_MSG_REQ (pid=26).
        Primary use cases:
        - Server commands: /set mapsize MEDIUM, /save, /start
        - Player chat: general messages to other players

        The FreeCiv server handles its own command restrictions.
        """
        if not self.is_llm_agent:
            self.write_message(
                json.dumps(
                    {
                        "type": "error",
                        "code": "E401",
                        "message": "Not authenticated as LLM agent",
                    }
                )
            )
            return

        # Extract message from data field or top-level
        message = None
        if "data" in msg_data and isinstance(msg_data["data"], dict):
            message = msg_data["data"].get("message")
        if message is None:
            message = msg_data.get("message")

        if not message:
            self.write_message(
                json.dumps(
                    {
                        "type": "error",
                        "code": "E220",
                        "message": "Missing required field: message",
                    }
                )
            )
            return

        # Validate message length (max 500 characters)
        if len(message) > 500:
            self.write_message(
                json.dumps(
                    {
                        "type": "error",
                        "code": "E170",
                        "message": f"Chat message too long: {len(message)} characters (max 500)",
                    }
                )
            )
            return

        # Create PACKET_CHAT_MSG_REQ packet (pid=26)
        chat_packet = {"pid": PACKET_CHAT_MSG_REQ, "message": message}

        # Send to civcom
        if self.civcom:
            try:
                self.civcom.queue_to_civserver(json.dumps(chat_packet))
                self.civcom.send_packets_to_civserver()

                # Log command vs chat
                if message.startswith("/"):
                    logger.info(f"Agent {self.agent_id} sent command: {message}")
                else:
                    logger.debug(
                        f"Agent {self.agent_id} sent chat: {message[:50]}..."
                        if len(message) > 50
                        else f"Agent {self.agent_id} sent chat: {message}"
                    )

                # Send acknowledgment
                correlation_id = msg_data.get("correlation_id")
                response = {
                    "type": "chat_sent",
                    "agent_id": self.agent_id,
                    "timestamp": time.time(),
                    "data": {
                        "success": True,
                        "message": (
                            message[:100] + "..." if len(message) > 100 else message
                        ),
                    },
                }
                if correlation_id:
                    response["correlation_id"] = correlation_id

                self.write_message(json.dumps(response))

            except Exception as e:
                logger.error(f"Failed to send chat for agent {self.agent_id}: {e}")
                self.write_message(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "E171",
                            "message": f"Failed to send chat message: {str(e)}",
                        }
                    )
                )
        else:
            self.write_message(
                json.dumps(
                    {
                        "type": "error",
                        "code": "E123",
                        "message": "Not connected to game server",
                    }
                )
            )

    def _handle_player_ready(self, msg_data: Dict[str, Any]):
        """Handle player ready status from LLM agent"""
        # Extract correlation_id for request/response matching
        correlation_id = msg_data.get('correlation_id')
        
        if not self.is_llm_agent:
            error_response = {
                'type': 'error',
                'code': 'E401',
                'message': 'Not authenticated as LLM agent'
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))
            return

        if self.player_id is None:
            error_response = {
                'type': 'error',
                'code': 'E402',
                'message': 'No player ID assigned yet'
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))
            return

        # Get ready status from message (default to True)
        is_ready = msg_data.get('is_ready', True)

        # Create PACKET_PLAYER_READY packet
        ready_packet = {
            "pid": PACKET_PLAYER_READY,  # PACKET_PLAYER_READY from packets.def:434
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
                response = {
                    'type': 'ready_confirmed',
                    'player_no': self.player_id,
                    'is_ready': is_ready,
                    'message': f'Player {self.player_id} marked {"ready" if is_ready else "not ready"}'
                }
                if correlation_id:
                    response['correlation_id'] = correlation_id
                self.write_message(json.dumps(response))
            except Exception as e:
                logger.error(f"Failed to send ready packet: {e}")
                error_response = {
                    'type': 'error',
                    'code': 'E403',
                    'message': f'Failed to send ready packet: {str(e)}'
                }
                if correlation_id:
                    error_response['correlation_id'] = correlation_id
                self.write_message(json.dumps(error_response))
        else:
            error_response = {
                'type': 'error',
                'code': 'E404',
                'message': 'Not connected to game server'
            }
            if correlation_id:
                error_response['correlation_id'] = correlation_id
            self.write_message(json.dumps(error_response))

    def _handle_unit_actions_query(self, msg_data: Dict[str, Any]):
        """Handle batch query for available actions on one or more units
        
        Request format (per protocol v2.0.1):
        {
            "type": "unit_actions_query",
            "agent_id": "my-agent",
            "timestamp": 1234567890.123,
            "correlation_id": "unit-query-001",
            "data": {
                "unit_ids": [42, 43, 44]
            }
        }
        
        Response format:
        {
            "type": "unit_actions_response",
            "agent_id": "my-agent",
            "timestamp": 1234567890.125,
            "correlation_id": "unit-query-001",
            "data": {
                "success": true,
                "units": {
                    "42": {"unit_id": 42, "success": true, "actions": [...]},
                    "43": {"unit_id": 43, "success": true, "actions": [...]},
                    "44": {"unit_id": 44, "success": false, "error": {...}, "actions": []}
                },
                "errors": [...]
            }
        }
        """
        import time as time_module
        correlation_id = msg_data.get('correlation_id')
        data = msg_data.get('data', {})
        unit_ids = data.get('unit_ids', [])

        logger.info(f"🎯 UNIT_ACTIONS_QUERY received from agent {self.agent_id} for units {unit_ids}")

        if not self.is_llm_agent:
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E120',
                'message': 'Not authenticated as LLM agent',
                'correlation_id': correlation_id
            }))
            return

        if self.player_id is None:
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E230',
                'message': 'No player ID assigned - cannot query units',
                'correlation_id': correlation_id
            }))
            return

        if not unit_ids or not isinstance(unit_ids, list):
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E220',
                'message': 'Missing or invalid unit_ids array in data',
                'correlation_id': correlation_id
            }))
            return

        try:
            state_extractor = self._get_state_extractor()
            if not state_extractor:
                self.write_message(json.dumps({
                    'type': 'error',
                    'code': 'E500',
                    'message': 'State extractor not available',
                    'correlation_id': correlation_id
                }))
                return

            # Process each unit in batch
            units_results = {}
            errors = []
            any_success = False

            for unit_id in unit_ids:
                result = state_extractor.get_unit_actions(unit_id, self.player_id, game_id=self.game_id)
                unit_key = str(unit_id)

                if result.get('error'):
                    error_info = {
                        'code': result.get('error_code', 'E230'),
                        'message': result['error']
                    }
                    units_results[unit_key] = {
                        'unit_id': unit_id,
                        'success': False,
                        'error': error_info,
                        'actions': []
                    }
                    errors.append({'unit_id': unit_id, **error_info})
                else:
                    any_success = True
                    # Format actions per protocol spec
                    actions = self._format_unit_actions_for_response(unit_id, result)
                    units_results[unit_key] = {
                        'unit_id': unit_id,
                        'success': True,
                        'actions': actions
                    }

            # Build response per protocol spec
            response = {
                'type': 'unit_actions_response',
                'agent_id': self.agent_id,
                'timestamp': time_module.time(),
                'data': {
                    'success': any_success,
                    'units': units_results,
                    'errors': errors
                }
            }
            if correlation_id:
                response['correlation_id'] = correlation_id

            self.write_message(json.dumps(response))
            num_actions = sum(len(u['actions']) for u in units_results.values() if u['success'])
            logger.info(f"✓ UNIT_ACTIONS_QUERY SUCCESS for agent {self.agent_id}: {len(unit_ids)} units queried, {len(errors)} errors, {num_actions} actions returned")

        except Exception as e:
            logger.error(f"❌ UNIT_ACTIONS_QUERY EXCEPTION for agent {self.agent_id}: {e}")
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E500',
                'message': f'Internal error: {str(e)}',
                'correlation_id': correlation_id
            }))

    def _format_unit_actions_for_response(self, unit_id: int, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Format unit actions to be directly submittable per protocol spec"""
        formatted_actions = []
        for action in result.get('actions', []):
            action_type = action.get('action', '')
            params = action.get('params', {})
            is_valid = action.get('is_valid', True)
            reason = action.get('reason')
            action_id = action.get('action_id')
            
            formatted = {
                'action_type': self._map_action_type(action_type),
                'actor_id': unit_id,
                'is_valid': is_valid
            }
            
            # Add reason if action is invalid
            if not is_valid and reason:
                formatted['reason'] = reason
            
            # Add FreeCiv action ID if available (useful for debugging)
            if action_id is not None:
                formatted['action_id'] = action_id
            
            # Add target based on action type and params
            if params:
                if 'direction' in params:
                    formatted['target'] = {'direction': params['direction']}
                    if 'target' in params and isinstance(params['target'], dict):
                        formatted['target'].update(params['target'])
                elif 'target' in params:
                    formatted['target'] = params['target']
                elif 'improvement' in params:
                    formatted['target'] = {'improvement': params['improvement']}
                elif 'city' in params:
                    formatted['target'] = {'city': params['city']}
                elif params:  # Pass through any other params
                    formatted['target'] = params
            
            formatted_actions.append(formatted)
        return formatted_actions

    def _map_action_type(self, action: str) -> str:
        """Map internal action names to protocol action_type values"""
        mapping = {
            'move': 'unit_move',
            'fortify': 'unit_fortify',
            'build_city': 'unit_build_city',
            'join_city': 'unit_join_city',
            'build_road': 'unit_build_road',
            'build_irrigation': 'unit_build_irrigation',
            'build_mine': 'unit_build_mine',
            'build_base': 'unit_build_base',
            'build_improvement': 'unit_build_improvement',
            'transform': 'unit_transform',
            'cultivate': 'unit_cultivate',
            'plant': 'unit_plant',
            'attack': 'unit_attack',
            'suicide_attack': 'unit_suicide_attack',
            'bombard': 'unit_bombard',
            'capture': 'unit_capture',
            'conquer_city': 'unit_conquer_city',
            'nuke': 'unit_nuke',
            'nuke_city': 'unit_nuke_city',
            'nuke_units': 'unit_nuke_units',
            'pillage': 'unit_pillage',
            'clean': 'unit_clean',
            'trade_route': 'unit_trade_route',
            'marketplace': 'unit_marketplace',
            'help_wonder': 'unit_help_wonder',
            'establish_embassy': 'unit_establish_embassy',
            'investigate_city': 'spy_investigate_city',
            'poison': 'spy_poison',
            'sabotage_city': 'spy_sabotage_city',
            'steal_tech': 'spy_steal_tech',
            'incite_city': 'spy_incite_city',
            'bribe_unit': 'spy_bribe_unit',
            'sabotage_unit': 'spy_sabotage_unit',
            'spy_attack': 'spy_attack',
            'board': 'unit_board',
            'deboard': 'unit_deboard',
            'embark': 'unit_embark',
            'disembark': 'unit_disembark',
            'load': 'unit_load',
            'unload': 'unit_unload',
            'disband': 'unit_disband',
            'home_city': 'unit_home_city',
            'upgrade': 'unit_upgrade',
            'convert': 'unit_convert',
            'heal': 'unit_heal',
            'airlift': 'unit_airlift',
            'paradrop': 'unit_paradrop',
            'skip': 'unit_skip',
            'sentry': 'unit_sentry',
        }
        return mapping.get(action, f'unit_{action}')

    def _handle_city_actions_query(self, msg_data: Dict[str, Any]):
        """Handle batch query for available actions on one or more cities
        
        Request format (per protocol v2.0.1):
        {
            "type": "city_actions_query",
            "agent_id": "my-agent",
            "timestamp": 1234567890.123,
            "correlation_id": "city-query-001",
            "data": {
                "city_ids": [5, 6]
            }
        }
        
        Response format:
        {
            "type": "city_actions_response",
            "agent_id": "my-agent",
            "timestamp": 1234567890.125,
            "correlation_id": "city-query-001",
            "data": {
                "success": true,
                "cities": {
                    "5": {"city_id": 5, "success": true, "actions": [...]},
                    "6": {"city_id": 6, "success": true, "actions": [...]}
                },
                "errors": []
            }
        }
        """
        import time as time_module
        correlation_id = msg_data.get('correlation_id')
        data = msg_data.get('data', {})
        city_ids = data.get('city_ids', [])

        logger.info(f"🏙️ CITY_ACTIONS_QUERY received from agent {self.agent_id} for cities {city_ids}")

        if not self.is_llm_agent:
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E120',
                'message': 'Not authenticated as LLM agent',
                'correlation_id': correlation_id
            }))
            return

        if self.player_id is None:
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E240',
                'message': 'No player ID assigned - cannot query cities',
                'correlation_id': correlation_id
            }))
            return

        if not city_ids or not isinstance(city_ids, list):
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E220',
                'message': 'Missing or invalid city_ids array in data',
                'correlation_id': correlation_id
            }))
            return

        try:
            state_extractor = self._get_state_extractor()
            if not state_extractor:
                self.write_message(json.dumps({
                    'type': 'error',
                    'code': 'E500',
                    'message': 'State extractor not available',
                    'correlation_id': correlation_id
                }))
                return

            # Process each city in batch
            cities_results = {}
            errors = []
            any_success = False

            for city_id in city_ids:
                result = state_extractor.get_city_actions(city_id, self.player_id, game_id=self.game_id)
                city_key = str(city_id)

                if result.get('error'):
                    error_info = {
                        'code': result.get('error_code', 'E240'),
                        'message': result['error']
                    }
                    cities_results[city_key] = {
                        'city_id': city_id,
                        'success': False,
                        'error': error_info,
                        'actions': []
                    }
                    errors.append({'city_id': city_id, **error_info})
                else:
                    any_success = True
                    # Format actions per protocol spec
                    actions = self._format_city_actions_for_response(city_id, result)
                    cities_results[city_key] = {
                        'city_id': city_id,
                        'success': True,
                        'actions': actions
                    }

            # Build response per protocol spec
            response = {
                'type': 'city_actions_response',
                'agent_id': self.agent_id,
                'timestamp': time_module.time(),
                'data': {
                    'success': any_success,
                    'cities': cities_results,
                    'errors': errors
                }
            }
            if correlation_id:
                response['correlation_id'] = correlation_id

            self.write_message(json.dumps(response))
            logger.info(f"✓ CITY_ACTIONS_QUERY SUCCESS for agent {self.agent_id}: {len(city_ids)} cities queried, {len(errors)} errors")

        except Exception as e:
            logger.error(f"❌ CITY_ACTIONS_QUERY EXCEPTION for agent {self.agent_id}: {e}")
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E500',
                'message': f'Internal error: {str(e)}',
                'correlation_id': correlation_id
            }))

    def _format_city_actions_for_response(self, city_id: int, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Format city actions to be directly submittable per protocol spec"""
        formatted_actions = []
        for action in result.get('actions', []):
            action_type = action.get('action', '')
            formatted = {
                'action_type': self._map_city_action_type(action_type),
                'actor_id': city_id
            }
            # Add target based on action type
            params = action.get('params', {})
            if action_type == 'change_production' and 'to' in params:
                formatted['target'] = {'production': params['to']}
            elif action_type == 'sell_improvement' and 'improvement' in params:
                formatted['target'] = {'improvement': params['improvement']}
            formatted_actions.append(formatted)
        return formatted_actions

    def _map_city_action_type(self, action: str) -> str:
        """Map internal city action names to protocol action_type values"""
        mapping = {
            'change_production': 'city_production',
            'buy': 'city_buy',
            'sell_improvement': 'city_sell_improvement',
            'add_specialist': 'city_add_specialist'
        }
        return mapping.get(action, f'city_{action}')

    def _get_state_extractor(self) -> Optional[StateExtractor]:
        """Get or create StateExtractor for current civcom connection"""
        if not self.civcom:
            return None
        try:
            # StateExtractor uses civcom_registry for access, with handler's civcom as fallback
            # Note: StateExtractor.__init__(civcom, cache, registry) - use named params for clarity
            return StateExtractor(civcom=self.civcom, cache=None, registry=civcom_registry)
        except Exception as e:
            logger.error(f"Failed to create StateExtractor: {e}")
            return None

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
                legal_actions = self._get_legal_actions_optimized(full_state)
                # Log action counts - legal_actions is now dict keyed by actor_id
                total_actions = sum(len(actions) for actions in legal_actions.values())
                unit_count = sum(1 for k in legal_actions.keys() if k != 'player')

                # Strategic logging for AGE-299: track legal_actions fetches per turn
                logger.info(
                    f"Legal actions fetched: agent={self.agent_id}, turn={full_state.get('turn', 'unknown')}, "
                    f"total_actions={total_actions}, units_with_actions={unit_count}"
                )

                logger.info(
                    f"✓ Generated {total_actions} legal actions for agent {self.agent_id}\n"
                    f"   Units with actions: {unit_count}\n"
                    f"   State keys: {list(state.keys())}"
                )
                state['legal_actions'] = legal_actions

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
            'techs': {},  # Dict format: {'player0': [...], 'player1': [...]}
            'map_info': {}
        }

    def send_game_ready(self):
        """Notify agent that initial game state is ready.

        Called by CivCom when first unit packet is received, indicating
        the game has started and state queries will return valid data.

        This solves the race condition where agents query state before
        the initial unit packets arrive, getting empty unit lists.

        NOTE: This may be called from CivCom thread, so we use IOLoop callback
        to schedule the write_message on the main Tornado IOLoop thread.
        """
        if not self.is_llm_agent:
            return

        try:
            ready_message = {
                'type': 'game_ready',
                'agent_id': self.agent_id,
                'player_id': self.player_id,
                'session_id': self.session_id,
                'timestamp': time.time()
            }
            message_json = json.dumps(ready_message)
            # Check if we're on the IOLoop thread to avoid potential deadlock
            # If called from IOLoop, write directly; otherwise schedule via callback
            current_loop = IOLoop.current(instance=False)
            if current_loop and current_loop == self.io_loop:
                self.write_message(message_json)
            else:
                # Schedule write on IOLoop since this is called from CivCom thread
                # This prevents "no current event loop in thread" errors
                self.io_loop.add_callback(self.write_message, message_json)
            logger.info(f"✅ Scheduled game_ready signal to {self.agent_id} (player {self.player_id})")
        except Exception as e:
            logger.error(f"❌ Failed to schedule game_ready to {self.agent_id}: {e}")

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
            'cities': cities,
            'techs': full_state.get('techs', {})
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

    def _get_legal_actions_optimized(self, game_state: Dict[str, Any] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Get legal actions keyed by actor_id for O(1) lookup.

        Returns dict structure:
        {
            "<unit_id>": [list of actions for that unit],
            "player": [player-level actions like end_turn, tech_research]
        }

        Uses state_extractor._generate_unit_actions() which properly validates
        actions against ruleset data and terrain.
        """
        actions_by_actor: Dict[str, List[Dict[str, Any]]] = {}

        # Get game state if not provided
        if not game_state and self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                game_state = self.civcom.get_full_state(self.player_id)
            except Exception as e:
                logger.warning(f"Failed to get game state from civcom: {e}")
                game_state = {}

        if not game_state:
            # Return fallback with just player actions
            actions_by_actor['player'] = self._get_player_level_actions({})
            return actions_by_actor

        # Get state extractor for proper action generation
        state_extractor = self._get_state_extractor()

        # Generate actions for each unit using state_extractor
        units = game_state.get('units', {})
        # Pre-filter units by owner (performance: avoid unnecessary API calls for enemy units)
        player_units = {uid: unit for uid, unit in units.items()
                        if unit.get('owner') == self.player_id}

        if state_extractor:
            # Use the comprehensive action generation from state_extractor
            for unit_id_str, unit in player_units.items():
                try:
                    unit_id = int(unit_id_str)
                    result = state_extractor.get_unit_actions(unit_id, self.player_id, game_state=game_state, game_id=self.game_id)

                    if result.get('error'):
                        error_code = result.get('error_code', '')
                        # E500 = internal error (warning), others like E230 = expected (debug)
                        if error_code.startswith('E5'):
                            logger.warning(f"Error getting actions for unit {unit_id}: {result.get('error')}")
                        else:
                            logger.debug(f"Skipping unit {unit_id}: {result.get('error')}")
                        continue

                    # Format actions for protocol
                    formatted_actions = self._format_unit_actions_for_response(unit_id, result)
                    if formatted_actions:
                        actions_by_actor[unit_id_str] = formatted_actions

                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid unit_id '{unit_id_str}': {e}")
                    continue
        else:
            # Fallback: generate basic actions without state_extractor
            logger.warning("StateExtractor unavailable, using fallback action generation")
            actions_by_actor = self._get_fallback_unit_actions(game_state)

        # Add player-level actions (tech_research, end_turn, city production)
        actions_by_actor['player'] = self._get_player_level_actions(game_state)

        # Log action counts for debugging
        total_actions = sum(len(actions) for actions in actions_by_actor.values())
        unit_count = len([k for k in actions_by_actor.keys() if k != 'player'])
        logger.debug(f"Generated {total_actions} legal actions for {unit_count} units + player")

        return actions_by_actor

    def _get_player_level_actions(self, game_state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get player-level actions (tech_research, end_turn, city production)."""
        actions = []

        if game_state:
            # Tech research action - use civcom's authoritative tech filtering
            # (civcom.get_researchable_techs properly checks prerequisites via can_research_tech)
            researchable = self.civcom.get_researchable_techs(self.player_id) if self.civcom else []
            available_techs = [tech['name'] for tech in researchable]
            if available_techs:
                # Only suggest one tech at a time
                tech = available_techs[0]
                actions.append({
                    'action_type': 'tech_research',
                    'actor_id': self.player_id or 0,
                    'target': {'tech_name': tech},
                    'is_valid': True
                })

            # City production actions
            cities = game_state.get('cities', {})
            for city_id_str, city in cities.items():
                # Skip cities not owned by this player
                if city.get('owner') != self.player_id:
                    continue
                try:
                    city_id = int(city_id_str)
                    # Use per-city buildable options if available
                    can_build = city.get('can_build', [])
                    if can_build:
                        # Show all production options (naval units like Trireme have high unit IDs)
                        for production in can_build:
                            prod_name = production.get('name', production) if isinstance(production, dict) else production
                            city_action = {
                                'action_type': 'city_change_production',
                                'actor_id': city_id,
                                'target': {'production_type': prod_name},
                                'is_valid': True
                            }
                            actions.append(city_action)
                            logger.debug(f"Generated city production action: {city_action}")
                    else:
                        # Fallback to common early-game options
                        for production in ['Warriors', 'Granary']:
                            actions.append({
                                'action_type': 'city_change_production',
                                'actor_id': city_id,
                                'target': {'production_type': production},
                                'is_valid': True
                            })
                except (ValueError, TypeError):
                    continue

        # Diplomacy actions - generated from civcom's diplomatic state
        if self.civcom:
            diplomacy_actions = self.civcom._get_diplomacy_actions(self.player_id)
            for da in diplomacy_actions:
                action_entry = {
                    'action_type': da['action'],
                    'actor_id': self.player_id or 0,
                    'target': da.get('params', {}),
                    'is_valid': da.get('is_valid', True),
                }
                actions.append(action_entry)

        # ALWAYS add end_turn action - critical for game progression
        actions.append({
            'action_type': 'end_turn',
            'actor_id': self.player_id or 0,
            'is_valid': True
        })

        return actions

    def _get_fallback_unit_actions(self, game_state: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Fallback action generation when state_extractor is unavailable."""
        actions_by_actor: Dict[str, List[Dict[str, Any]]] = {}

        units = game_state.get('units', {})
        directions = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw']
        direction_offsets = {
            'n': (0, -1), 'ne': (1, -1), 'e': (1, 0), 'se': (1, 1),
            's': (0, 1), 'sw': (-1, 1), 'w': (-1, 0), 'nw': (-1, -1)
        }

        for unit_id_str, unit in units.items():
            # Skip units not owned by this player
            if unit.get('owner') != self.player_id:
                continue
            unit_actions = []
            try:
                unit_id = int(unit_id_str)
            except (ValueError, TypeError):
                logger.warning(f"Invalid unit_id in fallback: '{unit_id_str}'")
                continue
            x, y = unit.get('x', 0), unit.get('y', 0)
            moves_left = unit.get('moves_left', 0)

            if moves_left > 0:
                # Add movement actions for all 8 directions
                for direction in directions:
                    dx, dy = direction_offsets[direction]
                    unit_actions.append({
                        'action_type': 'unit_move',
                        'actor_id': unit_id,
                        'target': {'x': x + dx, 'y': y + dy, 'direction': direction},
                        'is_valid': True
                    })

                # Add fortify action
                unit_actions.append({
                    'action_type': 'unit_fortify',
                    'actor_id': unit_id,
                    'is_valid': True
                })

            if unit_actions:
                actions_by_actor[unit_id_str] = unit_actions

        return actions_by_actor

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
        """Convert LLM action to FreeCiv packet format by delegating to the
        standalone packet_converter.convert_action_to_packet function.
        """
        # Delegate to shared, importable implementation which uses canonical constants
        return convert_action_to_packet(action, civcom=self.civcom)

        if action_type == 'unit_move':
            # CRITICAL FIX: Use correct packet ID 73 (PACKET_UNIT_ORDERS)
            # Previous code incorrectly used pid=31 (PACKET_CITY_INFO, server-to-client only)
            # This caused civserver to reject the packet and disconnect with "unsupported packet type"

            # Calculate destination tile index from coordinates
            # FreeCiv uses tile_index = x + y * map_width
            map_width = self.civcom.map_info.get('width', 80) if self.civcom and hasattr(self.civcom, 'map_info') else 80
            dest_tile = action['dest_x'] + action['dest_y'] * map_width

            # Get unit's current tile for sanity checking
            src_tile = self._get_unit_tile(action['unit_id'])

            # Calculate direction for unit movement
            # FreeCiv requires the dir field to contain the actual direction index
            # Direction indices follow DIR_DX/DIR_DY arrays in map.js:
            #   0: NW (dx=-1, dy=-1)  1: N  (dx=0, dy=-1)   2: NE (dx=1, dy=-1)
            #   3: W  (dx=-1, dy=0)                         4: E  (dx=1, dy=0)
            #   5: SW (dx=-1, dy=1)   6: S  (dx=0, dy=1)    7: SE (dx=1, dy=1)
            src_x = src_tile % map_width
            src_y = src_tile // map_width
            dest_x = action['dest_x']
            dest_y = action['dest_y']
            dx = dest_x - src_x
            dy = dest_y - src_y

            # Clamp to -1, 0, 1 for single-step movement
            dx = max(-1, min(1, dx))
            dy = max(-1, min(1, dy))

            # Map (dx, dy) to direction index using FreeCiv's DIR_DX/DIR_DY arrays
            # DIR_DX = [-1, 0, 1, -1, 1, -1, 0, 1]
            # DIR_DY = [-1, -1, -1, 0, 0, 1, 1, 1]
            dir_map = {
                (-1, -1): 0,  # NW
                (0, -1): 1,   # N
                (1, -1): 2,   # NE
                (-1, 0): 3,   # W
                (1, 0): 4,    # E
                (-1, 1): 5,   # SW
                (0, 1): 6,    # S
                (1, 1): 7,    # SE
            }
            direction = dir_map.get((dx, dy), -1)

            # If no movement or invalid direction, use -1
            if dx == 0 and dy == 0:
                direction = -1

            return {
                'pid': PACKET_UNIT_ORDERS,  # PACKET_UNIT_ORDERS (client-to-server)
                'unit_id': action['unit_id'],
                'src_tile': src_tile,  # Origin tile, included for sanity checking
                'dest_tile': dest_tile,  # Destination tile index
                'length': 1,  # Number of orders (single move)
                'repeat': False,  # Don't repeat the move
                'vigilant': False,  # Don't auto-wake on enemy contact
                'orders': [{
                    # CRITICAL: All 6 fields required by FreeCiv JSON parser (dataio_json.c:597-666)
                    # Use named constants from order_constants/activity_constants/action_constants
                    'order': ORDER_ACTION_MOVE,        # ORDER_ACTION_MOVE (web client default for movement)
                    'activity': ACTIVITY_LAST,    # ACTIVITY_LAST (matching web client control.js:1664)
                    'target': 0,       # No specific target
                    'sub_target': 0,   # FIX: PACKET_UNIT_ORDERS uses 'sub_target' (dataio_json.c:dio_put_unit_order_json)
                    'action': ACTION_NONE,     # Semantic 'no action' sentinel
                    'dir': direction   # CRITICAL: Actual direction index, NOT -1!
                }]
            }
        elif action_type in ('city_production', 'city_change_production'):
            # FIXED: Use correct packet ID and implement production name→ID mapping
            # Was using non-existent packet ID 45 with wrong field names
            # Should use PACKET_CITY_CHANGE (pid=35) with production_kind + production_value
            # Matches web client city.js:914 send_city_change()
            # Note: city_change_production is an alias for city_production

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
                'pid': PACKET_CITY_CHANGE,  # PACKET_CITY_CHANGE (NOT 45!)
                'city_id': action['city_id'],
                'production_kind': kind,      # 6 for units (VUT_UTYPE), 3 for buildings (VUT_IMPROVEMENT)
                'production_value': value     # unit_type_id or building_id
            }
        elif action_type == 'tech_research':
            # PACKET_PLAYER_RESEARCH requires tech ID, not tech name
            # Use RulesetMapper to dynamically map tech names to IDs from PACKET_RULESET_TECH
            # This supports all rulesets, not just the default one

            tech_name = action.get('tech_name', '')
            if not tech_name:
                raise ValueError("tech_research requires 'tech_name' field")

            # Create mapper on first use (cache per handler instance to avoid recreating)
            # Mapper reads from civcom.techs which is populated from PACKET_RULESET_TECH packets
            if not hasattr(self, '_ruleset_mapper'):
                self._ruleset_mapper = RulesetMapper(self.civcom)

            # Map tech name to ID using dynamic mapping from ruleset packets
            tech_id = self._ruleset_mapper.get_tech_id(tech_name)

            if tech_id is None:
                # Unknown tech name - provide helpful error with available options
                available_techs = self._ruleset_mapper.get_available_techs()
                error_msg = (
                    f"Unknown technology '{tech_name}' cannot be mapped to FreeCiv tech ID. "
                    f"Available techs: {', '.join(available_techs[:15])}..."
                )
                logger.error(f"Tech mapping error: {error_msg}")
                raise ValueError(error_msg)

            logger.info(f"Research: '{tech_name}' -> tech_id {tech_id}")

            return {
                'pid': PACKET_PLAYER_RESEARCH,  # PACKET_PLAYER_RESEARCH
                'tech': tech_id  # Field name is 'tech', not 'tech_name'!
            }
        elif action_type == 'end_turn':
            # CRITICAL: Signal turn completion to advance game
            # Sends PACKET_PLAYER_PHASE_DONE to tell civserver this player is done with their turn
            # Without this, the game will remain stuck on the current turn indefinitely
            # CRITICAL FIX (AGE-192): Must send 'turn' field, not 'player_no'
            # Per packets.def:971-973: PACKET_PLAYER_PHASE_DONE requires TURN turn field
            return {
                'pid': PACKET_PLAYER_PHASE_DONE,  # PACKET_PLAYER_PHASE_DONE
                'turn': self.civcom.game_turn if hasattr(self.civcom, 'game_turn') else 1
            }
        elif action_type == 'unit_build_city':
            unit_id = action['unit_id']

            # Get the tile where the unit is standing (required for city building)
            tile_id = self._get_unit_tile(unit_id)

            # Use provided city name or generate default
            city_name = action.get('name', f'City{unit_id}')

            return {
                'pid': PACKET_UNIT_DO_ACTION,              # PACKET_UNIT_DO_ACTION
                'action_type': ACTION_FOUND_CITY,      # ACTION_FOUND_CITY
                'actor_id': unit_id,
                'target_id': tile_id,
                'sub_tgt_id': 0,
                'sub_target': 0,
                'name': city_name
            }
        elif action_type == 'unit_explore':
            # FIXED: Use correct packet ID and field structure
            # Was using non-existent PACKET_UNIT_AUTO (pid=32)
            # Should use PACKET_UNIT_SERVER_SIDE_AGENT_SET (pid=74)
            # Matches web client control.js:2459-2467 request_unit_ssa_set()
            return {
                'pid': PACKET_UNIT_SERVER_SIDE_AGENT_SET,  # PACKET_UNIT_SERVER_SIDE_AGENT_SET
                'unit_id': action['unit_id'],
                'agent': 1  # SSA_AUTOEXPLORE
            }
        # AGE-192: New unit action packet converters
        elif action_type == 'unit_fortify':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_FORTIFYING,  # ACTIVITY_FORTIFYING
                'target': -1  # EXTRA_NONE (server decides)
            }
        elif action_type == 'unit_sentry':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_SENTRY,  # ACTIVITY_SENTRY
                'target': -1  # EXTRA_NONE (server decides)
            }
        elif action_type == 'unit_build_road':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_GEN_ROAD,  # ACTIVITY_GEN_ROAD
                'target': -1  # EXTRA_NONE (server auto-selects Road or Railroad)
            }
        elif action_type == 'unit_build_irrigation':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_IRRIGATE,  # ACTIVITY_IRRIGATE
                'target': -1  # EXTRA_NONE (server decides irrigation type)
            }
        elif action_type == 'unit_build_mine':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_MINE,  # ACTIVITY_MINE
                'target': -1  # EXTRA_NONE (server decides mine type)
            }

        # =================================================================
        # Combat Actions
        # =================================================================
        elif action_type == 'unit_attack':
            return {
                'pid': PACKET_UNIT_DO_ACTION,  # PACKET_UNIT_DO_ACTION
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_ATTACK  # ACTION_ATTACK
            }
        elif action_type == 'unit_suicide_attack':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_SUICIDE_ATTACK
            }
        elif action_type == 'unit_bombard':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_BOMBARD
            }
        elif action_type == 'unit_capture':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_CAPTURE_UNITS
            }
        elif action_type == 'unit_conquer_city':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_CONQUER_CITY
            }
        elif action_type == 'unit_nuke':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_NUKE
            }
        elif action_type == 'unit_nuke_city':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_NUKE_CITY
            }
        elif action_type == 'unit_nuke_units':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_NUKE_UNITS
            }
        elif action_type == 'unit_expel':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_EXPEL_UNIT
            }
        elif action_type == 'unit_heal':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_HEAL_UNIT
            }
        elif action_type == 'unit_pillage':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', action.get('tile_id', -1)),
                'sub_tgt_id': action.get('extra_id', -1),  # Which improvement to pillage
                'sub_target': action.get('extra_id', -1),
                'name': '',
                'action_type': ACTION_PILLAGE
            }

        # =================================================================
        # Transport Actions
        # =================================================================
        elif action_type == 'unit_board':
            return {
                'pid': PACKET_UNIT_DO_ACTION,  # PACKET_UNIT_DO_ACTION
                'actor_id': action['unit_id'],
                'target_id': action.get('transport_id', action.get('target_unit_id', action.get('target_id', -1))),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_TRANSPORT_BOARD
            }
        elif action_type == 'unit_embark':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('transport_id', action.get('target_unit_id', action.get('target_id', -1))),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_TRANSPORT_EMBARK
            }
        elif action_type == 'unit_disembark':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('tile_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_TRANSPORT_DISEMBARK1
            }
        elif action_type == 'unit_unload':
            # Unload a unit from transport at current location
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action.get('transport_id', action['unit_id']),
                'target_id': action.get('cargo_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_TRANSPORT_UNLOAD
            }
        elif action_type == 'unit_airlift':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_AIRLIFT
            }
        elif action_type == 'unit_paradrop':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('tile_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'sub_target': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_PARADROP
            }

        # =================================================================
        # Espionage Actions
        # =================================================================
        elif action_type == 'spy_investigate_city':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_SPY_INVESTIGATE_CITY
            }
        elif action_type == 'spy_poison':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_SPY_POISON
            }
        elif action_type == 'spy_sabotage_city':
            # Include both sub_tgt_id and sub_target for compatibility; remove normalization helper usage
            sub = action.get('building_id', -1)
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': sub,  # Specific building or -1 for random
                'sub_target': sub,
                'name': '',
                'action_type': ACTION_SPY_SABOTAGE_CITY
            }
        elif action_type == 'spy_targeted_sabotage_city':
            sub = action.get('building_id')
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': sub,  # Required for targeted sabotage
                'sub_target': sub,
                'name': '',
                'action_type': ACTION_SPY_TARGETED_SABOTAGE_CITY
            }
        elif action_type == 'spy_steal_tech':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_SPY_STEAL_TECH
            }
        elif action_type == 'spy_targeted_steal_tech':
            tech = action.get('tech_id')
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': tech,  # Required - which tech to steal
                'sub_target': tech,
                'name': '',
                'action_type': ACTION_SPY_TARGETED_STEAL_TECH
            }
        elif action_type == 'spy_incite_city':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_SPY_INCITE_CITY
            }
        elif action_type == 'spy_bribe_unit':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_unit_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_SPY_BRIBE_UNIT
            }
        elif action_type == 'establish_embassy':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_ESTABLISH_EMBASSY
            }
        elif action_type == 'spy_steal_gold':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_SPY_STEAL_GOLD
            }
        elif action_type == 'spy_spread_plague':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_SPY_SPREAD_PLAGUE
            }
        elif action_type == 'spy_nuke_city':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_CONQUER_EXTRAS
            }

        # =================================================================
        # Trade Actions
        # =================================================================
        elif action_type == 'unit_trade_route':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_TRADE_ROUTE
            }
        elif action_type == 'unit_marketplace':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_MARKETPLACE
            }
        elif action_type == 'unit_help_wonder':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_HELP_WONDER
            }

        # =================================================================
        # Diplomacy Actions
        # =================================================================
        elif action_type == 'diplomacy_start_negotiation':
            return {
                'pid': PACKET_DIPLOMACY_INIT_MEETING_REQ,
                'counterpart': action.get('target_player_id', action.get('player_id'))
            }
        elif action_type == 'diplomacy_cancel_meeting':
            return {
                'pid': PACKET_DIPLOMACY_CANCEL_MEETING_REQ,
                'counterpart': action.get('target_player_id', action.get('player_id'))
            }
        elif action_type == 'diplomacy_accept_treaty':
            return {
                'pid': PACKET_DIPLOMACY_ACCEPT_TREATY_REQ,
                'counterpart': action.get('target_player_id', action.get('player_id'))
            }
        elif action_type == 'diplomacy_cancel_pact':
            # CLAUSE_CEASEFIRE = 5, CLAUSE_PEACE = 6, CLAUSE_ALLIANCE = 7
            clause_type = action.get('clause_type', 6)  # Default to CLAUSE_PEACE
            return {
                'pid': PACKET_DIPLOMACY_CANCEL_PACT,
                'other_player_id': action.get('target_player_id', action.get('player_id')),
                'clause': clause_type
            }
        elif action_type == 'diplomacy_declare_war':
            # Cancel all peace clauses to declare war
            # Use target_player_id (set by normalization) not player_id
            return {
                'pid': PACKET_DIPLOMACY_CANCEL_PACT,
                'other_player_id': action.get('target_player_id', action.get('player_id')),
                'clause': 5  # CLAUSE_CEASEFIRE - canceling to declare war
            }
        elif action_type == 'diplomacy_propose_ceasefire':
            return {
                'pid': PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
                'counterpart': action.get('target_player_id', action.get('player_id')),
                'giver': action.get('giver', -1),  # Player giving the clause
                'type': 5,  # CLAUSE_CEASEFIRE
                'value': 0
            }
        elif action_type == 'diplomacy_propose_peace':
            return {
                'pid': PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
                'counterpart': action.get('target_player_id', action.get('player_id')),
                'giver': action.get('giver', -1),
                'type': 6,  # CLAUSE_PEACE
                'value': 0
            }
        elif action_type == 'diplomacy_propose_alliance':
            return {
                'pid': PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
                'counterpart': action.get('target_player_id', action.get('player_id')),
                'giver': action.get('giver', -1),
                'type': 7,  # CLAUSE_ALLIANCE
                'value': 0
            }
        elif action_type == 'diplomacy_share_vision':
            return {
                'pid': PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
                'counterpart': action.get('target_player_id', action.get('player_id')),
                'giver': action.get('giver', -1),
                'type': 8,  # CLAUSE_VISION
                'value': 0
            }
        elif action_type == 'diplomacy_withdraw_vision':
            return {
                'pid': PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ,
                'counterpart': action.get('target_player_id', action.get('player_id')),
                'giver': action.get('giver', -1),
                'type': 8,  # CLAUSE_VISION
                'value': 0
            }
        elif action_type == 'diplomacy_reject_treaty':
            return {
                'pid': PACKET_DIPLOMACY_CANCEL_MEETING_REQ,
                'counterpart': action['target_player_id']
            }
        elif action_type == 'diplomacy_cancel_treaty':
            clause_type = action.get('clause_type', 6)  # Default to CLAUSE_PEACE
            return {
                'pid': PACKET_DIPLOMACY_CANCEL_PACT,
                'other_player_id': action['target_player_id'],
                'clause': clause_type
            }
        elif action_type == 'diplomacy_message':
            message = action.get('message', '')
            target_player = action.get('target_player_id', -1)
            # FreeCiv chat protocol: /msg <player_id> <message> sends private message to target player
            return {
                'pid': PACKET_CHAT_MSG_REQ,
                'message': f"/msg {target_player} {message}" if target_player >= 0 else message,
            }

        # =================================================================
        # City Actions
        # =================================================================
        elif action_type == 'city_buy':
            return {
                'pid': PACKET_CITY_BUY,  # PACKET_CITY_BUY
                'city_id': action['city_id']
            }
        elif action_type == 'city_sell_improvement':
            return {
                'pid': PACKET_CITY_SELL,  # PACKET_CITY_SELL
                'city_id': action['city_id'],
                'build_id': action['improvement_id']
            }
        elif action_type == 'city_unload':
            # Unload all units from city (equivalent to activating them)
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action.get('unit_id', -1),
                'activity': ACTIVITY_IDLE,  # ACTIVITY_IDLE - activate the unit
                'target': -1
            }
        elif action_type == 'city_rename':
            return {
                'pid': PACKET_CITY_RENAME,  # PACKET_CITY_RENAME
                'city_id': action['city_id'],
                'name': action['name']
            }
        elif action_type == 'city_worklist':
            # Set city worklist - this typically uses multiple packets
            # For simplicity, we handle the change production case
            return {
                'pid': PACKET_CITY_CHANGE,  # PACKET_CITY_CHANGE
                'city_id': action['city_id'],
                'production_kind': action.get('production_kind', 0),
                'production_value': action.get('production_value', 0)
            }

        # =================================================================
        # Unit Actions - Additional
        # =================================================================
        elif action_type == 'unit_upgrade':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_UPGRADE_UNIT
            }
        elif action_type == 'unit_join_city':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_JOIN_CITY
            }
        elif action_type == 'unit_clean_pollution':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_POLLUTION,  # ACTIVITY_POLLUTION (clean pollution)
                'target': action.get('tile_id', -1)
            }
        elif action_type == 'unit_clean_fallout':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_FALLOUT,  # ACTIVITY_FALLOUT (clean fallout)
                'target': action.get('tile_id', -1)
            }
        elif action_type == 'unit_transform':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_TRANSFORM,  # ACTIVITY_TRANSFORM
                'target': -1
            }
        elif action_type == 'unit_cultivate':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('tile_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_CULTIVATE
            }
        elif action_type == 'unit_plant':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('tile_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_PLANT
            }
        elif action_type == 'unit_disband':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('target_id', -1),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_DISBAND_UNIT
            }
        elif action_type == 'unit_home_city':
            return {
                'pid': PACKET_UNIT_DO_ACTION,
                'actor_id': action['unit_id'],
                'target_id': action.get('city_id', action.get('target_id', -1)),
                'sub_tgt_id': action.get('sub_tgt_id', -1),
                'name': '',
                'action_type': ACTION_HOME_CITY
            }
        elif action_type == 'unit_wake':
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,  # PACKET_UNIT_CHANGE_ACTIVITY
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_IDLE,  # ACTIVITY_IDLE (wake up/activate)
                'target': -1
            }
        elif action_type == 'unit_skip':
            # unit_skip makes unit idle for current turn (same as unit_wake)
            return {
                'pid': PACKET_UNIT_CHANGE_ACTIVITY,
                'unit_id': action['unit_id'],
                'activity': ACTIVITY_IDLE,
                'target': -1
            }
        elif action_type == 'unit_auto_worker':
            return {
                'pid': PACKET_UNIT_SERVER_SIDE_AGENT_SET,  # PACKET_UNIT_SERVER_SIDE_AGENT_SET
                'unit_id': action['unit_id'],
                'agent': 1  # Auto-worker mode
            }

        return action  # Fallback

    def _get_unit_tile(self, unit_id: int) -> int:
        """Get the tile ID where a unit is currently located.

        Delegates to civcom.get_unit_tile() which maintains the authoritative
        unit position data from PACKET_UNIT_INFO packets.

        Args:
            unit_id: The unit's ID

        Returns:
            The tile ID where the unit is standing

        Raises:
            ValueError: If unit not found or tile information unavailable
        """
        if self.civcom:
            tile = self.civcom.get_unit_tile(unit_id)
            if tile >= 0:
                return tile
        raise ValueError(f"Unit {unit_id} not found or tile unavailable")

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
                error_msg = f"Unable to reach civserver at {host}:{port} after {max_attempts} attempts"
                raise ConnectionError(error_msg) from last_error

            # Create proper FreeCiv login packet (PACKET_SERVER_JOIN_REQ)
            # Must include pid=4 and version fields for server to parse it
            # FreeCiv usernames cannot start with a digit (see is_valid_username in player.c)
            # Agent IDs like "01JFCQ00..." start with digits, so we prefix with 'a'
            civserver_username = self.agent_id
            if civserver_username and civserver_username[0].isdigit():
                civserver_username = 'a' + civserver_username
                logger.debug(f"Prefixed agent_id with 'a' for civserver username: {civserver_username}")

            login_packet = json.dumps({
                'pid': PACKET_SERVER_JOIN_REQ,  # PACKET_SERVER_JOIN_REQ
                'username': civserver_username,
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
            # Update StateExtractor to use this civcom for fallback (fixes dual data source issue)
            # This ensures state.units and legal_actions use the same civcom instance
            self.state_extractor.civcom = self.civcom
            logger.debug(f"Created CivCom instance for {self.agent_id}")
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

    def _pause_and_suspend_partner(self):
        """Pause game and suspend partner when this agent disconnects.

        This prevents AI takeover by:
        1. Sending /set timeout 0 to pause the game
        2. Suspending the partner's session
        3. Closing the partner's WebSocket to trigger coordinated reconnection

        Both agents will be suspended and can reconnect within 60s.
        When both reconnect, the game will resume with original timeout.
        """
        try:
            # Get game session
            game_session = game_session_manager.sessions.get(self.game_id)
            if not game_session:
                logger.warning(f"No game session found for {self.game_id} - skipping pause")
                return

            # Only pause if game has started (not in pregame/setup phase)
            if not game_session.game_started:
                logger.debug(f"Game {self.game_id} not started yet - skipping pause")
                return

            # Pause the game (prevents AI takeover by stopping turn timer)
            game_session.pause_game(self.civcom, f"{self.agent_id} disconnected")

            # Find and suspend partner(s)
            for agent_id, player_info in game_session.players.items():
                if agent_id == self.agent_id:
                    continue  # Skip self

                partner_handler = player_info.handler
                if not partner_handler:
                    continue

                # Suspend partner's session
                if partner_handler.session_id:
                    session_manager.suspend_session(
                        partner_handler.session_id,
                        f"partner_{self.agent_id}_disconnected"
                    )
                    logger.info(
                        f"Suspended partner {agent_id} session due to {self.agent_id} disconnect"
                    )

                # Close partner's WebSocket to trigger coordinated reconnection
                # Use custom close code 4001 to indicate partner-triggered disconnect
                try:
                    # Check if WebSocket is already closing to prevent double-close issues
                    # when both agents disconnect simultaneously
                    ws_conn = getattr(partner_handler, 'ws_connection', None)
                    is_closing = False
                    if ws_conn:
                        # Tornado WebSocketProtocol has is_closing() method
                        is_closing_fn = getattr(ws_conn, 'is_closing', None)
                        if callable(is_closing_fn):
                            is_closing = is_closing_fn()

                    if not is_closing:
                        partner_handler.close(code=4001, reason="Partner disconnected - game paused")
                        logger.info(f"Closed partner {agent_id} WebSocket for coordinated disconnect")
                    else:
                        logger.debug(f"Partner {agent_id} WebSocket already closing, skipping close")
                except Exception as e:
                    logger.warning(f"Failed to close partner {agent_id} WebSocket: {e}")

        except Exception as e:
            logger.error(f"Error in _pause_and_suspend_partner for {self.agent_id}: {e}")

    def _suspend_partners(self):
        """Suspend partner sessions without pausing (pause already done separately).

        WARNING: Closing the partner's WebSocket (line 4417) triggers their on_close(),
        which runs the full disconnect flow including port release logic. If the
        partner's session suspension fails for any reason, on_close() may release
        the civserver port — see ⚠️ KNOWN RISK comment in on_close() port release block.
        """
        try:
            game_session = game_session_manager.sessions.get(self.game_id)
            if not game_session:
                return

            for agent_id, player_info in game_session.players.items():
                if agent_id == self.agent_id:
                    continue

                partner_handler = player_info.handler
                if not partner_handler:
                    continue

                # Suspend partner's session
                if partner_handler.session_id:
                    session_manager.suspend_session(
                        partner_handler.session_id,
                        f"partner_{self.agent_id}_disconnected"
                    )
                    logger.info(f"Suspended partner {agent_id} session due to {self.agent_id} disconnect")

                # Close partner's WebSocket
                try:
                    ws_conn = getattr(partner_handler, 'ws_connection', None)
                    is_closing = False
                    if ws_conn:
                        is_closing_fn = getattr(ws_conn, 'is_closing', None)
                        if callable(is_closing_fn):
                            is_closing = is_closing_fn()

                    if not is_closing:
                        partner_handler.close(code=4001, reason="Partner disconnected - game paused")
                        logger.info(f"Closed partner {agent_id} WebSocket for coordinated disconnect")
                except Exception as e:
                    logger.warning(f"Failed to close partner {agent_id} WebSocket: {e}")

        except Exception as e:
            logger.error(f"Error in _suspend_partners for {self.agent_id}: {e}")

    def _track_send_failure(self, error: Exception):
        """Track send failures and proactively pause if connection is degraded.

        This method is called by civcom when a packet send fails. If we see
        multiple consecutive failures, we proactively pause the game before
        the connection fully dies - this gives us a better chance of
        successfully sending the pause command.

        Args:
            error: The exception that occurred during send
        """
        # Initialize tracking attributes if not present
        if not hasattr(self, '_send_failure_count'):
            self._send_failure_count = 0
        if not hasattr(self, '_connection_dead'):
            self._connection_dead = False
        if not hasattr(self, '_connection_dead_since'):
            self._connection_dead_since = None

        # Once marked dead, silently ignore further failures to avoid log spam
        if self._connection_dead:
            return

        self._send_failure_count += 1

        # After threshold, mark connection as dead and attempt one proactive pause
        # Uses configurable CONNECTION_DEAD_FAILURE_THRESHOLD (default 20)
        if self._send_failure_count >= CONNECTION_DEAD_FAILURE_THRESHOLD:
            self._connection_dead = True  # Stop tracking further failures
            self._connection_dead_since = time.time()  # Track when connection died (for TTL cleanup)
            logger.error(
                f"Connection dead for {self.agent_id} "
                f"({self._send_failure_count} consecutive failures) - attempting proactive pause"
            )

            if self.game_id:
                game_session = game_session_manager.sessions.get(self.game_id)
                if game_session and game_session.game_started and not game_session.is_paused:
                    if self.civcom and not self.civcom.stopped:
                        success = game_session.pause_game(
                            self.civcom,
                            f"{self.agent_id} connection dead"
                        )
                        if success:
                            logger.info(f"Proactive pause successful for dead connection")
        else:
            # Only log warning before threshold is reached
            logger.warning(
                f"Send failure #{self._send_failure_count} for {self.agent_id}: {error}"
            )

    def _reset_send_failure_count(self):
        """Reset the send failure counter and dead flag after successful send."""
        self._send_failure_count = 0
        self._connection_dead = False
        self._connection_dead_since = None

    def _check_and_resume_game(self):
        """Check if game should be resumed after reconnection.

        Called after successful authentication/reconnection. If the game
        is paused and all players are now reconnected, resume the game
        by restoring the original timeout and notifying all agents.
        """
        if not self.game_id:
            return

        try:
            game_session = game_session_manager.sessions.get(self.game_id)
            if not game_session:
                return

            # Only proceed if game is paused
            if not game_session.is_paused:
                logger.debug(f"🔍 RESUME_CHECK: game_id={self.game_id} | is_paused=False | agent={self.agent_id}")
                return

            # Update handler reference and check all_connected under lock
            # This prevents race conditions when multiple handlers reconnect simultaneously
            all_connected = False
            handlers_to_notify = []
            with game_session._players_lock:
                # Update the player's handler reference in the game session
                # (needed because handler is new after reconnection)
                if self.agent_id in game_session.players:
                    game_session.players[self.agent_id].handler = self
                    logger.debug(f"Updated handler reference for {self.agent_id} in game session")

                # Check if all players are now connected with valid handlers and civcom
                all_connected = True
                connection_status = {}
                for agent_id, player_info in game_session.players.items():
                    handler = player_info.handler
                    if not handler:
                        connection_status[agent_id] = "missing_handler"
                        all_connected = False
                    elif not handler.civcom:
                        connection_status[agent_id] = "missing_civcom"
                        all_connected = False
                    elif handler.civcom.stopped:
                        connection_status[agent_id] = "civcom_stopped"
                        all_connected = False
                    else:
                        connection_status[agent_id] = "connected"
                        handlers_to_notify.append(handler)

                logger.info(
                    f"🔍 RESUME_CHECK: game_id={self.game_id} | triggered_by={self.agent_id} | "
                    f"all_connected={all_connected} | status={connection_status}"
                )

            # Resume outside the lock (to avoid holding lock during I/O)
            if all_connected:
                # Get current turn before resume for logging
                current_turn = getattr(self.civcom, 'turn', 'unknown') if self.civcom else 'unknown'

                logger.info(
                    f"🎮 GAME_RESUME_INITIATED: game_id={self.game_id} | "
                    f"current_turn={current_turn} | players={list(game_session.players.keys())}"
                )

                resume_success = game_session.resume_game(self.civcom)

                if resume_success:
                    # CRITICAL: Notify all agents that the game has resumed
                    # Without this, agents don't know they can continue playing!
                    self._notify_agents_game_resumed(handlers_to_notify, current_turn, game_session)
                else:
                    logger.error(
                        f"❌ GAME_RESUME_FAILED: game_id={self.game_id} | "
                        f"resume_game returned False"
                    )
            else:
                logger.info(
                    f"⏸️ GAME_STILL_PAUSED: game_id={self.game_id} | "
                    f"waiting_for_players | status={connection_status}"
                )

        except Exception as e:
            logger.error(f"❌ RESUME_CHECK_ERROR: game_id={self.game_id} | agent={self.agent_id} | error={e}")

    def _notify_agents_game_resumed(self, handlers, current_turn, game_session):
        """Send game_resumed notification to all connected agents.

        This is CRITICAL for agents to know they should continue playing after
        a recovery/reconnection cycle. Without this notification, agents may
        sit idle waiting for something that will never come.

        Args:
            handlers: List of LLMWSHandler instances to notify
            current_turn: Current game turn number
            game_session: GameSession instance for game metadata
        """
        notification = {
            'type': 'game_resumed',
            'game_id': self.game_id,
            'turn': current_turn,
            'message': 'Game has resumed after reconnection. Please query state and continue playing.',
            'action_required': 'state_query',
            'timestamp': time.time(),
        }

        notified_count = 0
        failed_count = 0

        for handler in handlers:
            try:
                handler.write_message(json.dumps(notification))
                notified_count += 1
                logger.info(
                    f"📤 GAME_RESUMED_NOTIFICATION_SENT: game_id={self.game_id} | "
                    f"agent={handler.agent_id} | turn={current_turn}"
                )
            except Exception as e:
                failed_count += 1
                logger.error(
                    f"❌ GAME_RESUMED_NOTIFICATION_FAILED: game_id={self.game_id} | "
                    f"agent={handler.agent_id} | error={e}"
                )

        logger.info(
            f"🎮 GAME_RESUMED_NOTIFICATIONS_COMPLETE: game_id={self.game_id} | "
            f"notified={notified_count} | failed={failed_count} | turn={current_turn}"
        )

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

        # PAUSE GAME AND SUSPEND PARTNER before session cleanup
        # Try to pause even if our civcom is stopped - use partner's civcom as fallback
        if self.game_id:
            game_session = game_session_manager.sessions.get(self.game_id)
            if game_session and game_session.game_started and not game_session.is_paused:
                # Try our civcom first
                civcom_to_use = None
                if self.civcom and not self.civcom.stopped:
                    civcom_to_use = self.civcom
                else:
                    # Our civcom is dead, try partner's civcom
                    logger.warning(f"Own civcom stopped for {self.agent_id}, trying partner's civcom for pause")
                    for agent_id, player_info in game_session.players.items():
                        if agent_id == self.agent_id:
                            continue
                        partner_handler = player_info.handler
                        if partner_handler and partner_handler.civcom and not partner_handler.civcom.stopped:
                            civcom_to_use = partner_handler.civcom
                            logger.info(f"Using {agent_id}'s civcom for pause (own civcom stopped)")
                            break

                if civcom_to_use:
                    success = game_session.pause_game(civcom_to_use, f"{self.agent_id} disconnected")
                    logger.info(f"Pause attempt for {self.game_id}: success={success}")
                    # Still call partner suspend logic if we have our own civcom
                    if self.civcom and not self.civcom.stopped:
                        self._suspend_partners()
                else:
                    logger.error(f"Cannot pause game {self.game_id} - no valid civcom available!")
            elif self.civcom and not self.civcom.stopped:
                # Game not started or already paused, but still suspend partners
                self._pause_and_suspend_partner()

        # Suspend session to allow reconnection within timeout window
        # (Uses existing suspend_session infrastructure that was never wired up)
        session_suspended = False
        if self.session_id:
            session_suspended = session_manager.suspend_session(self.session_id, "connection_closed")
            logger.info(f"Session {self.session_id} suspended for {self.agent_id} - reconnection allowed")

        # CRITICAL: Preserve CivCom when session is suspended for reconnection
        # The CivCom maintains TCP socket to FreeCiv server with all game state (units, cities, etc.)
        # Destroying it would lose state that FreeCiv won't resend on reconnect
        if session_suspended and self.civcom and not self.civcom.stopped:
            # Keep CivCom alive but detach from this WebSocket handler
            # The civcom will continue receiving packets from FreeCiv server
            logger.info(
                f"🔄 Preserving CivCom for {self.agent_id} during session suspension:\n"
                f"   CivCom keeps TCP connection to FreeCiv server (state preserved)\n"
                f"   Units in CivCom: {len(getattr(self.civcom, 'player_units', {}))}\n"
                f"   Will be reused on reconnection"
            )
            # Don't destroy civcom - it stays registered in civcom_registry for reconnection
            # Just clear our reference (civcom thread keeps running)
        else:
            # Session not suspended (terminated) or civcom already stopped - clean up fully
            if self.civcom:
                logger.info(f"Cleaning up CivCom for {self.agent_id} (session not suspended or civcom stopped)")
                self.civcom.stopped = True
                self.civcom.close_connection()

            if self.game_id and self.agent_id:
                registered_civcom = civcom_registry.get_civcom(self.game_id, self.agent_id)
                if registered_civcom is self.civcom:
                    civcom_registry.unregister_game(self.game_id, self.agent_id)

            # Release the allocated civserver port back to the pool
            # This prevents zombie sessions where ports stay unavailable after gateway failures
            #
            # Port release must account for paused reconnect windows.
            # If the game is paused for coordinated reconnect, the civserver port
            # must remain allocated until resume or stale-session cleanup timeout.
            civserver_port = None
            if self.session_info and hasattr(self.session_info, 'civserver_port'):
                civserver_port = self.session_info.civserver_port
            elif self.game_id:
                # Try to get port from game session if session_info doesn't have it
                game_session = game_session_manager.sessions.get(self.game_id)
                if game_session:
                    civserver_port = game_session.civserver_port

            if civserver_port and self.game_id:
                # Check if this is the last player in the game session
                # Only release port when ALL players have disconnected (not just one)
                game_session = game_session_manager.sessions.get(self.game_id)
                should_release = False
                remaining_players = 0

                if game_session:
                    # CRITICAL: Hold lock for BOTH the check AND the decision to release
                    # This prevents TOCTOU race where Player B could reconnect between
                    # our count check and the release action
                    with game_session._players_lock:
                        # Remove ourselves from players dict first
                        if self.agent_id in game_session.players:
                            del game_session.players[self.agent_id]
                            logger.debug(f"Removed {self.agent_id} from game_session.players")

                        # Now count remaining players (should be 0 if we were the last)
                        remaining_players = len(game_session.players)

                        # Make the decision while still holding the lock
                        # If paused for reconnect, skip release and let stale cleanup
                        # enforce SESSION_SUSPENSION_TIMEOUT_SECS.
                        if remaining_players == 0 and not game_session.is_paused:
                            should_release = True
                            # CRITICAL: Set port_releasing flag while still holding lock
                            # This prevents add_player() from accepting new connections
                            # during the window between releasing the lock and completing
                            # the port release
                            game_session._port_releasing = True
                            game_session._port_releasing_since = time.time()  # Issue #1 Fix: Record timestamp for timeout safety net

                # Now act on the decision (outside lock is fine since decision was atomic)
                if should_release:
                    # Stop observer CivCom before releasing the port
                    try:
                        stop_observer_civcom(self.game_id)
                    except Exception as e:
                        logger.debug(f"Observer cleanup error (benign): {e}")

                    logger.info(
                        f"PORT_RELEASE_START game_id={self.game_id} agent_id={self.agent_id} "
                        f"port={civserver_port} reason=last_player_disconnected"
                    )
                    # Schedule async port release via IOLoop
                    try:
                        from tornado.ioloop import IOLoop
                        IOLoop.current().add_callback(
                            lambda gid=self.game_id, port=civserver_port: asyncio.create_task(
                                game_session_manager.release_civserver_port(gid, port)
                            )
                        )
                    except Exception as e:
                        logger.error(f"Failed to schedule port release: {e}")
                elif game_session:
                    if remaining_players == 0 and game_session.is_paused:
                        logger.info(
                            f"PORT_RELEASE_SKIPPED game_id={self.game_id} agent_id={self.agent_id} "
                            f"port={civserver_port} reason=game_paused_for_reconnect"
                        )
                    else:
                        logger.info(
                            f"Player {self.agent_id} disconnected from game {self.game_id}, "
                            f"but {remaining_players} players remain - port {civserver_port} stays allocated"
                        )

        self.civcom = None

        # Remove from agent registry
        if self.agent_id and self.agent_id in llm_agents:
            del llm_agents[self.agent_id]

        # Invalidate cache for this player
        # Note: player_id=0 is valid, so use 'is not None' instead of falsy check
        if self.player_id is not None:
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
