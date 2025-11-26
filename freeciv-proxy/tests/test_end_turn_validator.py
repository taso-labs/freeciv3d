"""Tests for end_turn action validator"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator


class TestEndTurnValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.sample_game_state = {
            'players': {'0': {'id': 0, 'name': 'player1'}, '1': {'id': 1, 'name': 'player2'}},
            'game_phase': 'playing'
        }

    def test_end_turn_valid(self):
        action = {'type': 'end_turn', 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_end_turn_wrong_player(self):
        action = {'type': 'end_turn', 'player_id': 1}
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E005')

    def test_end_turn_no_game_state(self):
        action = {'type': 'end_turn', 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        self.assertTrue(result.is_valid)
