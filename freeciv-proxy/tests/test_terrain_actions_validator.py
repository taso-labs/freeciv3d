#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for terrain management action validators (Tier 2.5)
Tests validators for unit_clean_pollution, unit_clean_fallout, and unit_transform_terrain
"""

import pytest
from action_validator import LLMActionValidator, ActionType


@pytest.fixture
def validator():
    """Create validator instance for testing"""
    v = LLMActionValidator()
    v.add_capability(ActionType.UNIT_CLEAN_POLLUTION)
    v.add_capability(ActionType.UNIT_CLEAN_FALLOUT)
    v.add_capability(ActionType.UNIT_TRANSFORM_TERRAIN)
    return v


@pytest.fixture
def game_state_with_worker():
    """Game state with a worker unit"""
    return {
        'turn': 5,
        'units': {
            42: {
                'id': 42,
                'owner': 1,
                'type': 'Worker',
                'x': 10,
                'y': 20,
                'moves_left': 3
            }
        },
        'map_info': {
            'width': 100,
            'height': 100
        }
    }


@pytest.fixture
def game_state_with_enemy_worker():
    """Game state with enemy worker"""
    return {
        'turn': 5,
        'units': {
            99: {
                'id': 99,
                'owner': 2,
                'type': 'Worker',
                'x': 15,
                'y': 25,
                'moves_left': 3
            }
        }
    }


# ========================================
# unit_clean_pollution Tests
# ========================================

def test_clean_pollution_valid(validator, game_state_with_worker):
    """Test valid pollution cleanup action"""
    action = {
        'type': 'unit_clean_pollution',
        'unit_id': 42,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert result.is_valid
    assert result.error_code is None


def test_clean_pollution_missing_unit_id(validator, game_state_with_worker):
    """Test pollution cleanup without unit_id"""
    action = {
        'type': 'unit_clean_pollution',
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert not result.is_valid
    assert result.error_code == 'E100'
    assert 'unit_id' in result.error_message.lower()


def test_clean_pollution_not_owned_by_player(validator, game_state_with_enemy_worker):
    """Test pollution cleanup with unit owned by different player"""
    action = {
        'type': 'unit_clean_pollution',
        'unit_id': 99,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_enemy_worker)
    assert not result.is_valid
    assert result.error_code == 'E101'
    assert 'does not own' in result.error_message.lower()


def test_clean_pollution_unit_not_found(validator, game_state_with_worker):
    """Test pollution cleanup with non-existent unit"""
    action = {
        'type': 'unit_clean_pollution',
        'unit_id': 999,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert not result.is_valid
    assert result.error_code == 'E102'
    assert 'not found' in result.error_message.lower()


def test_clean_pollution_no_game_state(validator):
    """Test pollution cleanup without game state (should pass - server validates)"""
    action = {
        'type': 'unit_clean_pollution',
        'unit_id': 42,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=None)
    assert result.is_valid


# ========================================
# unit_clean_fallout Tests
# ========================================

def test_clean_fallout_valid(validator, game_state_with_worker):
    """Test valid fallout cleanup action"""
    action = {
        'type': 'unit_clean_fallout',
        'unit_id': 42,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert result.is_valid
    assert result.error_code is None


def test_clean_fallout_missing_unit_id(validator, game_state_with_worker):
    """Test fallout cleanup without unit_id"""
    action = {
        'type': 'unit_clean_fallout',
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert not result.is_valid
    assert result.error_code == 'E103'
    assert 'unit_id' in result.error_message.lower()


def test_clean_fallout_not_owned_by_player(validator, game_state_with_enemy_worker):
    """Test fallout cleanup with unit owned by different player"""
    action = {
        'type': 'unit_clean_fallout',
        'unit_id': 99,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_enemy_worker)
    assert not result.is_valid
    assert result.error_code == 'E104'
    assert 'does not own' in result.error_message.lower()


def test_clean_fallout_unit_not_found(validator, game_state_with_worker):
    """Test fallout cleanup with non-existent unit"""
    action = {
        'type': 'unit_clean_fallout',
        'unit_id': 999,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert not result.is_valid
    assert result.error_code == 'E105'
    assert 'not found' in result.error_message.lower()


def test_clean_fallout_no_game_state(validator):
    """Test fallout cleanup without game state (should pass - server validates)"""
    action = {
        'type': 'unit_clean_fallout',
        'unit_id': 42,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=None)
    assert result.is_valid


# ========================================
# unit_transform_terrain Tests
# ========================================

def test_transform_terrain_valid(validator, game_state_with_worker):
    """Test valid terrain transformation action"""
    action = {
        'type': 'unit_transform_terrain',
        'unit_id': 42,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert result.is_valid
    assert result.error_code is None


def test_transform_terrain_missing_unit_id(validator, game_state_with_worker):
    """Test terrain transformation without unit_id"""
    action = {
        'type': 'unit_transform_terrain',
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert not result.is_valid
    assert result.error_code == 'E106'
    assert 'unit_id' in result.error_message.lower()


def test_transform_terrain_not_owned_by_player(validator, game_state_with_enemy_worker):
    """Test terrain transformation with unit owned by different player"""
    action = {
        'type': 'unit_transform_terrain',
        'unit_id': 99,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_enemy_worker)
    assert not result.is_valid
    assert result.error_code == 'E107'
    assert 'does not own' in result.error_message.lower()


def test_transform_terrain_unit_not_found(validator, game_state_with_worker):
    """Test terrain transformation with non-existent unit"""
    action = {
        'type': 'unit_transform_terrain',
        'unit_id': 999,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=game_state_with_worker)
    assert not result.is_valid
    assert result.error_code == 'E108'
    assert 'not found' in result.error_message.lower()


def test_transform_terrain_no_game_state(validator):
    """Test terrain transformation without game state (should pass - server validates)"""
    action = {
        'type': 'unit_transform_terrain',
        'unit_id': 42,
        'player_id': 1,
        'game_id': 'test-game'
    }
    result = validator.validate_action(action, player_id=1, game_state=None)
    assert result.is_valid


# ========================================
# Integration Tests
# ========================================

def test_all_terrain_actions_different_error_codes(validator, game_state_with_worker):
    """Verify each terrain action has unique error codes"""
    
    # Test missing unit_id for all three actions
    pollution_result = validator.validate_action(
        {'type': 'unit_clean_pollution', 'player_id': 1},
        player_id=1,
        game_state=game_state_with_worker
    )
    fallout_result = validator.validate_action(
        {'type': 'unit_clean_fallout', 'player_id': 1},
        player_id=1,
        game_state=game_state_with_worker
    )
    transform_result = validator.validate_action(
        {'type': 'unit_transform_terrain', 'player_id': 1},
        player_id=1,
        game_state=game_state_with_worker
    )
    
    # All should fail with different error codes
    assert pollution_result.error_code == 'E100'
    assert fallout_result.error_code == 'E103'
    assert transform_result.error_code == 'E106'


def test_terrain_actions_with_engineer_unit(validator):
    """Test terrain actions with engineer unit (typical use case)"""
    game_state = {
        'turn': 50,
        'units': {
            100: {
                'id': 100,
                'owner': 1,
                'type': 'Engineers',
                'x': 25,
                'y': 30,
                'moves_left': 3
            }
        }
    }
    
    # All three actions should validate successfully with engineer
    pollution_action = {
        'type': 'unit_clean_pollution',
        'unit_id': 100,
        'player_id': 1
    }
    fallout_action = {
        'type': 'unit_clean_fallout',
        'unit_id': 100,
        'player_id': 1
    }
    transform_action = {
        'type': 'unit_transform_terrain',
        'unit_id': 100,
        'player_id': 1
    }
    
    assert validator.validate_action(pollution_action, player_id=1, game_state=game_state).is_valid
    assert validator.validate_action(fallout_action, player_id=1, game_state=game_state).is_valid
    assert validator.validate_action(transform_action, player_id=1, game_state=game_state).is_valid


def test_terrain_actions_validator_capabilities(validator):
    """Test that terrain action validators are properly registered"""
    # These action types should be recognized
    assert hasattr(ActionType, 'UNIT_CLEAN_POLLUTION')
    assert hasattr(ActionType, 'UNIT_CLEAN_FALLOUT')
    assert hasattr(ActionType, 'UNIT_TRANSFORM_TERRAIN')
