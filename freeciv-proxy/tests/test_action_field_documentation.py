"""
TDD Documentation: Action Field Names Protocol

Documents ALL field names that FreeCiv3D sends in legal_actions.
These fields MUST be preserved through the agent-clash LLM round-trip.

## Purpose
This test file serves as living documentation of the action protocol.
If a test fails, it means either:
1. The validator changed field requirements (update agent-clash)
2. A field name was accidentally changed (fix the regression)

## Field Reference for agent-clash ActionTarget struct

| Field Name       | Used By Actions                            | Purpose                    |
|------------------|-------------------------------------------|----------------------------|
| transport_id     | unit_board, unit_embark, unit_load        | Target transport unit      |
| target_unit_id   | spy_bribe_unit, spy_sabotage_unit, attack | Target unit                |
| cargo_id         | unit_unload                               | Which cargo to unload      |
| tile_id          | unit_disembark, unit_paradrop, pillage    | Target tile                |
| extra_id         | unit_pillage                              | Infrastructure to pillage  |
| building_id      | spy_targeted_sabotage_city                | Building to sabotage       |
| tech_id          | spy_targeted_steal_tech                   | Technology to steal        |
| target_id        | Many actions                              | Generic fallback           |
| target_city_id   | Espionage, trade, airlift                 | Target city                |
| target_x/y       | Combat, paradrop, teleport                | Target coordinates         |
| sub_target       | Targeted spy actions                      | Tech/building name         |
"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator


# Game state fixture with units of various types for testing
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
            "type": "Marines",  # Can board transports
            "x": 20,
            "y": 30,
            "owner": 1,
            "moves_left": 2,
        },
        44: {
            "id": 44,
            "type": "Spy",
            "x": 15,
            "y": 25,
            "owner": 1,
            "moves_left": 2,
        },
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
            "type": "Paratroopers",
            "x": 25,
            "y": 35,
            "owner": 1,
            "moves_left": 3,
        },
        47: {
            "id": 47,
            "type": "Workers",
            "x": 30,
            "y": 40,
            "owner": 1,
            "moves_left": 2,
        },
        99: {
            "id": 99,
            "type": "Warrior",
            "x": 11,
            "y": 21,
            "owner": 2,  # Enemy unit
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
# Transport Action Fields (unit_board, unit_embark, unit_load, unit_unload)
# =============================================================================


class TestTransportActionFields(unittest.TestCase):
    """
    Document fields for transport operations.
    These fields MUST be in agent-clash ActionTarget struct.

    Transport operations allow units to board and exit transports (ships, carriers).
    The key field is `transport_id` which identifies the target transport.
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_unit_board_accepts_transport_id(self):
        """
        unit_board must accept transport_id field.

        Field: transport_id (int) - The unit ID of the transport to board
        """
        action = {"type": "unit_board", "unit_id": 43, "transport_id": 45}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"transport_id should be accepted for unit_board: {result.error_message}"
        )

    def test_unit_board_accepts_target_unit_id_as_alias(self):
        """
        unit_board also accepts target_unit_id as an alias for transport_id.

        Field: target_unit_id (int) - Alternative name for transport target
        """
        action = {"type": "unit_board", "unit_id": 43, "target_unit_id": 45}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_unit_id should be accepted for unit_board: {result.error_message}"
        )

    def test_unit_board_accepts_target_id_as_fallback(self):
        """
        unit_board also accepts target_id as a generic fallback.

        Field: target_id (int) - Generic target identifier
        """
        action = {"type": "unit_board", "unit_id": 43, "target_id": 45}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_id should be accepted for unit_board: {result.error_message}"
        )

    def test_unit_embark_accepts_transport_id(self):
        """
        unit_embark must accept transport_id field.

        Field: transport_id (int) - The unit ID of the transport to embark
        """
        action = {"type": "unit_embark", "unit_id": 43, "transport_id": 45}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"transport_id should be accepted for unit_embark: {result.error_message}"
        )

    def test_unit_load_accepts_transport_id(self):
        """
        unit_load must accept transport_id field.

        Field: transport_id (int) - The unit ID of the transport to load onto
        """
        action = {"type": "unit_load", "unit_id": 43, "transport_id": 45}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"transport_id should be accepted for unit_load: {result.error_message}"
        )

    def test_unit_unload_requires_unit_id(self):
        """
        unit_unload requires at minimum a unit_id (the transport doing the unloading).

        Note: cargo_id may be used to specify which cargo to unload, but
        the C server typically handles cargo selection.
        """
        action = {"type": "unit_unload", "unit_id": 45}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"unit_unload with unit_id should be valid: {result.error_message}"
        )

    def test_unit_disembark_requires_unit_id(self):
        """
        unit_disembark requires unit_id (the unit leaving the transport).
        """
        action = {"type": "unit_disembark", "unit_id": 43}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"unit_disembark with unit_id should be valid: {result.error_message}"
        )

    def test_unit_deboard_requires_unit_id(self):
        """
        unit_deboard requires unit_id (the unit leaving the transport).
        """
        action = {"type": "unit_deboard", "unit_id": 43}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"unit_deboard with unit_id should be valid: {result.error_message}"
        )


