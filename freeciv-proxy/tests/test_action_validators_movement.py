"""
Phase 3: Movement Action Validator Tests

Tests validation logic for unit_move actions including:
- Valid moves within map bounds
- Out of bounds detection
- Unit not found errors
- Wrong owner detection
- No moves left detection
- Occupied tile detection
"""

import unittest
from unittest.mock import Mock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator, ValidationResult


class TestMovementValidators(unittest.TestCase):
    """Test validators for unit movement actions"""

    def setUp(self):
        """Set up test fixtures"""
        self.validator = LLMActionValidator()
        
        # Sample game state with units and map
        self.sample_game_state = {
            'map': {
                'width': 80,
                'height': 50,
                'tiles': []
            },
            'units': {
                '123': {
                    'id': 123,
                    'owner': 0,
                    'moves_left': 3,
                    'x': 10,
                    'y': 15,
                    'busy': False
                },
                '456': {
                    'id': 456,
                    'owner': 1,
                    'moves_left': 2,
                    'x': 20,
                    'y': 25,
                    'busy': False
                }
            },
            'cities': {},
            'players': {
                '0': {'id': 0, 'name': 'Player1'},
                '1': {'id': 1, 'name': 'Player2'}
            }
        }

    # ========================================================================
    # unit_move Tests
    # ========================================================================

    def test_unit_move_valid(self):
        """Valid unit move should pass validation"""
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'direction': 2,  # East
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_move_valid_with_coordinates(self):
        """Valid unit move with destination coordinates should pass"""
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'dest_x': 11,
            'dest_y': 15,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_move_unit_not_found(self):
        """Move with non-existent unit should fail with E010"""
        action = {
            'type': 'unit_move',
            'unit_id': 999,
            'direction': 2,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E010')
        self.assertIn('not found', result.error_message.lower())

    def test_unit_move_wrong_owner(self):
        """Move with unit owned by different player should fail with E011"""
        action = {
            'type': 'unit_move',
            'unit_id': 456,  # Owned by player 1
            'direction': 2,
            'player_id': 0  # Player 0 trying to move it
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E011')
        self.assertIn('does not own', result.error_message.lower())

    def test_unit_move_no_moves_left(self):
        """Move with unit that has no moves left should fail with E012"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['123'] = game_state['units']['123'].copy()
        game_state['units']['123']['moves_left'] = 0
        
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'direction': 2,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E012')
        self.assertIn('no moves', result.error_message.lower())

    def test_unit_move_out_of_bounds_x(self):
        """Move that would go out of bounds (X) should fail with E013"""
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'dest_x': 85,  # Beyond map width of 80
            'dest_y': 15,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E013')
        self.assertIn('out of bounds', result.error_message.lower())

    def test_unit_move_out_of_bounds_y(self):
        """Move that would go out of bounds (Y) should fail with E013"""
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'dest_x': 10,
            'dest_y': 55,  # Beyond map height of 50
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E013')
        self.assertIn('out of bounds', result.error_message.lower())

    def test_unit_move_out_of_bounds_negative(self):
        """Move to negative coordinates should fail with E013"""
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'dest_x': -1,
            'dest_y': 15,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E013')

    def test_unit_move_occupied_tile(self):
        """Move to tile occupied by another unit should fail with E014"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        # Add a third unit at (11, 15) - destination tile
        game_state['units']['789'] = {
            'id': 789,
            'owner': 0,
            'moves_left': 2,
            'x': 11,
            'y': 15,
            'busy': False
        }
        
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'dest_x': 11,
            'dest_y': 15,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E014')
        self.assertIn('occupied', result.error_message.lower())

    def test_unit_move_busy_unit(self):
        """Move with busy unit should fail"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['123'] = game_state['units']['123'].copy()
        game_state['units']['123']['busy'] = True
        
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'direction': 2,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        # Error code may vary based on implementation, just check it fails
        self.assertIn('busy', result.error_message.lower())

    def test_unit_move_missing_fields(self):
        """Move without unit_id should fail"""
        action = {
            'type': 'unit_move',
            'direction': 2,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)

    def test_unit_move_no_game_state_optimistic_pass(self):
        """Move without game state should optimistically pass"""
        action = {
            'type': 'unit_move',
            'unit_id': 123,
            'direction': 2,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        # Should pass optimistically when no game state available
        self.assertTrue(result.is_valid)

    def test_unit_move_multiple_directions(self):
        """Test moves in all 8 directions are accepted"""
        for direction in range(8):
            action = {
                'type': 'unit_move',
                'unit_id': 123,
                'direction': direction,
                'player_id': 0
            }
            result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
            self.assertTrue(result.is_valid, f"Direction {direction} should be valid")


if __name__ == '__main__':
    unittest.main()
