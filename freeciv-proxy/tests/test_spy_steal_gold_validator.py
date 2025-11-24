"""
Tests for spy_steal_gold action validator (Phase 5 - Quick Wins)
Tests the generic _validate_spy_action method with spy_steal_gold specific scenarios.
"""

import pytest
from action_validator import LLMActionValidator, ValidationResult


@pytest.fixture
def validator():
    """Create validator with spy actions enabled"""
    return LLMActionValidator()


@pytest.fixture
def mock_game_state_spy_steal_gold():
    """Mock game state with spy unit and target city"""
    return {
        'units': {
            'u101': {'id': 101, 'owner': 1, 'type': 'Spy', 'busy': False, 'moves_left': 1},
            'u102': {'id': 102, 'owner': 1, 'type': 'Warriors', 'busy': False, 'moves_left': 2}
        },
        'cities': {
            'c201': {'id': 201, 'owner': 2, 'name': 'EnemyCity'},
            'c301': {'id': 301, 'owner': 1, 'name': 'OwnCity'}
        },
        'players': {
            'p1': {'id': 1, 'gold': 500},
            'p2': {'id': 2, 'gold': 1000}
        }
    }


def test_spy_steal_gold_valid(validator, mock_game_state_spy_steal_gold):
    """Valid spy_steal_gold action"""
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert result.is_valid, f"Expected valid, got: {result.error_code} - {result.error_message}"


def test_spy_steal_gold_missing_unit_id(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with missing unit_id (E109)"""
    action = {
        'type': 'spy_steal_gold',
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E109'


def test_spy_steal_gold_missing_target_city_id(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with missing target_city_id (E115)"""
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E115'


def test_spy_steal_gold_unit_not_found(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with non-existent unit (E109)"""
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 999,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E109'


def test_spy_steal_gold_not_owner(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with unit not owned by player (E113)"""
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 2, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E113'


def test_spy_steal_gold_not_spy_unit(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with non-spy unit (E402)"""
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 102,  # Warriors unit
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E402'


def test_spy_steal_gold_target_city_not_found(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with non-existent target city (E115)"""
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101,
        'target_city_id': 999
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E115'


def test_spy_steal_gold_own_city(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold targeting own city (E115)"""
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101,
        'target_city_id': 301  # Own city
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E115'


def test_spy_steal_gold_unit_busy(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with busy unit (E110)"""
    mock_game_state_spy_steal_gold['units']['u101']['busy'] = True
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E110'


def test_spy_steal_gold_no_moves(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with no movement points (E111)"""
    mock_game_state_spy_steal_gold['units']['u101']['moves_left'] = 0
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert not result.is_valid
    assert result.error_code == 'E111'


def test_spy_steal_gold_optimistic_pass_no_game_state(validator):
    """Spy steal gold passes without game_state (optimistic validation)"""
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, None)
    assert result.is_valid


def test_spy_steal_gold_diplomat_unit_valid(validator, mock_game_state_spy_steal_gold):
    """Spy steal gold with diplomat unit (also valid)"""
    mock_game_state_spy_steal_gold['units']['u101']['type'] = 'Diplomat'
    action = {
        'type': 'spy_steal_gold',
        'unit_id': 101,
        'target_city_id': 201
    }
    result = validator.validate_action(action, 1, mock_game_state_spy_steal_gold)
    assert result.is_valid
