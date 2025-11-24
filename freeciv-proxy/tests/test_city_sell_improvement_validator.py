"""Tests for city_sell_improvement validator (Phase 5 completion)"""

import pytest
from action_validator import LLMActionValidator

@pytest.fixture
def validator():
    return LLMActionValidator()

@pytest.fixture
def game_state():
    return {
        'cities': {
            'c1': {
                'id': 101,
                'owner': 1,
                'name': 'Alpha',
                'improvements': [5, 7],
                'did_sell': False
            },
            'c2': {
                'id': 202,
                'owner': 2,
                'name': 'Beta',
                'improvements': [5]
            }
        },
        'improvements': {
            5: {'id': 5, 'name': 'Barracks'},
            7: {'id': 7, 'name': 'Granary'},
            9: {'id': 9, 'name': 'Palace', 'unsellable': True}
        },
        'players': {
            'p1': {'id': 1, 'gold': 300},
            'p2': {'id': 2, 'gold': 400}
        }
    }

def test_city_sell_improvement_valid_by_id(validator, game_state):
    action = {
        'type': 'city_sell_improvement',
        'city_id': 101,
        'improvement_id': 5
    }
    result = validator.validate_action(action, 1, game_state)
    assert result.is_valid, f"Unexpected failure: {result.error_code} {result.error_message}"

def test_city_sell_improvement_valid_by_name(validator, game_state):
    action = {
        'type': 'city_sell_improvement',
        'city_id': 101,
        'improvement_name': 'Granary'
    }
    result = validator.validate_action(action, 1, game_state)
    assert result.is_valid

def test_city_sell_improvement_missing_fields(validator, game_state):
    action = {
        'type': 'city_sell_improvement',
        'improvement_id': 5
    }
    result = validator.validate_action(action, 1, game_state)
    assert not result.is_valid and result.error_code == 'E142'

def test_city_sell_improvement_city_not_owned(validator, game_state):
    action = {
        'type': 'city_sell_improvement',
        'city_id': 202,
        'improvement_id': 5
    }
    result = validator.validate_action(action, 1, game_state)
    assert not result.is_valid and result.error_code == 'E143'

def test_city_sell_improvement_city_not_found(validator, game_state):
    action = {
        'type': 'city_sell_improvement',
        'city_id': 999,
        'improvement_id': 5
    }
    result = validator.validate_action(action, 1, game_state)
    assert not result.is_valid and result.error_code == 'E143'

def test_city_sell_improvement_improvement_not_present(validator, game_state):
    action = {
        'type': 'city_sell_improvement',
        'city_id': 101,
        'improvement_id': 9  # Palace not in city improvements list
    }
    result = validator.validate_action(action, 1, game_state)
    assert not result.is_valid and result.error_code == 'E144'

def test_city_sell_improvement_unsellable_flag(validator, game_state):
    # Add Palace to city improvements to test unsellable rule
    game_state['cities']['c1']['improvements'].append(9)
    action = {
        'type': 'city_sell_improvement',
        'city_id': 101,
        'improvement_id': 9
    }
    result = validator.validate_action(action, 1, game_state)
    assert not result.is_valid and result.error_code == 'E144'

def test_city_sell_improvement_already_sold(validator, game_state):
    game_state['cities']['c1']['did_sell'] = True
    action = {
        'type': 'city_sell_improvement',
        'city_id': 101,
        'improvement_id': 5
    }
    result = validator.validate_action(action, 1, game_state)
    assert not result.is_valid and result.error_code == 'E144'

def test_city_sell_improvement_optimistic_pass_no_gamestate(validator):
    action = {
        'type': 'city_sell_improvement',
        'city_id': 101,
        'improvement_id': 5
    }
    result = validator.validate_action(action, 1, None)
    assert result.is_valid

def test_city_sell_improvement_name_not_recognized(validator, game_state):
    action = {
        'type': 'city_sell_improvement',
        'city_id': 101,
        'improvement_name': 'UnknownBuilding'
    }
    result = validator.validate_action(action, 1, game_state)
    assert not result.is_valid and result.error_code == 'E144'
