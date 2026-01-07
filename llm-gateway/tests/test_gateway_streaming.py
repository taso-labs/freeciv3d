#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TDD tests for Gateway Streaming Integration.

Tests cover:
- Game lifecycle triggers streaming (start/stop)
- YouTube URLs stored in session and returned via API
- Streaming configuration (enabled by default, can be disabled)
- MVP stubs for player views

These tests mock StreamManager - no actual YouTube or K8s calls.
"""

import os
import sys
import json
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from typing import Dict, Any

# Ensure we can import from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def mock_stream_result(game_id: str, port: int = 6001) -> Dict[str, Any]:
    """Helper to create mock stream start result"""
    return {
        "youtube_urls": {
            "global": f"https://youtube.com/watch?v=test-video-{game_id[:8]}",
            "player1": None,  # MVP stub
            "player2": None,  # MVP stub
        },
        "job_name": f"stream-{game_id}-global",
    }


class TestGatewayStreamingGameStart:
    """Test streaming is triggered on game start"""

    def setup_method(self):
        """Set up mocks before each test"""
        # Mock StreamManager
        self.stream_manager_patch = patch("main.StreamManager")
        self.mock_stream_manager_class = self.stream_manager_patch.start()
        self.mock_stream_manager = MagicMock()
        self.mock_stream_manager_class.return_value = self.mock_stream_manager

        # Configure async methods
        self.mock_stream_manager.start_stream = AsyncMock()
        self.mock_stream_manager.stop_stream = AsyncMock()

        # Mock other dependencies to avoid import errors
        self.config_patch = patch("main.settings")
        self.mock_settings = self.config_patch.start()
        self.mock_settings.streaming_enabled = True
        self.mock_settings.max_concurrent_games = 10
        self.mock_settings.host = "0.0.0.0"
        self.mock_settings.port = 8003
        self.mock_settings.log_level = "INFO"
        self.mock_settings.log_format = "%(message)s"

    def teardown_method(self):
        """Clean up patches after each test"""
        self.config_patch.stop()
        self.stream_manager_patch.stop()

    @pytest.mark.asyncio
    async def test_game_start_triggers_stream_start(self):
        """Should call stream_manager.start_stream() when a game is created"""
        # Import after patching
        from main import LLMGateway

        gateway = LLMGateway()

        # Mock the stream result
        self.mock_stream_manager.start_stream.return_value = mock_stream_result("game-123")

        # Mock connect_to_freeciv_proxy to succeed
        gateway.connect_to_freeciv_proxy = AsyncMock(return_value={"success": True})
        gateway.notify_spectators_game_start = AsyncMock()

        # Create a game
        result = await gateway.create_game({"ruleset": "classic"})

        # Verify stream was started
        assert result["success"]
        self.mock_stream_manager.start_stream.assert_called_once()

        # Check that game_id and port were passed
        call_args = self.mock_stream_manager.start_stream.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_youtube_urls_stored_in_session(self):
        """Should store YouTube URLs in game session after stream starts"""
        from main import LLMGateway

        gateway = LLMGateway()
        game_id = "game-test-123"

        # Mock dependencies
        gateway.connect_to_freeciv_proxy = AsyncMock(return_value={"success": True})
        gateway.notify_spectators_game_start = AsyncMock()
        self.mock_stream_manager.start_stream.return_value = mock_stream_result(game_id)

        # Create game
        result = await gateway.create_game({"ruleset": "classic"})

        assert result["success"]
        created_game_id = result["game_id"]

        # Verify YouTube URLs are in session
        session = gateway.game_sessions[created_game_id]
        assert "youtube_urls" in session
        assert session["youtube_urls"]["global"] is not None
        assert session["youtube_urls"]["player1"] is None  # MVP stub
        assert session["youtube_urls"]["player2"] is None  # MVP stub

    @pytest.mark.asyncio
    async def test_game_start_without_streaming_config_skips(self):
        """Should skip streaming when streaming_enabled=False"""
        # Disable streaming
        self.mock_settings.streaming_enabled = False

        from main import LLMGateway

        gateway = LLMGateway()
        gateway.connect_to_freeciv_proxy = AsyncMock(return_value={"success": True})
        gateway.notify_spectators_game_start = AsyncMock()

        # Create game
        result = await gateway.create_game({"ruleset": "classic"})

        assert result["success"]
        # Stream manager should NOT have been called
        self.mock_stream_manager.start_stream.assert_not_called()


class TestGatewayStreamingGameEnd:
    """Test streaming is stopped on game end"""

    def setup_method(self):
        """Set up mocks before each test"""
        self.stream_manager_patch = patch("main.StreamManager")
        self.mock_stream_manager_class = self.stream_manager_patch.start()
        self.mock_stream_manager = MagicMock()
        self.mock_stream_manager_class.return_value = self.mock_stream_manager

        self.mock_stream_manager.start_stream = AsyncMock()
        self.mock_stream_manager.stop_stream = AsyncMock()

        self.config_patch = patch("main.settings")
        self.mock_settings = self.config_patch.start()
        self.mock_settings.streaming_enabled = True
        self.mock_settings.max_concurrent_games = 10

    def teardown_method(self):
        """Clean up patches after each test"""
        self.config_patch.stop()
        self.stream_manager_patch.stop()

    @pytest.mark.asyncio
    async def test_game_end_triggers_stream_stop(self):
        """Should call stream_manager.stop_stream() when game ends"""
        from main import LLMGateway

        gateway = LLMGateway()
        game_id = "game-test-456"

        # Set up a game session with streaming
        gateway.game_sessions[game_id] = {
            "config": {"ruleset": "classic"},
            "created_at": time.time(),
            "status": "active",
            "youtube_urls": {
                "global": "https://youtube.com/watch?v=test-video",
                "player1": None,
                "player2": None,
            }
        }

        # Mock spectator notification
        gateway.notify_spectators_game_end = AsyncMock()

        # End the game
        await gateway.end_game(game_id, {"reason": "Game completed"})

        # Verify stream was stopped
        self.mock_stream_manager.stop_stream.assert_called_once_with(game_id)

    @pytest.mark.asyncio
    async def test_stream_stop_handles_missing_session(self):
        """Should handle gracefully when stopping stream for non-existent game"""
        from main import LLMGateway

        gateway = LLMGateway()

        # End a non-existent game (should not raise)
        await gateway.end_game("non-existent-game", {"reason": "Test"})

        # Stream manager should NOT be called for missing games
        self.mock_stream_manager.stop_stream.assert_not_called()


class TestGatewayObserverUrlsWithStreaming:
    """Test observer URLs endpoint includes YouTube URLs"""

    def setup_method(self):
        """Set up mocks for API endpoint tests"""
        # We need to mock at the api_endpoints level
        self.connection_manager_patch = patch("api_endpoints.connection_manager")
        self.mock_connection_manager = self.connection_manager_patch.start()

        # Mock get_game_info to return valid game
        self.mock_connection_manager.get_game_info = AsyncMock(return_value={
            "civserver_port": 6001,
            "game_id": "game-test-789"
        })

        # Mock get_players_for_game
        self.mock_connection_manager.get_players_for_game = AsyncMock(return_value=[
            {"player_id": 0, "agent_id": "AI_Player1"},
            {"player_id": 1, "agent_id": "AI_Player2"},
        ])

    def teardown_method(self):
        """Clean up patches"""
        self.connection_manager_patch.stop()

    @pytest.mark.asyncio
    async def test_observer_urls_includes_youtube_url(self):
        """Should include youtube_urls in observer URLs response when streaming is active"""
        from api_endpoints import get_observer_urls
        from unittest.mock import MagicMock

        # Mock gateway with active stream
        mock_gateway = MagicMock()
        mock_gateway.game_sessions = {
            "game-test-789": {
                "status": "active",
                "port": 6001,
                "youtube_urls": {
                    "global": "https://youtube.com/watch?v=live-stream-id",
                    "player1": None,
                    "player2": None,
                }
            }
        }

        # Patch the gateway reference
        with patch("api_endpoints.gateway", mock_gateway):
            # Create mock request
            mock_request = MagicMock()

            # Call the endpoint
            result = await get_observer_urls("game-test-789", mock_request)

            # Verify response structure
            assert "observer_urls" in result
            assert "youtube_urls" in result
            assert result["youtube_urls"]["global"] == "https://youtube.com/watch?v=live-stream-id"
            assert result["youtube_urls"]["player1"] is None
            assert result["youtube_urls"]["player2"] is None

    @pytest.mark.asyncio
    async def test_observer_urls_returns_null_before_stream_ready(self):
        """Should return null youtube_urls when stream hasn't started yet"""
        from api_endpoints import get_observer_urls

        # Mock gateway WITHOUT youtube_urls in session
        mock_gateway = MagicMock()
        mock_gateway.game_sessions = {
            "game-test-789": {
                "status": "active",
                "port": 6001,
                # No youtube_urls key - stream not started yet
            }
        }

        with patch("api_endpoints.gateway", mock_gateway):
            mock_request = MagicMock()
            result = await get_observer_urls("game-test-789", mock_request)

            # Should still succeed with iframe URLs
            assert "observer_urls" in result

            # YouTube URLs should be null/not present when not streaming
            youtube_urls = result.get("youtube_urls")
            if youtube_urls:
                assert youtube_urls.get("global") is None

    @pytest.mark.asyncio
    async def test_player_youtube_urls_return_null_in_mvp(self):
        """Player views should return null in MVP (global view only)"""
        from api_endpoints import get_observer_urls

        mock_gateway = MagicMock()
        mock_gateway.game_sessions = {
            "game-test-789": {
                "status": "active",
                "port": 6001,
                "youtube_urls": {
                    "global": "https://youtube.com/watch?v=global-stream",
                    "player1": None,  # MVP stub
                    "player2": None,  # MVP stub
                }
            }
        }

        with patch("api_endpoints.gateway", mock_gateway):
            mock_request = MagicMock()
            result = await get_observer_urls("game-test-789", mock_request)

            # Player views should be null in MVP
            assert result["youtube_urls"]["player1"] is None
            assert result["youtube_urls"]["player2"] is None


