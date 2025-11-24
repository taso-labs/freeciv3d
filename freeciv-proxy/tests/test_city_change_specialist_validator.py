import pytest
from action_validator import LLMActionValidator, ActionType


@pytest.fixture
def validator():
    return LLMActionValidator(capabilities=[ActionType.CITY_CHANGE_SPECIALIST])


def make_state(city_owner=1, city_id=10):
    return {
        'cities': {
            city_id: {
                'id': city_id,
                'owner': city_owner,
                'name': 'TestCity',
                'specialists': [1, 2, 0]  # elvis, scientist, taxman counts
            }
        }
    }


def test_city_change_specialist_success_string_names(validator):
    """Test valid specialist change using string names"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 'elvis',
        'to_specialist': 'scientist'
    }
    result = validator.validate_action(action, 1, state)
    assert result.is_valid, f"Expected success got {result.error_code}: {result.error_message}"


def test_city_change_specialist_success_numeric_ids(validator):
    """Test valid specialist change using numeric IDs"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 0,
        'to_specialist': 1
    }
    result = validator.validate_action(action, 1, state)
    assert result.is_valid, f"Expected success got {result.error_code}: {result.error_message}"


def test_city_change_specialist_missing_city_id(validator):
    """Test E131: Missing city_id field"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'from_specialist': 'elvis',
        'to_specialist': 'scientist'
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E131'


def test_city_change_specialist_missing_from_specialist(validator):
    """Test E131: Missing from_specialist field"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'to_specialist': 'scientist'
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E131'


def test_city_change_specialist_missing_to_specialist(validator):
    """Test E131: Missing to_specialist field"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 'elvis'
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E131'


def test_city_change_specialist_city_not_found(validator):
    """Test E132: City not found"""
    state = make_state(city_id=10)
    action = {
        'type': 'city_change_specialist',
        'city_id': 999,  # Not in state
        'from_specialist': 'elvis',
        'to_specialist': 'scientist'
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E132'


def test_city_change_specialist_city_not_owned(validator):
    """Test E133: City not owned by player"""
    state = make_state(city_owner=2)  # Owned by player 2
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 'elvis',
        'to_specialist': 'scientist'
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E133'


def test_city_change_specialist_invalid_from_type_negative(validator):
    """Test E134: Invalid from_specialist (negative number)"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': -1,
        'to_specialist': 'scientist'
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E134'


def test_city_change_specialist_invalid_from_type_unknown_name(validator):
    """Test E134: Invalid from_specialist (unrecognized name)"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 'wizard',  # Not a valid specialist
        'to_specialist': 'scientist'
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E134'


def test_city_change_specialist_invalid_to_type_negative(validator):
    """Test E135: Invalid to_specialist (negative number)"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 'elvis',
        'to_specialist': -2
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E135'


def test_city_change_specialist_invalid_to_type_unknown_name(validator):
    """Test E135: Invalid to_specialist (unrecognized name)"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 'elvis',
        'to_specialist': 'warlock'  # Not a valid specialist
    }
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E135'


def test_city_change_specialist_no_game_state(validator):
    """Test optimistic pass when game_state is None"""
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 'elvis',
        'to_specialist': 'scientist'
    }
    result = validator.validate_action(action, 1, None)
    assert result.is_valid


def test_city_change_specialist_alternative_names(validator):
    """Test that 'entertainer' is recognized as alias for 'elvis'"""
    state = make_state()
    action = {
        'type': 'city_change_specialist',
        'city_id': 10,
        'from_specialist': 'entertainer',
        'to_specialist': 'taxman'
    }
    result = validator.validate_action(action, 1, state)
    assert result.is_valid
