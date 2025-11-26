"""Additional conversion tests to complete coverage for remaining actions."""

import unittest
import sys
import os
import secrets
from unittest.mock import Mock

# Ensure environment secrets
if 'CACHE_HMAC_SECRET' not in os.environ:
    os.environ['CACHE_HMAC_SECRET'] = secrets.token_hex(32)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_handler import LLMWSHandler
from packet_constants import (
    PACKET_UNIT_DO_ACTION,
    PACKET_UNIT_CHANGE_ACTIVITY,
    PACKET_PLAYER_RATES,
)
from fc_constants import (
    ACTION_TRANSPORT_DEBOARD,
    ACTION_TRANSPORT_UNLOAD,
    ACTION_ESTABLISH_EMBASSY,
    ACTION_SPY_POISON,
    ACTION_SPY_SABOTAGE_CITY,
    ACTION_SPY_STEAL_TECH,
    ACTION_SPY_BRIBE_UNIT,
    ACTION_SPY_STEAL_GOLD,
    ACTION_SPY_INCITE_CITY,
    ACTIVITY_BASE,
)


class TestActionHandlerConversionsExtra(unittest.TestCase):
    def setUp(self):
        # Create a mock handler using real _convert_action_to_packet
        self.handler = Mock(spec=LLMWSHandler)
        self.handler._convert_action_to_packet = LLMWSHandler._convert_action_to_packet.__get__(self.handler, LLMWSHandler)
        self.handler._get_unit_tile = lambda uid: 100
        self.handler._get_current_game_state = lambda: {'units': {}}
        self.handler.civcom = Mock()
        self.handler.civcom.game_turn = 1
        self.handler.civcom.unit_types = {1: {'name': 'Warriors', 'id': 1}}
        self.handler.civcom.improvements = {2: {'name': 'Granary', 'id': 2}}
        self.handler.civcom.map_info = {'width': 80}

    def test_transport_deboard(self):
        action = {'type': 'transport_deboard', 'unit_id': 7}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_TRANSPORT_DEBOARD)

    def test_transport_unload(self):
        action = {'type': 'transport_unload', 'unit_id': 7, 'cargo_id': 99}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_TRANSPORT_UNLOAD)

    def test_establish_embassy(self):
        action = {'type': 'establish_embassy', 'unit_id': 5, 'target_city_id': 2}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_ESTABLISH_EMBASSY)

    def test_spy_poison(self):
        action = {'type': 'spy_poison', 'unit_id': 10, 'target_city_id': 3}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_SPY_POISON)

    def test_spy_sabotage_city(self):
        action = {'type': 'spy_sabotage_city', 'unit_id': 10, 'target_city_id': 3}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_SPY_SABOTAGE_CITY)

    def test_spy_steal_tech(self):
        action = {'type': 'spy_steal_tech', 'unit_id': 10, 'target_city_id': 3}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_SPY_STEAL_TECH)

    def test_spy_bribe_unit(self):
        action = {'type': 'spy_bribe_unit', 'unit_id': 10, 'target_unit_id': 77}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_SPY_BRIBE_UNIT)

    def test_spy_steal_gold(self):
        action = {'type': 'spy_steal_gold', 'unit_id': 10, 'target_city_id': 3}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_SPY_STEAL_GOLD)

    def test_spy_incite_city(self):
        action = {'type': 'spy_incite_city', 'unit_id': 10, 'target_city_id': 3}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_DO_ACTION)
        self.assertEqual(pkt['action_type'], ACTION_SPY_INCITE_CITY)

    def test_base_activity(self):
        action = {'type': 'base', 'unit_id': 12}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_UNIT_CHANGE_ACTIVITY)
        self.assertEqual(pkt['activity'], ACTIVITY_BASE)

    def test_player_rates(self):
        action = {'type': 'player_rates', 'tax_rate': 60, 'science_rate': 40, 'luxury_rate': 0}
        pkt = self.handler._convert_action_to_packet(action)
        self.assertEqual(pkt['pid'], PACKET_PLAYER_RATES)
        self.assertEqual(pkt['tax'], 60)
        self.assertEqual(pkt['science'], 40)
        self.assertEqual(pkt['luxury'], 0)
