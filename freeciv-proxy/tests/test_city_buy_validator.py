import unittest
from action_validator import LLMActionValidator, ValidationResult, ActionType

class TestCityBuyValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        self.default_game_state = {
            'cities': {
                100: {
                    'id': 100,
                    'owner': 0,
                    'name': 'TestCity',
                    'production': {'name': 'Warrior', 'buy_cost': 50},
                    'buy_cost': 50,
                    'can_buy': True
                },
                101: {
                    'id': 101,
                    'owner': 1,
                    'name': 'EnemyCity',
                    'production': {'name': 'Settler', 'buy_cost': 100},
                    'buy_cost': 100,
                    'can_buy': True
                }
            },
            'players': {
                0: {'id': 0, 'gold': 100},
                1: {'id': 1, 'gold': 200}
            }
        }

    def test_city_buy_valid(self):
        action = {'type': 'city_buy', 'city_id': 100, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_city_buy_missing_city_id(self):
        action = {'type': 'city_buy', 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E202')

    def test_city_buy_city_not_found(self):
        action = {'type': 'city_buy', 'city_id': 999, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E202')

    def test_city_buy_not_owner(self):
        action = {'type': 'city_buy', 'city_id': 101, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E202')

    def test_city_buy_insufficient_gold(self):
        game_state = self.default_game_state.copy()
        game_state['players'][0]['gold'] = 30
        action = {'type': 'city_buy', 'city_id': 100, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E201')

    def test_city_buy_no_production(self):
        game_state = self.default_game_state.copy()
        game_state['cities'][100]['production'] = {'name': None}
        action = {'type': 'city_buy', 'city_id': 100, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E203')

    def test_city_buy_empty_production_name(self):
        game_state = self.default_game_state.copy()
        game_state['cities'][100]['production'] = {'name': ''}
        action = {'type': 'city_buy', 'city_id': 100, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E203')

    def test_city_buy_purchase_unavailable(self):
        game_state = self.default_game_state.copy()
        game_state['cities'][100]['can_buy'] = False
        action = {'type': 'city_buy', 'city_id': 100, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E204')

    def test_city_buy_exact_gold(self):
        game_state = self.default_game_state.copy()
        game_state['players'][0]['gold'] = 50
        action = {'type': 'city_buy', 'city_id': 100, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertTrue(result.is_valid)

    def test_city_buy_no_game_state(self):
        action = {'type': 'city_buy', 'city_id': 100, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)  # Should pass without game state validation

if __name__ == '__main__':
    unittest.main()
