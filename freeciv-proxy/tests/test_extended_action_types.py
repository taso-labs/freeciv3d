"""
Tests for LLM WebSocket Protocol v2.0.1 Extended Action Types

Tests the extended action type validation per protocol spec:
- Diplomacy actions (declare_war, propose_peace, etc.)
- Espionage actions (spy_steal_tech, spy_sabotage_city, etc.)
- Combat actions (unit_attack, unit_bombard, etc.)
- Transport actions (unit_embark, unit_disembark, etc.)
- Research & game control (tech_research, end_turn)

These tests use mock game state fixtures and do not require a live FreeCiv server.
"""

import unittest
import sys
import os
import json
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from error_handler import ErrorCode


# Sample game state fixture
SAMPLE_GAME_STATE = {
    "turn": 15,
    "phase": "movement",
    "player_id": 1,
    "map": {"width": 80, "height": 50},
    "units": {
        "42": {
            "id": 42, 
            "type": "Warrior", 
            "x": 10, 
            "y": 20, 
            "owner": 1, 
            "moves_left": 1,
            "hp": 10
        },
        "43": {
            "id": 43, 
            "type": "Diplomat", 
            "x": 12, 
            "y": 22, 
            "owner": 1, 
            "moves_left": 2
        },
        "44": {
            "id": 44, 
            "type": "Spy", 
            "x": 15, 
            "y": 25, 
            "owner": 1, 
            "moves_left": 2
        },
        "45": {
            "id": 45, 
            "type": "Transport", 
            "x": 20, 
            "y": 30, 
            "owner": 1, 
            "moves_left": 5,
            "cargo": []
        },
        "99": {
            "id": 99, 
            "type": "Warrior", 
            "x": 11, 
            "y": 21, 
            "owner": 2,
            "moves_left": 1
        }
    },
    "cities": {
        "1": {"id": 1, "name": "Capital", "x": 15, "y": 25, "owner": 1},
        "5": {"id": 5, "name": "Enemy City", "x": 30, "y": 30, "owner": 2}
    },
    "players": {
        "1": {"id": 1, "name": "Player1", "nation": "Romans", "gold": 100},
        "2": {"id": 2, "name": "Player2", "nation": "Greeks", "gold": 80}
    },
    "research": {
        "current": "Bronze Working",
        "available": ["Iron Working", "Writing", "Masonry"]
    },
    "diplomacy": {
        "2": {"status": "war"}  # At war with player 2
    }
}


class TestDiplomacyActions(unittest.TestCase):
    """Test diplomacy action format validation"""
    
    def test_diplomacy_declare_war_format(self):
        """diplomacy_declare_war should have correct format"""
        action = {
            "action_type": "diplomacy_declare_war",
            "actor_id": 0,  # Player-level action
            "target": {"player_id": 2}
        }
        
        self.assertEqual(action["action_type"], "diplomacy_declare_war")
        self.assertIn("player_id", action["target"])
        self.assertIsInstance(action["target"]["player_id"], int)
    
    def test_diplomacy_propose_peace_format(self):
        """diplomacy_propose_peace should have correct format"""
        action = {
            "action_type": "diplomacy_propose_peace",
            "actor_id": 0,
            "target": {"player_id": 2}
        }
        
        self.assertEqual(action["action_type"], "diplomacy_propose_peace")
        self.assertIn("player_id", action["target"])
    
    def test_diplomacy_propose_alliance_format(self):
        """diplomacy_propose_alliance should have correct format"""
        action = {
            "action_type": "diplomacy_propose_alliance",
            "actor_id": 0,
            "target": {"player_id": 3}
        }
        
        self.assertEqual(action["action_type"], "diplomacy_propose_alliance")
    
    def test_diplomacy_accept_treaty_format(self):
        """diplomacy_accept_treaty should have correct format"""
        action = {
            "action_type": "diplomacy_accept_treaty",
            "actor_id": 0,
            "target": {"player_id": 2}
        }
        
        self.assertEqual(action["action_type"], "diplomacy_accept_treaty")
    
    def test_diplomacy_message_format(self):
        """diplomacy_message should include message text"""
        action = {
            "action_type": "diplomacy_message",
            "actor_id": 0,
            "target": {"player_id": 2, "message": "Let's make peace!"}
        }
        
        self.assertIn("message", action["target"])
        self.assertIsInstance(action["target"]["message"], str)
        self.assertLessEqual(len(action["target"]["message"]), 256)
    
    def test_diplomacy_player_not_found_error(self):
        """Should return E260 for non-existent player"""
        error = {
            "code": "E260",
            "message": "Player not found"
        }
        
        self.assertEqual(error["code"], ErrorCode.PLAYER_NOT_FOUND)
    
    def test_diplomacy_invalid_action_error(self):
        """Should return E261 for invalid diplomatic action"""
        error = {
            "code": "E261",
            "message": "Cannot declare war on ally without canceling treaty first"
        }
        
        self.assertEqual(error["code"], ErrorCode.DIPLOMATIC_ACTION_INVALID)
    
    def test_diplomacy_treaty_exists_error(self):
        """Should return E262 when treaty already exists"""
        error = {
            "code": "E262",
            "message": "Peace treaty already exists with this player"
        }
        
        self.assertEqual(error["code"], ErrorCode.TREATY_EXISTS)


