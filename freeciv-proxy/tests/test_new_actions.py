"""
Tests for New LLM Action Validators

Tests the validation logic for the 4 newly implemented actions:
- unit_explore
- city_build_unit
- city_build_improvement
- diplomacy_message
"""

import unittest
from unittest.mock import Mock, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator, ValidationResult


class TestNewActionValidators(unittest.TestCase):

    def setUp(self):
        """Setup test fixtures"""
        self.maxDiff = None
        self.validator = LLMActionValidator()

        # Sample game state for testing
        self.sample_game_state = {
            'units': {
                '123': {
                    'id': 123,
                    'owner': 0,
                    'type': 'Explorer',
                    'moves_left': 3,
                    'x': 10,
                    'y': 15,
                    'activity': 'idle'
                },
                '456': {
                    'id': 456,
                    'owner': 1,
                    'type': 'Warrior',
                    'moves_left': 1,
                    'x': 20,
                    'y': 25,
                    'activity': 'idle'
                },
                '789': {
                    'id': 789,
                    'owner': 0,
                    'type': 'Settlers',
                    'moves_left': 0,
                    'x': 5,
                    'y': 8,
                    'activity': 'idle'
                }
            },
            'cities': {
                '1': {
                    'id': 1,
                    'name': 'Capital',
                    'owner': 0,
                    'x': 10,
                    'y': 15,
                    'population': 5,
                    'production': {'kind': 0, 'value': 0}
                },
                '2': {
                    'id': 2,
                    'name': 'Outpost',
                    'owner': 1,
                    'x': 20,
                    'y': 25,
                    'population': 3,
                    'production': {'kind': 1, 'value': 1}
                }
            },
            'players': {
                '0': {
                    'id': 0,
                    'name': 'player1',
                    'gold': 100,
                    'tech_count': 5
                },
                '1': {
                    'id': 1,
                    'name': 'player2',
                    'gold': 50,
                    'tech_count': 3
                }
            }
        }

    # ========================================================================
    # unit_explore Tests
    # ========================================================================

    def test_unit_explore_valid_action(self):
        """Valid explore action should pass validation"""
        action = {
            'type': 'unit_explore',
            'unit_id': 123,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")
        self.assertIsNone(result.error_code)
        self.assertIsNone(result.error_message)

    def test_unit_explore_missing_unit_id(self):
        """Explore without unit_id should fail with E120"""
        action = {
            'type': 'unit_explore',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E120')
        self.assertIn('unit_id', result.error_message.lower())

    def test_unit_explore_unit_not_found(self):
        """Explore non-existent unit should fail with E121"""
        action = {
            'type': 'unit_explore',
            'unit_id': 9999,  # Doesn't exist
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E121')
        self.assertIn('not found', result.error_message.lower())

    def test_unit_explore_wrong_player(self):
        """Explore unit owned by another player should fail with E122"""
        action = {
            'type': 'unit_explore',
            'unit_id': 456,  # Owned by player 1
            'player_id': 0   # But player 0 is acting
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E122')
        self.assertIn('own', result.error_message.lower())

    def test_unit_explore_no_moves_left(self):
        """Explore unit with no moves should fail with E124"""
        action = {
            'type': 'unit_explore',
            'unit_id': 123,
            'player_id': 0
        }
        
        # Update unit to have no moves
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['123'] = game_state['units']['123'].copy()
        game_state['units']['123']['moves_left'] = 0

        result = self.validator.validate_action(action, player_id=0, game_state=game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E124')
        self.assertIn('movement', result.error_message.lower())

    def test_unit_explore_non_explorer_unit(self):
        """Explore with settlers should fail with E123"""
        action = {
            'type': 'unit_explore',
            'unit_id': 789,  # Settlers
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E123')
        self.assertIn('cannot', result.error_message.lower())

    # ========================================================================
    # city_build_unit Tests
    # ========================================================================

    def test_city_build_unit_valid_action(self):
        """Valid city build unit action should pass validation"""
        action = {
            'type': 'city_build_unit',
            'city_id': 1,
            'unit_type': 'Warrior',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")
        self.assertIsNone(result.error_code)
        self.assertIsNone(result.error_message)

    def test_city_build_unit_missing_city_id(self):
        """Build unit without city_id should fail with E030"""
        action = {
            'type': 'city_build_unit',
            'unit_type': 'Warrior',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E030')
        self.assertIn('city_id', result.error_message.lower())

    def test_city_build_unit_missing_unit_type(self):
        """Build unit without unit_type should fail with E031"""
        action = {
            'type': 'city_build_unit',
            'city_id': 1,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E031')
        self.assertIn('unit_type', result.error_message.lower())

    def test_city_build_unit_city_not_found(self):
        """Build unit in non-existent city should fail with E032"""
        action = {
            'type': 'city_build_unit',
            'city_id': 9999,
            'unit_type': 'Warrior',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E032')
        self.assertIn('not found', result.error_message.lower())

    def test_city_build_unit_wrong_player(self):
        """Build unit in city owned by another player should fail with E033"""
        action = {
            'type': 'city_build_unit',
            'city_id': 2,  # Owned by player 1
            'unit_type': 'Warrior',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E033')
        self.assertIn('own', result.error_message.lower())

    def test_city_build_unit_invalid_unit_type(self):
        """Build unit with non-string unit_type should fail with E034"""
        action = {
            'type': 'city_build_unit',
            'city_id': 1,
            'unit_type': 123,  # Integer instead of string
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E034')
        self.assertIn('string', result.error_message.lower())

    # ========================================================================
    # city_build_improvement Tests
    # ========================================================================

    def test_city_build_improvement_valid_action(self):
        """Valid city build improvement action should pass validation"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 1,
            'improvement': 'Granary',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")
        self.assertIsNone(result.error_code)
        self.assertIsNone(result.error_message)

    def test_city_build_improvement_missing_city_id(self):
        """Build improvement without city_id should fail with E036"""
        action = {
            'type': 'city_build_improvement',
            'improvement': 'Granary',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E036')
        self.assertIn('city_id', result.error_message.lower())

    def test_city_build_improvement_missing_improvement(self):
        """Build improvement without improvement name should fail with E037"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 1,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E037')
        self.assertIn('improvement', result.error_message.lower())

    def test_city_build_improvement_city_not_found(self):
        """Build improvement in non-existent city should fail with E038"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 9999,
            'improvement': 'Granary',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E038')
        self.assertIn('not found', result.error_message.lower())

    def test_city_build_improvement_wrong_player(self):
        """Build improvement in city owned by another player should fail with E039"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 2,  # Owned by player 1
            'improvement': 'Granary',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E039')
        self.assertIn('own', result.error_message.lower())

    def test_city_build_improvement_invalid_improvement(self):
        """Build improvement with non-string improvement should fail with E040"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 1,
            'improvement': 123,  # Integer instead of string
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E040')
        self.assertIn('string', result.error_message.lower())

    # ========================================================================
    # diplomacy_message Tests
    # ========================================================================

    def test_diplomacy_message_valid_treaty_request(self):
        """Valid diplomacy treaty request should pass validation"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message_type': 'treaty_request',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")
        self.assertIsNone(result.error_code)
        self.assertIsNone(result.error_message)

    def test_diplomacy_message_missing_target_player(self):
        """Diplomacy message without target_player_id should fail with E500"""
        action = {
            'type': 'diplomacy_message',
            'message_type': 'treaty_request',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E500')
        self.assertIn('target_player_id', result.error_message.lower())

    def test_diplomacy_message_missing_message_type(self):
        """Diplomacy message without message_type should fail with E501"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E501')
        self.assertIn('message_type', result.error_message.lower())

    def test_diplomacy_message_invalid_message_type(self):
        """Diplomacy message with invalid message_type should fail with E502"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message_type': 'invalid_type',  # Not in valid list
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E502')
        self.assertIn('invalid', result.error_message.lower())

    def test_diplomacy_message_target_player_not_found(self):
        """Diplomacy message to non-existent player should fail with E504"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 9999,
            'message_type': 'treaty_request',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E504')
        self.assertIn('not found', result.error_message.lower())

    def test_diplomacy_message_to_self(self):
        """Diplomacy message to self should fail with E503"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 0,  # Same as player_id
            'message_type': 'treaty_request',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E503')
        self.assertIn('self', result.error_message.lower())

    # ========================================================================
    # Edge Cases and Integration Tests
    # ========================================================================

    def test_unit_explore_with_minimal_game_state(self):
        """Explore action should work with minimal game state"""
        action = {
            'type': 'unit_explore',
            'unit_id': 123,
            'player_id': 0
        }
        
        minimal_state = {
            'units': {
                '123': {
                    'id': 123,
                    'owner': 0,
                    'moves_left': 1
                }
            }
        }

        result = self.validator.validate_action(action, player_id=0, game_state=minimal_state)

        self.assertTrue(result.is_valid)


if __name__ == '__main__':
    unittest.main()
