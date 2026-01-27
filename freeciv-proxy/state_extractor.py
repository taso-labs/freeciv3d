#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
State Extraction Service for FreeCiv LLM Integration

Extracts and formats game state from the FreeCiv server into LLM-friendly JSON.
Provides REST API endpoints for game state extraction and optimization.

## Collection Format

All collections (units, cities, players) are returned as **dictionaries keyed by ID**:

```python
{
    "units": {
        "123": {"id": 123, "type": "Warrior", "owner": 0},
        "456": {"id": 456, "type": "Settler", "owner": 0}
    },
    "cities": {
        "1": {"id": 1, "name": "Capital", "owner": 0}
    }
}
```

**Key Design Decisions:**
- Dictionary keys are strings (not integers) for JSON compatibility
- Provides O(1) lookups: `units["123"]` instead of filtering lists
- Consistent structure across all collection types

## Type Normalization

For LLM readability, certain fields use human-readable strings:
- `nation`: "Romans" instead of integer ID
- `activity`: "idle" instead of integer enum

See docs/llm_websocket_protocol.md for complete protocol documentation.
"""

import json
import time
import logging
import os
import atexit
import signal
import sys
from enum import Enum
from typing import Dict, Any, List, Optional, Union, Tuple
from tornado import web
from tornado.concurrent import run_on_executor
from concurrent.futures import ThreadPoolExecutor

from state_cache import StateCache, CacheEntry
from civcom import CivCom

# Required modules for production use
try:
    from error_handler import error_handler, ErrorSeverity, ErrorCategory
    from security import InputSanitizer
    from api_rate_limiter import api_rate_limiter
    from auth import authenticator, AuthenticationError, AuthorizationError
except ImportError as e:
    raise ImportError(
        f"Failed to import required modules: {e}. "
        "The error_handler, security, api_rate_limiter, and auth modules are required. "
        "Ensure all required .py files are available in the Python path."
    )

logger = logging.getLogger("freeciv-proxy")


class StateExtractionError(Exception):
    """Exception raised during state extraction operations"""
    def __init__(self, message: str, game_id: str = None, player_id: int = None, cause: Exception = None):
        super().__init__(message)
        self.game_id = game_id
        self.player_id = player_id
        self.cause = cause


class CacheError(Exception):
    """Exception raised during cache operations"""
    def __init__(self, message: str, cache_key: str = None, operation: str = None):
        super().__init__(message)
        self.cache_key = cache_key
        self.operation = operation


class ValidationError(Exception):
    """Exception raised during input validation"""
    def __init__(self, message: str, parameter: str = None, value: Any = None):
        super().__init__(message)
        self.parameter = parameter
        self.value = value


class CivComNotFoundError(StateExtractionError):
    """Exception raised when CivCom instance is not available"""
    def __init__(self, game_id: str):
        message = f"No CivCom instance available for game {game_id}"
        super().__init__(message, game_id=game_id)


class CivComRegistry:
    """
    Registry for CivCom instances with proper lifecycle management
    Provides clean interface for registering and retrieving game connections

    FIXED: Now uses composite key (game_id, agent_id) to support multiple players per game
    """

    def __init__(self):
        self._civcom_instances: Dict[Tuple[str, str], CivCom] = {}
        self._game_metadata: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def register_game(self, game_id: str, agent_id: str | CivCom = None, civcom: Optional[CivCom] = None, metadata: Optional[Dict[str, Any]] = None):
        """Register a CivCom instance for a game.

        Backwards-compatible signature support:
        - register_game(game_id, civcom)
        - register_game(game_id, agent_id, civcom)

        Args:
            game_id: Unique game identifier
            agent_id: Either agent_id (str) or a CivCom instance when using legacy 2-arg form
            civcom: CivCom instance to register (required when specifying agent_id)
            metadata: Optional metadata dictionary
        """
        # Backwards compatibility: allow register_game(game_id, civcom)
        if civcom is None:
            # agent_id parameter is actually the civcom instance in legacy calls
            civcom = agent_id
            agent_id = "default"

        if not isinstance(game_id, str) or not game_id.strip():
            raise ValueError("game_id must be a non-empty string")

        if not isinstance(agent_id, str) or not agent_id.strip():
            raise ValueError("agent_id must be a non-empty string")

        if not civcom:
            raise ValueError("civcom instance cannot be None")

        key = (game_id, agent_id)
        if key in self._civcom_instances:
            logger.warning(f"Replacing CivCom for agent {agent_id} in game {game_id}")

        self._civcom_instances[key] = civcom
        self._game_metadata[key] = metadata or {}

        logger.info(f"Registered CivCom for agent {agent_id} in game {game_id}")

    def unregister_game(self, game_id: str, agent_id: str):
        """Unregister a game and clean up resources

        Args:
            game_id: Unique game identifier
            agent_id: Unique agent/player identifier
        """
        key = (game_id, agent_id)
        if key in self._civcom_instances:
            try:
                # Try to cleanup the civcom instance if it has cleanup methods
                civcom = self._civcom_instances[key]
                if hasattr(civcom, 'cleanup'):
                    civcom.cleanup()
                elif hasattr(civcom, 'close'):
                    civcom.close()
            except Exception as e:
                logger.warning(f"Error cleaning up CivCom for agent {agent_id} in game {game_id}: {e}")

            del self._civcom_instances[key]
            if key in self._game_metadata:
                del self._game_metadata[key]

            logger.info(f"Unregistered CivCom for agent {agent_id} in game {game_id}")

    def get_civcom(self, game_id: str, agent_id: str) -> Optional[CivCom]:
        """Get CivCom instance for a specific game and agent

        Args:
            game_id: Unique game identifier
            agent_id: Unique agent/player identifier

        Returns:
            CivCom instance or None if not found
        """
        if not isinstance(game_id, str) or not isinstance(agent_id, str):
            return None

        key = (game_id, agent_id)
        return self._civcom_instances.get(key)

    def get_all_for_game(self, game_id: str) -> Dict[Tuple[str, str], CivCom]:
        """Get all CivCom instances for a specific game

        Useful for multiplayer game coordination where you need access to all
        players' connections for the same game.

        Args:
            game_id: Unique game identifier

        Returns:
            Dictionary mapping (game_id, agent_id) tuples to CivCom instances
        """
        return {k: v for k, v in self._civcom_instances.items() if k[0] == game_id}

    def has_game(self, game_id: str, agent_id: Optional[str] = None) -> bool:
        """Check if game is registered

        Args:
            game_id: Unique game identifier
            agent_id: Optional agent identifier. If provided, checks for specific agent.
                     If None, checks if any agent is registered for this game.

        Returns:
            True if game (and optionally agent) is registered
        """
        if agent_id is not None:
            key = (game_id, agent_id)
            return key in self._civcom_instances
        else:
            # Check if any agent is registered for this game
            return any(k[0] == game_id for k in self._civcom_instances.keys())

    def list_games(self) -> List[str]:
        """Get list of unique registered game IDs"""
        return list(set(k[0] for k in self._civcom_instances.keys()))

    def get_game_metadata(self, game_id: str, agent_id: str) -> Dict[str, Any]:
        """Get metadata for a specific game and agent

        Args:
            game_id: Unique game identifier
            agent_id: Unique agent/player identifier

        Returns:
            Metadata dictionary or empty dict if not found
        """
        key = (game_id, agent_id)
        return self._game_metadata.get(key, {})

    def get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""
        unique_games = set(k[0] for k in self._civcom_instances.keys())
        return {
            'total_connections': len(self._civcom_instances),
            'unique_games': len(unique_games),
            'active_games': list(unique_games),
            'registry_size_kb': len(str(self._civcom_instances)) / 1024
        }

# Global registry for CivCom instances
civcom_registry = CivComRegistry()

# Shared thread pool executor for all state extraction operations
# Configurable via environment variable, defaults to 4
_MAX_WORKERS = int(os.getenv('STATE_EXTRACTOR_THREADS', '4'))
_shared_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="state-extractor")

# Configurable constants for magic numbers
MAX_TURN_NUMBER = int(os.getenv('MAX_TURN_NUMBER', '10000'))
MAX_EXPANSION_SITES = int(os.getenv('MAX_EXPANSION_SITES', '5'))
MAX_UNITS_ANALYZED = int(os.getenv('MAX_UNITS_ANALYZED', '5'))
MAX_CITIES_ANALYZED = int(os.getenv('MAX_CITIES_ANALYZED', '5'))
MAX_THREATS_RETURNED = int(os.getenv('MAX_THREATS_RETURNED', '5'))

def shutdown_executor():
    """Shutdown the shared thread pool executor gracefully"""
    if _shared_executor:
        logger.info("Shutting down state extractor thread pool...")
        _shared_executor.shutdown(wait=True)
        logger.info("State extractor thread pool shutdown complete")


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_executor()
    sys.exit(0)


# Register shutdown handlers
atexit.register(shutdown_executor)
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def authenticate_request(request_handler, required_permission: str = 'state_read') -> Tuple[bool, Optional[int], Optional[str], str]:
    """
    Authenticate request using API key or session

    Returns:
        tuple: (authenticated: bool, player_id: Optional[int], game_id: Optional[str], error_message: str)
    """
    # Check environment and authentication settings
    environment = os.getenv('ENVIRONMENT', 'production').lower()
    auth_enabled = os.getenv('AUTH_ENABLED', 'true').lower() == 'true'

    # Only allow authentication bypass in development environment
    if not auth_enabled:
        if environment == 'development':
            # Authentication disabled in development, allow but warn
            logger.warning(f"Authentication bypassed in development mode for {request_handler.request.remote_ip}")
            # Add warning header to response
            request_handler.set_header("X-Auth-Bypassed", "true")
            request_handler.set_header("X-Environment", "development")
            return True, None, None, ""
        else:
            # Force authentication in production/staging regardless of AUTH_ENABLED setting
            logger.error(f"Authentication bypass attempted in {environment} environment - BLOCKED")
            # Continue to authentication logic below

    try:
        # Get authentication credentials from headers or query params
        api_key = request_handler.get_argument('api_key', None)
        if not api_key:
            api_key = request_handler.request.headers.get('Authorization')
            if api_key and api_key.startswith('Bearer '):
                api_key = api_key[7:]

        session_id = request_handler.get_argument('session_id', None)
        if not session_id:
            session_id = request_handler.request.headers.get('X-Session-ID')

        # Attempt authentication
        authenticated, auth_player_id, auth_game_id = authenticator.authenticate_request(
            api_key=api_key,
            session_id=session_id,
            required_permission=required_permission
        )

        if not authenticated:
            return False, None, None, "Authentication required. Provide valid API key or session ID."

        return True, auth_player_id, auth_game_id, ""

    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return False, None, None, f"Authentication failed: {e}"


def validate_request_parameters(game_id: str, player_id: Any, format_str: str = 'full', since_turn: Any = None) -> tuple:
    """
    Validate and sanitize request parameters

    Returns:
        tuple: (validated_game_id, validated_player_id, validated_format, validated_since_turn)

    Raises:
        ValidationError: If any parameter is invalid
    """
    try:
        # Validate game_id (alphanumeric, underscores, max 50 chars)
        if not isinstance(game_id, str) or not game_id.strip():
            raise ValidationError("Game ID must be a non-empty string", parameter="game_id", value=game_id)

        if len(game_id) > 50 or not all(c.isalnum() or c in '_-' for c in game_id):
            raise ValidationError("Game ID must be alphanumeric with underscores/hyphens, max 50 characters",
                                parameter="game_id", value=game_id)

        # Validate player_id
        validated_player_id = InputSanitizer.sanitize_player_id(player_id)

        # Validate format
        valid_formats = ['full', 'delta', 'llm_optimized']
        if format_str not in valid_formats:
            raise ValidationError(f"Format must be one of: {', '.join(valid_formats)}",
                                parameter="format", value=format_str)

        # Validate since_turn if provided
        validated_since_turn = None
        if since_turn is not None:
            try:
                validated_since_turn = int(since_turn)
                if validated_since_turn < 0 or validated_since_turn > 10000:  # Reasonable bounds
                    raise ValidationError("Since turn must be between 0 and 10000",
                                        parameter="since_turn", value=since_turn)
            except (ValueError, TypeError):
                raise ValidationError("Since turn must be a valid integer",
                                    parameter="since_turn", value=since_turn)

        return game_id.strip(), validated_player_id, format_str, validated_since_turn

    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError(f"Parameter validation failed: {e}")


class StateFormat(Enum):
    """Supported state extraction formats"""
    FULL = "full"
    DELTA = "delta"
    LLM_OPTIMIZED = "llm_optimized"


class StateExtractor:
    """
    Core state extraction logic
    Handles game state retrieval, optimization, and caching
    """

    def __init__(self, civcom: Optional[CivCom] = None, cache: Optional[StateCache] = None,
                 registry: Optional[CivComRegistry] = None):
        self.civcom = civcom  # Optional fallback civcom instance
        self.cache = cache or StateCache(ttl=5, max_size_kb=4)
        self.executor = _shared_executor
        self.registry = registry or civcom_registry  # Use global registry by default

    def _get_civcom_for_game(self, game_id: str, agent_id: Optional[str] = None) -> Optional[CivCom]:
        """Get CivCom instance for a game from registry or fallback

        Args:
            game_id: Unique game identifier
            agent_id: Agent/player identifier (required for registry lookup after composite key fix)
        """
        # Try registry first - now requires both game_id and agent_id
        if agent_id:
            civcom = self.registry.get_civcom(game_id, agent_id)
            if civcom:
                return civcom

        # Fallback to provided civcom if it exists and has required methods
        if self.civcom and hasattr(self.civcom, 'get_full_state'):
            logger.debug(f"Using fallback civcom for game {game_id}")
            return self.civcom

        return None

    def extract_state(self, game_id: str, player_id: int, format_type: StateFormat,
                     since_turn: Optional[int] = None, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract game state in specified format

        Args:
            game_id: Unique game identifier
            player_id: Player ID for perspective-based state
            format_type: State format (full, delta, llm_optimized)
            since_turn: For delta format, changes since this turn
            agent_id: Agent identifier (required for proper CivCom registry lookup)

        Returns:
            Dictionary containing game state in requested format
        """
        # Get civcom FIRST to determine current turn for cache key
        # This prevents stale state being returned when turns advance faster than cache TTL
        civcom = self._get_civcom_for_game(game_id, agent_id)
        if not civcom:
            raise CivComNotFoundError(game_id)

        # Get current turn from civcom for turn-aware cache key
        current_turn = getattr(civcom, 'game_turn', None)

        # Build cache key with current turn to prevent stale data
        cache_key = self._build_cache_key(game_id, player_id, format_type.value, since_turn, current_turn)

        # Check cache
        cached_state = self.cache.get(cache_key)
        if cached_state is not None:
            logger.debug(f"Cache hit for {cache_key}")
            return cached_state

        # Extract fresh state
        start_time = time.time()

        try:
            if format_type == StateFormat.DELTA and since_turn is not None:
                state = self._extract_delta_state(game_id, player_id, since_turn, civcom)
            elif format_type == StateFormat.LLM_OPTIMIZED:
                # Use civcom.build_llm_optimized_state() directly as it already
                # includes legal_actions from _get_legal_actions_optimized()
                state = civcom.build_llm_optimized_state(player_id)
            else:
                raw_state = civcom.get_full_state(player_id)

                # Log warning if units are empty - don't block waiting for packets
                # The blocking time.sleep() was removed because it freezes Tornado's IOLoop
                # Agent-clash should retry state queries if needed
                if not raw_state.get('units'):
                    state_turn = raw_state.get('turn', 0)
                    logger.warning(
                        f"⚠️ No units for player {player_id} at turn {state_turn} in game {game_id}\n"
                        f"   CivCom may not have processed initial packets yet.\n"
                        f"   Agent should retry state query if needed."
                    )

                if format_type == StateFormat.FULL:
                    state = self._format_full_state(raw_state, player_id)
                else:
                    raise ValidationError(f"Unsupported format: {format_type}", parameter="format", value=format_type.value)

            # Cache the result
            self.cache.set(cache_key, state, player_id)

            extraction_time = (time.time() - start_time) * 1000
            logger.info(f"State extraction completed in {extraction_time:.2f}ms for {cache_key}")

            return state

        except (CivComNotFoundError, ValidationError, StateExtractionError) as e:
            # Re-raise specific exceptions with preserved context
            logger.error(f"State extraction failed for game {game_id}, player {player_id}: {e}")
            error_response = error_handler.handle_state_extraction_error(
                game_id, player_id, str(e)
            )
            logger.error(f"Error response: {error_response}")
            raise
        except Exception as e:
            # Convert unexpected exceptions to StateExtractionError
            logger.error(f"Unexpected error during state extraction: {e}", exc_info=True)
            raise StateExtractionError(
                f"Unexpected error during state extraction: {e}",
                game_id=game_id,
                player_id=player_id,
                cause=e
            )

    def get_state(self, raw_state: Dict[str, Any], format_type: StateFormat,
                  player_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Format a raw game state into the specified format.
        This method is used when you already have the raw state and just need formatting.

        Args:
            raw_state: Raw game state dictionary from civcom.get_full_state()
            format_type: State format (FULL, DELTA, LLM_OPTIMIZED)
            player_id: Optional player ID for perspective-based formatting
                      If not provided, will try to extract from raw_state

        Returns:
            Dictionary containing formatted game state

        Raises:
            ValidationError: If format type is unsupported or state is invalid
        """
        # Extract player_id if not provided
        if player_id is None:
            # Try to get from raw_state
            player_id = raw_state.get('player_id') or raw_state.get('current_player', 0)

        try:
            # Format based on requested type
            if format_type == StateFormat.FULL:
                state = self._format_full_state(raw_state, player_id)
            elif format_type == StateFormat.LLM_OPTIMIZED:
                state = self._format_llm_optimized_state(raw_state, player_id)
            elif format_type == StateFormat.DELTA:
                # For delta format without historical data, return full state
                # The caller should use extract_state() for proper delta functionality
                logger.warning("get_state() called with DELTA format - returning full state instead. Use extract_state() for delta functionality.")
                state = self._format_full_state(raw_state, player_id)
            else:
                raise ValidationError(
                    f"Unsupported format: {format_type}",
                    parameter="format",
                    value=format_type.value if hasattr(format_type, 'value') else str(format_type)
                )

            return state

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Error formatting state: {e}", exc_info=True)
            raise StateExtractionError(
                f"Failed to format state: {e}",
                player_id=player_id,
                cause=e
            )

    def get_legal_actions(self, game_id: str, player_id: int, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get top 20 legal actions for player, sorted by strategic priority

        Args:
            game_id: Unique game identifier
            player_id: Player ID
            agent_id: Agent identifier (required for proper CivCom registry lookup)

        Returns:
            List of up to 20 legal actions sorted by priority, in packet-converter format
        """
        try:
            civcom = self._get_civcom_for_game(game_id, agent_id)
            if not civcom:
                raise CivComNotFoundError(game_id)

            # For now, generate mock actions based on game state
            # In a full implementation, this would extract from the actual game
            state = civcom.get_full_state(player_id)
            all_actions = self._generate_legal_actions_from_state(state, player_id)

            # Normalize actions to packet-converter format (with 'type' field)
            # Filter out None results (invalid actions)
            normalized_actions = [
                normalized for normalized in
                [self._normalize_action_format(action) for action in all_actions]
                if normalized is not None
            ]
            
            # Sort by priority (highest first)
            sorted_actions = sorted(normalized_actions, key=lambda x: x.get('priority', 0), reverse=True)
            return sorted_actions

        except (CivComNotFoundError, StateExtractionError) as e:
            # Re-raise specific exceptions with preserved context
            logger.error(f"Legal actions extraction failed for game {game_id}, player {player_id}: {e}")
            error_response = error_handler.handle_action_extraction_error(
                game_id, player_id, str(e)
            )
            logger.error(f"Error response: {error_response}")
            raise
        except Exception as e:
            # Convert unexpected exceptions to StateExtractionError
            logger.error(f"Unexpected error during legal actions extraction: {e}", exc_info=True)
            raise StateExtractionError(
                f"Unexpected error during legal actions extraction: {e}",
                game_id=game_id,
                player_id=player_id,
                cause=e
            )

    def _normalize_action_format(self, action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert internal action format to packet-converter format.

        Returns:
            Dict with normalized action, or None if action is invalid and should be skipped.
        """
        if not action.get('is_valid', True):
            logger.debug(f"Skipping invalid action: {action.get('reason', 'no reason')}")
            return None

        action_type = action.get('action', '')
        params = action.get('params', {})
        unit_id = action.get('unit_id', 0)
        priority = action.get('priority')

        # Action type mappings with default priorities
        if action_type == 'move':
            target = params.get('target', {})
            return {
                'type': 'unit_move',
                'unit_id': unit_id,
                'dest_x': int(target.get('x', 0)),
                'dest_y': int(target.get('y', 0)),
                'is_valid': True,
                'priority': priority if priority is not None else 5
            }

        if action_type == 'build_city':
            return {'type': 'unit_build_city', 'unit_id': unit_id, 'is_valid': True, 'priority': priority or 5}

        if action_type == 'fortify':
            return {'type': 'unit_fortify', 'unit_id': unit_id, 'is_valid': True, 'priority': priority or 3}

        if action_type in ('skip', 'sentry'):
            return {'type': f'unit_{action_type}', 'unit_id': unit_id, 'is_valid': True, 'priority': priority or 1}

        if action_type in ('change_production', 'city_production'):
            production = params.get('to', params.get('production', ''))
            if not production:
                logger.warning(f"Skipping city_production with no target for city_id={action.get('city_id', 0)}")
                return None
            return {
                'type': 'city_production',
                'city_id': action.get('city_id', 0),
                'target': {'production': production},
                'is_valid': True,
                'priority': priority or 4
            }

        if action_type in ('research_tech', 'tech_research'):
            return {
                'type': 'tech_research',
                'tech': action.get('tech', params.get('to', '')),
                'tech_id': action.get('tech_id'),
                'is_valid': True,
                'priority': priority or 3
            }

        if action_type == 'end_turn':
            return {'type': 'end_turn', 'is_valid': True, 'priority': 10}

        # Unknown types: add 'type' field if missing
        normalized = dict(action)
        if 'type' not in normalized and 'action' in normalized:
            normalized['type'] = normalized.pop('action')
        return normalized

    def get_unit_actions(self, unit_id: int, player_id: int) -> Dict[str, Any]:
        """
        Get available actions for a specific unit.
        
        Args:
            unit_id: The ID of the unit to query
            player_id: The ID of the player making the query
            
        Returns:
            Dictionary with:
            - 'unit_type': str - Type name of the unit
            - 'actions': list - Available actions for this unit
            - 'location': dict - Current x, y coordinates
            
            Or on error:
            - 'error': str - Error message
            - 'error_code': str - Error code (E230, E231, etc.)
        """
        try:
            # Get civcom for current game
            civcom = self._get_civcom_for_player(player_id)
            if not civcom:
                return {
                    'error': 'Not connected to game server',
                    'error_code': 'E500'
                }
            
            # Get full state to find the unit
            state = civcom.get_full_state(player_id)
            units = state.get('units', {})
            
            # Handle both dict and list formats
            if isinstance(units, list):
                units = {str(u.get('id', i)): u for i, u in enumerate(units)}
            
            unit_key = str(unit_id)
            if unit_key not in units:
                return {
                    'error': f'Unit {unit_id} not found',
                    'error_code': 'E230'  # UNIT_NOT_FOUND
                }
            
            unit = units[unit_key]
            
            # Check ownership
            if unit.get('owner') != player_id:
                return {
                    'error': f'Unit {unit_id} is not owned by player {player_id}',
                    'error_code': 'E231'  # UNIT_NOT_OWNED
                }
            
            # Generate available actions based on unit type
            unit_type = unit.get('type_name', unit.get('type', 'Unknown'))
            actions = self._generate_unit_actions(unit, state, player_id)
            
            return {
                'unit_type': unit_type,
                'location': {'x': unit.get('x', 0), 'y': unit.get('y', 0)},
                'actions': actions
            }
            
        except Exception as e:
            logger.error(f"Error getting unit actions for unit {unit_id}: {e}")
            return {
                'error': str(e),
                'error_code': 'E500'
            }
    
    def get_city_actions(self, city_id: int, player_id: int) -> Dict[str, Any]:
        """
        Get available actions for a specific city.
        
        Args:
            city_id: The ID of the city to query
            player_id: The ID of the player making the query
            
        Returns:
            Dictionary with:
            - 'city_name': str - Name of the city
            - 'actions': list - Available actions for this city
            - 'location': dict - Current x, y coordinates
            
            Or on error:
            - 'error': str - Error message
            - 'error_code': str - Error code (E240, E241, etc.)
        """
        try:
            # Get civcom for current game
            civcom = self._get_civcom_for_player(player_id)
            if not civcom:
                return {
                    'error': 'Not connected to game server',
                    'error_code': 'E500'
                }
            
            # Get full state to find the city
            state = civcom.get_full_state(player_id)
            cities = state.get('cities', {})
            
            # Handle both dict and list formats
            if isinstance(cities, list):
                cities = {str(c.get('id', i)): c for i, c in enumerate(cities)}
            
            city_key = str(city_id)
            if city_key not in cities:
                return {
                    'error': f'City {city_id} not found',
                    'error_code': 'E240'  # CITY_NOT_FOUND
                }
            
            city = cities[city_key]
            
            # Check ownership
            if city.get('owner') != player_id:
                return {
                    'error': f'City {city_id} is not owned by player {player_id}',
                    'error_code': 'E241'  # CITY_NOT_OWNED
                }
            
            # Generate available actions based on city state
            city_name = city.get('name', 'Unknown')
            actions = self._generate_city_actions(city, state, player_id)
            
            return {
                'city_name': city_name,
                'location': {'x': city.get('x', 0), 'y': city.get('y', 0)},
                'actions': actions
            }
            
        except Exception as e:
            logger.error(f"Error getting city actions for city {city_id}: {e}")
            return {
                'error': str(e),
                'error_code': 'E500'
            }
    
    def _get_civcom_for_player(self, player_id: int) -> Optional[CivCom]:
        """Get CivCom instance for a player from the registry"""
        # Try to find civcom in registry
        for key, civcom in civcom_registry._civcom_instances.items():
            if civcom and hasattr(civcom, 'player_id'):
                if civcom.player_id == player_id:
                    return civcom
        # Fallback: use self.civcom if available
        if hasattr(self, 'civcom') and self.civcom:
            return self.civcom
        return None
    
    def _generate_unit_actions(self, unit: Dict[str, Any], state: Dict[str, Any], player_id: int) -> List[Dict[str, Any]]:
        """Generate all legal actions for a unit based on ruleset data and game state.
        
        This method uses server-provided ruleset data to determine which actions
        a unit can perform, avoiding hardcoded values whenever possible.
        
        Args:
            unit: Unit data dict from game state
            state: Full game state dict
            player_id: The player ID making the query
            
        Returns:
            List of action dicts with action type, params, and validity info
        """
        from civcom import (
            ACTION_FOUND_CITY, ACTION_JOIN_CITY, ACTION_ATTACK, ACTION_FORTIFY,
            ACTION_ROAD, ACTION_IRRIGATE, ACTION_MINE, ACTION_BASE, ACTION_PILLAGE,
            ACTION_CLEAN, ACTION_TRANSFORM_TERRAIN, ACTION_CULTIVATE, ACTION_PLANT,
            ACTION_TRADE_ROUTE, ACTION_MARKETPLACE, ACTION_HELP_WONDER,
            ACTION_ESTABLISH_EMBASSY, ACTION_SPY_INVESTIGATE_CITY, ACTION_SPY_POISON,
            ACTION_SPY_SABOTAGE_CITY, ACTION_SPY_STEAL_TECH, ACTION_SPY_INCITE_CITY,
            ACTION_SPY_BRIBE_UNIT, ACTION_SPY_SABOTAGE_UNIT, ACTION_SPY_ATTACK,
            ACTION_DISBAND_UNIT, ACTION_HOME_CITY, ACTION_UPGRADE_UNIT,
            ACTION_CONVERT, ACTION_AIRLIFT, ACTION_PARADROP,
            ACTION_TRANSPORT_BOARD, ACTION_TRANSPORT_DEBOARD,
            ACTION_TRANSPORT_EMBARK, ACTION_TRANSPORT_DISEMBARK1,
            ACTION_TRANSPORT_LOAD, ACTION_TRANSPORT_UNLOAD,
            ACTION_HEAL_UNIT, ACTION_BOMBARD, ACTION_CAPTURE_UNITS,
            ACTION_NUKE, ACTION_NUKE_CITY, ACTION_NUKE_UNITS,
            ACTION_SUICIDE_ATTACK, ACTION_CONQUER_CITY,
            ACTION_ID_TO_TYPE, TC_LAND, TC_OCEAN
        )
        
        actions = []
        
        # Get unit properties
        unit_id = unit.get('id')
        unit_type_id = unit.get('type_id')
        unit_type_name = unit.get('type', unit.get('type_name', '')).lower()
        moves_left = unit.get('moves_left', unit.get('moves', 0))
        activity = unit.get('activity', 'idle')
        tile_index = unit.get('tile')
        # Variables x, y are captured by get_target_tile() closure below (line ~829)
        x = unit.get('x', 0)
        y = unit.get('y', 0)
        is_transported = unit.get('transported', False)
        
        # Get civcom for ruleset data
        civcom = self._get_civcom_for_player(player_id)
        
        # Check if unit is currently working on an activity
        # These activities should not be interrupted
        working_activities = {'road', 'railroad', 'mine', 'irrigate', 'transform', 
                              'fortress', 'airbase', 'pollution', 'fallout', 'base'}
        is_working = activity in working_activities
        
        # Direction mappings for movement
        directions = ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw']
        direction_offsets = {
            'n': (0, -1), 'ne': (1, -1), 'e': (1, 0), 'se': (1, 1),
            's': (0, 1), 'sw': (-1, 1), 'w': (-1, 0), 'nw': (-1, -1)
        }
        
        # Helper to add action with proper formatting
        def add_action(action_type: str, params: dict = None, is_valid: bool = True, 
                      reason: str = None, action_id: int = None):
            action = {
                'action': action_type,
                'params': params or {},
                'is_valid': is_valid,
                'unit_id': unit_id  # Include unit_id so action normalization can use it
            }
            if reason:
                action['reason'] = reason
            if action_id is not None:
                action['action_id'] = action_id
            actions.append(action)
        
        # Helper to check if unit type can do action using ruleset
        def can_do_action(action_id: int) -> bool:
            if civcom and unit_type_id is not None:
                return civcom.utype_can_do_action(unit_type_id, action_id)
            # Fallback to name-based heuristics if no ruleset data
            return self._fallback_can_do_action(unit_type_name, action_id)
        
        # Helper to get target tile info
        def get_target_tile(direction: str) -> tuple:
            dx, dy = direction_offsets.get(direction, (0, 0))
            target_x = x + dx
            target_y = y + dy
            
            # Handle map wrapping
            if civcom:
                xsize = civcom.map_info.get('width', 80)
                ysize = civcom.map_info.get('height', 50)
                if civcom.map_info.get('wrap_x', True):
                    target_x = target_x % xsize
                if civcom.map_info.get('wrap_y', False):
                    target_y = target_y % ysize
                target_index = target_x + target_y * xsize
                return (target_x, target_y, target_index)
            return (target_x, target_y, None)
        
        # If unit is working on an improvement, add a "continue_work" action
        # This signals to the AI that it should NOT interrupt this unit
        if is_working:
            add_action('continue_work', {'current_activity': activity}, True, 
                      f"Unit is building {activity}")
        
        # === MOVEMENT ACTIONS ===
        if moves_left > 0:
            # Pre-compute city tile indexes for efficient lookup
            city_tiles = set()
            if civcom:
                for city_id, city in civcom.player_cities.items():
                    city_tile = city.get('tile')
                    if city_tile is not None:
                        city_tiles.add(city_tile)
                # Also check enemy cities
                for city in getattr(civcom, 'other_cities', {}).values():
                    city_tile = city.get('tile')
                    if city_tile is not None:
                        city_tiles.add(city_tile)
            
            for direction in directions:
                target_x, target_y, target_index = get_target_tile(direction)
                
                is_valid = True
                reason = None
                
                # Check terrain accessibility if we have civcom data
                if civcom and target_index is not None:
                    tile = civcom.tiles.get(target_index)
                    if tile:
                        terrain_id = tile.get('terrain')
                        terrain_class = civcom.get_terrain_class(terrain_id) if terrain_id is not None else TC_LAND
                        
                        # Get unit class info for terrain checking
                        unit_type_data = civcom.unit_types.get(unit_type_id, {})
                        unit_class_id = unit_type_data.get('unit_class')
                        
                        # Check if target tile has a city (cities allow entry for most unit types)
                        tile_has_city = target_index in city_tiles
                        
                        # Use proper native_to checking if available, fall back to class name check
                        if unit_class_id is not None and terrain_id is not None:
                            is_native = civcom.is_unit_class_native_to_terrain(unit_class_id, terrain_id)
                            if not is_native and not tile_has_city:
                                # Not native terrain and no city - check if can embark on transport
                                if terrain_class == TC_OCEAN:
                                    if not can_do_action(ACTION_TRANSPORT_EMBARK):
                                        is_valid = False
                                        reason = "Cannot enter ocean (non-naval unit, no transport available)"
                                else:
                                    is_valid = False
                                    reason = "Cannot enter non-native terrain"
                        else:
                            # Fallback: simple land/sea check by class name
                            unit_class = civcom.unit_classes.get(unit_class_id, {}) if unit_class_id else {}
                            class_name = unit_class.get('name', '').lower()
                            
                            if terrain_class == TC_OCEAN and not tile_has_city:
                                # Check if unit class can enter ocean
                                # Sea, Trireme, Air, Helicopter can enter ocean
                                if class_name not in ('sea', 'trireme', 'air', 'helicopter', 'missile'):
                                    if not can_do_action(ACTION_TRANSPORT_EMBARK):
                                        is_valid = False
                                        reason = "Cannot enter ocean (land unit, no transport)"
                            elif terrain_class == TC_LAND and not tile_has_city:
                                # Sea and Trireme classes cannot enter land (except through cities)
                                if class_name in ('sea', 'trireme'):
                                    is_valid = False
                                    reason = "Cannot enter land (naval unit)"
                
                add_action('move', {'direction': direction, 'target': {'x': target_x, 'y': target_y}}, 
                          is_valid, reason)
        
        # === CITY FOUNDING ACTIONS ===
        if can_do_action(ACTION_FOUND_CITY):
            is_valid = True
            reason = None

            # Check if unit has moves remaining this turn (required to perform any action)
            if moves_left <= 0:
                is_valid = False
                reason = "No moves left"

            # Check citymindist constraint
            if is_valid and civcom and tile_index is not None:
                can_found, found_reason = civcom.can_city_be_founded_at(tile_index)
                if not can_found:
                    is_valid = False
                    reason = found_reason

            # Check if on ocean
            if is_valid and civcom and tile_index is not None:
                tile = civcom.tiles.get(tile_index)
                if tile:
                    terrain_id = tile.get('terrain')
                    if terrain_id is not None and civcom.get_terrain_class(terrain_id) == TC_OCEAN:
                        is_valid = False
                        reason = "Cannot found city on ocean"

            # Check if already has a city here
            if is_valid and civcom:
                for city_id, city in civcom.player_cities.items():
                    if city.get('tile') == tile_index:
                        is_valid = False
                        reason = "Tile already has a city"
                        break

            add_action('build_city', {}, is_valid, reason, ACTION_FOUND_CITY)
        
        # === JOIN CITY ACTION ===
        if can_do_action(ACTION_JOIN_CITY):
            # Check if unit is in a city
            in_city = False
            city_name = None
            if civcom:
                for city_id, city in civcom.player_cities.items():
                    if city.get('tile') == tile_index:
                        in_city = True
                        city_name = city.get('name')
                        break
            
            add_action('join_city', {'city': city_name} if city_name else {}, 
                      in_city, None if in_city else "Not in a city", ACTION_JOIN_CITY)
        
        # === FORTIFY ACTION ===
        if can_do_action(ACTION_FORTIFY):
            is_valid = activity not in ('fortified', 'fortifying')
            add_action('fortify', {}, is_valid, 
                      "Already fortified" if not is_valid else None, ACTION_FORTIFY)
        
        # === TERRAIN IMPROVEMENT ACTIONS ===
        # Require moves_left > 0 - terrain improvements consume movement points
        terrain_actions = [
            (ACTION_ROAD, 'build_road', 'road'),
            (ACTION_IRRIGATE, 'build_irrigation', 'irrigation'),
            (ACTION_MINE, 'build_mine', 'mine'),
            (ACTION_BASE, 'build_base', 'base'),
            (ACTION_TRANSFORM_TERRAIN, 'transform', None),
            (ACTION_CULTIVATE, 'cultivate', None),
            (ACTION_PLANT, 'plant', None),
        ]

        for action_id, action_name, improvement in terrain_actions:
            if can_do_action(action_id):
                is_valid = True
                reason = None

                # Check if unit has moves remaining
                if moves_left <= 0:
                    is_valid = False
                    reason = "No moves left"

                # Basic validation: don't allow if already working on something
                elif is_working:
                    is_valid = False
                    reason = f"Already working on {activity}"

                # Check if on ocean (can't build most improvements on ocean)
                elif civcom and tile_index is not None:
                    tile = civcom.tiles.get(tile_index)
                    if tile:
                        terrain_id = tile.get('terrain')
                        if terrain_id is not None:
                            terrain_class = civcom.get_terrain_class(terrain_id)
                            if terrain_class == TC_OCEAN and action_id not in (ACTION_BASE,):
                                is_valid = False
                                reason = "Cannot build on ocean"

                params = {'improvement': improvement} if improvement else {}
                add_action(action_name, params, is_valid, reason, action_id)
        
        # === PILLAGE ACTION ===
        # Require moves_left > 0 - pillaging consumes movement points
        if can_do_action(ACTION_PILLAGE):
            is_valid = moves_left > 0
            reason = "No moves left" if not is_valid else None
            add_action('pillage', {}, is_valid, reason, ACTION_PILLAGE)

        # === CLEAN ACTION ===
        # Require moves_left > 0 - cleaning consumes movement points
        if can_do_action(ACTION_CLEAN):
            is_valid = moves_left > 0
            reason = "No moves left" if not is_valid else None
            add_action('clean', {}, is_valid, reason, ACTION_CLEAN)
        
        # === COMBAT ACTIONS ===
        # Attack actions for adjacent tiles
        # Require moves_left > 0 - combat actions consume movement points
        basic_combat_actions = [
            (ACTION_ATTACK, 'attack'),
            (ACTION_SUICIDE_ATTACK, 'suicide_attack'),
            (ACTION_CAPTURE_UNITS, 'capture'),
            (ACTION_CONQUER_CITY, 'conquer_city'),
        ]

        for action_id, action_name in basic_combat_actions:
            if can_do_action(action_id):
                # Check if unit has moves remaining
                is_valid = moves_left > 0
                reason = "No moves left" if not is_valid else None
                # Add attack actions for each direction
                for direction in directions:
                    target_x, target_y, _ = get_target_tile(direction)
                    add_action(action_name, {
                        'direction': direction,
                        'target': {'x': target_x, 'y': target_y}
                    }, is_valid, reason, action_id)

        # Bombard is ranged - check for visible targets
        # Require moves_left > 0 - bombard consumes movement points
        if can_do_action(ACTION_BOMBARD):
            is_valid = moves_left > 0
            reason = "No moves left" if not is_valid else None
            # Simplified: add bombard for adjacent tiles (full implementation would check range)
            # In full version: get unit type's bombard range and check for enemy units/cities in range
            for direction in directions:
                target_x, target_y, _ = get_target_tile(direction)
                add_action('bombard', {
                    'direction': direction,
                    'target': {'x': target_x, 'y': target_y}
                }, is_valid, reason, ACTION_BOMBARD)
        
        # === NUCLEAR ACTIONS ===
        # Nuclear weapons require targets and sufficient moves
        if can_do_action(ACTION_NUKE):
            # Require target selection and not being transported
            is_valid = not is_transported and moves_left > 0
            reason = None
            if is_transported:
                reason = "Cannot launch nuke while transported"
            elif moves_left <= 0:
                reason = "No moves left"
            add_action('nuke', {}, is_valid, reason, ACTION_NUKE)
        
        if can_do_action(ACTION_NUKE_CITY):
            is_valid = not is_transported and moves_left > 0
            reason = None
            if is_transported:
                reason = "Cannot launch nuke while transported"
            elif moves_left <= 0:
                reason = "No moves left"
            add_action('nuke_city', {}, is_valid, reason, ACTION_NUKE_CITY)
        
        if can_do_action(ACTION_NUKE_UNITS):
            is_valid = not is_transported and moves_left > 0
            reason = None
            if is_transported:
                reason = "Cannot launch nuke while transported"
            elif moves_left <= 0:
                reason = "No moves left"
            add_action('nuke_units', {}, is_valid, reason, ACTION_NUKE_UNITS)
        
        # === TRADE ACTIONS ===
        # Trade units (caravans/freight) must be in a city to establish trade or help
        if can_do_action(ACTION_TRADE_ROUTE):
            # Must be in a city to establish trade route
            in_city = False
            unit_city_id = None
            if civcom:
                for city_id, city in civcom.player_cities.items():
                    if city.get('tile') == tile_index:
                        in_city = True
                        unit_city_id = city_id
                        break
            
            if in_city and unit_city_id:
                # Generate trade route actions to other cities
                cities = state.get('cities', {})
                for dest_city_id, dest_city in cities.items():
                    if str(dest_city.get('id')) != str(unit_city_id):
                        # Can establish trade with different cities
                        add_action('trade_route', 
                                 {'target_city_id': dest_city.get('id')},
                                 True, None, ACTION_TRADE_ROUTE)
            else:
                add_action('trade_route', {}, False, 
                         "Must be in a city to establish trade route", ACTION_TRADE_ROUTE)
        
        if can_do_action(ACTION_MARKETPLACE):
            # Must be in a city to sell goods at marketplace
            in_city = civcom and any(city.get('tile') == tile_index 
                                    for city in civcom.player_cities.values())
            add_action('marketplace', {}, in_city, 
                     None if in_city else "Must be in a city", ACTION_MARKETPLACE)
        
        if can_do_action(ACTION_HELP_WONDER):
            # Must be in a city that's building a wonder
            in_city = False
            building_wonder = False
            if civcom:
                for city_id, city in civcom.player_cities.items():
                    if city.get('tile') == tile_index:
                        in_city = True
                        # Check if city is building a wonder (production_kind=1, value>=certain threshold)
                        prod_kind = city.get('production_kind')
                        if prod_kind == 1:  # Building improvement
                            building_wonder = True  # Simplified check
                        break
            
            is_valid = in_city and building_wonder
            reason = None if is_valid else ("Not in a city" if not in_city else "City not building a wonder")
            add_action('help_wonder', {}, is_valid, reason, ACTION_HELP_WONDER)
        
        # === ESPIONAGE ACTIONS ===
        # Spy/diplomat actions require targets (cities or units)
        city_spy_actions = [
            (ACTION_ESTABLISH_EMBASSY, 'establish_embassy'),
            (ACTION_SPY_INVESTIGATE_CITY, 'investigate_city'),
            (ACTION_SPY_POISON, 'poison'),
            (ACTION_SPY_SABOTAGE_CITY, 'sabotage_city'),
            (ACTION_SPY_STEAL_TECH, 'steal_tech'),
            (ACTION_SPY_INCITE_CITY, 'incite_city'),
        ]
        
        # Check for adjacent foreign cities for city-based espionage
        adjacent_foreign_cities = []
        if civcom and tile_index is not None:
            xsize = civcom.map_info.get('width', 80)
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1), (0, 0)]:
                adj_x, adj_y = x + dx, y + dy
                if civcom.map_info.get('wrap_x', True):
                    adj_x = adj_x % xsize
                adj_tile = adj_x + adj_y * xsize
                
                # Check for foreign cities at this tile
                for city in getattr(civcom, 'other_cities', {}).values():
                    if city.get('tile') == adj_tile and city.get('owner') != player_id:
                        adjacent_foreign_cities.append(city)
        
        for action_id, action_name in city_spy_actions:
            if can_do_action(action_id):
                if adjacent_foreign_cities:
                    for city in adjacent_foreign_cities:
                        add_action(action_name, 
                                 {'target_city_id': city.get('id')},
                                 True, None, action_id)
                else:
                    add_action(action_name, {}, False, 
                             "No foreign city nearby", action_id)
        
        # Unit-based espionage actions
        if can_do_action(ACTION_SPY_BRIBE_UNIT) or can_do_action(ACTION_SPY_SABOTAGE_UNIT):
            # Check for adjacent foreign units
            has_adjacent_enemy = False
            if civcom and tile_index is not None:
                xsize = civcom.map_info.get('width', 80)
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                    adj_x, adj_y = x + dx, y + dy
                    if civcom.map_info.get('wrap_x', True):
                        adj_x = adj_x % xsize
                    adj_tile = adj_x + adj_y * xsize
                    
                    # Check for enemy units
                    for other_unit in getattr(civcom, 'other_units', {}).values():
                        if other_unit.get('tile') == adj_tile and other_unit.get('owner') != player_id:
                            has_adjacent_enemy = True
                            break
                    if has_adjacent_enemy:
                        break
            
            if can_do_action(ACTION_SPY_BRIBE_UNIT):
                add_action('bribe_unit', {}, has_adjacent_enemy,
                         None if has_adjacent_enemy else "No enemy unit nearby", 
                         ACTION_SPY_BRIBE_UNIT)
            
            if can_do_action(ACTION_SPY_SABOTAGE_UNIT):
                add_action('sabotage_unit', {}, has_adjacent_enemy,
                         None if has_adjacent_enemy else "No enemy unit nearby",
                         ACTION_SPY_SABOTAGE_UNIT)
        
        if can_do_action(ACTION_SPY_ATTACK):
            add_action('spy_attack', {}, True, None, ACTION_SPY_ATTACK)
        
        # === TRANSPORT ACTIONS ===
        # Only offer disembark/deboard if unit is actually on a transport
        # Only offer embark/board if unit is NOT on a transport
        if is_transported:
            # Unit is on a transport - can disembark to adjacent land
            disembark_actions = [
                (ACTION_TRANSPORT_DEBOARD, 'deboard'),
                (ACTION_TRANSPORT_DISEMBARK1, 'disembark'),
                (ACTION_TRANSPORT_UNLOAD, 'unload'),
            ]
            
            # Check for adjacent land tiles for disembark
            has_adjacent_land = False
            if civcom and tile_index is not None:
                xsize = civcom.map_info.get('width', 80)
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    adj_x, adj_y = x + dx, y + dy
                    if civcom.map_info.get('wrap_x', True):
                        adj_x = adj_x % xsize
                    adj_tile = adj_x + adj_y * xsize
                    tile = civcom.tiles.get(adj_tile)
                    if tile:
                        terrain_id = tile.get('terrain')
                        if terrain_id is not None and civcom.get_terrain_class(terrain_id) == TC_LAND:
                            has_adjacent_land = True
                            break
            
            for action_id, action_name in disembark_actions:
                if can_do_action(action_id):
                    # Simplified: assume can disembark if adjacent land exists
                    add_action(action_name, {}, has_adjacent_land,
                             None if has_adjacent_land else "No adjacent land",
                             action_id)
        else:
            # Unit is NOT on a transport - can embark
            # NOTE: transport_id captured here may become stale if the transport moves,
            # is destroyed, or fills its cargo capacity before action execution.
            # The civserver will reject stale transport_ids with an appropriate error.
            # First, find available transports on the same tile
            available_transport_id = None
            if civcom and tile_index is not None:
                for other_unit_id, other_unit in civcom.player_units.items():
                    if other_unit_id == unit_id:
                        continue  # Skip self
                    if other_unit.get('tile') != tile_index:
                        continue  # Must be on same tile
                    # Check if this unit has transport capacity
                    other_type_id = other_unit.get('type_id')
                    if other_type_id is not None:
                        other_type = civcom.unit_types.get(other_type_id, {})
                        if other_type.get('transport_capacity', 0) > 0:
                            available_transport_id = other_unit_id
                            break  # Found a transport

            embark_actions = [
                (ACTION_TRANSPORT_BOARD, 'board'),
                (ACTION_TRANSPORT_EMBARK, 'embark'),
                (ACTION_TRANSPORT_LOAD, 'load'),
            ]
            for action_id, action_name in embark_actions:
                if can_do_action(action_id):
                    if available_transport_id is not None:
                        add_action(action_name, {'transport_id': available_transport_id},
                                  True, None, action_id)
                    else:
                        add_action(action_name, {}, False,
                                  "No transport available on this tile", action_id)
        
        # === UNIT MANAGEMENT ACTIONS ===
        if can_do_action(ACTION_DISBAND_UNIT):
            add_action('disband', {}, True, None, ACTION_DISBAND_UNIT)
        
        if can_do_action(ACTION_HOME_CITY):
            # Must be in a friendly city
            in_city = False
            city_name = None
            if civcom:
                for city_id, city in civcom.player_cities.items():
                    if city.get('tile') == tile_index:
                        in_city = True
                        city_name = city.get('name')
                        break
            
            add_action('home_city', {'city': city_name} if city_name else {}, 
                      in_city, None if in_city else "Must be in a friendly city", 
                      ACTION_HOME_CITY)
        
        if can_do_action(ACTION_UPGRADE_UNIT):
            # Must be in a friendly city
            in_city = False
            if civcom:
                for city_id, city in civcom.player_cities.items():
                    if city.get('tile') == tile_index:
                        in_city = True
                        break
            
            add_action('upgrade', {}, in_city,
                      None if in_city else "Must be in a friendly city to upgrade",
                      ACTION_UPGRADE_UNIT)
        
        if can_do_action(ACTION_CONVERT):
            add_action('convert', {}, True, None, ACTION_CONVERT)
        
        if can_do_action(ACTION_HEAL_UNIT):
            add_action('heal', {}, True, None, ACTION_HEAL_UNIT)
        
        # === SPECIAL MOVEMENT ACTIONS ===
        # Airlift - requires unit to be in a city with Airport improvement
        if can_do_action(ACTION_AIRLIFT):
            # Check if unit is in a city
            cities = state.get('cities', {})
            unit_city = None
            for city_id, city in cities.items():
                if city.get('x') == x and city.get('y') == y:
                    unit_city = city
                    break
            
            # Only generate airlift action if in a city with Airport
            if unit_city and civcom:
                has_airport = civcom.city_has_improvement(unit_city, 'Airport')
                if has_airport:
                    # Generate airlift actions to all other cities with airports
                    for dest_city_id, dest_city in cities.items():
                        if dest_city_id != str(unit_city.get('id')):
                            dest_has_airport = civcom.city_has_improvement(dest_city, 'Airport')
                            if dest_has_airport and dest_city.get('owner') == player_id:
                                add_action('airlift', 
                                         {'target_city_id': dest_city.get('id')}, 
                                         True, None, ACTION_AIRLIFT)
                else:
                    add_action('airlift', {}, False, 
                             "Source city needs Airport improvement", ACTION_AIRLIFT)
            else:
                add_action('airlift', {}, False, 
                         "Unit must be in a city to airlift", ACTION_AIRLIFT)
        
        if can_do_action(ACTION_PARADROP):
            # Check if unit is in a city with Airport or on a tile with Airbase
            can_launch = False
            if civcom and tile_index is not None:
                # Check if in city with Airport
                for city_id, city in civcom.player_cities.items():
                    if city.get('tile') == tile_index:
                        if civcom.city_has_improvement(city, 'Airport'):
                            can_launch = True
                        break
                
                # Could also check for Airbase extra on tile
                # (would need to check tile extras/improvements)
            
            if can_launch and not is_transported:
                # Generate paradrop actions to valid tiles within range
                # Simplified: just mark as valid if can launch
                add_action('paradrop', {}, True, None, ACTION_PARADROP)
            else:
                reason = "Transported units cannot paradrop" if is_transported else "Need Airport or Airbase to paradrop"
                add_action('paradrop', {}, False, reason, ACTION_PARADROP)
        
        # === SKIP/SENTRY ACTIONS (always available) ===
        add_action('skip', {}, True)
        add_action('sentry', {}, activity != 'sentry', 
                  "Already on sentry" if activity == 'sentry' else None)
        
        return actions
    
    def _fallback_can_do_action(self, unit_type_name: str, action_id: int) -> bool:
        """Fallback action detection using unit type name heuristics.
        
        Used when ruleset data is not available. This is less accurate than
        using the actual utype_actions bitfield from the server.
        
        Args:
            unit_type_name: Lowercase unit type name
            action_id: FreeCiv action ID
            
        Returns:
            True if the unit type likely can perform the action
        """
        from civcom import (
            ACTION_FOUND_CITY, ACTION_JOIN_CITY, ACTION_ATTACK, ACTION_FORTIFY,
            ACTION_ROAD, ACTION_IRRIGATE, ACTION_MINE, ACTION_BASE, ACTION_PILLAGE,
            ACTION_TRANSFORM_TERRAIN, ACTION_CULTIVATE, ACTION_PLANT,
            ACTION_TRADE_ROUTE, ACTION_MARKETPLACE, ACTION_HELP_WONDER,
            ACTION_ESTABLISH_EMBASSY, ACTION_SPY_INVESTIGATE_CITY, ACTION_SPY_POISON,
            ACTION_SPY_SABOTAGE_CITY, ACTION_SPY_STEAL_TECH, ACTION_SPY_INCITE_CITY,
            ACTION_SPY_BRIBE_UNIT, ACTION_SPY_SABOTAGE_UNIT,
            ACTION_PARADROP, ACTION_NUKE,
        )
        
        # Settler actions
        settler_types = ('settler', 'settlers', 'colonist')
        if action_id in (ACTION_FOUND_CITY, ACTION_JOIN_CITY):
            return any(s in unit_type_name for s in settler_types)
        
        # Worker/Engineer actions
        worker_types = ('worker', 'workers', 'engineer', 'engineers', 'settler', 'settlers')
        if action_id in (ACTION_ROAD, ACTION_IRRIGATE, ACTION_MINE, ACTION_BASE,
                        ACTION_CULTIVATE, ACTION_PLANT, ACTION_TRANSFORM_TERRAIN):
            return any(w in unit_type_name for w in worker_types)
        
        # Caravan/Freight actions
        trade_types = ('caravan', 'freight')
        if action_id in (ACTION_TRADE_ROUTE, ACTION_MARKETPLACE, ACTION_HELP_WONDER):
            return any(t in unit_type_name for t in trade_types)
        
        # Diplomat/Spy actions
        spy_types = ('diplomat', 'spy')
        if action_id in (ACTION_ESTABLISH_EMBASSY, ACTION_SPY_INVESTIGATE_CITY,
                        ACTION_SPY_POISON, ACTION_SPY_SABOTAGE_CITY,
                        ACTION_SPY_STEAL_TECH, ACTION_SPY_INCITE_CITY,
                        ACTION_SPY_BRIBE_UNIT, ACTION_SPY_SABOTAGE_UNIT):
            return any(s in unit_type_name for s in spy_types)
        
        # Paradrop action
        if action_id == ACTION_PARADROP:
            return 'paratrooper' in unit_type_name or 'paratroop' in unit_type_name
        
        # Nuclear action
        if action_id == ACTION_NUKE:
            return 'nuclear' in unit_type_name or 'nuke' in unit_type_name
        
        # Fortify - most land units can fortify
        if action_id == ACTION_FORTIFY:
            naval_types = ('trireme', 'caravel', 'galleon', 'frigate', 'ironclad',
                          'destroyer', 'cruiser', 'battleship', 'submarine', 'carrier', 'transport')
            return not any(n in unit_type_name for n in naval_types)
        
        # Pillage - most military units can pillage
        if action_id == ACTION_PILLAGE:
            civilian_types = ('settler', 'worker', 'engineer', 'caravan', 'freight', 'diplomat', 'spy', 'explorer')
            return not any(c in unit_type_name for c in civilian_types)
        
        # Attack - units with combat capability
        if action_id == ACTION_ATTACK:
            civilian_types = ('settler', 'worker', 'engineer', 'caravan', 'freight', 'explorer')
            return not any(c in unit_type_name for c in civilian_types)
        
        return False
    
    def _generate_city_actions(self, city: Dict[str, Any], state: Dict[str, Any], player_id: int) -> List[Dict[str, Any]]:
        """Generate available actions for a city based on its state"""
        actions = []
        city_id = city.get('id')
        
        # Production change
        productions = city.get('can_build', [])
        if not productions:
            # Default buildable units/buildings
            productions = ['Warrior', 'Settler', 'Worker', 'Barracks', 'Granary']
        
        for prod in productions:
            actions.append({
                'action': 'change_production',
                'params': {'to': prod},
                'is_valid': True,
                'city_id': city_id
            })
        
        # Buy current production
        buy_cost = city.get('buy_cost', 0)
        treasury = state.get('player', {}).get('gold', 0)
        actions.append({
            'action': 'buy',
            'params': {},
            'is_valid': treasury >= buy_cost if buy_cost > 0 else False,
            'city_id': city_id
        })
        
        # Sell improvements
        improvements = city.get('improvements', [])
        for imp in improvements:
            imp_name = imp if isinstance(imp, str) else imp.get('name', 'Unknown')
            actions.append({
                'action': 'sell_improvement',
                'params': {'improvement': imp_name},
                'is_valid': True,
                'city_id': city_id
            })
        
        # Specialist management
        for specialist in ['scientist', 'taxman', 'entertainer']:
            actions.append({
                'action': 'add_specialist',
                'params': {'type': specialist},
                'is_valid': True,
                'city_id': city_id
            })
        
        return actions

    def _extract_delta_state(self, game_id: str, player_id: int, since_turn: int, civcom: CivCom) -> Dict[str, Any]:
        """Extract changes since specified turn"""
        current_state = civcom.get_full_state(player_id)
        # For MVP, simulate previous state (in full implementation, store historical states)
        previous_state = self._simulate_previous_state(current_state, since_turn)

        return {
            'since_turn': since_turn,
            'current_turn': current_state.get('turn'),
            'changes': self._calculate_state_delta(previous_state, current_state),
            'timestamp': time.time()
        }

    def _calculate_state_delta(self, previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate differences between two game states
        Optimized for performance with O(1) lookups and set operations
        """
        changes = {}

        # Track unit changes - O(n) complexity
        # Units are now dicts keyed by ID, not lists
        prev_units_data = previous.get('units', {})
        prev_units = prev_units_data if isinstance(prev_units_data, dict) else {u['id']: u for u in prev_units_data}
        curr_units_data = current.get('units', {})
        curr_units = curr_units_data if isinstance(curr_units_data, dict) else {u['id']: u for u in curr_units_data}

        # Use sets for efficient difference operations
        prev_unit_ids = set(prev_units.keys())
        curr_unit_ids = set(curr_units.keys())

        unit_changes = []

        # Modified/existing units - O(n) where n = current units
        for unit_id in (prev_unit_ids & curr_unit_ids):  # Intersection
            unit = curr_units[unit_id]
            prev_unit = prev_units[unit_id]

            # Check only relevant fields for changes
            position_changed = unit['x'] != prev_unit['x'] or unit['y'] != prev_unit['y']
            hp_changed = unit['hp'] != prev_unit['hp']
            moves_changed = unit.get('moves', 0) != prev_unit.get('moves', 0)

            if position_changed or hp_changed or moves_changed:
                change_data = {'id': unit_id, 'changes': {}}

                if position_changed:
                    change_data['changes']['position'] = {
                        'from': (prev_unit['x'], prev_unit['y']),
                        'to': (unit['x'], unit['y'])
                    }
                if hp_changed:
                    change_data['changes']['hp'] = {'from': prev_unit['hp'], 'to': unit['hp']}
                if moves_changed:
                    change_data['changes']['moves'] = {
                        'from': prev_unit.get('moves', 0), 'to': unit.get('moves', 0)
                    }

                unit_changes.append(change_data)

        # New units - O(k) where k = new units
        for unit_id in (curr_unit_ids - prev_unit_ids):  # Difference
            unit_changes.append({'id': unit_id, 'type': 'created', 'data': curr_units[unit_id]})

        # Destroyed units - O(j) where j = destroyed units
        for unit_id in (prev_unit_ids - curr_unit_ids):  # Difference
            unit_changes.append({'id': unit_id, 'type': 'destroyed'})

        if unit_changes:
            changes['units'] = unit_changes

        # Track city changes - same optimization pattern
        # Cities are now dicts keyed by ID, not lists
        prev_cities_data = previous.get('cities', {})
        prev_cities = prev_cities_data if isinstance(prev_cities_data, dict) else {c['id']: c for c in prev_cities_data}
        curr_cities_data = current.get('cities', {})
        curr_cities = curr_cities_data if isinstance(curr_cities_data, dict) else {c['id']: c for c in curr_cities_data}

        prev_city_ids = set(prev_cities.keys())
        curr_city_ids = set(curr_cities.keys())

        city_changes = []

        # Modified/existing cities
        for city_id in (prev_city_ids & curr_city_ids):
            city = curr_cities[city_id]
            prev_city = prev_cities[city_id]

            pop_changed = city['population'] != prev_city['population']
            prod_changed = city.get('production') != prev_city.get('production')

            if pop_changed or prod_changed:
                change_data = {'id': city_id, 'changes': {}}

                if pop_changed:
                    change_data['changes']['population'] = {
                        'from': prev_city['population'], 'to': city['population']
                    }
                if prod_changed:
                    change_data['changes']['production'] = {
                        'from': prev_city.get('production'), 'to': city.get('production')
                    }

                city_changes.append(change_data)

        # New cities
        for city_id in (curr_city_ids - prev_city_ids):
            city_changes.append({'id': city_id, 'type': 'founded', 'data': curr_cities[city_id]})

        if city_changes:
            changes['cities'] = city_changes

        return changes

    def _ensure_valid_map(self, map_data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure map has valid dimensions (width, height >= 1)."""
        if not map_data:
            return {'width': 80, 'height': 50, 'tiles': [], 'visibility': {}}

        # Ensure width and height are at least 1
        if map_data.get('width', 0) < 1:
            map_data['width'] = 80
        if map_data.get('height', 0) < 1:
            map_data['height'] = 50

        # Ensure required fields exist
        if 'tiles' not in map_data:
            map_data['tiles'] = []
        if 'visibility' not in map_data:
            map_data['visibility'] = {}

        return map_data

    def _ensure_dict(self, data: Any, key_field: str = 'id') -> Dict[str, Any]:
        """Convert collections to dict format for consistent O(1) access patterns.

        This method standardizes all collections (units, cities, players) to use
        dictionary format keyed by ID, enabling efficient lookups and simpler
        access patterns for LLM agents.

        IMPORTANT: Dictionary keys are ALWAYS strings for JSON compatibility.
        Numeric IDs are converted to strings via str(), so ID 123 becomes "123".

        Args:
            data: Input data (dict, list, or None)
            key_field: Field name to use as dictionary key (default: 'id')

        Returns:
            Dict[str, Any]: Dictionary keyed by key_field value (STRING keys)

        Examples:
            >>> # List to dict conversion with string keys
            >>> _ensure_dict([{"id": 123, "name": "Warrior"}])
            {"123": {"id": 123, "name": "Warrior"}}

            >>> # Already a dict passes through
            >>> _ensure_dict({"1": {"id": 1}})
            {"1": {"id": 1}}

            >>> # None returns empty dict
            >>> _ensure_dict(None)
            {}

            >>> # Custom key field
            >>> _ensure_dict([{"city_id": 5, "name": "Rome"}], key_field='city_id')
            {"5": {"city_id": 5, "name": "Rome"}}

        Note:
            Items missing the key_field or non-dict items are silently skipped.
            This enables robust handling of malformed data.
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
                        # CRITICAL: Always convert to string for JSON serialization
                        # Browser JSON.parse() requires string keys for objects
                        # Example: numeric ID 123 becomes string key "123"
                        key = str(item[key_field])
                        result[key] = item
                return result
            except (TypeError, AttributeError) as e:
                # If iteration fails, log warning and return empty dict
                logger.warning(f"Failed to iterate over {type(data)} in _ensure_dict: {e}")
                return {}
        # Fallback for unexpected types
        logger.warning(f"Unexpected type {type(data)} in _ensure_dict, returning empty dict")
        return {}

    def _dict_to_list(self, data: Any) -> List:
        """Convert dict or list to list for iteration.

        Args:
            data: Input data (dict, list, or None)

        Returns:
            List of items
        """
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values())
        return []

    def _format_full_state(self, raw_state: Dict[str, Any], player_id: int) -> Dict[str, Any]:
        """Format complete game state"""
        # ALWAYS construct game dict with all required fields - don't trust raw_state
        game_dict = {
            'turn': raw_state.get('turn', 1),
            'phase': raw_state.get('phase', 'movement'),
            'is_over': False,
            'current_player': player_id
        }

        return {
            'format': 'full',
            'turn': raw_state.get('turn'),
            'phase': raw_state.get('phase'),
            'map': self._ensure_valid_map(raw_state.get('map', {})),
            'game': game_dict,
            'units': self._ensure_dict(raw_state.get('units')),
            'cities': self._ensure_dict(raw_state.get('cities')),
            'players': self._ensure_dict(raw_state.get('players')),
            'techs': raw_state.get('techs', {}),
            'timestamp': time.time(),
            'player_perspective': player_id
        }

    def _format_llm_optimized_state(self, raw_state: Dict[str, Any], player_id: int) -> Dict[str, Any]:
        """
        Format state optimized for LLM consumption
        Target: >70% size reduction while preserving decision-critical information
        """
        # Build strategic view
        strategic = self._build_strategic_view(raw_state, player_id)

        # Build tactical view
        tactical = self._build_tactical_view(raw_state, player_id)

        # Build economic view
        economic = self._build_economic_view(raw_state, player_id)

        # ALWAYS construct game dict with all required fields - don't trust raw_state
        # This ensures current_player is always present for agent-clash
        game_dict = {
            'turn': raw_state.get('turn', 1),
            'phase': raw_state.get('phase', 'movement'),
            'is_over': False,
            'current_player': player_id
        }

        return {
            'format': 'llm_optimized',
            'turn': raw_state.get('turn'),
            'phase': raw_state.get('phase'),
            'strategic': strategic,
            'tactical': tactical,
            'economic': economic,
            # Required fields for agent-clash FreeCivState compatibility
            'game': game_dict,
            'map': self._ensure_valid_map(raw_state.get('map', {})),
            'players': self._ensure_dict(raw_state.get('players')),
            'units': self._ensure_dict(raw_state.get('units')),
            'cities': self._ensure_dict(raw_state.get('cities')),
            'techs': raw_state.get('techs', {}),  # Dict of techs per player
            'timestamp': time.time(),
            'player_perspective': player_id
        }

    def _extract_player_techs(self, state: Dict[str, Any], player_id: int) -> list:
        """Extract researched technologies for a player

        Handles both formats:
        - Dict format: {'player0': [...], 'player1': [...]}
        - List format: [...] (shared/global techs)
        """
        techs = state.get('techs', [])

        # If techs is a dict with per-player keys
        if isinstance(techs, dict):
            return techs.get(f'player{player_id}', [])

        # If techs is a list (shared techs for all players)
        elif isinstance(techs, list):
            return techs

        # Fallback: empty list
        return []

    def _build_strategic_view(self, state: Dict[str, Any], player_id: int) -> Dict[str, Any]:
        """Build strategic layer focusing on long-term game position"""
        players = self._dict_to_list(state.get('players', {}))
        player = next((p for p in players if p['id'] == player_id), None)

        if not player:
            return {}

        # Calculate relative positions
        scores = {p['id']: self._calculate_player_score(state, p['id']) for p in players}
        player_rank = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Extract wonders for this player
        wonders = state.get('wonders', {}).get(f'player{player_id}', [])

        # Check for Apollo Program (required for Space Race)
        apollo_built = 'Apollo Program' in wonders

        # Extract spaceship data for this player
        spaceship = state.get('spaceship', {}).get(f'player{player_id}', {})

        return {
            'victory_progress': {
                'current_score': scores[player_id],
                'rank': next(i for i, (pid, _) in enumerate(player_rank, 1) if pid == player_id),
                'total_players': len(players)
            },
            'tech_position': {
                'researched': self._extract_player_techs(state, player_id),
                'research_points': player.get('science', 0)
            },
            'wonders': {
                'built': wonders,
                'apollo_program': apollo_built
            },
            'spaceship': {
                'state': spaceship.get('state', 0),  # 0=NONE, 1=STARTED, 2=LAUNCHED, 3=ARRIVED
                'structurals': spaceship.get('structurals', 0),
                'components': spaceship.get('components', 0),
                'modules': spaceship.get('modules', 0),
                'success_rate': spaceship.get('success_rate', 0.0),
                'launched': spaceship.get('state', 0) >= 2  # LAUNCHED or ARRIVED
            },
            'diplomatic_status': self._get_diplomatic_summary(state, player_id),
            'relative_strength': self._assess_relative_strength(state, player_id)
        }

    def _build_tactical_view(self, state: Dict[str, Any], player_id: int) -> Dict[str, Any]:
        """Build tactical layer focusing on immediate military situation"""
        units = [u for u in self._dict_to_list(state.get('units', {})) if u['owner'] == player_id]
        enemy_units = [u for u in self._dict_to_list(state.get('units', {})) if u['owner'] != player_id]

        # Group similar units
        unit_groups = {}
        for unit in units:
            unit_type = unit['type']
            if unit_type not in unit_groups:
                unit_groups[unit_type] = {'count': 0, 'positions': [], 'avg_hp': 0}

            unit_groups[unit_type]['count'] += 1
            unit_groups[unit_type]['positions'].append((unit['x'], unit['y']))
            unit_groups[unit_type]['avg_hp'] += unit['hp']

        # Calculate averages
        for group in unit_groups.values():
            group['avg_hp'] = group['avg_hp'] / group['count'] if group['count'] > 0 else 0
            # Keep only center positions for size reduction
            if len(group['positions']) > 3:
                center_x = sum(pos[0] for pos in group['positions']) // len(group['positions'])
                center_y = sum(pos[1] for pos in group['positions']) // len(group['positions'])
                group['positions'] = [(center_x, center_y)]

        return {
            'unit_groups': unit_groups,
            'immediate_threats': self._identify_threats(units, enemy_units),
            'exploration_frontier': self._get_exploration_opportunities(state, player_id),
            'combat_readiness': self._assess_combat_readiness(units)
        }

    def _build_economic_view(self, state: Dict[str, Any], player_id: int) -> Dict[str, Any]:
        """Build economic layer focusing on resource management"""
        cities = [c for c in self._dict_to_list(state.get('cities', {})) if c['owner'] == player_id]
        players = self._dict_to_list(state.get('players', {}))
        player = next((p for p in players if p['id'] == player_id), None)

        return {
            'cities': {
                'count': len(cities),
                'total_population': sum(c.get('population', 0) for c in cities),
                'production_focus': [c.get('production', 'unknown') for c in cities],
                'growth_potential': self._assess_growth_potential(cities)
            },
            'resources': {
                'gold': player.get('gold', 0) if player else 0,
                'science': player.get('science', 0) if player else 0
            },
            'infrastructure': {
                'development_level': self._assess_development_level(cities),
                'expansion_opportunities': self._get_expansion_sites(state, player_id)
            }
        }

    def _calculate_player_score(self, state: Dict[str, Any], player_id: int) -> int:
        """Calculate simple score for player ranking"""
        cities = [c for c in self._dict_to_list(state.get('cities', {})) if c['owner'] == player_id]
        units = [u for u in self._dict_to_list(state.get('units', {})) if u['owner'] == player_id]

        # Simple scoring: cities worth more than units
        return len(cities) * 10 + len(units) * 2

    def _get_diplomatic_summary(self, state: Dict[str, Any], player_id: int) -> Dict[str, str]:
        """Get simplified diplomatic status (placeholder)"""
        return {"status": "neutral"}  # Simplified for MVP

    def _assess_relative_strength(self, state: Dict[str, Any], player_id: int) -> str:
        """Assess military strength relative to others"""
        # Simplified assessment based on unit count
        player_units = len([u for u in self._dict_to_list(state.get('units', {})) if u['owner'] == player_id])
        total_units = len(self._dict_to_list(state.get('units', {})))

        if total_units == 0:
            return "unknown"

        ratio = player_units / total_units
        if ratio > 0.4:
            return "strong"
        elif ratio > 0.2:
            return "moderate"
        else:
            return "weak"

    def _identify_threats(self, friendly_units: List[Dict], enemy_units: List[Dict]) -> List[Dict[str, Any]]:
        """Identify immediate military threats"""
        threats = []
        threat_radius = 3  # Consider units within 3 tiles as threats

        for enemy in enemy_units:
            nearby_friendlies = [
                u for u in friendly_units
                if abs(u['x'] - enemy['x']) <= threat_radius and abs(u['y'] - enemy['y']) <= threat_radius
            ]

            if nearby_friendlies:
                threats.append({
                    'enemy_type': enemy['type'],
                    'position': (enemy['x'], enemy['y']),
                    'threatened_units': len(nearby_friendlies)
                })

        return threats[:MAX_THREATS_RETURNED]

    def _get_exploration_opportunities(self, state: Dict[str, Any], player_id: int) -> List[Dict[str, int]]:
        """Get exploration opportunities (simplified)"""
        # Placeholder - would analyze fog of war in full implementation
        return [{"direction": "north", "priority": 5}]

    def _assess_combat_readiness(self, units: List[Dict]) -> Dict[str, Any]:
        """Assess overall combat readiness"""
        if not units:
            return {"status": "no_units", "strength": 0}

        total_hp = sum(u['hp'] for u in units)
        avg_hp = total_hp / len(units) if len(units) > 0 else 0

        return {
            "unit_count": len(units),
            "avg_health": round(avg_hp, 1),
            "status": "ready" if avg_hp > 7 else "weakened"
        }

    def _assess_growth_potential(self, cities: List[Dict]) -> str:
        """Assess growth potential of cities"""
        if not cities:
            return "none"

        avg_pop = sum(c.get('population', 0) for c in cities) / len(cities) if len(cities) > 0 else 0
        return "high" if avg_pop < 5 else "moderate" if avg_pop < 10 else "limited"

    def _assess_development_level(self, cities: List[Dict]) -> str:
        """Assess overall development level"""
        if not cities:
            return "none"

        total_pop = sum(c.get('population', 0) for c in cities)
        return "developed" if total_pop > 20 else "developing" if total_pop > 10 else "early"

    def _get_expansion_sites(self, state: Dict[str, Any], player_id: int) -> int:
        """Get number of potential expansion sites based on actual game data"""
        try:
            # Get actual map data if available
            tiles = state.get('tiles', [])
            existing_cities = self._dict_to_list(state.get('cities', {}))
            player_units = [u for u in self._dict_to_list(state.get('units', {})) if u.get('owner') == player_id]

            if not tiles:
                # Fallback: estimate based on units and cities
                num_cities = len([c for c in existing_cities if c.get('owner') == player_id])
                num_settlers = len([u for u in player_units if u.get('type') == 'settler'])
                return max(0, min(3, num_settlers + (3 - num_cities)))

            # Analyze tiles for suitable city sites
            suitable_sites = 0
            city_positions = {(c['x'], c['y']) for c in existing_cities}

            for tile in tiles:
                x, y = tile.get('x', -1), tile.get('y', -1)
                if x < 0 or y < 0:
                    continue

                # Check if tile is suitable for a city
                terrain = tile.get('terrain', 'unknown')
                if terrain in ['grassland', 'plains', 'hills']:
                    # Check minimum distance from existing cities (at least 2 tiles)
                    too_close = any(
                        abs(x - cx) <= 2 and abs(y - cy) <= 2
                        for cx, cy in city_positions
                    )

                    if not too_close:
                        suitable_sites += 1

            return min(suitable_sites, MAX_EXPANSION_SITES)

        except Exception as e:
            logger.warning(f"Error analyzing expansion sites: {e}")
            return 2  # Conservative fallback

    def _build_cache_key(self, game_id: str, player_id: int, format_type: str, since_turn: Optional[int] = None, current_turn: Optional[int] = None) -> str:
        """Build cache key for state including current turn to prevent stale data.

        The current_turn parameter is critical for cache correctness - without it,
        state queries return stale data when turns advance faster than cache TTL.
        """
        key = f"{game_id}_{player_id}_{format_type}"
        if current_turn is not None:
            key += f"_turn_{current_turn}"
        if since_turn is not None:
            key += f"_since_{since_turn}"
        return key

    def _simulate_previous_state(self, current_state: Dict[str, Any], since_turn: int) -> Dict[str, Any]:
        """Get previous state from game history or cache"""
        # Try to get actual previous state from cache first
        cache_key = f"state_{current_state.get('game_id', 'unknown')}_{current_state.get('player_id', 0)}_turn_{since_turn}"
        cached_state = self.cache.get(cache_key)

        if cached_state:
            logger.debug(f"Retrieved previous state from cache for turn {since_turn}")
            return cached_state

        # If not in cache, try to get from civcom
        try:
            civcom = self._get_civcom_instance(current_state.get('game_id', ''))
            if civcom and hasattr(civcom, 'get_turn_state'):
                # Try to get historical state from game server
                historical_state = civcom.get_turn_state(since_turn, current_state.get('player_id', 0))
                if historical_state:
                    logger.debug(f"Retrieved previous state from civcom for turn {since_turn}")
                    return historical_state
        except Exception as e:
            logger.warning(f"Could not retrieve historical state: {e}")

        # Fallback: Create reasonable approximation by removing recent changes
        logger.debug(f"Using approximated previous state for turn {since_turn}")
        previous_state = current_state.copy()
        previous_state['turn'] = since_turn

        # Remove units that might have been built recently (conservative approach)
        if 'units' in previous_state and len(previous_state['units']) > 2:
            previous_state['units'] = previous_state['units'][:-1]  # Remove newest unit

        # Reduce city populations slightly (cities grow over time)
        if 'cities' in previous_state:
            for city in previous_state['cities']:
                if city.get('population', 0) > 1:
                    city['population'] = max(1, city['population'] - 1)

        return previous_state

    def _generate_legal_actions_from_state(self, state: Dict[str, Any], player_id: int) -> List[Dict[str, Any]]:
        """Generate legal actions based on actual game state from civcom
        
        Uses civcom._get_legal_actions_optimized() which provides:
        - Ruleset-driven action generation (not hardcoded)
        - Smart caching (per-turn for cities/tech, always fresh for units)
        - Semantic filtering (only show actions when decisions needed)
        - No per-category limits (all valid actions included)
        """
        # Get civcom instance for ruleset-based action generation
        civcom = self._get_civcom_for_player(player_id)
        
        if civcom and hasattr(civcom, '_get_legal_actions_optimized'):
            try:
                actions = civcom._get_legal_actions_optimized(player_id)
                # Ensure all actions have priority and is_valid fields
                for action in actions:
                    action.setdefault('priority', self._get_default_priority(action.get('type')))
                    action.setdefault('is_valid', True)
                return actions
            except Exception as e:
                logger.warning(f"Failed to use _get_legal_actions_optimized: {e}, falling back to legacy generator")
        
        # Fallback: Use legacy action generation if new method not available
        logger.debug("Using fallback action generation")
        actions = []

        # Get player's units and cities
        units = [u for u in self._dict_to_list(state.get('units', {})) if u.get('owner') == player_id]
        cities = [c for c in self._dict_to_list(state.get('cities', {})) if c.get('owner') == player_id]
        
        # Always provide end_turn action
        actions.append({
            'type': 'end_turn',
            'player_id': player_id,
            'priority': 10,
            'is_valid': True
        })
        
        # Generate unit-based actions
        for unit in units:
            actions.extend(self._generate_unit_actions(unit, state, player_id))
        
        # Generate city actions
        for city in cities:
            actions.extend(self._generate_city_actions(city, state, player_id))
        
        # Generate research actions using ruleset data
        if civcom:
            try:
                researchable_techs = civcom.get_researchable_techs(player_id)
                for tech in researchable_techs:
                    actions.append({
                        'type': 'research_tech',
                        'tech': tech.get('name', ''),
                        'tech_id': tech.get('id'),
                        'cost': {'beakers': tech.get('cost', 0)},
                        'priority': 7,
                        'is_valid': True
                    })
            except Exception as e:
                logger.warning(f"Failed to get researchable techs from civcom: {e}")
                # Fallback: no tech actions generated
        else:
            logger.debug("No civcom available for tech action generation")
        
        return actions
    
    def _get_default_priority(self, action_type: str) -> int:
        """Get default priority for action types from civcom._get_legal_actions_optimized()"""
        priority_map = {
            'end_turn': 10,
            'tech_research': 7,
            'city_production': 5,
            'unit_action': 3,
            'unit_move': 2
        }
        return priority_map.get(action_type, 1)


class StateExtractorHandler(web.RequestHandler):
    """Tornado HTTP handler for /api/game/{game_id}/state endpoint"""

    def initialize(self):
        """Initialize handler with StateExtractor"""
        self.extractor = StateExtractor()
        self.executor = _shared_executor

    @run_on_executor
    def _extract_state_async(self, game_id: str, player_id: int, format_type: StateFormat, since_turn: Optional[int] = None):
        """Run state extraction in thread pool"""
        return self.extractor.extract_state(game_id, player_id, format_type, since_turn)

    async def get(self, game_id: str):
        """Handle GET requests for game state"""
        try:
            # Parse parameters
            player_id_raw = self.get_argument('player_id', None)
            if player_id_raw is None:
                self.set_status(400)
                self.write({"error": "player_id parameter is required"})
                return

            # Validate and sanitize inputs
            try:
                player_id = InputSanitizer.sanitize_player_id(player_id_raw)
            except (ValueError, TypeError) as e:
                self.set_status(400)
                self.write({"error": f"Invalid player_id: {str(e)}"})
                return

            format_str = self.get_argument('format', 'full')
            since_turn = self.get_argument('since_turn', None)

            # Validate format parameter
            if format_str not in ['full', 'minimal', 'llm']:
                self.set_status(400)
                self.write({"error": f"Invalid format '{format_str}'. Allowed: full, minimal, llm"})
                return

            # Validate since_turn parameter if provided
            if since_turn is not None:
                try:
                    since_turn = int(since_turn)
                    if since_turn < 0 or since_turn > MAX_TURN_NUMBER:
                        raise ValueError("Turn number out of range")
                except (ValueError, TypeError):
                    self.set_status(400)
                    self.write({"error": f"Invalid since_turn parameter. Must be integer 0-{MAX_TURN_NUMBER}"})
                    return

            # Authenticate request
            authenticated, auth_player_id, auth_game_id, auth_error = authenticate_request(self, 'state_read')
            if not authenticated:
                self.set_status(401)
                self.write({"error": "Authentication required"})
                return

            # If authentication provides player info, validate it matches request
            if auth_player_id is not None and player_id != str(auth_player_id):
                self.set_status(403)
                self.write({"error": "Player ID in request does not match authenticated user"})
                return

            # Validate all parameters
            try:
                validated_game_id, validated_player_id, validated_format, validated_since_turn = validate_request_parameters(
                    game_id, player_id, format_str, since_turn
                )
                format_type = StateFormat(validated_format)
            except ValidationError as e:
                logger.warning(f"Request validation failed: {e}")
                self.set_status(400)
                self.write({"error": str(e)})
                return

            # Check rate limits
            client_ip = self.request.remote_ip or "unknown"
            rate_limit_allowed, retry_after, limit_type = api_rate_limiter.check_limits(
                validated_player_id, client_ip
            )

            if not rate_limit_allowed:
                self.set_status(429)
                if retry_after:
                    self.set_header("Retry-After", str(int(retry_after) + 1))
                self.write({
                    "error": f"Rate limit exceeded for {limit_type}",
                    "retry_after": retry_after,
                    "limit_type": limit_type
                })
                return

            # Extract state asynchronously
            state = await self._extract_state_async(validated_game_id, validated_player_id, format_type, validated_since_turn)

            self.set_header("Content-Type", "application/json")
            self.write(state)

        except ValueError as e:
            # Invalid format or other validation errors
            logger.warning(f"Validation error in StateExtractorHandler: {str(e)}")
            self.set_status(400)
            self.write({"error": "Invalid request parameters"})
        except (ConnectionError, OSError, TimeoutError) as e:
            # Network and connection errors
            logger.error(f"Connection error in StateExtractorHandler: {str(e)}")
            self.set_status(503)
            self.write({"error": "Service temporarily unavailable", "retry": True})
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error in StateExtractorHandler: {error_message}")

            # Determine appropriate status code based on error
            if "No civcom available" in error_message or "Game not found" in error_message:
                self.set_status(404)
                self.write({"error": "Game not found"})
            elif "Player not found" in error_message:
                self.set_status(404)
                self.write({"error": "Player not found"})
            else:
                self.set_status(500)
                self.write({"error": "Internal server error"})


class LegalActionsHandler(web.RequestHandler):
    """Tornado HTTP handler for /api/game/{game_id}/legal_actions endpoint"""

    def initialize(self):
        """Initialize handler with StateExtractor"""
        self.extractor = StateExtractor()
        self.executor = _shared_executor

    @run_on_executor
    def _get_actions_async(self, game_id: str, player_id: int):
        """Run action extraction in thread pool"""
        return self.extractor.get_legal_actions(game_id, player_id)

    async def get(self, game_id: str):
        """Handle GET requests for legal actions"""
        try:
            # Parse parameters
            player_id_raw = self.get_argument('player_id', None)
            if player_id_raw is None:
                self.set_status(400)
                self.write({"error": "player_id parameter is required"})
                return

            # Validate and sanitize inputs
            try:
                player_id = InputSanitizer.sanitize_player_id(player_id_raw)
            except (ValueError, TypeError) as e:
                self.set_status(400)
                self.write({"error": f"Invalid player_id: {str(e)}"})
                return

            # Authenticate request
            authenticated, auth_player_id, auth_game_id, auth_error = authenticate_request(self, 'actions_read')
            if not authenticated:
                self.set_status(401)
                self.write({"error": "Authentication required"})
                return

            # If authentication provides player info, validate it matches request
            if auth_player_id is not None and player_id != str(auth_player_id):
                self.set_status(403)
                self.write({"error": "Player ID in request does not match authenticated user"})
                return

            # Validate parameters
            try:
                validated_game_id, validated_player_id, _, _ = validate_request_parameters(
                    game_id, player_id, 'full', None
                )
            except ValidationError as e:
                logger.warning(f"Request validation failed: {e}")
                self.set_status(400)
                self.write({"error": str(e)})
                return

            # Check rate limits
            client_ip = self.request.remote_ip or "unknown"
            rate_limit_allowed, retry_after, limit_type = api_rate_limiter.check_limits(
                validated_player_id, client_ip
            )

            if not rate_limit_allowed:
                self.set_status(429)
                if retry_after:
                    self.set_header("Retry-After", str(int(retry_after) + 1))
                self.write({
                    "error": f"Rate limit exceeded for {limit_type}",
                    "retry_after": retry_after,
                    "limit_type": limit_type
                })
                return

            # Extract actions asynchronously
            actions = await self._get_actions_async(validated_game_id, validated_player_id)

            self.set_header("Content-Type", "application/json")
            self.write(actions)

        except (ConnectionError, OSError, TimeoutError) as e:
            # Network and connection errors
            logger.error(f"Connection error in LegalActionsHandler: {str(e)}")
            self.set_status(503)
            self.write({"error": "Service temporarily unavailable", "retry": True})
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error in LegalActionsHandler: {error_message}")

            # Determine appropriate status code based on error
            if "No civcom available" in error_message or "Game not found" in error_message:
                self.set_status(404)
                self.write({"error": "Game not found"})
            elif "Player not found" in error_message:
                self.set_status(404)
                self.write({"error": "Player not found"})
            else:
                self.set_status(500)
                self.write({"error": "Internal server error"})