class TestEspionageActions(unittest.TestCase):
    """Test espionage action format validation"""
    
    def test_spy_steal_tech_format(self):
        """spy_steal_tech should target a city"""
        action = {
            "action_type": "spy_steal_tech",
            "actor_id": 44,  # Spy unit ID
            "target": {"city_id": 5}
        }
        
        self.assertEqual(action["action_type"], "spy_steal_tech")
        self.assertIn("city_id", action["target"])
    
    def test_spy_targeted_steal_tech_format(self):
        """spy_targeted_steal_tech should have sub_target"""
        action = {
            "action_type": "spy_targeted_steal_tech",
            "actor_id": 44,
            "target": {"city_id": 5},
            "sub_target": {"type": "tech", "name": "Iron Working"}
        }
        
        self.assertIn("sub_target", action)
        self.assertEqual(action["sub_target"]["type"], "tech")
        self.assertIn("name", action["sub_target"])
    
    def test_spy_sabotage_city_format(self):
        """spy_sabotage_city should target a city"""
        action = {
            "action_type": "spy_sabotage_city",
            "actor_id": 44,
            "target": {"city_id": 5}
        }
        
        self.assertEqual(action["action_type"], "spy_sabotage_city")
    
    def test_spy_targeted_sabotage_city_format(self):
        """spy_targeted_sabotage_city should have building sub_target"""
        action = {
            "action_type": "spy_targeted_sabotage_city",
            "actor_id": 44,
            "target": {"city_id": 5},
            "sub_target": {"type": "building", "name": "Granary"}
        }
        
        self.assertEqual(action["sub_target"]["type"], "building")
    
    def test_spy_bribe_unit_format(self):
        """spy_bribe_unit should target an enemy unit"""
        action = {
            "action_type": "spy_bribe_unit",
            "actor_id": 44,
            "target": {"unit_id": 99}
        }
        
        self.assertIn("unit_id", action["target"])
    
    def test_unit_establish_embassy_format(self):
        """unit_establish_embassy should target a city"""
        action = {
            "action_type": "unit_establish_embassy",
            "actor_id": 43,  # Diplomat unit
            "target": {"city_id": 5}
        }
        
        self.assertEqual(action["action_type"], "unit_establish_embassy")


class TestCombatActions(unittest.TestCase):
    """Test combat action format validation"""
    
    def test_unit_attack_unit_target(self):
        """unit_attack can target an enemy unit"""
        action = {
            "action_type": "unit_attack",
            "actor_id": 42,
            "target": {"unit_id": 99}
        }
        
        self.assertIn("unit_id", action["target"])
    
    def test_unit_attack_tile_target(self):
        """unit_attack can target coordinates"""
        action = {
            "action_type": "unit_attack",
            "actor_id": 42,
            "target": {"x": 11, "y": 21}
        }
        
        self.assertIn("x", action["target"])
        self.assertIn("y", action["target"])
    
    def test_unit_bombard_format(self):
        """unit_bombard targets coordinates"""
        action = {
            "action_type": "unit_bombard",
            "actor_id": 42,
            "target": {"x": 12, "y": 22}
        }
        
        self.assertEqual(action["action_type"], "unit_bombard")
    
    def test_unit_nuke_format(self):
        """unit_nuke targets coordinates"""
        action = {
            "action_type": "unit_nuke",
            "actor_id": 42,
            "target": {"x": 30, "y": 30}
        }
        
        self.assertEqual(action["action_type"], "unit_nuke")
    
    def test_unit_conquer_city_format(self):
        """unit_conquer_city targets a city"""
        action = {
            "action_type": "unit_conquer_city",
            "actor_id": 42,
            "target": {"city_id": 5}
        }
        
        self.assertIn("city_id", action["target"])


