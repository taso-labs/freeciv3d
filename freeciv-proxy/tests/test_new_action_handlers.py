"""
Tests for New LLM Action Handlers

Tests the handler logic that converts LLM actions to FreeCiv packets for:
- unit_explore
- city_build_unit
- city_build_improvement
- diplomacy_message
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import sys
import os
import secrets

# Set up CACHE_HMAC_SECRET for tests before importing modules that need it
if 'CACHE_HMAC_SECRET' not in os.environ:
    os.environ['CACHE_HMAC_SECRET'] = secrets.token_hex(32)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packet_constants import PACKET_CITY_CHANGE, PACKET_DIPLOMACY_INIT_MEETING_REQ
from fc_constants import ACTIVITY_EXPLORE
from llm_handler import LLMWSHandler


class TestNewActionHandlers(unittest.TestCase):
    """Test action conversion to FreeCiv packets"""

    def setUp(self):
        """Setup test fixtures"""
        self.maxDiff = None
        
        # Create a mock handler with minimal setup
        self.handler = Mock(spec=LLMWSHandler)
        self.handler.civcom = Mock()
        
        # Use the real _convert_action_to_packet method
        self.handler._convert_action_to_packet = LLMWSHandler._convert_action_to_packet.__get__(self.handler, LLMWSHandler)

    def test_unit_explore_packet_conversion(self):
        """Test that unit_explore converts to correct PACKET_UNIT_SERVER_SIDE_AGENT_SET"""
        action = {
            'type': 'unit_explore',
            'unit_id': 123,
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Verify the packet structure
        self.assertEqual(result['pid'], 74)  # PACKET_UNIT_SERVER_SIDE_AGENT_SET
        self.assertEqual(result['unit_id'], 123)
        self.assertEqual(result['agent'], 1)  # SSA_AUTOEXPLORE

    def test_city_build_unit_packet_conversion(self):
        """Test that city_build_unit converts to PACKET_CITY_CHANGE"""
        # Mock unit_types with canonical dict structure
        self.handler.civcom.unit_types = {
            0: {'name': 'Settlers', 'id': 0},
            1: {'name': 'Warriors', 'id': 1},
            2: {'name': 'Phalanx', 'id': 2}
        }
        
        action = {
            'type': 'city_build_unit',
            'city_id': 1,
            'unit_type': 'Warriors',
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Verify the packet structure
        self.assertEqual(result['pid'], PACKET_CITY_CHANGE)
        self.assertEqual(result['pid'], 35)  # Verify constant value
        self.assertEqual(result['city_id'], 1)
        self.assertEqual(result['production_kind'], 0)  # 0 = unit
        self.assertEqual(result['production_value'], 1)  # Warriors is at index 1

    def test_city_build_unit_case_insensitive(self):
        """Test that unit type matching is case insensitive"""
        # Mock unit_types with canonical dict structure
        self.handler.civcom.unit_types = {
            0: {'name': 'Settlers', 'id': 0},
            1: {'name': 'Warriors', 'id': 1},
            2: {'name': 'Phalanx', 'id': 2}
        }
        
        # Test with lowercase input
        action = {
            'type': 'city_build_unit',
            'city_id': 1,
            'unit_type': 'warriors',  # lowercase
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should match 'Warriors' (index 1) case-insensitively
        self.assertEqual(result['production_value'], 1)

    def test_city_build_unit_unknown_unit_type(self):
        """Test that unknown unit type returns fallback action"""
        # Mock unit_types without the requested unit
        self.handler.civcom.unit_types = {
            0: {'name': 'Settlers', 'id': 0},
            1: {'name': 'Warriors', 'id': 1}
        }
        
        action = {
            'type': 'city_build_unit',
            'city_id': 1,
            'unit_type': 'Dragon',  # Not in ruleset
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should return original action when unit type not found
        self.assertEqual(result, action)
        self.assertEqual(result['type'], 'city_build_unit')

    def test_city_build_improvement_packet_conversion(self):
        """Test that city_build_improvement converts to PACKET_CITY_CHANGE"""
        # Mock improvements with canonical dict structure
        self.handler.civcom.improvements = {
            0: {'name': 'Palace', 'id': 0},
            1: {'name': 'Barracks', 'id': 1},
            2: {'name': 'Granary', 'id': 2},
            3: {'name': 'Temple', 'id': 3}
        }
        
        action = {
            'type': 'city_build_improvement',
            'city_id': 1,
            'improvement': 'Granary',
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Verify the packet structure
        self.assertEqual(result['pid'], PACKET_CITY_CHANGE)
        self.assertEqual(result['pid'], 35)  # Verify constant value
        self.assertEqual(result['city_id'], 1)
        self.assertEqual(result['production_kind'], 1)  # 1 = improvement
        self.assertEqual(result['production_value'], 2)  # Granary is at index 2

    def test_city_build_improvement_case_insensitive(self):
        """Test that improvement matching is case insensitive"""
        # Mock improvements with canonical dict structure
        self.handler.civcom.improvements = {
            0: {'name': 'Palace', 'id': 0},
            1: {'name': 'Barracks', 'id': 1},
            2: {'name': 'Granary', 'id': 2}
        }
        
        # Test with uppercase input
        action = {
            'type': 'city_build_improvement',
            'city_id': 1,
            'improvement': 'GRANARY',  # uppercase
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should match 'Granary' (index 2) case-insensitively
        self.assertEqual(result['production_value'], 2)

    def test_city_build_improvement_unknown_improvement(self):
        """Test that unknown improvement returns fallback action"""
        # Mock improvements without the requested improvement
        self.handler.civcom.improvements = {
            0: {'name': 'Palace', 'id': 0},
            1: {'name': 'Barracks', 'id': 1}
        }
        
        action = {
            'type': 'city_build_improvement',
            'city_id': 1,
            'improvement': 'SpacePort',  # Not in ruleset
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should return original action when improvement not found
        self.assertEqual(result, action)
        self.assertEqual(result['type'], 'city_build_improvement')

    def test_diplomacy_message_treaty_request_packet(self):
        """Test that diplomacy_message treaty_request converts to PACKET_DIPLOMACY_INIT_MEETING_REQ"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message_type': 'treaty_request',
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Verify the packet structure
        self.assertEqual(result['pid'], PACKET_DIPLOMACY_INIT_MEETING_REQ)
        self.assertEqual(result['pid'], 95)  # Verify constant value
        self.assertEqual(result['counterpart'], 1)
        self.assertEqual(len(result), 2)  # Only pid and counterpart

    def test_diplomacy_message_unsupported_type(self):
        """Test that unsupported message types return fallback action"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            'message_type': 'cancel_pact',  # Not implemented yet
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should return original action for unsupported types
        self.assertEqual(result, action)
        self.assertEqual(result['type'], 'diplomacy_message')

    def test_city_build_unit_missing_fields(self):
        """Test that missing required fields returns fallback action"""
        action = {
            'type': 'city_build_unit',
            'city_id': 1,
            # Missing unit_type
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should return original action when fields are missing
        self.assertEqual(result, action)

    def test_city_build_improvement_missing_fields(self):
        """Test that missing required fields returns fallback action"""
        action = {
            'type': 'city_build_improvement',
            # Missing city_id
            'improvement': 'Granary',
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should return original action when fields are missing
        self.assertEqual(result, action)

    def test_diplomacy_message_missing_fields(self):
        """Test that missing required fields returns fallback action"""
        action = {
            'type': 'diplomacy_message',
            'target_player_id': 1,
            # Missing message_type
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should return original action when fields are missing
        self.assertEqual(result, action)

    def test_unknown_action_type_returns_unchanged(self):
        """Test that unknown action types are returned unchanged"""
        action = {
            'type': 'unknown_action',
            'some_field': 123,
            'player_id': 0
        }
        
        result = self.handler._convert_action_to_packet(action)
        
        # Should return original action for unknown types
        self.assertEqual(result, action)

    def test_packet_constants_values(self):
        """Verify packet constants have correct values"""
        # PACKET_CITY_CHANGE should be 35
        self.assertEqual(PACKET_CITY_CHANGE, 35)
        
        # PACKET_DIPLOMACY_INIT_MEETING_REQ should be 95
        self.assertEqual(PACKET_DIPLOMACY_INIT_MEETING_REQ, 95)

    def test_city_build_unit_production_kinds(self):
        """Verify production kind values for units vs improvements"""
        self.handler.civcom.unit_types = {0: {'name': 'Warriors', 'id': 0}}
        self.handler.civcom.improvements = {0: {'name': 'Granary', 'id': 0}}
        
        unit_action = {
            'type': 'city_build_unit',
            'city_id': 1,
            'unit_type': 'Warriors',
            'player_id': 0
        }
        
        improvement_action = {
            'type': 'city_build_improvement',
            'city_id': 1,
            'improvement': 'Granary',
            'player_id': 0
        }
        
        unit_result = self.handler._convert_action_to_packet(unit_action)
        improvement_result = self.handler._convert_action_to_packet(improvement_action)
        
        # Units use production_kind = 0
        self.assertEqual(unit_result['production_kind'], 0)
        
        # Improvements use production_kind = 1
        self.assertEqual(improvement_result['production_kind'], 1)
        
        # They should be different
        self.assertNotEqual(unit_result['production_kind'], improvement_result['production_kind'])

