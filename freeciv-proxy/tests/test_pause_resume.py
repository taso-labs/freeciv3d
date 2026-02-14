#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for pause/resume coordinated disconnect functionality.

Tests the AI takeover prevention mechanism that:
1. Pauses game when an agent disconnects
2. Suspends partner sessions
3. Resumes game when both agents reconnect

This addresses the root cause of match 01KEC445AXNTQ7B2YZHBEGMYS2 failure where
Gemini's player slot was taken over by AI after container restart.
"""

import unittest
import json
import sys
import os
import secrets
from unittest.mock import Mock, MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# IMPORTANT: Set environment variables BEFORE importing modules that use them
os.environ['CACHE_HMAC_SECRET'] = '8dc50280f151af309d728c951584576f205688dc82d7d295174f2ef1b3e32181'
os.environ['LLM_API_TOKENS'] = 'test-token-123'

from game_session_manager import GameSession, GamePhase, PlayerInfo
from packet_constants import PACKET_CHAT_MSG_REQ


class TestGameSessionPause(unittest.TestCase):
    """Unit tests for GameSession.pause_game()"""

    def setUp(self):
        """Set up test fixtures"""
        self.session = GameSession(
            game_id="test-game-123",
            civserver_port=6001,
            min_players=2
        )
        self.mock_civcom = Mock()
        self.mock_civcom.game_timeout = 45  # Original timeout
        self.mock_civcom.queue_to_civserver = Mock()
        self.mock_civcom.send_packets_to_civserver = Mock()

    def test_pause_game_sends_correct_packet(self):
        """Verify pause sends /set timeout 0 and /set autotoggle disabled"""
        result = self.session.pause_game(self.mock_civcom, "test_disconnect")

        self.assertTrue(result)
        # Pause now sends two packets: timeout 0 + autotoggle disabled
        calls = self.mock_civcom.queue_to_civserver.call_args_list
        self.assertEqual(len(calls), 2)
        timeout_packet = json.loads(calls[0][0][0])
        self.assertEqual(timeout_packet["pid"], PACKET_CHAT_MSG_REQ)
        self.assertEqual(timeout_packet["message"], "/set timeout 0")
        autotoggle_packet = json.loads(calls[1][0][0])
        self.assertEqual(autotoggle_packet["pid"], PACKET_CHAT_MSG_REQ)
        self.assertEqual(autotoggle_packet["message"], "/set autotoggle disabled")

    def test_pause_game_captures_original_timeout(self):
        """Verify original timeout is stored from civcom.game_timeout"""
        self.session.pause_game(self.mock_civcom, "test")
        self.assertEqual(self.session.original_timeout, 45)

    def test_pause_game_sets_is_paused_flag(self):
        """Verify is_paused becomes True after pause"""
        self.assertFalse(self.session.is_paused)
        self.session.pause_game(self.mock_civcom, "test")
        self.assertTrue(self.session.is_paused)

    def test_pause_game_returns_false_when_already_paused(self):
        """Verify no-op when game is already paused"""
        self.session.is_paused = True
        result = self.session.pause_game(self.mock_civcom, "test")

        self.assertFalse(result)
        self.mock_civcom.queue_to_civserver.assert_not_called()

    def test_pause_game_returns_false_without_civcom(self):
        """Verify failure handling when civcom is None"""
        result = self.session.pause_game(None, "test")
        self.assertFalse(result)
        self.assertFalse(self.session.is_paused)

    def test_pause_game_uses_zero_timeout_if_not_captured(self):
        """Verify fallback to 0 when civcom.game_timeout is None (timeout=0 games)"""
        self.mock_civcom.game_timeout = None
        self.session.pause_game(self.mock_civcom, "test")
        # game_timeout=None means server uses timeout=0 — preserve that
        self.assertEqual(self.session.original_timeout, 0)

    def test_pause_game_calls_send_packets(self):
        """Verify send_packets_to_civserver is called after queueing"""
        self.session.pause_game(self.mock_civcom, "test")
        self.mock_civcom.send_packets_to_civserver.assert_called_once()

    def test_pause_game_preserves_first_timeout(self):
        """Verify original timeout is not overwritten on second pause attempt"""
        # First pause with timeout 45
        self.session.pause_game(self.mock_civcom, "test")
        self.assertEqual(self.session.original_timeout, 45)

        # Reset for second call (but original_timeout should be preserved)
        self.session.is_paused = False
        self.mock_civcom.game_timeout = 90  # Different timeout
        self.session.pause_game(self.mock_civcom, "test2")

        # Should keep the first captured timeout
        self.assertEqual(self.session.original_timeout, 45)


class TestGameSessionResume(unittest.TestCase):
    """Unit tests for GameSession.resume_game()"""

    def setUp(self):
        """Set up test fixtures"""
        self.session = GameSession(
            game_id="test-game-123",
            civserver_port=6001,
            min_players=2
        )
        self.session.is_paused = True
        self.session.original_timeout = 45

        self.mock_civcom = Mock()
        self.mock_civcom.queue_to_civserver = Mock()
        self.mock_civcom.send_packets_to_civserver = Mock()

    def test_resume_game_sends_correct_packet(self):
        """Verify resume sends /set timeout {original}"""
        result = self.session.resume_game(self.mock_civcom)

        self.assertTrue(result)
        call_args = self.mock_civcom.queue_to_civserver.call_args[0][0]
        packet = json.loads(call_args)
        self.assertEqual(packet["pid"], PACKET_CHAT_MSG_REQ)
        self.assertEqual(packet["message"], "/set timeout 45")

    def test_resume_game_clears_is_paused_flag(self):
        """Verify is_paused becomes False after resume"""
        self.assertTrue(self.session.is_paused)
        self.session.resume_game(self.mock_civcom)
        self.assertFalse(self.session.is_paused)

    def test_resume_game_returns_false_when_not_paused(self):
        """Verify no-op when game is not paused"""
        self.session.is_paused = False
        result = self.session.resume_game(self.mock_civcom)

        self.assertFalse(result)
        self.mock_civcom.queue_to_civserver.assert_not_called()

    def test_resume_game_returns_false_without_civcom(self):
        """Verify failure handling when civcom is None"""
        result = self.session.resume_game(None)
        self.assertFalse(result)
        # is_paused should remain True since resume failed
        self.assertTrue(self.session.is_paused)

    def test_resume_game_uses_zero_timeout_if_none_stored(self):
        """Verify fallback to 0 when original_timeout is None (timeout=0 games)"""
        self.session.original_timeout = None
        self.session.resume_game(self.mock_civcom)

        # Last queued packet should be the timeout restore
        call_args = self.mock_civcom.queue_to_civserver.call_args[0][0]
        packet = json.loads(call_args)
        self.assertEqual(packet["message"], "/set timeout 0")

    def test_resume_game_calls_send_packets(self):
        """Verify send_packets_to_civserver is called after queueing"""
        self.session.resume_game(self.mock_civcom)
        self.mock_civcom.send_packets_to_civserver.assert_called_once()

    def test_resume_game_rejects_negative_timeout(self):
        """Verify negative timeout values are rejected and default is used"""
        self.session.original_timeout = -5  # Invalid negative value
        self.session.resume_game(self.mock_civcom)

        call_args = self.mock_civcom.queue_to_civserver.call_args[0][0]
        packet = json.loads(call_args)
        self.assertEqual(packet["message"], "/set timeout 60")  # Default

    def test_resume_game_rejects_oversized_timeout(self):
        """Verify oversized timeout values (>3600s) are rejected"""
        self.session.original_timeout = 99999  # Too large (>MAX_GAME_TIMEOUT)
        self.session.resume_game(self.mock_civcom)

        call_args = self.mock_civcom.queue_to_civserver.call_args[0][0]
        packet = json.loads(call_args)
        self.assertEqual(packet["message"], "/set timeout 60")  # Default

    def test_resume_game_rejects_non_integer_timeout(self):
        """Verify non-integer timeout values are rejected"""
        self.session.original_timeout = "45"  # String, not int
        self.session.resume_game(self.mock_civcom)

        call_args = self.mock_civcom.queue_to_civserver.call_args[0][0]
        packet = json.loads(call_args)
        self.assertEqual(packet["message"], "/set timeout 60")  # Default

    def test_resume_game_accepts_valid_timeout(self):
        """Verify valid timeout values within bounds are accepted"""
        self.session.original_timeout = 120  # Valid: 0 < 120 <= 3600
        self.session.resume_game(self.mock_civcom)

        call_args = self.mock_civcom.queue_to_civserver.call_args[0][0]
        packet = json.loads(call_args)
        self.assertEqual(packet["message"], "/set timeout 120")


class TestGameSessionPlayersLock(unittest.TestCase):
    """Tests for thread-safe player handler mutations"""

    def setUp(self):
        """Set up test fixtures"""
        self.session = GameSession(
            game_id="test-game-123",
            civserver_port=6001,
            min_players=2
        )

    def test_session_has_players_lock(self):
        """Verify GameSession has _players_lock attribute"""
        self.assertTrue(hasattr(self.session, '_players_lock'))

    def test_players_lock_is_threading_lock(self):
        """Verify _players_lock is a threading.Lock"""
        import threading
        self.assertIsInstance(self.session._players_lock, type(threading.Lock()))

    def test_players_lock_can_be_acquired(self):
        """Verify the lock can be acquired and released"""
        with self.session._players_lock:
            # Lock acquired - we can safely modify players dict
            self.session.players["test"] = Mock()

        # Lock released - verify we can acquire again
        acquired = self.session._players_lock.acquire(blocking=False)
        self.assertTrue(acquired)
        self.session._players_lock.release()


class TestPauseGameTimeoutValidation(unittest.TestCase):
    """Tests for timeout validation in pause_game"""

    def setUp(self):
        """Set up test fixtures"""
        self.session = GameSession(
            game_id="test-game-123",
            civserver_port=6001,
            min_players=2
        )
        self.mock_civcom = Mock()
        self.mock_civcom.queue_to_civserver = Mock()
        self.mock_civcom.send_packets_to_civserver = Mock()

    def test_pause_captures_valid_timeout(self):
        """Verify valid timeout from civcom is captured"""
        self.mock_civcom.game_timeout = 90
        self.session.pause_game(self.mock_civcom, "test")
        self.assertEqual(self.session.original_timeout, 90)

    def test_pause_rejects_negative_timeout(self):
        """Verify negative timeout falls back to default"""
        self.mock_civcom.game_timeout = -10
        self.session.pause_game(self.mock_civcom, "test")
        self.assertEqual(self.session.original_timeout, 60)  # DEFAULT_GAME_TIMEOUT

    def test_pause_rejects_oversized_timeout(self):
        """Verify timeout > MAX_GAME_TIMEOUT falls back to default"""
        self.mock_civcom.game_timeout = 5000  # > 3600
        self.session.pause_game(self.mock_civcom, "test")
        self.assertEqual(self.session.original_timeout, 60)  # DEFAULT_GAME_TIMEOUT

    def test_pause_preserves_zero_timeout(self):
        """Verify zero timeout is stored as-is (valid config for LLM games)"""
        self.mock_civcom.game_timeout = 0
        self.session.pause_game(self.mock_civcom, "test")
        self.assertEqual(self.session.original_timeout, 0)


class TestPauseAndSuspendPartner(unittest.TestCase):
    """Unit tests for LLMWSHandler._pause_and_suspend_partner()"""

    def setUp(self):
        """Set up test fixtures with mock handlers"""
        # Import here to avoid circular imports in test setup
        from llm_handler import LLMWSHandler

        # Create mock handlers
        self.mock_app = Mock()
        self.mock_app.ui_methods = {}
        self.mock_app.ui_modules = {}
        self.mock_request = Mock()

        self.handler = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler.agent_id = "agent-1"
        self.handler.game_id = "test-game-123"
        self.handler.civcom = Mock()
        self.handler.civcom.stopped = False
        self.handler.session_id = "session-1"

        # Create partner handler
        self.partner_handler = LLMWSHandler(self.mock_app, self.mock_request)
        self.partner_handler.agent_id = "agent-2"
        self.partner_handler.game_id = "test-game-123"
        self.partner_handler.civcom = Mock()
        self.partner_handler.civcom.stopped = False
        self.partner_handler.session_id = "session-2"
        self.partner_handler.close = Mock()

        # Create game session
        self.game_session = GameSession(
            game_id="test-game-123",
            civserver_port=6001,
            min_players=2
        )
        self.game_session.game_started = True
        self.game_session.players = {
            "agent-1": PlayerInfo(
                agent_id="agent-1",
                player_id=0,
                handler=self.handler
            ),
            "agent-2": PlayerInfo(
                agent_id="agent-2",
                player_id=1,
                handler=self.partner_handler
            )
        }

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    def test_pause_and_suspend_calls_pause_game(self, mock_sess_mgr, mock_game_mgr):
        """Verify pause_game is called on game session"""
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.game_session.pause_game = Mock(return_value=True)

        self.handler._pause_and_suspend_partner()

        self.game_session.pause_game.assert_called_once()

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    def test_pause_and_suspend_closes_partner_websocket(self, mock_sess_mgr, mock_game_mgr):
        """Verify partner WebSocket is closed with code 4001"""
        mock_game_mgr.sessions = {"test-game-123": self.game_session}

        self.handler._pause_and_suspend_partner()

        self.partner_handler.close.assert_called_once()
        call_kwargs = self.partner_handler.close.call_args[1]
        self.assertEqual(call_kwargs["code"], 4001)
        self.assertIn("Partner disconnected", call_kwargs["reason"])

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    def test_pause_and_suspend_skips_if_game_not_started(self, mock_sess_mgr, mock_game_mgr):
        """Verify no pause when game hasn't started yet"""
        self.game_session.game_started = False
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.game_session.pause_game = Mock()

        self.handler._pause_and_suspend_partner()

        self.game_session.pause_game.assert_not_called()

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    def test_pause_and_suspend_skips_if_no_game_session(self, mock_sess_mgr, mock_game_mgr):
        """Verify graceful handling when game session doesn't exist"""
        mock_game_mgr.sessions = {}  # No game session

        # Should not raise exception
        self.handler._pause_and_suspend_partner()

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    def test_pause_and_suspend_suspends_partner_session(self, mock_sess_mgr, mock_game_mgr):
        """Verify session_manager.suspend_session is called for partner"""
        mock_game_mgr.sessions = {"test-game-123": self.game_session}

        self.handler._pause_and_suspend_partner()

        # Verify suspend_session was called for partner
        mock_sess_mgr.suspend_session.assert_called_once()
        call_args = mock_sess_mgr.suspend_session.call_args[0]
        self.assertEqual(call_args[0], "session-2")  # Partner's session ID
        self.assertIn("partner_agent-1_disconnected", call_args[1])

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    def test_pause_and_suspend_skips_self(self, mock_sess_mgr, mock_game_mgr):
        """Verify the disconnecting agent doesn't close its own WebSocket"""
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.handler.close = Mock()  # Mock self's close method

        self.handler._pause_and_suspend_partner()

        # Self's close should NOT be called
        self.handler.close.assert_not_called()
        # Partner's close SHOULD be called
        self.partner_handler.close.assert_called_once()


