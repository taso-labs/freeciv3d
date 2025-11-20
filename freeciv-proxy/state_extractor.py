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

    def register_game(self, game_id: str, agent_id: str, civcom: CivCom, metadata: Optional[Dict[str, Any]] = None):
        """Register a CivCom instance for a game with specific agent

        Args:
            game_id: Unique game identifier
            agent_id: Unique agent/player identifier
            civcom: CivCom instance to register
            metadata: Optional metadata dictionary
        """
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
        cache_key = self._build_cache_key(game_id, player_id, format_type.value, since_turn)

        # Check cache first
        cached_state = self.cache.get(cache_key)
        if cached_state is not None:
            logger.debug(f"Cache hit for {cache_key}")
            return cached_state

        # Get civcom for this game - pass agent_id for composite key lookup
        civcom = self._get_civcom_for_game(game_id, agent_id)
        if not civcom:
            raise CivComNotFoundError(game_id)

        # Extract fresh state
        start_time = time.time()

        try:
            if format_type == StateFormat.DELTA and since_turn is not None:
                state = self._extract_delta_state(game_id, player_id, since_turn, civcom)
            else:
                raw_state = civcom.get_full_state(player_id)

                if format_type == StateFormat.FULL:
                    state = self._format_full_state(raw_state, player_id)
                elif format_type == StateFormat.LLM_OPTIMIZED:
                    state = self._format_llm_optimized_state(raw_state, player_id)
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

    def get_legal_actions(self, game_id: str, player_id: int) -> List[Dict[str, Any]]:
        """
        Get top 20 legal actions for player, sorted by strategic priority

        Args:
            game_id: Unique game identifier
            player_id: Player ID

        Returns:
            List of up to 20 legal actions sorted by priority
        """
        try:
            civcom = self._get_civcom_for_game(game_id)
            if not civcom:
                raise CivComNotFoundError(game_id)

            # For now, generate mock actions based on game state
            # In a full implementation, this would extract from the actual game
            state = civcom.get_full_state(player_id)
            all_actions = self._generate_legal_actions_from_state(state, player_id)

            # Sort by priority (highest first) and take top 20
            sorted_actions = sorted(all_actions, key=lambda x: x.get('priority', 0), reverse=True)
            return sorted_actions[:40]

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
        # This ensures current_player is always present for game_arena
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
            # Required fields for game_arena FreeCivState compatibility
            'game': game_dict,
            'map': self._ensure_valid_map(raw_state.get('map', {})),
            'players': self._ensure_dict(raw_state.get('players')),
            'units': self._ensure_dict(raw_state.get('units')),
            'cities': self._ensure_dict(raw_state.get('cities')),
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
                # Freeciv Python CivCom stores city size in 'size'; some sources may use 'population'
                'total_population': sum(c.get('population', c.get('size', 1)) for c in cities),
                'production_focus': [c.get('production') for c in cities],
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

        avg_pop = sum(c.get('population', c.get('size', 1)) for c in cities) / len(cities) if len(cities) > 0 else 0
        return "high" if avg_pop < 5 else "moderate" if avg_pop < 10 else "limited"

    def _assess_development_level(self, cities: List[Dict]) -> str:
        """Assess overall development level"""
        if not cities:
            return "none"

        total_pop = sum(c.get('population', c.get('size', 1)) for c in cities)
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

    def _build_cache_key(self, game_id: str, player_id: int, format_type: str, since_turn: Optional[int] = None) -> str:
        """Build cache key for state"""
        key = f"{game_id}_{player_id}_{format_type}"
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
        """Generate legal actions based on actual game state from civcom"""
        actions = []

        try:
            # Get civcom instance for this game
            civcom = self._get_civcom_instance(state.get('game_id', ''))
            if civcom and hasattr(civcom, 'get_legal_actions'):
                # Use actual civcom to generate legal actions
                logger.debug("Getting legal actions from civcom")
                legal_actions = civcom.get_legal_actions(player_id)
                if legal_actions:
                    return legal_actions

        except Exception as e:
            logger.warning(f"Could not get legal actions from civcom: {e}")

        # Fallback: Generate actions based on available game entities
        logger.debug("Using fallback action generation")

        # Get player's units and cities
        units = [u for u in self._dict_to_list(state.get('units', {})) if u.get('owner') == player_id]
        cities = [c for c in self._dict_to_list(state.get('cities', {})) if c.get('owner') == player_id]

        # Generate realistic unit movement actions (only if unit hasn't finished moving)
        # Use done_moving flag instead of moves_left to handle Turn 1 correctly
        for unit in units:
            if not unit.get('done_moving', False):
                unit_type = unit.get('type', 'unknown')
                # Check adjacent tiles for valid moves
                for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
                    target_x, target_y = unit['x'] + dx, unit['y'] + dy

                    # Basic validity check (positive coordinates)
                    if target_x >= 0 and target_y >= 0:
                        actions.append({
                            'type': 'unit_move',
                            'unit_id': unit['id'],
                            'source': {'x': unit['x'], 'y': unit['y']},
                            'target': {'x': target_x, 'y': target_y},
                            'cost': 1,
                            'unit_type': unit_type,
                            'priority': 5 + (2 if unit_type == 'settler' else 1 if unit_type == 'explorer' else 0)
                        })

                # Add non-movement unit actions
                # Fortify action for military units
                if unit_type in ['warrior', 'archer', 'phalanx', 'legion', 'musketeer', 'riflemen', 'cavalry']:
                    actions.append({
                        'type': 'unit_fortify',
                        'unit_id': unit['id'],
                        'priority': 4
                    })

                # Build city action for settlers
                if unit_type in ['settler', 'settlers']:
                    actions.append({
                        'type': 'unit_build_city',
                        'unit_id': unit['id'],
                        'location': {'x': unit['x'], 'y': unit['y']},
                        'priority': 8
                    })

                # Worker/engineer improvement actions
                if unit_type in ['worker', 'workers', 'engineer', 'engineers']:
                    # Build road
                    actions.append({
                        'type': 'unit_build_road',
                        'unit_id': unit['id'],
                        'location': {'x': unit['x'], 'y': unit['y']},
                        'priority': 6
                    })
                    # Build irrigation
                    actions.append({
                        'type': 'unit_build_irrigation',
                        'unit_id': unit['id'],
                        'location': {'x': unit['x'], 'y': unit['y']},
                        'priority': 5
                    })
                    # Build mine
                    actions.append({
                        'type': 'unit_build_mine',
                        'unit_id': unit['id'],
                        'location': {'x': unit['x'], 'y': unit['y']},
                        'priority': 5
                    })

                # Sentry action for all units
                actions.append({
                    'type': 'unit_sentry',
                    'unit_id': unit['id'],
                    'priority': 3
                })

        # Generate city production actions based on what cities can actually build
        for city in cities:
            city_size = city.get('population', 1)
            # Larger cities can build more things
            possible_units = ['warrior']
            possible_buildings = ['granary']

            if city_size >= 2:
                possible_units.extend(['settler', 'worker'])
                possible_buildings.append('barracks')

            if city_size >= 3:
                possible_units.append('archer')
                possible_buildings.extend(['library', 'marketplace'])

            for unit_type in possible_units:
                actions.append({
                    'type': 'city_build_unit',
                    'city_id': city['id'],
                    'target': unit_type,
                    'cost': {'shields': 10 if unit_type == 'warrior' else 30},
                    'priority': 6 if unit_type in ['settler', 'warrior'] else 4
                })

            for building in possible_buildings:
                actions.append({
                    'type': 'city_build_improvement',
                    'city_id': city['id'],
                    'target': building,
                    'cost': {'shields': 20 if building == 'granary' else 40},
                    'priority': 5
                })

        # Generate research actions based on current tech level
        current_techs = state.get('technologies', [])
        available_techs = []

        # Basic tech tree progression
        if 'pottery' not in current_techs:
            available_techs.append('pottery')
        if 'bronze_working' not in current_techs:
            available_techs.append('bronze_working')
        if 'pottery' in current_techs and 'writing' not in current_techs:
            available_techs.append('writing')
        if 'bronze_working' in current_techs and 'iron_working' not in current_techs:
            available_techs.append('iron_working')

        for tech in available_techs:
            actions.append({
                'type': 'research_tech',
                'tech': tech,
                'cost': {'beakers': 12},
                'priority': 7
            })

        return actions


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
