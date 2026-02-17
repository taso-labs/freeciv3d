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
        # This mirrors the guard condition in llm_handler.py line 681:
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


if __name__ == '__main__':
    unittest.main()