class TestCheckAndResumeGame(unittest.TestCase):
    """Unit tests for LLMWSHandler._check_and_resume_game()"""

    def setUp(self):
        """Set up test fixtures"""
        from llm_handler import LLMWSHandler

        self.mock_app = Mock()
        self.mock_app.ui_methods = {}
        self.mock_app.ui_modules = {}
        self.mock_request = Mock()

        self.handler = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler.agent_id = "agent-1"
        self.handler.game_id = "test-game-123"
        self.handler.civcom = Mock()
        self.handler.civcom.stopped = False

        # Partner handler (fully connected)
        self.partner_handler = Mock()
        self.partner_handler.civcom = Mock()
        self.partner_handler.civcom.stopped = False

        # Game session (paused)
        self.game_session = GameSession(
            game_id="test-game-123",
            civserver_port=6001,
            min_players=2
        )
        self.game_session.is_paused = True
        self.game_session.original_timeout = 45
        self.game_session.players = {
            "agent-1": PlayerInfo(
                agent_id="agent-1",
                player_id=0,
                handler=self.handler
            ),
            "agent-2": PlayerInfo(
                agent_id="agent-2",
                player_id=1,
                handler=self.partner_handler
            )
        }

    @patch('llm_handler.game_session_manager')
    def test_check_resume_resumes_when_all_connected(self, mock_game_mgr):
        """Verify game resumes when all players reconnected"""
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.game_session.resume_game = Mock(return_value=True)

        self.handler._check_and_resume_game()

        self.game_session.resume_game.assert_called_once_with(self.handler.civcom)

    @patch('llm_handler.game_session_manager')
    def test_check_resume_waits_if_partner_missing_civcom(self, mock_game_mgr):
        """Verify game stays paused when partner has no civcom"""
        self.partner_handler.civcom = None
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.game_session.resume_game = Mock()

        self.handler._check_and_resume_game()

        self.game_session.resume_game.assert_not_called()

    @patch('llm_handler.game_session_manager')
    def test_check_resume_waits_if_partner_civcom_stopped(self, mock_game_mgr):
        """Verify game stays paused when partner's civcom is stopped"""
        self.partner_handler.civcom.stopped = True
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.game_session.resume_game = Mock()

        self.handler._check_and_resume_game()

        self.game_session.resume_game.assert_not_called()

    @patch('llm_handler.game_session_manager')
    def test_check_resume_waits_if_partner_missing_handler(self, mock_game_mgr):
        """Verify game stays paused when partner handler is None"""
        self.game_session.players["agent-2"].handler = None
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.game_session.resume_game = Mock()

        self.handler._check_and_resume_game()

        self.game_session.resume_game.assert_not_called()

    @patch('llm_handler.game_session_manager')
    def test_check_resume_skips_if_not_paused(self, mock_game_mgr):
        """Verify no-op when game is not paused"""
        self.game_session.is_paused = False
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.game_session.resume_game = Mock()

        self.handler._check_and_resume_game()

        self.game_session.resume_game.assert_not_called()

    @patch('llm_handler.game_session_manager')
    def test_check_resume_updates_handler_reference(self, mock_game_mgr):
        """Verify handler reference is updated after reconnection"""
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        # Simulate handler reference being stale (different object)
        old_handler = Mock()
        self.game_session.players["agent-1"].handler = old_handler
        self.game_session.resume_game = Mock(return_value=True)

        self.handler._check_and_resume_game()

        # Handler should be updated to self
        self.assertEqual(self.game_session.players["agent-1"].handler, self.handler)

    @patch('llm_handler.game_session_manager')
    def test_check_resume_skips_if_no_game_id(self, mock_game_mgr):
        """Verify graceful handling when handler has no game_id"""
        self.handler.game_id = None
        mock_game_mgr.sessions = {"test-game-123": self.game_session}
        self.game_session.resume_game = Mock()

        # Should not raise exception
        self.handler._check_and_resume_game()

        self.game_session.resume_game.assert_not_called()


