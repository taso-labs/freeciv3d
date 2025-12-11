"""Test legal action generation and normalization"""

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
        assert normalized['production_type'] == 'Warrior'

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
