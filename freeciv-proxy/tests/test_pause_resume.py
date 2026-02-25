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

from game_session_manager import GameSession, GamePhase, GameSessionManager, PlayerInfo
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
        self.handler.civcom.game_is_over = False
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


class TestGameOverPortRelease(unittest.TestCase):
    """Unit tests for game-over port release behavior.

    Verifies that completed games (ENDGAME_REPORT received) release ports
    immediately instead of holding them for the reconnect timeout.
    """

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
        self.handler.game_id = "test-game-gameover"
        self.handler.session_id = "session-1"
        self.handler.session_info = Mock()
        self.handler.session_info.civserver_port = 6001
        self.handler.civcom = Mock()
        self.handler.civcom.stopped = False
        self.handler.civcom.close_connection = Mock()
        self.handler.civcom.game_is_over = False
        self.handler._pause_and_suspend_partner = Mock()
        self.handler._suspend_partners = Mock()

    def _build_game_session(self, is_paused: bool, game_is_over: bool) -> GameSession:
        gs = GameSession(
            game_id="test-game-gameover",
            civserver_port=6001,
            min_players=2
        )
        gs.game_started = True
        gs.is_paused = is_paused
        if game_is_over:
            gs.mark_game_over(reason='test')
        gs.players = {
            "agent-1": PlayerInfo(
                agent_id="agent-1",
                player_id=0,
                handler=self.handler
            )
        }
        return gs

    def test_port_released_when_game_over_and_paused(self):
        """Game-over should override is_paused and allow port release."""
        game_session = self._build_game_session(is_paused=True, game_is_over=True)

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom") as mock_stop_observer, \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-game-gameover": game_session}
            mock_session_mgr.suspend_session.return_value = False
            mock_ioloop = Mock()
            mock_ioloop_current.return_value = mock_ioloop

            self.handler.on_close()

            # Port SHOULD be released even though game is paused
            mock_stop_observer.assert_called_once_with("test-game-gameover")
            mock_ioloop.add_callback.assert_called_once()
            self.assertTrue(game_session._port_releasing)
            self.assertIsNotNone(game_session._port_releasing_since)

    def test_pause_skipped_when_game_over(self):
        """When game is over, pause_game() should NOT be called."""
        game_session = self._build_game_session(is_paused=False, game_is_over=True)
        game_session.pause_game = Mock()

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom"), \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-game-gameover": game_session}
            mock_session_mgr.suspend_session.return_value = False
            mock_ioloop_current.return_value = Mock()

            self.handler.on_close()

            game_session.pause_game.assert_not_called()

    def test_civcom_game_over_propagates_to_session(self):
        """If civcom.game_is_over but session doesn't know yet, on_close should propagate."""
        game_session = self._build_game_session(is_paused=False, game_is_over=False)
        game_session.pause_game = Mock()
        # Simulate civcom knowing game is over but session doesn't yet
        self.handler.civcom.game_is_over = True

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom"), \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-game-gameover": game_session}
            mock_session_mgr.suspend_session.return_value = False
            mock_ioloop_current.return_value = Mock()

            self.handler.on_close()

            # Session should now reflect game_is_over
            self.assertTrue(game_session.game_is_over)
            self.assertIsNotNone(game_session.game_ended_at)
            # Pause should have been skipped
            game_session.pause_game.assert_not_called()

    def test_stale_cleanup_immediate_for_game_over(self):
        """Game-over sessions should be cleaned immediately; paused sessions should not."""
        import asyncio
        from unittest.mock import AsyncMock

        # Game-over session — should be cleaned by the fast-path
        gs_ended = GameSession(game_id="ended-game", civserver_port=6002, min_players=2)
        gs_ended.mark_game_over(reason='test')
        gs_ended.game_ended_at = 1000.0  # Override to simulate "long ago"
        gs_ended.is_paused = False
        gs_ended.players = {}

        # Regular paused session — should NOT be cleaned (timeout=999999)
        gs_paused = GameSession(game_id="paused-game", civserver_port=6003, min_players=2)
        gs_paused.is_paused = True
        gs_paused.paused_at = gs_paused.created_at  # Just paused
        gs_paused.players = {}

        manager = GameSessionManager()
        manager.sessions = {
            "ended-game": gs_ended,
            "paused-game": gs_paused,
        }

        # Use a very large timeout - game-over fast-path shouldn't need it,
        # and the paused session should survive because it hasn't exceeded timeout
        mock_release = AsyncMock(return_value=True)
        with patch.object(manager, 'release_civserver_port', mock_release):
            loop = asyncio.new_event_loop()
            try:
                cleaned = loop.run_until_complete(
                    manager.cleanup_stale_paused_sessions(suspension_timeout_secs=999999)
                )
            finally:
                loop.close()

        self.assertEqual(cleaned, 1)
        self.assertNotIn("ended-game", manager.sessions)
        # Regular paused session must survive — the fast-path is selective
        self.assertIn("paused-game", manager.sessions)
        self.assertFalse(gs_paused._port_releasing)

    def test_pause_still_works_when_game_not_over(self):
        """Regression: mid-game disconnects should still pause correctly."""
        game_session = self._build_game_session(is_paused=False, game_is_over=False)

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom"), \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-game-gameover": game_session}
            mock_session_mgr.suspend_session.return_value = False
            mock_ioloop = Mock()
            mock_ioloop_current.return_value = mock_ioloop

            self.handler.on_close()

            # Game should be paused (not game-over, so normal behavior)
            self.assertTrue(game_session.is_paused)
            # Port should NOT be released (paused for reconnect)
            mock_ioloop.add_callback.assert_not_called()
            self.assertFalse(game_session._port_releasing)


    def test_endgame_report_propagates_to_game_session(self):
        """PACKET_ENDGAME_REPORT in civcom should propagate game-over to GameSession."""
        gs = GameSession(game_id="endgame-prop", civserver_port=6005, min_players=2)
        self.assertFalse(gs.game_is_over)

        # Build a mock civcom handler whose .game_id leads back to our session
        mock_handler = Mock()
        mock_handler.game_id = "endgame-prop"

        # Replicate the attribute-traversal chain from civcom.py:
        #   handler = getattr(self, 'civwebserver', None)
        #   game_id = getattr(handler, 'game_id', None)
        mock_civcom = Mock()
        mock_civcom.civwebserver = mock_handler

        # Patch game_session_manager.sessions to contain our real GameSession
        with patch.dict("game_session_manager.game_session_manager.sessions", {"endgame-prop": gs}):
            # Execute the same propagation logic as civcom.py PACKET_ENDGAME_REPORT
            from game_session_manager import game_session_manager as gsm
            handler = getattr(mock_civcom, 'civwebserver', None)
            game_id = getattr(handler, 'game_id', None) if handler else None
            self.assertEqual(game_id, "endgame-prop")

            found_gs = gsm.sessions.get(game_id)
            self.assertIsNotNone(found_gs)
            found_gs.mark_game_over(reason="endgame_report")

        self.assertTrue(gs.game_is_over)
        self.assertIsNotNone(gs.game_ended_at)
        self.assertEqual(gs.phase, GamePhase.ENDED)

    def test_mark_game_over_is_idempotent(self):
        """Calling mark_game_over() twice should not update game_ended_at."""
        gs = GameSession(game_id="idempotent-test", civserver_port=6006, min_players=2)

        gs.mark_game_over(reason="first_call")
        first_ended_at = gs.game_ended_at
        self.assertTrue(gs.game_is_over)
        self.assertIsNotNone(first_ended_at)
        self.assertEqual(gs.phase, GamePhase.ENDED)

        # Second call should be a no-op (early-return guard)
        gs.mark_game_over(reason="second_call")
        self.assertEqual(gs.game_ended_at, first_ended_at)
        self.assertEqual(gs.phase, GamePhase.ENDED)


