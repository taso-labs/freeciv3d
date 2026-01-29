#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Action validation system for LLM agents in FreeCiv proxy
Validates actions before forwarding to the C server

## Error Code Scheme (Protocol v2.0.1)

Error codes are organized by category for easy identification:

### Input Validation (E220-E224, E251)
- **E220**: Missing required field
- **E221**: Invalid field type
- **E222**: Value out of range
- **E223**: Invalid characters (includes injection detection)
- **E224**: String too long
- **E251**: Invalid coordinate

### Action Validation (E001-E005, E0xx for specific actions)
- **E001-E005**: General validation errors (structure, type, auth)
- **E050-E052**: unit_fortify validation errors
- **E060-E062**: unit_sentry validation errors
- **E070-E072**: unit_build_road validation errors
- **E080-E082**: unit_build_irrigation validation errors
- **E090-E092**: unit_build_mine validation errors

### Category-Based Validation (E2xx-E3xx)
- **E230-E240**: Combat action errors
- **E260-E276**: Diplomacy/espionage errors
- **E280-E288**: Movement/transport errors
- **E290-E297**: Terrain/unit status errors
- **E310-E323**: Trade/city management errors
"""

import logging
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger("freeciv-proxy")

# === Constants ===
# Map size limits (standard FreeCiv maximum dimensions)
# See: https://freeciv.fandom.com/wiki/Map
DEFAULT_MAP_WIDTH = 200
DEFAULT_MAP_HEIGHT = 200

# Action validation limits
# NOTE: MAX_ACTION_PARAMS is intentionally only checked in _validate_basic_action as a
# catch-all for unknown action types. Specific validators (unit_move, diplomacy, etc.)
# have their own required/optional field validation which is more precise. This constant
# serves as a safety net for unrecognized actions, not a global enforcement.
MAX_ACTION_PARAMS = 20  # Maximum number of parameters in an action
MAX_NAME_LENGTH = 50  # Maximum length for names (city, tech, etc.)

class ValidationResult:
    """Result of action validation"""
    def __init__(self, is_valid: bool, error_code: Optional[str] = None, error_message: Optional[str] = None):
        self.is_valid = is_valid
        self.error_code = error_code
        self.error_message = error_message

class ActionType(Enum):
    """Supported action types for LLM agents per Protocol v2.0.1"""

    # === Movement & Transport ===
    UNIT_MOVE = "unit_move"
    UNIT_TELEPORT = "unit_teleport"
    UNIT_AIRLIFT = "unit_airlift"
    UNIT_PARADROP = "unit_paradrop"
    UNIT_EMBARK = "unit_embark"
    UNIT_DISEMBARK = "unit_disembark"
    UNIT_BOARD = "unit_board"
    UNIT_DEBOARD = "unit_deboard"
    UNIT_LOAD = "unit_load"
    UNIT_UNLOAD = "unit_unload"

    # === Combat ===
    UNIT_ATTACK = "unit_attack"
    UNIT_SUICIDE_ATTACK = "unit_suicide_attack"
    UNIT_BOMBARD = "unit_bombard"
    UNIT_CAPTURE = "unit_capture"
    UNIT_WIPE = "unit_wipe"
    UNIT_CONQUER_CITY = "unit_conquer_city"
    UNIT_NUKE = "unit_nuke"
    UNIT_NUKE_CITY = "unit_nuke_city"
    UNIT_NUKE_UNITS = "unit_nuke_units"

    # === City Foundation ===
    UNIT_BUILD_CITY = "unit_build_city"
    UNIT_JOIN_CITY = "unit_join_city"
    UNIT_HOME_CITY = "unit_home_city"

    # === Trade ===
    UNIT_TRADE_ROUTE = "unit_trade_route"
    TRADE_ROUTE = "trade_route"  # Legacy alias
    UNIT_MARKETPLACE = "unit_marketplace"
    UNIT_HELP_WONDER = "unit_help_wonder"

    # === Terrain Improvements ===
    UNIT_BUILD_ROAD = "unit_build_road"
    UNIT_BUILD_IRRIGATION = "unit_build_irrigation"
    UNIT_BUILD_MINE = "unit_build_mine"
    UNIT_BUILD_BASE = "unit_build_base"
    UNIT_PILLAGE = "unit_pillage"
    UNIT_CLEAN = "unit_clean"
    UNIT_TRANSFORM = "unit_transform"
    UNIT_CULTIVATE = "unit_cultivate"
    UNIT_PLANT = "unit_plant"

    # === Unit Status ===
    UNIT_FORTIFY = "unit_fortify"
    UNIT_SENTRY = "unit_sentry"
    UNIT_EXPLORE = "unit_explore"
    UNIT_DISBAND = "unit_disband"
    UNIT_UPGRADE = "unit_upgrade"
    UNIT_CONVERT = "unit_convert"
    UNIT_HEAL = "unit_heal"
    UNIT_SKIP = "unit_skip"
    UNIT_WAKE = "unit_wake"

    # === Espionage (Diplomat/Spy) ===
    UNIT_ESTABLISH_EMBASSY = "unit_establish_embassy"
    UNIT_EXPEL = "unit_expel"
    SPY_INVESTIGATE_CITY = "spy_investigate_city"
    SPY_POISON = "spy_poison"
    SPY_SABOTAGE_CITY = "spy_sabotage_city"
    SPY_TARGETED_SABOTAGE_CITY = "spy_targeted_sabotage_city"
    SPY_STEAL_TECH = "spy_steal_tech"
    SPY_TARGETED_STEAL_TECH = "spy_targeted_steal_tech"
    SPY_INCITE_CITY = "spy_incite_city"
    SPY_STEAL_GOLD = "spy_steal_gold"
    SPY_STEAL_MAPS = "spy_steal_maps"
    SPY_NUKE = "spy_nuke"
    SPY_SPREAD_PLAGUE = "spy_spread_plague"
    SPY_BRIBE_UNIT = "spy_bribe_unit"
    SPY_SABOTAGE_UNIT = "spy_sabotage_unit"
    SPY_ATTACK = "spy_attack"

    # === Diplomacy ===
    DIPLOMACY_DECLARE_WAR = "diplomacy_declare_war"
    DIPLOMACY_CANCEL_TREATY = "diplomacy_cancel_treaty"
    DIPLOMACY_PROPOSE_CEASEFIRE = "diplomacy_propose_ceasefire"
    DIPLOMACY_PROPOSE_PEACE = "diplomacy_propose_peace"
    DIPLOMACY_PROPOSE_ALLIANCE = "diplomacy_propose_alliance"
    DIPLOMACY_ACCEPT_TREATY = "diplomacy_accept_treaty"
    DIPLOMACY_REJECT_TREATY = "diplomacy_reject_treaty"
    DIPLOMACY_SHARE_VISION = "diplomacy_share_vision"
    DIPLOMACY_WITHDRAW_VISION = "diplomacy_withdraw_vision"
    DIPLOMACY_MESSAGE = "diplomacy_message"

    # === City Management ===
    CITY_PRODUCTION = "city_production"
    CITY_CHANGE_PRODUCTION = "city_change_production"  # Alias for city_production
    CITY_BUY = "city_buy"
    CITY_SELL_IMPROVEMENT = "city_sell_improvement"

    # === Research & Game Control ===
    TECH_RESEARCH = "tech_research"
    END_TURN = "end_turn"


# Categories for organizing action validation
class ActionCategory(Enum):
    """Categorization of action types for validation routing"""
    MOVEMENT = "movement"
    COMBAT = "combat"
    CITY_FOUNDATION = "city_foundation"
    TRADE = "trade"
    TERRAIN = "terrain"
    UNIT_STATUS = "unit_status"
    ESPIONAGE = "espionage"
    DIPLOMACY = "diplomacy"
    CITY_MANAGEMENT = "city_management"
    RESEARCH = "research"


# Map action types to their categories
ACTION_CATEGORIES = {
    # Movement
    ActionType.UNIT_MOVE: ActionCategory.MOVEMENT,
    ActionType.UNIT_TELEPORT: ActionCategory.MOVEMENT,
    ActionType.UNIT_AIRLIFT: ActionCategory.MOVEMENT,
    ActionType.UNIT_PARADROP: ActionCategory.MOVEMENT,
    ActionType.UNIT_EMBARK: ActionCategory.MOVEMENT,
    ActionType.UNIT_DISEMBARK: ActionCategory.MOVEMENT,
    ActionType.UNIT_BOARD: ActionCategory.MOVEMENT,
    ActionType.UNIT_DEBOARD: ActionCategory.MOVEMENT,
    ActionType.UNIT_LOAD: ActionCategory.MOVEMENT,
    ActionType.UNIT_UNLOAD: ActionCategory.MOVEMENT,
    # Combat
    ActionType.UNIT_ATTACK: ActionCategory.COMBAT,
    ActionType.UNIT_SUICIDE_ATTACK: ActionCategory.COMBAT,
    ActionType.UNIT_BOMBARD: ActionCategory.COMBAT,
    ActionType.UNIT_CAPTURE: ActionCategory.COMBAT,
    ActionType.UNIT_WIPE: ActionCategory.COMBAT,
    ActionType.UNIT_CONQUER_CITY: ActionCategory.COMBAT,
    ActionType.UNIT_NUKE: ActionCategory.COMBAT,
    ActionType.UNIT_NUKE_CITY: ActionCategory.COMBAT,
    ActionType.UNIT_NUKE_UNITS: ActionCategory.COMBAT,
    # City Foundation
    ActionType.UNIT_BUILD_CITY: ActionCategory.CITY_FOUNDATION,
    ActionType.UNIT_JOIN_CITY: ActionCategory.CITY_FOUNDATION,
    ActionType.UNIT_HOME_CITY: ActionCategory.CITY_FOUNDATION,
    # Trade
    ActionType.UNIT_TRADE_ROUTE: ActionCategory.TRADE,
    ActionType.TRADE_ROUTE: ActionCategory.TRADE,
    ActionType.UNIT_MARKETPLACE: ActionCategory.TRADE,
    ActionType.UNIT_HELP_WONDER: ActionCategory.TRADE,
    # Terrain
    ActionType.UNIT_BUILD_ROAD: ActionCategory.TERRAIN,
    ActionType.UNIT_BUILD_IRRIGATION: ActionCategory.TERRAIN,
    ActionType.UNIT_BUILD_MINE: ActionCategory.TERRAIN,
    ActionType.UNIT_BUILD_BASE: ActionCategory.TERRAIN,
    ActionType.UNIT_PILLAGE: ActionCategory.TERRAIN,
    ActionType.UNIT_CLEAN: ActionCategory.TERRAIN,
    ActionType.UNIT_TRANSFORM: ActionCategory.TERRAIN,
    ActionType.UNIT_CULTIVATE: ActionCategory.TERRAIN,
    ActionType.UNIT_PLANT: ActionCategory.TERRAIN,
    # Unit Status
    ActionType.UNIT_FORTIFY: ActionCategory.UNIT_STATUS,
    ActionType.UNIT_SENTRY: ActionCategory.UNIT_STATUS,
    ActionType.UNIT_EXPLORE: ActionCategory.UNIT_STATUS,
    ActionType.UNIT_DISBAND: ActionCategory.UNIT_STATUS,
    ActionType.UNIT_UPGRADE: ActionCategory.UNIT_STATUS,
    ActionType.UNIT_CONVERT: ActionCategory.UNIT_STATUS,
    ActionType.UNIT_HEAL: ActionCategory.UNIT_STATUS,
    ActionType.UNIT_SKIP: ActionCategory.UNIT_STATUS,
    ActionType.UNIT_WAKE: ActionCategory.UNIT_STATUS,
    # Espionage
    ActionType.UNIT_ESTABLISH_EMBASSY: ActionCategory.ESPIONAGE,
    ActionType.UNIT_EXPEL: ActionCategory.ESPIONAGE,
    ActionType.SPY_INVESTIGATE_CITY: ActionCategory.ESPIONAGE,
    ActionType.SPY_POISON: ActionCategory.ESPIONAGE,
    ActionType.SPY_SABOTAGE_CITY: ActionCategory.ESPIONAGE,
    ActionType.SPY_TARGETED_SABOTAGE_CITY: ActionCategory.ESPIONAGE,
    ActionType.SPY_STEAL_TECH: ActionCategory.ESPIONAGE,
    ActionType.SPY_TARGETED_STEAL_TECH: ActionCategory.ESPIONAGE,
    ActionType.SPY_INCITE_CITY: ActionCategory.ESPIONAGE,
    ActionType.SPY_STEAL_GOLD: ActionCategory.ESPIONAGE,
    ActionType.SPY_STEAL_MAPS: ActionCategory.ESPIONAGE,
    ActionType.SPY_NUKE: ActionCategory.ESPIONAGE,
    ActionType.SPY_SPREAD_PLAGUE: ActionCategory.ESPIONAGE,
    ActionType.SPY_BRIBE_UNIT: ActionCategory.ESPIONAGE,
    ActionType.SPY_SABOTAGE_UNIT: ActionCategory.ESPIONAGE,
    ActionType.SPY_ATTACK: ActionCategory.ESPIONAGE,
    # Diplomacy
    ActionType.DIPLOMACY_DECLARE_WAR: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_CANCEL_TREATY: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_PROPOSE_CEASEFIRE: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_PROPOSE_PEACE: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_PROPOSE_ALLIANCE: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_ACCEPT_TREATY: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_REJECT_TREATY: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_SHARE_VISION: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_WITHDRAW_VISION: ActionCategory.DIPLOMACY,
    ActionType.DIPLOMACY_MESSAGE: ActionCategory.DIPLOMACY,
    # City Management
    ActionType.CITY_PRODUCTION: ActionCategory.CITY_MANAGEMENT,
    ActionType.CITY_CHANGE_PRODUCTION: ActionCategory.CITY_MANAGEMENT,
    ActionType.CITY_BUY: ActionCategory.CITY_MANAGEMENT,
    ActionType.CITY_SELL_IMPROVEMENT: ActionCategory.CITY_MANAGEMENT,
    # Research
    ActionType.TECH_RESEARCH: ActionCategory.RESEARCH,
    ActionType.END_TURN: ActionCategory.RESEARCH,
}


class LLMActionValidator:
    """
    Validates LLM actions before forwarding to FreeCiv server
    Implements capability-based permissions and game rule validation
    """

    def __init__(self):
        self.validation_stats = {
            'total_actions': 0,
            'valid_actions': 0,
            'invalid_actions': 0,
            'errors_by_type': {}
        }
        # InputValidator for security checks (XSS detection)
        # NOTE: Lazy import is intentional to avoid circular dependency.
        # input_validator.py imports ValidationResult from this module at line 34,
        # so we cannot import InputValidator at module level. This pattern is safe
        # because __init__ is called after both modules are fully loaded.
        from input_validator import get_input_validator
        self._input_validator = get_input_validator()

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

        # Validate required player_id
        action_player_id = action.get('player_id', player_id)
        if action_player_id != player_id:
            return self._validation_error('E005', 'Action player_id does not match authenticated player')

        # Type-specific validation
        if action_type == ActionType.UNIT_MOVE:
            result = self._validate_unit_move(action, player_id, game_state)
        elif action_type == ActionType.UNIT_BUILD_CITY:
            result = self._validate_unit_build_city(action, player_id, game_state)
        elif action_type in (ActionType.CITY_PRODUCTION, ActionType.CITY_CHANGE_PRODUCTION):
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
            # Category-based validation for extended action types
            category = ACTION_CATEGORIES.get(action_type)
            if category == ActionCategory.COMBAT:
                result = self._validate_combat_action(action, action_type, player_id, game_state)
            elif category == ActionCategory.DIPLOMACY:
                result = self._validate_diplomacy_action(action, action_type, player_id, game_state)
            elif category == ActionCategory.ESPIONAGE:
                result = self._validate_espionage_action(action, action_type, player_id, game_state)
            elif category == ActionCategory.MOVEMENT:
                result = self._validate_movement_action(action, action_type, player_id, game_state)
            elif category == ActionCategory.TERRAIN:
                result = self._validate_terrain_action(action, action_type, player_id, game_state)
            elif category == ActionCategory.UNIT_STATUS:
                result = self._validate_unit_status_action(action, action_type, player_id, game_state)
            elif category == ActionCategory.TRADE:
                result = self._validate_trade_action(action, action_type, player_id, game_state)
            elif category == ActionCategory.CITY_MANAGEMENT:
                result = self._validate_city_management_action(action, action_type, player_id, game_state)
            else:
                # Default validation for any unrecognized categories
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

        # Comprehensive unit validation (existence, ownership, moves remaining)
        # Uses standardized error codes: E230 (not found), E231 (not owned), E024 (no moves)
        unit_result = self._validate_unit_can_act(action, player_id, game_state, 'Unit move')
        if not unit_result.is_valid:
            return unit_result

        return ValidationResult(True)

    def _validate_unit_build_city(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city building action"""
        if 'unit_id' not in action:
            return self._validation_error('E020', 'Build city requires unit_id')

        # Comprehensive unit validation (existence, ownership, moves remaining)
        unit_result = self._validate_unit_can_act(action, player_id, game_state, 'Build city')
        if not unit_result.is_valid:
            return unit_result

        # Additional check: unit type must be settler/colonist
        if game_state and 'units' in game_state:
            unit_id = action['unit_id']
            units = game_state['units']
            if isinstance(units, dict):
                unit = units.get(str(unit_id))
            else:
                unit = next((u for u in units if isinstance(u, dict) and u.get('id') == unit_id), None)

            if unit:
                unit_type = unit.get('type', '').lower()
                if 'settler' not in unit_type and 'colonist' not in unit_type:
                    return self._validation_error('E022', 'Unit cannot build cities')

        return ValidationResult(True)

    def _validate_city_production(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city production change"""
        required_fields = ['city_id', 'production_type']
        for field in required_fields:
            if field not in action:
                return self._validation_error('E030', f'City production requires {field}')

        city_id = action['city_id']
        production_type = action['production_type']

        # Basic sanity check - actual validation happens in llm_handler via RulesetMapper
        # which uses runtime unit/building data from PACKET_RULESET_UNIT and PACKET_RULESET_BUILDING
        # Here we just check for obviously invalid values (empty, too long, etc.)
        if not production_type:
            return self._validation_error('E031', 'production_type cannot be empty')
        if len(production_type) > 64:
            return self._validation_error('E031', f'production_type too long: {len(production_type)} chars')
        # Check for valid characters (alphanumeric, spaces, hyphens, periods allowed)
        import re
        if not re.match(r'^[a-zA-Z0-9\s\-\.]+$', production_type):
            return self._validation_error('E031', f'Invalid characters in production_type: {production_type}')

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
                return self._validation_error('E033', 'City not found')

        return ValidationResult(True)

    def _validate_tech_research(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate technology research action"""
        if 'tech_name' not in action:
            return self._validation_error('E040', 'Tech research requires tech_name field')

        tech_name = action['tech_name']

        # CHANGED: Case-insensitive tech validation with expanded tech list
        # FreeCiv standard tech tree expanded to 66 techs
        # Enables full era progression: Ancient → Classical → Medieval → Renaissance → Industrial → Modern
        valid_techs = [
            # Ancient era (0-5 tech count)
            'alphabet', 'animal_husbandry', 'agriculture', 'pottery',
            'mining', 'bronze_working', 'the_wheel', 'writing',
            'ceremonial_burial', 'code_of_laws', 'horseback_riding',
            'iron_working', 'mapmaking', 'masonry', 'mysticism',
            # Classical era (6-15 tech count)
            'mathematics', 'construction', 'currency', 'literacy',
            'philosophy', 'republic', 'monarchy', 'seafaring',
            'trade', 'university', 'warrior_code',
            # Medieval era (16-25 tech count)
            'astronomy', 'banking', 'chemistry', 'chivalry',
            'democracy', 'economics', 'engineering', 'feudalism',
            'gunpowder', 'invention', 'medicine', 'metallurgy',
            'navigation', 'physics', 'theology',
            # Renaissance era (26-35 tech count)
            'printing_press', 'colonization', 'magnetism', 'leadership',
            'tactics',
            # Industrial era (36-45 tech count)
            'steam_engine', 'railroad', 'steel', 'electricity',
            'sanitation', 'refrigeration', 'conscription', 'explosives',
            'corporation', 'refining',
            # Modern era (46+ tech count)
            'combustion', 'automobile', 'flight', 'radio',
            'electronics', 'mass_production', 'plastics', 'atomic_theory',
            'rocketry', 'computers'
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
        """Validate unit fortify action.

        Validates that the unit exists, is owned by the player, and has moves remaining.
        """
        return self._validate_unit_can_act(action, player_id, game_state, 'Unit fortify')

    def _validate_unit_sentry(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit sentry action.

        Validates that the unit exists, is owned by the player, and has moves remaining.
        """
        return self._validate_unit_can_act(action, player_id, game_state, 'Unit sentry')

    def _validate_unit_build_road(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build road action.

        Note: Road building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.

        Validates that the unit exists, is owned by the player, and has moves remaining.
        """
        return self._validate_unit_can_act(action, player_id, game_state, 'Unit build road')

    def _validate_unit_build_irrigation(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build irrigation action.

        Note: Irrigation building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.

        Validates that the unit exists, is owned by the player, and has moves remaining.
        """
        return self._validate_unit_can_act(action, player_id, game_state, 'Unit build irrigation')

    def _validate_unit_build_mine(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build mine action.

        Note: Mine building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.

        Validates that the unit exists, is owned by the player, and has moves remaining.
        """
        return self._validate_unit_can_act(action, player_id, game_state, 'Unit build mine')

    def _validate_basic_action(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Basic validation for other action types.

        Performs generic validation applicable to any action type not handled
        by a specific validator.
        """
        # Ensure action has reasonable structure
        if len(action) > MAX_ACTION_PARAMS:
            return self._validation_error('E003', f'Action has too many parameters (max {MAX_ACTION_PARAMS})')

        return ValidationResult(True)

    def _validation_error(self, code: str, message: str) -> ValidationResult:
        """Create validation error result"""
        logger.warning(f"Action validation failed: {code} - {message}")
        return ValidationResult(False, code, message)

    def _validate_unit_ownership(
        self,
        action: Dict[str, Any],
        player_id: int,
        game_state: Optional[Dict[str, Any]],
        error_missing: str,
        error_not_found: str,
        error_not_owned: str,
        action_name: str
    ) -> ValidationResult:
        """
        Validate unit ownership - common helper for all unit-based actions.

        Args:
            action: The action dict containing unit_id
            player_id: The player performing the action
            game_state: Optional game state with units
            error_missing: Error code when unit_id is missing
            error_not_found: Error code when unit not found
            error_not_owned: Error code when player doesn't own unit
            action_name: Action name for error messages

        Returns:
            ValidationResult with is_valid=True if valid, error otherwise
        """
        if 'unit_id' not in action:
            return self._validation_error(error_missing, f'{action_name} requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error(error_not_owned, f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error(error_not_found, f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_can_act(
        self,
        action: Dict[str, Any],
        player_id: int,
        game_state: Optional[Dict[str, Any]],
        action_name: str = 'Unit action'
    ) -> ValidationResult:
        """
        Comprehensive unit validation - checks existence, ownership, AND moves remaining.

        This is a defensive validation to catch:
        - Units that were destroyed between legal_actions generation and action submission
        - Units that ran out of moves between legal_actions and action submission

        Uses standardized error codes:
        - E230: Unit not found (destroyed or invalid ID)
        - E231: Unit not owned by player
        - E024: Unit has no moves remaining

        Args:
            action: The action dict containing unit_id or actor_id
            player_id: The player performing the action
            game_state: Current game state with units
            action_name: Action name for error messages

        Returns:
            ValidationResult with is_valid=True if unit can act, error otherwise
        """
        # Get unit_id from action (supports both unit_id and actor_id fields)
        unit_id = action.get('unit_id') or action.get('actor_id')
        if unit_id is None:
            return self._validation_error('E010', f'{action_name} requires unit_id or actor_id field')

        # If no game state, can't validate - allow action to proceed
        if not game_state or 'units' not in game_state:
            return ValidationResult(True)

        # Get units dict
        units = game_state['units']
        if isinstance(units, list):
            units = {str(u.get('id', i)): u for i, u in enumerate(units) if isinstance(u, dict)}

        # Find the unit (handle both string and integer keys)
        unit = None
        if str(unit_id) in units:
            unit = units[str(unit_id)]
        elif unit_id in units:
            unit = units[unit_id]

        if unit is None:
            return self._validation_error('E230', f'Unit {unit_id} not found (may have been destroyed)')

        # Check ownership
        if unit.get('owner') != player_id:
            return self._validation_error('E231', f'Player does not own unit {unit_id}')

        # Check moves remaining (defensive - catches stale legal_actions)
        moves_left = unit.get('moves_left', 0)
        if moves_left <= 0:
            return self._validation_error('E024', f'Unit {unit_id} has no moves remaining')

        return ValidationResult(True)

    def _validate_city_ownership(
        self,
        action: Dict[str, Any],
        player_id: int,
        game_state: Optional[Dict[str, Any]],
        error_missing: str,
        error_not_found: str,
        error_not_owned: str,
        action_name: str
    ) -> ValidationResult:
        """
        Validate city ownership - common helper for all city-based actions.

        Args:
            action: The action dict containing city_id
            player_id: The player performing the action
            game_state: Optional game state with cities
            error_missing: Error code when city_id is missing
            error_not_found: Error code when city not found
            error_not_owned: Error code when player doesn't own city
            action_name: Action name for error messages

        Returns:
            ValidationResult with is_valid=True if valid, error otherwise
        """
        if 'city_id' not in action:
            return self._validation_error(error_missing, f'{action_name} requires city_id field')

        city_id = action['city_id']

        # Validate city ownership if game state is available
        if game_state and 'cities' in game_state:
            cities = game_state['cities'].values() if isinstance(game_state['cities'], dict) else game_state['cities']
            for city in cities:
                if isinstance(city, dict) and city.get('id') == city_id:
                    if city.get('owner') != player_id:
                        return self._validation_error(error_not_owned, f'Player does not own city {city_id}')
                    return ValidationResult(True)
            # City not found in game state
            return self._validation_error(error_not_found, f'City not found: {city_id}')

        return ValidationResult(True)

    def get_validation_stats(self) -> Dict[str, Any]:
        """Get validation statistics"""
        return self.validation_stats.copy()

    def _extract_target_coordinates(self, action: Dict[str, Any]) -> tuple:
        """Extract target coordinates from action, supporting multiple formats.

        Supports:
        - Flat format: {'target_x': 10, 'target_y': 20}
        - Nested format: {'target': {'x': 10, 'y': 20}}

        Args:
            action: Action dict to extract coordinates from

        Returns:
            tuple: (target_x, target_y) or (None, None) if not found
        """
        # Try flat format first
        if 'target_x' in action and 'target_y' in action:
            return action['target_x'], action['target_y']

        # Try nested format (target.x, target.y)
        if 'target' in action and isinstance(action['target'], dict):
            target = action['target']
            if 'x' in target and 'y' in target:
                return target['x'], target['y']

        return None, None

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

    # === Category-based Validators for Extended Action Types ===

    def _validate_combat_action(self, action: Dict[str, Any], action_type: ActionType, player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate combat actions (attack, bombard, capture, nuke, etc.)

        Combat actions require:
        - unit_id: The attacking unit
        - target_x, target_y: Target location (for most combat actions)
        - target_unit_id or target_city_id: Optional specific target
        """
        # First validate unit ownership using helper
        ownership_result = self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E230', error_not_found='E232', error_not_owned='E231',
            action_name=action_type.value
        )
        if not ownership_result.is_valid:
            return ownership_result

        # Target validation depends on action type
        if action_type in [ActionType.UNIT_ATTACK, ActionType.UNIT_SUICIDE_ATTACK,
                          ActionType.UNIT_BOMBARD, ActionType.UNIT_CAPTURE]:
            # These require target coordinates or target unit
            # Support both flat (target_x, target_y) and nested (target.x, target.y) formats
            target_x, target_y = self._extract_target_coordinates(action)

            if target_x is not None and target_y is not None:
                # Use InputValidator for proper type checking (excludes bools)
                x_result = self._input_validator.validate_coordinate(target_x, 'target_x')
                if not x_result.is_valid:
                    return self._validation_error(x_result.error_code or 'E234', x_result.error_message or 'Invalid target_x')
                y_result = self._input_validator.validate_coordinate(target_y, 'target_y')
                if not y_result.is_valid:
                    return self._validation_error(y_result.error_code or 'E234', y_result.error_message or 'Invalid target_y')

                if not self._validate_coordinates(target_x, target_y, game_state):
                    return self._validation_error('E233', 'Target coordinates out of bounds')
            elif 'target_unit_id' not in action and 'target_city_id' not in action:
                return self._validation_error('E235', f'{action_type.value} requires target coordinates or target_unit_id/target_city_id')

        elif action_type == ActionType.UNIT_NUKE:
            # Nuke requires target location
            # Support both flat (target_x, target_y) and nested (target.x, target.y) formats
            target_x, target_y = self._extract_target_coordinates(action)
            if target_x is None or target_y is None:
                return self._validation_error('E236', 'unit_nuke requires target_x and target_y')

            # Use InputValidator for proper type checking
            x_result = self._input_validator.validate_coordinate(target_x, 'target_x')
            if not x_result.is_valid:
                return self._validation_error(x_result.error_code or 'E238', x_result.error_message or 'Invalid target_x')
            y_result = self._input_validator.validate_coordinate(target_y, 'target_y')
            if not y_result.is_valid:
                return self._validation_error(y_result.error_code or 'E238', y_result.error_message or 'Invalid target_y')

            if not self._validate_coordinates(target_x, target_y, game_state):
                return self._validation_error('E237', 'Nuke target coordinates out of bounds')

        elif action_type == ActionType.UNIT_NUKE_CITY:
            if 'target_city_id' not in action:
                return self._validation_error('E239', 'unit_nuke_city requires target_city_id')

        elif action_type == ActionType.UNIT_NUKE_UNITS:
            # Support both flat (target_x, target_y) and nested (target.x, target.y) formats
            target_x, target_y = self._extract_target_coordinates(action)
            if target_x is None or target_y is None:
                return self._validation_error('E240', 'unit_nuke_units requires target_x and target_y')

        return ValidationResult(True)

    def _validate_diplomacy_action(self, action: Dict[str, Any], action_type: ActionType, player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate diplomacy actions (declare war, propose peace, etc.)

        Diplomacy actions require:
        - target_player_id: The player to interact with
        - Additional fields depending on action type (message, treaty_type)
        """
        if 'target_player_id' not in action:
            return self._validation_error('E260', f'{action_type.value} requires target_player_id')

        target_player_id = action['target_player_id']

        # Cannot perform diplomacy with self
        if target_player_id == player_id:
            return self._validation_error('E261', 'Cannot perform diplomacy action on yourself')

        # Validate target player exists if game state available
        if game_state and 'players' in game_state:
            players = game_state['players']
            player_ids = [p.get('id') for p in players.values() if isinstance(p, dict)] if isinstance(players, dict) else [p.get('id') for p in players if isinstance(p, dict)]
            if target_player_id not in player_ids:
                return self._validation_error('E262', f'Target player not found: {target_player_id}')

        # Additional validation for specific diplomacy actions
        if action_type == ActionType.DIPLOMACY_MESSAGE:
            if 'message' not in action:
                return self._validation_error('E263', 'diplomacy_message requires message field')
            message = action['message']

            # Use InputValidator for comprehensive message validation
            msg_result = self._input_validator.validate_string_field(message, 'message')
            if not msg_result.is_valid:
                return self._validation_error(msg_result.error_code or 'E264', msg_result.error_message or 'Invalid message')

            # Check for XSS
            xss_result = self._input_validator.detect_xss(message)
            if not xss_result.is_valid:
                return self._validation_error('E265', 'Message contains potentially dangerous content')

        return ValidationResult(True)

    def _validate_espionage_action(self, action: Dict[str, Any], action_type: ActionType, player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate espionage actions (spy operations)

        Espionage actions require:
        - unit_id: The spy/diplomat unit
        - target_city_id or target_unit_id: The target
        - sub_target (optional): For targeted operations (specific tech, improvement)
        """
        # First validate unit ownership using helper
        ownership_result = self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E270', error_not_found='E272', error_not_owned='E271',
            action_name=action_type.value
        )
        if not ownership_result.is_valid:
            return ownership_result

        # City-targeting spy actions
        city_actions = [
            ActionType.SPY_INVESTIGATE_CITY, ActionType.SPY_POISON,
            ActionType.SPY_SABOTAGE_CITY, ActionType.SPY_TARGETED_SABOTAGE_CITY,
            ActionType.SPY_STEAL_TECH, ActionType.SPY_TARGETED_STEAL_TECH,
            ActionType.SPY_INCITE_CITY, ActionType.SPY_STEAL_GOLD,
            ActionType.SPY_STEAL_MAPS, ActionType.SPY_NUKE, ActionType.SPY_SPREAD_PLAGUE
        ]

        # Unit-targeting spy actions
        unit_actions = [
            ActionType.SPY_BRIBE_UNIT, ActionType.SPY_SABOTAGE_UNIT, ActionType.SPY_ATTACK
        ]

        if action_type in city_actions:
            if 'target_city_id' not in action:
                return self._validation_error('E273', f'{action_type.value} requires target_city_id')

            # Targeted actions require sub_target (tech or improvement name)
            if action_type in [ActionType.SPY_TARGETED_SABOTAGE_CITY, ActionType.SPY_TARGETED_STEAL_TECH]:
                if 'sub_target' not in action:
                    return self._validation_error('E274', f'{action_type.value} requires sub_target (improvement or tech name)')

                # Validate sub_target as a string field (tech_name or improvement_name)
                sub_target = action['sub_target']
                field_type = 'tech_name' if action_type == ActionType.SPY_TARGETED_STEAL_TECH else 'improvement_name'
                sub_result = self._input_validator.validate_string_field(sub_target, field_type)
                if not sub_result.is_valid:
                    return self._validation_error(sub_result.error_code or 'E274', sub_result.error_message or f'Invalid {field_type}')

        elif action_type in unit_actions:
            if 'target_unit_id' not in action:
                return self._validation_error('E275', f'{action_type.value} requires target_unit_id')

        elif action_type == ActionType.UNIT_ESTABLISH_EMBASSY:
            if 'target_player_id' not in action and 'target_city_id' not in action:
                return self._validation_error('E276', 'unit_establish_embassy requires target_player_id or target_city_id')

        return ValidationResult(True)

    def _validate_movement_action(self, action: Dict[str, Any], action_type: ActionType, player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate movement/transport actions (embark, disembark, airlift, etc.)

        Movement actions require:
        - unit_id: The unit to move
        - Additional fields depending on action type
        """
        # First validate unit ownership using helper
        ownership_result = self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E280', error_not_found='E282', error_not_owned='E281',
            action_name=action_type.value
        )
        if not ownership_result.is_valid:
            return ownership_result

        # Embark/board actions require transport target
        # Accept transport_id, target_unit_id, or target_id for flexibility
        if action_type in [ActionType.UNIT_EMBARK, ActionType.UNIT_BOARD, ActionType.UNIT_LOAD]:
            if 'transport_id' not in action and 'target_unit_id' not in action and 'target_id' not in action:
                return self._validation_error('E283', f'{action_type.value} requires transport_id, target_unit_id, or target_id')

        # Airlift requires source and destination cities
        elif action_type == ActionType.UNIT_AIRLIFT:
            if 'target_city_id' not in action:
                return self._validation_error('E284', 'unit_airlift requires target_city_id')

        # Paradrop requires target coordinates
        # Support both flat (target_x, target_y) and nested (target.x, target.y) formats
        elif action_type == ActionType.UNIT_PARADROP:
            target_x, target_y = self._extract_target_coordinates(action)
            if target_x is None or target_y is None:
                return self._validation_error('E285', 'unit_paradrop requires target_x and target_y')

            # Use InputValidator for proper type checking
            x_result = self._input_validator.validate_coordinate(target_x, 'target_x')
            if not x_result.is_valid:
                return self._validation_error(x_result.error_code or 'E287', x_result.error_message or 'Invalid target_x')
            y_result = self._input_validator.validate_coordinate(target_y, 'target_y')
            if not y_result.is_valid:
                return self._validation_error(y_result.error_code or 'E287', y_result.error_message or 'Invalid target_y')

            if not self._validate_coordinates(target_x, target_y, game_state):
                return self._validation_error('E286', 'Paradrop target coordinates out of bounds')

        # Teleport requires destination
        # Support both flat (target_x, target_y) and nested (target.x, target.y) formats
        elif action_type == ActionType.UNIT_TELEPORT:
            target_x, target_y = self._extract_target_coordinates(action)
            if target_x is None or target_y is None:
                return self._validation_error('E288', 'unit_teleport requires target_x and target_y')

            # Use InputValidator for proper type checking
            x_result = self._input_validator.validate_coordinate(target_x, 'target_x')
            if not x_result.is_valid:
                return self._validation_error(x_result.error_code or 'E288', x_result.error_message or 'Invalid target_x')
            y_result = self._input_validator.validate_coordinate(target_y, 'target_y')
            if not y_result.is_valid:
                return self._validation_error(y_result.error_code or 'E288', y_result.error_message or 'Invalid target_y')

        return ValidationResult(True)

    def _validate_terrain_action(self, action: Dict[str, Any], action_type: ActionType, player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate terrain improvement actions (build road, irrigation, pillage, etc.)

        Terrain actions require:
        - unit_id: The worker/engineer unit
        - Optional: improvement_type for generic build actions
        """
        # First validate unit ownership using helper
        ownership_result = self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E290', error_not_found='E292', error_not_owned='E291',
            action_name=action_type.value
        )
        if not ownership_result.is_valid:
            return ownership_result

        # Build base actions may specify base type
        if action_type == ActionType.UNIT_BUILD_BASE:
            if 'base_type' not in action:
                # Optional but recommended
                pass  # Will use default base type

        # Pillage may specify target infrastructure
        elif action_type == ActionType.UNIT_PILLAGE:
            if 'target' not in action:
                # Optional - will pillage default target
                pass

        return ValidationResult(True)

    def _validate_unit_status_action(self, action: Dict[str, Any], action_type: ActionType, player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit status actions (fortify, sentry, disband, upgrade, etc.)

        Status actions require:
        - unit_id: The unit to modify
        """
        # First validate unit ownership using helper
        ownership_result = self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E295', error_not_found='E297', error_not_owned='E296',
            action_name=action_type.value
        )
        if not ownership_result.is_valid:
            return ownership_result

        # Upgrade requires city context (for gold cost)
        if action_type == ActionType.UNIT_UPGRADE:
            # Unit must be in a city - checked by game server
            pass

        # Convert requires unit to have conversion ability
        if action_type == ActionType.UNIT_CONVERT:
            # Checked by game server
            pass

        return ValidationResult(True)

    def _validate_trade_action(self, action: Dict[str, Any], action_type: ActionType, player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate trade actions (trade route, marketplace, help wonder)

        Trade actions require:
        - unit_id: The trade unit (caravan, freight)
        - target_city_id: Destination city
        """
        # First validate unit ownership using helper
        ownership_result = self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E310', error_not_found='E312', error_not_owned='E311',
            action_name=action_type.value
        )
        if not ownership_result.is_valid:
            return ownership_result

        # Trade route and help wonder require target city
        if action_type in [ActionType.UNIT_TRADE_ROUTE, ActionType.TRADE_ROUTE,
                          ActionType.UNIT_HELP_WONDER]:
            if 'target_city_id' not in action:
                return self._validation_error('E313', f'{action_type.value} requires target_city_id')

        return ValidationResult(True)

    def _validate_city_management_action(self, action: Dict[str, Any], action_type: ActionType, player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city management actions (buy, sell)

        City management actions require:
        - city_id: The city to manage
        """
        # First validate city ownership using helper
        ownership_result = self._validate_city_ownership(
            action, player_id, game_state,
            error_missing='E320', error_not_found='E322', error_not_owned='E321',
            action_name=action_type.value
        )
        if not ownership_result.is_valid:
            return ownership_result

        # Sell improvement requires improvement_id
        if action_type == ActionType.CITY_SELL_IMPROVEMENT:
            if 'improvement_id' not in action and 'improvement_name' not in action:
                return self._validation_error('E323', 'city_sell_improvement requires improvement_id or improvement_name')

        return ValidationResult(True)

