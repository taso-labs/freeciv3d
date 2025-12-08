"""
Tests for LLM Action Validator Behavior

These tests verify that the action validators actually work correctly:
- Correct validation passes
- Missing fields are rejected with correct error codes
- Wrong player ownership is rejected
- Unit/city not found errors are returned
- Specific action type requirements are enforced
- Security validations (XSS, ReDoS, character allowlists)

These tests call the actual validator methods with mock game state.
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import (
    LLMActionValidator,
    ActionType,
    ActionCategory,
    ACTION_CATEGORIES,
)


# Sample game state fixture
GAME_STATE = {
    "turn": 15,
    "phase": "movement",
    "map_info": {"width": 80, "height": 50},
    "units": {
        42: {
            "id": 42,
            "type": "Warrior",
            "x": 10,
            "y": 20,
            "owner": 1,
            "moves_left": 1,
        },
        43: {
            "id": 43,
            "type": "Diplomat",
            "x": 12,
            "y": 22,
            "owner": 1,
            "moves_left": 2,
        },
        44: {"id": 44, "type": "Spy", "x": 15, "y": 25, "owner": 1, "moves_left": 2},
        45: {
            "id": 45,
            "type": "Transport",
            "x": 20,
            "y": 30,
            "owner": 1,
            "moves_left": 5,
        },
        46: {
            "id": 46,
            "type": "Workers",
            "x": 10,
            "y": 15,
            "owner": 1,
            "moves_left": 3,
        },
        47: {"id": 47, "type": "Settlers", "x": 5, "y": 8, "owner": 1, "moves_left": 2},
        99: {
            "id": 99,
            "type": "Warrior",
            "x": 11,
            "y": 21,
            "owner": 2,
            "moves_left": 1,
        },
    },
    "cities": {
        1: {"id": 1, "name": "Capital", "x": 15, "y": 25, "owner": 1, "size": 3},
        5: {"id": 5, "name": "Enemy City", "x": 30, "y": 30, "owner": 2, "size": 2},
    },
    "players": {
        1: {"id": 1, "name": "Player1", "nation": "Romans", "gold": 100},
        2: {"id": 2, "name": "Player2", "nation": "Greeks", "gold": 80},
    },
}


# =============================================================================
# Unit State Actions (fortify, sentry)
# =============================================================================


class TestUnitStateActionValidation(unittest.TestCase):
    """Test unit state action validators (fortify, sentry)"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    # -------------------------------------------------------------------------
    # unit_fortify Tests
    # -------------------------------------------------------------------------

    def test_unit_fortify_valid(self):
        """Valid fortify action should pass validation"""
        action = {"type": "unit_fortify", "unit_id": 42}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid, f"Expected valid, got error: {result.error_message}"
        )

    def test_unit_fortify_missing_unit_id(self):
        """Fortify without unit_id should fail with E050"""
        action = {"type": "unit_fortify"}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E050")

    def test_unit_fortify_wrong_player(self):
        """Fortify unit owned by another player should fail with E052"""
        action = {"type": "unit_fortify", "unit_id": 99}  # Owned by player 2
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E052")

    def test_unit_fortify_unit_not_found(self):
        """Fortify non-existent unit should fail with E051"""
        action = {"type": "unit_fortify", "unit_id": 9999}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E051")

    def test_unit_fortify_without_game_state(self):
        """Fortify should work without game state (minimal validation)"""
        action = {"type": "unit_fortify", "unit_id": 42}
        result = self.validator.validate_action(action, self.player_id, None)
        self.assertTrue(result.is_valid)

    # -------------------------------------------------------------------------
    # unit_sentry Tests
    # -------------------------------------------------------------------------

    def test_unit_sentry_valid(self):
        """Valid sentry action should pass validation"""
        action = {"type": "unit_sentry", "unit_id": 42}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_unit_sentry_missing_unit_id(self):
        """Sentry without unit_id should fail with E060"""
        action = {"type": "unit_sentry"}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E060")

    def test_unit_sentry_wrong_player(self):
        """Sentry unit owned by another player should fail"""
        action = {"type": "unit_sentry", "unit_id": 99}  # Owned by player 2
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)

    def test_unit_sentry_unit_not_found(self):
        """Sentry non-existent unit should fail"""
        action = {"type": "unit_sentry", "unit_id": 8888}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)

    def test_unit_sentry_without_game_state(self):
        """Sentry should work without game state"""
        action = {"type": "unit_sentry", "unit_id": 42}
        result = self.validator.validate_action(action, self.player_id, None)
        self.assertTrue(result.is_valid)


