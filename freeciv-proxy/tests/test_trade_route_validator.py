import unittest
from action_validator import LLMActionValidator, ActionType

class TestTradeRouteValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        # Trade route is restricted - add capability explicitly
        self.validator.add_capability(ActionType.TRADE_ROUTE)
        self.player_id = 0
        self.base_game_state = {
            'units': {
                900: {'id': 900, 'owner': 0, 'type': 'Caravan', 'moves_left': 1},
                901: {'id': 901, 'owner': 0, 'type': 'Warriors', 'moves_left': 1},
                902: {'id': 902, 'owner': 1, 'type': 'Caravan', 'moves_left': 1},
            },
            'cities': {
                40: {'id': 40, 'name': 'Foreign City', 'owner': 1},
                41: {'id': 41, 'name': 'Domestic City', 'owner': 0},
            },
            'players': {
                0: {'id': 0, 'gold': 100},
                1: {'id': 1, 'gold': 50}
            },
            'unit_actions': {
                900: [
                    {'action_type': 'trade_route', 'action_id': 20, 'probability': 100, 'target_city_id': 40}
                ]
            }
        }

    def test_trade_route_valid(self):
        action = {'type': 'trade_route', 'unit_id': 900, 'target_city_id': 40, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertTrue(result.is_valid)

    def test_missing_unit_id(self):
        action = {'type': 'trade_route', 'target_city_id': 40, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_missing_target_city(self):
        action = {'type': 'trade_route', 'unit_id': 900, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_unit_not_owner(self):
        action = {'type': 'trade_route', 'unit_id': 902, 'target_city_id': 40, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_invalid_unit_type(self):
        action = {'type': 'trade_route', 'unit_id': 901, 'target_city_id': 40, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E410')

    def test_target_city_not_found(self):
        action = {'type': 'trade_route', 'unit_id': 900, 'target_city_id': 999, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_domestic_trade_not_allowed(self):
        action = {'type': 'trade_route', 'unit_id': 900, 'target_city_id': 41, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_domestic_trade_allowed(self):
        # Add server action targeting domestic city
        gs = self.base_game_state.copy()
        gs['unit_actions'][900] = [{'action_type': 'trade_route', 'action_id': 20, 'probability': 100, 'target_city_id': 41}]  # type: ignore[arg-type]
        action = {'type': 'trade_route', 'unit_id': 900, 'target_city_id': 41, 'allow_domestic': True, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, gs)
        self.assertTrue(result.is_valid)

    def test_action_not_available(self):
        gs = self.base_game_state.copy()
        gs['unit_actions'][900] = [{'action_type': 'move', 'probability': 100}]  # type: ignore[arg-type]
        action = {'type': 'trade_route', 'unit_id': 900, 'target_city_id': 40, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, gs)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_probability_zero(self):
        gs = self.base_game_state.copy()
        gs['unit_actions'][900] = [{'action_type': 'trade_route', 'action_id': 20, 'probability': 0, 'target_city_id': 40}]  # type: ignore[arg-type]
        action = {'type': 'trade_route', 'unit_id': 900, 'target_city_id': 40, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, gs)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

if __name__ == '__main__':
    unittest.main()
