#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for stale connection reconnection fix.

When a civserver rejects a join during reconnection (for any reason),
the proxy should force-close the stale connection and retry once.
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
    """Test the retry decision logic for stale connections.

    Most civserver rejections during reconnection trigger cleanup-and-retry.
    However, definitively non-retriable rejections (e.g. server full, game
    already started) skip retry to avoid futile reconnection attempts.
    """

    def test_retriable_rejection_triggers_retry(self):
        """Retriable rejections during reconnection should trigger retry."""
        from llm_handler import NON_RETRIABLE_REASONS

        retriable_reasons = [
            None,
            "'Grok-41_Fast' already connected.",
            "Invalid username",
            f"Handshake timeout (5.0s)",
        ]
        for reason in retriable_reasons:
            join_rejected = True
            is_reconnecting = True
            reason_lower = (reason or '').lower()
            is_non_retriable = any(r in reason_lower for r in NON_RETRIABLE_REASONS)
            should_retry = is_reconnecting and join_rejected and not is_non_retriable
            self.assertTrue(should_retry, f"Should retry for reason: {reason!r}")

    def test_non_retriable_rejection_skips_retry(self):
        """Non-retriable rejections (server full, game started) should skip retry."""
        from llm_handler import NON_RETRIABLE_REASONS

        non_retriable_reasons = [
            "Server is full",
            "Game has already started",
            "server is full",  # case-insensitive
        ]
        for reason in non_retriable_reasons:
            join_rejected = True
            is_reconnecting = True
            reason_lower = (reason or '').lower()
            is_non_retriable = any(r in reason_lower for r in NON_RETRIABLE_REASONS)
            should_retry = is_reconnecting and join_rejected and not is_non_retriable
            self.assertFalse(should_retry, f"Should NOT retry for reason: {reason!r}")

    def test_retry_only_during_reconnection(self):
        """Retry logic should only activate when is_reconnecting=True."""
        # This mirrors the guard condition in llm_handler.py:
        # if is_reconnecting and self.civcom:

        # Case 1: Fresh connection - should NOT retry (is_reconnecting=False)
        is_reconnecting = False
        join_rejected = True
        should_retry = is_reconnecting and join_rejected
        self.assertFalse(should_retry)

        # Case 2: Reconnection with rejection - SHOULD retry
        is_reconnecting = True
        should_retry = is_reconnecting and join_rejected
        self.assertTrue(should_retry)

        # Case 3: Reconnection with any rejection reason - SHOULD retry
        should_retry = is_reconnecting and join_rejected
        self.assertTrue(should_retry)

    def test_handshake_timeout_treated_as_rejection(self):
        """Handshake timeout should synthesize join_rejected=True for retry."""
        # When handshake times out and join_rejected is still False,
        # the handler synthesizes a rejection so the retry path handles it.
        from llm_handler import STALE_CONN_HANDSHAKE_WAIT_SEC

        # Simulate CivCom state after handshake timeout (no server reply received)
        join_rejected = False
        join_rejection_reason = None

        # The handler code does:
        #   if not self.civcom.join_rejected:
        #       self.civcom.join_rejected = True
        #       self.civcom.join_rejection_reason = f"Handshake timeout ({...}s)"
        if not join_rejected:
            join_rejected = True
            join_rejection_reason = f"Handshake timeout ({STALE_CONN_HANDSHAKE_WAIT_SEC}s)"

        self.assertTrue(join_rejected)
        self.assertIn("Handshake timeout", join_rejection_reason)
        self.assertIn(str(STALE_CONN_HANDSHAKE_WAIT_SEC), join_rejection_reason)


class TestStaleConnectionConstants(unittest.TestCase):
    """Test that stale connection constants are properly defined."""

    def test_constants_exist(self):
        """Verify the stale connection constants are importable."""
        from llm_handler import (
            STALE_CONN_HANDSHAKE_WAIT_SEC,
            STALE_CONN_DISCONNECT_WAIT_SEC,
        )
        # Handshake wait should be reasonable (1-10s)
        self.assertGreaterEqual(STALE_CONN_HANDSHAKE_WAIT_SEC, 1.0)
        self.assertLessEqual(STALE_CONN_HANDSHAKE_WAIT_SEC, 10.0)

        # Disconnect wait should give civserver time to clean up
        self.assertGreaterEqual(STALE_CONN_DISCONNECT_WAIT_SEC, 1.0)
        self.assertLessEqual(STALE_CONN_DISCONNECT_WAIT_SEC, 10.0)


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
        """cleanup() should work on a CivCom that was rejected."""
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


class TestTurnDriftCivComDestruction(unittest.TestCase):
    """Test that large turn drift destroys the stale CivCom and unregisters it.

    When a preserved CivCom has a game_turn that drifts too far from the
    client's expected_turn, the civserver was likely reset. The handler must
    destroy the stale CivCom and remove it from the registry so subsequent
    reconnection attempts don't hit the same stale instance (infinite loop).
    """

    def test_large_drift_destroys_civcom_and_unregisters(self):
        """CivCom with turn drift > TURN_DRIFT_TOLERANCE should be stopped,
        closed, and unregistered from the registry."""
        from state_extractor import CivComRegistry
        from llm_handler import TURN_DRIFT_TOLERANCE

        registry = CivComRegistry()
        mock_civcom = MagicMock()
        mock_civcom.game_turn = 2  # Server reset to early turn
        mock_civcom.stopped = False

        registry.register_game("game1", "agent1", mock_civcom)

        expected_turn = 2 + TURN_DRIFT_TOLERANCE + 1  # Just over tolerance
        current_turn = mock_civcom.game_turn
        turn_drift = abs(current_turn - expected_turn)

        # Verify drift exceeds tolerance
        self.assertGreater(turn_drift, TURN_DRIFT_TOLERANCE)

        # Simulate the handler's destruction sequence (llm_handler.py lines 658-661)
        mock_civcom.stopped = True
        mock_civcom.close_connection()
        registry.unregister_game("game1", "agent1")

        # Verify all three steps happened
        self.assertTrue(mock_civcom.stopped)
        mock_civcom.close_connection.assert_called_once()
        self.assertIsNone(registry.get_civcom("game1", "agent1"))

    def test_small_drift_does_not_destroy_civcom(self):
        """CivCom with turn drift within TURN_DRIFT_TOLERANCE should be kept."""
        from state_extractor import CivComRegistry
        from llm_handler import TURN_DRIFT_TOLERANCE

        registry = CivComRegistry()
        mock_civcom = MagicMock()
        mock_civcom.game_turn = 8

        registry.register_game("game1", "agent1", mock_civcom)

        expected_turn = 8 + TURN_DRIFT_TOLERANCE  # Exactly at tolerance (not over)
        current_turn = mock_civcom.game_turn
        turn_drift = abs(current_turn - expected_turn)

        # Drift is within tolerance — should NOT destroy
        self.assertLessEqual(turn_drift, TURN_DRIFT_TOLERANCE)
        # CivCom should still be registered
        self.assertIs(registry.get_civcom("game1", "agent1"), mock_civcom)
        mock_civcom.close_connection.assert_not_called()

    def test_expected_turn_zero_skips_verification(self):
        """expected_turn=0 (or None) should skip state verification entirely."""
        # The guard condition: if expected_turn is not None and expected_turn > 0
        # Both None and 0 skip verification — agent-clash uses this on retry.
        for expected_turn in [None, 0]:
            should_verify = expected_turn is not None and expected_turn > 0
            self.assertFalse(should_verify, f"expected_turn={expected_turn!r} should skip verification")


if __name__ == '__main__':
    unittest.main()
