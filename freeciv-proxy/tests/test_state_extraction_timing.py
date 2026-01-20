"""
Tests for State Extraction Timing

Tests that state extraction properly waits for initial game packets
when units and cities are empty at game start (turn 0).
"""

import unittest
import sys
import os
import time
from unittest.mock import Mock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variable for cache - must be 64+ characters with good entropy
# Using a hex string generated from secrets for proper entropy
import secrets
os.environ['CACHE_HMAC_SECRET'] = secrets.token_hex(32)  # 64 character hex string

import logging
logging.disable(logging.CRITICAL)


class TestStateExtractionTiming(unittest.TestCase):
    """Test that state extraction returns immediately (no blocking)"""

    def test_extract_state_returns_immediately_even_with_empty_units(self):
        """extract_state should return immediately even if units are empty.

        The previous blocking/retry logic was removed because it froze Tornado's IOLoop.
        Now the caller (LLM agent) is responsible for handling empty states.
        """
        from state_extractor import StateExtractor, StateFormat

        # Create mock civcom that returns empty state
        civcom = Mock()
        call_count = [0]

        def mock_get_full_state(player_id):
            call_count[0] += 1
            return {
                'turn': 0,
                'phase': 'movement',
                'units': {},  # Empty units
                'cities': {},
                'players': {},
                'game': {'turn': 0, 'phase': 'movement', 'current_player': player_id}
            }

        civcom.get_full_state = mock_get_full_state
        civcom.game_turn = 0

        extractor = StateExtractor()
        with patch.object(extractor, '_get_civcom_for_game', return_value=civcom):
            start_time = time.time()
            state = extractor.extract_state('test_game', 0, StateFormat.FULL, agent_id='test_agent')
            elapsed = time.time() - start_time

            # Should only call once (no retry logic)
            self.assertEqual(call_count[0], 1, "Should call get_full_state exactly once")

            # Should return quickly (< 100ms since no blocking)
            self.assertLess(elapsed, 0.1, f"Should return quickly, took {elapsed}s")

            # Should return a valid state dict even if empty
            self.assertIsInstance(state, dict)

    def test_extract_state_with_units_present(self):
        """extract_state should return state when units are present"""
        civcom = Mock()
        call_count = [0]

        def mock_get_full_state(player_id):
            call_count[0] += 1
            return {
                'turn': 0,
                'phase': 'movement',
                'units': {'1': {'id': 1, 'owner': 0, 'type': 'Warrior', 'x': 10, 'y': 20}},
                'cities': {},
                'players': {},
                'game': {'turn': 0, 'phase': 'movement', 'current_player': player_id}
            }

        civcom.get_full_state = mock_get_full_state
        civcom.game_turn = 0

        from state_extractor import StateExtractor, StateFormat
        extractor = StateExtractor()
        with patch.object(extractor, '_get_civcom_for_game', return_value=civcom):
            start_time = time.time()
            state = extractor.extract_state('test_game', 0, StateFormat.FULL, agent_id='test_agent')
            elapsed = time.time() - start_time

            # Should only call once
            self.assertEqual(call_count[0], 1, "Should call get_full_state exactly once")

            # Should be fast
            self.assertLess(elapsed, 0.1, f"Should return quickly, took {elapsed}s")

            # Should return valid state with units
            self.assertIn('units', state)

    def test_extract_state_returns_empty_units_at_turn_5(self):
        """extract_state should return state with empty units at any turn"""
        civcom = Mock()
        call_count = [0]

        def mock_get_full_state(player_id):
            call_count[0] += 1
            return {
                'turn': 5,
                'phase': 'movement',
                'units': {},  # Empty units
                'cities': {},
                'players': {},
                'game': {'turn': 5, 'phase': 'movement', 'current_player': player_id}
            }

        civcom.get_full_state = mock_get_full_state
        civcom.game_turn = 5

        from state_extractor import StateExtractor, StateFormat
        extractor = StateExtractor()
        with patch.object(extractor, '_get_civcom_for_game', return_value=civcom):
            start_time = time.time()
            state = extractor.extract_state('test_game', 0, StateFormat.FULL, agent_id='test_agent')
            elapsed = time.time() - start_time
            
            # Should only call once (no retry after turn 0)
            self.assertEqual(call_count[0], 1, "Should not retry after turn 0")
            
            # Should be fast
            self.assertLess(elapsed, 0.1, f"Should not wait, took {elapsed}s")


if __name__ == '__main__':
    unittest.main()
