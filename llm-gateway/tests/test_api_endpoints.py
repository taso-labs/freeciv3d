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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
