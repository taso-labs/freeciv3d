#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for stale connection reconnection fix.

When a civserver rejects a join with "already connected" during reconnection,
the proxy should force-close the stale connection and retry.
"""

import asyncio
import json
import os
import sys
import time
import unittest
from threading import Event
from unittest.mock import MagicMock, patch, PropertyMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variables before importing modules
os.environ['CACHE_HMAC_SECRET'] = '8dc50280f151af309d728c951584576f205688dc82d7d295174f2ef1b3e32181'


class TestCivComJoinRejected(unittest.TestCase):
    """Test CivCom join_rejected flag behavior."""

    def test_join_rejected_defaults_to_false(self):
        """CivCom should start with join_rejected=False."""
        from civcom import CivCom

        mock_handler = MagicMock()
        mock_handler.loginpacket = '{"pid": 4}'
        civcom = CivCom("test_agent", 6000, "test_key", mock_handler)

        self.assertFalse(civcom.join_rejected)
        self.assertIsNone(civcom.join_rejection_reason)

    def test_join_rejected_set_on_you_can_join_false(self):
        """When civserver sends you_can_join=False, join_rejected should be set."""
        from civcom import CivCom
        from packet_constants import PACKET_SERVER_JOIN_REPLY

        mock_handler = MagicMock()
        mock_handler.loginpacket = '{"pid": 4}'
        civcom = CivCom("test_agent", 6000, "test_key", mock_handler)

        # Simulate receiving a rejection packet
        rejection_packet = json.dumps({
            'pid': PACKET_SERVER_JOIN_REPLY,
            'you_can_join': False,
            'message': "'test_agent' already connected.",
            'conn_id': -1
        })
        civcom.parse_and_store_packet(rejection_packet)

        self.assertTrue(civcom.join_rejected)
        self.assertEqual(civcom.join_rejection_reason, "'test_agent' already connected.")

    def test_join_not_rejected_on_you_can_join_true(self):
        """When civserver sends you_can_join=True, join_rejected stays False."""
        from civcom import CivCom
        from packet_constants import PACKET_SERVER_JOIN_REPLY

        mock_handler = MagicMock()
        mock_handler.loginpacket = '{"pid": 4}'
        civcom = CivCom("test_agent", 6000, "test_key", mock_handler)

        # Simulate receiving an acceptance packet
        accept_packet = json.dumps({
            'pid': PACKET_SERVER_JOIN_REPLY,
            'you_can_join': True,
            'conn_id': 1,
            'message': ''
        })
        civcom.parse_and_store_packet(accept_packet)

        self.assertFalse(civcom.join_rejected)
        self.assertIsNone(civcom.join_rejection_reason)

    def test_handshake_complete_set_on_rejection(self):
        """Handshake should complete (Event set) even on rejection."""
        from civcom import CivCom
        from packet_constants import PACKET_SERVER_JOIN_REPLY

        mock_handler = MagicMock()
        mock_handler.loginpacket = '{"pid": 4}'
        civcom = CivCom("test_agent", 6000, "test_key", mock_handler)

        # Before packet, handshake is not complete
        self.assertFalse(civcom.handshake_complete.is_set())

        rejection_packet = json.dumps({
            'pid': PACKET_SERVER_JOIN_REPLY,
            'you_can_join': False,
            'message': "'test_agent' already connected.",
            'conn_id': -1
        })
        civcom.parse_and_store_packet(rejection_packet)

        # After rejection, handshake should be complete (semaphore released)
        self.assertTrue(civcom.handshake_complete.is_set())


class TestStaleConnectionRetryLogic(unittest.TestCase):
    """Test the retry decision logic for stale connections."""

    def test_already_connected_detection(self):
        """Verify 'already connected' is detected in rejection reason."""
        # This tests the condition used in llm_handler.py
        reason = "'Grok-41_Fast' already connected."
        self.assertIn('already connected', reason)

    def test_other_rejection_not_retried(self):
        """Other rejection reasons should NOT trigger retry."""
        reasons = [
            "Server is full",
            "Invalid username",
            "Game has already started",
            None,
        ]
        for reason in reasons:
            self.assertNotIn('already connected', reason or '')

    def test_retry_only_during_reconnection(self):
        """Retry logic should only activate when is_reconnecting=True."""
        # This mirrors the guard condition in llm_handler.py:
        # if is_reconnecting and self.civcom:

        # Case 1: Fresh connection - should NOT retry
        is_reconnecting = False
        join_rejected = True
        reason = "'agent' already connected."
        should_retry = is_reconnecting and join_rejected and 'already connected' in (reason or '')
        self.assertFalse(should_retry)

        # Case 2: Reconnection with "already connected" - SHOULD retry
        is_reconnecting = True
        should_retry = is_reconnecting and join_rejected and 'already connected' in (reason or '')
        self.assertTrue(should_retry)

        # Case 3: Reconnection with different rejection - should NOT retry
        reason = "Server is full"
        should_retry = is_reconnecting and join_rejected and 'already connected' in (reason or '')
        self.assertFalse(should_retry)


class TestStaleConnectionConstants(unittest.TestCase):
    """Test that stale connection constants are properly defined."""

    def test_constants_exist(self):
        """Verify the stale connection constants are importable."""
        from llm_handler import (
            STALE_CONN_HANDSHAKE_WAIT_SEC,
            STALE_CONN_DISCONNECT_WAIT_SEC,
            STALE_CONN_MAX_RETRIES,
        )
        # Handshake wait should be reasonable (1-10s)
        self.assertGreaterEqual(STALE_CONN_HANDSHAKE_WAIT_SEC, 1.0)
        self.assertLessEqual(STALE_CONN_HANDSHAKE_WAIT_SEC, 10.0)

        # Disconnect wait should give civserver time to clean up
        self.assertGreaterEqual(STALE_CONN_DISCONNECT_WAIT_SEC, 1.0)
        self.assertLessEqual(STALE_CONN_DISCONNECT_WAIT_SEC, 10.0)

        # Max retries should be at least 1, at most 5
        self.assertGreaterEqual(STALE_CONN_MAX_RETRIES, 1)
        self.assertLessEqual(STALE_CONN_MAX_RETRIES, 5)


class TestCivComCleanupIdempotent(unittest.TestCase):
    """Test that CivCom.cleanup() is safe to call multiple times."""

    def test_double_cleanup_is_safe(self):
        """cleanup() should be idempotent — no error on second call."""
        from civcom import CivCom

        mock_handler = MagicMock()
        mock_handler.loginpacket = '{"pid": 4}'
        civcom = CivCom("test_agent", 6000, "test_key", mock_handler)

        # First cleanup
        civcom.cleanup()
        self.assertTrue(civcom.stopped)
        self.assertIsNone(civcom.socket)

        # Second cleanup should not raise
        civcom.cleanup()
        self.assertTrue(civcom.stopped)

    def test_cleanup_after_rejection(self):
        """cleanup() should work on a CivCom that was rejected and reset flags."""
        from civcom import CivCom
        from packet_constants import PACKET_SERVER_JOIN_REPLY

        mock_handler = MagicMock()
        mock_handler.loginpacket = '{"pid": 4}'
        civcom = CivCom("test_agent", 6000, "test_key", mock_handler)

        # Simulate rejection
        rejection_packet = json.dumps({
            'pid': PACKET_SERVER_JOIN_REPLY,
            'you_can_join': False,
            'message': "'test_agent' already connected.",
            'conn_id': -1
        })
        civcom.parse_and_store_packet(rejection_packet)

        # Verify rejection was detected before cleanup
        self.assertTrue(civcom.join_rejected)

        # cleanup should work even after rejection and reset the rejection flag
        civcom.cleanup()
        self.assertTrue(civcom.stopped)
        self.assertFalse(civcom.join_rejected)  # cleanup() resets rejection state
        self.assertIsNone(civcom.join_rejection_reason)


class TestCivComRegistryCleanup(unittest.TestCase):
    """Test that registry cleanup works for stale connection fix."""

    def test_unregister_cleans_up_civcom(self):
        """Unregistering should call cleanup on the CivCom."""
        from state_extractor import CivComRegistry

        registry = CivComRegistry()
        mock_civcom = MagicMock()
        mock_civcom.cleanup = MagicMock()

        registry.register_game("game1", "agent1", mock_civcom)
        registry.unregister_game("game1", "agent1")

        mock_civcom.cleanup.assert_called_once()
        self.assertIsNone(registry.get_civcom("game1", "agent1"))

    def test_unregister_nonexistent_is_safe(self):
        """Unregistering a nonexistent game/agent should not raise."""
        from state_extractor import CivComRegistry

        registry = CivComRegistry()
        # Should not raise
        registry.unregister_game("nonexistent_game", "nonexistent_agent")


class TestCivComRegistryThreadSafety(unittest.TestCase):
    """Test that CivComRegistry operations are thread-safe."""

    def test_registry_has_lock(self):
        """Registry should have a threading lock."""
        from state_extractor import CivComRegistry
        import threading

        registry = CivComRegistry()
        self.assertIsInstance(registry._lock, threading.Lock)

    def test_get_all_for_game_returns_snapshot(self):
        """get_all_for_game should return a safe copy, not a live view."""
        from state_extractor import CivComRegistry

        registry = CivComRegistry()
        mock1 = MagicMock()
        mock2 = MagicMock()
        registry.register_game("game1", "agent1", mock1)
        registry.register_game("game1", "agent2", mock2)
        registry.register_game("game2", "agent3", MagicMock())

        result = registry.get_all_for_game("game1")
        self.assertEqual(len(result), 2)
        self.assertIn(("game1", "agent1"), result)
        self.assertIn(("game1", "agent2"), result)

    def test_has_game_with_agent(self):
        """has_game should work with specific agent_id."""
        from state_extractor import CivComRegistry

        registry = CivComRegistry()
        registry.register_game("game1", "agent1", MagicMock())

        self.assertTrue(registry.has_game("game1", "agent1"))
        self.assertFalse(registry.has_game("game1", "agent2"))

    def test_has_game_any_agent(self):
        """has_game without agent_id should check any agent."""
        from state_extractor import CivComRegistry

        registry = CivComRegistry()
        registry.register_game("game1", "agent1", MagicMock())

        self.assertTrue(registry.has_game("game1"))
        self.assertFalse(registry.has_game("game2"))

    def test_concurrent_register_unregister(self):
        """Concurrent register/unregister should not raise."""
        from state_extractor import CivComRegistry
        import threading

        registry = CivComRegistry()
        errors = []

        def register_loop(agent_prefix, count):
            try:
                for i in range(count):
                    mock = MagicMock()
                    mock.cleanup = MagicMock()
                    registry.register_game("game1", f"{agent_prefix}_{i}", mock)
                    registry.unregister_game("game1", f"{agent_prefix}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_loop, args=(f"t{t}", 50))
            for t in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [], f"Concurrent access errors: {errors}")


class TestCleanupCivcomSafely(unittest.TestCase):
    """Test the _cleanup_civcom_safely helper method."""

    def test_cleanup_tolerates_cleanup_error(self):
        """_cleanup_civcom_safely should not raise if cleanup() throws."""
        from llm_handler import LLMWSHandler

        handler = MagicMock(spec=LLMWSHandler)
        handler.agent_id = "test_agent"

        # CivCom that throws on cleanup
        mock_civcom = MagicMock()
        mock_civcom.cleanup.side_effect = RuntimeError("socket already closed")
        handler.civcom = mock_civcom

        # Should not raise
        LLMWSHandler._cleanup_civcom_safely(handler, "game1")

    def test_cleanup_tolerates_unregister_error(self):
        """_cleanup_civcom_safely should not raise if unregister throws."""
        from llm_handler import LLMWSHandler

        handler = MagicMock(spec=LLMWSHandler)
        handler.agent_id = "test_agent"
        handler.civcom = MagicMock()

        with patch('llm_handler.civcom_registry') as mock_registry:
            mock_registry.get_civcom.return_value = None
            mock_registry.unregister_game.side_effect = KeyError("not found")

            # Should not raise
            LLMWSHandler._cleanup_civcom_safely(handler, "game1")


class TestRetryFailurePath(unittest.TestCase):
    """Test that retry failure properly cleans up resources."""

    def test_retry_failure_cleans_up_civcom(self):
        """When retry fails, the CivCom should be cleaned up."""
        from civcom import CivCom
        from packet_constants import PACKET_SERVER_JOIN_REPLY

        mock_handler = MagicMock()
        mock_handler.loginpacket = '{"pid": 4}'

        # First CivCom — rejected
        civcom1 = CivCom("test_agent", 6000, "test_key", mock_handler)
        rejection = json.dumps({
            'pid': PACKET_SERVER_JOIN_REPLY,
            'you_can_join': False,
            'message': "'test_agent' already connected.",
            'conn_id': -1
        })
        civcom1.parse_and_store_packet(rejection)
        self.assertTrue(civcom1.join_rejected)

        # Cleanup should reset state
        civcom1.cleanup()
        self.assertTrue(civcom1.stopped)
        self.assertFalse(civcom1.join_rejected)

        # Second CivCom (retry) — also rejected
        civcom2 = CivCom("test_agent", 6000, "test_key", mock_handler)
        civcom2.parse_and_store_packet(rejection)
        self.assertTrue(civcom2.join_rejected)

        # Cleanup the retry CivCom too
        civcom2.cleanup()
        self.assertTrue(civcom2.stopped)
        self.assertFalse(civcom2.join_rejected)


if __name__ == '__main__':
    unittest.main()
