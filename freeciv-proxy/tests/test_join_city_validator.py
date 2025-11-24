import pytest
from action_validator import LLMActionValidator, ActionType


@pytest.fixture
def validator():
    return LLMActionValidator(capabilities=[ActionType.JOIN_CITY])


def make_state(unit_owner=1, city_owner=1, unit_id=101, city_id=55, unit_type_name='worker'):
    return {
        'units': {
            unit_id: {
                'id': unit_id,
                'owner': unit_owner,
                'type': unit_type_name,
            }
        },
        'cities': {
            city_id: {
                'id': city_id,
                'owner': city_owner,
                'name': 'Capital'
            }
        }
    }


def test_join_city_success(validator):
    state = make_state()
    action = {'type': 'join_city', 'unit_id': 101, 'city_id': 55}
    result = validator.validate_action(action, 1, state)
    assert result.is_valid, f"Expected success got {result.error_code}: {result.error_message}"


def test_join_city_missing_fields(validator):
    state = make_state()
    action = {'type': 'join_city', 'unit_id': 101}  # missing city_id
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E126'


def test_join_city_unit_not_owned(validator):
    state = make_state(unit_owner=2)
    action = {'type': 'join_city', 'unit_id': 101, 'city_id': 55}
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E127'


def test_join_city_unit_not_found(validator):
    state = make_state()
    action = {'type': 'join_city', 'unit_id': 999, 'city_id': 55}
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E128'


def test_join_city_invalid_unit_type(validator):
    state = make_state(unit_type_name='warrior')
    action = {'type': 'join_city', 'unit_id': 101, 'city_id': 55}
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E129'


def test_join_city_city_not_found(validator):
    state = make_state()
    action = {'type': 'join_city', 'unit_id': 101, 'city_id': 999}
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E130'


def test_join_city_city_not_owned(validator):
    state = make_state(city_owner=2)
    action = {'type': 'join_city', 'unit_id': 101, 'city_id': 55}
    result = validator.validate_action(action, 1, state)
    assert not result.is_valid and result.error_code == 'E130'


def test_join_city_no_game_state(validator):
    action = {'type': 'join_city', 'unit_id': 101, 'city_id': 55}
    # Optimistic pass when game_state missing
    result = validator.validate_action(action, 1, None)
    assert result.is_valid
