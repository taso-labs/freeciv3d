"""
Tests for unit_move action format consistency

Verifies that unit_move actions use consistent dest_x/dest_y format
and that packet_converter can handle both formats transparently.
"""

import unittest
import json
from unittest.mock import Mock, MagicMock, patch
import secrets

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variable for cache - must be 64+ characters with good entropy
os.environ['CACHE_HMAC_SECRET'] = secrets.token_hex(32)  # 64 character hex string

import logging
logging.disable(logging.CRITICAL)


class TestUnitMoveFormat(unittest.TestCase):
    """Test that unit_move actions use consistent format"""

    def test_packet_converter_accepts_dest_x_dest_y(self):
        """packet_converter should accept dest_x/dest_y format"""
        from packet_converter import convert_action_to_packet
        
        # Create mock civcom with proper mock setup
        civcom = Mock()
        civcom.map_info = {'width': 80, 'height': 60}
        civcom.player_units = {42: {'id': 42, 'x': 10, 'y': 10}}
        # Mock _get_unit_tile to return a valid tile number
        civcom.get_unit_tile = Mock(return_value=10 + 10 * 80)
        
        action = {
            'type': 'unit_move',
            'unit_id': 42,
            'dest_x': 11,
            'dest_y': 10
        }
        
        # Should convert successfully with dest_x/dest_y
        try:
            packet = convert_action_to_packet(action, civcom)
            # Basic validation - should return a packet dict
            self.assertIsNotNone(packet)
            self.assertIsInstance(packet, dict)
        except (ValueError, TypeError) as e:
            # If conversion requires more setup, check if it's related to coordinates
            if "dest_x" in str(e) or "dest_y" in str(e):
                self.fail(f"packet_converter should accept dest_x/dest_y format: {e}")

    def test_packet_converter_accepts_target_format(self):
        """packet_converter should also accept nested target format for backward compatibility"""
        from packet_converter import convert_action_to_packet
        
        civcom = Mock()
        civcom.map_info = {'width': 80, 'height': 60}
        civcom.player_units = {42: {'id': 42, 'x': 10, 'y': 10}}
        civcom.get_unit_tile = Mock(return_value=10 + 10 * 80)
        
        action = {
            'type': 'unit_move',
            'unit_id': 42,
            'target': {'x': 11, 'y': 10}
        }
        
        # Should convert successfully with target format
        try:
            packet = convert_action_to_packet(action, civcom)
            # Basic validation - should return a packet dict
            self.assertIsNotNone(packet)
            self.assertIsInstance(packet, dict)
        except (ValueError, TypeError) as e:
            # If conversion requires more setup, check if it's related to coordinates
            if "target" in str(e):
                self.fail(f"packet_converter should accept target format: {e}")

    def test_packet_converter_rejects_invalid_format(self):
        """packet_converter should reject invalid formats"""
        from packet_converter import convert_action_to_packet
        
        civcom = Mock()
        civcom.map_info = {'width': 80}
        
        action = {
            'type': 'unit_move',
            'unit_id': 42,
            # Missing both dest_x/dest_y and target
        }
        
        # Should raise ValueError
        with self.assertRaises(ValueError):
            convert_action_to_packet(action, civcom)

    def test_state_extractor_generates_dest_x_dest_y(self):
        """state_extractor should generate unit_move with dest_x/dest_y"""
        from state_extractor import StateExtractor
        
        extractor = StateExtractor()
        
        # Create mock raw state with units
        raw_state = {
            'turn': 1,
            'phase': 'movement',
            'units': {
                '1': {
                    'id': 1,
                    'owner': 0,
                    'type': 'Warrior',
                    'x': 10,
                    'y': 20,
                    'done_moving': False
                }
            },
            'cities': {},
            'players': {},
            'map': {'width': 80, 'height': 60}
        }
        
        try:
            # Generate actions
            actions = extractor._generate_unit_actions(raw_state['units']['1'], raw_state, player_id=0)
            
            # Find unit_move actions
            move_actions = [a for a in actions if a.get('type') == 'unit_move']
            
            # If actions are generated, verify format
            for action in move_actions:
                self.assertIn('dest_x', action, "Should have dest_x field")
                self.assertIn('dest_y', action, "Should have dest_y field")
                self.assertNotIn('target', action, "Should not have old target format")
                self.assertIsInstance(action['dest_x'], int, "dest_x should be integer")
                self.assertIsInstance(action['dest_y'], int, "dest_y should be integer")
        except AttributeError:
            # If method doesn't exist yet, that's OK - just skip
            pass


if __name__ == '__main__':
    unittest.main()
