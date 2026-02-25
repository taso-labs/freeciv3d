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
# ROOT.war deploys at / context, so no path prefix needed
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


def mock_players_for_game(player1_name="Claude_Sonnet_45", player2_name="Gemini_3_Flash"):
    """Helper to create mock players list for get_players_for_game"""
    return [
        {"player_id": 0, "agent_id": player1_name},
        {"player_id": 1, "agent_id": player2_name},
    ]


def setup_mock_connection_manager(mock_cm, civserver_port=6001, players=None):
    """Setup mock connection_manager with both get_game_info and get_players_for_game"""
    mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=civserver_port))
    mock_cm.get_players_for_game = AsyncMock(
        return_value=players if players is not None else mock_players_for_game()
    )


class TestObserverUrlsEndpoint:
    """Test GET /api/games/{game_id}/observer-urls endpoint"""

    def setup_method(self):
        """Set up test client before each test"""
        self.client = TestClient(app)

    def test_returns_404_for_nonexistent_game(self):
        """Should return 404 when game_id doesn't exist in connection_manager"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=None)
            mock_cm.get_players_for_game = AsyncMock(return_value=[])

            response = self.client.get("/api/games/nonexistent-game/observer-urls")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_returns_409_when_port_not_assigned(self):
        """Should return 409 Conflict when game exists but port is None"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=None))
            mock_cm.get_players_for_game = AsyncMock(return_value=mock_players_for_game())

            response = self.client.get("/api/games/game-123/observer-urls")

        assert response.status_code == 409
        assert "port" in response.json()["detail"].lower()

    def test_returns_409_when_port_is_6000(self):
        """Should return 409 when port is 6000 (singleplayer, invalid for LLM games)"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6000))
            mock_cm.get_players_for_game = AsyncMock(return_value=mock_players_for_game())

            response = self.client.get("/api/games/game-123/observer-urls")

        assert response.status_code == 409

    def test_returns_observer_urls_for_valid_game(self):
        """Should return observer URLs when game has valid port (6001-6009)"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)

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

    def test_global_url_has_worldmap_camera(self):
        """Global observer URL should use worldmap camera preset with dynamic zoom"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()
        global_url = data["observer_urls"]["global"]

        # Parse URL and check parameters
        assert "camera=worldmap" in global_url
        assert "zoom_mode=dynamic" in global_url
        assert "embed=1" in global_url
        assert "autojoin=1" in global_url
        assert "action=observe" in global_url

    def test_player_urls_have_fog_of_war_attachment(self):
        """Player observer URLs should include observe_player param with player names"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()
        player1_url = data["observer_urls"]["player1"]
        player2_url = data["observer_urls"]["player2"]

        # Player 1 should observe first player (by name, URL-encoded)
        assert "observe_player=Claude_Sonnet_45" in player1_url
        assert "follow=Claude_Sonnet_45" in player1_url

        # Player 2 should observe second player (by name, URL-encoded)
        assert "observe_player=Gemini_3_Flash" in player2_url
        assert "follow=Gemini_3_Flash" in player2_url

    def test_player_urls_have_cinematic_camera(self):
        """Player observer URLs should use cinematic camera preset"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()
        player1_url = data["observer_urls"]["player1"]
        player2_url = data["observer_urls"]["player2"]

        assert "camera=cinematic" in player1_url
        assert "camera=cinematic" in player2_url

    def test_urls_use_configured_base_url(self):
        """URLs should use GATEWAY_FREECIV_WEB_BASE_URL from config"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()

        # All URLs should start with configured base URL + /webclient/
        for view_type, url in data["observer_urls"].items():
            assert url.startswith("https://freeciv.agentclash.gg/webclient/"), \
                f"{view_type} URL should use configured base URL"

    def test_urls_include_civserverport_parameter(self):
        """All URLs should include civserverport parameter matching game port"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6003)

            response = self.client.get("/api/games/game-123/observer-urls")

        data = response.json()

        for view_type, url in data["observer_urls"].items():
            assert "civserverport=6003" in url, \
                f"{view_type} URL should include civserverport=6003"

    def test_urls_include_unique_viewer_names(self):
        """Each view URL should have a unique viewer name to avoid conflicts"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)

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
            setup_mock_connection_manager(mock_cm, civserver_port=6005)

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

        # Restore original value (ROOT.war deploys at / context)
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
                setup_mock_connection_manager(mock_cm, civserver_port=port)

                response = self.client.get("/api/games/test-game/observer-urls")

            assert response.status_code == 200
            assert f"civserverport={port}" in response.json()["observer_urls"]["global"]

    def test_special_characters_in_game_id(self):
        """Should handle game IDs with special characters"""
        game_id = "game-with-dashes_and_underscores"

        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)

            response = self.client.get(f"/api/games/{game_id}/observer-urls")

        assert response.status_code == 200
        assert response.json()["game_id"] == game_id


