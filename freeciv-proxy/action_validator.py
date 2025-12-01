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
MAX_MESSAGE_LENGTH = 256  # Maximum length for text messages
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
    UNIT_FOUND_CITY = "unit_found_city"
    UNIT_BUILD_CITY = "unit_build_city"  # Legacy alias
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
    ActionType.UNIT_FOUND_CITY: ActionCategory.CITY_FOUNDATION,
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

    # Default capabilities for LLM agents - all standard actions
    DEFAULT_CAPABILITIES = [
        # Movement
        ActionType.UNIT_MOVE,
        ActionType.UNIT_EMBARK,
        ActionType.UNIT_DISEMBARK,
        ActionType.UNIT_BOARD,
        ActionType.UNIT_DEBOARD,
        ActionType.UNIT_LOAD,
        ActionType.UNIT_UNLOAD,
        ActionType.UNIT_AIRLIFT,
        ActionType.UNIT_PARADROP,
        ActionType.UNIT_TELEPORT,
        # Combat
        ActionType.UNIT_ATTACK,
        ActionType.UNIT_BOMBARD,
        ActionType.UNIT_CAPTURE,
        ActionType.UNIT_CONQUER_CITY,
        # City Foundation
        ActionType.UNIT_FOUND_CITY,
        ActionType.UNIT_BUILD_CITY,
        ActionType.UNIT_JOIN_CITY,
        ActionType.UNIT_HOME_CITY,
        # Trade
        ActionType.UNIT_TRADE_ROUTE,
        ActionType.TRADE_ROUTE,
        ActionType.UNIT_HELP_WONDER,
        # Terrain
        ActionType.UNIT_BUILD_ROAD,
        ActionType.UNIT_BUILD_IRRIGATION,
        ActionType.UNIT_BUILD_MINE,
        ActionType.UNIT_BUILD_BASE,
        ActionType.UNIT_PILLAGE,
        ActionType.UNIT_CLEAN,
        # Unit Status
        ActionType.UNIT_FORTIFY,
        ActionType.UNIT_SENTRY,
        ActionType.UNIT_EXPLORE,
        ActionType.UNIT_DISBAND,
        ActionType.UNIT_UPGRADE,
        ActionType.UNIT_HEAL,
        # Espionage
        ActionType.UNIT_ESTABLISH_EMBASSY,
        ActionType.SPY_INVESTIGATE_CITY,
        ActionType.SPY_STEAL_TECH,
        ActionType.SPY_TARGETED_STEAL_TECH,
        ActionType.SPY_SABOTAGE_CITY,
        ActionType.SPY_TARGETED_SABOTAGE_CITY,
        ActionType.SPY_BRIBE_UNIT,
        ActionType.SPY_INCITE_CITY,
        # Diplomacy
        ActionType.DIPLOMACY_DECLARE_WAR,
        ActionType.DIPLOMACY_CANCEL_TREATY,
        ActionType.DIPLOMACY_PROPOSE_CEASEFIRE,
        ActionType.DIPLOMACY_PROPOSE_PEACE,
        ActionType.DIPLOMACY_PROPOSE_ALLIANCE,
        ActionType.DIPLOMACY_ACCEPT_TREATY,
        ActionType.DIPLOMACY_REJECT_TREATY,
        ActionType.DIPLOMACY_SHARE_VISION,
        ActionType.DIPLOMACY_WITHDRAW_VISION,
        ActionType.DIPLOMACY_MESSAGE,
        # City Management
        ActionType.CITY_PRODUCTION,
        ActionType.CITY_BUY,
        ActionType.CITY_SELL_IMPROVEMENT,
        # Research
        ActionType.TECH_RESEARCH,
        ActionType.END_TURN,
    ]

    # Restricted actions that require special permissions (destructive/irreversible)
    RESTRICTED_ACTIONS = [
        ActionType.UNIT_NUKE,
        ActionType.UNIT_NUKE_CITY,
        ActionType.UNIT_NUKE_UNITS,
        ActionType.SPY_NUKE,
        ActionType.SPY_POISON,
        ActionType.SPY_SPREAD_PLAGUE,
    ]

    def __init__(self, capabilities: Optional[List[ActionType]] = None):
        self.capabilities = capabilities or self.DEFAULT_CAPABILITIES.copy()
        self.validation_stats = {
            'total_actions': 0,
            'valid_actions': 0,
            'invalid_actions': 0,
            'errors_by_type': {}
        }
        # InputValidator for security checks (XSS, SQL injection)
        # NOTE: Lazy import is intentional to avoid circular dependency.
        # input_validator.py imports ValidationResult from this module, so we
        # cannot import InputValidator at module level. This pattern is safe
        # because __init__ is only called once per validator instance.
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
                return self._validation_error('E014', 'Unit not found or not visible')

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
                return self._validation_error('E023', 'Unit not found')

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
        valid_production_types = [
            'warrior', 'settler', 'worker', 'archer', 'spearman',
            'barracks', 'granary', 'library', 'marketplace',
            'temple', 'aqueduct', 'walls'
        ]

        if production_type not in valid_production_types:
            return self._validation_error('E031', f'Invalid production type: {production_type}')

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
        return self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E050', error_not_found='E051', error_not_owned='E052',
            action_name='Unit fortify'
        )

    def _validate_unit_sentry(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit sentry action"""
        return self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E060', error_not_found='E061', error_not_owned='E062',
            action_name='Unit sentry'
        )

    def _validate_unit_build_road(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build road action

        Note: Road building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.
        """
        return self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E070', error_not_found='E071', error_not_owned='E072',
            action_name='Unit build road'
        )

    def _validate_unit_build_irrigation(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build irrigation action

        Note: Irrigation building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.
        """
        return self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E080', error_not_found='E081', error_not_owned='E082',
            action_name='Unit build irrigation'
        )

    def _validate_unit_build_mine(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build mine action

        Note: Mine building uses PACKET_UNIT_CHANGE_ACTIVITY which operates on the unit's
        current tile. Coordinates are not part of the packet protocol.
        """
        return self._validate_unit_ownership(
            action, player_id, game_state,
            error_missing='E090', error_not_found='E091', error_not_owned='E092',
            action_name='Unit build mine'
        )

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
            if 'target_x' in action and 'target_y' in action:
                # Use InputValidator for proper type checking (excludes bools)
                x_result = self._input_validator.validate_coordinate(action['target_x'], 'target_x')
                if not x_result.is_valid:
                    return self._validation_error(x_result.error_code or 'E234', x_result.error_message or 'Invalid target_x')
                y_result = self._input_validator.validate_coordinate(action['target_y'], 'target_y')
                if not y_result.is_valid:
                    return self._validation_error(y_result.error_code or 'E234', y_result.error_message or 'Invalid target_y')

                if not self._validate_coordinates(action['target_x'], action['target_y'], game_state):
                    return self._validation_error('E233', 'Target coordinates out of bounds')
            elif 'target_unit_id' not in action and 'target_city_id' not in action:
                return self._validation_error('E235', f'{action_type.value} requires target coordinates or target_unit_id/target_city_id')

        elif action_type == ActionType.UNIT_NUKE:
            # Nuke requires target location
            if 'target_x' not in action or 'target_y' not in action:
                return self._validation_error('E236', 'unit_nuke requires target_x and target_y')

            # Use InputValidator for proper type checking
            x_result = self._input_validator.validate_coordinate(action['target_x'], 'target_x')
            if not x_result.is_valid:
                return self._validation_error(x_result.error_code or 'E238', x_result.error_message or 'Invalid target_x')
            y_result = self._input_validator.validate_coordinate(action['target_y'], 'target_y')
            if not y_result.is_valid:
                return self._validation_error(y_result.error_code or 'E238', y_result.error_message or 'Invalid target_y')

            if not self._validate_coordinates(action['target_x'], action['target_y'], game_state):
                return self._validation_error('E237', 'Nuke target coordinates out of bounds')

        elif action_type == ActionType.UNIT_NUKE_CITY:
            if 'target_city_id' not in action:
                return self._validation_error('E239', 'unit_nuke_city requires target_city_id')

        elif action_type == ActionType.UNIT_NUKE_UNITS:
            if 'target_x' not in action or 'target_y' not in action:
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

            # Check for SQL injection
            sql_result = self._input_validator.detect_sql_injection(message)
            if not sql_result.is_valid:
                return self._validation_error('E265', 'Message contains potentially dangerous content')

            # Check for XSS
            xss_result = self._input_validator.detect_xss(message)
            if not xss_result.is_valid:
                return self._validation_error('E266', 'Message contains potentially dangerous content')

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
        if action_type in [ActionType.UNIT_EMBARK, ActionType.UNIT_BOARD, ActionType.UNIT_LOAD]:
            if 'transport_id' not in action and 'target_unit_id' not in action:
                return self._validation_error('E283', f'{action_type.value} requires transport_id or target_unit_id')

        # Airlift requires source and destination cities
        elif action_type == ActionType.UNIT_AIRLIFT:
            if 'target_city_id' not in action:
                return self._validation_error('E284', 'unit_airlift requires target_city_id')

        # Paradrop requires target coordinates
        elif action_type == ActionType.UNIT_PARADROP:
            if 'target_x' not in action or 'target_y' not in action:
                return self._validation_error('E285', 'unit_paradrop requires target_x and target_y')

            # Use InputValidator for proper type checking
            x_result = self._input_validator.validate_coordinate(action['target_x'], 'target_x')
            if not x_result.is_valid:
                return self._validation_error(x_result.error_code or 'E287', x_result.error_message or 'Invalid target_x')
            y_result = self._input_validator.validate_coordinate(action['target_y'], 'target_y')
            if not y_result.is_valid:
                return self._validation_error(y_result.error_code or 'E287', y_result.error_message or 'Invalid target_y')

            if not self._validate_coordinates(action['target_x'], action['target_y'], game_state):
                return self._validation_error('E286', 'Paradrop target coordinates out of bounds')

        # Teleport requires destination
        elif action_type == ActionType.UNIT_TELEPORT:
            if 'target_x' not in action or 'target_y' not in action:
                return self._validation_error('E288', 'unit_teleport requires target_x and target_y')

            # Use InputValidator for proper type checking
            x_result = self._input_validator.validate_coordinate(action['target_x'], 'target_x')
            if not x_result.is_valid:
                return self._validation_error(x_result.error_code or 'E288', x_result.error_message or 'Invalid target_x')
            y_result = self._input_validator.validate_coordinate(action['target_y'], 'target_y')
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

