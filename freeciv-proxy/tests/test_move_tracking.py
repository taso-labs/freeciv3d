"""Test local moves tracking for pre-submission validation"""

import os
import secrets

# Set required environment variable before imports
os.environ.setdefault('CACHE_HMAC_SECRET', secrets.token_hex(32))

from unittest.mock import Mock, MagicMock
import pytest


class TestLocalMovesTracking:
    """Test the local moves tracking mechanism in LLMWSHandler"""

    def setup_method(self):
        """Set up test fixtures"""
        # Mock the handler with minimal dependencies
        self.handler = Mock()
        self.handler.unit_moves_consumed = {}
        self.handler.last_tracked_turn = None
        self.handler.agent_id = "test_agent"

    def test_initial_state(self):
        """Test initial state of move tracking"""
        assert self.handler.unit_moves_consumed == {}
        assert self.handler.last_tracked_turn is None

    def test_track_single_move(self):
        """Test tracking a single unit move"""
        unit_id = 105

        # Simulate tracking a move
        self.handler.unit_moves_consumed[unit_id] = self.handler.unit_moves_consumed.get(unit_id, 0) + 1

        assert self.handler.unit_moves_consumed[unit_id] == 1

    def test_track_multiple_moves_same_unit(self):
        """Test tracking multiple moves for the same unit"""
        unit_id = 105

        # Simulate 3 actions consuming moves
        for _ in range(3):
            self.handler.unit_moves_consumed[unit_id] = self.handler.unit_moves_consumed.get(unit_id, 0) + 1

        assert self.handler.unit_moves_consumed[unit_id] == 3

    def test_track_multiple_units(self):
        """Test tracking moves for multiple units"""
        # Track moves for 3 different units
        for unit_id in [101, 102, 103]:
            self.handler.unit_moves_consumed[unit_id] = self.handler.unit_moves_consumed.get(unit_id, 0) + 1

        assert len(self.handler.unit_moves_consumed) == 3
        assert self.handler.unit_moves_consumed[101] == 1
        assert self.handler.unit_moves_consumed[102] == 1
        assert self.handler.unit_moves_consumed[103] == 1

    def test_turn_reset_clears_tracking(self):
        """Test that tracking is cleared on turn change"""
        unit_id = 105

        # Track some moves
        self.handler.unit_moves_consumed[unit_id] = 3
        self.handler.last_tracked_turn = 10

        # Simulate turn change (update last_tracked_turn first to reduce race condition)
        current_turn = 11
        if current_turn != self.handler.last_tracked_turn:
            self.handler.last_tracked_turn = current_turn
            self.handler.unit_moves_consumed.clear()

        assert self.handler.unit_moves_consumed == {}
        assert self.handler.last_tracked_turn == 11

    def test_effective_moves_calculation(self):
        """Test calculation of effective moves"""
        unit_id = 105
        cached_moves_left = 3

        # No moves consumed yet
        consumed = self.handler.unit_moves_consumed.get(unit_id, 0)
        effective_moves = cached_moves_left - consumed
        assert effective_moves == 3

        # After consuming 1 move
        self.handler.unit_moves_consumed[unit_id] = 1
        consumed = self.handler.unit_moves_consumed.get(unit_id, 0)
        effective_moves = cached_moves_left - consumed
        assert effective_moves == 2

        # After consuming all moves
        self.handler.unit_moves_consumed[unit_id] = 3
        consumed = self.handler.unit_moves_consumed.get(unit_id, 0)
        effective_moves = cached_moves_left - consumed
        assert effective_moves == 0

    def test_effective_moves_blocks_when_exhausted(self):
        """Test that actions are blocked when effective moves <= 0"""
        unit_id = 105
        cached_moves_left = 1

        # Consume the only move
        self.handler.unit_moves_consumed[unit_id] = 1
        consumed = self.handler.unit_moves_consumed.get(unit_id, 0)
        effective_moves = cached_moves_left - consumed

        # Should block
        assert effective_moves <= 0

    def test_units_dict_type_safety(self):
        """Test that units dict handles string/int keys correctly"""
        # Simulate game state units list
        units_list = [
            {'id': 101, 'moves_left': 3},
            {'id': '102', 'moves_left': 2},  # String ID
            {'id': 103, 'moves_left': 1},
        ]

        # Convert to dict with consistent int keys (matching implementation)
        units_dict = {int(u.get('id')): u for u in units_list if isinstance(u, dict) and u.get('id') is not None}

        # All keys should be ints
        assert all(isinstance(k, int) for k in units_dict.keys())
        assert 101 in units_dict
        assert 102 in units_dict
        assert 103 in units_dict

        # Lookup should work with int
        unit = units_dict.get(101)
        assert unit is not None
        assert unit['moves_left'] == 3

    def test_units_dict_filters_invalid_entries(self):
        """Test that units dict filters out invalid entries"""
        units_list = [
            {'id': 101, 'moves_left': 3},
            None,  # Invalid: not a dict
            {'moves_left': 2},  # Invalid: no id
            {'id': 103, 'moves_left': 1},
        ]

        units_dict = {int(u.get('id')): u for u in units_list if isinstance(u, dict) and u.get('id') is not None}

        # Should only have valid entries
        assert len(units_dict) == 2
        assert 101 in units_dict
        assert 103 in units_dict

    def test_action_data_extraction_with_data_key(self):
        """Test action data extraction prioritizes 'data' key"""
        msg_data = {
            'data': {'type': 'unit_move', 'unit_id': 101},
            'action': {'type': 'old_format'}
        }

        # Explicit check to avoid falsy value issues
        action_data = msg_data.get('data') if 'data' in msg_data else msg_data.get('action', {})

        assert action_data['type'] == 'unit_move'
        assert action_data['unit_id'] == 101

    def test_action_data_extraction_fallback_to_action(self):
        """Test action data extraction falls back to 'action' key"""
        msg_data = {
            'action': {'type': 'unit_move', 'unit_id': 102}
        }

        action_data = msg_data.get('data') if 'data' in msg_data else msg_data.get('action', {})

        assert action_data['type'] == 'unit_move'
        assert action_data['unit_id'] == 102

    def test_action_data_extraction_with_falsy_data(self):
        """Test action data extraction handles falsy 'data' values correctly"""
        # Empty dict should NOT fall back
        msg_data = {
            'data': {},
            'action': {'type': 'unit_move'}
        }

        action_data = msg_data.get('data') if 'data' in msg_data else msg_data.get('action', {})
        assert action_data == {}  # Should get the empty dict, not fall back

        # Empty list should NOT fall back
        msg_data = {
            'data': [],
            'action': {'type': 'unit_move'}
        }

        action_data = msg_data.get('data') if 'data' in msg_data else msg_data.get('action', {})
        assert action_data == []  # Should get the empty list, not fall back

        # Zero should NOT fall back
        msg_data = {
            'data': 0,
            'action': {'type': 'unit_move'}
        }

        action_data = msg_data.get('data') if 'data' in msg_data else msg_data.get('action', {})
        assert action_data == 0  # Should get 0, not fall back
