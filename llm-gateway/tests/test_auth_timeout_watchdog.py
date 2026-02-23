#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for AgentWebSocketHandler._auth_timeout_watchdog().

Covers the four key scenarios:
1. Watchdog fires E050 when auth_success not received within timeout
2. Watchdog is cancelled when auth succeeds (no E050 sent)
3. Reconnection resets the watchdog (old watchdog cancelled, new one started)
4. Late-cancel after agent disconnects is a graceful no-op
"""

import asyncio
import json
import os
import sys
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _make_handler():
    """Create a minimal AgentWebSocketHandler with mocked dependencies."""
    from websocket_handlers import AgentWebSocketHandler

    mock_ws = AsyncMock()
    mock_ws.send_text = AsyncMock()
    handler = AgentWebSocketHandler(websocket=mock_ws, agent_id="test-agent")
    handler.connection_id = "conn-123"
    return handler


@pytest.fixture
def handler():
    return _make_handler()


# ---------------------------------------------------------------------------
# Scenario 1: Watchdog fires E050 on timeout
# ---------------------------------------------------------------------------
class TestWatchdogFiresE050:
    """When auth_success is not received before the timeout, the watchdog
    should send an E050 error to the agent."""

    @pytest.mark.asyncio
    @patch("websocket_handlers.settings")
    async def test_watchdog_sends_e050_on_timeout(self, mock_settings, handler):
        """Watchdog fires E050 when auth_success not received."""
        mock_settings.auth_timeout = 0.05  # 50ms for fast test

        handler.authenticated = False
        handler._proxy_listener_task = None

        await handler._auth_timeout_watchdog()

        # Verify E050 was sent
        handler.websocket.send_text.assert_called_once()
        sent = json.loads(handler.websocket.send_text.call_args[0][0])
        assert sent["type"] == "error"
        assert sent["data"]["code"] == "E050"
        assert sent["data"]["details"]["reason"] == "auth_timeout"

    @pytest.mark.asyncio
    @patch("websocket_handlers.settings")
    async def test_watchdog_cancels_listener_on_timeout(self, mock_settings, handler):
        """After firing E050, watchdog should cancel the proxy listener task."""
        mock_settings.auth_timeout = 0.05

        handler.authenticated = False
        mock_listener = Mock()  # asyncio.Task uses sync done()/cancel()
        mock_listener.done.return_value = False
        handler._proxy_listener_task = mock_listener

        await handler._auth_timeout_watchdog()

        mock_listener.cancel.assert_called_once()


# ---------------------------------------------------------------------------
# Scenario 2: Watchdog cancelled on successful auth
# ---------------------------------------------------------------------------
class TestWatchdogCancelledOnAuth:
    """When auth_success arrives, the watchdog task is cancelled and
    no E050 should be sent."""

    @pytest.mark.asyncio
    @patch("websocket_handlers.settings")
    async def test_no_e050_when_cancelled(self, mock_settings, handler):
        """Cancelling the watchdog (simulating auth success) should not send E050."""
        mock_settings.auth_timeout = 10  # Long timeout — we'll cancel before it fires

        handler.authenticated = False

        task = asyncio.create_task(handler._auth_timeout_watchdog())
        # Let the task start sleeping
        await asyncio.sleep(0.01)
        # Simulate auth success: cancel the watchdog
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        handler.websocket.send_text.assert_not_called()

    @pytest.mark.asyncio
    @patch("websocket_handlers.settings")
    async def test_authenticated_before_timeout_no_e050(self, mock_settings, handler):
        """If authenticated=True before timeout expires, no E050 is sent."""
        mock_settings.auth_timeout = 0.05

        # Auth succeeds before watchdog fires
        handler.authenticated = True
        handler._proxy_listener_task = None

        await handler._auth_timeout_watchdog()

        handler.websocket.send_text.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 3: Reconnection resets watchdog
# ---------------------------------------------------------------------------
class TestWatchdogResetOnReconnect:
    """When an agent reconnects, the old watchdog is cancelled and a new
    one is started. Verifies the cancel-and-replace pattern."""

    @pytest.mark.asyncio
    @patch("websocket_handlers.settings")
    async def test_old_watchdog_cancelled_on_reconnect(self, mock_settings, handler):
        """Simulating reconnect: old watchdog cancelled, new one takes over."""
        mock_settings.auth_timeout = 10  # Long — won't fire during test

        handler.authenticated = False

        # Start first watchdog (simulates initial connection)
        first_task = asyncio.create_task(handler._auth_timeout_watchdog())
        handler._auth_timeout_task = first_task
        await asyncio.sleep(0.01)

        # Simulate reconnect: cancel old, start new (mirrors _connect_to_proxy_and_forward)
        assert not first_task.done()
        first_task.cancel()
        try:
            await first_task
        except asyncio.CancelledError:
            pass

        # First watchdog should NOT have sent E050
        handler.websocket.send_text.assert_not_called()

        # Start second watchdog with short timeout
        mock_settings.auth_timeout = 0.05
        handler.authenticated = False
        handler._proxy_listener_task = None
        second_task = asyncio.create_task(handler._auth_timeout_watchdog())
        await second_task  # Let it fire

        # Second watchdog SHOULD fire E050
        handler.websocket.send_text.assert_called_once()
        sent = json.loads(handler.websocket.send_text.call_args[0][0])
        assert sent["data"]["code"] == "E050"


# ---------------------------------------------------------------------------
# Scenario 4: Agent disconnects before watchdog fires (graceful no-op)
# ---------------------------------------------------------------------------
class TestWatchdogAgentDisconnected:
    """If the agent's WebSocket is already closed when the watchdog tries
    to send E050, it should handle the error gracefully."""

    @pytest.mark.asyncio
    @patch("websocket_handlers.settings")
    async def test_send_error_guarded_against_disconnect(self, mock_settings, handler):
        """_send_error failure (agent gone) should not raise from watchdog."""
        mock_settings.auth_timeout = 0.05

        handler.authenticated = False
        handler._proxy_listener_task = None
        # Simulate agent WebSocket already closed
        handler.websocket.send_text.side_effect = Exception("WebSocket closed")

        # Should NOT raise — the try/except in watchdog handles it
        await handler._auth_timeout_watchdog()

        # send_text was attempted (and failed gracefully)
        handler.websocket.send_text.assert_called_once()