# =============================================================================
# Espionage Action Fields (spy_*, unit_establish_embassy)
# =============================================================================


class TestEspionageActionFields(unittest.TestCase):
    """
    Document fields for spy/diplomat operations.
    These fields MUST be in agent-clash ActionTarget struct.

    Espionage actions use diplomats/spies against enemy cities or units.
    Key fields: target_city_id, target_unit_id, sub_target (for targeted ops).
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_spy_bribe_unit_accepts_target_unit_id(self):
        """
        spy_bribe_unit must accept target_unit_id field.

        Field: target_unit_id (int) - The enemy unit to bribe
        """
        action = {"type": "spy_bribe_unit", "unit_id": 44, "target_unit_id": 99}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_unit_id should be accepted for spy_bribe_unit: {result.error_message}"
        )

    def test_spy_sabotage_unit_accepts_target_unit_id(self):
        """
        spy_sabotage_unit must accept target_unit_id field.

        Field: target_unit_id (int) - The enemy unit to sabotage
        """
        action = {"type": "spy_sabotage_unit", "unit_id": 44, "target_unit_id": 99}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_unit_id should be accepted for spy_sabotage_unit: {result.error_message}"
        )

    def test_spy_attack_accepts_target_unit_id(self):
        """
        spy_attack must accept target_unit_id field.

        Field: target_unit_id (int) - The enemy spy/diplomat to attack
        """
        action = {"type": "spy_attack", "unit_id": 44, "target_unit_id": 99}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_unit_id should be accepted for spy_attack: {result.error_message}"
        )

    def test_spy_targeted_steal_tech_accepts_sub_target(self):
        """
        spy_targeted_steal_tech must accept sub_target field (technology name).

        Field: sub_target (str) - The name of the technology to steal
        """
        action = {
            "type": "spy_targeted_steal_tech",
            "unit_id": 44,
            "target_city_id": 5,
            "sub_target": "Iron Working"
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"sub_target should be accepted for spy_targeted_steal_tech: {result.error_message}"
        )

    def test_spy_targeted_sabotage_city_accepts_sub_target(self):
        """
        spy_targeted_sabotage_city must accept sub_target field (building name).

        Field: sub_target (str) - The name of the building to sabotage
        """
        action = {
            "type": "spy_targeted_sabotage_city",
            "unit_id": 44,
            "target_city_id": 5,
            "sub_target": "Granary"
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"sub_target should be accepted for spy_targeted_sabotage_city: {result.error_message}"
        )

    def test_spy_investigate_city_accepts_target_city_id(self):
        """
        spy_investigate_city must accept target_city_id field.

        Field: target_city_id (int) - The enemy city to investigate
        """
        action = {"type": "spy_investigate_city", "unit_id": 44, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for spy_investigate_city: {result.error_message}"
        )

    def test_spy_poison_accepts_target_city_id(self):
        """
        spy_poison must accept target_city_id field.

        Field: target_city_id (int) - The enemy city to poison
        """
        action = {"type": "spy_poison", "unit_id": 44, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for spy_poison: {result.error_message}"
        )

    def test_spy_steal_tech_accepts_target_city_id(self):
        """
        spy_steal_tech (random) must accept target_city_id field.

        Field: target_city_id (int) - The enemy city to steal from
        """
        action = {"type": "spy_steal_tech", "unit_id": 44, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for spy_steal_tech: {result.error_message}"
        )

    def test_spy_incite_city_accepts_target_city_id(self):
        """
        spy_incite_city must accept target_city_id field.

        Field: target_city_id (int) - The enemy city to incite
        """
        action = {"type": "spy_incite_city", "unit_id": 44, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for spy_incite_city: {result.error_message}"
        )

    def test_spy_sabotage_city_accepts_target_city_id(self):
        """
        spy_sabotage_city (random building) must accept target_city_id field.

        Field: target_city_id (int) - The enemy city to sabotage
        """
        action = {"type": "spy_sabotage_city", "unit_id": 44, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for spy_sabotage_city: {result.error_message}"
        )

    def test_unit_establish_embassy_accepts_target_city_id(self):
        """
        unit_establish_embassy must accept target_city_id field.

        Field: target_city_id (int) - The city to establish embassy in
        """
        action = {"type": "unit_establish_embassy", "unit_id": 44, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for unit_establish_embassy: {result.error_message}"
        )

    def test_unit_establish_embassy_accepts_target_player_id(self):
        """
        unit_establish_embassy also accepts target_player_id as alternative.

        Field: target_player_id (int) - Alternative way to specify embassy target
        """
        action = {"type": "unit_establish_embassy", "unit_id": 44, "target_player_id": 2}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_player_id should be accepted for unit_establish_embassy: {result.error_message}"
        )


# =============================================================================
# Combat Action Fields (unit_attack, unit_bombard, unit_nuke, etc.)
# =============================================================================


class TestCombatActionFields(unittest.TestCase):
    """
    Document fields for combat operations.
    These fields MUST be in agent-clash ActionTarget struct.

    Combat actions can target by coordinates (target_x, target_y) or
    by specific unit/city ID (target_unit_id, target_city_id).
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_unit_attack_accepts_target_coordinates(self):
        """
        unit_attack must accept target_x, target_y coordinates.

        Fields:
          - target_x (int) - X coordinate of attack target
          - target_y (int) - Y coordinate of attack target
        """
        action = {"type": "unit_attack", "unit_id": 42, "target_x": 11, "target_y": 21}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_x/target_y should be accepted for unit_attack: {result.error_message}"
        )

    def test_unit_attack_accepts_target_unit_id(self):
        """
        unit_attack can use target_unit_id instead of coordinates.

        Field: target_unit_id (int) - The enemy unit to attack
        """
        action = {"type": "unit_attack", "unit_id": 42, "target_unit_id": 99}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_unit_id should be accepted for unit_attack: {result.error_message}"
        )

    def test_unit_bombard_accepts_target_coordinates(self):
        """
        unit_bombard must accept target coordinates.

        Fields: target_x (int), target_y (int)
        """
        action = {"type": "unit_bombard", "unit_id": 42, "target_x": 11, "target_y": 21}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target coordinates should be accepted for unit_bombard: {result.error_message}"
        )

    def test_unit_capture_accepts_target_unit_id(self):
        """
        unit_capture can use target_unit_id.

        Field: target_unit_id (int) - The unit to capture
        """
        action = {"type": "unit_capture", "unit_id": 42, "target_unit_id": 99}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_unit_id should be accepted for unit_capture: {result.error_message}"
        )

    def test_unit_nuke_accepts_target_coordinates(self):
        """
        unit_nuke must accept target coordinates.

        Fields: target_x (int), target_y (int) - Location to nuke
        """
        action = {"type": "unit_nuke", "unit_id": 42, "target_x": 30, "target_y": 30}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target coordinates should be accepted for unit_nuke: {result.error_message}"
        )

    def test_unit_nuke_city_accepts_target_city_id(self):
        """
        unit_nuke_city must accept target_city_id.

        Field: target_city_id (int) - The city to nuke
        """
        action = {"type": "unit_nuke_city", "unit_id": 42, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for unit_nuke_city: {result.error_message}"
        )

    def test_unit_nuke_units_accepts_target_coordinates(self):
        """
        unit_nuke_units must accept target coordinates.

        Fields: target_x (int), target_y (int) - Location with units to nuke
        """
        action = {"type": "unit_nuke_units", "unit_id": 42, "target_x": 11, "target_y": 21}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target coordinates should be accepted for unit_nuke_units: {result.error_message}"
        )

    def test_unit_conquer_city_accepts_target_city_id(self):
        """
        unit_conquer_city can use target_city_id.

        Field: target_city_id (int) - The city to conquer
        """
        action = {"type": "unit_conquer_city", "unit_id": 42, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for unit_conquer_city: {result.error_message}"
        )


