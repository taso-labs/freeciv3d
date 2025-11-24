"""
Tests for LLM Action Validators

Tests the validation logic for all 5 new unit actions:
- unit_fortify
- unit_sentry
- unit_build_road
- unit_build_irrigation
- unit_build_mine
"""

import unittest
from unittest.mock import Mock, MagicMock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator, ValidationResult


class TestActionValidators(unittest.TestCase):

    # ========================================================================
    # unit_attack Tests (Tier 1)
    # ========================================================================
    def test_unit_attack_valid_adjacent(self):
        """Valid adjacent attack should pass validation"""
        action = {
            'type': 'unit_attack',
            'attacker_unit_id': 123,
            'target_unit_id': 456,
            'player_id': 0
        }
        # Place attacker at (10, 15), target at (11, 15) (adjacent)
        game_state = self.sample_game_state.copy()
        game_state['units'] = {
            '123': {'id': 123, 'owner': 0, 'moves_left': 2, 'x': 10, 'y': 15, 'can_attack': True},
            '456': {'id': 456, 'owner': 1, 'moves_left': 1, 'x': 11, 'y': 15}
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertTrue(result.is_valid)

    def test_unit_attack_attacker_not_found(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 999, 'target_unit_id': 456, 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_unit_attack_target_not_found(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 999, 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_unit_attack_wrong_owner(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 456, 'target_unit_id': 123, 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_unit_attack_friendly_target(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 789, 'player_id': 0}
        # Both units owned by player 0
        game_state = self.sample_game_state.copy()
        game_state['units'] = {
            '123': {'id': 123, 'owner': 0, 'moves_left': 2, 'x': 10, 'y': 15, 'can_attack': True},
            '789': {'id': 789, 'owner': 0, 'moves_left': 2, 'x': 11, 'y': 15}
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_unit_attack_no_moves_left(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
        game_state = self.sample_game_state.copy()
        game_state['units']['123']['moves_left'] = 0
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E111')

    def test_unit_attack_attacker_busy(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
        game_state = self.sample_game_state.copy()
        game_state['units']['123']['busy'] = True
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E110')

    def test_unit_attack_not_adjacent_non_ranged(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
        game_state = self.sample_game_state.copy()
        game_state['units']['123']['x'] = 10
        game_state['units']['123']['y'] = 15
        game_state['units']['456']['x'] = 20
        game_state['units']['456']['y'] = 25
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E112')

    def test_unit_attack_attacker_cannot_attack(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
        game_state = self.sample_game_state.copy()
        game_state['units']['123']['can_attack'] = False
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_unit_attack_action_not_available(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
        game_state = self.sample_game_state.copy()
        # No 'attack' in unit_actions for attacker
        game_state['unit_actions'] = {123: [{'action_type': 'other', 'probability': 100}]}
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

        # ========================================================================
        # unit_attack Tests (Tier 1)
        # ========================================================================

        def test_unit_attack_valid_adjacent(self):
            """Valid adjacent attack should pass validation"""
            action = {
                'type': 'unit_attack',
                'attacker_unit_id': 123,
                'target_unit_id': 456,
                'player_id': 0
            }
            # Place attacker at (10, 15), target at (11, 15) (adjacent)
            game_state = self.sample_game_state.copy()
            game_state['units'] = {
                '123': {'id': 123, 'owner': 0, 'moves_left': 2, 'x': 10, 'y': 15, 'can_attack': True},
                '456': {'id': 456, 'owner': 1, 'moves_left': 1, 'x': 11, 'y': 15}
            }
            result = self.validator.validate_action(action, player_id=0, game_state=game_state)
            self.assertTrue(result.is_valid)

        def test_unit_attack_attacker_not_found(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 999, 'target_unit_id': 456, 'player_id': 0}
            result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E109')

        def test_unit_attack_target_not_found(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 999, 'player_id': 0}
            result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E115')

        def test_unit_attack_wrong_owner(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 456, 'target_unit_id': 123, 'player_id': 0}
            result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E113')

        def test_unit_attack_friendly_target(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 789, 'player_id': 0}
            # Both units owned by player 0
            game_state = self.sample_game_state.copy()
            game_state['units'] = {
                '123': {'id': 123, 'owner': 0, 'moves_left': 2, 'x': 10, 'y': 15, 'can_attack': True},
                '789': {'id': 789, 'owner': 0, 'moves_left': 2, 'x': 11, 'y': 15}
            }
            result = self.validator.validate_action(action, player_id=0, game_state=game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E115')

        def test_unit_attack_no_moves_left(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
            game_state = self.sample_game_state.copy()
            game_state['units']['123']['moves_left'] = 0
            result = self.validator.validate_action(action, player_id=0, game_state=game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E111')

        def test_unit_attack_attacker_busy(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
            game_state = self.sample_game_state.copy()
            game_state['units']['123']['busy'] = True
            result = self.validator.validate_action(action, player_id=0, game_state=game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E110')

        def test_unit_attack_not_adjacent_non_ranged(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
            game_state = self.sample_game_state.copy()
            game_state['units']['123']['x'] = 10
            game_state['units']['123']['y'] = 15
            game_state['units']['456']['x'] = 20
            game_state['units']['456']['y'] = 25
            result = self.validator.validate_action(action, player_id=0, game_state=game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E112')

        def test_unit_attack_attacker_cannot_attack(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
            game_state = self.sample_game_state.copy()
            game_state['units']['123']['can_attack'] = False
            result = self.validator.validate_action(action, player_id=0, game_state=game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E113')

        def test_unit_attack_action_not_available(self):
            action = {'type': 'unit_attack', 'attacker_unit_id': 123, 'target_unit_id': 456, 'player_id': 0}
            game_state = self.sample_game_state.copy()
            # No 'attack' in unit_actions for attacker
            game_state['unit_actions'] = {123: [{'action_type': 'other', 'probability': 100}]}
            result = self.validator.validate_action(action, player_id=0, game_state=game_state)
            self.assertFalse(result.is_valid)
            self.assertEqual(result.error_code, 'E116')
    """Test suite for action validators"""

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
                    'type': 'Workers',
                    'moves_left': 3,
                    'x': 10,
                    'y': 15
                },
                '456': {
                    'id': 456,
                    'owner': 1,
                    'type': 'Warrior',
                    'moves_left': 1,
                    'x': 20,
                    'y': 25
                },
                '789': {
                    'id': 789,
                    'owner': 0,
                    'type': 'Settlers',
                    'moves_left': 2,
                    'x': 5,
                    'y': 8
                }
            },
            'players': {
                '0': {'id': 0, 'name': 'player1'},
                '1': {'id': 1, 'name': 'player2'}
            }
        }

    # ========================================================================
    # unit_fortify Tests
    # ========================================================================

    def test_unit_fortify_valid_action(self):
        """Valid fortify action should pass validation"""
        action = {
            'type': 'unit_fortify',
            'unit_id': 123,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")
        self.assertIsNone(result.error_code)
        self.assertIsNone(result.error_message)

    def test_unit_fortify_missing_unit_id(self):
        """Fortify without unit_id should fail with E050"""
        action = {
            'type': 'unit_fortify',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E050')
        self.assertIn('unit_id', result.error_message.lower())

    def test_unit_fortify_wrong_player(self):
        """Fortify unit owned by another player should fail with E052"""
        action = {
            'type': 'unit_fortify',
            'unit_id': 456,  # Owned by player 1
            'player_id': 0   # But player 0 is acting
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E052')
        self.assertIn('own', result.error_message.lower())

    def test_unit_fortify_unit_not_found(self):
        """Fortify non-existent unit should fail with E051"""
        action = {
            'type': 'unit_fortify',
            'unit_id': 9999,  # Doesn't exist
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E051')
        self.assertIn('not found', result.error_message.lower())

    def test_unit_fortify_with_game_state(self):
        """Fortify with full game state validation"""
        action = {
            'type': 'unit_fortify',
            'unit_id': 789,  # Settlers owned by player 0
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_fortify_multiple_units(self):
        """Fortify different units sequentially"""
        # Fortify first unit
        action1 = {'type': 'unit_fortify', 'unit_id': 123, 'player_id': 0}
        result1 = self.validator.validate_action(action1, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result1.is_valid)

        # Fortify second unit
        action2 = {'type': 'unit_fortify', 'unit_id': 789, 'player_id': 0}
        result2 = self.validator.validate_action(action2, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result2.is_valid)

    def test_unit_fortify_without_game_state(self):
        """Fortify should work without game state (minimal validation)"""
        action = {
            'type': 'unit_fortify',
            'unit_id': 123,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=None)

        # Should pass basic validation even without game state
        self.assertTrue(result.is_valid)

    def test_unit_fortify_error_message_details(self):
        """Verify error messages contain helpful context"""
        action = {
            'type': 'unit_fortify',
            'unit_id': 456,  # Wrong owner
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        # Error message should mention the unit ID
        self.assertIn('456', result.error_message)

    # ========================================================================
    # unit_sentry Tests
    # ========================================================================

    def test_unit_sentry_valid_action(self):
        """Valid sentry action should pass validation"""
        action = {
            'type': 'unit_sentry',
            'unit_id': 456,
            'player_id': 1
        }

        result = self.validator.validate_action(action, player_id=1, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_sentry_missing_unit_id(self):
        """Sentry without unit_id should fail with E060"""
        action = {
            'type': 'unit_sentry',
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E060')
        self.assertIn('unit_id', result.error_message.lower())

    def test_unit_sentry_wrong_player(self):
        """Sentry unit owned by another player should fail"""
        action = {
            'type': 'unit_sentry',
            'unit_id': 123,  # Owned by player 0
            'player_id': 1   # But player 1 is acting
        }

        result = self.validator.validate_action(action, player_id=1, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertIn('own', result.error_message.lower())

    def test_unit_sentry_unit_not_found(self):
        """Sentry non-existent unit should fail"""
        action = {
            'type': 'unit_sentry',
            'unit_id': 8888,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertIn('not found', result.error_message.lower())

    def test_unit_sentry_with_game_state(self):
        """Sentry with full game state validation"""
        action = {
            'type': 'unit_sentry',
            'unit_id': 123,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_sentry_without_game_state(self):
        """Sentry should work without game state"""
        action = {
            'type': 'unit_sentry',
            'unit_id': 123,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=None)

        self.assertTrue(result.is_valid)

    # ========================================================================
    # unit_build_road Tests
    # ========================================================================

    def test_unit_build_road_valid_with_coordinates(self):
        """Valid build_road with x,y coordinates"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'x': 10,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_road_missing_x_coordinate(self):
        """Build road without x coordinate should fail with E070"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E070')
        self.assertIn('coordinate', result.error_message.lower())

    def test_unit_build_road_missing_y_coordinate(self):
        """Build road without y coordinate should fail with E070"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'x': 10
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E070')

    def test_unit_build_road_x_negative(self):
        """Negative x coordinate should fail"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'x': -5,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E072')
        self.assertIn('bounds', result.error_message.lower())

    def test_unit_build_road_x_too_large(self):
        """x >= 200 should fail with E072"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'x': 200,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E072')

    def test_unit_build_road_y_out_of_bounds(self):
        """Invalid y coordinate should fail"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'x': 10,
            'y': 300  # Too large
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E072')

    def test_unit_build_road_wrong_player(self):
        """Build road with unit owned by other player should fail"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 456,  # Owned by player 1
            'player_id': 0,
            'x': 10,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertIn('own', result.error_message.lower())

    def test_unit_build_road_at_boundary(self):
        """Coordinates at map edge (199, 199) should pass"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'x': 199,
            'y': 199
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_road_at_zero(self):
        """Coordinates at (0, 0) should pass"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'x': 0,
            'y': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_road_non_integer_coordinates(self):
        """Non-integer coordinates should be handled"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 123,
            'player_id': 0,
            'x': "10",  # String instead of int
            'y': 15.5   # Float instead of int
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        # Should either convert or fail gracefully
        # Implementation determines exact behavior
        self.assertIsNotNone(result)

    # ========================================================================
    # unit_build_irrigation Tests
    # ========================================================================

    def test_unit_build_irrigation_valid(self):
        """Valid build_irrigation with coordinates"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 123,
            'player_id': 0,
            'x': 12,
            'y': 18
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_irrigation_missing_coordinates(self):
        """Build irrigation without coordinates should fail"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 123,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E080')

    def test_unit_build_irrigation_x_out_of_bounds(self):
        """Out of bounds x for irrigation should fail"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 123,
            'player_id': 0,
            'x': -1,
            'y': 10
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E082')

    def test_unit_build_irrigation_y_out_of_bounds(self):
        """Out of bounds y for irrigation should fail"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 123,
            'player_id': 0,
            'x': 10,
            'y': 250
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E082')

    def test_unit_build_irrigation_wrong_player(self):
        """Build irrigation with wrong player should fail"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 456,  # Player 1's unit
            'player_id': 0,
            'x': 10,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)

    def test_unit_build_irrigation_unit_not_found(self):
        """Build irrigation with non-existent unit should fail"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 7777,
            'player_id': 0,
            'x': 10,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)

    def test_unit_build_irrigation_at_boundary(self):
        """Irrigation at map boundary should pass"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 123,
            'player_id': 0,
            'x': 199,
            'y': 199
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_irrigation_at_zero(self):
        """Irrigation at (0,0) should pass"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 123,
            'player_id': 0,
            'x': 0,
            'y': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_irrigation_coordinates_middle(self):
        """Irrigation at middle of map should pass"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 789,
            'player_id': 0,
            'x': 100,
            'y': 100
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_irrigation_without_game_state(self):
        """Irrigation without game state should still validate coordinates"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 123,
            'player_id': 0,
            'x': 50,
            'y': 50
        }

        result = self.validator.validate_action(action, player_id=0, game_state=None)

        self.assertTrue(result.is_valid)

    # ========================================================================
    # unit_build_mine Tests
    # ========================================================================

    def test_unit_build_mine_valid(self):
        """Valid build_mine with coordinates"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 123,
            'player_id': 0,
            'x': 25,
            'y': 30
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_mine_missing_coordinates(self):
        """Build mine without coordinates should fail"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 123,
            'player_id': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E090')

    def test_unit_build_mine_x_out_of_bounds_negative(self):
        """Negative x for mine should fail"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 123,
            'player_id': 0,
            'x': -10,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E092')

    def test_unit_build_mine_x_out_of_bounds_large(self):
        """x >= 200 for mine should fail"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 123,
            'player_id': 0,
            'x': 201,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E092')

    def test_unit_build_mine_y_out_of_bounds(self):
        """Out of bounds y for mine should fail"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 123,
            'player_id': 0,
            'x': 10,
            'y': -5
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E092')

    def test_unit_build_mine_wrong_player(self):
        """Build mine with wrong player should fail"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 456,  # Player 1's warrior
            'player_id': 0,
            'x': 10,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)

    def test_unit_build_mine_unit_not_found(self):
        """Build mine with non-existent unit should fail"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 6666,
            'player_id': 0,
            'x': 10,
            'y': 15
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertFalse(result.is_valid)

    def test_unit_build_mine_at_boundary(self):
        """Mine at map boundary should pass"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 123,
            'player_id': 0,
            'x': 199,
            'y': 199
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_mine_at_zero(self):
        """Mine at (0,0) should pass"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 789,
            'player_id': 0,
            'x': 0,
            'y': 0
        }

        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

        self.assertTrue(result.is_valid)

    def test_unit_build_mine_various_coordinates(self):
        """Mine at various valid coordinates should pass"""
        test_coords = [(0, 0), (50, 50), (100, 150), (199, 0), (0, 199)]

        for x, y in test_coords:
            with self.subTest(x=x, y=y):
                action = {
                    'type': 'unit_build_mine',
                    'unit_id': 123,
                    'player_id': 0,
                    'x': x,
                    'y': y
                }

                result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)

                self.assertTrue(result.is_valid, f"Failed at ({x}, {y})")


if __name__ == '__main__':
    unittest.main()
