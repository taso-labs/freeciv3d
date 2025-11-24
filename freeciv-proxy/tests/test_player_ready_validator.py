import unittest
from action_validator import LLMActionValidator, ValidationResult, ActionType

class TestPlayerReadyValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        self.default_game_state = {
            'game_phase': 'nations_selecting',
            'players': {
                0: {'id': 0, 'ready': False},
                1: {'id': 1, 'ready': False}
            },
            'min_players': 2
        }

    def test_player_ready_valid(self):
        action = {'type': 'player_ready', 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_player_ready_wrong_phase(self):
        game_state = self.default_game_state.copy()
        game_state['game_phase'] = 'running'
        action = {'type': 'player_ready', 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E300')

    def test_player_ready_already_ready(self):
        game_state = self.default_game_state.copy()
        game_state['players'][0]['ready'] = True
        action = {'type': 'player_ready', 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, game_state)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.error_code, 'E301')

    def test_player_ready_insufficient_players(self):
        game_state = self.default_game_state.copy()
        game_state['players'] = {0: {'id': 0, 'ready': False}}
        game_state['min_players'] = 2
        action = {'type': 'player_ready', 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E302')

    def test_player_ready_ready_to_start_phase(self):
        game_state = self.default_game_state.copy()
        game_state['game_phase'] = 'ready_to_start'
        action = {'type': 'player_ready', 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

if __name__ == '__main__':
    unittest.main()
