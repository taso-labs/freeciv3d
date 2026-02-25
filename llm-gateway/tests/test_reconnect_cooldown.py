#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for ConnectionManager reconnect cooldown logic.

Validates that check_resumable_session enforces a minimum cooldown
between disconnect and reconnect to prevent rapid connect/disconnect
spirals that leak zombie CivCom instances.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from connection_manager import ConnectionManager, ConnectionInfo


@pytest.fixture
def manager():
    """Create a ConnectionManager with known settings for testing."""
    with patch('connection_manager.settings') as mock_settings:
        mock_settings.heartbeat_interval = 30
        mock_settings.session_resumption_window = 7200
        mgr = ConnectionManager()
        # Override cooldown for predictable testing
        mgr.MIN_RECONNECT_COOLDOWN_SECS = 5.0
        yield mgr


def _make_disconnected_session(identifier: str, disconnected_ago: float) -> ConnectionInfo:
    """Create a mock disconnected session that disconnected `disconnected_ago` seconds ago."""
    mock_ws = AsyncMock()
    info = ConnectionInfo(mock_ws, "agent", identifier, session_id="session-123")
    info.player_id = 1
    info.game_id = "game-1"
    info.authenticated = True
    info.disconnected_at = time.time() - disconnected_ago
    return info


class TestReconnectCooldown:
    """Tests for the reconnect cooldown guard in check_resumable_session."""

    @pytest.mark.asyncio
    async def test_reject_immediate_reconnect(self, manager):
        """Reconnect at 0s after disconnect should be rejected."""
        manager.disconnected_sessions["agent-1"] = _make_disconnected_session("agent-1", 0.0)

        result = await manager.check_resumable_session("agent-1")
        assert result is None, "Should reject reconnect at 0s (within cooldown)"

    @pytest.mark.asyncio
    async def test_reject_reconnect_within_cooldown(self, manager):
        """Reconnect at 4.9s (just under 5s cooldown) should be rejected."""
        manager.disconnected_sessions["agent-1"] = _make_disconnected_session("agent-1", 4.9)

        result = await manager.check_resumable_session("agent-1")
        assert result is None, "Should reject reconnect at 4.9s (within 5s cooldown)"

    @pytest.mark.asyncio
    async def test_allow_reconnect_after_cooldown(self, manager):
        """Reconnect at 5.0s (exactly at cooldown threshold) should be allowed."""
        manager.disconnected_sessions["agent-1"] = _make_disconnected_session("agent-1", 5.0)

        result = await manager.check_resumable_session("agent-1")
        assert result is not None, "Should allow reconnect at 5.0s (cooldown elapsed)"
        assert result.session_id == "session-123"
        assert result.player_id == 1

    @pytest.mark.asyncio
    async def test_allow_reconnect_well_after_cooldown(self, manager):
        """Reconnect at 30s after disconnect should be allowed."""
        manager.disconnected_sessions["agent-1"] = _make_disconnected_session("agent-1", 30.0)

        result = await manager.check_resumable_session("agent-1")
        assert result is not None, "Should allow reconnect at 30s"

    @pytest.mark.asyncio
    async def test_reject_expired_session(self, manager):
        """Reconnect after session_resumption_window (7200s) should expire the session."""
        manager.disconnected_sessions["agent-1"] = _make_disconnected_session("agent-1", 7201.0)

        result = await manager.check_resumable_session("agent-1")
        assert result is None, "Should reject expired session"
        # Session should be cleaned up
        assert "agent-1" not in manager.disconnected_sessions

    @pytest.mark.asyncio
    async def test_no_session_returns_none(self, manager):
        """check_resumable_session with no cached session should return None."""
        result = await manager.check_resumable_session("unknown-agent")
        assert result is None

    @pytest.mark.asyncio
    async def test_session_without_disconnected_at_returns_none(self, manager):
        """Session with disconnected_at=None should return None."""
        mock_ws = AsyncMock()
        info = ConnectionInfo(mock_ws, "agent", "agent-1")
        info.disconnected_at = None
        manager.disconnected_sessions["agent-1"] = info

        result = await manager.check_resumable_session("agent-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_cooldown_rejection_does_not_remove_session(self, manager):
        """Cooldown rejection should preserve the session for later retry."""
        manager.disconnected_sessions["agent-1"] = _make_disconnected_session("agent-1", 2.0)

        result = await manager.check_resumable_session("agent-1")
        assert result is None
        # Session should still be cached for retry
        assert "agent-1" in manager.disconnected_sessions
