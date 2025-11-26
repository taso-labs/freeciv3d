"""
Phase 3: Worker Action Validator Tests

Tests validation logic for worker/terrain improvement actions:
- unit_build_road
- unit_build_irrigation  
- unit_build_mine
- unit_clean_pollution
- unit_clean_fallout
- unit_transform_terrain
- cultivate
- plant
- base
"""

import unittest
from unittest.mock import Mock
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator, ValidationResult


class TestWorkerValidators(unittest.TestCase):
    """Test validators for worker/terrain improvement actions"""

    def setUp(self):
        """Set up test fixtures"""
        self.validator = LLMActionValidator()
        
        # Sample game state with worker units
        self.sample_game_state = {
            'map': {'width': 80, 'height': 50},
            'units': {
                '100': {
                    'id': 100,
                    'owner': 0,
                    'moves_left': 3,
                    'x': 10,
                    'y': 15,
                    'busy': False,
                    'activity': 0,  # ACTIVITY_IDLE
                    'type': 'Settlers'
                },
                '200': {
                    'id': 200,
                    'owner': 1,
                    'moves_left': 2,
                    'x': 20,
                    'y': 25,
                    'busy': False,
                    'activity': 0
                }
            },
            'players': {
                '0': {'id': 0, 'name': 'Player1'},
                '1': {'id': 1, 'name': 'Player2'}
            },
            'cities': {}
        }

    # ========================================================================
    # unit_build_road Tests
    # ========================================================================

    def test_unit_build_road_valid(self):
        """Valid build road action should pass"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_build_road_unit_not_found(self):
        """Build road with non-existent unit should fail with E070"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E070')

    def test_unit_build_road_wrong_owner(self):
        """Build road with enemy unit should fail with E071"""
        action = {
            'type': 'unit_build_road',
            'unit_id': 200,  # Owned by player 1
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E071')

    def test_unit_build_road_unit_busy(self):
        """Build road with busy unit should fail with E072"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['100'] = game_state['units']['100'].copy()
        game_state['units']['100']['busy'] = True
        
        action = {
            'type': 'unit_build_road',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E072')

    # ========================================================================
    # unit_build_irrigation Tests
    # ========================================================================

    def test_unit_build_irrigation_valid(self):
        """Valid build irrigation action should pass"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_build_irrigation_unit_not_found(self):
        """Build irrigation with non-existent unit should fail with E080"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E080')

    def test_unit_build_irrigation_wrong_owner(self):
        """Build irrigation with enemy unit should fail with E081"""
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E081')

    def test_unit_build_irrigation_no_moves(self):
        """Build irrigation with no moves should fail with E082"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['100'] = game_state['units']['100'].copy()
        game_state['units']['100']['moves_left'] = 0
        
        action = {
            'type': 'unit_build_irrigation',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E082')

    # ========================================================================
    # unit_build_mine Tests
    # ========================================================================

    def test_unit_build_mine_valid(self):
        """Valid build mine action should pass"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_build_mine_unit_not_found(self):
        """Build mine with non-existent unit should fail with E090"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E090')

    def test_unit_build_mine_wrong_owner(self):
        """Build mine with enemy unit should fail with E091"""
        action = {
            'type': 'unit_build_mine',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E091')

    # ========================================================================
    # unit_clean_pollution Tests
    # ========================================================================

    def test_unit_clean_pollution_valid(self):
        """Valid clean pollution action should pass"""
        action = {
            'type': 'unit_clean_pollution',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_clean_pollution_unit_not_found(self):
        """Clean pollution with non-existent unit should fail with E100"""
        action = {
            'type': 'unit_clean_pollution',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E100')

    def test_unit_clean_pollution_wrong_owner(self):
        """Clean pollution with enemy unit should fail with E101"""
        action = {
            'type': 'unit_clean_pollution',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E101')

    # ========================================================================
    # unit_clean_fallout Tests
    # ========================================================================

    def test_unit_clean_fallout_valid(self):
        """Valid clean fallout action should pass"""
        action = {
            'type': 'unit_clean_fallout',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_clean_fallout_unit_not_found(self):
        """Clean fallout with non-existent unit should fail with E103"""
        action = {
            'type': 'unit_clean_fallout',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E103')

    def test_unit_clean_fallout_wrong_owner(self):
        """Clean fallout with enemy unit should fail with E104"""
        action = {
            'type': 'unit_clean_fallout',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E104')

    # ========================================================================
    # unit_transform_terrain Tests
    # ========================================================================

    def test_unit_transform_terrain_valid(self):
        """Valid transform terrain action should pass"""
        action = {
            'type': 'unit_transform_terrain',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_unit_transform_terrain_unit_not_found(self):
        """Transform terrain with non-existent unit should fail with E106"""
        action = {
            'type': 'unit_transform_terrain',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E106')

    def test_unit_transform_terrain_wrong_owner(self):
        """Transform terrain with enemy unit should fail with E107"""
        action = {
            'type': 'unit_transform_terrain',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E107')

    # ========================================================================
    # cultivate Tests
    # ========================================================================

    def test_cultivate_valid(self):
        """Valid cultivate action should pass"""
        action = {
            'type': 'cultivate',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_cultivate_unit_not_found(self):
        """Cultivate with non-existent unit should fail with E145"""
        action = {
            'type': 'cultivate',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E145')

    def test_cultivate_wrong_owner(self):
        """Cultivate with enemy unit should fail with E146"""
        action = {
            'type': 'cultivate',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E146')

    # ========================================================================
    # plant Tests
    # ========================================================================

    def test_plant_valid(self):
        """Valid plant action should pass"""
        action = {
            'type': 'plant',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_plant_unit_not_found(self):
        """Plant with non-existent unit should fail with E148"""
        action = {
            'type': 'plant',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E148')

    def test_plant_wrong_owner(self):
        """Plant with enemy unit should fail with E149"""
        action = {
            'type': 'plant',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E149')

    # ========================================================================
    # base Tests
    # ========================================================================

    def test_base_valid(self):
        """Valid base building action should pass"""
        action = {
            'type': 'base',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertTrue(result.is_valid)

    def test_base_unit_not_found(self):
        """Base with non-existent unit should fail with E151"""
        action = {
            'type': 'base',
            'unit_id': 999,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E151')

    def test_base_wrong_owner(self):
        """Base with enemy unit should fail with E152"""
        action = {
            'type': 'base',
            'unit_id': 200,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=self.sample_game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E152')

    def test_base_unit_busy(self):
        """Base with busy unit should fail with E153"""
        game_state = self.sample_game_state.copy()
        game_state['units'] = game_state['units'].copy()
        game_state['units']['100'] = game_state['units']['100'].copy()
        game_state['units']['100']['busy'] = True
        
        action = {
            'type': 'base',
            'unit_id': 100,
            'player_id': 0
        }
        result = self.validator.validate_action(action, player_id=0, game_state=game_state)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E153')

    # ========================================================================
    # General Tests
    # ========================================================================

    def test_worker_actions_no_game_state_optimistic(self):
        """All worker actions should optimistically pass without game state"""
        worker_actions = [
            'unit_build_road',
            'unit_build_irrigation',
            'unit_build_mine',
            'unit_clean_pollution',
            'unit_clean_fallout',
            'unit_transform_terrain',
            'cultivate',
            'plant',
            'base'
        ]
        
        for action_type in worker_actions:
            action = {
                'type': action_type,
                'unit_id': 100,
                'player_id': 0
            }
            result = self.validator.validate_action(action, player_id=0, game_state=None)
            self.assertTrue(result.is_valid, f"{action_type} should optimistically pass")


if __name__ == '__main__':
    unittest.main()