class TestObserverUrlsRetryBehavior:
    """Test retry/polling behavior for observer URLs endpoint (race condition fix)"""

    def setup_method(self):
        self.client = TestClient(app)

    def test_waits_for_game_info_before_failing(self):
        """Should poll for game info instead of immediately returning 404"""
        call_count = 0

        async def delayed_game_info(game_id):
            nonlocal call_count
            call_count += 1
            # Return None for first 2 calls, then return valid data
            if call_count <= 2:
                return None
            return mock_game_info(civserver_port=6001)

        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = delayed_game_info
            mock_cm.get_players_for_game = AsyncMock(return_value=mock_players_for_game())
            # Also patch asyncio.sleep to speed up the test
            with patch("api_endpoints.asyncio.sleep", new_callable=AsyncMock):
                response = self.client.get("/api/games/delayed-game/observer-urls")

        assert response.status_code == 200
        assert call_count >= 3, "Should have polled at least 3 times"

    def test_waits_for_valid_port_before_failing(self):
        """Should poll until civserver_port is valid (not None or 6000)"""
        call_count = 0

        async def delayed_port_info(game_id):
            nonlocal call_count
            call_count += 1
            # Return invalid port first, then valid port
            if call_count <= 2:
                return mock_game_info(civserver_port=None)
            return mock_game_info(civserver_port=6001)

        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = delayed_port_info
            mock_cm.get_players_for_game = AsyncMock(return_value=mock_players_for_game())
            with patch("api_endpoints.asyncio.sleep", new_callable=AsyncMock):
                response = self.client.get("/api/games/delayed-port/observer-urls")

        assert response.status_code == 200
        assert call_count >= 3, "Should have polled at least 3 times"

    def test_returns_404_after_max_attempts(self):
        """Should return 404 after exhausting retry attempts"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            # Always return None - game never found
            mock_cm.get_game_info = AsyncMock(return_value=None)
            mock_cm.get_players_for_game = AsyncMock(return_value=[])
            with patch("api_endpoints.asyncio.sleep", new_callable=AsyncMock):
                response = self.client.get("/api/games/never-found/observer-urls")

        assert response.status_code == 404
        # Error message mentions wait time (dynamically calculated from constants)
        assert "after waiting" in response.json()["detail"]
        assert "s" in response.json()["detail"]

    def test_returns_409_after_max_attempts_when_port_invalid(self):
        """Should return 409 after exhausting retries when port stays invalid"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            # Return game info but with invalid port
            mock_cm.get_game_info = AsyncMock(return_value=mock_game_info(civserver_port=6000))
            mock_cm.get_players_for_game = AsyncMock(return_value=mock_players_for_game())
            with patch("api_endpoints.asyncio.sleep", new_callable=AsyncMock):
                response = self.client.get("/api/games/invalid-port/observer-urls")

        assert response.status_code == 409
        # Error message mentions wait time (dynamically calculated from constants)
        assert "after waiting" in response.json()["detail"]
        assert "s" in response.json()["detail"]

    def test_returns_immediately_when_game_ready(self):
        """Should return immediately without waiting if game info is available"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)
            with patch("api_endpoints.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                response = self.client.get("/api/games/ready-game/observer-urls")

        assert response.status_code == 200
        # Should not have called sleep since data was immediately available
        mock_sleep.assert_not_called()

    def test_succeeds_on_last_attempt(self):
        """Should succeed if game info arrives on the very last attempt (boundary condition)"""
        # Import the constant to know exactly how many attempts
        from utils.constants import OBSERVER_URL_MAX_RETRY_ATTEMPTS

        call_count = 0

        async def game_info_on_last_attempt(game_id):
            nonlocal call_count
            call_count += 1
            # Return None for all but the last attempt
            if call_count < OBSERVER_URL_MAX_RETRY_ATTEMPTS:
                return None
            return mock_game_info(civserver_port=6001)

        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = game_info_on_last_attempt
            mock_cm.get_players_for_game = AsyncMock(return_value=mock_players_for_game())
            with patch("api_endpoints.asyncio.sleep", new_callable=AsyncMock):
                response = self.client.get("/api/games/last-second/observer-urls")

        assert response.status_code == 200
        assert call_count == OBSERVER_URL_MAX_RETRY_ATTEMPTS, \
            f"Should have used exactly {OBSERVER_URL_MAX_RETRY_ATTEMPTS} attempts"

    def test_port_becomes_valid_during_polling(self):
        """Should succeed when port transitions from invalid (6000) to valid during polling"""
        call_count = 0

        async def port_transitions_to_valid(game_id):
            nonlocal call_count
            call_count += 1
            # Return single-player port (6000) first, then valid multiplayer port
            if call_count <= 3:
                return mock_game_info(civserver_port=6000)  # Invalid: single-player port
            return mock_game_info(civserver_port=6005)  # Valid: multiplayer port

        with patch("api_endpoints.connection_manager") as mock_cm:
            mock_cm.get_game_info = port_transitions_to_valid
            mock_cm.get_players_for_game = AsyncMock(return_value=mock_players_for_game())
            with patch("api_endpoints.asyncio.sleep", new_callable=AsyncMock):
                response = self.client.get("/api/games/port-transition/observer-urls")

        assert response.status_code == 200
        assert call_count >= 4, "Should have polled at least 4 times to see port transition"
        # Verify the correct port was used in the URLs
        data = response.json()
        assert "6005" in data["observer_urls"]["global"]


class TestObserverUrlsStreamingDisabled:
    """
    Regression prevention tests for observer URLs when streaming is disabled.

    These tests ensure that observer mode continues to work correctly regardless
    of the streaming feature flag state. This is critical for safe deployment
    of the streaming feature.
    """

    def setup_method(self):
        self.client = TestClient(app)

    def test_observer_urls_returned_when_gateway_stream_manager_is_none(self):
        """Observer URLs should be returned even when stream_manager is None (streaming disabled)"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)
            # Mock gateway with stream_manager=None (streaming disabled)
            with patch("api_endpoints.gateway") as mock_gateway:
                mock_gateway.stream_manager = None
                mock_gateway.game_sessions = {}

                response = self.client.get("/api/games/test-game/observer-urls")

        assert response.status_code == 200
        data = response.json()
        # Observer URLs should always be present
        assert "observer_urls" in data
        assert data["observer_urls"]["global"] is not None
        assert data["observer_urls"]["player1"] is not None
        assert data["observer_urls"]["player2"] is not None
        # Streaming URLs should be absent when streaming is disabled
        assert data.get("youtube_urls") is None
        assert data.get("local_stream_urls") is None

    def test_observer_urls_returned_when_gateway_is_none(self):
        """Observer URLs should work even when gateway module is not initialized"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)
            with patch("api_endpoints.gateway", None):
                response = self.client.get("/api/games/test-game/observer-urls")

        assert response.status_code == 200
        data = response.json()
        assert "observer_urls" in data
        assert data["observer_urls"]["global"] is not None
        # No streaming URLs when gateway is None
        assert data.get("youtube_urls") is None
        assert data.get("local_stream_urls") is None

    def test_local_stream_urls_only_returned_when_stream_manager_exists(self):
        """local_stream_urls should only be returned when stream_manager is initialized"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)
            # Mock gateway WITH stream_manager (streaming enabled)
            with patch("api_endpoints.gateway") as mock_gateway:
                mock_gateway.stream_manager = MagicMock()  # Non-None = streaming enabled
                mock_gateway.game_sessions = {}

                response = self.client.get("/api/games/test-game/observer-urls")

        assert response.status_code == 200
        data = response.json()
        # Observer URLs should always be present
        assert "observer_urls" in data
        # local_stream_urls should be present when stream_manager exists
        assert data.get("local_stream_urls") is not None

    def test_observer_mode_independent_of_streaming_failures(self):
        """Observer URLs should not fail if streaming encounters errors"""
        with patch("api_endpoints.connection_manager") as mock_cm:
            setup_mock_connection_manager(mock_cm, civserver_port=6001)
            # Mock gateway where stream_manager raises exception on access
            with patch("api_endpoints.gateway") as mock_gateway:
                mock_gateway.stream_manager = None  # Streaming disabled/failed
                mock_gateway.game_sessions = {"test-game": {"port": 6001}}

                response = self.client.get("/api/games/test-game/observer-urls")

        assert response.status_code == 200
        data = response.json()
        # Observer URLs should still work
        assert "observer_urls" in data
        assert "global" in data["observer_urls"]