# =============================================================================
# Movement Action Fields (unit_paradrop, unit_teleport, unit_airlift)
# =============================================================================


class TestMovementActionFields(unittest.TestCase):
    """
    Document fields for special movement operations.
    These fields MUST be in agent-clash ActionTarget struct.

    Special movement uses coordinates for destination or city IDs.
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_unit_paradrop_accepts_target_coordinates(self):
        """
        unit_paradrop must accept target_x, target_y coordinates.

        Fields:
          - target_x (int) - X coordinate of paradrop destination
          - target_y (int) - Y coordinate of paradrop destination
        """
        action = {"type": "unit_paradrop", "unit_id": 46, "target_x": 25, "target_y": 35}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target coordinates should be accepted for unit_paradrop: {result.error_message}"
        )

    def test_unit_teleport_accepts_target_coordinates(self):
        """
        unit_teleport must accept target_x, target_y coordinates.

        Fields:
          - target_x (int) - X coordinate of teleport destination
          - target_y (int) - Y coordinate of teleport destination
        """
        action = {"type": "unit_teleport", "unit_id": 42, "target_x": 40, "target_y": 45}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target coordinates should be accepted for unit_teleport: {result.error_message}"
        )

    def test_unit_airlift_accepts_target_city_id(self):
        """
        unit_airlift must accept target_city_id field.

        Field: target_city_id (int) - The destination city for airlift
        """
        action = {"type": "unit_airlift", "unit_id": 42, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for unit_airlift: {result.error_message}"
        )


# =============================================================================
# Trade Action Fields (trade_route, unit_help_wonder, unit_marketplace)
# =============================================================================


class TestTradeActionFields(unittest.TestCase):
    """
    Document fields for trade/caravan operations.
    These fields MUST be in agent-clash ActionTarget struct.

    Trade actions use target_city_id for the destination city.
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1
        # Add a caravan unit for trade tests
        self.game_state = GAME_STATE.copy()
        self.game_state["units"] = GAME_STATE["units"].copy()
        self.game_state["units"][50] = {
            "id": 50,
            "type": "Caravan",
            "x": 15,
            "y": 25,
            "owner": 1,
            "moves_left": 3,
        }

    def test_unit_trade_route_accepts_target_city_id(self):
        """
        unit_trade_route must accept target_city_id field.

        Field: target_city_id (int) - The destination city for trade route
        """
        action = {"type": "unit_trade_route", "unit_id": 50, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for unit_trade_route: {result.error_message}"
        )

    def test_trade_route_alias_accepts_target_city_id(self):
        """
        trade_route (legacy alias) must accept target_city_id field.

        Field: target_city_id (int) - The destination city for trade route
        """
        action = {"type": "trade_route", "unit_id": 50, "target_city_id": 5}
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for trade_route: {result.error_message}"
        )

    def test_unit_help_wonder_accepts_target_city_id(self):
        """
        unit_help_wonder must accept target_city_id field.

        Field: target_city_id (int) - The city building a wonder to help
        """
        action = {"type": "unit_help_wonder", "unit_id": 50, "target_city_id": 1}
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(
            result.is_valid,
            f"target_city_id should be accepted for unit_help_wonder: {result.error_message}"
        )

    def test_unit_marketplace_requires_unit_id(self):
        """
        unit_marketplace requires at minimum unit_id.
        Entering marketplace is typically done at current location.
        """
        action = {"type": "unit_marketplace", "unit_id": 50}
        result = self.validator.validate_action(action, self.player_id, self.game_state)
        self.assertTrue(
            result.is_valid,
            f"unit_marketplace with unit_id should be valid: {result.error_message}"
        )


