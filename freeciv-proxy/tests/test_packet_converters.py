"""
Tests for action-to-packet converters in LLM handler.

These tests verify that _convert_action_to_packet correctly transforms
LLM action commands into FreeCiv packet format.

We test the converter function in isolation by extracting it from the source.
"""

import pytest
import re
import os

from action_constants import *
from packet_constants import (
    PACKET_UNIT_DO_ACTION,
    PACKET_UNIT_ORDERS,
    PACKET_UNIT_SERVER_SIDE_AGENT_SET,
    PACKET_UNIT_CHANGE_ACTIVITY,
    PACKET_CITY_CHANGE,
    PACKET_PLAYER_RESEARCH,
    PACKET_PLAYER_PHASE_DONE,
    PACKET_CITY_BUY,
    PACKET_CITY_SELL,
    PACKET_CITY_RENAME,
    PACKET_DIPLOMACY_INIT_MEETING_REQ,
    PACKET_DIPLOMACY_CANCEL_MEETING_REQ,
    PACKET_DIPLOMACY_ACCEPT_TREATY_REQ,
    PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
    PACKET_DIPLOMACY_CANCEL_PACT,
    PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ,
)
from packet_converter import convert_action_to_packet as _convert_action_to_packet


class TestCombatActionConverters:
    """Test combat action packet conversion."""
    
    def test_unit_attack_conversion(self):
        """Test unit_attack converts to PACKET_UNIT_DO_ACTION with action_type 45."""
        action = {
            'type': 'unit_attack',
            'unit_id': 101,
            'target_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['actor_id'] == 101
        assert result['target_id'] == 202
        assert result['action_type'] == 45  # ACTION_ATTACK
    
    def test_unit_suicide_attack_conversion(self):
        """Test unit_suicide_attack converts to action_type 46."""
        action = {
            'type': 'unit_suicide_attack',
            'unit_id': 101,
            'target_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_SUICIDE_ATTACK
    
    def test_unit_bombard_conversion(self):
        """Test unit_bombard converts to action_type 53."""
        action = {
            'type': 'unit_bombard',
            'unit_id': 101,
            'target_id': 303
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_BOMBARD
    
    def test_unit_capture_conversion(self):
        """Test unit_capture converts to action_type 24."""
        action = {
            'type': 'unit_capture',
            'unit_id': 101,
            'target_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_CAPTURE_UNITS
    
    def test_unit_nuke_conversion(self):
        """Test unit_nuke converts to action_type 33."""
        action = {
            'type': 'unit_nuke',
            'unit_id': 101,
            'target_id': 500
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_NUKE
    
    def test_unit_nuke_city_conversion(self):
        """Test unit_nuke_city converts to action_type 34."""
        action = {
            'type': 'unit_nuke_city',
            'unit_id': 101,
            'target_id': 600
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_NUKE_CITY
    
    def test_unit_pillage_conversion(self):
        """Test unit_pillage includes extra_id as sub_tgt_id (protocol field name)."""
        action = {
            'type': 'unit_pillage',
            'unit_id': 101,
            'tile_id': 500,
            'extra_id': 3
        }

        result = _convert_action_to_packet(action)

        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_PILLAGE
        assert result['sub_tgt_id'] == 3  # extra_id for what to pillage
    
    def test_unit_heal_conversion(self):
        """Test unit_heal converts to action_type 98."""
        action = {
            'type': 'unit_heal',
            'unit_id': 101,
            'target_id': 102
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_HEAL_UNIT
    
    def test_unit_conquer_city_conversion(self):
        """Test unit_conquer_city converts to action_type 49."""
        action = {
            'type': 'unit_conquer_city',
            'unit_id': 101,
            'target_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_CONQUER_CITY
    
    def test_unit_expel_conversion(self):
        """Test unit_expel converts to action_type 37."""
        action = {
            'type': 'unit_expel',
            'unit_id': 101,
            'target_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_EXPEL_UNIT
    
    def test_unit_nuke_units_conversion(self):
        """Test unit_nuke_units converts to action_type 35."""
        action = {
            'type': 'unit_nuke_units',
            'unit_id': 101,
            'target_id': 500
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_NUKE_UNITS


class TestCombatActionCoordinateResolution:
    """Test that combat actions resolve target coordinates to target_id.

    This tests the fix for the 'attackUnit #121Failed' error where LLM agents
    send coordinates in various formats (flat or nested) that need to be
    converted to target_id (tile index) for the FreeCiv server.

    Note: Default map width is 64 (for 1v1 LLM gameplay).
    """

    def test_unit_attack_with_flat_coordinates(self):
        """Test unit_attack resolves flat target_x, target_y to target_id."""
        action = {
            'type': 'unit_attack',
            'unit_id': 101,
            'target_x': 10,
            'target_y': 20
        }
        # map_width defaults to 64, so tile_id = 10 + 20 * 64 = 1290
        result = _convert_action_to_packet(action)

        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['target_id'] == 1290  # 10 + 20 * 64
        assert result['action_type'] == ACTION_ATTACK

    def test_unit_attack_with_nested_coordinates(self):
        """Test unit_attack resolves nested target.x, target.y to target_id."""
        action = {
            'type': 'unit_attack',
            'unit_id': 101,
            'target': {'x': 15, 'y': 25}
        }
        # map_width defaults to 64, so tile_id = 15 + 25 * 64 = 1615
        result = _convert_action_to_packet(action)

        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['target_id'] == 1615  # 15 + 25 * 64
        assert result['action_type'] == ACTION_ATTACK

    def test_unit_attack_prefers_direct_target_id(self):
        """Test that direct target_id takes precedence over coordinates."""
        action = {
            'type': 'unit_attack',
            'unit_id': 101,
            'target_id': 999,
            'target_x': 10,
            'target_y': 20
        }
        result = _convert_action_to_packet(action)

        assert result['target_id'] == 999  # Direct target_id wins

    def test_unit_bombard_with_coordinates(self):
        """Test unit_bombard resolves coordinates to target_id."""
        action = {
            'type': 'unit_bombard',
            'unit_id': 101,
            'target': {'x': 5, 'y': 10}
        }
        result = _convert_action_to_packet(action)

        assert result['target_id'] == 645  # 5 + 10 * 64
        assert result['action_type'] == ACTION_BOMBARD

    def test_unit_capture_with_coordinates(self):
        """Test unit_capture resolves coordinates to target_id."""
        action = {
            'type': 'unit_capture',
            'unit_id': 101,
            'target_x': 30,
            'target_y': 40
        }
        result = _convert_action_to_packet(action)

        assert result['target_id'] == 2590  # 30 + 40 * 64
        assert result['action_type'] == ACTION_CAPTURE_UNITS

    def test_unit_nuke_with_coordinates(self):
        """Test unit_nuke resolves coordinates to target_id."""
        action = {
            'type': 'unit_nuke',
            'unit_id': 101,
            'target': {'x': 50, 'y': 50}
        }
        result = _convert_action_to_packet(action)

        assert result['target_id'] == 3250  # 50 + 50 * 64
        assert result['action_type'] == ACTION_NUKE

    def test_unit_paradrop_with_coordinates(self):
        """Test unit_paradrop resolves coordinates to target_id."""
        action = {
            'type': 'unit_paradrop',
            'unit_id': 101,
            'target_x': 20,
            'target_y': 30
        }
        result = _convert_action_to_packet(action)

        assert result['target_id'] == 1940  # 20 + 30 * 64
        assert result['action_type'] == ACTION_PARADROP

    def test_unit_disembark_with_coordinates(self):
        """Test unit_disembark resolves coordinates to target_id."""
        action = {
            'type': 'unit_disembark',
            'unit_id': 101,
            'target': {'x': 12, 'y': 15}
        }
        result = _convert_action_to_packet(action)

        assert result['target_id'] == 972  # 12 + 15 * 64
        assert result['action_type'] == ACTION_TRANSPORT_DISEMBARK1

    def test_negative_coordinates_returns_negative_one(self):
        """Test that negative coordinates return -1 as target_id."""
        action = {
            'type': 'unit_attack',
            'unit_id': 101,
            'target_x': -5,
            'target_y': 10
        }
        result = _convert_action_to_packet(action)

        assert result['target_id'] == -1  # Negative coords rejected

    def test_no_coordinates_returns_negative_one(self):
        """Test that missing coordinates returns -1 as target_id."""
        action = {
            'type': 'unit_attack',
            'unit_id': 101
            # No target coordinates or target_id
        }
        result = _convert_action_to_packet(action)

        assert result['target_id'] == -1


class TestTransportActionConverters:
    """Test transport action packet conversion."""
    
    def test_unit_board_conversion(self):
        """Test unit_board converts to action_type 68."""
        action = {
            'type': 'unit_board',
            'unit_id': 101,
            'transport_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['actor_id'] == 101
        assert result['target_id'] == 202
        assert result['action_type'] == ACTION_TRANSPORT_BOARD
    
    def test_unit_embark_conversion(self):
        """Test unit_embark converts to action_type 72."""
        action = {
            'type': 'unit_embark',
            'unit_id': 101,
            'transport_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_TRANSPORT_EMBARK
    
    def test_unit_disembark_conversion(self):
        """Test unit_disembark converts to action_type 76."""
        action = {
            'type': 'unit_disembark',
            'unit_id': 101,
            'tile_id': 500
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['target_id'] == 500  # tile_id
        assert result['action_type'] == ACTION_TRANSPORT_DISEMBARK1
    
    def test_unit_airlift_conversion(self):
        """Test unit_airlift converts to action_type 44."""
        action = {
            'type': 'unit_airlift',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['target_id'] == 300  # city_id
        assert result['action_type'] == ACTION_AIRLIFT
    
    def test_unit_paradrop_conversion(self):
        """Test unit_paradrop converts to action_type 100."""
        action = {
            'type': 'unit_paradrop',
            'unit_id': 101,
            'tile_id': 700
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['target_id'] == 700  # tile_id
        assert result['action_type'] == ACTION_PARADROP


class TestEspionageActionConverters:
    """Test espionage action packet conversion."""
    
    def test_spy_investigate_city_conversion(self):
        """Test spy_investigate_city converts to action_type 2."""
        action = {
            'type': 'spy_investigate_city',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['target_id'] == 300
        assert result['action_type'] == ACTION_SPY_INVESTIGATE_CITY
    
    def test_spy_poison_conversion(self):
        """Test spy_poison converts to action_type 4."""
        action = {
            'type': 'spy_poison',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_SPY_POISON
    
    def test_spy_sabotage_city_conversion(self):
        """Test spy_sabotage_city converts to action_type 8."""
        action = {
            'type': 'spy_sabotage_city',
            'unit_id': 101,
            'city_id': 300,
            'building_id': 5
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['sub_tgt_id'] == 5  # building_id
        assert result['action_type'] == ACTION_SPY_SABOTAGE_CITY
    
    def test_spy_targeted_sabotage_city_conversion(self):
        """Test spy_targeted_sabotage_city includes required building_id."""
        action = {
            'type': 'spy_targeted_sabotage_city',
            'unit_id': 101,
            'city_id': 300,
            'building_id': 7
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['sub_tgt_id'] == 7  # Required building_id
        assert result['action_type'] == ACTION_SPY_TARGETED_SABOTAGE_CITY
    
    def test_spy_steal_tech_conversion(self):
        """Test spy_steal_tech converts to action_type 14."""
        action = {
            'type': 'spy_steal_tech',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_SPY_STEAL_TECH
    
    def test_spy_targeted_steal_tech_conversion(self):
        """Test spy_targeted_steal_tech includes required tech_id."""
        action = {
            'type': 'spy_targeted_steal_tech',
            'unit_id': 101,
            'city_id': 300,
            'tech_id': 25
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['sub_tgt_id'] == 25  # tech_id
        assert result['action_type'] == ACTION_SPY_TARGETED_STEAL_TECH
    
    def test_spy_incite_city_conversion(self):
        """Test spy_incite_city converts to action_type 18."""
        action = {
            'type': 'spy_incite_city',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_SPY_INCITE_CITY
    
    def test_spy_bribe_unit_conversion(self):
        """Test spy_bribe_unit converts to action_type 23."""
        action = {
            'type': 'spy_bribe_unit',
            'unit_id': 101,
            'target_unit_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['target_id'] == 202
        assert result['action_type'] == ACTION_SPY_BRIBE_UNIT
    
    def test_establish_embassy_conversion(self):
        """Test establish_embassy converts to action_type 0."""
        action = {
            'type': 'establish_embassy',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_ESTABLISH_EMBASSY
    
    def test_spy_steal_gold_conversion(self):
        """Test spy_steal_gold converts to action_type 82."""
        action = {
            'type': 'spy_steal_gold',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)

        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_SPY_STEAL_GOLD
    
    def test_spy_spread_plague_conversion(self):
        """Test spy_spread_plague converts to action_type 84."""
        action = {
            'type': 'spy_spread_plague',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_SPY_SPREAD_PLAGUE

class TestTradeActionConverters:
    """Test trade action packet conversion."""
    
    def test_unit_trade_route_conversion(self):
        """Test unit_trade_route converts to action_type 20."""
        action = {
            'type': 'unit_trade_route',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['target_id'] == 300
        assert result['action_type'] == ACTION_TRADE_ROUTE
    
    def test_unit_marketplace_conversion(self):
        """Test unit_marketplace converts to action_type 21."""
        action = {
            'type': 'unit_marketplace',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_MARKETPLACE
    
    def test_unit_help_wonder_conversion(self):
        """Test unit_help_wonder converts to action_type 22."""
        action = {
            'type': 'unit_help_wonder',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_HELP_WONDER


class TestDiplomacyActionConverters:
    """Test diplomacy action packet conversion."""
    
    def test_diplomacy_start_negotiation_conversion(self):
        """Test diplomacy_start_negotiation uses PACKET_DIPLOMACY_INIT_MEETING_REQ."""
        action = {
            'type': 'diplomacy_start_negotiation',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_INIT_MEETING_REQ
        assert result['counterpart'] == 2
    
    def test_diplomacy_cancel_meeting_conversion(self):
        """Test diplomacy_cancel_meeting uses PACKET_DIPLOMACY_CANCEL_MEETING_REQ."""
        action = {
            'type': 'diplomacy_cancel_meeting',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_CANCEL_MEETING_REQ
        assert result['counterpart'] == 2
    
    def test_diplomacy_accept_treaty_conversion(self):
        """Test diplomacy_accept_treaty uses PACKET_DIPLOMACY_ACCEPT_TREATY_REQ."""
        action = {
            'type': 'diplomacy_accept_treaty',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_ACCEPT_TREATY_REQ
        assert result['counterpart'] == 2
    
    def test_diplomacy_cancel_pact_conversion(self):
        """Test diplomacy_cancel_pact uses PACKET_DIPLOMACY_CANCEL_PACT."""
        action = {
            'type': 'diplomacy_cancel_pact',
            'player_id': 2,
            'clause_type': 6  # CLAUSE_PEACE
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_CANCEL_PACT
        assert result['other_player_id'] == 2
        assert result['clause'] == 6  # CLAUSE_PEACE
    
    def test_diplomacy_declare_war_conversion(self):
        """Test diplomacy_declare_war cancels ceasefire."""
        action = {
            'type': 'diplomacy_declare_war',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_CANCEL_PACT
        assert result['other_player_id'] == 2
        assert result['clause'] == 5  # CLAUSE_CEASEFIRE
    
    def test_diplomacy_propose_ceasefire_conversion(self):
        """Test diplomacy_propose_ceasefire uses CREATE_CLAUSE with type 5."""
        action = {
            'type': 'diplomacy_propose_ceasefire',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_CREATE_CLAUSE_REQ
        assert result['counterpart'] == 2
        assert result['type'] == 5  # CLAUSE_CEASEFIRE
    
    def test_diplomacy_propose_peace_conversion(self):
        """Test diplomacy_propose_peace uses CREATE_CLAUSE with type 6."""
        action = {
            'type': 'diplomacy_propose_peace',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_CREATE_CLAUSE_REQ
        assert result['type'] == 6  # CLAUSE_PEACE
    
    def test_diplomacy_propose_alliance_conversion(self):
        """Test diplomacy_propose_alliance uses CREATE_CLAUSE with type 7."""
        action = {
            'type': 'diplomacy_propose_alliance',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_CREATE_CLAUSE_REQ
        assert result['type'] == 7  # CLAUSE_ALLIANCE
    
    def test_diplomacy_share_vision_conversion(self):
        """Test diplomacy_share_vision uses CREATE_CLAUSE with type 8."""
        action = {
            'type': 'diplomacy_share_vision',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_DIPLOMACY_CREATE_CLAUSE_REQ
        assert result['type'] == 8  # CLAUSE_VISION
    
    def test_diplomacy_withdraw_vision_conversion(self):
        """Test diplomacy_withdraw_vision uses REMOVE_CLAUSE."""
        action = {
            'type': 'diplomacy_withdraw_vision',
            'player_id': 2
        }
        
        result = _convert_action_to_packet(action)

        assert result['pid'] == PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ
        assert result['type'] == 8  # CLAUSE_VISION


class TestCityActionConverters:
    """Test city action packet conversion."""
    
    def test_city_buy_conversion(self):
        """Test city_buy uses PACKET_CITY_BUY."""
        action = {
            'type': 'city_buy',
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_CITY_BUY
        assert result['city_id'] == 300
    
    def test_city_sell_improvement_conversion(self):
        """Test city_sell_improvement uses PACKET_CITY_SELL."""
        action = {
            'type': 'city_sell_improvement',
            'city_id': 300,
            'improvement_id': 5
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_CITY_SELL
        assert result['city_id'] == 300
        assert result['build_id'] == 5
    
    def test_city_rename_conversion(self):
        """Test city_rename uses PACKET_CITY_RENAME."""
        action = {
            'type': 'city_rename',
            'city_id': 300,
            'name': 'New City Name'
        }
        
        result = _convert_action_to_packet(action)

        assert result['pid'] == PACKET_CITY_RENAME
        assert result['city_id'] == 300
        assert result['name'] == 'New City Name'


class TestAdditionalUnitActionConverters:
    """Test additional unit action packet conversion."""
    
    def test_unit_upgrade_conversion(self):
        """Test unit_upgrade converts to action_type 42."""
        action = {
            'type': 'unit_upgrade',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_UPGRADE_UNIT
    
    def test_unit_join_city_conversion(self):
        """Test unit_join_city converts to action_type 28."""
        action = {
            'type': 'unit_join_city',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_JOIN_CITY
    
    def test_unit_clean_pollution_conversion(self):
        """Test unit_clean_pollution uses ACTIVITY_POLLUTION (7)."""
        action = {
            'type': 'unit_clean_pollution',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_CHANGE_ACTIVITY
        assert result['activity'] == 7  # ACTIVITY_POLLUTION
    
    def test_unit_clean_fallout_conversion(self):
        """Test unit_clean_fallout uses ACTIVITY_FALLOUT (11)."""
        action = {
            'type': 'unit_clean_fallout',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_CHANGE_ACTIVITY
        assert result['activity'] == 11  # ACTIVITY_FALLOUT
    
    def test_unit_transform_conversion(self):
        """Test unit_transform uses ACTIVITY_TRANSFORM (8)."""
        action = {
            'type': 'unit_transform',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_CHANGE_ACTIVITY
        assert result['activity'] == 8  # ACTIVITY_TRANSFORM
    
    def test_unit_disband_conversion(self):
        """Test unit_disband converts to action_type 30."""
        action = {
            'type': 'unit_disband',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_DISBAND_UNIT
    
    def test_unit_home_city_conversion(self):
        """Test unit_home_city converts to action_type 32."""
        action = {
            'type': 'unit_home_city',
            'unit_id': 101,
            'city_id': 300
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_HOME_CITY
    
    def test_unit_wake_conversion(self):
        """Test unit_wake uses ACTIVITY_IDLE (0)."""
        action = {
            'type': 'unit_wake',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_CHANGE_ACTIVITY
        assert result['activity'] == 0  # ACTIVITY_IDLE (wake up)
    
    def test_unit_auto_worker_conversion(self):
        """Test unit_auto_worker uses PACKET_UNIT_SERVER_SIDE_AGENT_SET."""
        action = {
            'type': 'unit_auto_worker',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_SERVER_SIDE_AGENT_SET
        assert result['agent'] == 1  # Auto-worker mode
    
    def test_unit_cultivate_conversion(self):
        """Test unit_cultivate converts to action_type 64."""
        action = {
            'type': 'unit_cultivate',
            'unit_id': 101,
            'tile_id': 500
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_CULTIVATE
    
    def test_unit_plant_conversion(self):
        """Test unit_plant converts to action_type 66."""
        action = {
            'type': 'unit_plant',
            'unit_id': 101,
            'tile_id': 500
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == ACTION_PLANT


class TestFallbackBehavior:
    """Test fallback behavior for unrecognized actions."""
    
    def test_unknown_action_returns_original(self):
        """Test that unknown actions are returned unchanged."""
        action = {
            'type': 'unknown_future_action',
            'some_param': 123
        }
        
        result = _convert_action_to_packet(action)
        
        # Should return original action unchanged
        assert result == action
    
    def test_empty_action_returns_original(self):
        """Test that empty action dicts are returned unchanged."""
        action = {}
        
        result = _convert_action_to_packet(action)
        
        assert result == action


class TestTargetIdFallbacks:
    """Test that target_id fallback logic works correctly."""
    
    def test_embark_uses_transport_id(self):
        """Test unit_embark uses transport_id as target_id."""
        action = {
            'type': 'unit_embark',
            'unit_id': 101,
            'transport_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['target_id'] == 202
    
    def test_embark_fallback_to_target_id(self):
        """Test unit_embark falls back to target_id if no transport_id."""
        action = {
            'type': 'unit_embark',
            'unit_id': 101,
            'target_id': 303
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['target_id'] == 303
    
    def test_airlift_uses_city_id(self):
        """Test unit_airlift uses city_id as target_id."""
        action = {
            'type': 'unit_airlift',
            'unit_id': 101,
            'city_id': 400
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['target_id'] == 400
    
    def test_bribe_uses_target_unit_id(self):
        """Test spy_bribe_unit uses target_unit_id."""
        action = {
            'type': 'spy_bribe_unit',
            'unit_id': 101,
            'target_unit_id': 202
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['target_id'] == 202
    
    def test_disembark_uses_tile_id(self):
        """Test unit_disembark uses tile_id as target_id."""
        action = {
            'type': 'unit_disembark',
            'unit_id': 101,
            'tile_id': 500
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['target_id'] == 500
    
    def test_paradrop_uses_tile_id(self):
        """Test unit_paradrop uses tile_id as target_id."""
        action = {
            'type': 'unit_paradrop',
            'unit_id': 101,
            'tile_id': 600
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['target_id'] == 600


class TestExistingActionConverters:
    """Test that existing action converters still work correctly.
    
    Note: Some of these tests are skipped because they require self.civcom
    which is stubbed out in our isolated testing approach.
    """
    
    @pytest.mark.skip(reason="Requires self.civcom for map_width calculation")
    def test_unit_move_conversion(self):
        """Test unit_move converts to PACKET_UNIT_ORDERS."""
        action = {
            'type': 'unit_move',
            'unit_id': 101,
            'tile': 500
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_ORDERS
        assert result['unit_id'] == 101
        assert result['dest_tile'] == 500
    
    @pytest.mark.skip(reason="Requires self.civcom for ruleset lookup")
    def test_city_production_conversion(self):
        """Test city_production converts to PACKET_CITY_CHANGE."""
        action = {
            'type': 'city_production',
            'city_id': 300,
            'production_type': 'unit',  # Required field
            'production_value': 5
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_CITY_CHANGE
        assert result['city_id'] == 300
    
    @pytest.mark.skip(reason="Requires tech_name for lookup")
    def test_tech_research_conversion(self):
        """Test tech_research converts to PACKET_PLAYER_RESEARCH."""
        action = {
            'type': 'tech_research',
            'tech': 15  # Uses 'tech' not 'tech_id'
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_PLAYER_RESEARCH
        assert result['tech'] == 15
    
    @pytest.mark.skip(reason="Requires self.civcom.player_id")
    def test_end_turn_conversion(self):
        """Test end_turn converts to PACKET_PLAYER_PHASE_DONE."""
        action = {
            'type': 'end_turn'
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_PLAYER_PHASE_DONE
    
    def test_unit_build_city_conversion(self):
        """Test unit_build_city converts to PACKET_UNIT_DO_ACTION with action_type 27."""
        action = {
            'type': 'unit_build_city',
            'unit_id': 101,
            'name': 'New City'
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_DO_ACTION
        assert result['action_type'] == 27  # ACTION_FOUND_CITY
        assert result['name'] == 'New City'
    
    def test_unit_fortify_conversion(self):
        """Test unit_fortify converts to PACKET_UNIT_CHANGE_ACTIVITY."""
        action = {
            'type': 'unit_fortify',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_CHANGE_ACTIVITY
        assert result['activity'] == 10  # ACTIVITY_FORTIFYING
    
    def test_unit_sentry_conversion(self):
        """Test unit_sentry converts to PACKET_UNIT_CHANGE_ACTIVITY."""
        action = {
            'type': 'unit_sentry',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_CHANGE_ACTIVITY
        assert result['activity'] == 5  # ACTIVITY_SENTRY
    
    def test_unit_explore_conversion(self):
        """Test unit_explore converts to PACKET_UNIT_SERVER_SIDE_AGENT_SET."""
        action = {
            'type': 'unit_explore',
            'unit_id': 101
        }
        
        result = _convert_action_to_packet(action)
        
        assert result['pid'] == PACKET_UNIT_SERVER_SIDE_AGENT_SET
        assert result['agent'] == 1  # SSA_AUTOEXPLORE
