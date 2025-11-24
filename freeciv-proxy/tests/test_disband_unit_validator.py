import pytest

from action_validator import LLMActionValidator, ActionType

@pytest.fixture
def validator():
    return LLMActionValidator(capabilities=[ActionType.DISBAND_UNIT])

@pytest.fixture
def game_state_units():
    return {
        'units': [
            {'id': 7, 'owner': 1, 'type': 'warrior'},
            {'id': 8, 'owner': 2, 'type': 'warrior'}
        ]
    }

# Valid disband

def test_disband_unit_valid(validator, game_state_units):
    action = {'type': 'disband_unit', 'unit_id': 7, 'player_id': 1}
    result = validator.validate_action(action, 1, game_state_units)
    assert result.is_valid, f"Unexpected failure: {result.error_code} {result.error_message}"

# Missing unit_id

def test_disband_unit_missing_unit_id(validator, game_state_units):
    action = {'type': 'disband_unit', 'player_id': 1}
    result = validator.validate_action(action, 1, game_state_units)
    assert not result.is_valid and result.error_code == 'E123'

# Not owned

def test_disband_unit_not_owned(validator, game_state_units):
    action = {'type': 'disband_unit', 'unit_id': 8, 'player_id': 1}
    result = validator.validate_action(action, 1, game_state_units)
    assert not result.is_valid and result.error_code == 'E124'

# Unit not found

def test_disband_unit_not_found(validator, game_state_units):
    action = {'type': 'disband_unit', 'unit_id': 999, 'player_id': 1}
    result = validator.validate_action(action, 1, game_state_units)
    assert not result.is_valid and result.error_code == 'E125'

# No game state (optimistic)

def test_disband_unit_no_game_state(validator):
    action = {'type': 'disband_unit', 'unit_id': 42, 'player_id': 1}
    result = validator.validate_action(action, 1, None)
    assert result.is_valid