# =============================================================================
# Terrain Action Fields (unit_pillage, unit_build_base)
# =============================================================================


class TestTerrainActionFields(unittest.TestCase):
    """
    Document fields for terrain improvement operations.
    These fields MUST be in agent-clash ActionTarget struct.

    Terrain actions may specify optional targets (what to pillage, base type).
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_unit_pillage_accepts_target_field(self):
        """
        unit_pillage accepts optional target field to specify infrastructure.

        Field: target (str) - Infrastructure type to pillage (e.g., "Road", "Irrigation")
        """
        action = {"type": "unit_pillage", "unit_id": 47, "target": "Road"}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"target field should be accepted for unit_pillage: {result.error_message}"
        )

    def test_unit_pillage_works_without_target(self):
        """
        unit_pillage works without explicit target (server chooses).
        """
        action = {"type": "unit_pillage", "unit_id": 47}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"unit_pillage without target should be valid: {result.error_message}"
        )

    def test_unit_build_base_accepts_base_type(self):
        """
        unit_build_base accepts optional base_type field.

        Field: base_type (str) - Type of base to build (e.g., "Fortress", "Airbase")
        """
        action = {"type": "unit_build_base", "unit_id": 47, "base_type": "Fortress"}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"base_type field should be accepted for unit_build_base: {result.error_message}"
        )


# =============================================================================
# City Action Fields (city_production, city_buy, city_sell_improvement)
# =============================================================================


class TestCityActionFields(unittest.TestCase):
    """
    Document fields for city management operations.
    These fields MUST be in agent-clash ActionTarget struct.
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_city_production_accepts_production_type(self):
        """
        city_production must accept production_type field.

        Field: production_type (str) - Unit or building name to produce
        """
        action = {
            "type": "city_production",
            "city_id": 1,
            "production_type": "Phalanx"
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"production_type should be accepted for city_production: {result.error_message}"
        )

    def test_city_buy_requires_city_id(self):
        """
        city_buy requires city_id field.

        Field: city_id (int) - The city to buy production in
        """
        action = {"type": "city_buy", "city_id": 1}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"city_id should be accepted for city_buy: {result.error_message}"
        )

    def test_city_sell_improvement_accepts_improvement_name(self):
        """
        city_sell_improvement accepts improvement_name field.

        Field: improvement_name (str) - Name of building to sell
        """
        action = {
            "type": "city_sell_improvement",
            "city_id": 1,
            "improvement_name": "Granary"
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"improvement_name should be accepted for city_sell_improvement: {result.error_message}"
        )

    def test_city_sell_improvement_accepts_improvement_id(self):
        """
        city_sell_improvement also accepts improvement_id field.

        Field: improvement_id (int) - ID of building to sell
        """
        action = {
            "type": "city_sell_improvement",
            "city_id": 1,
            "improvement_id": 10
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"improvement_id should be accepted for city_sell_improvement: {result.error_message}"
        )


