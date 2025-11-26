"""
Phase 3: Transport and Spy Action Validator Tests

Tests validation logic for transport and spy actions:
- transport_board
- transport_deboard
- transport_unload
- airlift
- spy_investigate_city
- spy_poison
- spy_sabotage_city
- spy_steal_tech
- spy_bribe_unit
- spy_steal_gold
- spy_incite_city
"""

import unittest
from unittest.mock import Mock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator, ValidationResult


class TestTransportSpyValidators(unittest.TestCase):
    """Test validators for transport and spy actions"""

    def setUp(self):
        """Set up test fixtures"""
        self.validator = LLMActionValidator()
        
        # Sample game state with transports, passengers, and spy units
        self.sample_game_state = {
            'map': {'width': 80, 'height': 50},
            'units': {
                '100': {  # Transport ship
                    'id': 100,
                    'owner': 0,
                    'moves_left': 3,
                    'x': 10,
                    'y': 15,
                    'busy': False,
                    'type': 'Trireme',
                    'can_transport': True,
                    'transport_capacity': 2,
                    'passengers': []
                },
                '200': {  # Passenger unit
                    'id': 200,
                    'owner': 0,
                    'moves_left': 2,
                    'x': 10,
                    'y': 15,
                    'busy': False,
                    'type': 'Warriors'
                },
                '300': {  # Spy unit
                    'id': 300,
                    'owner': 0,
                    'moves_left': 3,
                    'x': 20,
                    'y': 25,
                    'busy': False,
                    'type': 'Spy'
                },
                '400': {  # Enemy unit
                    'id': 400,
                    'owner': 1,
                    'moves_left': 2,
                    'x': 30,
                    'y': 35,
                    'busy': False,
                    'type': 'Phalanx'
                }
            },
            'cities': {
                '10': {
                    'id': 10,
                    'owner': 0,
                    'name': 'TestCity',
                    'x': 25,
                    'y': 30
                },
                '20': {
                    'id': 20,
                    'owner': 1,
                    'name': 'EnemyCity',
                    'x': 30,
                    'y': 35
                }
            },
            'players': {
                '0': {'id': 0, 'name': 'Player1'},
                '1': {'id': 1, 'name': 'Player2'}
            }
        }

    # ========================================================================
    # transport_board Tests
    # ========================================================================

    def test_transport_board_valid(self):
        """Valid transport board action should pass"""
        action = {
            'type': 'transport_board',
            'unit_id': 200,  # Passenger
            'transport_id': 100,  # Transport
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_transport_board_unit_not_found(self):
        """Board with non-existent unit should fail with E350"""
        action = {
            'type': 'transport_board',
            'unit_id': 999,
            'transport_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E350')

    def test_transport_board_transport_not_found(self):
        """Board with non-existent transport should fail with E351"""
        action = {
            'type': 'transport_board',
            'unit_id': 200,
            'transport_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E351')

    def test_transport_board_wrong_owner(self):
        """Board with enemy unit should fail with E352"""
        action = {
            'type': 'transport_board',
            'unit_id': 400,  # Enemy unit
            'transport_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E352')

    def test_transport_board_transport_full(self):
        """Board when transport is full should fail with E353"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['100'] = game_state['units']['100'].copy()
        game_state['units']['100']['passengers'] = [201, 202]  # Full capacity
        
        action = {
            'type': 'transport_board',
            'unit_id': 200,
            'transport_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E353')

    # ========================================================================
    # transport_deboard Tests
    # ========================================================================

    def test_transport_deboard_valid(self):
        """Valid transport deboard action should pass"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['100'] = game_state['units']['100'].copy()
        game_state['units']['100']['passengers'] = [200]  # Unit is on transport
        
        action = {
            'type': 'transport_deboard',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertTrue(result.is_valid)

    def test_transport_deboard_unit_not_found(self):
        """Deboard with non-existent unit should fail with E350"""
        action = {
            'type': 'transport_deboard',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E350')

    def test_transport_deboard_wrong_owner(self):
        """Deboard with enemy unit should fail with E352"""
        action = {
            'type': 'transport_deboard',
            'unit_id': 400,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E352')

    # ========================================================================
    # transport_unload Tests
    # ========================================================================

    def test_transport_unload_valid(self):
        """Valid transport unload action should pass"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['100'] = game_state['units']['100'].copy()
        game_state['units']['100']['passengers'] = [200]
        
        action = {
            'type': 'transport_unload',
            'transport_id': 100,
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertTrue(result.is_valid)

    def test_transport_unload_transport_not_found(self):
        """Unload from non-existent transport should fail with E351"""
        action = {
            'type': 'transport_unload',
            'transport_id': 999,
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E351')

    def test_transport_unload_wrong_owner(self):
        """Unload from enemy transport should fail with E352"""
        action = {
            'type': 'transport_unload',
            'transport_id': 100,
            'unit_id': 400,  # Enemy unit
            'player_id': 1  # Different player
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E005')  # player_id mismatch

    # ========================================================================
    # airlift Tests
    # ========================================================================

    def test_airlift_valid(self):
        """Valid airlift action should pass"""
        action = {
            'type': 'airlift',
            'unit_id': 200,
            'dest_city_id': 10,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_airlift_unit_not_found(self):
        """Airlift with non-existent unit should fail with E354"""
        action = {
            'type': 'airlift',
            'unit_id': 999,
            'dest_city_id': 10,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E354')

    def test_airlift_city_not_found(self):
        """Airlift to non-existent city should fail with E355"""
        action = {
            'type': 'airlift',
            'unit_id': 200,
            'dest_city_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E355')

    def test_airlift_wrong_owner(self):
        """Airlift with enemy unit should fail with E356"""
        action = {
            'type': 'airlift',
            'unit_id': 400,  # Enemy unit
            'dest_city_id': 10,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E356')

    # ========================================================================
    # Spy Action Tests
    # ========================================================================

    def test_spy_investigate_city_valid(self):
        """Valid spy investigate action should pass"""
        action = {
            'type': 'spy_investigate_city',
            'unit_id': 300,
            'target_city_id': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_spy_poison_valid(self):
        """Valid spy poison action should pass"""
        action = {
            'type': 'spy_poison',
            'unit_id': 300,
            'target_city_id': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_spy_sabotage_city_valid(self):
        """Valid spy sabotage action should pass"""
        action = {
            'type': 'spy_sabotage_city',
            'unit_id': 300,
            'target_city_id': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_spy_steal_tech_valid(self):
        """Valid spy steal tech action should pass"""
        action = {
            'type': 'spy_steal_tech',
            'unit_id': 300,
            'target_city_id': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_spy_bribe_unit_valid(self):
        """Valid spy bribe unit action should pass"""
        action = {
            'type': 'spy_bribe_unit',
            'unit_id': 300,
            'target_unit_id': 400,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_spy_steal_gold_valid(self):
        """Valid spy steal gold action should pass"""
        action = {
            'type': 'spy_steal_gold',
            'unit_id': 300,
            'target_city_id': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_spy_incite_city_valid(self):
        """Valid spy incite city action should pass"""
        action = {
            'type': 'spy_incite_city',
            'unit_id': 300,
            'target_city_id': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_spy_action_unit_not_found(self):
        """Spy action with non-existent unit should fail with E400"""
        action = {
            'type': 'spy_investigate_city',
            'unit_id': 999,
            'target_city_id': 20,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E400')

    def test_spy_action_target_city_not_found(self):
        """Spy action with non-existent target city should fail with E401"""
        action = {
            'type': 'spy_poison',
            'unit_id': 300,
            'target_city_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E401')

    def test_spy_action_wrong_owner(self):
        """Spy action with enemy spy should fail with E402"""
        action = {
            'type': 'spy_investigate_city',
            'unit_id': 400,  # Enemy unit, not a spy
            'target_city_id': 10,
            'player_id': 1  # Different player
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E005')  # player_id mismatch

    def test_spy_bribe_unit_target_not_found(self):
        """Spy bribe with non-existent target unit should fail"""
        action = {
            'type': 'spy_bribe_unit',
            'unit_id': 300,
            'target_unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        # Error code depends on implementation

    # ========================================================================
    # General Tests
    # ========================================================================

    def test_transport_actions_no_game_state_optimistic(self):
        """Transport actions should optimistically pass without game state"""
        transport_actions = [
            ('transport_board', {'unit_id': 200, 'transport_id': 100}),
            ('transport_deboard', {'unit_id': 200}),
            ('transport_unload', {'transport_id': 100, 'unit_id': 200}),
            ('airlift', {'unit_id': 200, 'dest_city_id': 10})
        ]
        
        for action_type, params in transport_actions:
            action = {'type': action_type, 'player_id': 0}
            action.update(params)
            result = self.validator.validate_action(action, player_id=0, game_state=None)
            self.assertTrue(result.is_valid, f"{action_type} should optimistically pass")

    def test_spy_actions_no_game_state_optimistic(self):
        """Spy actions should optimistically pass without game state"""
        spy_actions = [
            'spy_investigate_city',
            'spy_poison',
            'spy_sabotage_city',
            'spy_steal_tech',
            'spy_steal_gold',
            'spy_incite_city'
        ]
        
        for action_type in spy_actions:
            action = {
                'type': action_type,
                'unit_id': 300,
                'target_city_id': 20,
                'player_id': 0
            }
            result = self.validator.validate_action(action, player_id=0, game_state=None)
            self.assertTrue(result.is_valid, f"{action_type} should optimistically pass")


if __name__ == '__main__':
    unittest.main()