class TestOnClosePortReleaseGuard(unittest.TestCase):
    """Unit tests for on_close() paused-port-release guard."""

    def setUp(self):
        """Set up test fixtures."""
        from llm_handler import LLMWSHandler

        self.mock_app = Mock()
        self.mock_app.ui_methods = {}
        self.mock_app.ui_modules = {}
        self.mock_request = Mock()

        self.handler = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler.agent_id = "agent-1"
        self.handler.player_id = 0
        self.handler.game_id = "test-game-123"
        self.handler.session_id = "session-1"
        self.handler.session_info = Mock()
        self.handler.session_info.civserver_port = 6001
        self.handler.civcom = Mock()
        self.handler.civcom.stopped = False
        self.handler.civcom.close_connection = Mock()
        # Keep test focused on port release decision, not partner pause mechanics.
        self.handler._pause_and_suspend_partner = Mock()

    def _build_game_session(self, is_paused: bool) -> GameSession:
        game_session = GameSession(
            game_id="test-game-123",
            civserver_port=6001,
            min_players=2
        )
        game_session.game_started = False
        game_session.is_paused = is_paused
        game_session.players = {
            "agent-1": PlayerInfo(
                agent_id="agent-1",
                player_id=0,
                handler=self.handler
            )
        }
        return game_session

    def test_on_close_skips_release_when_last_player_and_game_paused(self):
        """Last player disconnect should NOT release port while game is paused."""
        game_session = self._build_game_session(is_paused=True)

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom") as mock_stop_observer, \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-game-123": game_session}
            mock_session_mgr.suspend_session.return_value = False  # Force cleanup branch
            mock_ioloop = Mock()
            mock_ioloop_current.return_value = mock_ioloop

            self.handler.on_close()

            mock_ioloop.add_callback.assert_not_called()
            mock_stop_observer.assert_not_called()
            self.assertFalse(game_session._port_releasing)
            self.assertIsNone(game_session._port_releasing_since)
            self.assertEqual(len(game_session.players), 0)

    def test_on_close_releases_port_when_last_player_and_not_paused(self):
        """Last player disconnect should release port when game is not paused."""
        game_session = self._build_game_session(is_paused=False)

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom") as mock_stop_observer, \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-game-123": game_session}
            mock_session_mgr.suspend_session.return_value = False  # Force cleanup branch
            mock_ioloop = Mock()
            mock_ioloop_current.return_value = mock_ioloop

            self.handler.on_close()

            mock_stop_observer.assert_called_once_with("test-game-123")
            mock_ioloop.add_callback.assert_called_once()
            self.assertTrue(game_session._port_releasing)
            self.assertIsNotNone(game_session._port_releasing_since)
            self.assertEqual(len(game_session.players), 0)


