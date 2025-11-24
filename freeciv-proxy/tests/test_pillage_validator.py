import unittest
from action_validator import LLMActionValidator, ValidationResult, ActionType

class TestPillageValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        self.default_game_state = {
            'units': {
                400: {
                    'id': 400,
                    'owner': 0,
                    'type': 'Warriors',
                    'can_pillage': True,
                    'moves_left': 2,
                    'tile': 100
                },
                401: {
                    'id': 401,
                    'owner': 0,
                    'type': 'Settlers',
                    'can_pillage': False,
                    'moves_left': 2,
                    'tile': 105
                },
                402: {
                    'id': 402,
                    'owner': 1,
                    'type': 'Phalanx',
                    'can_pillage': True,
                    'moves_left': 2,
                    'tile': 200
                }
            },
            'players': {
                0: {'id': 0, 'gold': 100},
                1: {'id': 1, 'gold': 50}
            },
            'unit_actions': {
                400: [
                    {'action_type': 'pillage', 'probability': 100, 'name': 'Pillage'}
                ],
                401: [
                    {'action_type': 'build_city', 'probability': 100}
                ]
            },
            'tiles': {
                100: {'id': 100, 'has_improvements': True},
                105: {'id': 105, 'has_improvements': False}
            }
        }

    def test_pillage_valid(self):
        action = {'type': 'pillage', 'unit_id': 400, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_pillage_missing_unit_id(self):
        action = {'type': 'pillage', 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_pillage_unit_not_found(self):
        action = {'type': 'pillage', 'unit_id': 999, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_pillage_not_owner(self):
        action = {'type': 'pillage', 'unit_id': 402, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_pillage_unit_busy(self):
        game_state = self.default_game_state.copy()
        game_state['units'][400]['busy'] = True
        action = {'type': 'pillage', 'unit_id': 400, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E110')

    def test_pillage_no_capability(self):
        action = {'type': 'pillage', 'unit_id': 401, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_pillage_no_movement(self):
        game_state = self.default_game_state.copy()
        game_state['units'][400]['moves_left'] = 0
        action = {'type': 'pillage', 'unit_id': 400, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E111')

    def test_pillage_no_improvements(self):
        game_state = self.default_game_state.copy()
        game_state['units'][401]['tile'] = 105
        game_state['units'][401]['can_pillage'] = True
        game_state['unit_actions'][401] = []  # No actions available
        action = {'type': 'pillage', 'unit_id': 401, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_pillage_action_not_available(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][400] = [
            {'action_type': 'attack', 'probability': 100}  # No pillage action
        ]
        action = {'type': 'pillage', 'unit_id': 400, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_pillage_action_probability_zero(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][400] = [
            {'action_type': 'pillage', 'probability': 0, 'name': 'Pillage'}
        ]
        action = {'type': 'pillage', 'unit_id': 400, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_pillage_no_game_state(self):
        action = {'type': 'pillage', 'unit_id': 400, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)  # Should pass without game state validation

if __name__ == '__main__':
    unittest.main()
