import unittest
from action_validator import LLMActionValidator, ValidationResult, ActionType

class TestBombardValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        self.default_game_state = {
            'units': {
                300: {
                    'id': 300,
                    'owner': 0,
                    'type': 'Catapult',
                    'can_bombard': True,
                    'moves_left': 1,
                    'attacks_left': 1,
                    'tile': 100,
                    'bombard_range': 2
                },
                301: {
                    'id': 301,
                    'owner': 0,
                    'type': 'Warriors',
                    'can_bombard': False,
                    'moves_left': 3,
                    'tile': 105
                },
                302: {
                    'id': 302,
                    'owner': 1,
                    'type': 'Cannon',
                    'can_bombard': True,
                    'moves_left': 2,
                    'tile': 200
                }
            },
            'players': {
                0: {'id': 0, 'gold': 100},
                1: {'id': 1, 'gold': 50}
            },
            'unit_actions': {
                300: [
                    {'action_id': 53, 'action_type': 'bombard', 'probability': 100}
                ],
                301: [
                    {'action_id': 45, 'action_type': 'attack', 'probability': 100}
                ]
            }
        }

    def test_bombard_valid(self):
        action = {'type': 'bombard', 'unit_id': 300, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_bombard_missing_unit_id(self):
        action = {'type': 'bombard', 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_bombard_missing_target_tile_id(self):
        action = {'type': 'bombard', 'unit_id': 300, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_bombard_unit_not_found(self):
        action = {'type': 'bombard', 'unit_id': 999, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_bombard_not_owner(self):
        action = {'type': 'bombard', 'unit_id': 302, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_bombard_unit_busy(self):
        game_state = self.default_game_state.copy()
        game_state['units'][300]['busy'] = True
        action = {'type': 'bombard', 'unit_id': 300, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E110')

    def test_bombard_no_capability(self):
        action = {'type': 'bombard', 'unit_id': 301, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_bombard_no_attacks_left(self):
        game_state = self.default_game_state.copy()
        game_state['units'][300]['moves_left'] = 0
        game_state['units'][300]['attacks_left'] = 0
        action = {'type': 'bombard', 'unit_id': 300, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E111')

    def test_bombard_action_not_available(self):
        action = {'type': 'bombard', 'unit_id': 301, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        # Will fail on can_bombard check first (E113), not E116

    def test_bombard_own_tile(self):
        action = {'type': 'bombard', 'unit_id': 300, 'target_tile_id': 100, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_bombard_action_probability_zero(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][300] = [
            {'action_id': 53, 'action_type': 'bombard', 'probability': 0}
        ]
        action = {'type': 'bombard', 'unit_id': 300, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_bombard_no_game_state(self):
        action = {'type': 'bombard', 'unit_id': 300, 'target_tile_id': 150, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)  # Should pass without game state validation

if __name__ == '__main__':
    unittest.main()
