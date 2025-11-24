import unittest
from action_validator import LLMActionValidator, ActionType

class TestSpyActionsValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 0
        # Base game state for spy actions
        self.base_game_state = {
            'units': {
                800: {'id': 800, 'owner': 0, 'type': 'Spy', 'moves_left': 1},
                801: {'id': 801, 'owner': 0, 'type': 'Diplomat', 'moves_left': 1},
                802: {'id': 802, 'owner': 0, 'type': 'Warriors', 'moves_left': 1},
                850: {'id': 850, 'owner': 1, 'type': 'Legion', 'moves_left': 1},
            },
            'cities': {
                30: {'id': 30, 'name': 'Enemy City', 'owner': 1},
                31: {'id': 31, 'name': 'Friendly City', 'owner': 0},
            },
            'players': {
                0: {'id': 0, 'gold': 100},
                1: {'id': 1, 'gold': 50}
            },
            'unit_actions': {
                800: [
                    {'action_type': 'investigate_city', 'action_id': 2, 'probability': 100, 'target_city_id': 30},
                    {'action_type': 'poison', 'action_id': 4, 'probability': 100, 'target_city_id': 30},
                    {'action_type': 'sabotage_city', 'action_id': 8, 'probability': 100, 'target_city_id': 30},
                    {'action_type': 'steal_tech', 'action_id': 14, 'probability': 100, 'target_city_id': 30},
                    {'action_type': 'bribe_unit', 'action_id': 23, 'probability': 100, 'target_unit_id': 850, 'cost': 40},
                ]
            }
        }

    def test_investigate_city_valid(self):
        action = {'type': 'spy_investigate_city', 'unit_id': 800, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertTrue(result.is_valid)

    def test_poison_valid(self):
        action = {'type': 'spy_poison', 'unit_id': 800, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertTrue(result.is_valid)

    def test_sabotage_city_valid(self):
        action = {'type': 'spy_sabotage_city', 'unit_id': 800, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertTrue(result.is_valid)

    def test_steal_tech_valid(self):
        action = {'type': 'spy_steal_tech', 'unit_id': 800, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertTrue(result.is_valid)

    def test_bribe_unit_valid(self):
        action = {'type': 'spy_bribe_unit', 'unit_id': 800, 'target_unit_id': 850, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertTrue(result.is_valid)

    def test_missing_unit_id(self):
        action = {'type': 'spy_investigate_city', 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E109')

    def test_missing_target_city(self):
        action = {'type': 'spy_investigate_city', 'unit_id': 800, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_invalid_unit_type(self):
        action = {'type': 'spy_investigate_city', 'unit_id': 802, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E402')

    def test_action_not_available(self):
        gs = self.base_game_state.copy()
        gs['unit_actions'][800] = [{'action_type': 'move', 'probability': 100}]  # type: ignore[arg-type]
        action = {'type': 'spy_poison', 'unit_id': 800, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, gs)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_probability_zero(self):
        gs = self.base_game_state.copy()
        gs['unit_actions'][800] = [{'action_type': 'poison', 'action_id': 4, 'probability': 0, 'target_city_id': 30}]  # type: ignore[arg-type]
        action = {'type': 'spy_poison', 'unit_id': 800, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, gs)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E116')

    def test_insufficient_gold_bribe(self):
        gs = self.base_game_state.copy()
        gs['players'][0]['gold'] = 10  # Less than cost 40  # type: ignore[index]
        action = {'type': 'spy_bribe_unit', 'unit_id': 800, 'target_unit_id': 850, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, gs)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E403')

    def test_bribe_own_unit(self):
        action = {'type': 'spy_bribe_unit', 'unit_id': 800, 'target_unit_id': 801, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_bribe_target_not_found(self):
        action = {'type': 'spy_bribe_unit', 'unit_id': 800, 'target_unit_id': 999, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, self.base_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E115')

    def test_detected_flag(self):
        gs = self.base_game_state.copy()
        gs['unit_actions'][800] = [{'action_type': 'sabotage_city', 'action_id': 8, 'probability': 100, 'target_city_id': 30, 'detected': True}]  # type: ignore[arg-type]
        action = {'type': 'spy_sabotage_city', 'unit_id': 800, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, gs)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E400')

    def test_mission_failed_flag(self):
        gs = self.base_game_state.copy()
        gs['unit_actions'][800] = [{'action_type': 'poison', 'action_id': 4, 'probability': 100, 'target_city_id': 30, 'mission_failed': True}]  # type: ignore[arg-type]
        action = {'type': 'spy_poison', 'unit_id': 800, 'target_city_id': 30, 'player_id': self.player_id}
        result = self.validator.validate_action(action, self.player_id, gs)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E401')

if __name__ == '__main__':
    unittest.main()
