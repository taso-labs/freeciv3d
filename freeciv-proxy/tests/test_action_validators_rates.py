"""
Phase 3: Player Rates Action Validator Tests

Tests validation logic for player_rates action:
- Valid rates (sum to 100)
- Invalid total (not 100)
- Negative values
- Missing fields
- Non-integer values
- Out of range values
"""

import unittest
from unittest.mock import Mock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator, ValidationResult


class TestPlayerRatesValidator(unittest.TestCase):
    """Test validator for player_rates action"""

    def setUp(self):
        """Set up test fixtures"""
        self.validator = LLMActionValidator()
        
        # Sample game state
        self.sample_game_state = {
            'players': {
                '0': {'id': 0, 'name': 'Player1'},
                '1': {'id': 1, 'name': 'Player2'}
            }
        }

    # ========================================================================
    # player_rates Tests
    # ========================================================================

    def test_player_rates_valid_balanced(self):
        """Valid player rates that sum to 100 should pass"""
        action = {
            'type': 'player_rates',
            'tax_rate': 40,
            'science_rate': 40,
            'luxury_rate': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_player_rates_valid_all_tax(self):
        """Valid rates with 100% tax should pass"""
        action = {
            'type': 'player_rates',
            'tax_rate': 100,
            'science_rate': 0,
            'luxury_rate': 0,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_player_rates_valid_all_science(self):
        """Valid rates with 100% science should pass"""
        action = {
            'type': 'player_rates',
            'tax_rate': 0,
            'science_rate': 100,
            'luxury_rate': 0,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_player_rates_valid_all_luxury(self):
        """Valid rates with 100% luxury should pass"""
        action = {
            'type': 'player_rates',
            'tax_rate': 0,
            'science_rate': 0,
            'luxury_rate': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_player_rates_invalid_sum_too_high(self):
        """Rates that sum to more than 100 should fail with E719"""
        action = {
            'type': 'player_rates',
            'tax_rate': 50,
            'science_rate': 40,
            'luxury_rate': 20,  # Sum = 110
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E719')
        self.assertIn('sum to 100', result.error_message)

    def test_player_rates_invalid_sum_too_low(self):
        """Rates that sum to less than 100 should fail with E719"""
        action = {
            'type': 'player_rates',
            'tax_rate': 30,
            'science_rate': 30,
            'luxury_rate': 30,  # Sum = 90
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E719')
        self.assertIn('sum to 100', result.error_message)

    def test_player_rates_negative_tax(self):
        """Negative tax rate should fail with E716"""
        action = {
            'type': 'player_rates',
            'tax_rate': -10,
            'science_rate': 70,
            'luxury_rate': 40,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E716')
        self.assertIn('between 0 and 100', result.error_message)

    def test_player_rates_negative_science(self):
        """Negative science rate should fail with E717"""
        action = {
            'type': 'player_rates',
            'tax_rate': 70,
            'science_rate': -10,
            'luxury_rate': 40,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E717')
        self.assertIn('between 0 and 100', result.error_message)

    def test_player_rates_negative_luxury(self):
        """Negative luxury rate should fail with E718"""
        action = {
            'type': 'player_rates',
            'tax_rate': 70,
            'science_rate': 40,
            'luxury_rate': -10,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E718')
        self.assertIn('between 0 and 100', result.error_message)

    def test_player_rates_over_100_tax(self):
        """Tax rate over 100 should fail with E716"""
        action = {
            'type': 'player_rates',
            'tax_rate': 150,
            'science_rate': 0,
            'luxury_rate': 0,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E716')

    def test_player_rates_over_100_science(self):
        """Science rate over 100 should fail with E717"""
        action = {
            'type': 'player_rates',
            'tax_rate': 0,
            'science_rate': 101,
            'luxury_rate': 0,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E717')

    def test_player_rates_over_100_luxury(self):
        """Luxury rate over 100 should fail with E718"""
        action = {
            'type': 'player_rates',
            'tax_rate': 0,
            'science_rate': 0,
            'luxury_rate': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E718')

    def test_player_rates_missing_tax_rate(self):
        """Missing tax_rate should fail with E710"""
        action = {
            'type': 'player_rates',
            'science_rate': 50,
            'luxury_rate': 50,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E710')
        self.assertIn('requires tax_rate', result.error_message)

    def test_player_rates_missing_science_rate(self):
        """Missing science_rate should fail with E711"""
        action = {
            'type': 'player_rates',
            'tax_rate': 50,
            'luxury_rate': 50,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E711')
        self.assertIn('requires science_rate', result.error_message)

    def test_player_rates_missing_luxury_rate(self):
        """Missing luxury_rate should fail with E712"""
        action = {
            'type': 'player_rates',
            'tax_rate': 50,
            'science_rate': 50,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E712')
        self.assertIn('requires luxury_rate', result.error_message)

    def test_player_rates_float_tax(self):
        """Float tax rate should fail with E713"""
        action = {
            'type': 'player_rates',
            'tax_rate': 40.5,
            'science_rate': 40,
            'luxury_rate': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E713')
        self.assertIn('must be an integer', result.error_message)

    def test_player_rates_float_science(self):
        """Float science rate should fail with E714"""
        action = {
            'type': 'player_rates',
            'tax_rate': 40,
            'science_rate': 39.5,
            'luxury_rate': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E714')
        self.assertIn('must be an integer', result.error_message)

    def test_player_rates_float_luxury(self):
        """Float luxury rate should fail with E715"""
        action = {
            'type': 'player_rates',
            'tax_rate': 40,
            'science_rate': 40,
            'luxury_rate': 20.5,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E715')
        self.assertIn('must be an integer', result.error_message)

    def test_player_rates_string_values(self):
        """String rate values should fail"""
        action = {
            'type': 'player_rates',
            'tax_rate': '40',
            'science_rate': 40,
            'luxury_rate': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E713')

    def test_player_rates_no_game_state_optimistic(self):
        """Player rates without game state should optimistically pass"""
        action = {
            'type': 'player_rates',
            'tax_rate': 40,
            'science_rate': 40,
            'luxury_rate': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        self.assertTrue(result.is_valid)

    def test_player_rates_various_valid_combinations(self):
        """Test various valid rate combinations"""
        valid_combinations = [
            (33, 33, 34),
            (50, 25, 25),
            (25, 50, 25),
            (25, 25, 50),
            (60, 20, 20),
            (10, 80, 10),
            (0, 0, 100),
            (100, 0, 0),
            (0, 100, 0),
        ]
        
        for tax, science, luxury in valid_combinations:
            action = {
                'type': 'player_rates',
                'tax_rate': tax,
                'science_rate': science,
                'luxury_rate': luxury,
                'player_id': 0
            }
            result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
            self.assertTrue(result.is_valid, 
                          f"Rates {tax}/{science}/{luxury} should be valid")


if __name__ == '__main__':
    unittest.main()