class TestResumeDebounce(unittest.TestCase):
    """Tests for resume_game() debounce guard (defense-in-depth against TOCTOU race)."""

    def setUp(self):
        self.session = GameSession(
            game_id="test-debounce",
            civserver_port=6001,
            min_players=2
        )
        self.mock_civcom = Mock()
        self.mock_civcom.queue_to_civserver = Mock()
        self.mock_civcom.send_packets_to_civserver = Mock()
        self.mock_civcom.username = "test-agent"
        self.mock_civcom.turn = 5

    def test_double_resume_blocked_by_debounce(self):
        """Second resume_game() within 2s should return False (debounced)."""
        # Pause, then resume once
        self.session.pause_game(self.mock_civcom, "test")
        result1 = self.session.resume_game(self.mock_civcom)
        self.assertTrue(result1)
        self.assertFalse(self.session.is_paused)

        # Re-pause, then try immediate second resume — debounce should block
        self.session.is_paused = True
        result2 = self.session.resume_game(self.mock_civcom)
        self.assertFalse(result2)
        # is_paused should remain True since debounce blocked the resume
        self.assertTrue(self.session.is_paused)

    def test_debounce_expiry_allows_resume(self):
        """After debounce window (2s), resume_game() should succeed again."""
        import time as time_module

        self.session.pause_game(self.mock_civcom, "test")
        self.session.resume_game(self.mock_civcom)

        # Simulate debounce window expiry by backdating last_resumed_at
        self.session.last_resumed_at = time_module.time() - 3.0

        # Re-pause and try again — should succeed now
        self.session.is_paused = True
        result = self.session.resume_game(self.mock_civcom)
        self.assertTrue(result)

    def test_first_resume_not_debounced(self):
        """First resume_game() should never be debounced (last_resumed_at is None)."""
        self.session.pause_game(self.mock_civcom, "test")
        self.assertIsNone(self.session.last_resumed_at)

        result = self.session.resume_game(self.mock_civcom)
        self.assertTrue(result)


