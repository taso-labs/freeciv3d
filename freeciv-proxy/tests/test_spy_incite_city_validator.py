"""
Tests for spy_incite_city action validator (Phase 5 - Quick Wins)
Tests the generic _validate_spy_action method with spy_incite_city specific scenarios.
"""

import pytest
from action_validator import LLMActionValidator, ValidationResult


@pytest.fixture
def validator():
    """Create validator with spy actions enabled"""
    return LLMActionValidator()


@pytest.fixture
def mock_game_state_spy_incite():
    """Mock game state with spy unit and target city"""
    return {
        'units': {
            'u101': {'id': 101, 'owner': 1, 'type': 'Spy', 'busy': False, 'moves_left': 1},
            'u102': {'id': 102, 'owner': 1, 'type': 'Diplomat', 'busy': False, 'moves_left': 2},
            'u103': {'id': 103, 'owner': 1, 'type': 'Warriors', 'busy': False, 'moves_left': 1}
        },
        'cities': {
            'c201': {'id': 201, 'owner': 2, 'name': 'EnemyCity'},
            'c301': {'id': 301, 'owner': 1, 'name': 'OwnCity'}
        },
        'players': {
            'p1': {'id': 1, 'gold': 500},
            'p2': {'id': 2, 'gold': 1000}
        },
        'unit_actions': {
            101: [
                {
                    'action_id': 18,
                    'action_type': 'incite_city',
                    'probability': 100,
                    'target_city_id': 201,
                    'cost': 300
                }
            ]
        }
    }


def test_spy_incite_city_valid(validator, mock_game_state_spy_incite):
    """Valid spy_incite_city action"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert result.is_valid, f"Expected valid, got: {result.error_code} - {result.error_message}"


def test_spy_incite_city_missing_unit_id(validator, mock_game_state_spy_incite):
    """Spy incite city with missing unit_id (E109)"""
    action = {
        'type': 'spy_incite_city',
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E109'


def test_spy_incite_city_missing_target_city_id(validator, mock_game_state_spy_incite):
    """Spy incite city with missing target_city_id (E115)"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E115'


def test_spy_incite_city_unit_not_found(validator, mock_game_state_spy_incite):
    """Spy incite city with non-existent unit (E109)"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 999,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E109'


def test_spy_incite_city_not_owner(validator, mock_game_state_spy_incite):
    """Spy incite city with unit not owned by player (E113)"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 2, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E113'


def test_spy_incite_city_not_spy_or_diplomat(validator, mock_game_state_spy_incite):
    """Spy incite city with non-spy/diplomat unit (E402)"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 103,  # Warriors unit
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E402'


def test_spy_incite_city_target_city_not_found(validator, mock_game_state_spy_incite):
    """Spy incite city with non-existent target city (E115)"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 999
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E115'


def test_spy_incite_city_own_city(validator, mock_game_state_spy_incite):
    """Spy incite city targeting own city (E115)"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 301  # Own city
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E115'


def test_spy_incite_city_insufficient_gold(validator, mock_game_state_spy_incite):
    """Spy incite city with insufficient gold (E403)"""
    mock_game_state_spy_incite['players']['p1']['gold'] = 100  # Less than 300 cost
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E403'


def test_spy_incite_city_unit_busy(validator, mock_game_state_spy_incite):
    """Spy incite city with busy unit (E110)"""
    mock_game_state_spy_incite['units']['u101']['busy'] = True
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E110'


def test_spy_incite_city_no_moves(validator, mock_game_state_spy_incite):
    """Spy incite city with no movement points (E111)"""
    mock_game_state_spy_incite['units']['u101']['moves_left'] = 0
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E111'


def test_spy_incite_city_optimistic_pass_no_game_state(validator):
    """Spy incite city passes without game_state (optimistic validation)"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, None)
    assert result.is_valid


def test_spy_incite_city_diplomat_unit_valid(validator, mock_game_state_spy_incite):
    """Spy incite city with diplomat unit (also valid)"""
    action = {
        'type': 'spy_incite_city',
        'unit_id': 102,  # Diplomat unit
        'target_city_id': 201
    }
    # Remove unit_actions to test without server validation
    mock_game_state_spy_incite.pop('unit_actions', None)
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert result.is_valid


def test_spy_incite_city_action_not_available(validator, mock_game_state_spy_incite):
    """Spy incite city when action not available from server (E116)"""
    # Modify unit_actions to show zero probability
    mock_game_state_spy_incite['unit_actions'][101][0]['probability'] = 0
    action = {
        'type': 'spy_incite_city',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_incite)
    assert not result.is_valid
    assert result.error_code == 'E116'
