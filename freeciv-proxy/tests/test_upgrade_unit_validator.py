import unittest
from action_validator import LLMActionValidator, ValidationResult, ActionType

class TestUpgradeUnitValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        self.default_game_state = {
            'units': {
                200: {
                    'id': 200,
                    'owner': 0,
                    'type': 'Warriors',
                    'homecity': 100
                },
                201: {
                    'id': 201,
                    'owner': 1,
                    'type': 'Phalanx',
                    'homecity': 101
                }
            },
            'players': {
                0: {'id': 0, 'gold': 150},
                1: {'id': 1, 'gold': 50}
            },
            'unit_actions': {
                200: [
                    {'action_id': 42, 'action_type': 'upgrade', 'probability': 100, 'cost': 100}
                ],
                201: [
                    {'action_id': 42, 'action_type': 'upgrade', 'probability': 100, 'cost': 80}
                ]
            }
        }

    def test_upgrade_unit_valid(self):
        action = {'type': 'upgrade_unit', 'unit_id': 200, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_upgrade_unit_missing_unit_id(self):
        action = {'type': 'upgrade_unit', 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_upgrade_unit_not_found(self):
        action = {'type': 'upgrade_unit', 'unit_id': 999, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_upgrade_unit_not_owner(self):
        action = {'type': 'upgrade_unit', 'unit_id': 201, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_upgrade_unit_no_upgrade_path(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][200] = [
            {'action_id': 45, 'action_type': 'attack', 'probability': 100}  # No upgrade action
        ]
        action = {'type': 'upgrade_unit', 'unit_id': 200, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E205')

    def test_upgrade_unit_upgrade_probability_zero(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][200] = [
            {'action_id': 42, 'action_type': 'upgrade', 'probability': 0, 'cost': 100}
        ]
        action = {'type': 'upgrade_unit', 'unit_id': 200, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E205')

    def test_upgrade_unit_insufficient_gold(self):
        game_state = self.default_game_state.copy()
        game_state['players'][0]['gold'] = 50
        action = {'type': 'upgrade_unit', 'unit_id': 200, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E206')

    def test_upgrade_unit_exact_gold(self):
        game_state = self.default_game_state.copy()
        game_state['players'][0]['gold'] = 100
        action = {'type': 'upgrade_unit', 'unit_id': 200, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertTrue(result.is_valid)

    def test_upgrade_unit_free_upgrade(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][200] = [
            {'action_id': 42, 'action_type': 'upgrade', 'probability': 100, 'cost': 0}
        ]
        game_state['players'][0]['gold'] = 0
        action = {'type': 'upgrade_unit', 'unit_id': 200, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertTrue(result.is_valid)

    def test_upgrade_unit_no_game_state(self):
        action = {'type': 'upgrade_unit', 'unit_id': 200, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)  # Should pass without game state validation

if __name__ == '__main__':
    unittest.main()