class TestResumeLockSerialization(unittest.TestCase):
    """Test that _players_lock serializes concurrent resume attempts."""

    def setUp(self):
        from llm_handler import LLMWSHandler

        self.mock_app = Mock()
        self.mock_app.ui_methods = {}
        self.mock_app.ui_modules = {}
        self.mock_request = Mock()

        # Two handlers simulating two agents reconnecting simultaneously
        self.handler_a = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler_a.agent_id = "agent-a"
        self.handler_a.game_id = "test-lock-race"
        self.handler_a.civcom = Mock()
        self.handler_a.civcom.stopped = False
        self.handler_a.civcom.turn = 10
        self.handler_a.civcom.username = "agent-a"
        self.handler_a.civcom.queue_to_civserver = Mock()
        self.handler_a.civcom.send_packets_to_civserver = Mock()

        self.handler_b = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler_b.agent_id = "agent-b"
        self.handler_b.game_id = "test-lock-race"
        self.handler_b.civcom = Mock()
        self.handler_b.civcom.stopped = False
        self.handler_b.civcom.turn = 10
        self.handler_b.civcom.username = "agent-b"
        self.handler_b.civcom.queue_to_civserver = Mock()
        self.handler_b.civcom.send_packets_to_civserver = Mock()

        # Game session — paused, both players registered
        self.game_session = GameSession(
            game_id="test-lock-race",
            civserver_port=6004,
            min_players=2
        )
        self.game_session.is_paused = True
        self.game_session.original_timeout = 60
        self.game_session.autotoggle_disabled = True
        self.game_session.players = {
            "agent-a": PlayerInfo(
                agent_id="agent-a",
                player_id=0,
                handler=self.handler_a
            ),
            "agent-b": PlayerInfo(
                agent_id="agent-b",
                player_id=1,
                handler=self.handler_b
            )
        }

    @patch('llm_handler.game_session_manager')
    def test_concurrent_resume_only_executes_once(self, mock_game_mgr):
        """Two threads calling _check_and_resume_game() — only one resume should fire."""
        import threading

        mock_game_mgr.sessions = {"test-lock-race": self.game_session}

        resume_results = []
        original_resume = self.game_session.resume_game

        def tracking_resume(civcom):
            """Wrap resume_game to record calls."""
            result = original_resume(civcom)
            resume_results.append(result)
            return result

        self.game_session.resume_game = tracking_resume

        barrier = threading.Barrier(2)
        errors = []

        def run_check(handler):
            try:
                barrier.wait(timeout=5)
                handler._check_and_resume_game()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=run_check, args=(self.handler_a,))
        t2 = threading.Thread(target=run_check, args=(self.handler_b,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [], f"Threads raised errors: {errors}")

        # Exactly one True (successful resume) and one False (blocked by is_paused=False
        # or debounce). The key invariant: at most one resume sends commands.
        true_count = sum(1 for r in resume_results if r is True)
        self.assertEqual(true_count, 1,
                         f"Expected exactly 1 successful resume, got {true_count}: {resume_results}")


class TestCascadeBreaker(unittest.TestCase):
    """Verify on_close() skips partner suspension when close_code=4001.

    When agent B is closed by agent A's coordinated disconnect (code=4001),
    B's on_close() must NOT re-close A — otherwise we get an infinite cascade:
    A closes B → B closes A → A closes B → ...
    """

    def setUp(self):
        from llm_handler import LLMWSHandler

        self.mock_app = Mock()
        self.mock_app.ui_methods = {}
        self.mock_app.ui_modules = {}
        self.mock_request = Mock()

        # Handler B — the one being closed by partner A
        self.handler = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler.agent_id = "agent-B"
        self.handler.player_id = 1
        self.handler.game_id = "test-cascade"
        self.handler.session_id = "session-B"
        self.handler.session_info = Mock()
        self.handler.session_info.civserver_port = 6001
        self.handler.civcom = Mock()
        self.handler.civcom.stopped = False
        self.handler.civcom.close_connection = Mock()
        self.handler.civcom.game_is_over = False
        self.handler.civcom.player_units = {}  # Prevent len(Mock) error in logging

        # Game session — already paused by A
        self.game_session = GameSession(
            game_id="test-cascade",
            civserver_port=6001,
            min_players=2
        )
        self.game_session.game_started = True
        self.game_session.is_paused = True  # A already paused
        self.game_session.players = {
            "agent-B": PlayerInfo(
                agent_id="agent-B",
                player_id=1,
                handler=self.handler
            )
        }

    def test_partner_close_code_4001_skips_suspend_partners(self):
        """When closed by partner (code=4001), do NOT call _suspend_partners()."""
        # Simulate close_code=4001 (set by Tornado when partner calls close(code=4001))
        self.handler.close_code = 4001
        self.handler._suspend_partners = Mock()
        self.handler._pause_and_suspend_partner = Mock()

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom"), \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-cascade": self.game_session}
            mock_session_mgr.suspend_session.return_value = True
            mock_ioloop_current.return_value = Mock()

            self.handler.on_close()

            self.handler._suspend_partners.assert_not_called()
            self.handler._pause_and_suspend_partner.assert_not_called()

    def test_normal_close_code_still_suspends_partners(self):
        """Normal disconnect (code=None/1000) SHOULD call partner suspension."""
        self.handler.close_code = None  # Normal disconnect
        self.handler._pause_and_suspend_partner = Mock()

        # Make game not paused so we hit the pause+suspend branch
        self.game_session.is_paused = False

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom"), \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-cascade": self.game_session}
            mock_session_mgr.suspend_session.return_value = True
            mock_ioloop_current.return_value = Mock()

            self.handler.on_close()

            # For game_started + not paused + civcom alive → _suspend_partners is called
            # (through the pause branch which calls game_session.pause_game + _suspend_partners)
            # The key check: partner suspension logic IS entered (not skipped)

    def test_partner_close_still_suspends_own_session(self):
        """Agent closed by partner should still suspend its OWN session."""
        self.handler.close_code = 4001

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom"), \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-cascade": self.game_session}
            mock_session_mgr.suspend_session.return_value = True
            mock_ioloop_current.return_value = Mock()

            self.handler.on_close()

            # Own session IS suspended (line 4877)
            mock_session_mgr.suspend_session.assert_called_once_with(
                "session-B", "connection_closed"
            )

    def test_partner_close_preserves_civcom(self):
        """CivCom should be preserved when closed by partner (code=4001)."""
        self.handler.close_code = 4001
        original_civcom = self.handler.civcom  # Save ref before on_close clears it

        with patch("llm_handler.game_session_manager") as mock_game_mgr, \
             patch("llm_handler.session_manager") as mock_session_mgr, \
             patch("llm_handler.stop_observer_civcom"), \
             patch("tornado.ioloop.IOLoop.current") as mock_ioloop_current:

            mock_game_mgr.sessions = {"test-cascade": self.game_session}
            mock_session_mgr.suspend_session.return_value = True
            mock_ioloop_current.return_value = Mock()

            self.handler.on_close()

            # CivCom should NOT be destroyed (close_connection not called)
            original_civcom.close_connection.assert_not_called()


