"""
Test suite for advanced strategic actions (Phase 9).

Tests cover 6 advanced actions:
1. strike_building - Surgical strike on specific building
2. strike_production - Surgical strike on city production
3. marketplace - Convert caravan to gold at marketplace
4. expel_unit - Diplomatically expel foreign unit
5. spy_sabotage_unit - Sabotage specific enemy unit
6. player_rates - Set tax/science/luxury rates

These actions provide precision military strikes, economic controls, diplomacy, and advanced espionage.
"""

import unittest
from unittest import IsolatedAsyncioTestCase
from action_validator import LLMActionValidator, ValidationResult


class TestStrikeBuildingAction(IsolatedAsyncioTestCase):
    """Test strike_building action - surgical strike on specific building."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = LLMActionValidator()
        self.player_id = 1
        self.game_state = {
            'units': {
                '100': {'id': 100, 'owner': 1, 'type': 'Bomber', 'can_bombard': True},
                '101': {'id': 101, 'owner': 1, 'type': 'Fighter', 'can_bombard': True},
                '102': {'id': 102, 'owner': 1, 'type': 'Warrior', 'can_bombard': False}
            },
            'cities': {
                '200': {'id': 200, 'owner': 2, 'name': 'Enemy City'},
                '201': {'id': 201, 'owner': 1, 'name': 'My City'}
            }
        }

    def test_valid_strike_building(self):
        """Test valid strike_building action."""
        action = {
            'type': 'strike_building',
            'unit_id': 100,
            'target_city_id': 200,
            'building_id': 5
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_missing_unit_id(self):
        """Test missing unit_id."""
        action = {
            'type': 'strike_building',
            'target_city_id': 200,
            'building_id': 5
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E660')

    def test_missing_target_city_id(self):
        """Test missing target_city_id."""
        action = {
            'type': 'strike_building',
            'unit_id': 100,
            'building_id': 5
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E661')

    def test_missing_building_id(self):
        """Test missing building_id."""
        action = {
            'type': 'strike_building',
            'unit_id': 100,
            'target_city_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E662')

    def test_unit_not_found(self):
        """Test unit not found."""
        action = {
            'type': 'strike_building',
            'unit_id': 999,
            'target_city_id': 200,
            'building_id': 5
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E663')

    def test_not_owner_of_unit(self):
        """Test player doesn't own unit."""
        action = {
            'type': 'strike_building',
            'unit_id': 100,
            'target_city_id': 200,
            'building_id': 5
        }
        result = self.validator.validate_action(action, 2, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E664')

    def test_unit_cannot_strike(self):
        """Test unit cannot perform strikes."""
        action = {
            'type': 'strike_building',
            'unit_id': 102,  # Warrior cannot bombard
            'target_city_id': 200,
            'building_id': 5
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E665')

    def test_target_city_not_found(self):
        """Test target city not found."""
        action = {
            'type': 'strike_building',
            'unit_id': 100,
            'target_city_id': 999,
            'building_id': 5
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E666')

    def test_cannot_strike_own_city(self):
        """Test cannot strike own city."""
        action = {
            'type': 'strike_building',
            'unit_id': 100,
            'target_city_id': 201,  # Own city
            'building_id': 5
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E667')


class TestStrikeProductionAction(IsolatedAsyncioTestCase):
    """Test strike_production action - surgical strike on city production."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = LLMActionValidator()
        self.player_id = 1
        self.game_state = {
            'units': {
                '100': {'id': 100, 'owner': 1, 'type': 'Bomber', 'can_bombard': True}
            },
            'cities': {
                '200': {'id': 200, 'owner': 2, 'name': 'Enemy City'}
            }
        }

    def test_valid_strike_production(self):
        """Test valid strike_production action."""
        action = {
            'type': 'strike_production',
            'unit_id': 100,
            'target_city_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_missing_unit_id(self):
        """Test missing unit_id."""
        action = {
            'type': 'strike_production',
            'target_city_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E670')

    def test_missing_target_city_id(self):
        """Test missing target_city_id."""
        action = {
            'type': 'strike_production',
            'unit_id': 100
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E671')


class TestMarketplaceAction(IsolatedAsyncioTestCase):
    """Test marketplace action - convert caravan to gold."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = LLMActionValidator()
        self.player_id = 1
        self.game_state = {
            'units': {
                '100': {'id': 100, 'owner': 1, 'type': 'Caravan'},
                '101': {'id': 101, 'owner': 1, 'type': 'Freight'},
                '102': {'id': 102, 'owner': 1, 'type': 'Warrior'}
            },
            'cities': {
                '200': {'id': 200, 'owner': 1, 'name': 'My City'},
                '201': {'id': 201, 'owner': 2, 'name': 'Foreign City'}
            }
        }

    def test_valid_marketplace_caravan(self):
        """Test valid marketplace action with caravan."""
        action = {
            'type': 'marketplace',
            'unit_id': 100,
            'target_city_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_valid_marketplace_freight(self):
        """Test valid marketplace action with freight."""
        action = {
            'type': 'marketplace',
            'unit_id': 101,
            'target_city_id': 201
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_missing_unit_id(self):
        """Test missing unit_id."""
        action = {
            'type': 'marketplace',
            'target_city_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E680')

    def test_missing_target_city_id(self):
        """Test missing target_city_id."""
        action = {
            'type': 'marketplace',
            'unit_id': 100
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E681')

    def test_unit_not_caravan_or_freight(self):
        """Test unit is not caravan or freight."""
        action = {
            'type': 'marketplace',
            'unit_id': 102,  # Warrior
            'target_city_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E684')


class TestExpelUnitAction(IsolatedAsyncioTestCase):
    """Test expel_unit action - diplomatically expel foreign unit."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = LLMActionValidator()
        self.player_id = 1
        self.game_state = {
            'units': {
                '100': {'id': 100, 'owner': 1, 'type': 'Diplomat'},
                '200': {'id': 200, 'owner': 2, 'type': 'Warrior'},
                '201': {'id': 201, 'owner': 1, 'type': 'Settler'}
            }
        }

    def test_valid_expel_unit(self):
        """Test valid expel_unit action."""
        action = {
            'type': 'expel_unit',
            'unit_id': 100,
            'target_unit_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_missing_unit_id(self):
        """Test missing unit_id."""
        action = {
            'type': 'expel_unit',
            'target_unit_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E690')

    def test_missing_target_unit_id(self):
        """Test missing target_unit_id."""
        action = {
            'type': 'expel_unit',
            'unit_id': 100
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E691')

    def test_cannot_expel_own_unit(self):
        """Test cannot expel own unit."""
        action = {
            'type': 'expel_unit',
            'unit_id': 100,
            'target_unit_id': 201  # Own unit
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E695')


class TestSpySabotageUnitAction(IsolatedAsyncioTestCase):
    """Test spy_sabotage_unit action - sabotage specific enemy unit."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = LLMActionValidator()
        self.player_id = 1
        self.game_state = {
            'units': {
                '100': {'id': 100, 'owner': 1, 'type': 'Spy'},
                '101': {'id': 101, 'owner': 1, 'type': 'Diplomat'},
                '102': {'id': 102, 'owner': 1, 'type': 'Warrior'},
                '200': {'id': 200, 'owner': 2, 'type': 'Tank'},
                '201': {'id': 201, 'owner': 1, 'type': 'Settlers'}
            }
        }

    def test_valid_spy_sabotage_unit(self):
        """Test valid spy_sabotage_unit action with spy."""
        action = {
            'type': 'spy_sabotage_unit',
            'unit_id': 100,
            'target_unit_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_valid_diplomat_sabotage_unit(self):
        """Test valid spy_sabotage_unit action with diplomat."""
        action = {
            'type': 'spy_sabotage_unit',
            'unit_id': 101,
            'target_unit_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_missing_unit_id(self):
        """Test missing unit_id."""
        action = {
            'type': 'spy_sabotage_unit',
            'target_unit_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E700')

    def test_missing_target_unit_id(self):
        """Test missing target_unit_id."""
        action = {
            'type': 'spy_sabotage_unit',
            'unit_id': 100
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E701')

    def test_unit_not_spy_or_diplomat(self):
        """Test unit is not spy or diplomat."""
        action = {
            'type': 'spy_sabotage_unit',
            'unit_id': 102,  # Warrior
            'target_unit_id': 200
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E704')

    def test_cannot_sabotage_own_unit(self):
        """Test cannot sabotage own unit."""
        action = {
            'type': 'spy_sabotage_unit',
            'unit_id': 100,
            'target_unit_id': 201  # Own unit
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E706')


class TestPlayerRatesAction(IsolatedAsyncioTestCase):
    """Test player_rates action - set tax/science/luxury rates."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = LLMActionValidator()
        self.player_id = 1
        self.game_state = {}

    def test_valid_player_rates_balanced(self):
        """Test valid player_rates with balanced rates."""
        action = {
            'type': 'player_rates',
            'tax_rate': 40,
            'science_rate': 30,
            'luxury_rate': 30
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_valid_player_rates_max_science(self):
        """Test valid player_rates with max science."""
        action = {
            'type': 'player_rates',
            'tax_rate': 0,
            'science_rate': 100,
            'luxury_rate': 0
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_valid_player_rates_max_tax(self):
        """Test valid player_rates with max tax."""
        action = {
            'type': 'player_rates',
            'tax_rate': 100,
            'science_rate': 0,
            'luxury_rate': 0
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(result.is_valid)

    def test_missing_tax_rate(self):
        """Test missing tax_rate."""
        action = {
            'type': 'player_rates',
            'science_rate': 50,
            'luxury_rate': 50
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E710')

    def test_missing_science_rate(self):
        """Test missing science_rate."""
        action = {
            'type': 'player_rates',
            'tax_rate': 50,
            'luxury_rate': 50
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E711')

    def test_missing_luxury_rate(self):
        """Test missing luxury_rate."""
        action = {
            'type': 'player_rates',
            'tax_rate': 50,
            'science_rate': 50
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E712')

    def test_tax_rate_not_integer(self):
        """Test tax_rate is not integer."""
        action = {
            'type': 'player_rates',
            'tax_rate': '50',
            'science_rate': 30,
            'luxury_rate': 20
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E713')

    def test_tax_rate_negative(self):
        """Test tax_rate is negative."""
        action = {
            'type': 'player_rates',
            'tax_rate': -10,
            'science_rate': 60,
            'luxury_rate': 50
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E716')

    def test_tax_rate_over_100(self):
        """Test tax_rate over 100."""
        action = {
            'type': 'player_rates',
            'tax_rate': 110,
            'science_rate': 0,
            'luxury_rate': 0
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E716')

    def test_rates_dont_sum_to_100(self):
        """Test rates don't sum to 100."""
        action = {
            'type': 'player_rates',
            'tax_rate': 40,
            'science_rate': 40,
            'luxury_rate': 30  # Sum is 110
        }
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E719')


if __name__ == '__main__':
    unittest.main()
