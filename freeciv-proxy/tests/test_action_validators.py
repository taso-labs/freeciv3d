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


class TestCategoryValidators(unittest.TestCase):
    """Test suite for category-based action validators (combat, diplomacy, espionage, etc.)"""

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
                    'type': 'Warrior',
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
                    'type': 'Spy',
                    'moves_left': 2,
                    'x': 5,
                    'y': 8
                }
            },
            'players': {
                '0': {'id': 0, 'name': 'player1'},
                '1': {'id': 1, 'name': 'player2'},
                '2': {'id': 2, 'name': 'player3'}
            },
            'cities': {
                '100': {'id': 100, 'owner': 0, 'name': 'Capital'},
                '200': {'id': 200, 'owner': 1, 'name': 'EnemyCity'}
            }
        }

    # ========================================================================
    # Combat Action Tests
    # ========================================================================

    def test_combat_attack_valid(self):
        """Valid attack action should pass validation"""
        action = {
            'type': 'unit_attack',
            'unit_id': 123,
            'target_x': 11,
            'target_y': 16,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_combat_attack_missing_target(self):
        """Attack without target should fail"""
        action = {
            'type': 'unit_attack',
            'unit_id': 123,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E235')

    def test_combat_attack_boolean_coordinates_rejected(self):
        """Attack with boolean coordinates should fail"""
        action = {
            'type': 'unit_attack',
            'unit_id': 123,
            'target_x': True,  # Boolean instead of int
            'target_y': 16,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        # Should be E221 (invalid type) from InputValidator

    def test_combat_attack_coordinates_out_of_bounds(self):
        """Attack with out-of-bounds coordinates should fail"""
        action = {
            'type': 'unit_attack',
            'unit_id': 123,
            'target_x': 300,  # Out of bounds
            'target_y': 16,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E233')

    def test_nuke_valid(self):
        """Valid nuke action should pass validation"""
        # Add nuke to capabilities
        from action_validator import ActionType
        self.validator.capabilities.append(ActionType.UNIT_NUKE)

        action = {
            'type': 'unit_nuke',
            'unit_id': 123,
            'target_x': 50,
            'target_y': 50,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_nuke_missing_target(self):
        """Nuke without target coordinates should fail"""
        from action_validator import ActionType
        self.validator.capabilities.append(ActionType.UNIT_NUKE)

        action = {
            'type': 'unit_nuke',
            'unit_id': 123,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E236')

    # ========================================================================
    # Diplomacy Action Tests
    # ========================================================================

    def test_diplomacy_message_valid(self):
        """Valid diplomacy message should pass"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message': 'Hello, would you like to trade?',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_diplomacy_message_sql_injection_blocked(self):
        """Diplomacy message with SQL injection should fail"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message': "Hello' OR '1'='1",
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        # E223 from character allowlist (single quotes not allowed) or E265 from SQL injection detection
        self.assertIn(result.error_code, ['E223', 'E265'])

    def test_diplomacy_message_xss_blocked(self):
        """Diplomacy message with XSS should fail"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message': '<script>alert("xss")</script>',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        # E223 from character allowlist (< and > not allowed) or E266 from XSS detection
        self.assertIn(result.error_code, ['E223', 'E266'])

    def test_diplomacy_self_target_blocked(self):
        """Diplomacy action targeting self should fail"""
        action = {
            'type': 'diplomacy_declare_war',
            'target_player_id': 0,  # Same as player_id
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E261')

    def test_diplomacy_missing_target(self):
        """Diplomacy action without target_player_id should fail"""
        action = {
            'type': 'diplomacy_propose_peace',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E260')

    def test_diplomacy_invalid_target_player(self):
        """Diplomacy action with non-existent target player should fail"""
        action = {
            'type': 'diplomacy_propose_alliance',
            'target_player_id': 999,  # Non-existent player
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E262')

    # ========================================================================
    # Espionage Action Tests
    # ========================================================================

    def test_espionage_steal_tech_valid(self):
        """Valid spy steal tech action should pass"""
        action = {
            'type': 'spy_steal_tech',
            'unit_id': 789,  # Spy unit
            'target_city_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_espionage_targeted_steal_tech_valid(self):
        """Valid spy targeted steal tech action should pass"""
        action = {
            'type': 'spy_targeted_steal_tech',
            'unit_id': 789,
            'target_city_id': 200,
            'sub_target': 'alphabet',  # Tech name
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_espionage_targeted_steal_tech_invalid_sub_target(self):
        """Spy targeted steal tech with invalid sub_target should fail"""
        action = {
            'type': 'spy_targeted_steal_tech',
            'unit_id': 789,
            'target_city_id': 200,
            'sub_target': '<script>evil()</script>',  # XSS attempt
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        # Should fail due to invalid characters in tech_name

    def test_espionage_missing_target_city(self):
        """Spy action without target_city_id should fail"""
        action = {
            'type': 'spy_sabotage_city',
            'unit_id': 789,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E273')

    def test_espionage_bribe_unit_valid(self):
        """Valid spy bribe unit action should pass"""
        action = {
            'type': 'spy_bribe_unit',
            'unit_id': 789,
            'target_unit_id': 456,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_espionage_bribe_unit_missing_target(self):
        """Spy bribe unit without target_unit_id should fail"""
        action = {
            'type': 'spy_bribe_unit',
            'unit_id': 789,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E275')

    # ========================================================================
    # Movement Action Tests
    # ========================================================================

    def test_paradrop_valid(self):
        """Valid paradrop action should pass"""
        action = {
            'type': 'unit_paradrop',
            'unit_id': 123,
            'target_x': 50,
            'target_y': 50,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_paradrop_boolean_coordinate_rejected(self):
        """Paradrop with boolean coordinate should fail"""
        action = {
            'type': 'unit_paradrop',
            'unit_id': 123,
            'target_x': False,  # Boolean instead of int
            'target_y': 50,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        # Should fail with E221 or E287

    def test_teleport_valid(self):
        """Valid teleport action should pass"""
        action = {
            'type': 'unit_teleport',
            'unit_id': 123,
            'target_x': 100,
            'target_y': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_embark_valid(self):
        """Valid embark action should pass"""
        action = {
            'type': 'unit_embark',
            'unit_id': 123,
            'transport_id': 456,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_embark_missing_transport(self):
        """Embark without transport_id should fail"""
        action = {
            'type': 'unit_embark',
            'unit_id': 123,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E283')

    # ========================================================================
    # Trade Action Tests
    # ========================================================================

    def test_trade_route_valid(self):
        """Valid trade route action should pass"""
        action = {
            'type': 'unit_trade_route',
            'unit_id': 123,
            'target_city_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid, f"Expected valid, got error: {result.error_message}")

    def test_trade_route_missing_city(self):
        """Trade route without target_city_id should fail"""
        action = {
            'type': 'unit_trade_route',
            'unit_id': 123,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E313')


class TestInputValidatorIntegration(unittest.TestCase):
    """Test InputValidator integration in action validation"""

    def setUp(self):
        """Setup test fixtures"""
        self.validator = LLMActionValidator()

    def test_redos_protection_long_input(self):
        """Very long input should be rejected before regex matching"""
        # Create a message that exceeds MAX_INPUT_LENGTH_FOR_REGEX (now 2048)
        long_message = 'A' * 3000

        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message': long_message,
            'player_id': 0
        }

        game_state = {
            'players': {'0': {'id': 0}, '1': {'id': 1}}
        }

        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        # Should fail due to message too long (E224)
        self.assertFalse(result.is_valid)

    def test_sql_comment_injection_blocked(self):
        """SQL comment injection should be blocked"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message': "Hello'-- DROP TABLE users",
            'player_id': 0
        }

        game_state = {
            'players': {'0': {'id': 0}, '1': {'id': 1}}
        }

        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E265')


if __name__ == '__main__':
    unittest.main()