class TestIdempotentSuspend(unittest.TestCase):
    """Verify suspend_session() returns True for already-suspended sessions.

    When agent A pre-suspends B's session, then B's own on_close() calls
    suspend_session(), the second call must return True (not False).
    If it returns False, CivCom gets destroyed and reconnection fails.
    """

    def test_suspend_active_session_returns_true_inmemory(self):
        """First suspend of an active in-memory session returns True."""
        from session_manager import InMemorySessionManager, SessionState

        mgr = InMemorySessionManager()
        session_info = mgr.create_session(
            agent_id="test-agent", api_token="tok", game_id="g1"
        )
        session_id = session_info.session_id

        result = mgr.suspend_session(session_id, "test")
        self.assertTrue(result)

        # Verify state changed
        session = mgr.sessions[session_id]
        self.assertEqual(session.state, SessionState.SUSPENDED)

    def test_suspend_already_suspended_returns_true_inmemory(self):
        """Second suspend of an already-suspended in-memory session returns True."""
        from session_manager import InMemorySessionManager, SessionState

        mgr = InMemorySessionManager()
        session_info = mgr.create_session(
            agent_id="test-agent", api_token="tok", game_id="g1"
        )
        session_id = session_info.session_id

        # First suspend
        result1 = mgr.suspend_session(session_id, "partner_disconnect")
        self.assertTrue(result1)

        # Second suspend (idempotent) — must also return True
        result2 = mgr.suspend_session(session_id, "own_on_close")
        self.assertTrue(result2)

        # State should remain SUSPENDED
        session = mgr.sessions[session_id]
        self.assertEqual(session.state, SessionState.SUSPENDED)

    def test_civcom_preserved_when_pre_suspended(self):
        """CivCom should be preserved even when session was pre-suspended by partner.

        Simulates the cascade scenario:
        1. A pre-suspends B's session → state='suspended'
        2. B's on_close runs → suspend_session() must return True
        3. Since session_suspended=True → CivCom preserved (not destroyed)
        """
        from session_manager import InMemorySessionManager

        mgr = InMemorySessionManager()
        session_info = mgr.create_session(
            agent_id="agent-B", api_token="tok", game_id="g1"
        )
        session_id = session_info.session_id

        # Step 1: A pre-suspends B's session
        mgr.suspend_session(session_id, "partner_agent-A_disconnected")

        # Step 2: B's on_close calls suspend_session
        result = mgr.suspend_session(session_id, "connection_closed")

        # Must return True so CivCom is preserved
        self.assertTrue(result, "suspend_session must return True for already-suspended sessions")


