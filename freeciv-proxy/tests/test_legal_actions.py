"""Test legal action generation and normalization"""

import os
import secrets

# Set required environment variable for StateCache before any imports
os.environ.setdefault('CACHE_HMAC_SECRET', secrets.token_hex(32))

from unittest.mock import Mock, patch
from state_extractor import StateExtractor


class TestLegalActionNormalization:
    """Test action format normalization"""

    def test_normalize_move_action(self):
        """Test normalizing move action to packet format"""
        extractor = StateExtractor()
        
        internal_action = {
            'action': 'move',
            'params': {'direction': 'n', 'target': {'x': 10, 'y': 20}},
            'is_valid': True,
            'unit_id': 5
        }
        
        normalized = extractor._normalize_action_format(internal_action)
        
        assert normalized is not None
        assert normalized['type'] == 'unit_move'
        assert normalized['unit_id'] == 5
        assert normalized['dest_x'] == 10
        assert normalized['dest_y'] == 20
        assert normalized['is_valid'] is True

    def test_normalize_build_city_action(self):
        """Test normalizing build_city action"""
        extractor = StateExtractor()
        
        internal_action = {
            'action': 'build_city',
            'params': {},
            'is_valid': True,
            'unit_id': 3
        }
        
        normalized = extractor._normalize_action_format(internal_action)
        
        assert normalized is not None
        assert normalized['type'] == 'unit_build_city'
        assert normalized['unit_id'] == 3

    def test_normalize_city_production_action(self):
        """Test normalizing city production action"""
        extractor = StateExtractor()
        
        internal_action = {
            'action': 'change_production',
            'params': {'to': 'Warrior'},
            'is_valid': True,
            'city_id': 7
        }
        
        normalized = extractor._normalize_action_format(internal_action)

        assert normalized is not None
        assert normalized['type'] == 'city_production'
        assert normalized['city_id'] == 7
        assert normalized['target']['production'] == 'Warrior'

    def test_normalize_tech_research_action(self):
        """Test normalizing tech research action"""
        extractor = StateExtractor()
        
        internal_action = {
            'action': 'research_tech',
            'params': {},
            'is_valid': True,
            'tech': 'Alphabet',
            'tech_id': 1
        }
        
        normalized = extractor._normalize_action_format(internal_action)
        
        assert normalized is not None
        assert normalized['type'] == 'tech_research'
        assert normalized['tech'] == 'Alphabet'
        assert normalized['tech_id'] == 1

    def test_normalize_end_turn_action(self):
        """Test normalizing end_turn action"""
        extractor = StateExtractor()
        
        internal_action = {
            'action': 'end_turn',
            'params': {},
            'is_valid': True
        }
        
        normalized = extractor._normalize_action_format(internal_action)
        
        assert normalized is not None
        assert normalized['type'] == 'end_turn'

    def test_normalize_invalid_action_returns_none(self):
        """Test that invalid actions are filtered out"""
        extractor = StateExtractor()
        
        internal_action = {
            'action': 'move',
            'params': {'target': {'x': 0, 'y': 0}},
            'is_valid': False,
            'reason': 'Cannot move here',
            'unit_id': 5
        }
        
        normalized = extractor._normalize_action_format(internal_action)
        
        # Invalid actions should return None
        assert normalized is None

    def test_normalize_action_preserves_priority(self):
        """Test that priority is preserved in normalized action"""
        extractor = StateExtractor()
        
        internal_action = {
            'action': 'move',
            'params': {'direction': 'n', 'target': {'x': 10, 'y': 20}},
            'is_valid': True,
            'unit_id': 5,
            'priority': 8
        }
        
        normalized = extractor._normalize_action_format(internal_action)
        
        assert normalized is not None
        assert normalized['priority'] == 8

    def test_normalize_unknown_action_type(self):
        """Test normalizing unknown action type"""
        extractor = StateExtractor()
        
        internal_action = {
            'action': 'custom_action',
            'params': {'foo': 'bar'},
            'is_valid': True
        }
        
        normalized = extractor._normalize_action_format(internal_action)
        
        # Unknown types should still work, with action converted to type
        assert normalized is not None
        assert normalized.get('type') == 'custom_action'

    def test_get_legal_actions_calls_normalization(self):
        """Test that get_legal_actions properly normalizes actions"""
        extractor = StateExtractor()
        
        # Mock civcom with get_full_state that returns basic state
        mock_civcom = Mock()
        mock_civcom.get_full_state.return_value = {
            'units': {
                '1': {'id': 1, 'type': 'warriors', 'owner': 0, 'x': 10, 'y': 10, 'moves_left': 2}
            },
            'cities': {
                '1': {'id': 1, 'owner': 0, 'x': 10, 'y': 10}
            }
        }
        
        with patch.object(extractor, '_get_civcom_for_game', return_value=mock_civcom):
            with patch.object(extractor, '_generate_legal_actions_from_state') as mock_gen:
                # Return some sample actions in internal format
                mock_gen.return_value = [
                    {
                        'action': 'end_turn',
                        'params': {},
                        'is_valid': True,
                        'priority': 10
                    },
                    {
                        'action': 'move',
                        'params': {'direction': 'n', 'target': {'x': 10, 'y': 9}},
                        'is_valid': True,
                        'unit_id': 1,
                        'priority': 5
                    }
                ]
                
                actions = extractor.get_legal_actions('game_1', 0)
                
                assert len(actions) == 2
                assert actions[0]['type'] == 'end_turn'  # Higher priority first
                assert actions[1]['type'] == 'unit_move'
                assert actions[1]['unit_id'] == 1

    def test_get_legal_actions_filters_invalid(self):
        """Test that invalid actions are filtered out"""
        extractor = StateExtractor()
        
        mock_civcom = Mock()
        mock_civcom.get_full_state.return_value = {'units': {}, 'cities': {}}
        
        with patch.object(extractor, '_get_civcom_for_game', return_value=mock_civcom):
            with patch.object(extractor, '_generate_legal_actions_from_state') as mock_gen:
                mock_gen.return_value = [
                    {
                        'action': 'end_turn',
                        'params': {},
                        'is_valid': True,
                        'priority': 10
                    },
                    {
                        'action': 'move',
                        'params': {'target': {'x': 0, 'y': 0}},
                        'is_valid': False,
                        'reason': 'No moves left',
                        'unit_id': 1,
                        'priority': 5
                    }
                ]
                
                actions = extractor.get_legal_actions('game_1', 0)

                # Only valid action should be returned
                assert len(actions) == 1
                assert actions[0]['type'] == 'end_turn'