# =============================================================================
# Diplomacy Action Fields (diplomacy_*, share_vision)
# =============================================================================


class TestDiplomacyActionFields(unittest.TestCase):
    """
    Document fields for diplomacy operations.
    These fields MUST be in agent-clash ActionTarget struct.
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_diplomacy_actions_accept_target_player_id(self):
        """
        All diplomacy actions require target_player_id field.

        Field: target_player_id (int) - The player to interact with diplomatically
        """
        diplomacy_actions = [
            "diplomacy_declare_war",
            "diplomacy_cancel_treaty",
            "diplomacy_propose_ceasefire",
            "diplomacy_propose_peace",
            "diplomacy_propose_alliance",
            "diplomacy_share_vision",
            "diplomacy_withdraw_vision",
        ]

        for action_type in diplomacy_actions:
            action = {"type": action_type, "target_player_id": 2}
            result = self.validator.validate_action(action, self.player_id, GAME_STATE)
            self.assertTrue(
                result.is_valid,
                f"target_player_id should be accepted for {action_type}: {result.error_message}"
            )

    def test_diplomacy_message_accepts_message_field(self):
        """
        diplomacy_message must accept message field.

        Fields:
          - target_player_id (int) - The player to message
          - message (str) - The diplomatic message content
        """
        action = {
            "type": "diplomacy_message",
            "target_player_id": 2,
            "message": "Let us form an alliance!"
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertTrue(
            result.is_valid,
            f"message field should be accepted for diplomacy_message: {result.error_message}"
        )


# =============================================================================
# Unit Status Action Fields (fortify, sentry, explore, upgrade, etc.)
# =============================================================================


class TestUnitStatusActionFields(unittest.TestCase):
    """
    Document fields for unit status operations.
    Most of these only require unit_id.
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_basic_unit_status_actions_require_only_unit_id(self):
        """
        Basic unit status actions only require unit_id field.

        Field: unit_id (int) - The unit to modify status of
        """
        status_actions = [
            "unit_fortify",
            "unit_sentry",
            "unit_explore",
            "unit_disband",
            "unit_upgrade",
            "unit_convert",
            "unit_heal",
            "unit_skip",
            "unit_wake",
        ]

        for action_type in status_actions:
            action = {"type": action_type, "unit_id": 42}
            result = self.validator.validate_action(action, self.player_id, GAME_STATE)
            self.assertTrue(
                result.is_valid,
                f"unit_id should be sufficient for {action_type}: {result.error_message}"
            )


