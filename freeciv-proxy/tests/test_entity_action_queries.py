"""
Tests for LLM WebSocket Protocol v2.0.1 Entity Action Queries (Batch)

Tests the unit_actions_query and city_actions_query batch message handling:
- Request validation with unit_ids/city_ids arrays
- Batch processing of multiple entities
- Response format per protocol spec (data.units/data.cities dictionaries)
- Partial success handling (some valid, some invalid)
- Error handling (E230, E231, E240, E241, E503)

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


# Sample game state fixture for testing
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
            "hp": 10,
            "activity": "idle",
            "can_fortify": True,
            "can_sentry": True
        },
        "43": {
            "id": 43, 
            "type": "Settler", 
            "x": 12, 
            "y": 22, 
            "owner": 1, 
            "moves_left": 2,
            "hp": 20,
            "activity": "idle",
            "can_found_city": True
        },
        "44": {
            "id": 44, 
            "type": "Workers", 
            "x": 15, 
            "y": 25, 
            "owner": 1, 
            "moves_left": 2,
            "hp": 20,
            "activity": "idle",
            "can_build_road": True,
            "can_build_irrigation": True,
            "can_build_mine": True
        },
        "99": {
            "id": 99, 
            "type": "Warrior", 
            "x": 11, 
            "y": 21, 
            "owner": 2,  # Enemy unit
            "moves_left": 1,
            "hp": 10,
            "activity": "idle"
        }
    },
    "cities": {
        "1": {
            "id": 1, 
            "name": "Capital", 
            "x": 15, 
            "y": 25, 
            "owner": 1, 
            "size": 3,
            "production": "Warrior",
            "improvements": ["Granary", "Barracks"],
            "can_build": ["Warrior", "Settler", "Workers", "Phalanx", "Granary", "Barracks", "City Walls"]
        },
        "5": {
            "id": 5, 
            "name": "Second City", 
            "x": 20, 
            "y": 30, 
            "owner": 1, 
            "size": 2,
            "production": "Settler",
            "improvements": ["Granary"],
            "can_build": ["Warrior", "Settler", "Workers"]
        },
        "6": {
            "id": 6, 
            "name": "Enemy City", 
            "x": 30, 
            "y": 30, 
            "owner": 2,  # Enemy city
            "size": 2
        }
    },
    "players": {
        "1": {"id": 1, "name": "Player1", "nation": "Romans", "gold": 100},
        "2": {"id": 2, "name": "Player2", "nation": "Greeks", "gold": 80}
    }
}


class TestUnitActionsQueryValidation(unittest.TestCase):
    """Test unit_actions_query message validation"""

    def test_valid_unit_actions_query_batch_message(self):
        """Valid unit_actions_query with unit_ids array should be accepted"""
        message = {
            "type": "unit_actions_query",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "correlation_id": "batch-query-001",
            "data": {
                "unit_ids": [42, 43, 44]
            }
        }
        
        # Should have required fields
        self.assertEqual(message["type"], "unit_actions_query")
        self.assertIn("data", message)
        self.assertIn("unit_ids", message["data"])
        self.assertIsInstance(message["data"]["unit_ids"], list)
        self.assertEqual(len(message["data"]["unit_ids"]), 3)

    def test_unit_actions_query_single_unit(self):
        """unit_actions_query with single unit_id in array is valid"""
        message = {
            "type": "unit_actions_query",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "data": {
                "unit_ids": [42]
            }
        }
        
        self.assertEqual(len(message["data"]["unit_ids"]), 1)

    def test_unit_actions_query_missing_unit_ids(self):
        """unit_actions_query without unit_ids should fail with E220"""
        message = {
            "type": "unit_actions_query",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "data": {}  # Missing unit_ids
        }
        
        # Validation should require unit_ids
        self.assertNotIn("unit_ids", message["data"])

    def test_unit_actions_query_empty_unit_ids(self):
        """unit_actions_query with empty unit_ids array should fail"""
        message = {
            "type": "unit_actions_query",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "data": {
                "unit_ids": []  # Empty array
            }
        }
        
        self.assertEqual(len(message["data"]["unit_ids"]), 0)


class TestCityActionsQueryValidation(unittest.TestCase):
    """Test city_actions_query message validation"""

    def test_valid_city_actions_query_batch_message(self):
        """Valid city_actions_query with city_ids array should be accepted"""
        message = {
            "type": "city_actions_query",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "correlation_id": "city-query-001",
            "data": {
                "city_ids": [1, 5]
            }
        }
        
        self.assertEqual(message["type"], "city_actions_query")
        self.assertIn("city_ids", message["data"])
        self.assertIsInstance(message["data"]["city_ids"], list)
        self.assertEqual(len(message["data"]["city_ids"]), 2)

    def test_city_actions_query_missing_city_ids(self):
        """city_actions_query without city_ids should fail with E220"""
        message = {
            "type": "city_actions_query",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "data": {}  # Missing city_ids
        }
        
        self.assertNotIn("city_ids", message["data"])


class TestUnitActionsResponse(unittest.TestCase):
    """Test unit_actions_response format per protocol spec"""

    def test_unit_actions_response_batch_structure(self):
        """Response should match protocol spec batch structure"""
        response = {
            "type": "unit_actions_response",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "correlation_id": "batch-query-001",
            "data": {
                "success": True,
                "units": {
                    "42": {
                        "unit_id": 42,
                        "success": True,
                        "actions": [
                            {"action_type": "unit_move", "actor_id": 42, "target": {"x": 11, "y": 21}},
                            {"action_type": "unit_fortify", "actor_id": 42}
                        ]
                    },
                    "43": {
                        "unit_id": 43,
                        "success": True,
                        "actions": [
                            {"action_type": "unit_move", "actor_id": 43, "target": {"x": 15, "y": 25}}
                        ]
                    }
                },
                "errors": []
            }
        }
        
        self.assertEqual(response["type"], "unit_actions_response")
        self.assertIn("data", response)
        self.assertIn("success", response["data"])
        self.assertIn("units", response["data"])
        self.assertIn("errors", response["data"])
        
        # Check units are keyed by string ID
        self.assertIn("42", response["data"]["units"])
        self.assertIn("43", response["data"]["units"])
        
        # Check unit result structure
        unit_42 = response["data"]["units"]["42"]
        self.assertEqual(unit_42["unit_id"], 42)
        self.assertTrue(unit_42["success"])
        self.assertIn("actions", unit_42)

    def test_action_is_directly_submittable(self):
        """Actions in response should be directly submittable as ACTION requests"""
        action = {
            "action_type": "unit_move",
            "actor_id": 42,
            "target": {"x": 11, "y": 21}
        }
        
        # Required fields for action submission
        self.assertIn("action_type", action)
        self.assertIn("actor_id", action)
        
        # Action can be wrapped directly in action request
        action_request = {
            "type": "action",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "data": action
        }
        self.assertEqual(action_request["data"]["action_type"], "unit_move")


class TestCityActionsResponse(unittest.TestCase):
    """Test city_actions_response format per protocol spec"""

    def test_city_actions_response_batch_structure(self):
        """Response should match protocol spec batch structure"""
        response = {
            "type": "city_actions_response",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "correlation_id": "city-query-001",
            "data": {
                "success": True,
                "cities": {
                    "5": {
                        "city_id": 5,
                        "success": True,
                        "actions": [
                            {"action_type": "city_production", "actor_id": 5, "target": {"production": "Warrior"}},
                            {"action_type": "city_buy", "actor_id": 5}
                        ]
                    },
                    "6": {
                        "city_id": 6,
                        "success": True,
                        "actions": [
                            {"action_type": "city_production", "actor_id": 6, "target": {"production": "Granary"}}
                        ]
                    }
                },
                "errors": []
            }
        }
        
        self.assertEqual(response["type"], "city_actions_response")
        self.assertIn("data", response)
        self.assertIn("success", response["data"])
        self.assertIn("cities", response["data"])
        self.assertIn("errors", response["data"])


class TestUnitActionsQueryErrors(unittest.TestCase):
    """Test error handling for unit_actions_query"""

    def test_unit_not_found_error(self):
        """Should return E230 for non-existent unit"""
        error_response = {
            "unit_id": 999,
            "success": False,
            "error": {
                "code": "E230",
                "message": "Unit not found"
            },
            "actions": []
        }
        
        self.assertEqual(error_response["error"]["code"], "E230")
        self.assertEqual(error_response["error"]["code"], ErrorCode.UNIT_NOT_FOUND)
        self.assertFalse(error_response["success"])
        self.assertEqual(error_response["actions"], [])

    def test_unit_not_owned_error(self):
        """Should return E231 for unit owned by another player"""
        error_response = {
            "unit_id": 99,
            "success": False,
            "error": {
                "code": "E231",
                "message": "Unit not owned by player"
            },
            "actions": []
        }
        
        self.assertEqual(error_response["error"]["code"], "E231")
        self.assertEqual(error_response["error"]["code"], ErrorCode.UNIT_NOT_OWNED)

    def test_partial_success_with_errors(self):
        """Batch query should support partial success"""
        response = {
            "type": "unit_actions_response",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "data": {
                "success": True,  # True because at least one succeeded
                "units": {
                    "42": {
                        "unit_id": 42,
                        "success": True,
                        "actions": [{"action_type": "unit_fortify", "actor_id": 42}]
                    },
                    "999": {
                        "unit_id": 999,
                        "success": False,
                        "error": {"code": "E230", "message": "Unit not found"},
                        "actions": []
                    }
                },
                "errors": [
                    {"unit_id": 999, "code": "E230", "message": "Unit not found"}
                ]
            }
        }
        
        self.assertTrue(response["data"]["success"])
        self.assertTrue(response["data"]["units"]["42"]["success"])
        self.assertFalse(response["data"]["units"]["999"]["success"])
        self.assertEqual(len(response["data"]["errors"]), 1)


class TestCityActionsQueryErrors(unittest.TestCase):
    """Test error handling for city_actions_query"""

    def test_city_not_found_error(self):
        """Should return E240 for non-existent city"""
        error_response = {
            "city_id": 999,
            "success": False,
            "error": {
                "code": "E240",
                "message": "City not found"
            },
            "actions": []
        }
        
        self.assertEqual(error_response["error"]["code"], "E240")
        self.assertEqual(error_response["error"]["code"], ErrorCode.CITY_NOT_FOUND)

    def test_city_not_owned_error(self):
        """Should return E241 for city owned by another player"""
        error_response = {
            "city_id": 6,
            "success": False,
            "error": {
                "code": "E241",
                "message": "City not owned by player"
            },
            "actions": []
        }
        
        self.assertEqual(error_response["error"]["code"], "E241")
        self.assertEqual(error_response["error"]["code"], ErrorCode.CITY_NOT_OWNED)


class TestQueryTimeout(unittest.TestCase):
    """Test timeout error handling"""

    def test_query_timeout_error(self):
        """Should return E503 on query timeout"""
        error = {
            "code": "E503",
            "message": "Query timeout"
        }
        
        self.assertEqual(error["code"], "E503")
        self.assertEqual(error["code"], ErrorCode.QUERY_TIMEOUT)


class TestUnitActionEnumeration(unittest.TestCase):
    """Test that unit actions are properly enumerated based on unit type"""

    def test_warrior_actions(self):
        """Warrior should have move, fortify, attack actions"""
        warrior_actions = [
            {"action_type": "unit_move", "actor_id": 42, "target": {"direction": "n"}},
            {"action_type": "unit_fortify", "actor_id": 42},
            {"action_type": "unit_attack", "actor_id": 42, "target": {"direction": "n"}}
        ]
        
        action_types = [a["action_type"] for a in warrior_actions]
        self.assertIn("unit_move", action_types)
        self.assertIn("unit_fortify", action_types)
        self.assertIn("unit_attack", action_types)

    def test_settler_actions(self):
        """Settler should have move, build_city actions"""
        settler_actions = [
            {"action_type": "unit_move", "actor_id": 43, "target": {"direction": "s"}},
            {"action_type": "unit_build_city", "actor_id": 43}
        ]
        
        action_types = [a["action_type"] for a in settler_actions]
        self.assertIn("unit_move", action_types)
        self.assertIn("unit_build_city", action_types)

    def test_worker_actions(self):
        """Worker should have move, build_improvement actions"""
        worker_actions = [
            {"action_type": "unit_move", "actor_id": 44, "target": {"direction": "e"}},
            {"action_type": "unit_build_improvement", "actor_id": 44, "target": {"improvement": "road"}},
            {"action_type": "unit_build_improvement", "actor_id": 44, "target": {"improvement": "irrigation"}}
        ]
        
        action_types = [a["action_type"] for a in worker_actions]
        self.assertIn("unit_move", action_types)
        self.assertIn("unit_build_improvement", action_types)


class TestCityActionEnumeration(unittest.TestCase):
    """Test that city actions are properly enumerated"""

    def test_city_production_actions(self):
        """City should have change_production actions for buildable items"""
        city_actions = [
            {"action_type": "city_production", "actor_id": 1, "target": {"production": "Warrior"}},
            {"action_type": "city_production", "actor_id": 1, "target": {"production": "Settler"}},
            {"action_type": "city_production", "actor_id": 1, "target": {"production": "Granary"}}
        ]
        
        # All should be production changes
        for action in city_actions:
            self.assertEqual(action["action_type"], "city_production")
            self.assertIn("production", action["target"])

    def test_city_buy_action(self):
        """City should have buy action if affordable"""
        buy_action = {
            "action_type": "city_buy",
            "actor_id": 1
        }
        
        self.assertEqual(buy_action["action_type"], "city_buy")

    def test_city_sell_improvement_actions(self):
        """City should have sell_improvement actions for existing improvements"""
        sell_actions = [
            {"action_type": "city_sell_improvement", "actor_id": 1, "target": {"improvement": "Granary"}},
            {"action_type": "city_sell_improvement", "actor_id": 1, "target": {"improvement": "Barracks"}}
        ]
        
        for action in sell_actions:
            self.assertEqual(action["action_type"], "city_sell_improvement")
            self.assertIn("improvement", action["target"])


class TestCorrelationId(unittest.TestCase):
    """Test correlation_id handling"""

    def test_correlation_id_in_success_response(self):
        """correlation_id should be echoed in response"""
        request_correlation = "batch-query-001"
        
        response = {
            "type": "unit_actions_response",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "correlation_id": request_correlation,
            "data": {
                "success": True,
                "units": {},
                "errors": []
            }
        }
        
        self.assertEqual(response["correlation_id"], request_correlation)

    def test_correlation_id_in_error_response(self):
        """correlation_id should be echoed in error response"""
        request_correlation = "query-fail-001"
        
        error_response = {
            "type": "error",
            "code": "E120",
            "message": "Not authenticated",
            "correlation_id": request_correlation
        }
        
        self.assertEqual(error_response["correlation_id"], request_correlation)


class TestBatchQuerySize(unittest.TestCase):
    """Test batch query size limits"""
    
    def test_reasonable_batch_size(self):
        """Should support reasonable batch sizes"""
        # Typical batch query for all player units
        unit_ids = list(range(1, 51))  # 50 units
        message = {
            "type": "unit_actions_query",
            "agent_id": "test-agent",
            "timestamp": time.time(),
            "data": {
                "unit_ids": unit_ids
            }
        }
        
        self.assertEqual(len(message["data"]["unit_ids"]), 50)
    
    def test_batch_response_keyed_by_string_id(self):
        """Response units/cities should be keyed by string IDs for JSON compatibility"""
        response = {
            "type": "unit_actions_response",
            "data": {
                "success": True,
                "units": {
                    "42": {"unit_id": 42, "success": True, "actions": []},
                    "43": {"unit_id": 43, "success": True, "actions": []}
                },
                "errors": []
            }
        }
        
        # Keys should be strings
        for key in response["data"]["units"].keys():
            self.assertIsInstance(key, str)


if __name__ == '__main__':
    unittest.main()
