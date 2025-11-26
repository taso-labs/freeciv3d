"""
Tests for Phase 8 strategic and unit management actions:
- help_wonder
- conquer_city
- capture_units
- steal_maps
- convert
- home_city
"""

import pytest
from unittest.mock import MagicMock
from action_validator import ActionType, LLMActionValidator, ValidationResult


@pytest.fixture
def validator():
    """Create validator with civcom mock"""
    civcom = MagicMock()
    return LLMActionValidator(civcom=civcom)


@pytest.fixture
def game_state_with_units_and_cities():
    """Game state with units and cities for testing"""
    return {
        'units': {
            '100': {'id': 100, 'owner': 1, 'type': 'Warrior', 'can_attack': True, 'moves_left': 3},
            '101': {'id': 101, 'owner': 1, 'type': 'Spy', 'can_attack': False},
            '102': {'id': 102, 'owner': 2, 'type': 'Settler', 'can_attack': False},
            '103': {'id': 103, 'owner': 1, 'type': 'Caravan', 'can_capture': True},
            '104': {'id': 104, 'owner': 1, 'type': 'Missionary', 'can_convert': True},
        },
        'cities': {
            '200': {'id': 200, 'owner': 1, 'name': 'MyCity'},
            '201': {'id': 201, 'owner': 2, 'name': 'EnemyCity'},
        }
    }


