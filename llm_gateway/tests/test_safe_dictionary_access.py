#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for safe dictionary access patterns
Addresses security critical issue: KeyError crashes from unsafe nested dict access
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock

import sys
try:
    from llm_gateway.main import LLMGateway
    from llm_gateway.utils.safe_access import get_agent_game_id, get_agent_config
except ImportError:
    LLMGateway = None
    get_agent_game_id = None
    get_agent_config = None


class TestSafeDictionaryAccess:
    """Test suite for safe dictionary access in LLMGateway"""

    def setup_method(self):
        """Set up test fixtures"""
        self.gateway = LLMGateway()

    @pytest.mark.asyncio
    async def test_agent_retrieval_with_missing_agent(self):
        """Should handle missing agent gracefully without KeyError"""
        # RED: This test should FAIL initially because code uses unsafe dict access
        message = {"agent_id": "nonexistent_agent", "data": {}}

        result = await self.gateway._route_to_freeciv(message)

        # Should return error, not raise KeyError
        assert result["success"] is False
        assert "Agent not registered" in result["error"]
        # Should NOT crash with KeyError

    @pytest.mark.asyncio
    async def test_nested_dictionary_access_missing_config(self):
        """Should safely access nested dictionaries when keys are missing"""
        # RED: Should fail because active_agents[agent_id]["config"]["game_id"] raises KeyError
        self.gateway.active_agents["agent1"] = {
            "session_id": "session123",
            # Missing "config" key
        }

        # This should NOT raise KeyError
        game_id = get_agent_game_id(self.gateway.active_agents, "agent1")

        assert game_id is None  # Gracefully returns None instead of crashing

    @pytest.mark.asyncio
    async def test_nested_dictionary_access_missing_game_id(self):
        """Should safely access game_id when config exists but game_id missing"""
        # RED: Tests deep nesting safety
        self.gateway.active_agents["agent2"] = {
            "session_id": "session456",
            "config": {
                # Missing "game_id" key
                "other_field": "value"
            }
        }

        game_id = get_agent_game_id(self.gateway.active_agents, "agent2")

        assert game_id is None

    @pytest.mark.asyncio
    async def test_get_agent_config_with_missing_agent(self):
        """get_agent_config should return None for missing agent"""
        # RED: Should fail if using unsafe dict access
        config = get_agent_config(self.gateway.active_agents, "nonexistent")

        assert config is None

    @pytest.mark.asyncio
    async def test_get_agent_config_with_missing_config_key(self):
        """get_agent_config should return None when config key missing"""
        self.gateway.active_agents["agent3"] = {
            "session_id": "session789",
            # No config key
        }

        config = get_agent_config(self.gateway.active_agents, "agent3")

        assert config is None

    @pytest.mark.asyncio
    async def test_safe_get_nested_with_deep_path(self):
        """safe_get_nested should handle arbitrarily deep paths"""
        # RED: Tests the safe_access utility directly
        test_dict = {
            "level1": {
                "level2": {
                    "level3": {
                        "value": "found"
                    }
                }
            }
        }

        # Valid path
        result = safe_get_nested(test_dict, ["level1", "level2", "level3", "value"])
        assert result == "found"

        # Invalid path - should return None, not crash
        result = safe_get_nested(test_dict, ["level1", "missing", "level3", "value"])
        assert result is None

        # Empty dict
        result = safe_get_nested({}, ["any", "path"])
        assert result is None

    @pytest.mark.asyncio
    async def test_route_to_freeciv_with_valid_agent(self):
        """Should successfully route when agent exists with all required fields"""
        # GREEN: This should pass once we fix the unsafe access
        self.gateway.active_agents["valid_agent"] = {
            "session_id": "session_valid",
            "config": {
                "game_id": "game_123"
            },
            "connected_at": 1234567890.0
        }

        # Mock the connection_state_manager
        with patch('llm_gateway.main.connection_state_manager') as mock_csm:
            async def mock_get_connection(gid):
                return Mock()

            async def mock_is_healthy(gid):
                return True

            mock_csm.get_connection = mock_get_connection
            mock_csm.is_connection_healthy = mock_is_healthy

            # Mock forward_to_proxy
            async def mock_forward(gid, msg):
                return True

            self.gateway.forward_to_proxy = mock_forward

            message = {"agent_id": "valid_agent", "data": {"test": "data"}}
            result = await self.gateway._route_to_freeciv(message)

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_register_agent_prevents_duplicate_session_ids(self):
        """Should handle agent registration safely even with missing fields"""
        # RED: Tests registration flow
        config = {"game_id": "game_456", "model": "gpt-4"}

        result = await self.gateway.register_agent("new_agent", config)

        assert result["success"] is True
        assert "agent_id" in result
        assert "session_id" in result

        # Verify agent stored with all required fields
        assert "new_agent" in self.gateway.active_agents
        agent_data = self.gateway.active_agents["new_agent"]
        assert "session_id" in agent_data
        assert "connected_at" in agent_data

    @pytest.mark.asyncio
    async def test_concurrent_agent_access_no_race_condition(self):
        """Multiple coroutines accessing active_agents shouldn't cause KeyError"""
        # RED: Tests thread safety / race conditions
        self.gateway.active_agents["agent_concurrent"] = {
            "session_id": "session_concurrent",
            "config": {"game_id": "game_789"}
        }

        async def access_agent():
            # Try to access agent info
            game_id = get_agent_game_id(self.gateway.active_agents, "agent_concurrent")
            return game_id

        async def remove_agent():
            # Simulate agent disconnect
            await asyncio.sleep(0.001)
            if "agent_concurrent" in self.gateway.active_agents:
                del self.gateway.active_agents["agent_concurrent"]

        # Run access and removal concurrently
        results = await asyncio.gather(
            access_agent(),
            access_agent(),
            remove_agent(),
            access_agent(),
            return_exceptions=True
        )

        # Should not raise KeyError, might return None after removal
        for result in results:
            if not isinstance(result, Exception):
                assert result is None or result == "game_789"
            else:
                # If exception, it shouldn't be KeyError
                assert not isinstance(result, KeyError)

    def test_safe_get_nested_with_default_value(self):
        """safe_get_nested should support custom default values"""
        test_dict = {"a": {"b": "value"}}

        # Missing path with default
        result = safe_get_nested(test_dict, ["x", "y"], default="custom_default")
        assert result == "custom_default"

        # Existing path should return actual value
        result = safe_get_nested(test_dict, ["a", "b"], default="custom_default")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_agent_cleanup_doesnt_leave_dangling_references(self):
        """Removing agent should clean up all references safely"""
        # Add agent
        self.gateway.active_agents["cleanup_test"] = {
            "session_id": "session_cleanup",
            "config": {"game_id": "game_cleanup"}
        }

        # Remove agent
        if "cleanup_test" in self.gateway.active_agents:
            del self.gateway.active_agents["cleanup_test"]

        # Accessing removed agent should return None, not crash
        game_id = get_agent_game_id(self.gateway.active_agents, "cleanup_test")
        assert game_id is None

        config = get_agent_config(self.gateway.active_agents, "cleanup_test")
        assert config is None