# =============================================================================
# Combat Actions
# =============================================================================


class TestCombatActionValidation(unittest.TestCase):
    """Test combat action validator behavior"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_unit_attack_valid(self):
        """Valid attack action should pass validation"""
        action = {
            "type": "unit_attack",
            "unit_id": 42,
            "target_x": 11,
            "target_y": 21,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid, f"Expected valid, got: {result.error_message}")

    def test_unit_attack_missing_unit_id(self):
        """Attack without unit_id should fail with E230"""
        action = {
            "type": "unit_attack",
            "target_x": 11,
            "target_y": 21,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E230")

    def test_unit_attack_unit_not_owned(self):
        """Attack with enemy unit should fail with E231"""
        action = {
            "type": "unit_attack",
            "unit_id": 99,  # Enemy unit
            "target_x": 10,
            "target_y": 20,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E231")

    def test_unit_attack_unit_not_found(self):
        """Attack with non-existent unit should fail with E232"""
        action = {
            "type": "unit_attack",
            "unit_id": 9999,
            "target_x": 11,
            "target_y": 21,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E232")

    def test_unit_attack_missing_target(self):
        """Attack without target should fail with E235"""
        action = {
            "type": "unit_attack",
            "unit_id": 42,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E235")

    def test_unit_attack_target_out_of_bounds(self):
        """Attack with out-of-bounds target should fail with E233"""
        action = {
            "type": "unit_attack",
            "unit_id": 42,
            "target_x": 999,
            "target_y": 999,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E233")

    def test_unit_attack_with_target_unit_id(self):
        """Attack with target_unit_id instead of coordinates should pass"""
        action = {
            "type": "unit_attack",
            "unit_id": 42,
            "target_unit_id": 99,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_unit_nuke_valid(self):
        """Valid nuke action should pass validation"""
        action = {
            "type": "unit_nuke",
            "unit_id": 42,
            "target_x": 30,
            "target_y": 30,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        # Nuke action with valid parameters passes validation
        self.assertTrue(result.is_valid)

    def test_unit_nuke_missing_target(self):
        """Nuke without target should fail"""
        action = {
            "type": "unit_nuke",
            "unit_id": 42,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E236")


class TestDiplomacyActionValidation(unittest.TestCase):
    """Test diplomacy action validator behavior"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_diplomacy_declare_war_valid(self):
        """Valid declare war should pass"""
        action = {
            "type": "diplomacy_declare_war",
            "target_player_id": 2,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid, f"Expected valid, got: {result.error_message}")

    def test_diplomacy_missing_target_player(self):
        """Diplomacy without target_player_id should fail with E260"""
        action = {
            "type": "diplomacy_declare_war",
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E260")

    def test_diplomacy_self_target(self):
        """Diplomacy targeting self should fail with E261"""
        action = {
            "type": "diplomacy_declare_war",
            "target_player_id": 1,  # Same as player_id
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E261")

    def test_diplomacy_player_not_found(self):
        """Diplomacy targeting non-existent player should fail with E262"""
        action = {
            "type": "diplomacy_declare_war",
            "target_player_id": 999,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E262")

    def test_diplomacy_message_valid(self):
        """Valid diplomacy message should pass"""
        action = {
            "type": "diplomacy_message",
            "target_player_id": 2,
            "message": "Let's make peace!",
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_diplomacy_message_missing_message(self):
        """Diplomacy message without message field should fail with E263"""
        action = {
            "type": "diplomacy_message",
            "target_player_id": 2,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E263")

    def test_diplomacy_message_too_long(self):
        """Diplomacy message over 500 chars should fail"""
        action = {
            "type": "diplomacy_message",
            "target_player_id": 2,
            "message": "x" * 501,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        # E224 (string too long) or E264 (message too long) depending on validation order
        self.assertIn(result.error_code, ["E224", "E264"])


class TestEspionageActionValidation(unittest.TestCase):
    """Test espionage action validator behavior"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_spy_steal_tech_valid(self):
        """Valid spy steal tech should pass"""
        action = {
            "type": "spy_steal_tech",
            "unit_id": 44,  # Spy unit
            "target_city_id": 5,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid, f"Expected valid, got: {result.error_message}")

    def test_spy_missing_unit_id(self):
        """Spy action without unit_id should fail with E270"""
        action = {
            "type": "spy_steal_tech",
            "target_city_id": 5,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E270")

    def test_spy_unit_not_owned(self):
        """Spy action with enemy unit should fail with E271"""
        action = {
            "type": "spy_steal_tech",
            "unit_id": 99,  # Enemy unit
            "target_city_id": 5,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E271")

    def test_spy_unit_not_found(self):
        """Spy action with non-existent unit should fail with E272"""
        action = {
            "type": "spy_steal_tech",
            "unit_id": 9999,
            "target_city_id": 5,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E272")

    def test_spy_steal_tech_missing_city(self):
        """Spy steal tech without target_city_id should fail with E273"""
        action = {
            "type": "spy_steal_tech",
            "unit_id": 44,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E273")

    def test_spy_targeted_steal_tech_missing_sub_target(self):
        """spy_targeted_steal_tech without sub_target should fail with E274"""
        action = {
            "type": "spy_targeted_steal_tech",
            "unit_id": 44,
            "target_city_id": 5,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E274")

    def test_spy_targeted_steal_tech_valid(self):
        """spy_targeted_steal_tech with sub_target should pass"""
        action = {
            "type": "spy_targeted_steal_tech",
            "unit_id": 44,
            "target_city_id": 5,
            "sub_target": "Iron Working",
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_spy_bribe_unit_missing_target(self):
        """spy_bribe_unit without target_unit_id should fail with E275"""
        action = {
            "type": "spy_bribe_unit",
            "unit_id": 44,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E275")

    def test_spy_bribe_unit_valid(self):
        """Valid spy bribe unit should pass"""
        action = {
            "type": "spy_bribe_unit",
            "unit_id": 44,
            "target_unit_id": 99,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)


class TestMovementActionValidation(unittest.TestCase):
    """Test movement/transport action validator behavior"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_unit_embark_valid(self):
        """Valid embark should pass"""
        action = {
            "type": "unit_embark",
            "unit_id": 42,
            "transport_id": 45,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_unit_embark_missing_transport(self):
        """Embark without transport should fail with E283"""
        action = {
            "type": "unit_embark",
            "unit_id": 42,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E283")

    def test_unit_airlift_valid(self):
        """Valid airlift should pass"""
        action = {
            "type": "unit_airlift",
            "unit_id": 42,
            "target_city_id": 1,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_unit_airlift_missing_city(self):
        """Airlift without target city should fail with E284"""
        action = {
            "type": "unit_airlift",
            "unit_id": 42,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E284")

    def test_unit_paradrop_valid(self):
        """Valid paradrop should pass"""
        action = {
            "type": "unit_paradrop",
            "unit_id": 42,
            "target_x": 25,
            "target_y": 35,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_unit_paradrop_missing_target(self):
        """Paradrop without target should fail with E285"""
        action = {
            "type": "unit_paradrop",
            "unit_id": 42,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E285")

    def test_unit_paradrop_out_of_bounds(self):
        """Paradrop to invalid coords should fail with E286"""
        action = {
            "type": "unit_paradrop",
            "unit_id": 42,
            "target_x": 999,
            "target_y": 999,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E286")


class TestTerrainActionValidation(unittest.TestCase):
    """Test terrain improvement action validator behavior"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    # -------------------------------------------------------------------------
    # unit_build_road Tests
    # -------------------------------------------------------------------------

    def test_build_road_valid(self):
        """Valid build road should pass"""
        action = {"type": "unit_build_road", "unit_id": 46}  # Workers unit
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_build_road_missing_unit(self):
        """Build road without unit_id should fail with E070"""
        action = {"type": "unit_build_road"}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E070")

    def test_build_road_wrong_player(self):
        """Build road with unit owned by other player should fail"""
        action = {"type": "unit_build_road", "unit_id": 99}  # Enemy unit
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)

    def test_build_road_without_coordinates(self):
        """Build road without coordinates should PASS per Protocol v2.0.1

        Per protocol: Terrain improvement actions operate on the unit's current tile.
        No target coordinates needed.
        """
        action = {"type": "unit_build_road", "unit_id": 46}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    # -------------------------------------------------------------------------
    # unit_build_irrigation Tests
    # -------------------------------------------------------------------------

    def test_build_irrigation_valid(self):
        """Valid build irrigation should pass"""
        action = {"type": "unit_build_irrigation", "unit_id": 46}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_build_irrigation_missing_unit(self):
        """Build irrigation without unit_id should fail with E080"""
        action = {"type": "unit_build_irrigation"}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E080")

    def test_build_irrigation_wrong_player(self):
        """Build irrigation with unit owned by other player should fail"""
        action = {"type": "unit_build_irrigation", "unit_id": 99}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)

    def test_build_irrigation_unit_not_found(self):
        """Build irrigation with non-existent unit should fail"""
        action = {"type": "unit_build_irrigation", "unit_id": 7777}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)

    def test_build_irrigation_without_game_state(self):
        """Build irrigation without game state should still pass basic validation"""
        action = {"type": "unit_build_irrigation", "unit_id": 46}
        result = self.validator.validate_action(action, self.player_id, None)
        self.assertTrue(result.is_valid)

    # -------------------------------------------------------------------------
    # unit_build_mine Tests
    # -------------------------------------------------------------------------

    def test_build_mine_valid(self):
        """Valid build mine should pass"""
        action = {"type": "unit_build_mine", "unit_id": 46}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_build_mine_missing_unit(self):
        """Build mine without unit_id should fail with E090"""
        action = {"type": "unit_build_mine"}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E090")

    def test_build_mine_wrong_player(self):
        """Build mine with unit owned by other player should fail"""
        action = {"type": "unit_build_mine", "unit_id": 99}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)

    def test_build_mine_unit_not_found(self):
        """Build mine with non-existent unit should fail"""
        action = {"type": "unit_build_mine", "unit_id": 6666}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)

    def test_build_mine_without_game_state(self):
        """Build mine without game state should still pass basic validation"""
        action = {"type": "unit_build_mine", "unit_id": 46}
        result = self.validator.validate_action(action, self.player_id, None)
        self.assertTrue(result.is_valid)

    # -------------------------------------------------------------------------
    # unit_pillage Tests
    # -------------------------------------------------------------------------

    def test_pillage_valid(self):
        """Valid pillage should pass"""
        action = {"type": "unit_pillage", "unit_id": 42}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)
        self.assertTrue(result.is_valid)


class TestTradeActionValidation(unittest.TestCase):
    """Test trade action validator behavior"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_trade_route_valid(self):
        """Valid trade route should pass"""
        action = {
            "type": "unit_trade_route",
            "unit_id": 42,
            "target_city_id": 5,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_trade_route_missing_unit(self):
        """Trade route without unit_id should fail with E310"""
        action = {
            "type": "unit_trade_route",
            "target_city_id": 5,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E310")

    def test_trade_route_missing_city(self):
        """Trade route without target_city_id should fail with E313"""
        action = {
            "type": "unit_trade_route",
            "unit_id": 42,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E313")


class TestCityManagementActionValidation(unittest.TestCase):
    """Test city management action validator behavior"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_city_buy_valid(self):
        """Valid city buy should pass"""
        action = {
            "type": "city_buy",
            "city_id": 1,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_city_buy_missing_city(self):
        """City buy without city_id should fail with E320"""
        action = {
            "type": "city_buy",
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E320")

    def test_city_buy_not_owned(self):
        """City buy for enemy city should fail with E321"""
        action = {
            "type": "city_buy",
            "city_id": 5,  # Enemy city
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E321")

    def test_city_buy_not_found(self):
        """City buy for non-existent city should fail with E322"""
        action = {
            "type": "city_buy",
            "city_id": 9999,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E322")

    def test_city_sell_improvement_valid(self):
        """Valid city sell improvement should pass"""
        action = {
            "type": "city_sell_improvement",
            "city_id": 1,
            "improvement_name": "Barracks",
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(result.is_valid)

    def test_city_sell_improvement_missing_improvement(self):
        """City sell without improvement should fail with E323"""
        action = {
            "type": "city_sell_improvement",
            "city_id": 1,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E323")


class TestUnknownActionRejection(unittest.TestCase):
    """Test that unknown actions are properly rejected"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_unknown_action_type_rejected(self):
        """Unknown action types should be rejected with E003"""
        action = {
            "type": "totally_fake_action",
            "unit_id": 42,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E003")


class TestActionCategoryMapping(unittest.TestCase):
    """Test that action types are correctly mapped to categories"""

    def test_combat_actions_mapped(self):
        """Combat actions should be in COMBAT category"""
        combat_actions = [
            ActionType.UNIT_ATTACK,
            ActionType.UNIT_BOMBARD,
            ActionType.UNIT_CAPTURE,
        ]
        for action_type in combat_actions:
            self.assertEqual(
                ACTION_CATEGORIES.get(action_type),
                ActionCategory.COMBAT,
                f"{action_type} should be COMBAT",
            )

    def test_diplomacy_actions_mapped(self):
        """Diplomacy actions should be in DIPLOMACY category"""
        diplomacy_actions = [
            ActionType.DIPLOMACY_DECLARE_WAR,
            ActionType.DIPLOMACY_PROPOSE_PEACE,
            ActionType.DIPLOMACY_MESSAGE,
        ]
        for action_type in diplomacy_actions:
            self.assertEqual(
                ACTION_CATEGORIES.get(action_type),
                ActionCategory.DIPLOMACY,
                f"{action_type} should be DIPLOMACY",
            )

    def test_espionage_actions_mapped(self):
        """Espionage actions should be in ESPIONAGE category"""
        espionage_actions = [
            ActionType.SPY_STEAL_TECH,
            ActionType.SPY_BRIBE_UNIT,
            ActionType.SPY_SABOTAGE_CITY,
        ]
        for action_type in espionage_actions:
            self.assertEqual(
                ACTION_CATEGORIES.get(action_type),
                ActionCategory.ESPIONAGE,
                f"{action_type} should be ESPIONAGE",
            )


# =============================================================================
# Input Validation & Security Tests
# =============================================================================


class TestInputValidatorIntegration(unittest.TestCase):
    """Test InputValidator integration in action validation (security)"""

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_redos_protection_long_input(self):
        """Very long input should be rejected before regex matching"""
        # Create a message that exceeds MAX_INPUT_LENGTH_FOR_REGEX (2048)
        long_message = "A" * 3000
        action = {
            "type": "diplomacy_message",
            "target_player_id": 2,
            "message": long_message,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        # Should fail due to message too long (E224 or E264)
        self.assertFalse(result.is_valid)

    def test_sql_injection_blocked(self):
        """Character allowlist blocks SQL keywords like OR and ="""
        action = {
            "type": "diplomacy_message",
            "target_player_id": 2,
            "message": "Hello' OR '1'='1",
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        # E223 from character allowlist (blocks OR keyword and =)
        self.assertEqual(result.error_code, "E223")

    def test_xss_injection_blocked(self):
        """XSS injection should be blocked"""
        action = {
            "type": "diplomacy_message",
            "target_player_id": 2,
            "message": '<script>alert("xss")</script>',
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        # E223 from character allowlist (< and > not allowed) or E266 from XSS detection
        self.assertIn(result.error_code, ["E223", "E266"])

    def test_espionage_xss_in_sub_target_blocked(self):
        """XSS in espionage sub_target should be blocked"""
        action = {
            "type": "spy_targeted_steal_tech",
            "unit_id": 44,
            "target_city_id": 5,
            "sub_target": "<script>evil()</script>",
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        # Should fail due to invalid characters in tech_name

    def test_boolean_coordinates_rejected(self):
        """Boolean values as coordinates should fail type validation"""
        action = {
            "type": "unit_attack",
            "unit_id": 42,
            "target_x": True,  # Boolean instead of int
            "target_y": 16,
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        # Should be E221 (invalid type) or similar from InputValidator


if __name__ == "__main__":
    unittest.main()
