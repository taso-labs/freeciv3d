import pytest

from action_validator import LLMActionValidator, ActionType

@pytest.fixture
def validator():
    v = LLMActionValidator(capabilities=[
        ActionType.GOVERNMENT_CHANGE
    ])
    return v

@pytest.fixture
def game_state_governments():
    return {
        'player': {
            'id': 1,
            'current_government': 'despotism',
            'revolution_active': False
        },
        'available_governments': ['despotism', 'monarchy', 'republic']
    }

@pytest.fixture
def game_state_revolution():
    return {
        'player': {
            'id': 1,
            'current_government': 'despotism',
            'revolution_active': True
        },
        'available_governments': ['despotism', 'monarchy', 'republic']
    }

# Valid change
def test_government_change_valid(validator, game_state_governments):
    action = {
        'type': 'government_change',
        'government_name': 'republic',
        'player_id': 1
    }
    result = validator.validate_action(action, 1, game_state_governments)
    assert result.is_valid, f"Expected valid government change, got {result.error_code}: {result.error_message}"

# Missing field
def test_government_change_missing_field(validator, game_state_governments):
    action = {
        'type': 'government_change',
        'player_id': 1
    }
    result = validator.validate_action(action, 1, game_state_governments)
    assert not result.is_valid and result.error_code == 'E117'

# Empty government name
def test_government_change_empty_name(validator, game_state_governments):
    action = {
        'type': 'government_change',
        'government_name': '   ',
        'player_id': 1
    }
    result = validator.validate_action(action, 1, game_state_governments)
    assert not result.is_valid and result.error_code == 'E117'

# Unrecognized government
def test_government_change_unrecognized(validator, game_state_governments):
    action = {
        'type': 'government_change',
        'government_name': 'galactic technocracy',
        'player_id': 1
    }
    result = validator.validate_action(action, 1, game_state_governments)
    assert not result.is_valid and result.error_code == 'E118'

# Already active government
def test_government_change_already_active(validator, game_state_governments):
    action = {
        'type': 'government_change',
        'government_name': 'despotism',
        'player_id': 1
    }
    result = validator.validate_action(action, 1, game_state_governments)
    assert not result.is_valid and result.error_code == 'E119'

# Recognized but not yet available (e.g., democracy missing from available list)
def test_government_change_not_available(validator, game_state_governments):
    action = {
        'type': 'government_change',
        'government_name': 'democracy',
        'player_id': 1
    }
    result = validator.validate_action(action, 1, game_state_governments)
    assert not result.is_valid and result.error_code == 'E118', "Democracy should be unrecognized (not in available or current)"

# Revolution active
def test_government_change_revolution_active(validator, game_state_revolution):
    action = {
        'type': 'government_change',
        'government_name': 'republic',
        'player_id': 1
    }
    result = validator.validate_action(action, 1, game_state_revolution)
    # Since republic is available, but revolution_active True → E121
    assert not result.is_valid and result.error_code == 'E121'

# Missing game state (optimistic pass)
def test_government_change_no_game_state(validator):
    action = {
        'type': 'government_change',
        'government_name': 'republic',
        'player_id': 1
    }
    result = validator.validate_action(action, 1, None)
    assert result.is_valid

# Missing government data structure
def test_government_change_missing_data_structure(validator):
    action = {
        'type': 'government_change',
        'government_name': 'republic',
        'player_id': 1
    }
    # Provide game_state without government info
    game_state = {'units': {}}
    result = validator.validate_action(action, 1, game_state)
    # Since available list empty and current not in player -> E122
    assert not result.is_valid and result.error_code == 'E122'
