import unittest
from action_validator import LLMActionValidator, ValidationResult, ActionType

class TestEmbassyValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        self.default_game_state = {
            'units': {
                700: {
                    'id': 700,
                    'owner': 0,
                    'type': 'Diplomat',
                    'tile': 100
                },
                701: {
                    'id': 701,
                    'owner': 0,
                    'type': 'Spy',
                    'tile': 100
                },
                702: {
                    'id': 702,
                    'owner': 0,
                    'type': 'Warriors',
                    'tile': 100,
                    'can_establish_embassy': False
                },
                703: {
                    'id': 703,
                    'owner': 1,
                    'type': 'Diplomat',
                    'tile': 200
                }
            },
            'cities': {
                20: {
                    'id': 20,
                    'name': 'Foreign Capital',
                    'owner': 1
                },
                21: {
                    'id': 21,
                    'name': 'Allied City',
                    'owner': 2
                }
            },
            'players': {
                0: {'id': 0, 'gold': 100},
                1: {'id': 1, 'gold': 50},
                2: {'id': 2, 'gold': 75}
            },
            'unit_actions': {
                700: [
                    {'action_type': 'establish_embassy', 'action_id': 0, 'probability': 100,
                     'target_city_id': 20, 'name': 'Establish Embassy'}
                ],
                701: [
                    {'action_type': 'establish_embassy', 'action_id': 0, 'probability': 100,
                     'target_city_id': 20, 'name': 'Establish Embassy'}
                ]
            }
        }

    def test_embassy_valid_diplomat(self):
        action = {'type': 'establish_embassy', 'unit_id': 700, 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_embassy_valid_spy(self):
        action = {'type': 'establish_embassy', 'unit_id': 701, 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_embassy_missing_unit_id(self):
        action = {'type': 'establish_embassy', 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_embassy_missing_target_city_id(self):
        action = {'type': 'establish_embassy', 'unit_id': 700, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_embassy_unit_not_found(self):
        action = {'type': 'establish_embassy', 'unit_id': 999, 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_embassy_not_owner(self):
        action = {'type': 'establish_embassy', 'unit_id': 703, 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_embassy_invalid_unit_type(self):
        action = {'type': 'establish_embassy', 'unit_id': 702, 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E312')

    def test_embassy_action_not_available(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][700] = [
            {'action_type': 'move', 'probability': 100}  # No embassy action
        ]
        action = {'type': 'establish_embassy', 'unit_id': 700, 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_embassy_probability_zero(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][700] = [
            {'action_type': 'establish_embassy', 'action_id': 0, 'probability': 0,
             'target_city_id': 20, 'name': 'Establish Embassy'}
        ]
        action = {'type': 'establish_embassy', 'unit_id': 700, 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_embassy_no_game_state(self):
        action = {'type': 'establish_embassy', 'unit_id': 700, 'target_city_id': 20, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)

if __name__ == '__main__':
    unittest.main()
