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
- **E100-E102**: unit_clean_pollution validation errors
- **E103-E105**: unit_clean_fallout validation errors
- **E106-E108**: unit_transform_terrain validation errors
- **E109-E116**: Tactical/unit level errors (attack, bombard, pillage, transport, airlift, espionage)
- **E201-E204**: city_buy validation errors
- **E205-E206**: upgrade_unit validation errors
- **E300-E304**: player_ready validation errors
// Diplomacy & Trade
- **E310-E312**: Diplomacy (embassy) errors
// Transport
- **E350-E353**: Transport specific errors
- **E354-E356**: Airlift specific errors
// Espionage & Trade (future expansion)
- **E400-E403**: Espionage specific errors
- **E410**: Trade route unit type error

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
    UNIT_CLEAN_POLLUTION = "unit_clean_pollution"
    UNIT_CLEAN_FALLOUT = "unit_clean_fallout"
    UNIT_TRANSFORM_TERRAIN = "unit_transform_terrain"
    
    UNIT_ATTACK = "unit_attack"
    PLAYER_READY = "player_ready"
    
    UPGRADE_UNIT = "upgrade_unit"
    BOMBARD = "bombard"
    PILLAGE = "pillage"
    
    TRANSPORT_BOARD = "transport_board"
    TRANSPORT_DEBOARD = "transport_deboard"
    TRANSPORT_UNLOAD = "transport_unload"
    
    AIRLIFT = "airlift"
    ESTABLISH_EMBASSY = "establish_embassy"
    
    SPY_INVESTIGATE_CITY = "spy_investigate_city"
    SPY_POISON = "spy_poison"
    SPY_SABOTAGE_CITY = "spy_sabotage_city"
    SPY_STEAL_TECH = "spy_steal_tech"
    SPY_BRIBE_UNIT = "spy_bribe_unit"
    SPY_STEAL_GOLD = "spy_steal_gold"
    SPY_INCITE_CITY = "spy_incite_city"
    
    GOVERNMENT_CHANGE = "government_change"
    
    DISBAND_UNIT = "disband_unit"
    JOIN_CITY = "join_city"
    
    CITY_CHANGE_SPECIALIST = "city_change_specialist"
    CITY_SELL_IMPROVEMENT = "city_sell_improvement"
    
    CULTIVATE = "cultivate"
    PLANT = "plant"
    BASE = "base"
    
    CITY_BUILD_UNIT = "city_build_unit"
    CITY_BUILD_IMPROVEMENT = "city_build_improvement"
    
    DIPLOMACY_MESSAGE = "diplomacy_message"
    
    HELP_WONDER = "help_wonder"
    CONQUER_CITY = "conquer_city"
    CAPTURE_UNITS = "capture_units"
    STEAL_MAPS = "steal_maps"
    CONVERT = "convert"
    HOME_CITY = "home_city"
    # Advanced Actions: Military & Economic
    STRIKE_BUILDING = "strike_building"
    STRIKE_PRODUCTION = "strike_production"
    MARKETPLACE = "marketplace"
    EXPEL_UNIT = "expel_unit"
    SPY_SABOTAGE_UNIT = "spy_sabotage_unit"
    PLAYER_RATES = "player_rates"

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
        ActionType.UNIT_BUILD_MINE,
        # Include UNIT_ATTACK in default capabilities
        ActionType.UNIT_ATTACK,
        ActionType.PLAYER_READY,
        # Economy actions
        ActionType.CITY_BUY,
        ActionType.UPGRADE_UNIT,
        # Combat actions
        ActionType.BOMBARD,
        ActionType.PILLAGE,
        # Transport actions
        ActionType.TRANSPORT_BOARD,
        ActionType.TRANSPORT_DEBOARD,
        ActionType.TRANSPORT_UNLOAD,
        # Strategic & Diplomacy actions
        ActionType.AIRLIFT,
        ActionType.ESTABLISH_EMBASSY,
        ActionType.SPY_INVESTIGATE_CITY,
        ActionType.SPY_POISON,
        ActionType.SPY_SABOTAGE_CITY,
        ActionType.SPY_STEAL_TECH,
        ActionType.SPY_BRIBE_UNIT,
        ActionType.SPY_STEAL_GOLD,
        ActionType.SPY_INCITE_CITY,
        # Terrain management
        ActionType.UNIT_CLEAN_POLLUTION,
        ActionType.UNIT_CLEAN_FALLOUT,
        ActionType.UNIT_TRANSFORM_TERRAIN,
        
        ActionType.GOVERNMENT_CHANGE,
        ActionType.DISBAND_UNIT,
        ActionType.JOIN_CITY,
        ActionType.CITY_CHANGE_SPECIALIST,
        ActionType.CITY_SELL_IMPROVEMENT,
        
        ActionType.CULTIVATE,
        ActionType.PLANT,
        ActionType.BASE,
        
        ActionType.CITY_BUILD_UNIT,
        ActionType.CITY_BUILD_IMPROVEMENT,
        
        ActionType.DIPLOMACY_MESSAGE,
        
        ActionType.HELP_WONDER,
        ActionType.CONQUER_CITY,
        ActionType.CAPTURE_UNITS,
        ActionType.STEAL_MAPS,
        ActionType.CONVERT,
        ActionType.HOME_CITY,
        # Advanced Actions: Military & Economic
        ActionType.STRIKE_BUILDING,
        ActionType.STRIKE_PRODUCTION,
        ActionType.MARKETPLACE,
        ActionType.EXPEL_UNIT,
        ActionType.SPY_SABOTAGE_UNIT,
        ActionType.PLAYER_RATES,
    ]

    # Restricted actions that require special permissions
    RESTRICTED_ACTIONS = [
        ActionType.TRADE_ROUTE
    ]

    def __init__(self, capabilities: Optional[List[ActionType]] = None, civcom: Optional[CivCom] = None):
        self.capabilities = capabilities if capabilities is not None else self.DEFAULT_CAPABILITIES.copy()
        self.civcom = civcom
        # Typed stats container to avoid type inference issues
        self.validation_stats: Dict[str, Any] = {
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
        # Safely increment total action counter with explicit type narrowing
        _ta = self.validation_stats.get('total_actions')
        if not isinstance(_ta, int):
            _ta = 0
        self.validation_stats['total_actions'] = _ta + 1

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
        elif action_type == ActionType.UNIT_CLEAN_POLLUTION:
            result = self._validate_unit_clean_pollution(action, player_id, game_state)
        elif action_type == ActionType.UNIT_CLEAN_FALLOUT:
            result = self._validate_unit_clean_fallout(action, player_id, game_state)
        elif action_type == ActionType.UNIT_TRANSFORM_TERRAIN:
            result = self._validate_unit_transform_terrain(action, player_id, game_state)
        elif action_type == ActionType.UNIT_ATTACK:
            result = self._validate_unit_attack(action, player_id, game_state)
        elif action_type == ActionType.PLAYER_READY:
            result = self._validate_player_ready(action, player_id, game_state)
        elif action_type == ActionType.CITY_BUY:
            result = self._validate_city_buy(action, player_id, game_state)
        elif action_type == ActionType.UPGRADE_UNIT:
            result = self._validate_upgrade_unit(action, player_id, game_state)
        elif action_type == ActionType.BOMBARD:
            result = self._validate_bombard(action, player_id, game_state)
        elif action_type == ActionType.PILLAGE:
            result = self._validate_pillage(action, player_id, game_state)
        elif action_type == ActionType.TRANSPORT_BOARD:
            result = self._validate_transport_board(action, player_id, game_state)
        elif action_type == ActionType.TRANSPORT_DEBOARD:
            result = self._validate_transport_deboard(action, player_id, game_state)
        elif action_type == ActionType.TRANSPORT_UNLOAD:
            result = self._validate_transport_unload(action, player_id, game_state)
        elif action_type == ActionType.AIRLIFT:
            result = self._validate_airlift(action, player_id, game_state)
        elif action_type == ActionType.ESTABLISH_EMBASSY:
            result = self._validate_establish_embassy(action, player_id, game_state)
        elif action_type in (
            ActionType.SPY_INVESTIGATE_CITY,
            ActionType.SPY_POISON,
            ActionType.SPY_SABOTAGE_CITY,
            ActionType.SPY_STEAL_TECH,
            ActionType.SPY_BRIBE_UNIT,
            ActionType.SPY_STEAL_GOLD,
            ActionType.SPY_INCITE_CITY
        ):
            result = self._validate_spy_action(action, player_id, game_state)
        elif action_type == ActionType.TRADE_ROUTE:
            result = self._validate_trade_route(action, player_id, game_state)
        elif action_type == ActionType.GOVERNMENT_CHANGE:
            result = self._validate_government_change(action, player_id, game_state)
        elif action_type == ActionType.DISBAND_UNIT:
            result = self._validate_disband_unit(action, player_id, game_state)
        elif action_type == ActionType.JOIN_CITY:
            result = self._validate_join_city(action, player_id, game_state)
        elif action_type == ActionType.CITY_CHANGE_SPECIALIST:
            result = self._validate_city_change_specialist(action, player_id, game_state)
        elif action_type == ActionType.CITY_SELL_IMPROVEMENT:
            result = self._validate_city_sell_improvement(action, player_id, game_state)
        elif action_type == ActionType.CULTIVATE:
            result = self._validate_cultivate(action, player_id, game_state)
        elif action_type == ActionType.PLANT:
            result = self._validate_plant(action, player_id, game_state)
        elif action_type == ActionType.BASE:
            result = self._validate_base(action, player_id, game_state)
        elif action_type == ActionType.UNIT_EXPLORE:
            result = self._validate_unit_explore(action, player_id, game_state)
        elif action_type == ActionType.CITY_BUILD_UNIT:
            result = self._validate_city_build_unit(action, player_id, game_state)
        elif action_type == ActionType.CITY_BUILD_IMPROVEMENT:
            result = self._validate_city_build_improvement(action, player_id, game_state)
        elif action_type == ActionType.DIPLOMACY_MESSAGE:
            result = self._validate_diplomacy_message(action, player_id, game_state)
        elif action_type == ActionType.HELP_WONDER:
            result = self._validate_help_wonder(action, player_id, game_state)
        elif action_type == ActionType.CONQUER_CITY:
            result = self._validate_conquer_city(action, player_id, game_state)
        elif action_type == ActionType.CAPTURE_UNITS:
            result = self._validate_capture_units(action, player_id, game_state)
        elif action_type == ActionType.STEAL_MAPS:
            result = self._validate_steal_maps(action, player_id, game_state)
        elif action_type == ActionType.CONVERT:
            result = self._validate_convert(action, player_id, game_state)
        elif action_type == ActionType.HOME_CITY:
            result = self._validate_home_city(action, player_id, game_state)
        elif action_type == ActionType.STRIKE_BUILDING:
            result = self._validate_strike_building(action, player_id, game_state)
        elif action_type == ActionType.STRIKE_PRODUCTION:
            result = self._validate_strike_production(action, player_id, game_state)
        elif action_type == ActionType.MARKETPLACE:
            result = self._validate_marketplace(action, player_id, game_state)
        elif action_type == ActionType.EXPEL_UNIT:
            result = self._validate_expel_unit(action, player_id, game_state)
        elif action_type == ActionType.SPY_SABOTAGE_UNIT:
            result = self._validate_spy_sabotage_unit(action, player_id, game_state)
        elif action_type == ActionType.PLAYER_RATES:
            result = self._validate_player_rates(action, player_id, game_state)
        else:
            # Default validation for other action types
            result = self._validate_basic_action(action, player_id, game_state)

        # Update statistics (simplified type-safe increments)
        if result.is_valid:
            _va = self.validation_stats.get('valid_actions')
            if not isinstance(_va, int):
                _va = 0
            self.validation_stats['valid_actions'] = _va + 1
        else:
            _ia = self.validation_stats.get('invalid_actions')
            if not isinstance(_ia, int):
                _ia = 0
            self.validation_stats['invalid_actions'] = _ia + 1
            error_type = result.error_code or 'unknown'
            _errors = self.validation_stats.get('errors_by_type')
            if not isinstance(_errors, dict):
                _errors = {}
            _count = _errors.get(error_type)
            if not isinstance(_count, int):
                _count = 0
            _errors[error_type] = _count + 1
            self.validation_stats['errors_by_type'] = _errors

        return result

    def _validate_unit_attack(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit attack action"""
        # Required fields
        required_fields = ['attacker_unit_id', 'target_unit_id']
        for field in required_fields:
            if field not in action:
                return self._validation_error('E109', f'Attack requires {field}')

        attacker_id = action['attacker_unit_id']
        target_id = action['target_unit_id']

        # Validate attacker and target exist and ownership
        attacker = None
        target = None
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict):
                    if unit.get('id') == attacker_id:
                        attacker = unit
                    if unit.get('id') == target_id:
                        target = unit
            if not attacker:
                return self._validation_error('E109', f'Attacker unit {attacker_id} not found')
            if not target:
                return self._validation_error('E115', f'Target unit {target_id} not found')
            if attacker.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own attacker unit')
            if target.get('owner') == player_id:
                return self._validation_error('E115', 'Cannot attack own unit')

        # Check if attacker is busy
        if attacker and attacker.get('busy', False):
            return self._validation_error('E110', 'Attacker unit is busy')

        # Check movement points (assume 'moves_left' field)
        if attacker and attacker.get('moves_left', 0) <= 0:
            return self._validation_error('E111', 'Attacker has no movement points left')

        # Check attacker has attack capability (assume 'can_attack' field or fallback to type check)
        if attacker and not attacker.get('can_attack', True):
            return self._validation_error('E113', 'Attacker unit cannot attack')

        # Check action available to unit type (cross-reference server authoritative list if present)
        if game_state and 'unit_actions' in game_state:
            actions = game_state['unit_actions'].get(attacker_id, [])
            found = False
            for a in actions:
                if a.get('action_type') == 'attack' or a.get('action_id') == 45:
                    if a.get('probability', 0) > 0:
                        found = True
                        break
            if not found:
                return self._validation_error('E116', 'Attack not possible according to server')

        # Check range (assume adjacent for now, can be extended for ranged units)
        if attacker and target:
            ax, ay = attacker.get('x'), attacker.get('y')
            tx, ty = target.get('x'), target.get('y')
            if ax is not None and ay is not None and tx is not None and ty is not None:
                if abs(ax - tx) > 1 or abs(ay - ty) > 1:
                    return self._validation_error('E112', 'Target not adjacent (non-ranged attack)')

        return ValidationResult(True)

    def _validate_city_sell_improvement(self, action: Dict[str, Any], player_id: int,
                                        game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city_sell_improvement action

        Sells an existing city improvement for gold refund.
        Packet: PACKET_CITY_SELL (pid=33) with fields {city_id, build_id}.

        Error Codes:
            E142: Missing required fields (city_id AND one of improvement_id/improvement_name)
            E143: City not found / not owned by player
            E144: Improvement not present / unsellable / already sold this turn

        Accepted input forms:
            { 'type': 'city_sell_improvement', 'city_id': int, 'improvement_id': int }
            { 'type': 'city_sell_improvement', 'city_id': int, 'improvement_name': str }

        Validation Strategy:
            - Optimistic pass if no game_state (defer to server)
            - Map improvement_name -> improvement_id if possible using game_state['improvements'] or
              ruleset mapping in game_state['ruleset']['improvements'].
            - Ensure city ownership and improvement present.
            - Prevent selling more than once per turn via city['did_sell'] flag if provided.
        """
        if 'city_id' not in action or ('improvement_id' not in action and 'improvement_name' not in action):
            return self._validation_error('E142', 'city_sell_improvement requires city_id and improvement_id or improvement_name')

        city_id = action['city_id']
        improvement_id = action.get('improvement_id')
        improvement_name = action.get('improvement_name')

        # Optimistic pass if no game state
        if not game_state:
            return ValidationResult(True)

        # Locate city
        cities_collection = game_state.get('cities') or {}
        cities_iter = cities_collection.values() if isinstance(cities_collection, dict) else cities_collection
        city: Optional[Dict[str, Any]] = None
        for c in cities_iter:
            if isinstance(c, dict) and c.get('id') == city_id:
                city = c
                break
        if not city:
            return self._validation_error('E143', f'City {city_id} not found')
        if city.get('owner') != player_id:
            return self._validation_error('E143', f'Player does not own city {city_id}')

        # Prevent double sell in same turn
        if city.get('did_sell') is True:
            return self._validation_error('E144', f'City {city_id} already sold an improvement this turn')

        # Resolve improvement id via name if needed
        improvements_map = game_state.get('improvements') or game_state.get('ruleset', {}).get('improvements') or {}
        if improvement_id is None and improvement_name:
            name_lower = str(improvement_name).strip().lower()
            if isinstance(improvements_map, dict):
                for imp_key, imp_val in improvements_map.items():
                    if isinstance(imp_val, dict) and str(imp_val.get('name', '')).lower() == name_lower:
                        improvement_id = imp_val.get('id', imp_key)
                        break
            if improvement_id is None:
                return self._validation_error('E144', f'Improvement name not recognized: {improvement_name}')

        # Gather improvements present in city
        city_improvements = city.get('improvements') or city.get('buildings') or []
        present_ids = set()
        if isinstance(city_improvements, list):
            for val in city_improvements:
                if isinstance(val, dict):
                    present_ids.add(val.get('id'))
                else:
                    present_ids.add(val)
        elif isinstance(city_improvements, dict):
            for k, v in city_improvements.items():
                if isinstance(v, dict):
                    present_ids.add(v.get('id', k))
                else:
                    present_ids.add(k)

        if improvement_id not in present_ids:
            return self._validation_error('E144', f'Improvement id {improvement_id} not present in city {city_id}')

        # Unsellable flag check (optional ruleset metadata)
        if isinstance(improvements_map, dict):
            imp_obj = improvements_map.get(improvement_id) or improvements_map.get(str(improvement_id))
            if isinstance(imp_obj, dict) and imp_obj.get('unsellable') is True:
                return self._validation_error('E144', f'Improvement {improvement_id} is unsellable')

        return ValidationResult(True)

    def _validate_cultivate(self, action: Dict[str, Any], player_id: int,
                           game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate cultivate action

        Cultivates tile to change terrain type (e.g., forest to plains).
        Uses PACKET_UNIT_CHANGE_ACTIVITY (pid=222) with activity=ACTIVITY_CULTIVATE (15).

        Error Codes:
            E145: Missing required fields (unit_id)
            E146: Unit not found / not owned by player
            E147: Unit busy / insufficient moves / cannot cultivate

        Accepted input:
            { 'type': 'cultivate', 'unit_id': int }

        Validation Strategy:
            - Optimistic pass if no game_state
            - Check unit ownership and existence
            - Verify unit not busy with another activity
            - Verify unit has moves remaining (cultivate requires work turns)
        """
        if 'unit_id' not in action:
            return self._validation_error('E145', 'cultivate requires unit_id field')

        unit_id = action['unit_id']

        # Optimistic pass if no game state
        if not game_state:
            return ValidationResult(True)

        # Find unit
        units_collection = game_state.get('units') or {}
        units_iter = units_collection.values() if isinstance(units_collection, dict) else units_collection
        unit: Optional[Dict[str, Any]] = None
        for u in units_iter:
            if isinstance(u, dict) and u.get('id') == unit_id:
                unit = u
                break

        if not unit:
            return self._validation_error('E145', f'Unit {unit_id} not found')
        if unit.get('owner') != player_id:
            return self._validation_error('E146', f'Player does not own unit {unit_id}')

        # Check if unit is busy
        from fc_constants import BUSY_ACTIVITIES
        activity = unit.get('activity', 0)
        if activity in BUSY_ACTIVITIES:
            return self._validation_error('E147', f'Unit {unit_id} is busy with activity {activity}')

        # Check moves remaining (cultivate takes multiple turns)
        moves_left = unit.get('moves_left', 0)
        if moves_left <= 0:
            return self._validation_error('E147', f'Unit {unit_id} has no moves left')

        return ValidationResult(True)

    def _validate_plant(self, action: Dict[str, Any], player_id: int,
                       game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate plant action

        Plants vegetation on tile to change terrain type (e.g., plains to forest).
        Uses PACKET_UNIT_CHANGE_ACTIVITY (pid=222) with activity=ACTIVITY_PLANT (16).

        Error Codes:
            E148: Missing required fields (unit_id)
            E149: Unit not found / not owned by player
            E150: Unit busy / insufficient moves / cannot plant

        Accepted input:
            { 'type': 'plant', 'unit_id': int }

        Validation Strategy:
            - Optimistic pass if no game_state
            - Check unit ownership and existence
            - Verify unit not busy with another activity
            - Verify unit has moves remaining (plant requires work turns)
        """
        if 'unit_id' not in action:
            return self._validation_error('E148', 'plant requires unit_id field')

        unit_id = action['unit_id']

        # Optimistic pass if no game state
        if not game_state:
            return ValidationResult(True)

        # Find unit
        units_collection = game_state.get('units') or {}
        units_iter = units_collection.values() if isinstance(units_collection, dict) else units_collection
        unit: Optional[Dict[str, Any]] = None
        for u in units_iter:
            if isinstance(u, dict) and u.get('id') == unit_id:
                unit = u
                break

        if not unit:
            return self._validation_error('E148', f'Unit {unit_id} not found')
        if unit.get('owner') != player_id:
            return self._validation_error('E149', f'Player does not own unit {unit_id}')

        # Check if unit is busy
        from fc_constants import BUSY_ACTIVITIES
        activity = unit.get('activity', 0)
        if activity in BUSY_ACTIVITIES:
            return self._validation_error('E150', f'Unit {unit_id} is busy with activity {activity}')

        # Check moves remaining (plant takes multiple turns)
        moves_left = unit.get('moves_left', 0)
        if moves_left <= 0:
            return self._validation_error('E150', f'Unit {unit_id} has no moves left')

        return ValidationResult(True)

    def _validate_base(self, action: Dict[str, Any], player_id: int,
                      game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate base action

        Builds a base (fortress/airbase) on tile.
        Uses PACKET_UNIT_CHANGE_ACTIVITY (pid=222) with activity=ACTIVITY_BASE (12).

        Error Codes:
            E151: Missing required fields (unit_id)
            E152: Unit not found / not owned by player
            E153: Unit busy / insufficient moves / cannot build base

        Accepted input:
            { 'type': 'base', 'unit_id': int }

        Validation Strategy:
            - Optimistic pass if no game_state
            - Check unit ownership and existence
            - Verify unit not busy with another activity
            - Verify unit has moves remaining (base building requires work turns)
        """
        if 'unit_id' not in action:
            return self._validation_error('E151', 'base requires unit_id field')

        unit_id = action['unit_id']

        # Optimistic pass if no game state
        if not game_state:
            return ValidationResult(True)

        # Find unit
        units_collection = game_state.get('units') or {}
        units_iter = units_collection.values() if isinstance(units_collection, dict) else units_collection
        unit: Optional[Dict[str, Any]] = None
        for u in units_iter:
            if isinstance(u, dict) and u.get('id') == unit_id:
                unit = u
                break

        if not unit:
            return self._validation_error('E151', f'Unit {unit_id} not found')
        if unit.get('owner') != player_id:
            return self._validation_error('E152', f'Player does not own unit {unit_id}')

        # Check if unit is busy
        if unit.get('busy', False):
            return self._validation_error('E153', f'Unit {unit_id} is busy')
        
        # Check if unit is busy with activity
        from fc_constants import BUSY_ACTIVITIES
        activity = unit.get('activity', 0)
        if activity in BUSY_ACTIVITIES:
            return self._validation_error('E153', f'Unit {unit_id} is busy with activity {activity}')

        # Check moves remaining (base building takes multiple turns)
        moves_left = unit.get('moves_left', 0)
        if moves_left <= 0:
            return self._validation_error('E153', f'Unit {unit_id} has no moves left')

        return ValidationResult(True)

    def _validate_player_ready(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate player_ready action"""
        # Error codes:
        # E300: Not in correct phase
        # E301: Player already marked ready (idempotent)
        # E302: Not enough players to start
        # E303: Player not found in game state
        # E304: Unknown error

        # Check phase (must be nations_selecting or ready_to_start)
        if game_state:
            phase = game_state.get('game_phase')
            if phase not in ('nations_selecting', 'ready_to_start'):
                return self._validation_error('E300', f'Cannot ready up in phase: {phase}')

            # Check player exists
            players = game_state.get('players', {})
            player = players.get(str(player_id)) or players.get(player_id)
            if not player:
                return self._validation_error('E303', f'Player {player_id} not found in game state')

            # Check already ready (idempotent)
            if player.get('ready') or player.get('marked_ready'):
                return ValidationResult(True, 'E301', 'Player already marked ready (idempotent)')

            # Check min players
            min_players = game_state.get('min_players', 2)
            if len(players) < min_players:
                return self._validation_error('E302', f'Not enough players to start: {len(players)}/{min_players}')

        return ValidationResult(True)

    def _validate_city_buy(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city_buy action"""
        # Error codes:
        # E201: Insufficient gold
        # E202: Invalid city or city not found
        # E203: Production queue empty or nothing to buy
        # E204: Purchase unavailable

        # Required fields
        if 'city_id' not in action:
            return self._validation_error('E202', 'city_buy requires city_id field')

        city_id = action['city_id']

        # Validate city exists and ownership
        if game_state and 'cities' in game_state:
            cities = game_state['cities'].values() if isinstance(game_state['cities'], dict) else game_state['cities']
            city = None
            for c in cities:
                if isinstance(c, dict) and c.get('id') == city_id:
                    city = c
                    break

            if not city:
                return self._validation_error('E202', f'City {city_id} not found')

            if city.get('owner') != player_id:
                return self._validation_error('E202', f'Player does not own city {city_id}')

            # Check city has production to buy
            production = city.get('production')
            if not production or production.get('name') in (None, '', 'None'):
                return self._validation_error('E203', 'City has no production to buy')

            # Check player has enough gold
            if 'players' in game_state:
                players = game_state['players'].values() if isinstance(game_state['players'], dict) else game_state['players']
                player = None
                for p in players:
                    if isinstance(p, dict) and p.get('id') == player_id:
                        player = p
                        break

                if player:
                    gold = player.get('gold', 0)
                    buy_cost = city.get('buy_cost') or production.get('buy_cost', 0)
                    if buy_cost > 0 and gold < buy_cost:
                        return self._validation_error('E201', f'Insufficient gold: need {buy_cost}, have {gold}')

            # Check if purchase is available (some cities may not allow buying)
            if city.get('can_buy') is False:
                return self._validation_error('E204', 'Purchase unavailable for this city')

        return ValidationResult(True)

    def _validate_upgrade_unit(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate upgrade_unit action"""
        # Error codes:
        # E109: Unit not found
        # E116: Action not possible per server
        # E205: Upgrade unavailable (no upgrade path)
        # E206: Insufficient gold for upgrade

        # Required fields
        if 'unit_id' not in action:
            return self._validation_error('E109', 'upgrade_unit requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit exists and ownership
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit = None
            for u in units:
                if isinstance(u, dict) and u.get('id') == unit_id:
                    unit = u
                    break

            if not unit:
                return self._validation_error('E109', f'Unit {unit_id} not found')

            if unit.get('owner') != player_id:
                return self._validation_error('E109', 'Player does not own this unit')

            # Check if upgrade action is available from server
            if 'unit_actions' in game_state:
                actions = game_state['unit_actions'].get(unit_id, [])
                upgrade_available = False
                upgrade_cost = 0
                for a in actions:
                    if a.get('action_type') == 'upgrade' or a.get('action_id') == 42:  # ACTION_UPGRADE_UNIT
                        if a.get('probability', 0) > 0:
                            upgrade_available = True
                            upgrade_cost = a.get('cost', 0)
                            break

                if not upgrade_available:
                    return self._validation_error('E205', 'No upgrade path available for this unit')

                # Check player has enough gold for upgrade
                if upgrade_cost > 0 and 'players' in game_state:
                    players = game_state['players'].values() if isinstance(game_state['players'], dict) else game_state['players']
                    player = None
                    for p in players:
                        if isinstance(p, dict) and p.get('id') == player_id:
                            player = p
                            break

                    if player:
                        gold = player.get('gold', 0)
                        if gold < upgrade_cost:
                            return self._validation_error('E206', f'Insufficient gold for upgrade: need {upgrade_cost}, have {gold}')

        return ValidationResult(True)

    def _validate_bombard(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate bombard action"""
        # Error codes: Reuse tactical range E109-E116
        # E109: Unit not found
        # E110: Unit busy
        # E111: Insufficient movement/attacks
        # E112: Target out of range
        # E113: Unit lacks capability
        # E114: (reserved)
        # E115: Invalid target
        # E116: Action not possible per server

        # Required fields
        required_fields = ['unit_id', 'target_tile_id']
        for field in required_fields:
            if field not in action:
                return self._validation_error('E109', f'Bombard requires {field}')

        unit_id = action['unit_id']
        target_tile_id = action['target_tile_id']

        # Validate unit exists and ownership
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit = None
            for u in units:
                if isinstance(u, dict) and u.get('id') == unit_id:
                    unit = u
                    break

            if not unit:
                return self._validation_error('E109', f'Unit {unit_id} not found')

            if unit.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own this unit')

            # Check if unit is busy
            if unit.get('busy', False):
                return self._validation_error('E110', 'Unit is busy')

            # Check if unit has bombard capability
            if not unit.get('can_bombard', True):  # Default to True if not specified
                return self._validation_error('E113', 'Unit cannot bombard')

            # Check movement/attack points
            if unit.get('moves_left', 0) <= 0 and unit.get('attacks_left', 1) <= 0:
                return self._validation_error('E111', 'Unit has no attacks or movement left')

            # Check if bombard action is available from server
            if 'unit_actions' in game_state:
                actions = game_state['unit_actions'].get(unit_id, [])
                bombard_available = False
                for a in actions:
                    # ACTION_BOMBARD = 53, and variants 54, 55, 56
                    if a.get('action_type') == 'bombard' or a.get('action_id') in (53, 54, 55, 56):
                        if a.get('probability', 0) > 0:
                            bombard_available = True
                            break

                if not bombard_available:
                    return self._validation_error('E116', 'Bombard not possible according to server')

            # Check range (if we have position data)
            unit_tile = unit.get('tile')
            if unit_tile is not None:
                # Calculate range based on unit type or default
                bombard_range = unit.get('bombard_range', 2)  # Default range
                # Simple tile distance check (would need proper map distance calculation)
                # For now, just validate that target is different from unit position
                if unit_tile == target_tile_id:
                    return self._validation_error('E115', 'Cannot bombard own tile')

        return ValidationResult(True)

    def _validate_pillage(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate pillage action"""
        # Error codes: Reuse tactical range E109-E116
        # E109: Unit not found
        # E110: Unit busy
        # E111: Insufficient movement
        # E112: (not used for pillage)
        # E113: Unit lacks capability
        # E114: (reserved)
        # E115: No improvements to pillage
        # E116: Action not possible per server

        # Required fields
        if 'unit_id' not in action:
            return self._validation_error('E109', 'pillage requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit exists and ownership
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit = None
            for u in units:
                if isinstance(u, dict) and u.get('id') == unit_id:
                    unit = u
                    break

            if not unit:
                return self._validation_error('E109', f'Unit {unit_id} not found')

            if unit.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own this unit')

            # Check if unit is busy
            if unit.get('busy', False):
                return self._validation_error('E110', 'Unit is busy')

            # Check if unit has pillage capability (most units can pillage)
            if unit.get('can_pillage') is False:
                return self._validation_error('E113', 'Unit cannot pillage')

            # Check movement points
            if unit.get('moves_left', 0) <= 0:
                return self._validation_error('E111', 'Unit has no movement points left')

            # Check if pillage action is available from server
            # Server should indicate if tile has improvements to pillage
            if 'unit_actions' in game_state:
                actions = game_state['unit_actions'].get(unit_id, [])
                pillage_available = False
                for a in actions:
                    # Check for pillage-related actions
                    if a.get('action_type') == 'pillage' or 'pillage' in str(a.get('name', '')).lower():
                        if a.get('probability', 0) > 0:
                            pillage_available = True
                            break

                if not pillage_available:
                    # Check if tile info indicates no improvements
                    unit_tile = unit.get('tile')
                    if unit_tile is not None and 'tiles' in game_state:
                        tiles = game_state['tiles']
                        tile_info = tiles.get(unit_tile, {})
                        if not tile_info.get('has_improvements', True):  # Default to True
                            return self._validation_error('E115', 'No improvements to pillage on this tile')
                    return self._validation_error('E116', 'Pillage not possible according to server')

        return ValidationResult(True)

    def _validate_transport_board(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate transport board action"""
        # Use tactical error range to align with tests
        # E109: Missing unit_id / actor or unit not found
        # E110: Unit busy
        # E111: No movement
        # E113: Ownership/capability issues
        # E115: Missing/invalid target (transport_id missing/not found)
        # E116: Not possible per server

        # Required fields
        if 'unit_id' not in action:
            return self._validation_error('E109', 'transport_board requires unit_id field')
        if 'transport_id' not in action:
            return self._validation_error('E115', 'transport_board requires transport_id field')

        unit_id = action['unit_id']
        transport_id = action['transport_id']

        # Validate units exist and ownership
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit = None
            transport = None
            for u in units:
                if isinstance(u, dict):
                    if u.get('id') == unit_id:
                        unit = u
                    if u.get('id') == transport_id:
                        transport = u

            if not unit:
                return self._validation_error('E109', f'Unit {unit_id} not found')
            if not transport:
                return self._validation_error('E115', f'Transport {transport_id} not found')

            if unit.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own cargo unit')
            if transport.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own transport')

            # Check if unit is busy
            if unit.get('busy', False):
                return self._validation_error('E110', 'Unit is busy')

            # Check movement points
            if unit.get('moves_left', 0) <= 0:
                return self._validation_error('E111', 'Unit has no movement points left')
            
            # Check if transport has capacity
            transport_capacity = transport.get('transport_capacity', 2)
            current_passengers = transport.get('passengers', [])
            if len(current_passengers) >= transport_capacity:
                return self._validation_error('E353', 'Transport is at full capacity')

            # Check if board action is available from server (server validates capacity, compatibility, terrain)
            if 'unit_actions' in game_state:
                actions = game_state['unit_actions'].get(unit_id, [])
                board_available = False
                for a in actions:
                    # Check for board/embark actions (ACTION_TRANSPORT_BOARD=68, ACTION_TRANSPORT_EMBARK=72)
                    action_type = a.get('action_type', '')
                    action_id = a.get('action_id', -1)
                    if 'board' in action_type.lower() or 'embark' in action_type.lower() or action_id in (68, 69, 70, 72, 73, 74, 75):
                        if a.get('probability', 0) > 0:
                            # Check if target matches our transport
                            target = a.get('target_unit_id', a.get('target_id'))
                            if target is None or target == transport_id:
                                board_available = True
                                break

                if not board_available:
                    return self._validation_error('E116', 'Board transport not possible according to server')

        return ValidationResult(True)

    def _validate_transport_deboard(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate transport deboard action"""
        # Tactical error codes alignment
        # E109 missing unit_id / not found, E113 ownership, E353 not on transport, E116 not possible

        # Required fields
        if 'unit_id' not in action:
            return self._validation_error('E109', 'transport_deboard requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit exists and ownership
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit = None
            for u in units:
                if isinstance(u, dict) and u.get('id') == unit_id:
                    unit = u
                    break

            if not unit:
                return self._validation_error('E109', f'Unit {unit_id} not found')

            if unit.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own this unit')

            # Check if unit is on a transport (optimistically pass if no transported field)
            if 'transported' in unit and not unit.get('transported', False):
                return self._validation_error('E353', 'Unit is not on a transport')

            # Check if deboard action is available from server (server validates terrain suitability)
            if 'unit_actions' in game_state:
                actions = game_state['unit_actions'].get(unit_id, [])
                deboard_available = False
                for a in actions:
                    # Check for deboard/disembark actions (ACTION_TRANSPORT_DEBOARD=71, ACTION_TRANSPORT_DISEMBARK=76-79)
                    action_type = a.get('action_type', '')
                    action_id = a.get('action_id', -1)
                    if 'deboard' in action_type.lower() or 'disembark' in action_type.lower() or action_id in (71, 76, 77, 78, 79):
                        if a.get('probability', 0) > 0:
                            deboard_available = True
                            break

                if not deboard_available:
                    return self._validation_error('E116', 'Deboard not possible according to server')

        return ValidationResult(True)

    def _validate_transport_unload(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate transport unload action"""
        # Tactical error codes alignment
        # Expected by tests: unit_id = transport (actor), cargo_id = cargo (target)
        # E109: missing/invalid actor (unit_id)
        # E115: missing/invalid target (cargo_id)
        # E113: ownership, E353: not on transport, E116: not possible

        # Required fields (test contract)
        if 'unit_id' not in action:
            return self._validation_error('E109', 'transport_unload requires unit_id (transport) field')
        if 'cargo_id' not in action:
            return self._validation_error('E115', 'transport_unload requires cargo_id field')

        transport_id = action['unit_id']   # Transport unit (actor)
        cargo_id = action['cargo_id']      # Cargo to unload (target)

        # Validate units exist and ownership
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            transport = None
            cargo = None
            for u in units:
                if isinstance(u, dict):
                    if u.get('id') == transport_id:
                        transport = u
                    if u.get('id') == cargo_id:
                        cargo = u

            if not transport:
                return self._validation_error('E109', f'Transport {transport_id} not found')
            if not cargo:
                return self._validation_error('E115', f'Cargo unit {cargo_id} not found')

            if transport.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own transport')
            if cargo.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own cargo unit')

            # Check if cargo is on this transport
            # Check both: cargo's transported_by field AND transport's passengers list
            cargo_on_transport = False
            if cargo.get('transported', False) and cargo.get('transported_by') == transport_id:
                cargo_on_transport = True
            # Also check if transport has passengers list including this cargo
            if transport.get('passengers') and cargo_id in transport.get('passengers', []):
                cargo_on_transport = True
            
            if not cargo_on_transport:
                return self._validation_error('E353', 'Cargo is not on this transport')

            # Check if unload action is available from server
            if 'unit_actions' in game_state:
                actions = game_state['unit_actions'].get(transport_id, [])
                unload_available = False
                for a in actions:
                    # Check for unload/load actions (ACTION_TRANSPORT_UNLOAD=83, ACTION_TRANSPORT_LOAD=80-82)
                    action_type = a.get('action_type', '')
                    action_id = a.get('action_id', -1)
                    if 'unload' in action_type.lower() or action_id in (80, 81, 82, 83):
                        if a.get('probability', 0) > 0:
                            # Check if target matches our cargo
                            target = a.get('target_unit_id', a.get('target_id'))
                            if target is None or target == cargo_id:
                                unload_available = True
                                break

                if not unload_available:
                    return self._validation_error('E116', 'Unload not possible according to server')

        return ValidationResult(True)

    def _validate_airlift(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate airlift action"""
        # Align with tactical error codes expected by tests
        # E109 missing unit_id / not found, E113 not owner, E115 target city issues, E116 not possible

        # Required fields
        if 'unit_id' not in action:
            return self._validation_error('E109', 'airlift requires unit_id field')
        # Accept either target_city_id or dest_city_id
        if 'target_city_id' not in action and 'dest_city_id' not in action:
            return self._validation_error('E115', 'airlift requires target_city_id or dest_city_id field')

        unit_id = action['unit_id']
        target_city_id = action.get('target_city_id') or action.get('dest_city_id')

        # Validate unit exists and ownership
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit = None
            for u in units:
                if isinstance(u, dict) and u.get('id') == unit_id:
                    unit = u
                    break

            if not unit:
                return self._validation_error('E109', f'Unit {unit_id} not found')

            if unit.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own this unit')
            
            # Check if target city exists
            if 'cities' in game_state:
                cities = game_state['cities'].values() if isinstance(game_state['cities'], dict) else game_state['cities']
                target_city_found = False
                for city in cities:
                    if isinstance(city, dict) and city.get('id') == target_city_id:
                        target_city_found = True
                        break
                if not target_city_found:
                    return self._validation_error('E115', f'Target city {target_city_id} not found')
            
            # Optimistically pass if no detailed validation data
            if 'unit_actions' not in game_state:
                return ValidationResult(True)

            # Check if airlift action is available from server
            # Server validates: airport at origin, airport at target, tech requirements, capacity
            if 'unit_actions' in game_state:
                actions = game_state['unit_actions'].get(unit_id, [])
                airlift_available = False
                for a in actions:
                    # Check for airlift action (ACTION_AIRLIFT=44)
                    action_type = a.get('action_type', '')
                    action_id = a.get('action_id', -1)
                    if 'airlift' in action_type.lower() or action_id == 44:
                        if a.get('probability', 0) > 0:
                            # Check if target matches
                            target = a.get('target_city_id', a.get('target_id'))
                            if target is None or target == target_city_id:
                                airlift_available = True
                                break

                if not airlift_available:
                    return self._validation_error('E116', 'Airlift not possible according to server')

        return ValidationResult(True)

    def _validate_establish_embassy(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate establish embassy action"""
        # Error codes: E109-E116 (tactical), E310-E312 (diplomacy)
        # E109: Unit not found
        # E113: Not owner or lacks capability
        # E115: Target not found
        # E116: Action not possible per server
        # E310: Embassy already exists
        # E311: Insufficient gold
        # E312: Invalid diplomat/spy unit

        # Required fields
        if 'unit_id' not in action:
            return self._validation_error('E109', 'establish_embassy requires unit_id field')
        if 'target_city_id' not in action:
            return self._validation_error('E115', 'establish_embassy requires target_city_id field')

        unit_id = action['unit_id']
        target_city_id = action['target_city_id']

        # Validate unit exists and ownership
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit = None
            for u in units:
                if isinstance(u, dict) and u.get('id') == unit_id:
                    unit = u
                    break

            if not unit:
                return self._validation_error('E109', f'Unit {unit_id} not found')

            if unit.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own this unit')

            # Check if unit is a diplomat or spy
            unit_type = unit.get('type', '').lower()
            if 'diplomat' not in unit_type and 'spy' not in unit_type:
                if not unit.get('can_establish_embassy', False):
                    return self._validation_error('E312', 'Unit cannot establish embassies')

            # Check if establish_embassy action is available from server
            # Server validates: embassy doesn't exist, sufficient gold, diplomatic relations
            if 'unit_actions' in game_state:
                actions = game_state['unit_actions'].get(unit_id, [])
                embassy_available = False
                for a in actions:
                    # Check for embassy action (ACTION_ESTABLISH_EMBASSY=0)
                    action_type = a.get('action_type', '')
                    action_id = a.get('action_id', -1)
                    if 'embassy' in action_type.lower() or action_id in (0, 1):
                        if a.get('probability', 0) > 0:
                            # Check if target matches
                            target = a.get('target_city_id', a.get('target_id'))
                            if target is None or target == target_city_id:
                                embassy_available = True
                                break

                if not embassy_available:
                    return self._validation_error('E116', 'Establish embassy not possible according to server')

        return ValidationResult(True)

    def _validate_spy_action(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate spy / espionage actions

        Supports: investigate_city, poison, sabotage_city, steal_tech, bribe_unit, steal_gold, incite_city
        Error codes:
        E109: Missing unit_id or unit not found
        E110: Unit busy
        E111: No movement points
        E113: Ownership mismatch (player does not own unit)
        E115: Missing/invalid target (city/unit) or own target
        E116: Action not possible per server
        E400: Mission would be detected (pre-emptive)
        E401: Mission would fail (pre-emptive)
        E402: Invalid spy/diplomat unit type
        E403: Insufficient gold for bribe/incite
        """
        if 'unit_id' not in action:
            return self._validation_error('E109', 'Spy action requires unit_id field')

        unit_id = action['unit_id']
        action_type = action.get('type')

        # Determine required target field(s)
        requires_city = action_type in ('spy_investigate_city', 'spy_poison', 'spy_sabotage_city', 'spy_steal_tech', 'spy_steal_gold', 'spy_incite_city')
        requires_unit = action_type == 'spy_bribe_unit'

        if requires_city and 'target_city_id' not in action:
            return self._validation_error('E115', f'{action_type} requires target_city_id field')
        if requires_unit and 'target_unit_id' not in action:
            return self._validation_error('E115', f'{action_type} requires target_unit_id field')

        target_city_id = action.get('target_city_id')
        target_unit_id = action.get('target_unit_id')

        unit = None
        target_unit = None
        target_city = None

        if game_state and 'units' in game_state:
            units_iter = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for u in units_iter:
                if isinstance(u, dict):
                    if u.get('id') == unit_id:
                        unit = u
                    if requires_unit and target_unit_id is not None and u.get('id') == target_unit_id:
                        target_unit = u
            if not unit:
                return self._validation_error('E109', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E113', 'Player does not own spy unit')
            if unit.get('busy', False):
                return self._validation_error('E110', 'Spy unit is busy')
            if unit.get('moves_left', 0) <= 0:
                return self._validation_error('E111', 'Spy unit has no movement points left')

            # Validate unit type (diplomat or spy). Allow explicit capability flag for flexibility
            utype = str(unit.get('type', '')).lower()
            if 'diplomat' not in utype and 'spy' not in utype and not unit.get('can_spy', False):
                return self._validation_error('E402', 'Unit is not a diplomat or spy')

        if requires_unit:
            if not target_unit:
                return self._validation_error('E115', f'Target unit {target_unit_id} not found')
            if target_unit.get('owner') == player_id:
                return self._validation_error('E115', 'Cannot bribe own unit')

        if requires_city and game_state and 'cities' in game_state:
            cities_iter = game_state['cities'].values() if isinstance(game_state['cities'], dict) else game_state['cities']
            for c in cities_iter:
                if isinstance(c, dict) and c.get('id') == target_city_id:
                    target_city = c
                    break
            if not target_city:
                return self._validation_error('E115', f'Target city {target_city_id} not found')
            if target_city.get('owner') == player_id:
                # All espionage missions target foreign cities
                return self._validation_error('E115', 'Target city must belong to another player')

        # Check server-provided action availability
        if game_state and 'unit_actions' in game_state and unit_id in game_state['unit_actions']:
            actions_list = game_state['unit_actions'].get(unit_id, [])
            spy_available = False
            selected_action: Optional[Dict[str, Any]] = None
            for a in actions_list:
                a_type = str(a.get('action_type', '')).lower()
                a_id = a.get('action_id', -1)
                # Map action ids from fc_constants
                matches_type = False
                if action_type == 'spy_investigate_city' and (a_type.startswith('investigate') or a_id == 2):
                    matches_type = True
                elif action_type == 'spy_poison' and ('poison' in a_type or a_id == 4):
                    matches_type = True
                elif action_type == 'spy_sabotage_city' and ('sabotage' in a_type or a_id == 8):
                    matches_type = True
                elif action_type == 'spy_steal_tech' and ('steal' in a_type or 'tech' in a_type or a_id == 14):
                    matches_type = True
                elif action_type == 'spy_bribe_unit' and ('bribe' in a_type or a_id == 23):
                    matches_type = True
                elif action_type == 'spy_steal_gold' and ('steal' in a_type or 'gold' in a_type or a_id == 6):
                    matches_type = True
                elif action_type == 'spy_incite_city' and ('incite' in a_type or a_id == 18):
                    matches_type = True

                if matches_type and a.get('probability', 0) > 0:
                    # Target matching (if server supplies target IDs, ensure alignment)
                    target_match = True
                    if requires_city:
                        target_match = (a.get('target_city_id') in (None, target_city_id, 'unknown'))
                    if requires_unit:
                        target_match = (a.get('target_unit_id', a.get('target_id')) in (None, target_unit_id))
                    if target_match:
                        spy_available = True
                        selected_action = a
                        break

            if not spy_available:
                return self._validation_error('E116', f'{action_type} not possible according to server')

            # Pre-emptive mission outcome flags (optional)
            if selected_action:
                if selected_action.get('detected') is True:
                    return self._validation_error('E400', 'Mission would be detected according to server')
                if selected_action.get('mission_failed') is True:
                    return self._validation_error('E401', 'Mission would fail according to server')

                # Bribe cost check
                if action_type == 'spy_bribe_unit':
                    bribe_cost = selected_action.get('cost', 0)
                    if bribe_cost > 0 and game_state and 'players' in game_state:
                        players_iter = game_state['players'].values() if isinstance(game_state['players'], dict) else game_state['players']
                        player_obj = None
                        for p in players_iter:
                            if isinstance(p, dict) and p.get('id') == player_id:
                                player_obj = p
                                break
                        if player_obj:
                            if player_obj.get('gold', 0) < bribe_cost:
                                return self._validation_error('E403', f'Insufficient gold for bribe: need {bribe_cost}, have {player_obj.get("gold", 0)}')

                # Incite cost check
                if action_type == 'spy_incite_city':
                    incite_cost = selected_action.get('cost', 0)
                    if incite_cost > 0 and game_state and 'players' in game_state:
                        players_iter = game_state['players'].values() if isinstance(game_state['players'], dict) else game_state['players']
                        player_obj = None
                        for p in players_iter:
                            if isinstance(p, dict) and p.get('id') == player_id:
                                player_obj = p
                                break
                        if player_obj:
                            if player_obj.get('gold', 0) < incite_cost:
                                return self._validation_error('E403', f'Insufficient gold for incite: need {incite_cost}, have {player_obj.get("gold", 0)}')

        return ValidationResult(True)

    def _validate_trade_route(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate trade_route action

        Error codes:
        E109: Unit not found
        E110: Unit busy
        E111: Insufficient movement
        E113: Ownership
        E115: Target city missing / invalid
        E116: Action not possible per server
        E410: Unit cannot create trade routes
        """
        if 'unit_id' not in action:
            return self._validation_error('E109', 'trade_route requires unit_id field')
        if 'target_city_id' not in action:
            return self._validation_error('E115', 'trade_route requires target_city_id field')

        unit_id = action['unit_id']
        target_city_id = action['target_city_id']
        unit = None
        target_city = None

        if game_state:
            # Validate unit
            if 'units' in game_state:
                units_iter = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
                for u in units_iter:
                    if isinstance(u, dict) and u.get('id') == unit_id:
                        unit = u
                        break
                if not unit:
                    return self._validation_error('E109', f'Unit {unit_id} not found')
                if unit.get('owner') != player_id:
                    return self._validation_error('E113', 'Player does not own trade unit')
                if unit.get('busy', False):
                    return self._validation_error('E110', 'Unit is busy')
                if unit.get('moves_left', 0) <= 0:
                    return self._validation_error('E111', 'Unit has no movement points left')
                utype = str(unit.get('type', '')).lower()
                if ('caravan' not in utype and 'freight' not in utype and not unit.get('can_create_trade_route', False)):
                    return self._validation_error('E410', 'Unit cannot create trade routes')

            # Validate city
            if 'cities' in game_state:
                cities_iter = game_state['cities'].values() if isinstance(game_state['cities'], dict) else game_state['cities']
                for c in cities_iter:
                    if isinstance(c, dict) and c.get('id') == target_city_id:
                        target_city = c
                        break
                if not target_city:
                    return self._validation_error('E115', f'Target city {target_city_id} not found')
                if target_city.get('owner') == player_id:
                    # Trade routes generally require foreign or at least different city; allow same owner only if explicit flag
                    if not action.get('allow_domestic', False):
                        return self._validation_error('E115', 'Target city must belong to another player for international trade')

            # Server availability
            if 'unit_actions' in game_state and unit_id in game_state['unit_actions']:
                trade_available = False
                for a in game_state['unit_actions'].get(unit_id, []):
                    a_type = str(a.get('action_type', '')).lower()
                    a_id = a.get('action_id', -1)
                    if ('trade' in a_type or 'route' in a_type or a_id == 20) and a.get('probability', 0) > 0:
                        # Optional target matching
                        target_match = a.get('target_city_id') in (None, target_city_id)
                        if target_match:
                            trade_available = True
                            break
                if not trade_available:
                    return self._validation_error('E116', 'Trade route not possible according to server')

        return ValidationResult(True)

    def _validate_unit_move(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit movement action
        
        Accepts either:
        - direction field (0-7 for 8 directions)
        - dest_x and dest_y fields (absolute coordinates)
        
        Error codes:
        - E010: Unit not found
        - E011: Player does not own unit
        - E012: Unit has no moves left
        - E013: Destination out of bounds
        - E014: Destination tile occupied (if tile validation is implemented)
        """
        if 'unit_id' not in action:
            return self._validation_error('E010', 'Unit move requires unit_id')

        unit_id = action['unit_id']
        
        # Check if we have direction OR coordinates
        has_direction = 'direction' in action
        has_coordinates = 'dest_x' in action and 'dest_y' in action
        
        if not has_direction and not has_coordinates:
            return self._validation_error('E013', 'Unit move requires either direction or dest_x/dest_y')
        
        # If we have coordinates, validate them
        if has_coordinates:
            dest_x = action['dest_x']
            dest_y = action['dest_y']
            
            # Validate coordinates are integers
            try:
                dest_x = int(dest_x)
                dest_y = int(dest_y)
            except (ValueError, TypeError):
                return self._validation_error('E013', 'Destination coordinates must be integers')

            # Enhanced coordinate validation against actual game boundaries
            if not self._validate_coordinates(dest_x, dest_y, game_state):
                return self._validation_error('E013', 'Destination coordinates out of bounds')
        
        # If game state is available, validate unit ownership and moves
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            unit_found = False
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    unit_found = True
                    if unit.get('owner') != player_id:
                        return self._validation_error('E011', 'Player does not own this unit')
                    # Check if unit is busy
                    if unit.get('busy', False):
                        return self._validation_error('E012', 'Unit is busy')
                    # Check if unit has moves left
                    if unit.get('moves_left', 0) <= 0:
                        return self._validation_error('E012', 'Unit has no moves left')
                    break

            if not unit_found:
                return self._validation_error('E010', f'Unit {unit_id} not found')
            
            # Check if destination tile is occupied (only if we have coordinates)
            if has_coordinates:
                dest_x = int(action['dest_x'])
                dest_y = int(action['dest_y'])
                for other_unit in units:
                    if isinstance(other_unit, dict) and other_unit.get('id') != unit_id:
                        if other_unit.get('x') == dest_x and other_unit.get('y') == dest_y:
                            # Tile is occupied by another unit
                            return self._validation_error('E014', 'Destination tile is occupied')

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
        """Validate city production change
        
        Error codes:
        - E030: City not found
        - E031: Player does not own city
        - E032: Invalid production type
        - E033: Missing required field
        """
        required_fields = ['city_id', 'production_type']
        for field in required_fields:
            if field not in action:
                return self._validation_error('E033', f'City production requires {field}')

        city_id = action['city_id']
        production_type = action['production_type']
        production_name = action.get('production_name', production_type)

        # Validate production name is reasonable (skip if civcom not available)
        if self.civcom is not None and production_name:
            valid_production_types: list[str] = []
            for _, prod_type in chain(
                self.civcom.unit_types.items(), self.civcom.improvements.items()
            ):
                name = prod_type.get("name", "")
                if not name:
                    continue
                clean_name = clean_production_name(name)
                valid_production_types.append(clean_name)

            production_matched = False
            for production in valid_production_types:
                if production_name.casefold() == production.casefold():
                    production_matched = True
                    break
            
            # Only fail if we have civcom data AND the name doesn't match
            if len(valid_production_types) > 0 and not production_matched:
                return self._validation_error(
                    "E032",
                    f"Invalid production name: {production_name}, should be one of {valid_production_types}",
                )

        # If game state available, verify city ownership
        if game_state and 'cities' in game_state:
            # Iterate directly over dict values (no need to create intermediate list)
            cities = game_state['cities'].values() if isinstance(game_state['cities'], dict) else game_state['cities']
            for city in cities:
                if isinstance(city, dict) and city.get('id') == city_id:
                    if city.get('owner') != player_id:
                        return self._validation_error('E031', 'Player does not own this city')
                    break
            else:
                return self._validation_error("E030", "City not found")

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

        Hybrid semantics:
        - If coordinates (x,y) are provided, validate bounds and plan movement before activity.
        - If coordinates are omitted, assume current tile.

        Error codes:
        - E070: Missing unit_id or missing one/both coordinates when coordinates are required by client
        - E071: Wrong owner
        - E072: Out-of-bounds coordinates, unit busy, or no moves left
        """
        if 'unit_id' not in action:
            return self._validation_error('E070', 'Unit build road requires unit_id field')

        unit_id = action['unit_id']

        # If client provided any coordinate, require both and validate bounds
        has_x = 'x' in action
        has_y = 'y' in action
        if has_x or has_y:
            if not (has_x and has_y):
                return self._validation_error('E070', 'Unit build road requires both x and y coordinates')
            try:
                x = int(action['x'])
                y = int(action['y'])
            except (ValueError, TypeError):
                return self._validation_error('E070', 'Coordinates must be integers')
            if not self._validate_coordinates(x, y, game_state):
                return self._validation_error('E072', 'Coordinates out of bounds')

        # Validate unit ownership if game state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E071', f'Player does not own unit {unit_id}')
                    # Check if unit is busy
                    if unit.get('busy', False):
                        return self._validation_error('E072', f'Unit {unit_id} is busy')
                    # Check if unit has moves left
                    if unit.get('moves_left', 0) <= 0:
                        return self._validation_error('E072', f'Unit {unit_id} has no moves left')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E070', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_build_irrigation(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build irrigation action (hybrid)

        Coordinates optional; if provided, require both x and y and validate bounds.

        Error codes:
        - E080: Missing unit_id or missing/invalid coordinates when provided
        - E081: Wrong owner
        - E082: Out-of-bounds coordinates or no moves left
        """
        if 'unit_id' not in action:
            return self._validation_error('E080', 'Unit build irrigation requires unit_id field')

        unit_id = action['unit_id']

        # Require coordinates for irrigation per protocol/tests
        if 'x' not in action or 'y' not in action:
            return self._validation_error('E080', 'Unit build irrigation requires both x and y coordinates')
        try:
            x = int(action['x'])
            y = int(action['y'])
        except (ValueError, TypeError):
            return self._validation_error('E080', 'Coordinates must be integers')
        if not self._validate_coordinates(x, y, game_state):
            return self._validation_error('E082', 'Coordinates out of bounds')

        # Validate unit ownership if game state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E081', f'Player does not own unit {unit_id}')
                    # Check if unit has moves left
                    if unit.get('moves_left', 0) <= 0:
                        return self._validation_error('E082', f'Unit {unit_id} has no moves left')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E080', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_build_mine(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit build mine action (hybrid)

        Coordinates optional; if provided, require both x and y and validate bounds.

        Error codes:
        - E090: Missing unit_id or missing/invalid coordinates when provided
        - E091: Wrong owner
        - E092: Out-of-bounds coordinates or no moves left
        """
        if 'unit_id' not in action:
            return self._validation_error('E090', 'Unit build mine requires unit_id field')

        unit_id = action['unit_id']

        # Require coordinates for mine per protocol/tests
        if 'x' not in action or 'y' not in action:
            return self._validation_error('E090', 'Unit build mine requires both x and y coordinates')
        try:
            x = int(action['x'])
            y = int(action['y'])
        except (ValueError, TypeError):
            return self._validation_error('E090', 'Coordinates must be integers')
        if not self._validate_coordinates(x, y, game_state):
            return self._validation_error('E092', 'Coordinates out of bounds')

        # Validate unit ownership if game_state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E091', f'Player does not own unit {unit_id}')
                    # Check if unit has moves left
                    if unit.get('moves_left', 0) <= 0:
                        return self._validation_error('E092', f'Unit {unit_id} has no moves left')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E090', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_clean_pollution(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit clean pollution action

        Validates worker/settler cleaning pollution from a tile using PACKET_UNIT_CHANGE_ACTIVITY
        with ACTIVITY_POLLUTION. The action operates on the unit's current tile.

        Error Codes:
            E100: Missing unit_id field
            E101: Player does not own unit
            E102: Unit not found

        Args:
            action: Action data with unit_id
            player_id: Player executing the action
            game_state: Current game state

        Returns:
            ValidationResult with validation status
        """
        if 'unit_id' not in action:
            return self._validation_error('E100', 'Clean pollution requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game_state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E101', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E102', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_clean_fallout(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit clean fallout action

        Validates worker/settler cleaning nuclear fallout from a tile using PACKET_UNIT_CHANGE_ACTIVITY
        with ACTIVITY_FALLOUT. The action operates on the unit's current tile.

        Error Codes:
            E103: Missing unit_id field
            E104: Player does not own unit
            E105: Unit not found

        Args:
            action: Action data with unit_id
            player_id: Player executing the action
            game_state: Current game state

        Returns:
            ValidationResult with validation status
        """
        if 'unit_id' not in action:
            return self._validation_error('E103', 'Clean fallout requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game_state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E104', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E105', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_unit_transform_terrain(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit transform terrain action

        Validates engineer/settler transforming terrain type (e.g., plains to grassland, desert to plains)
        using PACKET_UNIT_CHANGE_ACTIVITY with ACTIVITY_TRANSFORM. The action operates on the unit's
        current tile. Server determines valid transformations based on ruleset.

        Error Codes:
            E106: Missing unit_id field
            E107: Player does not own unit
            E108: Unit not found

        Args:
            action: Action data with unit_id
            player_id: Player executing the action
            game_state: Current game state

        Returns:
            ValidationResult with validation status
        """
        if 'unit_id' not in action:
            return self._validation_error('E106', 'Transform terrain requires unit_id field')

        unit_id = action['unit_id']

        # Validate unit ownership if game_state is available
        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E107', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            # Unit not found in game state
            return self._validation_error('E108', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_government_change(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate government change action

        Player attempts to change government via PACKET_PLAYER_CHANGE_GOVERNMENT (pid=54).
        Requires specifying a target government name. Validation ensures:

        Error Codes:
            E117: Missing government_name field
            E118: Invalid government name (not recognized in ruleset)
            E119: Government already active
            E120: Government recognized but not yet available (prereq unmet)
            E121: Revolution/cooldown active - cannot change now
            E122: Game state missing government data

        Expected game_state structure fragment (if available):
        {
            'player': {
                'current_government': 'despotism',
                'revolution_active': False
            },
            'available_governments': ['despotism', 'monarchy', 'republic']
        }

        Args:
            action: {'type': 'government_change', 'government_name': 'republic'}
            player_id: Player executing the action
            game_state: Optional current game state
        """
        if 'government_name' not in action:
            return self._validation_error('E117', 'Government change requires government_name field')

        gov_name = str(action['government_name']).strip().lower()
        if not gov_name:
            return self._validation_error('E117', 'government_name cannot be empty')

        # If no game state, accept optimistically (server authoritative)
        if not game_state:
            return ValidationResult(True)

        player_info = game_state.get('player') or {}
        current_gov = str(player_info.get('current_government', '')).lower()
        revolution_active = bool(player_info.get('revolution_active', False))
        available = game_state.get('available_governments') or []

        # If essential government data missing, return specific error
        if not available and not current_gov:
            return self._validation_error('E122', 'Government data unavailable in game state')

        # Normalize available governments
        normalized_available = [str(g).lower() for g in available if isinstance(g, str)]

        # Determine known governments (recognized) - use available list as proxy.
        recognized_governments = set(normalized_available) | {current_gov} if current_gov else set(normalized_available)

        if gov_name not in recognized_governments:
            return self._validation_error('E118', f'Unrecognized government: {gov_name}')

        if gov_name == current_gov:
            return self._validation_error('E119', f'Government {gov_name} already active')

        if gov_name not in normalized_available:
            return self._validation_error('E120', f'Government {gov_name} not yet available')

        if revolution_active:
            return self._validation_error('E121', 'Cannot change government during revolution cooldown')

        return ValidationResult(True)

    def _validate_disband_unit(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate disband unit action

        Simple validation prior to sending PACKET_UNIT_DO_ACTION with ACTION_DISBAND_UNIT (39).
        The server is authoritative about special constraints (e.g., cannot disband last defender
        or units with cargo). Client-side validator ensures the unit reference is structurally sound.

        Error Codes:
            E123: Missing unit_id field
            E124: Player does not own unit
            E125: Unit not found

        Args:
            action: {'type': 'disband_unit', 'unit_id': 17}
            player_id: Player executing the action
            game_state: Optional game state for ownership check
        """
        if 'unit_id' not in action:
            return self._validation_error('E123', 'Disband unit requires unit_id field')

        unit_id = action['unit_id']

        if game_state and 'units' in game_state:
            units = game_state['units'].values() if isinstance(game_state['units'], dict) else game_state['units']
            for unit in units:
                if isinstance(unit, dict) and unit.get('id') == unit_id:
                    if unit.get('owner') != player_id:
                        return self._validation_error('E124', f'Player does not own unit {unit_id}')
                    return ValidationResult(True)
            return self._validation_error('E125', f'Unit not found: {unit_id}')

        return ValidationResult(True)

    def _validate_join_city(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate join city action

        Worker/settler adds its population to a city using PACKET_UNIT_DO_ACTION with ACTION_JOIN_CITY (28).
        Server enforces deeper rules (e.g., unit type allowed, city size constraints); client checks structure.

        Error Codes:
            E126: Missing unit_id or city_id field
            E127: Player does not own unit
            E128: Unit not found
            E129: Invalid unit type (cannot join city)
            E130: City not found or not owned by player (if game_state provides cities)

        Expected fields: {'type': 'join_city', 'unit_id': int, 'city_id': int}
        """
        if 'unit_id' not in action or 'city_id' not in action:
            return self._validation_error('E126', 'Join city requires unit_id and city_id fields')

        unit_id = action['unit_id']
        city_id = action['city_id']

        unit_obj = None
        city_obj = None

        if game_state:
            # Validate unit ownership/existence
            units_collection = game_state.get('units')
            if units_collection:
                units_iter = units_collection.values() if isinstance(units_collection, dict) else units_collection
                for u in units_iter:
                    if isinstance(u, dict) and u.get('id') == unit_id:
                        unit_obj = u
                        break
            if not unit_obj:
                return self._validation_error('E128', f'Unit not found: {unit_id}')
            if unit_obj.get('owner') != player_id:
                return self._validation_error('E127', f'Player does not own unit {unit_id}')

            # Basic unit type check (assume 'type' field names workers/settlers)
            unit_type_name = str(unit_obj.get('type', '')).lower()
            if unit_type_name and not any(tok in unit_type_name for tok in ('worker', 'settler', 'engineer')):
                return self._validation_error('E129', f'Unit type {unit_type_name} cannot join city')

            # Validate city existence/ownership if cities present
            cities_collection = game_state.get('cities')
            if cities_collection:
                cities_iter = cities_collection.values() if isinstance(cities_collection, dict) else cities_collection
                for c in cities_iter:
                    if isinstance(c, dict) and c.get('id') == city_id:
                        city_obj = c
                        break
                if not city_obj:
                    return self._validation_error('E130', f'City not found: {city_id}')
                if city_obj.get('owner') != player_id:
                    return self._validation_error('E130', f'City {city_id} not owned by player')

        return ValidationResult(True)

    def _validate_city_change_specialist(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city change specialist action

        Convert one specialist type to another within a city using PACKET_CITY_CHANGE_SPECIALIST (pid=39).
        This allows micromanagement of citizen allocation (e.g., converting entertainers to scientists).
        Server validates specialist availability and city ownership.

        Error Codes:
            E131: Missing city_id, from_specialist, or to_specialist field
            E132: City not found in game state
            E133: City not owned by player
            E134: Invalid from_specialist type (negative or unknown)
            E135: Invalid to_specialist type (negative or unknown)

        Expected fields: {'type': 'city_change_specialist', 'city_id': int, 'from_specialist': str/int, 'to_specialist': str/int}
        Specialist types: 'elvis' (entertainer), 'scientist', 'taxman', or numeric IDs 0-2
        """
        if 'city_id' not in action or 'from_specialist' not in action or 'to_specialist' not in action:
            return self._validation_error('E131', 'City change specialist requires city_id, from_specialist, and to_specialist fields')

        city_id = action['city_id']
        from_spec = action['from_specialist']
        to_spec = action['to_specialist']

        # Validate specialist type format (allow string names or numeric IDs)
        def validate_specialist_type(spec_value, field_name):
            if isinstance(spec_value, int):
                if spec_value < 0:
                    return False, f'{field_name} must be non-negative'
            elif isinstance(spec_value, str):
                # Common specialist names (case-insensitive)
                valid_names = ['elvis', 'entertainer', 'scientist', 'taxman']
                if spec_value.lower() not in valid_names:
                    return False, f'{field_name} "{spec_value}" not recognized (expected: {valid_names})'
            else:
                return False, f'{field_name} must be string or integer'
            return True, None

        is_valid_from, from_error = validate_specialist_type(from_spec, 'from_specialist')
        if not is_valid_from:
            return self._validation_error('E134', from_error or 'Invalid from_specialist')

        is_valid_to, to_error = validate_specialist_type(to_spec, 'to_specialist')
        if not is_valid_to:
            return self._validation_error('E135', to_error or 'Invalid to_specialist')

        # Validate city ownership if game_state provided
        if game_state:
            cities_collection = game_state.get('cities')
            if cities_collection:
                cities_iter = cities_collection.values() if isinstance(cities_collection, dict) else cities_collection
                city_found = False
                for city in cities_iter:
                    if isinstance(city, dict) and city.get('id') == city_id:
                        city_found = True
                        if city.get('owner') != player_id:
                            return self._validation_error('E133', f'City {city_id} not owned by player')
                        break
                if not city_found:
                    return self._validation_error('E132', f'City not found: {city_id}')

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
            game_state: Optional game state with map_info or map

        Returns:
            bool: True if coordinates are valid, False otherwise
        """
        # Try map_info first, then map, then defaults
        if game_state:
            if 'map_info' in game_state:
                map_info = game_state['map_info']
                max_x = map_info.get('width', DEFAULT_MAP_WIDTH)
                max_y = map_info.get('height', DEFAULT_MAP_HEIGHT)
            elif 'map' in game_state:
                map_data = game_state['map']
                max_x = map_data.get('width', DEFAULT_MAP_WIDTH)
                max_y = map_data.get('height', DEFAULT_MAP_HEIGHT)
            else:
                max_x = DEFAULT_MAP_WIDTH
                max_y = DEFAULT_MAP_HEIGHT

            if not (0 <= x < max_x and 0 <= y < max_y):
                return False
        elif not (0 <= x < DEFAULT_MAP_WIDTH and 0 <= y < DEFAULT_MAP_HEIGHT):
            # Fallback to default map bounds when no game state
            # Coordinates from 0 to 199 for default 200x200 map
            return False

        return True

    def _validate_unit_explore(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate unit_explore action"""
        # Required fields
        if 'unit_id' not in action:
            return self._validation_error('E120', 'unit_explore requires unit_id')
        
        unit_id = action['unit_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E121', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E122', 'Player does not own unit')
            
            # Check unit can explore (settlers/workers typically can't)
            unit_type = unit.get('type', '').lower()
            non_explorer_types = ['settlers', 'worker', 'engineers']
            if any(t in unit_type for t in non_explorer_types):
                return self._validation_error('E123', f'Unit type {unit_type} cannot auto-explore')
            
            # Check movement points
            if unit.get('moves_left', 0) <= 0:
                return self._validation_error('E124', 'Unit has no movement points')
        
        return ValidationResult(is_valid=True)

    def _validate_city_build_unit(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city_build_unit action"""
        # Required fields
        if 'city_id' not in action:
            return self._validation_error('E030', 'city_build_unit requires city_id')
        if 'unit_type' not in action:
            return self._validation_error('E031', 'city_build_unit requires unit_type')
        
        city_id = action['city_id']
        unit_type = action['unit_type']
        
        # Validate city exists and is owned by player
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E032', f'City {city_id} not found')
            if city.get('owner') != player_id:
                return self._validation_error('E033', 'Player does not own city')
        
        # Validate unit_type is a string
        if not isinstance(unit_type, str):
            return self._validation_error('E034', 'unit_type must be a string')
        
        return ValidationResult(is_valid=True)

    def _validate_city_build_improvement(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate city_build_improvement action"""
        # Required fields
        if 'city_id' not in action:
            return self._validation_error('E036', 'city_build_improvement requires city_id')
        if 'improvement' not in action:
            return self._validation_error('E037', 'city_build_improvement requires improvement')
        
        city_id = action['city_id']
        improvement = action['improvement']
        
        # Validate city exists and is owned by player
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E038', f'City {city_id} not found')
            if city.get('owner') != player_id:
                return self._validation_error('E039', 'Player does not own city')
        
        # Validate improvement is a string
        if not isinstance(improvement, str):
            return self._validation_error('E040', 'improvement must be a string')
        
        return ValidationResult(is_valid=True)

    def _validate_diplomacy_message(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate diplomacy_message action"""
        # Required fields
        if 'target_player_id' not in action:
            return self._validation_error('E500', 'diplomacy_message requires target_player_id')
        if 'message_type' not in action:
            return self._validation_error('E501', 'diplomacy_message requires message_type')
        
        target_player_id = action['target_player_id']
        message_type = action['message_type']
        
        # Validate message_type is valid
        valid_types = ['treaty_request', 'declare_war', 'make_peace', 'cancel_treaty', 'share_vision']
        if message_type not in valid_types:
            return self._validation_error('E502', f'Invalid message_type. Must be one of: {valid_types}')
        
        # Can't send diplomacy to self
        if target_player_id == player_id:
            return self._validation_error('E503', 'Cannot send diplomacy message to self')
        
        # Validate target player exists
        if game_state and 'players' in game_state:
            players = game_state['players']
            target = players.get(str(target_player_id)) if isinstance(players, dict) else None
            if not target:
                return self._validation_error('E504', f'Target player {target_player_id} not found')
        
        return ValidationResult(is_valid=True)

    def _validate_help_wonder(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate help_wonder action - unit adds shields to wonder construction"""
        if 'unit_id' not in action:
            return self._validation_error('E600', 'help_wonder requires unit_id')
        if 'target_city_id' not in action:
            return self._validation_error('E601', 'help_wonder requires target_city_id')
        
        unit_id = action['unit_id']
        target_city_id = action['target_city_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E602', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E603', 'Player does not own unit')
        
        # Validate target city exists and is owned by player
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(target_city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E604', f'City {target_city_id} not found')
            if city.get('owner') != player_id:
                return self._validation_error('E605', 'Player does not own city')
        
        return ValidationResult(is_valid=True)

    def _validate_conquer_city(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate conquer_city action - military unit conquers enemy city"""
        if 'unit_id' not in action:
            return self._validation_error('E610', 'conquer_city requires unit_id')
        if 'target_city_id' not in action:
            return self._validation_error('E611', 'conquer_city requires target_city_id')
        
        unit_id = action['unit_id']
        target_city_id = action['target_city_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E612', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E613', 'Player does not own unit')
            # Check unit is military
            if not unit.get('can_attack', True):
                return self._validation_error('E614', 'Unit cannot attack (not a military unit)')
        
        # Validate target city exists and is NOT owned by player
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(target_city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E615', f'City {target_city_id} not found')
            if city.get('owner') == player_id:
                return self._validation_error('E616', 'Cannot conquer own city')
        
        return ValidationResult(is_valid=True)

    def _validate_capture_units(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate capture_units action - capture defeated units instead of destroying them"""
        if 'unit_id' not in action:
            return self._validation_error('E620', 'capture_units requires unit_id')
        if 'target_tile' not in action:
            return self._validation_error('E621', 'capture_units requires target_tile')
        
        unit_id = action['unit_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E622', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E623', 'Player does not own unit')
            # Check unit has capture capability
            if not unit.get('can_capture', False):
                return self._validation_error('E624', 'Unit cannot capture (lacks capture capability)')
        
        return ValidationResult(is_valid=True)

    def _validate_steal_maps(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate steal_maps action - spy steals enemy maps"""
        if 'unit_id' not in action:
            return self._validation_error('E630', 'steal_maps requires unit_id')
        if 'target_city_id' not in action:
            return self._validation_error('E631', 'steal_maps requires target_city_id')
        
        unit_id = action['unit_id']
        target_city_id = action['target_city_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E632', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E633', 'Player does not own unit')
            # Check unit is a spy/diplomat
            unit_type = unit.get('type', '').lower()
            if 'spy' not in unit_type and 'diplomat' not in unit_type:
                return self._validation_error('E634', 'Unit must be spy or diplomat')
        
        # Validate target city exists and is NOT owned by player
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(target_city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E635', f'City {target_city_id} not found')
            if city.get('owner') == player_id:
                return self._validation_error('E636', 'Cannot steal maps from own city')
        
        return ValidationResult(is_valid=True)

    def _validate_convert(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate convert action - convert unit type (e.g., religion, government)"""
        if 'unit_id' not in action:
            return self._validation_error('E640', 'convert requires unit_id')
        
        unit_id = action['unit_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E641', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E642', 'Player does not own unit')
            # Check unit can be converted
            if not unit.get('can_convert', True):
                return self._validation_error('E643', 'Unit cannot be converted')
        
        return ValidationResult(is_valid=True)

    def _validate_home_city(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate home_city action - change unit's home city"""
        if 'unit_id' not in action:
            return self._validation_error('E650', 'home_city requires unit_id')
        if 'city_id' not in action:
            return self._validation_error('E651', 'home_city requires city_id')
        
        unit_id = action['unit_id']
        city_id = action['city_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E652', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E653', 'Player does not own unit')
        
        # Validate city exists and is owned by player
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E654', f'City {city_id} not found')
            if city.get('owner') != player_id:
                return self._validation_error('E655', 'Player does not own city')
        
        return ValidationResult(is_valid=True)

    def _validate_strike_building(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate strike_building action - surgical strike on specific building"""
        if 'unit_id' not in action:
            return self._validation_error('E660', 'strike_building requires unit_id')
        if 'target_city_id' not in action:
            return self._validation_error('E661', 'strike_building requires target_city_id')
        if 'building_id' not in action:
            return self._validation_error('E662', 'strike_building requires building_id')
        
        unit_id = action['unit_id']
        target_city_id = action['target_city_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E663', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E664', 'Player does not own unit')
            # Check unit can strike (bomber, fighter, etc.)
            if not unit.get('can_bombard', False):
                return self._validation_error('E665', 'Unit cannot perform strikes')
        
        # Validate target city exists and is NOT owned by player
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(target_city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E666', f'City {target_city_id} not found')
            if city.get('owner') == player_id:
                return self._validation_error('E667', 'Cannot strike own city')
        
        return ValidationResult(is_valid=True)

    def _validate_strike_production(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate strike_production action - surgical strike on production"""
        if 'unit_id' not in action:
            return self._validation_error('E670', 'strike_production requires unit_id')
        if 'target_city_id' not in action:
            return self._validation_error('E671', 'strike_production requires target_city_id')
        
        unit_id = action['unit_id']
        target_city_id = action['target_city_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E672', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E673', 'Player does not own unit')
            # Check unit can strike
            if not unit.get('can_bombard', False):
                return self._validation_error('E674', 'Unit cannot perform strikes')
        
        # Validate target city exists and is NOT owned by player
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(target_city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E675', f'City {target_city_id} not found')
            if city.get('owner') == player_id:
                return self._validation_error('E676', 'Cannot strike own city')
        
        return ValidationResult(is_valid=True)

    def _validate_marketplace(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate marketplace action - convert caravan to gold"""
        if 'unit_id' not in action:
            return self._validation_error('E680', 'marketplace requires unit_id')
        if 'target_city_id' not in action:
            return self._validation_error('E681', 'marketplace requires target_city_id')
        
        unit_id = action['unit_id']
        target_city_id = action['target_city_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E682', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E683', 'Player does not own unit')
            # Check unit is caravan/freight
            unit_type = unit.get('type', '').lower()
            if 'caravan' not in unit_type and 'freight' not in unit_type:
                return self._validation_error('E684', 'Unit must be caravan or freight')
        
        # Validate target city exists
        if game_state and 'cities' in game_state:
            cities = game_state['cities']
            city = cities.get(str(target_city_id)) if isinstance(cities, dict) else None
            if not city:
                return self._validation_error('E685', f'City {target_city_id} not found')
        
        return ValidationResult(is_valid=True)

    def _validate_expel_unit(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate expel_unit action - diplomatically expel foreign unit"""
        if 'unit_id' not in action:
            return self._validation_error('E690', 'expel_unit requires unit_id')
        if 'target_unit_id' not in action:
            return self._validation_error('E691', 'expel_unit requires target_unit_id')
        
        unit_id = action['unit_id']
        target_unit_id = action['target_unit_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E692', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E693', 'Player does not own unit')
        
        # Validate target unit exists and is NOT owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            target = units.get(str(target_unit_id)) if isinstance(units, dict) else None
            if not target:
                return self._validation_error('E694', f'Target unit {target_unit_id} not found')
            if target.get('owner') == player_id:
                return self._validation_error('E695', 'Cannot expel own unit')
        
        return ValidationResult(is_valid=True)

    def _validate_spy_sabotage_unit(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate spy_sabotage_unit action - sabotage specific enemy unit"""
        if 'unit_id' not in action:
            return self._validation_error('E700', 'spy_sabotage_unit requires unit_id')
        if 'target_unit_id' not in action:
            return self._validation_error('E701', 'spy_sabotage_unit requires target_unit_id')
        
        unit_id = action['unit_id']
        target_unit_id = action['target_unit_id']
        
        # Validate unit exists and is owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            unit = units.get(str(unit_id)) if isinstance(units, dict) else None
            if not unit:
                return self._validation_error('E702', f'Unit {unit_id} not found')
            if unit.get('owner') != player_id:
                return self._validation_error('E703', 'Player does not own unit')
            # Check unit is spy/diplomat
            unit_type = unit.get('type', '').lower()
            if 'spy' not in unit_type and 'diplomat' not in unit_type:
                return self._validation_error('E704', 'Unit must be spy or diplomat')
        
        # Validate target unit exists and is NOT owned by player
        if game_state and 'units' in game_state:
            units = game_state['units']
            target = units.get(str(target_unit_id)) if isinstance(units, dict) else None
            if not target:
                return self._validation_error('E705', f'Target unit {target_unit_id} not found')
            if target.get('owner') == player_id:
                return self._validation_error('E706', 'Cannot sabotage own unit')
        
        return ValidationResult(is_valid=True)

    def _validate_player_rates(self, action: Dict[str, Any], player_id: int, game_state: Optional[Dict[str, Any]]) -> ValidationResult:
        """Validate player_rates action - set tax/science/luxury rates"""
        if 'tax_rate' not in action:
            return self._validation_error('E710', 'player_rates requires tax_rate')
        if 'science_rate' not in action:
            return self._validation_error('E711', 'player_rates requires science_rate')
        if 'luxury_rate' not in action:
            return self._validation_error('E712', 'player_rates requires luxury_rate')
        
        tax_rate = action['tax_rate']
        science_rate = action['science_rate']
        luxury_rate = action['luxury_rate']
        
        # Validate rates are integers
        if not isinstance(tax_rate, int):
            return self._validation_error('E713', 'tax_rate must be an integer')
        if not isinstance(science_rate, int):
            return self._validation_error('E714', 'science_rate must be an integer')
        if not isinstance(luxury_rate, int):
            return self._validation_error('E715', 'luxury_rate must be an integer')
        
        # Validate rates are 0-100
        if not (0 <= tax_rate <= 100):
            return self._validation_error('E716', 'tax_rate must be between 0 and 100')
        if not (0 <= science_rate <= 100):
            return self._validation_error('E717', 'science_rate must be between 0 and 100')
        if not (0 <= luxury_rate <= 100):
            return self._validation_error('E718', 'luxury_rate must be between 0 and 100')
        
        # Validate rates sum to 100
        if tax_rate + science_rate + luxury_rate != 100:
            return self._validation_error('E719', 'Rates must sum to 100')
        
        return ValidationResult(is_valid=True)
