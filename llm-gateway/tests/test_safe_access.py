#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for safe_access utilities - Defensive programming to prevent KeyError crashes
"""

import pytest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils.safe_access import (
    safe_get_nested, safe_get_list_item, safe_get_attribute,
    validate_dict_structure, safe_update_nested, SafeDict,
    get_agent_game_id, get_agent_config
)


class TestSafeAccess:
    """Test safe access utilities"""

    def test_safe_get_nested_success(self):
        """Test successful nested dictionary access"""
        data = {
            "agents": {
                "agent1": {
                    "config": {
                        "game_id": "game123",
                        "model": "gpt-4"
                    }
                }
            }
        }

        result = safe_get_nested(data, "agents", "agent1", "config", "game_id")
        assert result == "game123"

    def test_safe_get_nested_missing_key(self):
        """Test nested access with missing key"""
        data = {
            "agents": {
                "agent1": {
                    "config": {}
                }
            }
        }

        result = safe_get_nested(data, "agents", "agent1", "config", "missing_key")
        assert result is None

        result = safe_get_nested(data, "agents", "agent1", "config", "missing_key", default="default_value")
        assert result == "default_value"

    def test_safe_get_nested_non_dict_intermediate(self):
        """Test nested access when intermediate value is not a dict"""
        data = {
            "agents": {
                "agent1": "not_a_dict"
            }
        }

        result = safe_get_nested(data, "agents", "agent1", "config", "game_id")
        assert result is None

    def test_safe_get_nested_required_success(self):
        """Test required nested access that succeeds"""
        data = {
            "agents": {
                "agent1": {
                    "config": {
                        "game_id": "game123"
                    }
                }
            }
        }

        result = safe_get_nested(data, "agents", "agent1", "config", "game_id", required=True)
        assert result == "game123"

    def test_safe_get_nested_required_failure(self):
        """Test required nested access that fails"""
        data = {
            "agents": {
                "agent1": {}
            }
        }

        with pytest.raises(ValueError, match="Required key path not found"):
            safe_get_nested(data, "agents", "agent1", "config", "game_id", required=True)

    def test_safe_get_list_item_success(self):
        """Test successful list item access"""
        data = ["first", "second", "third"]

        result = safe_get_list_item(data, 1)
        assert result == "second"

    def test_safe_get_list_item_out_of_range(self):
        """Test list access with out of range index"""
        data = ["first", "second"]

        result = safe_get_list_item(data, 5)
        assert result is None

        result = safe_get_list_item(data, 5, default="default")
        assert result == "default"

    def test_safe_get_list_item_negative_index(self):
        """Test list access with negative index"""
        data = ["first", "second"]

        result = safe_get_list_item(data, -1)
        assert result is None

    def test_safe_get_list_item_not_list(self):
        """Test list access on non-list"""
        data = "not_a_list"

        result = safe_get_list_item(data, 0)
        assert result is None

    def test_safe_get_attribute_success(self):
        """Test successful attribute access"""
        class TestObj:
            test_attr = "test_value"

        obj = TestObj()
        result = safe_get_attribute(obj, "test_attr")
        assert result == "test_value"

    def test_safe_get_attribute_missing(self):
        """Test attribute access with missing attribute"""
        class TestObj:
            pass

        obj = TestObj()
        result = safe_get_attribute(obj, "missing_attr")
        assert result is None

        result = safe_get_attribute(obj, "missing_attr", default="default")
        assert result == "default"

    def test_validate_dict_structure_success(self):
        """Test successful dict structure validation"""
        data = {
            "api_token": "test_token",
            "model": "gpt-4",
            "game_id": "game123"
        }

        schema = {
            "api_token": {"type": str, "required": True},
            "model": {"type": str, "required": True},
            "game_id": {"type": str, "required": True}
        }

        result = validate_dict_structure(data, schema)
        assert len(result["errors"]) == 0

    def test_validate_dict_structure_missing_required(self):
        """Test dict validation with missing required field"""
        data = {
            "api_token": "test_token",
            "model": "gpt-4"
        }

        schema = {
            "api_token": {"type": str, "required": True},
            "model": {"type": str, "required": True},
            "game_id": {"type": str, "required": True}
        }

        result = validate_dict_structure(data, schema)
        assert len(result["errors"]) == 1
        assert "game_id" in result["errors"][0]

    def test_validate_dict_structure_type_mismatch(self):
        """Test dict validation with type mismatch"""
        data = {
            "api_token": "test_token",
            "model": "gpt-4",
            "game_id": 123  # Should be string
        }

        schema = {
            "api_token": {"type": str, "required": True},
            "model": {"type": str, "required": True},
            "game_id": {"type": str, "required": True}
        }

        result = validate_dict_structure(data, schema)
        assert len(result["errors"]) == 1
        assert "Type mismatch" in result["errors"][0]

    def test_safe_update_nested_success(self):
        """Test successful nested update"""
        data = {}

        success = safe_update_nested(data, "test_value", "agents", "agent1", "config", "game_id")
        assert success is True
        assert data["agents"]["agent1"]["config"]["game_id"] == "test_value"

    def test_safe_update_nested_existing_path(self):
        """Test nested update on existing path"""
        data = {
            "agents": {
                "agent1": {
                    "config": {
                        "game_id": "old_value"
                    }
                }
            }
        }

        success = safe_update_nested(data, "new_value", "agents", "agent1", "config", "game_id")
        assert success is True
        assert data["agents"]["agent1"]["config"]["game_id"] == "new_value"

    def test_safe_dict_wrapper(self):
        """Test SafeDict wrapper class"""
        data = {
            "agents": {
                "agent1": {
                    "config": {
                        "game_id": "game123"
                    }
                }
            }
        }

        safe_dict = SafeDict(data)

        # Test nested access
        result = safe_dict.get_nested("agents", "agent1", "config", "game_id")
        assert result == "game123"

        # Test path checking
        assert safe_dict.has_path("agents", "agent1", "config", "game_id") is True
        assert safe_dict.has_path("agents", "agent1", "config", "missing") is False

        # Test nested setting
        success = safe_dict.set_nested("new_value", "agents", "agent1", "config", "new_key")
        assert success is True
        assert safe_dict.get_nested("agents", "agent1", "config", "new_key") == "new_value"

    def test_get_agent_game_id_success(self):
        """Test getting agent game_id successfully"""
        active_agents = {
            "agent1": {
                "config": {
                    "game_id": "game123"
                }
            }
        }

        result = get_agent_game_id(active_agents, "agent1")
        assert result == "game123"

    def test_get_agent_game_id_missing_agent(self):
        """Test getting game_id for missing agent"""
        active_agents = {}

        result = get_agent_game_id(active_agents, "missing_agent")
        assert result is None

    def test_get_agent_game_id_missing_config(self):
        """Test getting game_id when config is missing"""
        active_agents = {
            "agent1": {}
        }

        result = get_agent_game_id(active_agents, "agent1")
        assert result is None

    def test_get_agent_config_success(self):
        """Test getting agent config successfully"""
        active_agents = {
            "agent1": {
                "config": {
                    "game_id": "game123",
                    "model": "gpt-4"
                }
            }
        }

        result = get_agent_config(active_agents, "agent1")
        assert result["game_id"] == "game123"
        assert result["model"] == "gpt-4"

    def test_get_agent_config_missing_agent(self):
        """Test getting config for missing agent"""
        active_agents = {}

        result = get_agent_config(active_agents, "missing_agent")
        assert result == {}

    def test_create_agent_accessor(self):
        """Test creating agent accessor function"""
        from utils.safe_access import create_agent_accessor

        active_agents = {
            "agent1": {
                "config": {
                    "game_id": "game123"
                }
            }
        }

        get_agent_data = create_agent_accessor(active_agents)
        agent_data = get_agent_data("agent1")

        assert isinstance(agent_data, SafeDict)
        assert agent_data.get_nested("config", "game_id") == "game123"


if __name__ == "__main__":
    pytest.main([__file__])
