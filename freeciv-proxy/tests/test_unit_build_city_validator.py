"""Tests for unit_build_city action validator"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator


class TestUnitBuildCityValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.base_game_state = {
            'units': {
                '123': {'id': 123, 'owner': 0, 'type': 'Settler', 'moves_left': 3},
                '456': {'id': 456, 'owner': 0, 'type': 'Warrior', 'moves_left': 2},
                '789': {'id': 789, 'owner': 1, 'type': 'Colonist', 'moves_left': 1}
            }
        }

    def test_unit_build_city_valid_settler(self):
        action = {'type': 'unit_build_city', 'unit_id': 123, 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=self.base_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_build_city_invalid_not_settler(self):
        action = {'type': 'unit_build_city', 'unit_id': 456, 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E022')

    def test_unit_build_city_missing_unit_id(self):
        action = {'type': 'unit_build_city', 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E020')

    def test_unit_build_city_unit_not_found(self):
        action = {'type': 'unit_build_city', 'unit_id': 999, 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E023')

    def test_unit_build_city_no_game_state(self):
        action = {'type': 'unit_build_city', 'unit_id': 123, 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        # Optimistic pass without game state
        self.assertTrue(result.is_valid)