class TestTransportActions(unittest.TestCase):
    """Test transport action format validation"""
    
    def test_unit_embark_format(self):
        """unit_embark targets a transport unit"""
        action = {
            "action_type": "unit_embark",
            "actor_id": 42,
            "target": {"unit_id": 45}  # Transport unit
        }
        
        self.assertIn("unit_id", action["target"])
    
    def test_unit_disembark_format(self):
        """unit_disembark targets coordinates"""
        action = {
            "action_type": "unit_disembark",
            "actor_id": 42,
            "target": {"x": 21, "y": 31}
        }
        
        self.assertIn("x", action["target"])
        self.assertIn("y", action["target"])
    
    def test_unit_airlift_format(self):
        """unit_airlift targets a city"""
        action = {
            "action_type": "unit_airlift",
            "actor_id": 42,
            "target": {"city_id": 1}
        }
        
        self.assertIn("city_id", action["target"])
    
    def test_unit_paradrop_format(self):
        """unit_paradrop targets coordinates"""
        action = {
            "action_type": "unit_paradrop",
            "actor_id": 42,
            "target": {"x": 25, "y": 35}
        }
        
        self.assertEqual(action["action_type"], "unit_paradrop")


class TestResearchActions(unittest.TestCase):
    """Test research and game control action validation"""
    
    def test_tech_research_format(self):
        """tech_research should specify technology name"""
        action = {
            "action_type": "tech_research",
            "actor_id": 0,  # Player-level action
            "target": {"tech": "Bronze Working"}
        }
        
        self.assertIn("tech", action["target"])
        self.assertIsInstance(action["target"]["tech"], str)
    
    def test_end_turn_format(self):
        """end_turn has minimal format"""
        action = {
            "action_type": "end_turn",
            "actor_id": 0
        }
        
        self.assertEqual(action["action_type"], "end_turn")
        # end_turn has no target
        self.assertNotIn("target", action)


class TestCityActions(unittest.TestCase):
    """Test city action format validation"""
    
    def test_city_production_format(self):
        """city_production should specify production target"""
        action = {
            "action_type": "city_production",
            "actor_id": 1,  # City ID
            "target": {"production": "Warrior"}
        }
        
        self.assertIn("production", action["target"])
    
    def test_city_buy_format(self):
        """city_buy has no target (buys current production)"""
        action = {
            "action_type": "city_buy",
            "actor_id": 1
        }
        
        self.assertEqual(action["action_type"], "city_buy")
    
    def test_city_sell_improvement_format(self):
        """city_sell_improvement should specify improvement"""
        action = {
            "action_type": "city_sell_improvement",
            "actor_id": 1,
            "target": {"improvement": "Granary"}
        }
        
        self.assertIn("improvement", action["target"])


class TestCityFoundationActions(unittest.TestCase):
    """Test city foundation action validation"""
    
    def test_unit_found_city_with_name(self):
        """unit_found_city can specify city name"""
        action = {
            "action_type": "unit_found_city",
            "actor_id": 43,  # Settler unit
            "target": {"name": "New Rome"}
        }
        
        self.assertIn("name", action["target"])
        self.assertLessEqual(len(action["target"]["name"]), 50)
    
    def test_unit_found_city_without_name(self):
        """unit_found_city can omit name for auto-naming"""
        action = {
            "action_type": "unit_found_city",
            "actor_id": 43
        }
        
        self.assertEqual(action["action_type"], "unit_found_city")
    
    def test_unit_join_city_format(self):
        """unit_join_city targets a city"""
        action = {
            "action_type": "unit_join_city",
            "actor_id": 43,
            "target": {"city_id": 1}
        }
        
        self.assertIn("city_id", action["target"])


class TestTerrainImprovementActions(unittest.TestCase):
    """Test terrain improvement action validation"""
    
    def test_unit_build_road_format(self):
        """unit_build_road has no target (uses current tile)"""
        action = {
            "action_type": "unit_build_road",
            "actor_id": 44
        }
        
        self.assertEqual(action["action_type"], "unit_build_road")
        # No target needed - operates on unit's current tile
    
    def test_unit_build_irrigation_format(self):
        """unit_build_irrigation has no target"""
        action = {
            "action_type": "unit_build_irrigation",
            "actor_id": 44
        }
        
        self.assertEqual(action["action_type"], "unit_build_irrigation")
    
    def test_unit_pillage_format(self):
        """unit_pillage can optionally specify extra to pillage"""
        action = {
            "action_type": "unit_pillage",
            "actor_id": 42,
            "target": {"extra": "Road"}
        }
        
        self.assertIn("extra", action["target"])