class TestPauseResumeIntegration(unittest.TestCase):
    """Integration tests for the full pause/resume flow"""

    def setUp(self):
        """Set up test fixtures for integration testing"""
        self.game_session = GameSession(
            game_id="test-game-123",
            civserver_port=6001,
            min_players=2
        )
        self.game_session.game_started = True

        # Create mock civcom
        self.mock_civcom = Mock()
        self.mock_civcom.game_timeout = 60
        self.mock_civcom.queue_to_civserver = Mock()
        self.mock_civcom.send_packets_to_civserver = Mock()
        self.mock_civcom.stopped = False

    def test_full_pause_resume_cycle(self):
        """Test complete pause -> resume cycle with autotoggle"""
        # Initial state
        self.assertFalse(self.game_session.is_paused)
        self.assertIsNone(self.game_session.original_timeout)

        # Pause
        result = self.game_session.pause_game(self.mock_civcom, "agent_disconnected")
        self.assertTrue(result)
        self.assertTrue(self.game_session.is_paused)
        self.assertTrue(self.game_session.autotoggle_disabled)
        self.assertEqual(self.game_session.original_timeout, 60)

        # Verify pause packets (timeout 0 + autotoggle disabled)
        calls = self.mock_civcom.queue_to_civserver.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(calls[0][0][0])["message"], "/set timeout 0")
        self.assertEqual(json.loads(calls[1][0][0])["message"], "/set autotoggle disabled")

        # Resume
        result = self.game_session.resume_game(self.mock_civcom)
        self.assertTrue(result)
        self.assertFalse(self.game_session.is_paused)
        self.assertFalse(self.game_session.autotoggle_disabled)

        # Verify resume packets (autotoggle enabled + timeout restore)
        # Total calls: 2 (pause) + 2 (resume) = 4
        calls = self.mock_civcom.queue_to_civserver.call_args_list
        self.assertEqual(len(calls), 4)
        self.assertEqual(json.loads(calls[2][0][0])["message"], "/set autotoggle enabled")
        self.assertEqual(json.loads(calls[3][0][0])["message"], "/set timeout 60")

    def test_double_pause_is_idempotent(self):
        """Test that pausing twice doesn't send duplicate packets"""
        # First pause sends 2 packets (timeout + autotoggle)
        self.game_session.pause_game(self.mock_civcom, "first")
        self.assertEqual(self.mock_civcom.queue_to_civserver.call_count, 2)

        # Second pause should be no-op
        result = self.game_session.pause_game(self.mock_civcom, "second")
        self.assertFalse(result)
        self.assertEqual(self.mock_civcom.queue_to_civserver.call_count, 2)

    def test_double_resume_is_idempotent(self):
        """Test that resuming twice doesn't send duplicate packets"""
        # Pause first (sends 2 packets)
        self.game_session.pause_game(self.mock_civcom, "test")
        initial_call_count = self.mock_civcom.queue_to_civserver.call_count

        # First resume sends 2 packets (autotoggle enabled + timeout restore)
        self.game_session.resume_game(self.mock_civcom)
        self.assertEqual(
            self.mock_civcom.queue_to_civserver.call_count,
            initial_call_count + 2
        )

        # Second resume should be no-op
        result = self.game_session.resume_game(self.mock_civcom)
        self.assertFalse(result)
        self.assertEqual(
            self.mock_civcom.queue_to_civserver.call_count,
            initial_call_count + 2
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