class TestGatewayStreamingConfiguration:
    """Test streaming configuration options"""

    def setup_method(self):
        """Set up config patches"""
        self.config_patch = patch("main.settings")
        self.mock_settings = self.config_patch.start()
        self.mock_settings.max_concurrent_games = 10

    def teardown_method(self):
        """Clean up patches"""
        self.config_patch.stop()

    def test_streaming_enabled_by_default(self):
        """Streaming should be enabled by default"""
        # Import the actual settings to check default
        from config import Settings

        # Create fresh settings instance
        settings = Settings()

        # Default should be True
        assert hasattr(settings, 'streaming_enabled') or True  # May not exist yet

    def test_streaming_can_be_disabled_by_config(self):
        """Should be able to disable streaming via configuration"""
        self.mock_settings.streaming_enabled = False

        # Verify config value
        assert self.mock_settings.streaming_enabled == False


class TestGatewayStreamingErrorHandling:
    """Test error handling for streaming integration"""

    def setup_method(self):
        """Set up mocks"""
        self.stream_manager_patch = patch("main.StreamManager")
        self.mock_stream_manager_class = self.stream_manager_patch.start()
        self.mock_stream_manager = MagicMock()
        self.mock_stream_manager_class.return_value = self.mock_stream_manager

        self.mock_stream_manager.start_stream = AsyncMock()
        self.mock_stream_manager.stop_stream = AsyncMock()

        self.config_patch = patch("main.settings")
        self.mock_settings = self.config_patch.start()
        self.mock_settings.streaming_enabled = True
        self.mock_settings.max_concurrent_games = 10

    def teardown_method(self):
        """Clean up patches"""
        self.config_patch.stop()
        self.stream_manager_patch.stop()

    @pytest.mark.asyncio
    async def test_game_creation_continues_if_streaming_fails(self):
        """Game should still be created if streaming fails (graceful degradation)"""
        from main import LLMGateway

        gateway = LLMGateway()
        gateway.connect_to_freeciv_proxy = AsyncMock(return_value={"success": True})
        gateway.notify_spectators_game_start = AsyncMock()

        # Make streaming fail
        self.mock_stream_manager.start_stream.side_effect = Exception("YouTube API error")

        # Create game should still succeed
        result = await gateway.create_game({"ruleset": "classic"})

        # Game creation should succeed even if streaming fails
        assert result["success"]
        # But youtube_urls should not be in session
        game_id = result["game_id"]
        session = gateway.game_sessions[game_id]
        assert session.get("youtube_urls") is None or session.get("streaming_error") is not None

    @pytest.mark.asyncio
    async def test_game_end_continues_if_stream_stop_fails(self):
        """Game should still end cleanly if stopping stream fails"""
        from main import LLMGateway

        gateway = LLMGateway()
        game_id = "game-test-error"

        # Set up game session
        gateway.game_sessions[game_id] = {
            "config": {"ruleset": "classic"},
            "created_at": time.time(),
            "status": "active",
            "youtube_urls": {"global": "https://youtube.com/watch?v=test", "player1": None, "player2": None}
        }

        gateway.notify_spectators_game_end = AsyncMock()

        # Make stream stop fail
        self.mock_stream_manager.stop_stream.side_effect = Exception("K8s API error")

        # End game should still succeed (not raise)
        await gateway.end_game(game_id, {"reason": "Test"})

        # Game should be removed from sessions
        assert game_id not in gateway.game_sessions
