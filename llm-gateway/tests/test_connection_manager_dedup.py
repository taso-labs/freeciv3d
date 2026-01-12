#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for ConnectionManager.get_players_for_game deduplication.

Addresses bug where observer URLs showed the same player name for both
player1 and player2 when an agent had multiple connections.
"""

import os
import sys
import time
import pytest
from unittest.mock import MagicMock

# Ensure we can import from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from connection_manager import ConnectionManager, ConnectionInfo


class TestGetPlayersDeduplication:
    """Test that get_players_for_game deduplicates by player_id"""

    @pytest.fixture
    def connection_manager(self):
        """Fresh ConnectionManager instance"""
        return ConnectionManager()

    def create_mock_connection_info(
        self, identifier: str, game_id: str, player_id: int, authenticated: bool = True
    ) -> ConnectionInfo:
        """Create a mock ConnectionInfo with specified attributes"""
        mock_ws = MagicMock()
        conn = ConnectionInfo(
            websocket=mock_ws,
            connection_type="agent",
            identifier=identifier,
        )
        conn.game_id = game_id
        conn.player_id = player_id
        conn.authenticated = authenticated
        return conn

    @pytest.mark.asyncio
    async def test_returns_unique_players_by_player_id(self, connection_manager):
        """When agent has multiple connections, should deduplicate by player_id"""
        game_id = "test-game-123"

        # Simulate agent with 2 connections (e.g., reconnection scenario)
        # Both connections have the same player_id=0
        conn1 = self.create_mock_connection_info("Gemini_3_Flash", game_id, player_id=0)
        conn2 = self.create_mock_connection_info("Gemini_3_Flash", game_id, player_id=0)

        connection_manager.connections["conn-1"] = conn1
        connection_manager.connections["conn-2"] = conn2

        players = await connection_manager.get_players_for_game(game_id)

        # Should only return 1 player, not 2 duplicates
        assert len(players) == 1
        assert players[0]["player_id"] == 0
        assert players[0]["agent_id"] == "Gemini_3_Flash"

    @pytest.mark.asyncio
    async def test_returns_both_players_when_different_player_ids(self, connection_manager):
        """Normal case: two agents with different player_ids"""
        game_id = "test-game-123"

        conn1 = self.create_mock_connection_info("Gemini_3_Flash", game_id, player_id=0)
        conn2 = self.create_mock_connection_info("Claude_Sonnet_45", game_id, player_id=1)

        connection_manager.connections["conn-1"] = conn1
        connection_manager.connections["conn-2"] = conn2

        players = await connection_manager.get_players_for_game(game_id)

        assert len(players) == 2
        assert players[0]["player_id"] == 0
        assert players[0]["agent_id"] == "Gemini_3_Flash"
        assert players[1]["player_id"] == 1
        assert players[1]["agent_id"] == "Claude_Sonnet_45"

    @pytest.mark.asyncio
    async def test_sorted_by_player_id(self, connection_manager):
        """Results should be sorted by player_id"""
        game_id = "test-game-123"

        # Add connections in reverse order
        conn2 = self.create_mock_connection_info("Claude_Sonnet_45", game_id, player_id=1)
        conn1 = self.create_mock_connection_info("Gemini_3_Flash", game_id, player_id=0)

        connection_manager.connections["conn-2"] = conn2
        connection_manager.connections["conn-1"] = conn1

        players = await connection_manager.get_players_for_game(game_id)

        # Should be sorted by player_id regardless of insertion order
        assert players[0]["player_id"] == 0
        assert players[1]["player_id"] == 1

    @pytest.mark.asyncio
    async def test_filters_by_game_id(self, connection_manager):
        """Should only return players for the specified game_id"""
        game_id = "test-game-123"
        other_game_id = "other-game-456"

        conn1 = self.create_mock_connection_info("Gemini_3_Flash", game_id, player_id=0)
        conn2 = self.create_mock_connection_info("Claude_Sonnet_45", other_game_id, player_id=0)

        connection_manager.connections["conn-1"] = conn1
        connection_manager.connections["conn-2"] = conn2

        players = await connection_manager.get_players_for_game(game_id)

        assert len(players) == 1
        assert players[0]["agent_id"] == "Gemini_3_Flash"

    @pytest.mark.asyncio
    async def test_ignores_unauthenticated_connections(self, connection_manager):
        """Should not include unauthenticated connections"""
        game_id = "test-game-123"

        conn1 = self.create_mock_connection_info("Gemini_3_Flash", game_id, player_id=0, authenticated=True)
        conn2 = self.create_mock_connection_info("Claude_Sonnet_45", game_id, player_id=1, authenticated=False)

        connection_manager.connections["conn-1"] = conn1
        connection_manager.connections["conn-2"] = conn2

        players = await connection_manager.get_players_for_game(game_id)

        assert len(players) == 1
        assert players[0]["agent_id"] == "Gemini_3_Flash"

    @pytest.mark.asyncio
    async def test_ignores_connections_with_none_player_id(self, connection_manager):
        """Should not include connections where player_id is None"""
        game_id = "test-game-123"

        conn1 = self.create_mock_connection_info("Gemini_3_Flash", game_id, player_id=0)
        conn2 = self.create_mock_connection_info("Claude_Sonnet_45", game_id, player_id=1)
        conn2.player_id = None  # Not yet assigned

        connection_manager.connections["conn-1"] = conn1
        connection_manager.connections["conn-2"] = conn2

        players = await connection_manager.get_players_for_game(game_id)

        assert len(players) == 1
        assert players[0]["agent_id"] == "Gemini_3_Flash"

    @pytest.mark.asyncio
    async def test_first_connection_wins_for_same_player_id(self, connection_manager):
        """When deduplicating, keep first connection for each player_id"""
        game_id = "test-game-123"

        # Agent with 2 connections - first should win
        conn1 = self.create_mock_connection_info("Gemini_First", game_id, player_id=0)
        conn2 = self.create_mock_connection_info("Gemini_Second", game_id, player_id=0)

        connection_manager.connections["conn-1"] = conn1
        connection_manager.connections["conn-2"] = conn2

        players = await connection_manager.get_players_for_game(game_id)

        assert len(players) == 1
        # The first one added should be kept (dict iteration order is insertion order in Python 3.7+)
        assert players[0]["agent_id"] == "Gemini_First"

    @pytest.mark.asyncio
    async def test_empty_when_no_matching_connections(self, connection_manager):
        """Should return empty list when no connections match"""
        game_id = "test-game-123"

        # No connections for this game
        players = await connection_manager.get_players_for_game(game_id)

        assert len(players) == 0
