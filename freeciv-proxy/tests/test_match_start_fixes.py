#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for match start failure fixes (01KFQ563SKTWAF19ZGWRCX7CWQ)

Tests two fixes:
1. Python time module shadowing bug - Verifies no UnboundLocalError from local imports
2. Metaserver allocation retry logic - Tests exponential backoff for 503 responses

These tests verify the fixes prevent:
- E140: Retry logic failures due to time module shadowing
- Connection failures due to K8s distributed state mismatches
"""

import unittest
import asyncio
import json
import sys
import os
import time
from unittest.mock import Mock, MagicMock, patch, AsyncMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variables before importing modules
os.environ['CACHE_HMAC_SECRET'] = '8dc50280f151af309d728c951584576f205688dc82d7d295174f2ef1b3e32181'
os.environ['LLM_API_TOKENS'] = 'test-token-123'

from game_session_manager import (
    GameSession, GameSessionManager, GamePhase, PlayerInfo,
    METASERVER_MAX_RETRIES, METASERVER_BASE_DELAY
)
from packet_constants import PACKET_CHAT_MSG_REQ


class AsyncContextManager:
    """Helper class to create async context managers for mocking."""
    def __init__(self, return_value):
        self.return_value = return_value

    async def __aenter__(self):
        return self.return_value

    async def __aexit__(self, *args):
        pass


class TestTimeModuleShadowingFix(unittest.TestCase):
    """
    Tests for Phase 1: Python time module shadowing bug fix.

    Previously, functions had `import time` inside them which shadowed
    the global import, causing UnboundLocalError when `time` was
    referenced before the local import within the same function.

    These tests verify the fix by ensuring functions that use `time`
    work correctly without raising UnboundLocalError.
    """

    def setUp(self):
        """Set up test fixtures"""
        self.session = GameSession(
            game_id="time-shadow-test",
            civserver_port=6001,
            min_players=2
        )
        self.mock_civcom = Mock()
        self.mock_civcom.game_timeout = 45
        self.mock_civcom.queue_to_civserver = Mock()
        self.mock_civcom.send_packets_to_civserver = Mock()

    def test_pause_game_retry_uses_time_sleep_correctly(self):
        """
        Verify pause_game retry logic uses time.sleep without UnboundLocalError.

        The fix removed `import time` from inside pause_game(), which was
        causing the global `time` module to be shadowed. This test verifies
        that the retry logic (which calls time.sleep) works correctly.
        """
        # Make the first two attempts fail, third should succeed
        call_count = [0]
        def side_effect(*args):
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Simulated network failure")

        self.mock_civcom.queue_to_civserver.side_effect = side_effect

        # This should NOT raise UnboundLocalError
        # The function should retry with time.sleep between attempts
        result = self.session.pause_game(self.mock_civcom, "test_retry")

        # Should have made 4 queue calls: 2 failures + 1 timeout success + 1 autotoggle success
        # (Each successful attempt queues 2 packets: timeout + autotoggle)
        self.assertEqual(call_count[0], 4)

    def test_pause_game_time_sleep_called_on_retry(self):
        """
        Verify that time.sleep is actually called between retry attempts.
        """
        # Make the function always fail to force retries
        self.mock_civcom.queue_to_civserver.side_effect = Exception("Always fails")

        with patch('game_session_manager.time.sleep') as mock_sleep:
            result = self.session.pause_game(self.mock_civcom, "test_sleep")

            # Should have called time.sleep for retry delays
            # (MAX_RETRIES - 1 = 2 sleeps between 3 attempts)
            self.assertEqual(mock_sleep.call_count, 2)
            # Verify the sleep delay (RETRY_DELAY = 0.1)
            mock_sleep.assert_called_with(0.1)

    def test_pause_game_succeeds_on_first_try(self):
        """Verify pause_game works on first attempt without any time issues."""
        result = self.session.pause_game(self.mock_civcom, "first_try")

        self.assertTrue(result)
        self.assertTrue(self.session.is_paused)
        # Pause now queues 2 packets (timeout + autotoggle)
        self.assertEqual(self.mock_civcom.queue_to_civserver.call_count, 2)


class TestMetaserverAllocationRetry(unittest.TestCase):
    """
    Tests for Phase 2: Metaserver allocation retry logic.

    The fix adds exponential backoff retry when metaserver returns 503
    (no servers available on this pod). This allows time for K8s load
    balancer to route to a different pod with available servers.
    """

    def setUp(self):
        """Set up test fixtures"""
        self.manager = GameSessionManager(metaserver_url="http://localhost:8080")

    def _create_mock_response(self, status, json_data=None):
        """Create a mock aiohttp response."""
        response = MagicMock()
        response.status = status
        if json_data:
            async def mock_json():
                return json_data
            response.json = mock_json
        return response

    def test_allocation_succeeds_on_first_try(self):
        """Verify allocation works when metaserver returns 200 immediately."""
        async def run_test():
            response = self._create_mock_response(200, {
                "success": True,
                "port": 6001,
                "reused": False
            })

            with patch('game_session_manager.aiohttp.ClientSession') as mock_cls:
                mock_session = MagicMock()
                # aiohttp.ClientSession() is called directly, not as context manager
                mock_cls.return_value = mock_session
                mock_session.post.return_value = AsyncContextManager(response)

                port = await self.manager._allocate_port_from_metaserver("test-game-1")

                self.assertEqual(port, 6001)
                self.assertEqual(mock_session.post.call_count, 1)

        asyncio.run(run_test())

    def test_allocation_retries_on_503(self):
        """
        Verify allocation retries with exponential backoff on 503.

        503 means no servers available on current pod. The fix adds
        retry logic so the request can be routed to a different pod.
        """
        async def run_test():
            call_count = [0]

            def mock_post(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] < 3:
                    return AsyncContextManager(self._create_mock_response(503))
                else:
                    return AsyncContextManager(self._create_mock_response(200, {
                        "success": True,
                        "port": 6002,
                        "reused": False
                    }))

            with patch('game_session_manager.aiohttp.ClientSession') as mock_cls:
                mock_session = MagicMock()
                # aiohttp.ClientSession() is called directly, not as context manager
                mock_cls.return_value = mock_session
                mock_session.post = mock_post

                with patch('game_session_manager.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                    port = await self.manager._allocate_port_from_metaserver("test-game-2")

                    self.assertEqual(call_count[0], 3)
                    self.assertEqual(port, 6002)
                    self.assertEqual(mock_sleep.call_count, 2)
                    mock_sleep.assert_any_call(1.0)
                    mock_sleep.assert_any_call(2.0)

        asyncio.run(run_test())

    def test_allocation_returns_none_after_max_retries(self):
        """
        Verify allocation returns None after max retries on persistent 503.
        """
        async def run_test():
            call_count = [0]

            def mock_post(*args, **kwargs):
                call_count[0] += 1
                return AsyncContextManager(self._create_mock_response(503))

            with patch('game_session_manager.aiohttp.ClientSession') as mock_cls:
                mock_session = MagicMock()
                # aiohttp.ClientSession() is called directly, not as context manager
                mock_cls.return_value = mock_session
                mock_session.post = mock_post

                with patch('game_session_manager.asyncio.sleep', new_callable=AsyncMock):
                    port = await self.manager._allocate_port_from_metaserver("test-game-3")

                    self.assertIsNone(port)
                    self.assertEqual(call_count[0], 3)

        asyncio.run(run_test())

    def test_allocation_retries_on_exception(self):
        """
        Verify allocation retries on network exceptions.
        """
        async def run_test():
            call_count = [0]

            def mock_post(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] < 2:
                    raise Exception("Network error")
                else:
                    return AsyncContextManager(self._create_mock_response(200, {
                        "success": True,
                        "port": 6003,
                        "reused": False
                    }))

            with patch('game_session_manager.aiohttp.ClientSession') as mock_cls:
                mock_session = MagicMock()
                # aiohttp.ClientSession() is called directly, not as context manager
                mock_cls.return_value = mock_session
                mock_session.post = mock_post

                with patch('game_session_manager.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                    port = await self.manager._allocate_port_from_metaserver("test-game-4")

                    self.assertEqual(port, 6003)
                    self.assertEqual(call_count[0], 2)
                    mock_sleep.assert_called_once_with(1.0)

        asyncio.run(run_test())

    def test_exponential_backoff_delays_are_correct(self):
        """
        Verify the exponential backoff formula: base_delay * (2 ** attempt)

        For base_delay=1.0:
        - Attempt 0 to 1: 1.0 * (2^0) = 1.0s
        - Attempt 1 to 2: 1.0 * (2^1) = 2.0s
        """
        async def run_test():
            def mock_post(*args, **kwargs):
                return AsyncContextManager(self._create_mock_response(503))

            with patch('game_session_manager.aiohttp.ClientSession') as mock_cls:
                mock_session = MagicMock()
                # aiohttp.ClientSession() is called directly, not as context manager
                mock_cls.return_value = mock_session
                mock_session.post = mock_post

                with patch('game_session_manager.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
                    await self.manager._allocate_port_from_metaserver("test-game-5")

                    calls = mock_sleep.call_args_list
                    self.assertEqual(len(calls), 2)
                    self.assertEqual(calls[0][0][0], 1.0)
                    self.assertEqual(calls[1][0][0], 2.0)

        asyncio.run(run_test())


class TestLocalSessionCache(unittest.TestCase):
    """
    Tests for session caching to prevent port allocation race conditions.

    When two players connect to the same game_id simultaneously,
    the session manager should return the same port from the cache
    rather than making duplicate metaserver requests.
    """

    def setUp(self):
        """Set up test fixtures"""
        self.manager = GameSessionManager(metaserver_url="http://localhost:8080")

    def _create_mock_response(self, status, json_data=None):
        """Create a mock aiohttp response."""
        response = MagicMock()
        response.status = status
        if json_data:
            async def mock_json():
                return json_data
            response.json = mock_json
        return response

    def test_second_player_gets_same_port_from_cache(self):
        """
        Verify second player reuses port from local session cache.

        This prevents the issue where Player 2 could get a different
        port than Player 1 for the same game_id.
        """
        async def run_test():
            game_id = "same-game-test"
            call_count = [0]

            def mock_post(*args, **kwargs):
                call_count[0] += 1
                return AsyncContextManager(self._create_mock_response(200, {
                    "success": True,
                    "port": 6005,
                    "reused": False
                }))

            with patch('game_session_manager.aiohttp.ClientSession') as mock_cls:
                mock_session = MagicMock()
                # aiohttp.ClientSession() is called directly, not as context manager
                mock_cls.return_value = mock_session
                mock_session.post = mock_post

                # First player allocates port
                port1 = await self.manager.allocate_civserver_port(game_id)

                # Second player should get same port from cache
                port2 = await self.manager.allocate_civserver_port(game_id)

                self.assertEqual(port1, 6005)
                self.assertEqual(port2, 6005)
                # Should only make ONE metaserver request (first player)
                self.assertEqual(call_count[0], 1)

        asyncio.run(run_test())

    def test_different_games_get_different_allocations(self):
        """Verify different game_ids trigger separate allocations."""
        async def run_test():
            call_count = [0]

            def mock_post(*args, **kwargs):
                call_count[0] += 1
                return AsyncContextManager(self._create_mock_response(200, {
                    "success": True,
                    "port": 6000 + call_count[0],
                    "reused": False
                }))

            with patch('game_session_manager.aiohttp.ClientSession') as mock_cls:
                mock_session = MagicMock()
                # aiohttp.ClientSession() is called directly, not as context manager
                mock_cls.return_value = mock_session
                mock_session.post = mock_post

                port1 = await self.manager.allocate_civserver_port("game-A")
                port2 = await self.manager.allocate_civserver_port("game-B")

                self.assertEqual(call_count[0], 2)
                self.assertEqual(port1, 6001)
                self.assertEqual(port2, 6002)

        asyncio.run(run_test())


class TestStalePausedSessionCleanup(unittest.TestCase):
    """Tests for stale paused-session cleanup and forced port release."""

    def setUp(self):
        self.manager = GameSessionManager(metaserver_url="http://localhost:8080")

    def test_expired_paused_session_releases_port_and_clears_flags(self):
        async def run_test():
            game_id = "stale-paused-game"
            session = GameSession(game_id=game_id, civserver_port=6006, min_players=2)
            session.is_paused = True
            session.paused_at = time.time() - 120  # Expired
            session._port_releasing = True
            session._port_releasing_since = time.time() - 120
            self.manager.sessions[game_id] = session

            self.manager.release_civserver_port = AsyncMock(return_value=True)

            cleaned = await self.manager.cleanup_stale_paused_sessions(suspension_timeout_secs=60)

            self.assertEqual(cleaned, 1)
            self.manager.release_civserver_port.assert_awaited_once_with(game_id, 6006)
            self.assertNotIn(game_id, self.manager.sessions)
            self.assertFalse(session._port_releasing)
            self.assertIsNone(session._port_releasing_since)

        asyncio.run(run_test())

    def test_expired_paused_session_with_active_reconnect_is_skipped(self):
        async def run_test():
            game_id = "active-reconnect-game"
            session = GameSession(game_id=game_id, civserver_port=6007, min_players=2)
            session.is_paused = True
            session.paused_at = time.time() - 120  # Expired

            active_handler = Mock()
            active_handler.ws_connection = Mock()
            active_handler.ws_connection.is_closing.return_value = False
            session.players = {
                "agent-1": PlayerInfo(agent_id="agent-1", player_id=0, handler=active_handler)
            }
            self.manager.sessions[game_id] = session

            self.manager.release_civserver_port = AsyncMock(return_value=True)

            cleaned = await self.manager.cleanup_stale_paused_sessions(suspension_timeout_secs=60)

            self.assertEqual(cleaned, 0)
            self.manager.release_civserver_port.assert_not_called()
            self.assertIn(game_id, self.manager.sessions)

        asyncio.run(run_test())

    def test_failed_release_retains_session_and_resets_flag(self):
        async def run_test():
            game_id = "failed-release-game"
            session = GameSession(game_id=game_id, civserver_port=6008, min_players=2)
            session.is_paused = True
            session.paused_at = time.time() - 120  # Expired
            self.manager.sessions[game_id] = session

            self.manager.release_civserver_port = AsyncMock(return_value=False)

            cleaned = await self.manager.cleanup_stale_paused_sessions(suspension_timeout_secs=60)

            self.assertEqual(cleaned, 0)
            self.manager.release_civserver_port.assert_awaited_once_with(game_id, 6008)
            # Session must be retained for retry on next sweep
            self.assertIn(game_id, self.manager.sessions)
            # _port_releasing flag must be reset so next sweep can retry
            self.assertFalse(session._port_releasing)
            self.assertIsNone(session._port_releasing_since)

        asyncio.run(run_test())


class TestModuleImports(unittest.TestCase):
    """
    Tests to verify module imports don't have shadowing issues.

    These tests import the actual modules and verify they can be
    used without UnboundLocalError from variable shadowing.
    """

    def test_llm_handler_imports_without_error(self):
        """Verify llm_handler module imports successfully."""
        try:
            import llm_handler
            self.assertTrue(True)
        except UnboundLocalError as e:
            self.fail(f"llm_handler import caused UnboundLocalError: {e}")

    def test_game_session_manager_imports_without_error(self):
        """Verify game_session_manager module imports successfully."""
        try:
            import game_session_manager
            self.assertTrue(True)
        except UnboundLocalError as e:
            self.fail(f"game_session_manager import caused UnboundLocalError: {e}")

    def test_time_module_accessible_in_game_session(self):
        """Verify time module is properly accessible in GameSession methods."""
        session = GameSession(
            game_id="import-test",
            civserver_port=6001,
            min_players=2
        )

        # These operations internally use time.time() or time.sleep()
        # and should not raise UnboundLocalError
        try:
            status = session.get_status()
            self.assertIn('uptime', status)
            self.assertIsInstance(status['uptime'], float)
        except UnboundLocalError as e:
            self.fail(f"time module access caused UnboundLocalError: {e}")


if __name__ == '__main__':
    unittest.main()