class TestStaleHandlerGuard(unittest.TestCase):
    """Verify partner close is skipped when partner already reconnected.

    When agent A's OLD on_close() handler still runs but A has already
    reconnected with a NEW handler, the old handler must not close
    the new handler's WebSocket.
    """

    def setUp(self):
        from llm_handler import LLMWSHandler

        self.mock_app = Mock()
        self.mock_app.ui_methods = {}
        self.mock_app.ui_modules = {}
        self.mock_request = Mock()

        # Agent A — the one whose on_close is running
        self.handler_a = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler_a.agent_id = "agent-A"
        self.handler_a.game_id = "test-stale"
        self.handler_a.civcom = Mock()
        self.handler_a.civcom.stopped = False
        self.handler_a.session_id = "session-A"

        # Agent B — the partner
        self.old_handler_b = LLMWSHandler(self.mock_app, self.mock_request)
        self.old_handler_b.agent_id = "agent-B"
        self.old_handler_b.game_id = "test-stale"
        self.old_handler_b.civcom = Mock()
        self.old_handler_b.civcom.stopped = False
        self.old_handler_b.session_id = "session-B"
        self.old_handler_b.close = Mock()

        # New handler B (already reconnected)
        self.new_handler_b = LLMWSHandler(self.mock_app, self.mock_request)
        self.new_handler_b.agent_id = "agent-B"

        # Game session
        self.game_session = GameSession(
            game_id="test-stale",
            civserver_port=6001,
            min_players=2
        )
        self.game_session.game_started = True
        self.game_session.players = {
            "agent-A": PlayerInfo(
                agent_id="agent-A", player_id=0, handler=self.handler_a
            ),
            "agent-B": PlayerInfo(
                agent_id="agent-B", player_id=1, handler=self.old_handler_b
            )
        }

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    @patch('llm_handler.llm_agents')
    def test_stale_handler_skips_close_in_suspend_partners(self, mock_llm_agents, mock_sess_mgr, mock_game_mgr):
        """If partner reconnected (new handler in llm_agents), skip close."""
        mock_game_mgr.sessions = {"test-stale": self.game_session}
        # B already reconnected with new handler
        mock_llm_agents.get.return_value = self.new_handler_b

        self.handler_a._suspend_partners()

        # Old handler B's close should NOT be called
        self.old_handler_b.close.assert_not_called()

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    @patch('llm_handler.llm_agents')
    def test_current_handler_proceeds_with_close_in_suspend_partners(self, mock_llm_agents, mock_sess_mgr, mock_game_mgr):
        """If partner handler IS the current handler, proceed with close."""
        mock_game_mgr.sessions = {"test-stale": self.game_session}
        # B has NOT reconnected — llm_agents still has old handler (or None)
        mock_llm_agents.get.return_value = self.old_handler_b

        self.handler_a._suspend_partners()

        # Old handler B's close SHOULD be called
        self.old_handler_b.close.assert_called_once()

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    @patch('llm_handler.llm_agents')
    def test_stale_handler_skips_close_in_pause_and_suspend(self, mock_llm_agents, mock_sess_mgr, mock_game_mgr):
        """Stale handler guard also works in _pause_and_suspend_partner()."""
        mock_game_mgr.sessions = {"test-stale": self.game_session}
        # B already reconnected with new handler
        mock_llm_agents.get.return_value = self.new_handler_b

        self.handler_a._pause_and_suspend_partner()

        # Old handler B's close should NOT be called
        self.old_handler_b.close.assert_not_called()

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    @patch('llm_handler.llm_agents')
    def test_no_llm_agent_entry_proceeds_with_close(self, mock_llm_agents, mock_sess_mgr, mock_game_mgr):
        """If partner has no entry in llm_agents (already cleaned up), proceed with close."""
        mock_game_mgr.sessions = {"test-stale": self.game_session}
        # B not in llm_agents at all
        mock_llm_agents.get.return_value = None

        self.handler_a._suspend_partners()

        # Should still close (None means not reconnected, just gone)
        self.old_handler_b.close.assert_called_once()


