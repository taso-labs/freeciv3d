#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for observer_civcom module — dedicated global-observer CivCom.
"""

import json
import os
import sys
import asyncio
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variables before importing modules
os.environ['CACHE_HMAC_SECRET'] = '8dc50280f151af309d728c951584576f205688dc82d7d295174f2ef1b3e32181'

from observer_civcom import (
    ObserverStub,
    ObserverCivCom,
    OBSERVER_AGENT_ID,
    spawn_observer_civcom,
    stop_observer_civcom,
)
from packet_constants import PACKET_CHAT_MSG_REQ, PACKET_SERVER_JOIN_REQ


class TestObserverStub(unittest.TestCase):
    """Tests for ObserverStub — minimal civwebserver substitute."""

    def test_provides_loginpacket(self):
        """Stub must expose loginpacket attribute (CivCom reads it in run())."""
        packet = '{"pid": 4, "username": "test"}'
        stub = ObserverStub(packet)
        self.assertEqual(stub.loginpacket, packet)

    def test_write_message_noop(self):
        """write_message should not raise — observer discards forwarded packets."""
        stub = ObserverStub('{}')
        stub.write_message('some packet data')
        stub.write_message('another packet', binary=True)

    def test_has_expected_attributes(self):
        """Stub must have is_llm_agent and buffer_enabled for CivCom hasattr checks."""
        stub = ObserverStub('{}')
        self.assertFalse(stub.is_llm_agent)
        self.assertFalse(stub.buffer_enabled)


class TestObserverCivCom(unittest.TestCase):
    """Tests for ObserverCivCom subclass — /observe injection logic."""

    def _make_observer(self):
        """Create an ObserverCivCom with a stubbed civwebserver."""
        stub = ObserverStub('{"pid": 4}')
        observer = ObserverCivCom('obs_test_view_', 6001, 'obs_key', stub)
        return observer

    def test_observe_sent_after_handshake(self):
        """After handshake_complete is set, /observe should be queued."""
        observer = self._make_observer()
        observer.queue_to_civserver = Mock()

        # Simulate handshake completion (normally set by PACKET_SERVER_JOIN_REPLY handler)
        observer.handshake_complete.set()

        # Call parse_and_store_packet with a dummy packet —
        # the super() call processes it, then our override checks handshake_complete
        with patch.object(type(observer).__bases__[0], 'parse_and_store_packet'):
            observer.parse_and_store_packet('{"pid": 999}')

        # /observe should have been queued
        observer.queue_to_civserver.assert_called_once()
        queued = json.loads(observer.queue_to_civserver.call_args[0][0])
        self.assertEqual(queued['pid'], PACKET_CHAT_MSG_REQ)
        self.assertEqual(queued['message'], '/observe')

    def test_observe_sent_only_once(self):
        """/observe must not be sent more than once."""
        observer = self._make_observer()
        observer.queue_to_civserver = Mock()
        observer.handshake_complete.set()

        with patch.object(type(observer).__bases__[0], 'parse_and_store_packet'):
            observer.parse_and_store_packet('{"pid": 999}')
            observer.parse_and_store_packet('{"pid": 998}')
            observer.parse_and_store_packet('{"pid": 997}')

        self.assertEqual(observer.queue_to_civserver.call_count, 1)
        self.assertTrue(observer._observe_sent)

    def test_no_observe_before_handshake(self):
        """/observe must NOT be sent before handshake completes."""
        observer = self._make_observer()
        observer.queue_to_civserver = Mock()

        # handshake_complete is NOT set
        with patch.object(type(observer).__bases__[0], 'parse_and_store_packet'):
            observer.parse_and_store_packet('{"pid": 999}')

        observer.queue_to_civserver.assert_not_called()
        self.assertFalse(observer._observe_sent)


class TestSpawnAndStop(unittest.TestCase):
    """Tests for spawn_observer_civcom and stop_observer_civcom."""

    @patch('observer_civcom.ObserverCivCom')
    @patch('observer_civcom.civcom_registry')
    def test_spawn_registers_in_registry(self, mock_registry, MockObserverCivCom):
        """spawn_observer_civcom should register the observer with OBSERVER_AGENT_ID."""
        mock_instance = Mock()
        MockObserverCivCom.return_value = mock_instance

        result = spawn_observer_civcom('game-abcd-1234', 6001)

        # Should register with (game_id, "__observer__")
        mock_registry.register_game.assert_called_once_with(
            'game-abcd-1234', OBSERVER_AGENT_ID, mock_instance
        )
        # Thread should be started
        mock_instance.start.assert_called_once()
        self.assertEqual(result, mock_instance)

    @patch('observer_civcom.ObserverCivCom')
    @patch('observer_civcom.civcom_registry')
    def test_spawn_creates_correct_login_packet(self, mock_registry, MockObserverCivCom):
        """Login packet should use PACKET_SERVER_JOIN_REQ and observer username."""
        calls = []
        def capture_init(username, port, key, stub):
            calls.append({'username': username, 'port': port, 'stub': stub})
            return Mock()
        MockObserverCivCom.side_effect = capture_init

        spawn_observer_civcom('abcd1234-rest', 6002)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['username'], 'obs_abcd1234_view_')
        self.assertEqual(calls[0]['port'], 6002)

        # Verify login packet on stub
        stub = calls[0]['stub']
        packet = json.loads(stub.loginpacket)
        self.assertEqual(packet['pid'], PACKET_SERVER_JOIN_REQ)
        self.assertEqual(packet['username'], 'obs_abcd1234_view_')

    @patch('observer_civcom.civcom_registry')
    def test_stop_sets_stopped_and_unregisters(self, mock_registry):
        """stop_observer_civcom should stop the observer and unregister."""
        mock_observer = Mock()
        mock_registry.get_civcom.return_value = mock_observer

        stop_observer_civcom('game-xyz')

        mock_registry.get_civcom.assert_called_once_with('game-xyz', OBSERVER_AGENT_ID)
        self.assertTrue(mock_observer.stopped)
        mock_observer.close_connection.assert_called_once()
        mock_registry.unregister_game.assert_called_once_with('game-xyz', OBSERVER_AGENT_ID)

    @patch('observer_civcom.civcom_registry')
    def test_stop_noop_when_no_observer(self, mock_registry):
        """stop_observer_civcom should do nothing if no observer exists."""
        mock_registry.get_civcom.return_value = None

        stop_observer_civcom('game-xyz')

        mock_registry.unregister_game.assert_not_called()


class TestGlobalStateObserverPreference(unittest.TestCase):
    """Tests that _handle_global_state_query prefers observer CivCom."""

    def _run_async(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_uses_observer_when_alive(self):
        """When observer is alive and not stopped, use its state directly."""
        from llm_handler import LLMWSHandler

        handler = Mock(spec=LLMWSHandler)
        handler.agent_id = 'agent_p1'
        handler.is_llm_agent = True
        handler.game_id = 'test-game'

        # Handler's own civcom
        handler.civcom = Mock()
        handler.civcom.stopped = False

        # Observer mock — alive, not stopped
        observer = Mock()
        observer.stopped = False
        observer.is_alive.return_value = True
        observer.get_full_state_global.return_value = {
            'turn': 5, 'phase': 'movement',
            'units': {'100': {'id': 100, 'owner': 0}, '101': {'id': 101, 'owner': 1}},
            'cities': {'200': {'id': 200, 'owner': 0}, '201': {'id': 201, 'owner': 1}},
            'players': {
                '0': {'id': 0, 'gold': 30, 'name': 'Player0'},
                '1': {'id': 1, 'gold': 50, 'name': 'Player1'},
            },
            'techs': {'player0': ['Bronze Working'], 'player1': ['Alphabet']},
            'wonders': {},
            'spaceship': {},
        }

        handler._handle_global_state_query = LLMWSHandler._handle_global_state_query.__get__(
            handler, LLMWSHandler
        )

        with patch('llm_handler.civcom_registry') as mock_registry:
            mock_registry.get_civcom.return_value = observer
            self._run_async(handler._handle_global_state_query({
                'correlation_id': 'obs-test'
            }))

        # Observer's get_full_state_global should have been called
        observer.get_full_state_global.assert_called_once()
        # Handler's own civcom should NOT have been called
        handler.civcom.get_full_state_global.assert_not_called()

        response = json.loads(handler.write_message.call_args[0][0])
        self.assertEqual(response['type'], 'global_state_response')
        # Both players' units from observer
        self.assertIn('100', response['data']['units'])
        self.assertIn('101', response['data']['units'])
        # Correct gold from observer (no merge needed)
        self.assertEqual(response['data']['players']['0']['gold'], 30)
        self.assertEqual(response['data']['players']['1']['gold'], 50)

    def test_falls_back_without_observer(self):
        """When no observer exists, fall back to aggregation."""
        from llm_handler import LLMWSHandler

        handler = Mock(spec=LLMWSHandler)
        handler.agent_id = 'agent_p1'
        handler.is_llm_agent = True
        handler.game_id = 'test-game'

        handler.civcom = Mock()
        handler.civcom.stopped = False
        handler.civcom.player_id = 1
        handler.civcom.get_full_state_global.return_value = {
            'turn': 5, 'phase': 'movement',
            'units': {'101': {'id': 101, 'owner': 1}},
            'cities': {},
            'players': {'1': {'id': 1, 'gold': 50}},
            'techs': {},
            'wonders': {},
            'spaceship': {},
        }

        handler._handle_global_state_query = LLMWSHandler._handle_global_state_query.__get__(
            handler, LLMWSHandler
        )

        with patch('llm_handler.civcom_registry') as mock_registry:
            # No observer
            mock_registry.get_civcom.return_value = None
            mock_registry.get_all_for_game.return_value = {
                ('test-game', 'agent_p1'): handler.civcom,
            }
            self._run_async(handler._handle_global_state_query({}))

        # Handler's own civcom should have been used (aggregation path)
        handler.civcom.get_full_state_global.assert_called_once()

        response = json.loads(handler.write_message.call_args[0][0])
        self.assertEqual(response['type'], 'global_state_response')

    def test_falls_back_when_observer_stopped(self):
        """When observer is stopped, fall back to aggregation."""
        from llm_handler import LLMWSHandler

        handler = Mock(spec=LLMWSHandler)
        handler.agent_id = 'agent_p1'
        handler.is_llm_agent = True
        handler.game_id = 'test-game'

        handler.civcom = Mock()
        handler.civcom.stopped = False
        handler.civcom.get_full_state_global.return_value = {
            'turn': 3, 'phase': 'movement',
            'units': {}, 'cities': {}, 'players': {},
            'techs': {}, 'wonders': {}, 'spaceship': {},
        }

        # Observer exists but is stopped
        observer = Mock()
        observer.stopped = True

        handler._handle_global_state_query = LLMWSHandler._handle_global_state_query.__get__(
            handler, LLMWSHandler
        )

        with patch('llm_handler.civcom_registry') as mock_registry:
            mock_registry.get_civcom.return_value = observer
            mock_registry.get_all_for_game.return_value = {
                ('test-game', 'agent_p1'): handler.civcom,
            }
            self._run_async(handler._handle_global_state_query({}))

        # Observer should NOT be used
        observer.get_full_state_global.assert_not_called()
        # Aggregation path should be used
        handler.civcom.get_full_state_global.assert_called_once()


if __name__ == '__main__':
    unittest.main()
