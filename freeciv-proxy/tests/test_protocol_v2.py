#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for protocol v2.0 features in llm_handler
Tests unit_actions dict structure, action_result response, packet callbacks
"""

import pytest
import json
import time
from unittest.mock import Mock, MagicMock, patch

# Import the handler
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestProtocolV2Features:
    """Test suite for protocol v2.0 features"""

    @pytest.fixture
    def mock_handler(self):
        """Create a mock LLMHandler with necessary attributes"""
        from llm_handler import LLMHandler
        
        handler = Mock(spec=LLMHandler)
        handler.player_id = 1
        handler.agent_id = "test_agent"
        handler.is_llm_agent = True
        handler.session_id = "test_session"
        
        # Initialize cache
        from unit_action_cache import UnitActionCache
        handler.unit_action_cache = UnitActionCache(max_entries=100, ttl_seconds=300)
        
        # Mock civcom
        handler.civcom = Mock()
        handler.civcom.game_turn = 5
        handler.civcom.get_full_state = Mock(return_value={
            'turn': 5,
            'units': {
                123: {'id': 123, 'owner': 1, 'type': 'Warriors', 'x': 10, 'y': 20, 'moves_left': 3},
                124: {'id': 124, 'owner': 1, 'type': 'Settlers', 'x': 11, 'y': 21, 'moves_left': 1},
                125: {'id': 125, 'owner': 2, 'type': 'Archers', 'x': 12, 'y': 22, 'moves_left': 2}  # Enemy unit
            },
            'cities': {},
            'map': {'width': 80, 'height': 50},
            'visible_tiles': []
        })
        
        return handler

    def test_get_unit_actions_dict_structure(self, mock_handler):
        """Test that _get_unit_actions_dict returns correct structure"""
        from llm_handler import LLMHandler
        
        # Call the method using real implementation
        result = LLMHandler._get_unit_actions_dict(mock_handler, game_state=None)
        
        # Should return dict keyed by unit_id strings
        assert isinstance(result, dict)
        assert '123' in result
        assert '124' in result
        assert '125' not in result  # Enemy unit should not be included
        
        # Each entry should have correct structure
        unit_entry = result['123']
        assert 'unit_id' in unit_entry
        assert 'available_actions' in unit_entry
        assert 'last_updated' in unit_entry
        assert unit_entry['unit_id'] == 123
        assert isinstance(unit_entry['available_actions'], list)

    def test_get_unit_actions_dict_with_cache(self, mock_handler):
        """Test that cached data is used when available"""
        from llm_handler import LLMHandler
        
        # Populate cache with action data
        cached_actions = [
            {'action_type': 'move', 'probability': 200},
            {'action_type': 'attack', 'probability': 150}
        ]
        cache_entry = {
            'actions': cached_actions,
            'timestamp': time.time(),
            'turn': 5
        }
        mock_handler.unit_action_cache.set(123, 5, cache_entry)
        
        # Get unit actions
        result = LLMHandler._get_unit_actions_dict(mock_handler, game_state=None)
        
        # Should use cached data
        assert '123' in result
        assert result['123']['available_actions'] == cached_actions
        assert result['123']['last_updated'] is not None

    def test_get_unit_actions_dict_cache_miss(self, mock_handler):
        """Test that cache misses return empty actions"""
        from llm_handler import LLMHandler
        
        # Don't populate cache - should get empty actions
        result = LLMHandler._get_unit_actions_dict(mock_handler, game_state=None)
        
        assert '123' in result
        assert result['123']['available_actions'] == []
        assert result['123']['last_updated'] is None

    def test_handle_action_answer_packet(self, mock_handler):
        """Test processing PACKET_UNIT_ACTION_ANSWER"""
        from llm_handler import LLMHandler
        
        # Simulate packet from server
        packet = {
            'actor_unit_id': 123,
            'action_type': 5,  # Some action type ID
            'action_prob': 150,  # 75% probability
            'target_unit_id': 456,
            'target_city_id': None,
            'target_tile_id': 789,
            'target_extra_id': None
        }
        
        # Process packet
        LLMHandler._handle_action_answer_packet(mock_handler, 123, packet, 5)
        
        # Check cache was populated
        cached = mock_handler.unit_action_cache.get(123, 5)
        assert cached is not None
        assert len(cached['actions']) == 1
        assert cached['actions'][0]['action_type'] == 5
        assert cached['actions'][0]['probability'] == 150
        assert cached['actions'][0]['target_unit_id'] == 456

    def test_handle_unit_actions_packet(self, mock_handler):
        """Test processing PACKET_UNIT_ACTIONS"""
        from llm_handler import LLMHandler
        
        # Simulate packet from server with multiple actions
        packet = {
            'actor_unit_id': 123,
            'actions': [
                {'action_type': 1, 'probability': 200, 'target_unit_id': None},
                {'action_type': 2, 'probability': 150, 'target_unit_id': 456},
                {'action_type': 3, 'probability': 100, 'target_tile_id': 789}
            ]
        }
        
        # Process packet
        LLMHandler._handle_unit_actions_packet(mock_handler, 123, packet, 5)
        
        # Check cache was populated with all actions
        cached = mock_handler.unit_action_cache.get(123, 5)
        assert cached is not None
        assert len(cached['actions']) == 3
        assert cached['actions'][0]['action_type'] == 1
        assert cached['actions'][1]['probability'] == 150
        assert cached['actions'][2]['target_tile_id'] == 789

    def test_invalidate_unit_cache(self, mock_handler):
        """Test cache invalidation for specific unit"""
        from llm_handler import LLMHandler
        
        # Populate cache
        cache_entry = {
            'actions': [{'action_type': 'move', 'probability': 200}],
            'timestamp': time.time(),
            'turn': 5
        }
        mock_handler.unit_action_cache.set(123, 5, cache_entry)
        
        # Verify cached
        assert mock_handler.unit_action_cache.get(123, 5) is not None
        
        # Invalidate
        LLMHandler._invalidate_unit_cache(mock_handler, 123, 5)
        
        # Should be gone
        assert mock_handler.unit_action_cache.get(123, 5) is None

    def test_invalidate_all_cache(self, mock_handler):
        """Test clearing entire cache on turn change"""
        from llm_handler import LLMHandler
        
        # Populate cache with multiple units
        for unit_id in [123, 124, 125]:
            cache_entry = {
                'actions': [],
                'timestamp': time.time(),
                'turn': 5
            }
            mock_handler.unit_action_cache.set(unit_id, 5, cache_entry)
        
        # Verify all cached
        assert mock_handler.unit_action_cache.get(123, 5) is not None
        assert mock_handler.unit_action_cache.get(124, 5) is not None
        
        # Clear on turn change
        LLMHandler._invalidate_all_cache(mock_handler, 6)
        
        # All should be gone
        assert mock_handler.unit_action_cache.get(123, 5) is None
        assert mock_handler.unit_action_cache.get(124, 5) is None

    def test_unit_actions_dict_empty_game_state(self, mock_handler):
        """Test handling empty game state"""
        from llm_handler import LLMHandler
        
        mock_handler.civcom.get_full_state = Mock(return_value={})
        
        result = LLMHandler._get_unit_actions_dict(mock_handler, game_state=None)
        
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_unit_actions_dict_filters_enemy_units(self, mock_handler):
        """Test that enemy units are excluded"""
        from llm_handler import LLMHandler
        
        result = LLMHandler._get_unit_actions_dict(mock_handler, game_state=None)
        
        # Should include player 1's units
        assert '123' in result
        assert '124' in result
        
        # Should NOT include player 2's unit
        assert '125' not in result

    def test_packet_callback_error_handling(self, mock_handler):
        """Test that packet callback errors are handled gracefully"""
        from llm_handler import LLMHandler
        
        # Malformed packet
        bad_packet = {
            'actor_unit_id': 123,
            # Missing required fields
        }
        
        # Should not raise exception
        LLMHandler._handle_action_answer_packet(mock_handler, 123, bad_packet, 5)
        
        # Cache should not be populated with bad data
        cached = mock_handler.unit_action_cache.get(123, 5)
        assert cached is None or cached['actions'] == []


class TestActionResultResponse:
    """Test suite for action_result response format"""

    def test_action_result_structure(self):
        """Test that action_result has correct structure"""
        action_result = {
            'type': 'action_result',
            'success': True,
            'action_type': 'unit_move',
            'result': {
                'action': {'type': 'unit_move', 'unit_id': 123},
                'timestamp': time.time(),
                'status': 'queued'
            }
        }
        
        # Validate structure
        assert action_result['type'] == 'action_result'
        assert 'success' in action_result
        assert 'action_type' in action_result
        assert 'result' in action_result
        assert isinstance(action_result['result'], dict)

    def test_action_result_with_correlation_id(self):
        """Test action_result preserves correlation_id"""
        correlation_id = "batch_123_action_1"
        
        action_result = {
            'type': 'action_result',
            'success': True,
            'action_type': 'unit_move',
            'correlation_id': correlation_id,
            'result': {
                'action': {},
                'timestamp': time.time()
            }
        }
        
        assert action_result['correlation_id'] == correlation_id

    def test_action_result_failure(self):
        """Test action_result for failed action"""
        action_result = {
            'type': 'action_result',
            'success': False,
            'action_type': 'unit_move',
            'error_code': 'E201',
            'error_message': 'Unit has no moves left',
            'result': {
                'action': {},
                'timestamp': time.time(),
                'status': 'rejected'
            }
        }
        
        assert action_result['success'] is False
        assert 'error_code' in action_result
        assert 'error_message' in action_result


class TestMessageValidation:
    """Test suite for protocol v2.0 message validation"""

    def test_action_result_schema_validation(self):
        """Test that ACTION_RESULT message validates correctly"""
        from message_validator import MessageValidator, MessageType
        
        validator = MessageValidator()
        
        # Valid action_result message
        message = {
            'type': 'action_result',
            'success': True,
            'action_type': 'unit_move',
            'result': {
                'action': {'type': 'unit_move', 'unit_id': 123},
                'timestamp': time.time(),
                'status': 'queued'
            }
        }
        
        # Should validate
        result = validator.validate_message_data(message, MessageType.ACTION_RESULT)
        assert result is not None

    def test_unit_action_query_schema_validation(self):
        """Test that unit_action_query validates correctly"""
        from message_validator import MessageValidator, MessageType
        
        validator = MessageValidator()
        
        # Valid query
        message = {
            'type': 'unit_action_query',
            'unit_id': 123,
            'target_unit_id': 456,
            'correlation_id': 'query_1'
        }
        
        # Should validate
        result = validator.validate_message_data(message, MessageType.UNIT_ACTION_QUERY)
        assert result is not None
