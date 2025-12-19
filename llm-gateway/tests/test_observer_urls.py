#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDD tests for Observer URLs endpoint.

Tests cover:
- GET /api/games/{game_id}/observer-urls endpoint
- freeciv_web_base_url configuration setting
- URL structure and parameters

Updated to test connection_manager-based implementation (Approach B).
"""

import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from urllib.parse import urlparse, parse_qs

# Ensure we can import from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Disable API key for testing
os.environ["GATEWAY_REQUIRE_API_KEY"] = "false"
os.environ["GATEWAY_FREECIV_WEB_BASE_URL"] = "https://freeciv.agentclash.gg"

from fastapi.testclient import TestClient
from main import app


def mock_game_info(civserver_port=6001, player_id=0, agent_id="test-agent"):
    """Helper to create mock game info dict"""
    return {
        "civserver_port": civserver_port,
        "player_id": player_id,
        "agent_id": agent_id,
        "session_id": "test-session",
        "connected_at": time.time(),
    }


class TestObserverUrlsEndpoint:
    """Test GET /api/games/{game_id}/observer-urls endpoint"""

    def setup_method(self):
        """Set up test client before each test"""
        self.client = TestClient(app)

    def test_returns_404_for_nonexistent_game(self):
        """Should return 404 when game_id doesn't exist in connection_manager"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=None)

            response = self.client.get("/api/games/nonexistent-game/observer-urls")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_returns_409_when_port_not_assigned(self):
        """Should return 409 Conflict when game exists but port is None"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=None))

            response = self.client.get("/api/games/game-123/observer-urls")

        assert response.status_code == 409
        assert "port" in response.json()["detail"].lower()

    def test_returns_409_when_port_is_6000(self):
        """Should return 409 when port is 6000 (singleplayer, invalid for LLM games)"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6000))

            response = self.client.get("/api/games/game-123/observer-urls")

        assert response.status_code == 409

    def test_returns_observer_urls_for_valid_game(self):
        """Should return observer URLs when game has valid port (6001-6009)"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6001))

            response = self.client.get("/api/games/game-123/observer-urls")

        assert response.status_code == 200
        data = response.json()

        # Check response structure
        assert data["game_id"] == "game-123"
        assert data["civserver_port"] == 6001
        assert "observer_urls" in data
        assert "global" in data["observer_urls"]
        assert "player1" in data["observer_urls"]
        assert "player2" in data["observer_urls"]

    def test_global_url_has_strategic_camera(self):
        """Global observer URL should use strategic camera preset for bird's eye view"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6001))

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()
        global_url = data["observer_urls"]["global"]

        # Parse URL and check parameters
        assert "camera=strategic" in global_url
        assert "embed=1" in global_url
        assert "autojoin=1" in global_url
        assert "action=observe" in global_url

    def test_player_urls_have_fog_of_war_attachment(self):
        """Player observer URLs should include observe_player param for FOW"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6001))

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()
        player1_url = data["observer_urls"]["player1"]
        player2_url = data["observer_urls"]["player2"]

        # Player 1 should observe AI*1 (URL encoded as AI%2A1)
        assert "observe_player=AI%2A1" in player1_url
        assert "follow=AI%2A1" in player1_url

        # Player 2 should observe AI*2 (URL encoded as AI%2A2)
        assert "observe_player=AI%2A2" in player2_url
        assert "follow=AI%2A2" in player2_url

    def test_player_urls_have_cinematic_camera(self):
        """Player observer URLs should use cinematic camera preset"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6001))

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()
        player1_url = data["observer_urls"]["player1"]
        player2_url = data["observer_urls"]["player2"]

        assert "camera=cinematic" in player1_url
        assert "camera=cinematic" in player2_url

    def test_urls_use_configured_base_url(self):
        """URLs should use GATEWAY_FREECIV_WEB_BASE_URL from config"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6001))

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()

        # All URLs should start with configured base URL
        for view_type, url in data["observer_urls"].items():
            assert url.startswith("https://freeciv.agentclash.gg/webclient/"), \
                f"{view_type} URL should use configured base URL"

    def test_urls_include_civserverport_parameter(self):
        """All URLs should include civserverport parameter matching game port"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6003))

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()

        for view_type, url in data["observer_urls"].items():
            assert "civserverport=6003" in url, \
                f"{view_type} URL should include civserverport=6003"

    def test_urls_include_unique_viewer_names(self):
        """Each view URL should have a unique viewer name to avoid conflicts"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6001))

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()

        # Extract names from URLs
        names = set()
        for view_type, url in data["observer_urls"].items():
            # Parse the name= parameter
            if "name=" in url:
                start = url.index("name=") + 5
                end = url.find("&", start) if "&" in url[start:] else len(url)
                name = url[start:end]
                assert name not in names, f"Duplicate viewer name: {name}"
                names.add(name)

    def test_response_includes_civserver_port(self):
        """Response should include civserver_port for reference"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6005))

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()
        assert "civserver_port" in data
        assert data["civserver_port"] == 6005


class TestObserverUrlsConfig:
    """Test configuration for observer URLs"""

    def test_freeciv_web_base_url_setting_exists(self):
        """Config should have freeciv_web_base_url setting"""
        from config import Settings
        settings = Settings()

        # This test will fail initially because the setting doesn't exist
        assert hasattr(settings, 'freeciv_web_base_url'), \
            "Settings should have freeciv_web_base_url attribute"

    def test_freeciv_web_base_url_reads_from_env(self):
        """Setting should read from GATEWAY_FREECIV_WEB_BASE_URL env var"""
        # Set environment variable
        os.environ["GATEWAY_FREECIV_WEB_BASE_URL"] = "https://custom.example.com"

        # Re-import to get fresh settings
        from importlib import reload
        import config
        reload(config)

        settings = config.Settings()
        assert settings.freeciv_web_base_url == "https://custom.example.com"

        # Restore original value
        os.environ["GATEWAY_FREECIV_WEB_BASE_URL"] = "https://freeciv.agentclash.gg"

    def test_freeciv_web_base_url_has_default(self):
        """Setting should have a default value when env var not set"""
        # Temporarily remove env var
        original = os.environ.pop("GATEWAY_FREECIV_WEB_BASE_URL", None)

        try:
            from importlib import reload
            import config
            reload(config)

            settings = config.Settings()
            # Default should be localhost
            assert settings.freeciv_web_base_url == "http://localhost:8080"
        finally:
            # Restore env var
            if original:
                os.environ["GATEWAY_FREECIV_WEB_BASE_URL"] = original


class TestObserverUrlsEdgeCases:
    """Test edge cases for observer URLs endpoint"""

    def setup_method(self):
        self.client = TestClient(app)

    def test_handles_different_port_numbers(self):
        """Should work with any valid multiplayer port (6001-6009)"""
        for port in [6001, 6002, 6005, 6009]:
            with patch("api_endpoints.connection_manager") as mock_cm:
                mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=port))

                response = self.client.get("/api/games/test-game/observer-urls")

            assert response.status_code == 200
            assert f"civserverport={port}" in response.json()["observer_urls"]["global"]

    def test_special_characters_in_game_id(self):
        """Should handle game IDs with special characters"""
        game_id = "game-with-dashes_and_underscores"

        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6001))

            response = self.client.get(f"/api/games/{game_id}/observer-urls")

        assert response.status_code == 200
        assert response.json()["game_id"] == game_id
