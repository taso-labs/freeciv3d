#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Action validation system for LLM agents in FreeCiv proxy
Validates actions before forwarding to the C server

## Error Code Scheme

Error codes are organized by action type for easy identification:

- **E001-E005**: General validation errors (structure, type, auth)
- **E010-E014**: unit_move validation errors
- **E020-E023**: unit_build_city validation errors
- **E030-E033**: city_production validation errors
- **E040-E041**: tech_research validation errors
- **E050-E052**: unit_fortify validation errors
- **E060-E062**: unit_sentry validation errors
- **E070-E072**: unit_build_road validation errors
- **E080-E082**: unit_build_irrigation validation errors
- **E090-E092**: unit_build_mine validation errors

This grouping makes it easy to identify which action failed from the error code.
"""

import logging
from typing import Dict, Any, List, Optional
from enum import Enum
from itertools import chain

from civcom import CivCom
from ruleset_mapper import clean_production_name

logger = logging.getLogger("freeciv-proxy")

# Map size limits (standard FreeCiv maximum dimensions)
# See: https://freeciv.fandom.com/wiki/Map
DEFAULT_MAP_WIDTH = 200
DEFAULT_MAP_HEIGHT = 200

class ValidationResult:
    """Result of action validation"""
    def __init__(self, is_valid: bool, error_code: Optional[str] = None, error_message: Optional[str] = None):
        self.is_valid = is_valid
        self.error_code = error_code
        self.error_message = error_message

class ActionType(Enum):
    """Supported action types for LLM agents"""
    UNIT_MOVE = "unit_move"
    UNIT_BUILD_CITY = "unit_build_city"
    UNIT_EXPLORE = "unit_explore"
    CITY_PRODUCTION = "city_production"
    CITY_BUY = "city_buy"
    TECH_RESEARCH = "tech_research"
    TRADE_ROUTE = "trade_route"
    END_TURN = "end_turn"
    # AGE-192: New action types for richer gameplay
    UNIT_FORTIFY = "unit_fortify"
    UNIT_SENTRY = "unit_sentry"
    UNIT_BUILD_ROAD = "unit_build_road"
    UNIT_BUILD_IRRIGATION = "unit_build_irrigation"
    UNIT_BUILD_MINE = "unit_build_mine"

class LLMActionValidator:
    """
    Validates LLM actions before forwarding to FreeCiv server
    Implements capability-based permissions and game rule validation
    """

    # Default capabilities for LLM agents
    DEFAULT_CAPABILITIES = [
        ActionType.UNIT_MOVE,
        ActionType.UNIT_BUILD_CITY,
        ActionType.UNIT_EXPLORE,
        ActionType.CITY_PRODUCTION,
        ActionType.TECH_RESEARCH,
        ActionType.END_TURN,
        # AGE-192: Additional unit actions for richer gameplay
        ActionType.UNIT_FORTIFY,
        ActionType.UNIT_SENTRY,
        ActionType.UNIT_BUILD_ROAD,
        ActionType.UNIT_BUILD_IRRIGATION,
        ActionType.UNIT_BUILD_MINE
    ]

    # Restricted actions that require special permissions
    RESTRICTED_ACTIONS = [
        ActionType.CITY_BUY,
        ActionType.TRADE_ROUTE
    ]

    def __init__(self, capabilities: Optional[List[ActionType]] = None, civcom: Optional[CivCom] = None):
        self.capabilities = capabilities or self.DEFAULT_CAPABILITIES.copy()
        self.civcom = civcom
        self.validation_stats = {
            'total_actions': 0,
            'valid_actions': 0,
            'invalid_actions': 0,
            'errors_by_type': {}
        }

    def validate_action(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]] = None) -> ValidationResult:
        """
        Validate an LLM action before forwarding to server

        Args:
            action: Action dictionary with type and parameters
            player_id: ID of the player making the action
            game_state: Current game state for context validation

        Returns:
            ValidationResult indicating if action is valid
        """
        self.validation_stats['total_actions'] += 1

        # Basic structure validation
        if not isinstance(action, dict):
            return self._validation_error('E001', 'Action must be a dictionary')

        if 'type' not in action:
            return self._validation_error('E002', 'Action must specify a type')

        action_type_str = action['type']

        # Convert string to enum
        try:
            action_type = ActionType(action_type_str)
        except ValueError:
            return self._validation_error('E003', f'Unknown action type: {action_type_str}')

        # Capability check
        if action_type not in self.capabilities:
            return self._validation_error('E004', f'Action type {action_type_str} not permitted for this agent')

        # Validate required player_id
        action_player_id = action.get('player_id', player_id)
        if action_player_id != player_id:
            return self._validation_error('E005', 'Action player_id does not match authenticated player')

        # Type-specific validation
        if action_type == ActionType.UNIT_MOVE:
            result = self._validate_unit_move(action, player_id, game_state)
        elif action_type == ActionType.UNIT_BUILD_CITY:
            result = self._validate_unit_build_city(action, player_id, game_state)
        elif action_type == ActionType.CITY_PRODUCTION:
            result = self._validate_city_production(action, player_id, game_state)
        elif action_type == ActionType.TECH_RESEARCH:
            result = self._validate_tech_research(action, player_id, game_state)
        elif action_type == ActionType.END_TURN:
            result = self._validate_end_turn(action, player_id, game_state)
        # AGE-192: New unit action validators
        elif action_type == ActionType.UNIT_FORTIFY:
            result = self._validate_unit_fortify(action, player_id, game_state)
        elif action_type == ActionType.UNIT_SENTRY:
            result = self._validate_unit_sentry(action, player_id, game_state)
        elif action_type == ActionType.UNIT_BUILD_ROAD:
            result = self._validate_unit_build_road(action, player_id, game_state)
        elif action_type == ActionType.UNIT_BUILD_IRRIGATION:
            result = self._validate_unit_build_irrigation(action, player_id, game_state)
        elif action_type == ActionType.UNIT_BUILD_MINE:
            result = self._validate_unit_build_mine(action, player_id, game_state)
        else:
            # Default validation for other action types
            result = self._validate_basic_action(action, player_id, game_state)

        # Update statistics
        if result.is_valid:
            self.validation_stats['valid_actions'] += 1
        else:
            self.validation_stats['invalid_actions'] += 1
            error_type = result.error_code or 'unknown'
            self.validation_stats['errors_by_type'][error_type] = (
                self.validation_stats['errors_by_type'].get(error_type, 0) + 1
            )

        return result

    def _validate_unit_move(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit movement action"""
        required_fields = ['unit_id', 'dest_x', 'dest_y']
        for field in required_fields:
            if field not in action:
                return self._validation_error('E010', f'Unit move requires {field}')

        unit_id = action['unit_id']
        dest_x = action['dest_x']
        dest_y = action['dest_y']

        # Validate coordinates are integers
        try:
            dest_x = int(dest_x)
            dest_y = int(dest_y)
        except (ValueError, TypeError):
            return self._validation_error('E011', 'Destination coordinates must be integers')

        # Enhanced coordinate validation against actual game boundaries
        if not self._validate_coordinates(dest_x, dest_y, game_state):
            return self._validation_error('E012', 'Destination coordinates out of game bounds')

        # If game state is available, validate unit ownership
        if game_state and 'units' in game_state:
            # Iterate directly over dict values (no need to create intermediate list)
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit_found = False
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    unit_found = True
                    if unit.get('owner') != player_id:
                        return self._validation_error('E013', 'Player does not own this unit')
                    break

            if not unit_found:
                return self._validation_error('E014', f'Unit {unit_id} not found or not visible out of {units}')

        return ValidationResult(True)

    def _validate_unit_build_city(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city building action"""
        if 'unit_id' not in action:
            return self._validation_error('E020', 'Build city requires unit_id')

        unit_id = action['unit_id']

        # If game state is available, verify unit can build city (settler)
        if game_state and 'units' in game_state:
            # Iterate directly over dict values (no need to create intermediate list)
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E021', 'Player does not own this unit')

                    # Check if unit type can build cities (should be settler)
                    unit_type = unit.get('type', '').lower()
                    if 'settler' not in unit_type and 'colonist' not in unit_type:
                        return self._validation_error('E022', 'Unit cannot build cities')
                    break
            else:
                return self._validation_error("E023", "Unit not found")

        return ValidationResult(True)

    def _validate_city_production(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city production change"""
        required_fields = ['city_id', 'production_type']
        for field in required_fields:
            if field not in action:
                return self._validation_error('E030', f'City production requires {field}')

        city_id = action['city_id']
        production_type = action['production_type']

        # Validate production type is reasonable
        valid_production_types: list[str] = []

        for _, prod_type in chain(
            self.civcom.unit_types.items(), self.civcom.improvements.items()
        ):
            name = prod_type.get("name", "")
            if not name:
                continue
            clean_name = clean_production_name(name)
            valid_production_types.append(clean_name)

        for production in valid_production_types:
            if production_type.casefold() == production.casefold():
                production_type = production
                break
        else:
            return self._validation_error(
                "E031",
                f"Invalid production type: {production_type}, should be one of {valid_production_types}",
            )

        # If game state available, verify city ownership
        if game_state and 'cities' in game_state:
            # Iterate directly over dict values (no need to create intermediate list)
            cities = game_state['cities'].values() if isinstance(game_state['cities'], dict) else game_state['cities']
            for city in cities:
                if isinstance(city, dict) and city.get('id') == city_id:
                    if city.get('owner') != player_id:
                        return self._validation_error('E032', 'Player does not own this city')
                    break
            else:
                return self._validation_error("E033", "City not found")

        return ValidationResult(True)

    def _validate_tech_research(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate technology research action"""
        if 'tech_name' not in action:
            return self._validation_error('E040', 'Tech research requires tech_name field')

        tech_name = action['tech_name']

        # CHANGED: Case-insensitive tech validation with expanded tech list
        # FreeCiv standard tech tree (common techs across rulesets)
        valid_techs = [
            # Ancient techs
            'alphabet', 'animal_husbandry', 'agriculture', 'pottery',
            'mining', 'bronze_working', 'the_wheel', 'writing',
            'ceremonial_burial', 'code_of_laws', 'horseback_riding',
            'iron_working', 'mapmaking', 'masonry', 'mysticism',
            # Classical techs
            'mathematics', 'construction', 'currency', 'literacy',
            'philosophy', 'republic', 'monarchy', 'seafaring',
            'trade', 'university', 'warrior_code',
            # Medieval techs
            'astronomy', 'banking', 'chemistry', 'chivalry',
            'democracy', 'economics', 'engineering', 'feudalism',
            'gunpowder', 'invention', 'medicine', 'metallurgy',
            'navigation', 'physics', 'theology'
        ]

        # Case-insensitive comparison
        tech_name_lower = str(tech_name).lower().replace(' ', '_')

        if tech_name_lower not in valid_techs:
            # More helpful error message with suggestions
            return self._validation_error(
                'E041',
                f'Invalid technology: "{tech_name}". '
                f'Try one of: {", ".join(sorted(valid_techs[:12]))}... '
                f'(Note: tech names are case-insensitive)'
            )

        return ValidationResult(True)

    def _validate_end_turn(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate end turn action

        end_turn is the simplest action - it just requires player_id validation
        which is already done at the top level. This method exists for completeness
        and future extension (e.g., checking if player can actually end turn).
        """
        # end_turn has no required fields beyond type and player_id (already validated)
        # In the future, could add validation like:
        # - Check if it's actually this player's turn
        # - Check if player has pending actions that must be resolved
        # For now, always allow end_turn
        return ValidationResult(True)

    # AGE-192: New unit action validators
    def _validate_unit_fortify(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit fortify action"""
        if 'unit_id' not in action:
            return self._validation_error('E050', 'Unit fortify requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E052', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E051', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_sentry(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit sentry action"""
        if 'unit_id' not in action:
            return self._validation_error('E060', 'Unit sentry requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E062', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E061', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_build_road(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build road action

        Note: Road building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.
        """
        if 'unit_id' not in action:
            return self._validation_error('E070', 'Unit build road requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E071', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E072', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_build_irrigation(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build irrigation action

        Note: Irrigation building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.
        """
        if 'unit_id' not in action:
            return self._validation_error('E080', 'Unit build irrigation requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E081', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E082', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_build_mine(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build mine action

        Note: Mine building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.
        """
        if 'unit_id' not in action:
            return self._validation_error('E090', 'Unit build mine requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game_state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E091', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E092', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_basic_action(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Basic validation for other action types"""
        # Ensure action has reasonable structure
        if len(action) > 20:  # Prevent overly complex actions
            return self._validation_error('E050', 'Action has too many parameters')

        return ValidationResult(True)

    def _validation_error(self, code: str, message: str) -> ValidationResult:
        """Create validation error result"""
        logger.warning(f"Action validation failed: {code} - {message}")
        return ValidationResult(False, code, message)

    def get_validation_stats(self) -> Dict[str, Any]:
        """Get validation statistics"""
        return self.validation_stats.copy()

    def add_capability(self, action_type: ActionType):
        """Add capability for this validator"""
        if action_type not in self.capabilities:
            self.capabilities.append(action_type)

    def remove_capability(self, action_type: ActionType):
        """Remove capability for this validator"""
        if action_type in self.capabilities:
            self.capabilities.remove(action_type)

    def _validate_coordinates(self, x: int, y: int, game_state: Optional[Dict[str, Any]] = None) -> bool:
        """Enhanced coordinate validation against actual game boundaries

        Uses module-level constants DEFAULT_MAP_WIDTH and DEFAULT_MAP_HEIGHT.
        Valid coordinates: 0 to (size-1), so 0-199 for default 200x200 map.

        Args:
            x: X coordinate to validate
            y: Y coordinate to validate
            game_state: Optional game state with map_info

        Returns:
            bool: True if coordinates are valid, False otherwise
        """
        if game_state and 'map_info' in game_state:
            map_info = game_state['map_info']
            max_x = map_info.get('width', DEFAULT_MAP_WIDTH)
            max_y = map_info.get('height', DEFAULT_MAP_HEIGHT)

            if not (0 <= x < max_x and 0 <= y < max_y):
                return False
        elif not (0 <= x < DEFAULT_MAP_WIDTH and 0 <= y < DEFAULT_MAP_HEIGHT):
            # Fallback to default map bounds when no game state
            # Coordinates from 0 to 199 for default 200x200 map
            return False

        return True