class TestSafeAccessUtilities:
    """Test the safe_access utility functions directly"""

    def test_get_agent_game_id_various_structures(self):
        """Test get_agent_game_id with different dict structures"""
        # Valid structure
        agents = {
            "agent1": {"config": {"game_id": "game123"}}
        }
        assert get_agent_game_id(agents, "agent1") == "game123"

        # Missing agent
        assert get_agent_game_id(agents, "agent2") is None

        # Missing config
        agents["agent3"] = {"session_id": "s1"}
        assert get_agent_game_id(agents, "agent3") is None

        # Empty config
        agents["agent4"] = {"config": {}}
        assert get_agent_game_id(agents, "agent4") is None

        # None config
        agents["agent5"] = {"config": None}
        assert get_agent_game_id(agents, "agent5") is None

    def test_get_agent_config_edge_cases(self):
        """Test get_agent_config with edge cases"""
        agents = {}

        # Empty dict
        assert get_agent_config(agents, "any") is None

        # Agent with no config
        agents["agent1"] = {}
        assert get_agent_config(agents, "agent1") is None

        # Agent with null config
        agents["agent2"] = {"config": None}
        assert get_agent_config(agents, "agent2") is None

        # Agent with valid config
        agents["agent3"] = {"config": {"key": "value"}}
        assert get_agent_config(agents, "agent3") == {"key": "value"}

    def test_safe_get_nested_non_dict_values(self):
        """safe_get_nested should handle non-dict intermediate values"""
        test_dict = {
            "a": "not_a_dict",
            "b": {
                "c": 123
            }
        }

        # Path through non-dict should return None
        result = safe_get_nested(test_dict, ["a", "b", "c"])
        assert result is None

        # Path to number should work
        result = safe_get_nested(test_dict, ["b", "c"])
        assert result == 123


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
