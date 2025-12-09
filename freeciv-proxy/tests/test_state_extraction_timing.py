"""
Tests for State Extraction Timing

Tests that state extraction properly waits for initial game packets
when units and cities are empty at game start (turn 0).
"""

import unittest
import sys
import os
import time
from unittest.mock import Mock, MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variable for cache - must be 64+ characters with good entropy
# Using a hex string generated from secrets for proper entropy
import secrets
os.environ['CACHE_HMAC_SECRET'] = secrets.token_hex(32)  # 64 character hex string

import logging
logging.disable(logging.CRITICAL)


class TestStateExtractionTiming(unittest.TestCase):
    """Test that state extraction waits for initial game packets"""

    def test_extract_state_waits_for_units_at_turn_0(self):
        """extract_state should retry when units are empty at turn 0"""
        from state_extractor import StateExtractor, StateFormat
        
        # Create mock civcom that returns empty state first, then populated
        civcom = Mock()
        call_count = [0]
        
        def mock_get_full_state(player_id):
            call_count[0] += 1
            if call_count[0] <= 2:  # First 2 calls return empty
                return {
                    'turn': 0,
                    'phase': 'movement',
                    'units': {},
                    'cities': {},
                    'players': {},
                    'game': {'turn': 0, 'phase': 'movement', 'current_player': player_id}
                }
            else:  # Subsequent calls have units
                return {
                    'turn': 0,
                    'phase': 'movement',
                    'units': {'1': {'id': 1, 'owner': 0, 'type': 'Warrior', 'x': 10, 'y': 20}},
                    'cities': {},
                    'players': {},
                    'game': {'turn': 0, 'phase': 'movement', 'current_player': 0}
                }
        
        civcom.get_full_state = mock_get_full_state
        
        extractor = StateExtractor()
        with patch.object(extractor, '_get_civcom_for_game', return_value=civcom):
            start_time = time.time()
            try:
                state = extractor.extract_state('test_game', 0, StateFormat.FULL, agent_id='test_agent')
            except Exception:
                # May fail due to mock data, but we just care about the wait behavior
                pass
            elapsed = time.time() - start_time
            
            # Should have retried (called get_full_state multiple times)
            self.assertGreater(call_count[0], 1, "Should retry getting state when empty at turn 0")
            
            # Should have waited (at least 200ms for 2 retries)
            self.assertGreater(elapsed, 0.15, f"Should have waited, took {elapsed}s")

    def test_extract_state_does_not_retry_when_units_present(self):
        """extract_state should not retry if units already present"""
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
        
        from state_extractor import StateExtractor, StateFormat
        extractor = StateExtractor()
        with patch.object(extractor, '_get_civcom_for_game', return_value=civcom):
            start_time = time.time()
            try:
                state = extractor.extract_state('test_game', 0, StateFormat.FULL, agent_id='test_agent')
            except Exception:
                pass
            elapsed = time.time() - start_time
            
            # Should only call once (no retries needed)
            self.assertEqual(call_count[0], 1, "Should not retry if units already present")
            
            # Should be fast
            self.assertLess(elapsed, 0.1, f"Should not wait, took {elapsed}s")

    def test_extract_state_does_not_retry_after_turn_0(self):
        """extract_state should not retry if turn > 0, even with empty units"""
        civcom = Mock()
        call_count = [0]
        
        def mock_get_full_state(player_id):
            call_count[0] += 1
            return {
                'turn': 5,  # Not turn 0
                'phase': 'movement',
                'units': {},  # Empty, but turn > 0 so no retry
                'cities': {},
                'players': {},
                'game': {'turn': 5, 'phase': 'movement', 'current_player': player_id}
            }
        
        civcom.get_full_state = mock_get_full_state
        
        from state_extractor import StateExtractor, StateFormat
        extractor = StateExtractor()
        with patch.object(extractor, '_get_civcom_for_game', return_value=civcom):
            start_time = time.time()
            try:
                state = extractor.extract_state('test_game', 0, StateFormat.FULL, agent_id='test_agent')
            except Exception:
                pass
            elapsed = time.time() - start_time
            
            # Should only call once (no retry after turn 0)
            self.assertEqual(call_count[0], 1, "Should not retry after turn 0")
            
            # Should be fast
            self.assertLess(elapsed, 0.1, f"Should not wait, took {elapsed}s")


if __name__ == '__main__':
    unittest.main()
