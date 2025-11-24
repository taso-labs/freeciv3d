import unittest
from action_validator import LLMActionValidator, ValidationResult, ActionType

class TestTransportValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        self.default_game_state = {
            'units': {
                500: {  # Trireme (transport)
                    'id': 500,
                    'owner': 0,
                    'type': 'Trireme',
                    'can_transport': True,
                    'transport_capacity': 3,
                    'moves_left': 2,
                    'tile': 100
                },
                501: {  # Warrior (cargo)
                    'id': 501,
                    'owner': 0,
                    'type': 'Warriors',
                    'transported': False,
                    'transported_by': None,
                    'moves_left': 1,
                    'tile': 100
                },
                502: {  # Phalanx (on transport)
                    'id': 502,
                    'owner': 0,
                    'type': 'Phalanx',
                    'transported': True,
                    'transported_by': 500,
                    'moves_left': 0,
                    'tile': 100
                },
                503: {  # Enemy transport
                    'id': 503,
                    'owner': 1,
                    'type': 'Trireme',
                    'can_transport': True,
                    'moves_left': 2,
                    'tile': 105
                },
                504: {  # Settler (on transport 500)
                    'id': 504,
                    'owner': 0,
                    'type': 'Settlers',
                    'transported': True,
                    'transported_by': 500,
                    'moves_left': 0,
                    'tile': 100
                }
            },
            'players': {
                0: {'id': 0, 'gold': 100},
                1: {'id': 1, 'gold': 50}
            },
            'unit_actions': {
                501: [
                    {'action_type': 'transport_board', 'action_id': 68, 'probability': 100, 
                     'target_unit_id': 500, 'name': 'Board Transport'}
                ],
                502: [
                    {'action_type': 'transport_deboard', 'action_id': 71, 'probability': 100,
                     'name': 'Deboard Transport'}
                ],
                500: [
                    {'action_type': 'transport_unload', 'action_id': 83, 'probability': 100,
                     'target_unit_id': 502, 'name': 'Unload Unit'}
                ]
            }
        }

    def test_transport_board_valid(self):
        action = {'type': 'transport_board', 'unit_id': 501, 'transport_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_transport_board_missing_unit_id(self):
        action = {'type': 'transport_board', 'transport_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_transport_board_missing_transport_id(self):
        action = {'type': 'transport_board', 'unit_id': 501, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_transport_board_unit_not_found(self):
        action = {'type': 'transport_board', 'unit_id': 999, 'transport_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_transport_board_transport_not_found(self):
        action = {'type': 'transport_board', 'unit_id': 501, 'transport_id': 999, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_transport_board_not_owner_of_cargo(self):
        game_state = self.default_game_state.copy()
        game_state['units'][501]['owner'] = 1  # Enemy owns cargo
        action = {'type': 'transport_board', 'unit_id': 501, 'transport_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_transport_board_not_owner_of_transport(self):
        action = {'type': 'transport_board', 'unit_id': 501, 'transport_id': 503, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_transport_board_unit_busy(self):
        game_state = self.default_game_state.copy()
        game_state['units'][501]['busy'] = True
        action = {'type': 'transport_board', 'unit_id': 501, 'transport_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E110')

    def test_transport_board_no_movement(self):
        game_state = self.default_game_state.copy()
        game_state['units'][501]['moves_left'] = 0
        action = {'type': 'transport_board', 'unit_id': 501, 'transport_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E111')

    def test_transport_board_action_not_available(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][501] = [
            {'action_type': 'move', 'probability': 100}  # No board action
        ]
        action = {'type': 'transport_board', 'unit_id': 501, 'transport_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_transport_deboard_valid(self):
        action = {'type': 'transport_deboard', 'unit_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_transport_deboard_missing_unit_id(self):
        action = {'type': 'transport_deboard', 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_transport_deboard_unit_not_found(self):
        action = {'type': 'transport_deboard', 'unit_id': 999, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_transport_deboard_not_owner(self):
        game_state = self.default_game_state.copy()
        game_state['units'][502]['owner'] = 1
        action = {'type': 'transport_deboard', 'unit_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_transport_deboard_not_on_transport(self):
        action = {'type': 'transport_deboard', 'unit_id': 501, 'player_id': self.player_id}  # Unit 501 is not transported
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E353')

    def test_transport_deboard_action_not_available(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][502] = [
            {'action_type': 'wait', 'probability': 100}  # No deboard action
        ]
        action = {'type': 'transport_deboard', 'unit_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_transport_unload_valid(self):
        action = {'type': 'transport_unload', 'unit_id': 500, 'cargo_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_transport_unload_missing_unit_id(self):
        action = {'type': 'transport_unload', 'cargo_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_transport_unload_missing_cargo_id(self):
        action = {'type': 'transport_unload', 'unit_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_transport_unload_transport_not_found(self):
        action = {'type': 'transport_unload', 'unit_id': 999, 'cargo_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_transport_unload_cargo_not_found(self):
        action = {'type': 'transport_unload', 'unit_id': 500, 'cargo_id': 999, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_transport_unload_not_owner_of_transport(self):
        game_state = self.default_game_state.copy()
        game_state['units'][500]['owner'] = 1
        action = {'type': 'transport_unload', 'unit_id': 500, 'cargo_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_transport_unload_not_owner_of_cargo(self):
        game_state = self.default_game_state.copy()
        game_state['units'][502]['owner'] = 1
        action = {'type': 'transport_unload', 'unit_id': 500, 'cargo_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E113')

    def test_transport_unload_cargo_not_on_transport(self):
        action = {'type': 'transport_unload', 'unit_id': 500, 'cargo_id': 501, 'player_id': self.player_id}  # Unit 501 not transported
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=self.default_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E353')

    def test_transport_unload_cargo_on_different_transport(self):
        game_state = self.default_game_state.copy()
        game_state['units'][502]['transported_by'] = 503  # On different transport
        action = {'type': 'transport_unload', 'unit_id': 500, 'cargo_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E353')

    def test_transport_unload_action_not_available(self):
        game_state = self.default_game_state.copy()
        game_state['unit_actions'][500] = [
            {'action_type': 'move', 'probability': 100}  # No unload action
        ]
        action = {'type': 'transport_unload', 'unit_id': 500, 'cargo_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_transport_board_no_game_state(self):
        action = {'type': 'transport_board', 'unit_id': 501, 'transport_id': 500, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)

    def test_transport_deboard_no_game_state(self):
        action = {'type': 'transport_deboard', 'unit_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)

    def test_transport_unload_no_game_state(self):
        action = {'type': 'transport_unload', 'unit_id': 500, 'cargo_id': 502, 'player_id': self.player_id}
        result = self.validator.validate_action(action, player_id=self.player_id, game_state=None)
        self.assertTrue(result.is_valid)

if __name__ == '__main__':
    unittest.main()