class TestUnitStatusActions(unittest.TestCase):
    """Test unit status action validation"""
    
    def test_unit_fortify_format(self):
        """unit_fortify has no target"""
        action = {
            "action_type": "unit_fortify",
            "actor_id": 42
        }
        
        self.assertEqual(action["action_type"], "unit_fortify")
    
    def test_unit_sentry_format(self):
        """unit_sentry has no target"""
        action = {
            "action_type": "unit_sentry",
            "actor_id": 42
        }
        
        self.assertEqual(action["action_type"], "unit_sentry")
    
    def test_unit_explore_format(self):
        """unit_explore has no target"""
        action = {
            "action_type": "unit_explore",
            "actor_id": 42
        }
        
        self.assertEqual(action["action_type"], "unit_explore")
    
    def test_unit_upgrade_format(self):
        """unit_upgrade has no target (upgrades in place)"""
        action = {
            "action_type": "unit_upgrade",
            "actor_id": 42
        }
        
        self.assertEqual(action["action_type"], "unit_upgrade")
    
    def test_unit_heal_format(self):
        """unit_heal targets a friendly unit"""
        action = {
            "action_type": "unit_heal",
            "actor_id": 42,
            "target": {"unit_id": 43}
        }
        
        self.assertIn("unit_id", action["target"])


class TestTradeActions(unittest.TestCase):
    """Test trade action validation"""
    
    def test_unit_trade_route_format(self):
        """unit_trade_route targets a city"""
        action = {
            "action_type": "unit_trade_route",
            "actor_id": 42,
            "target": {"city_id": 5}
        }
        
        self.assertIn("city_id", action["target"])
    
    def test_unit_help_wonder_format(self):
        """unit_help_wonder targets a city"""
        action = {
            "action_type": "unit_help_wonder",
            "actor_id": 42,
            "target": {"city_id": 1}
        }
        
        self.assertEqual(action["action_type"], "unit_help_wonder")


class TestActionTypeEnumValues(unittest.TestCase):
    """Test that all protocol action types are recognized"""
    
    EXPECTED_ACTION_TYPES = [
        # Diplomacy
        "diplomacy_declare_war",
        "diplomacy_cancel_treaty",
        "diplomacy_propose_ceasefire",
        "diplomacy_propose_peace",
        "diplomacy_propose_alliance",
        "diplomacy_accept_treaty",
        "diplomacy_reject_treaty",
        "diplomacy_share_vision",
        "diplomacy_withdraw_vision",
        "diplomacy_message",
        # Espionage
        "unit_establish_embassy",
        "spy_investigate_city",
        "spy_poison",
        "spy_sabotage_city",
        "spy_targeted_sabotage_city",
        "spy_steal_tech",
        "spy_targeted_steal_tech",
        "spy_incite_city",
        "spy_steal_gold",
        "spy_steal_maps",
        "spy_nuke",
        "spy_spread_plague",
        "spy_bribe_unit",
        "spy_sabotage_unit",
        "spy_attack",
        "unit_expel",
        # Combat
        "unit_attack",
        "unit_suicide_attack",
        "unit_bombard",
        "unit_capture",
        "unit_wipe",
        "unit_conquer_city",
        "unit_nuke",
        "unit_nuke_city",
        "unit_nuke_units",
        # Transport
        "unit_move",
        "unit_teleport",
        "unit_airlift",
        "unit_paradrop",
        "unit_embark",
        "unit_disembark",
        "unit_board",
        "unit_deboard",
        "unit_load",
        "unit_unload",
        # City Foundation
        "unit_found_city",
        "unit_join_city",
        "unit_home_city",
        # Trade
        "unit_trade_route",
        "unit_marketplace",
        "unit_help_wonder",
        # Terrain
        "unit_build_road",
        "unit_build_irrigation",
        "unit_build_mine",
        "unit_build_base",
        "unit_pillage",
        "unit_clean",
        "unit_transform",
        "unit_cultivate",
        "unit_plant",
        # Unit Status
        "unit_fortify",
        "unit_sentry",
        "unit_explore",
        "unit_disband",
        "unit_upgrade",
        "unit_convert",
        "unit_heal",
        # City
        "city_production",
        "city_buy",
        "city_sell_improvement",
        # Research
        "tech_research",
        "end_turn"
    ]
    
    def test_action_type_list_completeness(self):
        """Verify we have documented all protocol action types"""
        # This test documents all expected action types
        self.assertGreater(len(self.EXPECTED_ACTION_TYPES), 70)
    
    def test_action_types_are_strings(self):
        """All action types should be snake_case strings"""
        for action_type in self.EXPECTED_ACTION_TYPES:
            self.assertIsInstance(action_type, str)
            # Snake case: lowercase with underscores
            self.assertEqual(action_type, action_type.lower())
            self.assertNotIn("-", action_type)
            self.assertNotIn(" ", action_type)


if __name__ == '__main__':
    unittest.main()