# =============================================================================
# Error Cases - Document Required Fields by Testing Failures
# =============================================================================


class TestMissingFieldErrors(unittest.TestCase):
    """
    Document which fields are REQUIRED by testing error cases.
    These tests verify the validator rejects actions missing required fields.
    """

    def setUp(self):
        self.validator = LLMActionValidator()
        self.player_id = 1

    def test_unit_board_without_transport_fails(self):
        """
        unit_board without transport_id/target_unit_id/target_id must fail.

        Error: E283 - Missing transport target
        """
        action = {"type": "unit_board", "unit_id": 43}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E283")

    def test_spy_bribe_unit_without_target_fails(self):
        """
        spy_bribe_unit without target_unit_id must fail.

        Error: E275 - Missing target unit
        """
        action = {"type": "spy_bribe_unit", "unit_id": 44}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E275")

    def test_spy_targeted_steal_tech_without_sub_target_fails(self):
        """
        spy_targeted_steal_tech without sub_target must fail.

        Error: E274 - Missing sub_target (technology name)
        """
        action = {
            "type": "spy_targeted_steal_tech",
            "unit_id": 44,
            "target_city_id": 5
        }
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E274")

    def test_unit_paradrop_without_coordinates_fails(self):
        """
        unit_paradrop without target_x/target_y must fail.

        Error: E285 - Missing paradrop coordinates
        """
        action = {"type": "unit_paradrop", "unit_id": 46}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E285")

    def test_diplomacy_action_without_target_player_fails(self):
        """
        Diplomacy actions without target_player_id must fail.

        Error: E260 - Missing target player
        """
        action = {"type": "diplomacy_declare_war"}
        result = self.validator.validate_action(action, self.player_id, GAME_STATE)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "E260")


if __name__ == "__main__":
    unittest.main()