class TestHelpWonder:
    """Tests for help_wonder action validation"""

    def test_help_wonder_valid(self, validator, game_state_with_units_and_cities):
        """Valid help_wonder action"""
        action = {
            'type': 'help_wonder',
            'unit_id': 100,
            'target_city_id': 200
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert result.is_valid

    def test_help_wonder_missing_unit_id(self, validator, game_state_with_units_and_cities):
        """help_wonder without unit_id"""
        action = {
            'type': 'help_wonder',
            'target_city_id': 200
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E600'

    def test_help_wonder_missing_target_city(self, validator, game_state_with_units_and_cities):
        """help_wonder without target_city_id"""
        action = {
            'type': 'help_wonder',
            'unit_id': 100
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E601'

    def test_help_wonder_unit_not_found(self, validator, game_state_with_units_and_cities):
        """help_wonder with non-existent unit"""
        action = {
            'type': 'help_wonder',
            'unit_id': 999,
            'target_city_id': 200
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E602'

    def test_help_wonder_not_owned_unit(self, validator, game_state_with_units_and_cities):
        """help_wonder with enemy unit"""
        action = {
            'type': 'help_wonder',
            'unit_id': 102,  # Owned by player 2
            'target_city_id': 200
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E603'

    def test_help_wonder_city_not_found(self, validator, game_state_with_units_and_cities):
        """help_wonder with non-existent city"""
        action = {
            'type': 'help_wonder',
            'unit_id': 100,
            'target_city_id': 999
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E604'

    def test_help_wonder_not_owned_city(self, validator, game_state_with_units_and_cities):
        """help_wonder with enemy city"""
        action = {
            'type': 'help_wonder',
            'unit_id': 100,
            'target_city_id': 201  # Owned by player 2
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E605'


class TestConquerCity:
    """Tests for conquer_city action validation"""

    def test_conquer_city_valid(self, validator, game_state_with_units_and_cities):
        """Valid conquer_city action"""
        action = {
            'type': 'conquer_city',
            'unit_id': 100,
            'target_city_id': 201
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert result.is_valid

    def test_conquer_city_missing_unit_id(self, validator, game_state_with_units_and_cities):
        """conquer_city without unit_id"""
        action = {
            'type': 'conquer_city',
            'target_city_id': 201
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E610'

    def test_conquer_city_missing_target_city(self, validator, game_state_with_units_and_cities):
        """conquer_city without target_city_id"""
        action = {
            'type': 'conquer_city',
            'unit_id': 100
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E611'

    def test_conquer_city_unit_not_found(self, validator, game_state_with_units_and_cities):
        """conquer_city with non-existent unit"""
        action = {
            'type': 'conquer_city',
            'unit_id': 999,
            'target_city_id': 201
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E612'

    def test_conquer_city_non_military_unit(self, validator, game_state_with_units_and_cities):
        """conquer_city with non-military unit"""
        action = {
            'type': 'conquer_city',
            'unit_id': 101,  # Spy, can_attack=False
            'target_city_id': 201
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E614'

    def test_conquer_city_own_city(self, validator, game_state_with_units_and_cities):
        """conquer_city targeting own city"""
        action = {
            'type': 'conquer_city',
            'unit_id': 100,
            'target_city_id': 200  # Owned by player 1
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E616'


class TestCaptureUnits:
    """Tests for capture_units action validation"""

    def test_capture_units_valid(self, validator, game_state_with_units_and_cities):
        """Valid capture_units action"""
        action = {
            'type': 'capture_units',
            'unit_id': 103,
            'target_tile': 1234
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert result.is_valid

    def test_capture_units_missing_unit_id(self, validator, game_state_with_units_and_cities):
        """capture_units without unit_id"""
        action = {
            'type': 'capture_units',
            'target_tile': 1234
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E620'

    def test_capture_units_missing_target_tile(self, validator, game_state_with_units_and_cities):
        """capture_units without target_tile"""
        action = {
            'type': 'capture_units',
            'unit_id': 103
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E621'

    def test_capture_units_no_capability(self, validator, game_state_with_units_and_cities):
        """capture_units with unit lacking capture capability"""
        action = {
            'type': 'capture_units',
            'unit_id': 100,  # Warrior, no can_capture flag
            'target_tile': 1234
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E624'


class TestStealMaps:
    """Tests for steal_maps action validation"""

    def test_steal_maps_valid(self, validator, game_state_with_units_and_cities):
        """Valid steal_maps action"""
        action = {
            'type': 'steal_maps',
            'unit_id': 101,  # Spy
            'target_city_id': 201
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert result.is_valid

    def test_steal_maps_missing_unit_id(self, validator, game_state_with_units_and_cities):
        """steal_maps without unit_id"""
        action = {
            'type': 'steal_maps',
            'target_city_id': 201
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E630'

    def test_steal_maps_missing_target_city(self, validator, game_state_with_units_and_cities):
        """steal_maps without target_city_id"""
        action = {
            'type': 'steal_maps',
            'unit_id': 101
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E631'

    def test_steal_maps_not_spy(self, validator, game_state_with_units_and_cities):
        """steal_maps with non-spy unit"""
        action = {
            'type': 'steal_maps',
            'unit_id': 100,  # Warrior
            'target_city_id': 201
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E634'

    def test_steal_maps_own_city(self, validator, game_state_with_units_and_cities):
        """steal_maps targeting own city"""
        action = {
            'type': 'steal_maps',
            'unit_id': 101,
            'target_city_id': 200  # Owned by player 1
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E636'


class TestConvert:
    """Tests for convert action validation"""

    def test_convert_valid(self, validator, game_state_with_units_and_cities):
        """Valid convert action"""
        action = {
            'type': 'convert',
            'unit_id': 104  # Missionary with can_convert
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert result.is_valid

    def test_convert_missing_unit_id(self, validator, game_state_with_units_and_cities):
        """convert without unit_id"""
        action = {
            'type': 'convert'
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E640'

    def test_convert_unit_not_found(self, validator, game_state_with_units_and_cities):
        """convert with non-existent unit"""
        action = {
            'type': 'convert',
            'unit_id': 999
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E641'

    def test_convert_not_owned_unit(self, validator, game_state_with_units_and_cities):
        """convert with enemy unit"""
        action = {
            'type': 'convert',
            'unit_id': 102  # Owned by player 2
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E642'


class TestHomeCity:
    """Tests for home_city action validation"""

    def test_home_city_valid(self, validator, game_state_with_units_and_cities):
        """Valid home_city action"""
        action = {
            'type': 'home_city',
            'unit_id': 100,
            'city_id': 200
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert result.is_valid

    def test_home_city_missing_unit_id(self, validator, game_state_with_units_and_cities):
        """home_city without unit_id"""
        action = {
            'type': 'home_city',
            'city_id': 200
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E650'

    def test_home_city_missing_city_id(self, validator, game_state_with_units_and_cities):
        """home_city without city_id"""
        action = {
            'type': 'home_city',
            'unit_id': 100
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E651'

    def test_home_city_unit_not_found(self, validator, game_state_with_units_and_cities):
        """home_city with non-existent unit"""
        action = {
            'type': 'home_city',
            'unit_id': 999,
            'city_id': 200
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E652'

    def test_home_city_not_owned_unit(self, validator, game_state_with_units_and_cities):
        """home_city with enemy unit"""
        action = {
            'type': 'home_city',
            'unit_id': 102,  # Owned by player 2
            'city_id': 200
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E653'

    def test_home_city_city_not_found(self, validator, game_state_with_units_and_cities):
        """home_city with non-existent city"""
        action = {
            'type': 'home_city',
            'unit_id': 100,
            'city_id': 999
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E654'

    def test_home_city_not_owned_city(self, validator, game_state_with_units_and_cities):
        """home_city with enemy city"""
        action = {
            'type': 'home_city',
            'unit_id': 100,
            'city_id': 201  # Owned by player 2
        }
        result = validator.validate_action(action, player_id=1, game_state=game_state_with_units_and_cities)
        assert not result.is_valid
        assert result.error_code == 'E655'


class TestActionTypeEnum:
    """Test that new action types are in enum and capabilities"""

    def test_action_types_exist(self):
        """All Phase 8 actions exist in ActionType enum"""
        assert hasattr(ActionType, 'HELP_WONDER')
        assert hasattr(ActionType, 'CONQUER_CITY')
        assert hasattr(ActionType, 'CAPTURE_UNITS')
        assert hasattr(ActionType, 'STEAL_MAPS')
        assert hasattr(ActionType, 'CONVERT')
        assert hasattr(ActionType, 'HOME_CITY')

    def test_action_types_in_defaults(self, validator):
        """All Phase 8 actions in DEFAULT_CAPABILITIES"""
        assert ActionType.HELP_WONDER in validator.capabilities
        assert ActionType.CONQUER_CITY in validator.capabilities
        assert ActionType.CAPTURE_UNITS in validator.capabilities
        assert ActionType.STEAL_MAPS in validator.capabilities
        assert ActionType.CONVERT in validator.capabilities
        assert ActionType.HOME_CITY in validator.capabilities
