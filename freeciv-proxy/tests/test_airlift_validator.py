import unittest
from action_validator import LLMActionValidator, ValidationResult, ActionType

class TestAirliftValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        self.default_game_state = {
            'units': {
                600: {
                    'id': 600,
                    'owner': 0,
                    'type': 'Musketeers',
                    'tile': 100,
                    'homecity': 10
                },
                601: {
                    'id': 601,
                    'owner': 1,
                    'type': 'Riflemen',
                    'tile': 200,
                    'homecity': 20
                }
            },
            'cities': {
                10: {
                    'id': 10,
                    'name': 'Capital',
                    'owner': 0,
                    'has_airport': True
                },
                11: {
                    'id': 11,
                    'name': 'Remote City',
                    'owner': 0,
                    'has_airport': True
                },
                12: {
                    'id': 12,
                    'name': 'Small Town',
                    'owner': 0,
                    'has_airport': False
                }
            },
            'players': {
                0: {'id': 0, 'gold': 100},
                1: {'id': 1, 'gold': 50}
            },
            'unit_actions': {
                600: [
                    {'action_type': 'airlift', 'action_id': 44, 'probability': 100,
                     'target_city_id': 11, 'name': 'Airlift Unit'}
                ]
            }
        }

    def test_airlift_valid(self):
        action = {'type': 'airlift', 'unit_id': 600, 'target_city_id': 11, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_airlift_missing_unit_id(self):
        action = {'type': 'airlift', 'target_city_id': 11, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_airlift_missing_target_city_id(self):
        action = {'type': 'airlift', 'unit_id': 600, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_airlift_unit_not_found(self):
        action = {'type': 'airlift', 'unit_id': 999, 'target_city_id': 11, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_airlift_not_owner(self):
        action = {'type': 'airlift', 'unit_id': 601, 'target_city_id': 11, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_airlift_action_not_available(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][600] = [
            {'action_type': 'move', 'probability': 100}  # No airlift action
        ]
        action = {'type': 'airlift', 'unit_id': 600, 'target_city_id': 11, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_airlift_probability_zero(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][600] = [
            {'action_type': 'airlift', 'action_id': 44, 'probability': 0,
             'target_city_id': 11, 'name': 'Airlift Unit'}
        ]
        action = {'type': 'airlift', 'unit_id': 600, 'target_city_id': 11, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_airlift_no_game_state(self):
        action = {'type': 'airlift', 'unit_id': 600, 'target_city_id': 11, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)

if __name__ == '__main__':
    unittest.main()
