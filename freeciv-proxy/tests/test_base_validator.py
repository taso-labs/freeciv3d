#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for base action validator (Phase 6 - Advanced Terrain)
"""

import pytest
from action_validator import LLMActionValidator, ActionType


class TestBaseValidator:
    """Test suite for base action validation (Phase 6 - Advanced Terrain)"""

    @pytest.fixture
    def validator(self):
        """Create validator with base capability"""
        return LLMActionValidator(capabilities=[ActionType.BASE])

    @pytest.fixture
    def game_state(self):
        """Create base game state fixture"""
        return {
            'units': {
                1: {
                    'id': 1,
                    'owner': 10,
                    'activity': 0,  # ACTIVITY_IDLE
                    'moves_left': 3
                },
                2: {
                    'id': 2,
                    'owner': 11,  # Different owner
                    'activity': 0,
                    'moves_left': 3
                },
                3: {
                    'id': 3,
                    'owner': 10,
                    'activity': 13,  # ACTIVITY_GEN_ROAD (busy)
                    'moves_left': 3
                },
                4: {
                    'id': 4,
                    'owner': 10,
                    'activity': 0,
                    'moves_left': 0  # No moves
                }
            }
        }

    def test_base_valid(self, validator, game_state):
        """Valid base action should pass"""
        action = {
            'type': 'base',
            'unit_id': 1
        }
        result = validator.validate_action(action, player_id=10, game_state=game_state)
        assert result.is_valid

    def test_base_missing_unit_id(self, validator, game_state):
        """Base without unit_id should fail with E151"""
        action = {
            'type': 'base'
        }
        result = validator.validate_action(action, player_id=10, game_state=game_state)
        assert not result.is_valid
        assert result.error_code == 'E151'
        assert 'unit_id' in result.error_message

    def test_base_unit_not_found(self, validator, game_state):
        """Base with non-existent unit should fail with E152"""
        action = {
            'type': 'base',
            'unit_id': 999  # Non-existent
        }
        result = validator.validate_action(action, player_id=10, game_state=game_state)
        assert not result.is_valid
        assert result.error_code == 'E152'
        assert 'not found' in result.error_message.lower()

    def test_base_not_owner(self, validator, game_state):
        """Base with unit owned by another player should fail with E152"""
        action = {
            'type': 'base',
            'unit_id': 2  # Owned by player 11
        }
        result = validator.validate_action(action, player_id=10, game_state=game_state)
        assert not result.is_valid
        assert result.error_code == 'E152'
        assert 'does not own' in result.error_message.lower()

    def test_base_unit_busy(self, validator, game_state):
        """Base with busy unit should fail with E153"""
        action = {
            'type': 'base',
            'unit_id': 3  # Busy with ACTIVITY_GEN_ROAD
        }
        result = validator.validate_action(action, player_id=10, game_state=game_state)
        assert not result.is_valid
        assert result.error_code == 'E153'
        assert 'busy' in result.error_message.lower()

    def test_base_no_moves(self, validator, game_state):
        """Base with no moves left should fail with E153"""
        action = {
            'type': 'base',
            'unit_id': 4  # No moves left
        }
        result = validator.validate_action(action, player_id=10, game_state=game_state)
        assert not result.is_valid
        assert result.error_code == 'E153'
        assert 'no moves' in result.error_message.lower()

    def test_base_optimistic_pass_no_game_state(self, validator):
        """Base without game_state should pass (optimistic)"""
        action = {
            'type': 'base',
            'unit_id': 1
        }
        result = validator.validate_action(action, player_id=10, game_state=None)
        assert result.is_valid

    def test_base_capability_check(self):
        """Base without capability should fail"""
        validator = LLMActionValidator(capabilities=[])
        action = {
            'type': 'base',
            'unit_id': 1
        }
        result = validator.validate_action(action, player_id=10, game_state=None)
        assert not result.is_valid
        assert 'not permitted' in result.error_message.lower() or 'capability' in result.error_message.lower()