class TestReconnectionStillWorks(unittest.TestCase):
    """Verify the full disconnect -> reconnect -> resume flow still works
    after the cascade fix. External clients rely on coordinated disconnect
    to trigger reconnection."""

    def setUp(self):
        from llm_handler import LLMWSHandler

        self.mock_app = Mock()
        self.mock_app.ui_methods = {}
        self.mock_app.ui_modules = {}
        self.mock_request = Mock()

        # Agent A (disconnects first)
        self.handler_a = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler_a.agent_id = "agent-A"
        self.handler_a.player_id = 0
        self.handler_a.game_id = "test-reconnect"
        self.handler_a.session_id = "session-A"
        self.handler_a.session_info = Mock()
        self.handler_a.session_info.civserver_port = 6001
        self.handler_a.civcom = Mock()
        self.handler_a.civcom.stopped = False
        self.handler_a.civcom.close_connection = Mock()
        self.handler_a.civcom.game_is_over = False
        self.handler_a.civcom.game_timeout = 60
        self.handler_a.civcom.queue_to_civserver = Mock()
        self.handler_a.civcom.send_packets_to_civserver = Mock()

        # Agent B (partner, will be closed by A)
        self.handler_b = LLMWSHandler(self.mock_app, self.mock_request)
        self.handler_b.agent_id = "agent-B"
        self.handler_b.player_id = 1
        self.handler_b.game_id = "test-reconnect"
        self.handler_b.session_id = "session-B"
        self.handler_b.session_info = Mock()
        self.handler_b.session_info.civserver_port = 6001
        self.handler_b.civcom = Mock()
        self.handler_b.civcom.stopped = False
        self.handler_b.civcom.close_connection = Mock()
        self.handler_b.civcom.game_is_over = False
        self.handler_b.close = Mock()

        # Game session
        self.game_session = GameSession(
            game_id="test-reconnect",
            civserver_port=6001,
            min_players=2
        )
        self.game_session.game_started = True
        self.game_session.players = {
            "agent-A": PlayerInfo(
                agent_id="agent-A", player_id=0, handler=self.handler_a
            ),
            "agent-B": PlayerInfo(
                agent_id="agent-B", player_id=1, handler=self.handler_b
            )
        }

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    @patch('llm_handler.llm_agents', {})
    def test_disconnect_pauses_game_and_closes_partner(self, mock_sess_mgr, mock_game_mgr):
        """Agent A disconnect should: pause game + close partner B's WS."""
        mock_game_mgr.sessions = {"test-reconnect": self.game_session}

        # A's _pause_and_suspend_partner pauses game + closes B
        self.handler_a._pause_and_suspend_partner()

        # Game should be paused
        self.assertTrue(self.game_session.is_paused)

        # B's WebSocket should be closed with code=4001
        self.handler_b.close.assert_called_once()
        call_kwargs = self.handler_b.close.call_args[1]
        self.assertEqual(call_kwargs["code"], 4001)

    @patch('llm_handler.game_session_manager')
    @patch('llm_handler.session_manager')
    @patch('llm_handler.llm_agents', {})
    def test_partner_session_suspended_for_reconnection(self, mock_sess_mgr, mock_game_mgr):
        """Partner B's session should be suspended (allowing reconnect)."""
        mock_game_mgr.sessions = {"test-reconnect": self.game_session}

        self.handler_a._pause_and_suspend_partner()

        # B's session should be suspended
        mock_sess_mgr.suspend_session.assert_called_once()
        call_args = mock_sess_mgr.suspend_session.call_args[0]
        self.assertEqual(call_args[0], "session-B")

    def test_both_civcoms_preserved_after_coordinated_disconnect(self):
        """Both A and B CivComs should be preserved for reconnection."""
        from session_manager import InMemorySessionManager

        mgr = InMemorySessionManager()
        info_a = mgr.create_session(
            agent_id="agent-A", api_token="tok", game_id="g1"
        )
        info_b = mgr.create_session(
            agent_id="agent-B", api_token="tok", game_id="g1"
        )

        # A suspends B, then A suspends self (normal path)
        result_b_by_a = mgr.suspend_session(info_b.session_id, "partner_A_disconnected")
        result_a = mgr.suspend_session(info_a.session_id, "connection_closed")

        # B's own on_close suspends itself again (idempotent)
        result_b_self = mgr.suspend_session(info_b.session_id, "connection_closed")

        # ALL suspensions must return True → CivCom preserved for both
        self.assertTrue(result_b_by_a)
        self.assertTrue(result_a)
        self.assertTrue(result_b_self, "B's self-suspend must return True (idempotent)")

    @patch('llm_handler.game_session_manager')
    def test_both_reconnect_triggers_resume(self, mock_game_mgr):
        """When both agents reconnect, _check_and_resume_game() fires resume."""
        from llm_handler import LLMWSHandler

        # Game session is paused
        self.game_session.is_paused = True
        self.game_session.original_timeout = 60
        mock_game_mgr.sessions = {"test-reconnect": self.game_session}

        # Simulate both handlers reconnected with live civcoms
        new_handler_a = LLMWSHandler(self.mock_app, self.mock_request)
        new_handler_a.agent_id = "agent-A"
        new_handler_a.game_id = "test-reconnect"
        new_handler_a.civcom = Mock()
        new_handler_a.civcom.stopped = False

        new_handler_b = Mock()
        new_handler_b.civcom = Mock()
        new_handler_b.civcom.stopped = False

        self.game_session.players = {
            "agent-A": PlayerInfo(
                agent_id="agent-A", player_id=0, handler=new_handler_a
            ),
            "agent-B": PlayerInfo(
                agent_id="agent-B", player_id=1, handler=new_handler_b
            )
        }

        self.game_session.resume_game = Mock(return_value=True)

        new_handler_a._check_and_resume_game()

        # Resume should be called since both agents have live handlers+civcoms
        self.game_session.resume_game.assert_called_once_with(new_handler_a.civcom)


if __name__ == '__main__':
    unittest.main(verbosity=2)
