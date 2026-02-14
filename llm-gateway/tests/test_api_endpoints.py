#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Simple tests for LLM API Gateway REST API endpoints
"""

import pytest
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# Import the modules we're testing
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import the app directly from main
from main import app

# Set environment to disable API key requirement for testing
os.environ["GATEWAY_REQUIRE_API_KEY"] = "false"
import api_endpoints
api_endpoints.settings.require_api_key = False


class TestBasicFunctionality:
    """Test basic API functionality"""

    def test_health_check(self):
        """Test health check endpoint"""
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "active_games" in data
        assert "active_agents" in data
        assert "proxy_connections" in data

    def test_game_creation_success(self):
        """Test successful game creation"""
        client = TestClient(app)

        game_config = {
            "ruleset": "classic",
            "map_size": "small",
            "max_players": 4,
            "ai_level": "easy",
        }

        with patch("main.gateway.create_game") as mock_create:
            mock_create.return_value = {
                "success": True,
                "game_id": "game-123",
                "connection_details": {
                    "ws_url": "ws://localhost:8002/llmsocket/8002",
                    "game_port": 6001,
                },
            }

            response = client.post("/api/game/create", json=game_config)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["game_id"] == "game-123"

    def test_game_state_success(self):
        """Test successful game state retrieval"""
        client = TestClient(app)

        with patch("main.gateway.get_game_state") as mock_get_state:
            mock_get_state.return_value = {
                "success": True,
                "format": "llm_optimized",
                "data": {
                    "turn": 1,
                    "phase": "movement",
                    "strategic_summary": {
                        "cities_count": 1,
                        "units_count": 2,
                        "tech_progress": "early",
                    },
                },
            }

            response = client.get(
                "/api/game/game-123/state?player_id=1&format=llm_optimized"
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["format"] == "llm_optimized"

    def test_action_submission_success(self):
        """Test successful action submission"""
        client = TestClient(app)

        action = {
            "action_type": "unit_move",
            "actor_id": 42,
            "target": {"x": 11, "y": 21},
            "player_id": 1,
        }

        with patch("main.gateway.submit_action") as mock_submit:
            mock_submit.return_value = {
                "success": True,
                "action_id": "action-456",
                "result": "Action executed successfully",
            }

            response = client.post("/api/game/game-123/action", json=action)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["action_id"] == "action-456"

    def test_stop_game_success(self):
        """Test successful game stop via admin API"""
        client = TestClient(app)

        stop_request = {
            "reason": "admin_stop",
            "message": "Match stopped by administrator"
        }

        # Mock the gateway's game_sessions and end_game
        with patch("api_endpoints.get_gateway") as mock_get_gateway, \
             patch("api_endpoints.connection_manager.get_players_for_game") as mock_get_players, \
             patch("api_endpoints.settings") as mock_settings:

            mock_settings.require_api_key = False

            mock_gw = MagicMock()
            mock_gw.game_sessions = {
                "game-123": {
                    "status": "active",
                    "created_at": 1704067200.0,
                    "current_turn": 42,
                    "last_state": {
                        "cities": {"1": {"id": 1, "owner": 0}},
                        "units": {"10": {"id": 10, "owner": 0}, "11": {"id": 11, "owner": 0}},
                        "players": {"0": {"id": 0, "gold": 500}}
                    }
                }
            }
            mock_gw.end_game = AsyncMock()
            mock_get_gateway.return_value = mock_gw

            mock_get_players.return_value = [
                {"player_id": 0, "agent_id": "llm_gemini"}
            ]

            response = client.post("/api/games/game-123/stop", json=stop_request)

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "game_ended"
        assert data["game_id"] == "game-123"
        assert data["data"]["success"] is True
        assert data["data"]["final_turn"] == 42
        assert data["data"]["end_reason"] == "admin_stop"
        assert len(data["data"]["players"]) == 1
        assert data["data"]["players"][0]["agent_id"] == "llm_gemini"
        assert data["data"]["players"][0]["cities"] == 1
        assert data["data"]["players"][0]["units"] == 2

    def test_stop_game_not_found(self):
        """Test stop game when game doesn't exist"""
        client = TestClient(app)

        with patch("api_endpoints.get_gateway") as mock_get_gateway, \
             patch("api_endpoints.settings") as mock_settings:

            mock_settings.require_api_key = False
            mock_gw = MagicMock()
            mock_gw.game_sessions = {}  # No games
            mock_get_gateway.return_value = mock_gw

            response = client.post(
                "/api/games/nonexistent/stop",
                json={"reason": "admin_stop"}
            )

        assert response.status_code == 200  # Returns 200 with error in body
        data = response.json()
        assert data["type"] == "error"
        assert data["data"]["code"] == "E010"

    def test_stop_game_already_ended(self):
        """Test stop game when game already ended"""
        client = TestClient(app)

        with patch("api_endpoints.get_gateway") as mock_get_gateway, \
             patch("api_endpoints.settings") as mock_settings:

            mock_settings.require_api_key = False
            mock_gw = MagicMock()
            mock_gw.game_sessions = {
                "game-123": {"status": "ended"}
            }
            mock_get_gateway.return_value = mock_gw

            response = client.post(
                "/api/games/game-123/stop",
                json={"reason": "admin_stop"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "error"
        assert data["data"]["code"] == "E011"

    def test_stop_game_unauthorized_when_api_key_required(self):
        """Stop API should return 401 when auth is required and header is missing."""
        client = TestClient(app)

        with patch("api_endpoints.settings") as mock_settings:
            mock_settings.require_api_key = True

            response = client.post(
                "/api/games/game-123/stop",
                json={"reason": "admin_stop"}
            )

        assert response.status_code == 401
        assert response.json()["detail"] == "Authorization header required"

    def test_stop_game_authorized_calls_proxy_terminate(self):
        """Authorized stop should return 200 and invoke proxy terminate path."""
        client = TestClient(app)

        stop_request = {
            "reason": "admin_stop",
            "message": "Match stopped by administrator"
        }

        with patch("api_endpoints.get_gateway") as mock_get_gateway, \
             patch("api_endpoints.connection_manager.get_players_for_game") as mock_get_players, \
             patch("api_endpoints._call_proxy_terminate", new_callable=AsyncMock) as mock_terminate, \
             patch("api_endpoints.settings") as mock_settings:

            mock_settings.require_api_key = True

            mock_gw = MagicMock()
            mock_gw.game_sessions = {
                "game-123": {
                    "status": "active",
                    "created_at": 1704067200.0,
                    "current_turn": 42,
                    "last_state": {
                        "cities": {"1": {"id": 1, "owner": 0}},
                        "units": {"10": {"id": 10, "owner": 0}},
                        "players": {"0": {"id": 0, "gold": 500}}
                    }
                }
            }
            mock_gw.end_game = AsyncMock()
            mock_get_gateway.return_value = mock_gw

            mock_get_players.return_value = [{"player_id": 0, "agent_id": "llm_gemini"}]
            mock_terminate.return_value = {"terminated": True, "mode": "hard"}

            response = client.post(
                "/api/games/game-123/stop",
                json=stop_request,
                headers={"Authorization": "Bearer valid-test-token-12345"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "game_ended"
        assert data["game_id"] == "game-123"
        mock_terminate.assert_awaited_once()
        assert mock_terminate.await_args.args[0] == "game-123"
        assert mock_terminate.await_args.args[1] == "hard"


class TestGlobalStateEndpoint:
    """Test global state REST endpoint"""

    def test_global_state_success(self):
        """Test successful global state retrieval"""
        client = TestClient(app)

        with patch("api_endpoints.gateway") as mock_gw:
            mock_gw.get_global_game_state = AsyncMock(return_value={
                "success": True,
                "data": {
                    "turn": 5,
                    "phase": "movement",
                    "units": {"10": {"id": 10, "owner": 0, "type": "Warriors"}},
                    "cities": {"1": {"id": 1, "owner": 0, "name": "Berlin"}},
                    "players": {"0": {"id": 0, "gold": 100}},
                },
                "timestamp": 1700000000.0,
            })

            response = client.get("/api/game/game-123/global-state")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["turn"] == 5
        assert "10" in data["data"]["units"]
        assert "1" in data["data"]["cities"]
        mock_gw.get_global_game_state.assert_called_once_with("game-123")

    def test_global_state_game_not_found(self):
        """Test global state when game doesn't exist"""
        client = TestClient(app)

        with patch("api_endpoints.gateway") as mock_gw:
            mock_gw.get_global_game_state = AsyncMock(return_value={
                "success": False,
                "error": "Game not found: nonexistent",
            })

            response = client.get("/api/game/nonexistent/global-state")

        assert response.status_code == 404

    def test_global_state_server_error(self):
        """Test global state when gateway returns non-404 error"""
        client = TestClient(app)

        with patch("api_endpoints.gateway") as mock_gw:
            mock_gw.get_global_game_state = AsyncMock(return_value={
                "success": False,
                "error": "CivCom connection lost",
            })

            response = client.get("/api/game/game-123/global-state")

        assert response.status_code == 500

    def test_global_state_gateway_not_initialized(self):
        """Test global state when gateway is None"""
        client = TestClient(app)

        with patch("api_endpoints.gateway", None):
            response = client.get("/api/game/game-123/global-state")

        assert response.status_code == 500


class TestGlobalStateResponseHandler:
    """Test _handle_freeciv_message processing of global_state_response messages"""

    def _create_gateway(self):
        """Create a minimal LLMGateway instance with streaming disabled."""
        with patch("main.settings") as mock_settings, \
             patch("main.create_stream_manager", return_value=None):
            mock_settings.streaming_enabled = False
            from main import LLMGateway
            return LLMGateway()

    @pytest.mark.asyncio
    async def test_global_state_response_resolves_correlation_id(self):
        """Verify that a global_state_response with correlation_id resolves the pending request"""
        gw = self._create_gateway()

        message = {
            "type": "global_state_response",
            "correlation_id": "corr-abc-123",
            "data": {
                "turn": 10,
                "players": {"0": {"id": 0, "gold": 250}},
                "units": {"5": {"id": 5, "owner": 0}},
                "cities": {"2": {"id": 2, "owner": 0, "name": "TestCity"}},
            },
            "timestamp": 1700000000.0,
        }

        with patch("main.request_manager") as mock_rm:
            mock_rm.resolve_request = AsyncMock(return_value=True)

            await gw._handle_freeciv_message("game-test-1", message)

            mock_rm.resolve_request.assert_called_once_with(
                "corr-abc-123",
                {
                    "type": "global_state_response",
                    "success": True,
                    "data": message["data"],
                    "timestamp": 1700000000.0,
                },
            )

    @pytest.mark.asyncio
    async def test_global_state_response_without_correlation_id(self):
        """Verify that a global_state_response without correlation_id does not call resolve_request"""
        gw = self._create_gateway()

        message = {
            "type": "global_state_response",
            "data": {"turn": 3},
            "timestamp": 1700000001.0,
        }

        with patch("main.request_manager") as mock_rm:
            mock_rm.resolve_request = AsyncMock()

            await gw._handle_freeciv_message("game-test-2", message)

            mock_rm.resolve_request.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