class TestMovesLeftPrecondition:
    """Test that actions requiring movement are invalid when moves_left = 0.

    This tests the fix for E024 errors where units with no moves remaining
    were being offered terrain improvement, combat, and other movement-consuming
    actions in their legal_actions list.
    """

    def _create_mock_civcom(self, can_do_actions=None):
        """Create a mock civcom that enables specific actions via action_probabilities"""
        mock = Mock()
        mock.player_id = 0
        mock.tiles = {}
        mock.player_cities = {}
        mock.other_cities = {}
        mock.other_units = {}  # Other player's units
        mock.player_units = {}  # Our units
        mock.unit_types = {1: {'name': 'Workers', 'unit_class': 1}}
        mock.unit_classes = {1: {'name': 'Land'}}
        mock.get_terrain_class = Mock(return_value=0)  # TC_LAND
        mock.is_unit_class_native_to_terrain = Mock(return_value=True)
        mock.can_city_be_founded_at = Mock(return_value=(False, "Not a settler"))
        # Map info for coordinate calculations
        mock.map_info = {'width': 80, 'height': 50, 'wrap_x': True, 'wrap_y': False}
        # Diplomacy info
        mock.diplomacy = {}
        mock.player_info = {'player_id': 0}
        # Set up action probabilities for allowed actions
        if can_do_actions:
            mock.action_probabilities = {1: {action_id: {'max': 200} for action_id in can_do_actions}}
        else:
            mock.action_probabilities = {}
        return mock

    def test_terrain_actions_invalid_when_no_moves(self):
        """Test that terrain improvement actions are invalid when moves_left = 0"""
        from state_extractor import StateExtractor, civcom_registry
        from civcom import (
            ACTION_ROAD, ACTION_IRRIGATE, ACTION_MINE, ACTION_BASE,
            ACTION_TRANSFORM_TERRAIN, ACTION_CULTIVATE, ACTION_PLANT
        )

        extractor = StateExtractor()

        # Unit with 0 moves
        unit = {
            'id': 1,
            'type_id': 1,
            'type': 'Workers',
            'owner': 0,
            'x': 10,
            'y': 10,
            'tile': 100,
            'moves_left': 0,  # No moves remaining
            'activity': 'idle'
        }

        state = {'units': {'1': unit}, 'cities': {}}

        # Enable terrain actions in the mock
        terrain_action_ids = [ACTION_ROAD, ACTION_IRRIGATE, ACTION_MINE, ACTION_BASE,
                               ACTION_TRANSFORM_TERRAIN, ACTION_CULTIVATE, ACTION_PLANT]
        mock_civcom = self._create_mock_civcom(can_do_actions=terrain_action_ids)

        # Patch civcom_registry to return our mock
        with patch.object(extractor, '_get_civcom_for_player', return_value=mock_civcom):
            actions = extractor._generate_unit_actions(unit, state, player_id=0)

        # Find terrain improvement actions
        terrain_action_names = ['build_road', 'build_irrigation', 'build_mine',
                                 'build_base', 'transform', 'cultivate', 'plant']
        terrain_actions = [a for a in actions if a.get('action') in terrain_action_names]

        # All terrain actions should be marked as invalid with "No moves left" reason
        assert len(terrain_actions) > 0, "Expected terrain actions to be generated"
        for action in terrain_actions:
            assert action.get('is_valid') is False, \
                f"Action {action.get('action')} should be invalid when moves_left=0"
            assert action.get('reason') == "No moves left", \
                f"Action {action.get('action')} should have reason 'No moves left'"

    def test_terrain_actions_valid_when_has_moves(self):
        """Test that terrain improvement actions are valid when moves_left > 0"""
        from state_extractor import StateExtractor
        from civcom import ACTION_ROAD

        extractor = StateExtractor()

        # Unit with moves
        unit = {
            'id': 1,
            'type_id': 1,
            'type': 'Workers',
            'owner': 0,
            'x': 10,
            'y': 10,
            'tile': 100,
            'moves_left': 3,  # Has moves
            'activity': 'idle'
        }

        state = {'units': {'1': unit}, 'cities': {}}

        mock_civcom = self._create_mock_civcom(can_do_actions=[ACTION_ROAD])

        with patch.object(extractor, '_get_civcom_for_player', return_value=mock_civcom):
            actions = extractor._generate_unit_actions(unit, state, player_id=0)

        # Find build_road action
        road_actions = [a for a in actions if a.get('action') == 'build_road']

        assert len(road_actions) > 0, "Expected build_road action to be generated"
        # Should be valid since unit has moves
        assert road_actions[0].get('is_valid') is True, \
            "build_road should be valid when moves_left > 0"

    def test_combat_actions_invalid_when_no_moves(self):
        """Test that combat actions are invalid when moves_left = 0"""
        from state_extractor import StateExtractor
        from civcom import (
            ACTION_ATTACK, ACTION_SUICIDE_ATTACK,
            ACTION_CAPTURE_UNITS, ACTION_CONQUER_CITY, ACTION_BOMBARD
        )

        extractor = StateExtractor()

        # Unit with 0 moves
        unit = {
            'id': 1,
            'type_id': 1,
            'type': 'Warriors',
            'owner': 0,
            'x': 10,
            'y': 10,
            'tile': 100,
            'moves_left': 0,  # No moves remaining
            'activity': 'idle'
        }

        state = {'units': {'1': unit}, 'cities': {}}

        combat_action_ids = [ACTION_ATTACK, ACTION_SUICIDE_ATTACK,
                             ACTION_CAPTURE_UNITS, ACTION_CONQUER_CITY, ACTION_BOMBARD]
        mock_civcom = self._create_mock_civcom(can_do_actions=combat_action_ids)

        with patch.object(extractor, '_get_civcom_for_player', return_value=mock_civcom):
            actions = extractor._generate_unit_actions(unit, state, player_id=0)

        # Find combat actions
        combat_action_names = ['attack', 'suicide_attack', 'capture', 'conquer_city', 'bombard']
        combat_actions = [a for a in actions if a.get('action') in combat_action_names]

        # All combat actions should be marked as invalid with "No moves left" reason
        assert len(combat_actions) > 0, "Expected combat actions to be generated"
        for action in combat_actions:
            assert action.get('is_valid') is False, \
                f"Action {action.get('action')} should be invalid when moves_left=0"
            assert action.get('reason') == "No moves left", \
                f"Action {action.get('action')} should have reason 'No moves left'"

    def test_pillage_clean_invalid_when_no_moves(self):
        """Test that pillage and clean actions are invalid when moves_left = 0"""
        from state_extractor import StateExtractor
        from civcom import ACTION_PILLAGE, ACTION_CLEAN

        extractor = StateExtractor()

        # Unit with 0 moves
        unit = {
            'id': 1,
            'type_id': 1,
            'type': 'Warriors',
            'owner': 0,
            'x': 10,
            'y': 10,
            'tile': 100,
            'moves_left': 0,  # No moves remaining
            'activity': 'idle'
        }

        state = {'units': {'1': unit}, 'cities': {}}

        mock_civcom = self._create_mock_civcom(can_do_actions=[ACTION_PILLAGE, ACTION_CLEAN])

        with patch.object(extractor, '_get_civcom_for_player', return_value=mock_civcom):
            actions = extractor._generate_unit_actions(unit, state, player_id=0)

        # Find pillage/clean actions
        pillage_clean = [a for a in actions if a.get('action') in ['pillage', 'clean']]

        # All should be marked as invalid with "No moves left" reason
        assert len(pillage_clean) > 0, "Expected pillage/clean actions to be generated"
        for action in pillage_clean:
            assert action.get('is_valid') is False, \
                f"Action {action.get('action')} should be invalid when moves_left=0"
            assert action.get('reason') == "No moves left", \
                f"Action {action.get('action')} should have reason 'No moves left'"

    def test_movement_actions_not_generated_when_no_moves(self):
        """Test that movement actions are not generated at all when moves_left = 0"""
        from state_extractor import StateExtractor

        extractor = StateExtractor()

        # Unit with 0 moves
        unit = {
            'id': 1,
            'type_id': 1,
            'type': 'Warriors',
            'owner': 0,
            'x': 10,
            'y': 10,
            'tile': 100,
            'moves_left': 0,  # No moves remaining
            'activity': 'idle'
        }

        state = {'units': {'1': unit}, 'cities': {}}

        mock_civcom = self._create_mock_civcom()

        with patch.object(extractor, '_get_civcom_for_player', return_value=mock_civcom):
            actions = extractor._generate_unit_actions(unit, state, player_id=0)

        # Find move actions
        move_actions = [a for a in actions if a.get('action') == 'move']

        # Movement actions should not be generated at all (this behavior was already correct)
        assert len(move_actions) == 0, \
            "Movement actions should not be generated when moves_left=0"
