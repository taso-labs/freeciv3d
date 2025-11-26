"""Tests for LLMWSHandler action -> packet conversion for many action types"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import Mock
from llm_handler import LLMWSHandler
from packet_constants import PACKET_UNIT_DO_ACTION, PACKET_UNIT_ORDERS, PACKET_CITY_CHANGE, PACKET_PLAYER_RESEARCH, PACKET_PLAYER_PHASE_DONE, PACKET_CITY_BUY, PACKET_CITY_SELL, PACKET_UNIT_SERVER_SIDE_AGENT_SET, PACKET_UNIT_CHANGE_ACTIVITY
from fc_constants import ACTION_CAPTURE_UNITS, ACTION_CONQUER_CITY


class TestActionHandlerConversions(unittest.TestCase):
    def setUp(self):
        # Create a mock handler using real _convert_action_to_packet
        self.handler = Mock(spec=LLMWSHandler)
        self.handler._convert_action_to_packet = LLMWSHandler._convert_action_to_packet.__get__(self.handler, LLMWSHandler)
        self.handler._get_unit_tile = lambda uid: 100  # simple tile lookup helper
        self.handler._get_current_game_state = lambda: {'units': {}}  # prevent None
        self.handler.civcom = Mock()
        self.handler.civcom.game_turn = 1
        # Minimal civcom storage expected by mapper and move path resolution
        self.handler.civcom.unit_types = {1: {'name': 'Warriors', 'id': 1}}
        self.handler.civcom.improvements = {2: {'name': 'Granary', 'id': 2}}
        self.handler.civcom.map_info = {'width': 80}

    def check_conversion(self, action, expected_fields: dict):
        pkt = self.handler._convert_action_to_packet(action)
        self.assertIsInstance(pkt, dict)
        for k, v in expected_fields.items():
            self.assertIn(k, pkt)
            self.assertEqual(pkt[k], v)

    def test_unit_move_conversion(self):
        action = {'type': 'unit_move', 'unit_id': 1, 'dest_x': 2, 'dest_y': 3}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_ORDERS)

    def test_unit_attack_conversion(self):
        action = {'type': 'unit_attack', 'attacker_unit_id': 10, 'target_unit_id': 20}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], 45)  # ACTION_ATTACK

    def test_city_production_conversion(self):
        action = {'type': 'city_production', 'city_id': 1, 'production_type': 'Warriors'}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_CITY_CHANGE)

    def test_tech_research_conversion(self):
        action = {'type': 'tech_research', 'tech_name': 'alphabet'}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_PLAYER_RESEARCH)

    def test_end_turn_conversion(self):
        action = {'type': 'end_turn'}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_PLAYER_PHASE_DONE)

    def test_unit_build_city_conversion(self):
        action = {'type': 'unit_build_city', 'unit_id': 77, 'name': 'NewCity'}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        # ACTION_FOUND_CITY currently encoded as numeric 27 in handler
        self.assertEqual(pkt['action_type'], 27)

    def test_join_city_conversion(self):
        action = {'type': 'join_city', 'unit_id': 33, 'city_id': 99}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], 28)

    def test_city_build_unit_conversion(self):
        action = {'type': 'city_build_unit', 'city_id': 1, 'unit_type': 'Warriors'}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_CITY_CHANGE)

    def test_unit_explore_conversion(self):
        action = {'type': 'unit_explore', 'unit_id': 50}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_SERVER_SIDE_AGENT_SET)

    def test_city_buy_conversion(self):
        action = {'type': 'city_buy', 'city_id': 2}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_CITY_BUY)

    def test_city_sell_improvement_conversion(self):
        action = {'type': 'city_sell_improvement', 'city_id': 2, 'improvement_id': 7}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_CITY_SELL)

    def test_upgrade_unit_conversion(self):
        action = {'type': 'upgrade_unit', 'unit_id': 1}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], 42)

    def test_bombard_conversion(self):
        action = {'type': 'bombard', 'unit_id': 1, 'target_tile_id': 100}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], 53)

    def test_disband_unit_conversion(self):
        action = {'type': 'disband_unit', 'unit_id': 5}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], 39)

    def test_pillage_conversion(self):
        action = {'type': 'pillage', 'unit_id': 6}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], 222)

    def test_transport_board_conversion(self):
        action = {'type': 'transport_board', 'unit_id': 10, 'transport_id': 20}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)

    def test_airlift_conversion(self):
        action = {'type': 'airlift', 'unit_id': 5, 'target_city_id': 2}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)

    def test_spy_actions_conversion(self):
        action = {'type': 'spy_investigate_city', 'unit_id': 10, 'target_city_id': 3}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)

    def test_trade_route_conversion(self):
        action = {'type': 'trade_route', 'unit_id': 10, 'target_city_id': 5}
        # Handler may use PACKET_UNIT_DO_ACTION for trade routes (or custom). Just ensure it returns a dict.
        pkt = self.handler._convert_action_to_packet(action)
        self.assertIsInstance(pkt, dict)

    def test_unit_build_road_conversion(self):
        action = {'type': 'unit_build_road', 'unit_id': 12}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)

    def test_unit_clean_pollution_conversion(self):
        action = {'type': 'unit_clean_pollution', 'unit_id': 15}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)

    def test_unit_clean_fallout_conversion(self):
        action = {'type': 'unit_clean_fallout', 'unit_id': 16}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)

    def test_unit_build_irrigation_conversion(self):
        action = {'type': 'unit_build_irrigation', 'unit_id': 17}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)

    def test_unit_build_mine_conversion(self):
        action = {'type': 'unit_build_mine', 'unit_id': 18}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)

    def test_unit_fortify_conversion(self):
        action = {'type': 'unit_fortify', 'unit_id': 19}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)

    def test_unit_sentry_conversion(self):
        action = {'type': 'unit_sentry', 'unit_id': 20}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)

    def test_unit_transform_terrain_conversion(self):
        action = {'type': 'unit_transform_terrain', 'unit_id': 21}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)

    def test_capture_units_conversion(self):
        action = {'type': 'capture_units', 'unit_id': 22, 'target_tile': 100}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_CAPTURE_UNITS)

    def test_conquer_city_conversion(self):
        action = {'type': 'conquer_city', 'unit_id': 24, 'target_city_id': 2}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_CONQUER_CITY)

    def test_steal_maps_conversion(self):
        action = {'type': 'steal_maps', 'unit_id': 25, 'target_city_id': 2}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)

    def test_cultivate_conversion(self):
        action = {'type': 'cultivate', 'unit_id': 26}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], 222)

    def test_plant_conversion(self):
        action = {'type': 'plant', 'unit_id': 27}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], 222)

