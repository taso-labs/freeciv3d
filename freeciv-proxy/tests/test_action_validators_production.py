"""
Phase 3: Production Action Validator Tests

Tests validation logic for production-related actions:
- city_production (legacy)
- city_build_unit
- city_build_improvement
"""

import unittest
from unittest.mock import Mock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator, ValidationResult


class TestProductionValidators(unittest.TestCase):
    """Test validators for city production actions"""

    def setUp(self):
        """Set up test fixtures"""
        self.validator = LLMActionValidator()
        
        # Mock civcom with valid production types
        mock_civcom = Mock()
        mock_civcom.unit_types = {
            '1': {'name': 'Warriors', 'id': 1},
            '2': {'name': 'Phalanx', 'id': 2},
            '3': {'name': 'Archers', 'id': 3}
        }
        mock_civcom.improvements = {
            '1': {'name': 'Barracks', 'id': 1},
            '2': {'name': 'Granary', 'id': 2},
            '3': {'name': 'Library', 'id': 3}
        }
        self.validator.civcom = mock_civcom
        
        # Sample game state with cities and ruleset data
        self.sample_game_state = {
            'map': {'width': 80, 'height': 50},
            'cities': {
                '10': {
                    'id': 10,
                    'owner': 0,
                    'name': 'TestCity',
                    'x': 25,
                    'y': 30,
                    'production': {
                        'name': 'Warriors',
                        'kind': 0,  # Unit
                        'value': 1
                    }
                },
                '20': {
                    'id': 20,
                    'owner': 1,
                    'name': 'EnemyCity',
                    'x': 35,
                    'y': 40
                }
            },
            'players': {
                '0': {'id': 0, 'name': 'Player1'},
                '1': {'id': 1, 'name': 'Player2'}
            },
            'units': {}
        }

    # ========================================================================
    # city_production Tests (legacy action type)
    # ========================================================================

    def test_city_production_valid(self):
        """Valid city production change should pass"""
        action = {
            'type': 'city_production',
            'city_id': 10,
            'production_type': 'unit',
            'production_name': 'Phalanx',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_city_production_city_not_found(self):
        """Production change for non-existent city should fail with E030"""
        action = {
            'type': 'city_production',
            'city_id': 999,
            'production_type': 'unit',
            'production_name': 'Warriors',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E030')
        self.assertIn('not found', result.error_message.lower())

    def test_city_production_wrong_owner(self):
        """Production change for city owned by different player should fail with E031"""
        action = {
            'type': 'city_production',
            'city_id': 20,  # Owned by player 1
            'production_type': 'unit',
            'production_name': 'Warriors',
            'player_id': 0  # Player 0 trying to change it
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E031')
        self.assertIn('does not own', result.error_message.lower())

    def test_city_production_invalid_type(self):
        """Production change with invalid type should fail with E032"""
        action = {
            'type': 'city_production',
            'city_id': 10,
            'production_type': 'spaceship',  # Invalid type
            'production_name': 'Enterprise',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E032')
        self.assertIn('invalid', result.error_message.lower())

    def test_city_production_missing_fields(self):
        """Production change without required fields should fail"""
        action = {
            'type': 'city_production',
            'city_id': 10,
            'player_id': 0
            # Missing production_type and production_name
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)

    # ========================================================================
    # city_build_unit Tests
    # ========================================================================

    def test_city_build_unit_valid(self):
        """Valid city build unit should pass"""
        action = {
            'type': 'city_build_unit',
            'city_id': 10,
            'unit_type': 'Warriors',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_city_build_unit_city_not_found(self):
        """Build unit for non-existent city should fail"""
        action = {
            'type': 'city_build_unit',
            'city_id': 999,
            'unit_type': 'Warriors',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertIn('not found', result.error_message.lower())

    def test_city_build_unit_wrong_owner(self):
        """Build unit for enemy city should fail"""
        action = {
            'type': 'city_build_unit',
            'city_id': 20,  # Owned by player 1
            'unit_type': 'Warriors',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertIn('does not own', result.error_message.lower())

    def test_city_build_unit_missing_unit_type(self):
        """Build unit without unit_type should fail"""
        action = {
            'type': 'city_build_unit',
            'city_id': 10,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)

    def test_city_build_unit_no_game_state_optimistic(self):
        """Build unit without game state should optimistically pass"""
        action = {
            'type': 'city_build_unit',
            'city_id': 10,
            'unit_type': 'Warriors',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        self.assertTrue(result.is_valid)

    # ========================================================================
    # city_build_improvement Tests
    # ========================================================================

    def test_city_build_improvement_valid(self):
        """Valid city build improvement should pass"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 10,
            'improvement': 'Granary',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_city_build_improvement_city_not_found(self):
        """Build improvement for non-existent city should fail"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 999,
            'improvement': 'Granary',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertIn('not found', result.error_message.lower())

    def test_city_build_improvement_wrong_owner(self):
        """Build improvement for enemy city should fail"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 20,  # Owned by player 1
            'improvement': 'Granary',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertIn('does not own', result.error_message.lower())

    def test_city_build_improvement_missing_improvement(self):
        """Build improvement without improvement name should fail"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 10,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)

    def test_city_build_improvement_no_game_state_optimistic(self):
        """Build improvement without game state should optimistically pass"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 10,
            'improvement': 'Granary',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        self.assertTrue(result.is_valid)

    def test_city_build_improvement_case_insensitive(self):
        """Build improvement with different case should pass"""
        action = {
            'type': 'city_build_improvement',
            'city_id': 10,
            'improvement': 'GRANARY',
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)


if __name__ == '__main__':
    unittest.main()
