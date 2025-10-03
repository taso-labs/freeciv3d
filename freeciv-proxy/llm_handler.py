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
from tornado import websocket
from civcom import CivCom
from state_cache import state_cache
from state_extractor import StateExtractor, StateFormat
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
    """

    def __init__(self, application, request, **kwargs):
        super().__init__(application, request, **kwargs)
        self.id = str(uuid.uuid4())
        self.is_llm_agent = False
        self.agent_id = None
        self.player_id = None
        self.civcom = None
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

        # Initialize message validator with configurable size limit
        max_size_mb = llm_config.get('validation.max_message_size_mb', 1.0)
        self.message_validator = MessageValidator(max_message_size=int(max_size_mb * 1024 * 1024))

        # Initialize state extractor for proper state formatting
        self.state_extractor = StateExtractor()

    def open(self):
        """Handle WebSocket connection opening"""
        logger.info(f"LLM agent connection opened: {self.id}")
        self.set_nodelay(True)

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
        self.write_message(json.dumps({
            'type': 'welcome',
            'handler_id': self.id,
            'message': 'LLM agent handler ready. Send llm_connect message to authenticate.'
        }))

    def on_message(self, message):
        """Handle incoming WebSocket messages"""
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
                self._handle_llm_connect(msg_data)
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

    def _handle_llm_connect(self, msg_data: Dict[str, Any]):
        """Handle LLM agent authentication with session management"""
        print(f"[DEBUG] _handle_llm_connect called, msg_data keys: {list(msg_data.keys())}", flush=True)
        print(f"[DEBUG] msg_data nation: {msg_data.get('nation')}, leader_name: {msg_data.get('leader_name')}", flush=True)
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

            # Generate player ID (simplified)
            self.player_id = len(llm_agents) + 1
            self.session_info.player_id = self.player_id

            # Register agent
            llm_agents[self.agent_id] = self
            self.is_llm_agent = True

            # Connect to civserver (simplified connection)
            # TODO: Implement proper game server allocation via metaserver
            # Use port 6000 (singleplayer but we'll configure for multi) since multiplayer ports had issues
            # Ports 6001/6004 crashed, 6007 may have existing players
            civserver_port = msg_data.get('port', 6000)  # Try port 6000 (singleplayer, will set minplayers)

            # Get or create game session for coordination
            game_id = msg_data.get('data', {}).get('game_id', 'default_game')
            logger.info(f"Agent {self.agent_id} joining game session '{game_id}' on port {civserver_port}")

            # Connect to civserver
            logger.info(f"Connecting agent {self.agent_id} to civserver port {civserver_port}")
            self._connect_to_civserver(civserver_port, game_id)

            # After connection, complete pregame flow: select nation and mark ready
            # Extract nation preference from message
            nation_name = msg_data.get('data', {}).get('nation') or msg_data.get('nation', 'random')
            leader_name = msg_data.get('data', {}).get('leader_name') or msg_data.get('leader_name', self.agent_id)

            print(f"[DEBUG] Starting nation selection for {self.agent_id}: nation={nation_name}, leader={leader_name}", flush=True)

            # Get nation ID
            nation_id = self._get_nation_id(nation_name)
            print(f"[DEBUG] Got nation ID: {nation_id}", flush=True)

            # Wait briefly for connection to stabilize
            time.sleep(0.5)

            # Send PACKET_NATION_SELECT_REQ (pid=10)
            print(f"[DEBUG] About to send PACKET_NATION_SELECT_REQ, civcom={self.civcom is not None}", flush=True)
            nation_packet = json.dumps({
                "pid": 10,
                "player_no": self.player_id,
                "nation_no": nation_id,
                "is_male": True,
                "name": leader_name,
                "style": 0  # Default city style
            })
            print(f"[DEBUG] Nation packet: {nation_packet}", flush=True)
            self.civcom.queue_to_civserver(nation_packet)
            print(f"[DEBUG] Packet queued successfully", flush=True)
            logger.info(f"Sent PACKET_NATION_SELECT_REQ for {nation_name} (ID {nation_id}) - Leader: {leader_name}")

            # Register with game session manager that nation was selected
            game_session = game_session_manager.get_session(game_id)
            if game_session:
                game_session.mark_nation_selected(self.agent_id)

            # Wait briefly for nation selection to process
            time.sleep(0.5)

            # Send PACKET_PLAYER_READY (pid=11)
            ready_packet = json.dumps({
                "pid": 11,
                "is_ready": True,
                "player_no": self.player_id
            })
            self.civcom.queue_to_civserver(ready_packet)
            logger.info(f"Sent PACKET_PLAYER_READY for player {self.player_id}")

            # Register with game session manager that player is ready
            if game_session:
                game_session.mark_player_ready(self.agent_id)

            # Send success response with session information
            self.write_message(json.dumps({
                'type': 'auth_success',
                'agent_id': self.agent_id,
                'session_id': self.session_id,
                'player_id': self.player_id,
                'capabilities': list(capability_set),
                'session_expires_in': int(self.session_info.expires_at - time.time()),
                'message': 'LLM agent authenticated successfully'
            }))

            SecurityLogger.log_authentication_attempt(self.agent_id, True)
            SecurityLogger.log_connection_event(self.agent_id, "AUTHENTICATED",
                                              f"player_id={self.player_id}, session_id={self.session_id}")
            logger.info(f"LLM agent authenticated: {self.agent_id} (player {self.player_id}, session {self.session_id})")

        except Exception as e:
            error_response = error_handler.handle_system_error(
                "authentication", e, self.agent_id, self.session_id
            )
            self.write_message(error_response.to_json())

    def _handle_state_query(self, msg_data: Dict[str, Any]):
        """Handle optimized state query for LLM"""
        if not self.is_llm_agent:
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E120',
                'message': 'Not authenticated as LLM agent'
            }))
            return

        # Update session activity
        if self.session_id:
            session_manager.update_session_activity(self.session_id)

        try:
            query_format = msg_data.get('format', 'llm_optimized')
            include_actions = msg_data.get('include_actions', True)

            # Generate cache key with session info for security
            cache_key = f"state_{self.player_id}_{query_format}_{int(time.time() // 5)}"  # 5-second granularity

            # Try cache first
            cached_state = state_cache.get(cache_key)
            if cached_state:
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
            state_data = self._build_optimized_state(query_format, include_actions)

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
            logger.exception(f"Error in state query: {e}")
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E121',
                'message': 'State query failed'
            }))

    def _handle_action(self, msg_data: Dict[str, Any]):
        """Handle and validate LLM action"""
        if not self.is_llm_agent:
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

            # Sanitize action data to prevent injection attacks
            try:
                sanitized_action = InputSanitizer.sanitize_action_data(action_data)
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

            # Validate action
            validation_result = self.action_validator.validate_action(
                sanitized_action, self.player_id, self._get_current_game_state()
            )

            if not validation_result.is_valid:
                self.write_message(json.dumps({
                    'type': 'action_rejected',
                    'error_code': validation_result.error_code,
                    'error_message': validation_result.error_message,
                    'action': action_data
                }))
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
        # Get actual game state from civcom if available
        if self.civcom and hasattr(self.civcom, 'get_full_state'):
            try:
                full_state = self.civcom.get_full_state(self.player_id)
            except Exception as e:
                logger.warning(f"Failed to get game state from civcom: {e}")
                full_state = self._get_fallback_state()
        else:
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
            state = self.state_extractor.get_state(full_state, state_format)
        except Exception as e:
            logger.error(f"StateExtractor failed: {e}, falling back to manual construction")
            import traceback
            logger.error(f"StateExtractor traceback: {traceback.format_exc()}")
            # Fallback to basic state if extractor fails - ENSURE LISTS NOT DICTS
            state = {
                'turn': full_state.get('turn', 1),
                'phase': full_state.get('phase', 'movement'),
                'player_id': self.player_id,
                'timestamp': time.time(),
                'game': {
                    'turn': full_state.get('turn', 1),
                    'phase': full_state.get('phase', 'movement')
                },
                'map': {'width': 80, 'height': 50, 'tiles': [], 'visibility': {}},
                'players': [],
                'units': [],  # MUST BE LIST
                'cities': []  # MUST BE LIST
            }

        # Add player_id and timestamp which are handler-specific
        state['player_id'] = self.player_id
        state['timestamp'] = time.time()

        # For llm_optimized format, add AI analysis layers
        if format_type == 'llm_optimized':
            state['strategic_summary'] = self._get_strategic_summary()
            state['immediate_priorities'] = self._get_immediate_priorities()
            state['threats'] = self._assess_threats()
            state['opportunities'] = self._identify_opportunities()

            if include_actions:
                state['legal_actions'] = self._get_legal_actions_optimized(full_state)

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
            'players': {},
            'techs': [],
            'map_info': {}
        }

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
                players = state.get('players', {})
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

                # Check for aggressive players
                for player_id, player_data in players.items():
                    if player_id != str(self.player_id) and player_data.get('attitude') == 'hostile':
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
                players = state.get('players', {})
                friendly_players = [p for p_id, p in players.items() if p_id != str(self.player_id) and p.get('attitude') == 'friendly']
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
                unit_type = unit.get('type', '').lower()
                current_x, current_y = unit.get('x', 0), unit.get('y', 0)

                if unit_type in ['settlers', 'engineer']:
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
            return {
                'pid': 50,  # PACKET_PLAYER_RESEARCH
                'tech_name': action['tech_name'],
                'player_id': action.get('player_id', self.player_id)
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
        """Get nation ID from nation name.

        Args:
            nation_name: Name of the nation (e.g., "Americans", "Romans")

        Returns:
            Nation ID integer (0-9 for known nations, 0 for unknown)
        """
        if not nation_name or nation_name.lower() == 'random':
            # Select random nation from defaults
            import random
            nation_name = random.choice(DEFAULT_NATIONS)
            logger.info(f"Auto-selecting random nation: {nation_name}")

        nation_id = NATION_MAP.get(nation_name, 0)
        logger.debug(f"Nation '{nation_name}' → ID {nation_id}")
        return nation_id

    def _connect_to_civserver(self, port: int, game_id: str):
        """Connect to civserver and register with game session manager"""
        try:
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
            self.civcom.start()

            logger.info(f"LLM agent {self.agent_id} connected to civserver on port {port}")

            # Register player with game session manager
            game_session = game_session_manager.get_or_create_session(game_id, port, min_players=2)
            game_session.add_player(self.agent_id, self.player_id, self)
            logger.info(f"Registered agent {self.agent_id} with game session {game_id}")

        except Exception as e:
            logger.exception(f"Failed to connect LLM agent to civserver: {e}")
            self.write_message(json.dumps({
                'type': 'error',
                'code': 'E140',
                'message': 'Failed to connect to game server'
            }))

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
        logger.info(f"LLM agent connection closed: {self.agent_id}")

        # Terminate session
        if self.session_id:
            session_manager.terminate_session(self.session_id, "connection_closed")

        # Clean up civcom connection
        if self.civcom:
            self.civcom.stopped = True
            self.civcom.close_connection()

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

        # Log unauthorized origin attempts
        SecurityLogger.log_security_violation(
            self.agent_id or "unknown",
            "INVALID_ORIGIN",
            f"Rejected origin: {origin}"
        )
        logger.warning(f"Rejected WebSocket connection from unauthorized origin: {origin}")
        return False

    def get_compression_options(self):
        """Enable WebSocket compression"""
        return {'compression_level': 9, 'mem_level': 9}