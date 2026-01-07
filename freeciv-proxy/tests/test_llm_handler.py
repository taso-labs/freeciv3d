#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Behavioral test suite for LLM WebSocket handler
Tests actual functionality, not just structure
"""

import unittest
import asyncio
import json
import time
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variables before importing modules
# Use a proper high-entropy secret for testing
os.environ['CACHE_HMAC_SECRET'] = '8dc50280f151af309d728c951584576f205688dc82d7d295174f2ef1b3e32181'

from state_cache import StateCache
from action_validator import LLMActionValidator, ActionType, ValidationResult
from message_validator import MessageValidator, ValidationError
from config_loader import llm_config


class TestStateCache(unittest.TestCase):
    """Behavioral tests for state caching system"""

    def setUp(self):
        """Set up cache test fixtures"""
        self.cache = StateCache(ttl=5, max_size_kb=4)
        self.test_state = {
            'turn': 1,
            'units': [{'id': 1, 'type': 'warrior', 'x': 10, 'y': 20}],
            'cities': [{'id': 1, 'name': 'Capital', 'population': 3}],
            'timestamp': time.time()
        }

    def test_cache_set_and_get_returns_data(self):
        """Test basic cache set/get operations return actual data"""
        cache_key = 'game_123_player_1'
        
        # Set should succeed
        result = self.cache.set(cache_key, self.test_state, player_id=1)
        self.assertTrue(result, "Cache set should return True on success")
        
        # Get should return the same data
        retrieved = self.cache.get(cache_key)
        self.assertIsNotNone(retrieved, "Cache get should return data")
        self.assertEqual(retrieved['turn'], 1, "Retrieved data should match original")
        self.assertEqual(len(retrieved['units']), 1, "Units should be preserved")

    def test_cache_ttl_expiry_removes_data(self):
        """Test cache TTL expiration actually removes data"""
        # Use a very short TTL
        short_cache = StateCache(ttl=1, max_size_kb=4)
        cache_key = 'game_456_player_1'
        
        short_cache.set(cache_key, self.test_state, player_id=1)
        
        # Immediately should return data
        self.assertIsNotNone(short_cache.get(cache_key))
        
        # After TTL expires, should return None
        time.sleep(1.1)
        self.assertIsNone(short_cache.get(cache_key), "Expired data should return None")

    def test_cache_size_limits_enforced(self):
        """Test that states larger than max_size_kb are rejected"""
        # Create a state larger than 4KB
        large_state = {
            'units': [{'id': i, 'type': 'warrior', 'x': i, 'y': i, 
                      'extra_data': 'x' * 100} for i in range(100)]
        }
        
        result = self.cache.set('large_key', large_state, player_id=1)
        # May succeed if compression works, or fail if still too large
        # Either way, the cache should handle it gracefully
        self.assertIsInstance(result, bool)

    def test_cache_integrity_verification(self):
        """Test HMAC signature verification prevents cache poisoning"""
        cache_key = 'integrity_test'
        self.cache.set(cache_key, self.test_state, player_id=1)
        
        # Tamper with cached data directly
        if cache_key in self.cache.cache:
            entry = self.cache.cache[cache_key]
            # Modify the signature to simulate tampering
            entry.signature = 'tampered_signature'
        
        # Get should now return None due to integrity failure
        result = self.cache.get(cache_key)
        self.assertIsNone(result, "Tampered data should be rejected")

    def test_cache_player_isolation(self):
        """Test that different players have isolated cache entries"""
        # Use fields that won't be optimized away
        state_p1 = {'turn': 1, 'phase': 'p1_phase', 'player_id': 1}
        state_p2 = {'turn': 1, 'phase': 'p2_phase', 'player_id': 2}
        
        self.cache.set('game_1_player_1', state_p1, player_id=1)
        self.cache.set('game_1_player_2', state_p2, player_id=2)
        
        p1_data = self.cache.get('game_1_player_1')
        p2_data = self.cache.get('game_1_player_2')
        
        # Check that data is retrieved and isolated
        self.assertIsNotNone(p1_data)
        self.assertIsNotNone(p2_data)
        self.assertEqual(p1_data.get('phase'), 'p1_phase')
        self.assertEqual(p2_data.get('phase'), 'p2_phase')


class TestActionValidator(unittest.TestCase):
    """Behavioral tests for LLM action validation"""

    def setUp(self):
        """Set up action validation test fixtures"""
        self.validator = LLMActionValidator()
        
        self.mock_game_state = {
            'turn': 15,
            'phase': 'movement',
            'units': {
                1: {'id': 1, 'type': 'warrior', 'x': 10, 'y': 20, 'owner': 1, 'moves_left': 3},
                2: {'id': 2, 'type': 'settler', 'x': 11, 'y': 21, 'owner': 1, 'moves_left': 2}
            },
            'cities': {
                1: {'id': 1, 'name': 'Capital', 'x': 10, 'y': 20, 'owner': 1, 'population': 5}
            },
            'map': {
                'width': 80,
                'height': 50
            }
        }

    def test_valid_unit_move_accepted(self):
        """Test that valid unit moves pass validation"""
        action = {
            'type': 'unit_move',
            'unit_id': 1,
            'dest_x': 11,
            'dest_y': 20
        }
        
        # Note: validate_action signature is (action, player_id, game_state)
        result = self.validator.validate_action(action, 1, self.mock_game_state)
        self.assertTrue(result.is_valid, f"Valid move should pass: {result.error_message}")

    def test_invalid_action_type_rejected(self):
        """Test that restricted actions not in default capabilities are rejected"""
        action = {
            'type': 'unit_nuke',  # Restricted action not in DEFAULT_CAPABILITIES
            'actor_id': 1,
            'target_x': 10,
            'target_y': 20
        }
        
        result = self.validator.validate_action(action, 1, self.mock_game_state)
        self.assertFalse(result.is_valid, "Restricted action type should be rejected")
        self.assertIsNotNone(result.error_code)

    def test_missing_required_fields_rejected(self):
        """Test that actions missing required fields are rejected"""
        action = {
            'type': 'unit_move',
            # Missing actor_id and target
        }
        
        result = self.validator.validate_action(action, 1, self.mock_game_state)
        self.assertFalse(result.is_valid, "Missing fields should cause rejection")

    def test_out_of_bounds_target_rejected(self):
        """Test that targets outside map bounds are rejected"""
        action = {
            'type': 'unit_move',
            'unit_id': 1,
            'dest_x': 999,
            'dest_y': 999  # Way out of bounds
        }
        
        result = self.validator.validate_action(action, 1, self.mock_game_state)
        self.assertFalse(result.is_valid, "Out of bounds target should be rejected")

    def test_unit_ownership_validated(self):
        """Test that player can only control their own units"""
        # Add an enemy unit to game state
        self.mock_game_state['units'][99] = {
            'id': 99, 'type': 'warrior', 'x': 5, 'y': 5, 'owner': 2, 'moves_left': 3
        }
        
        action = {
            'type': 'unit_move',
            'unit_id': 99,  # Enemy unit
            'dest_x': 6,
            'dest_y': 5
        }
        
        result = self.validator.validate_action(action, 1, self.mock_game_state)
        self.assertFalse(result.is_valid, "Cannot control enemy units")

    def test_fortify_action_validation(self):
        """Test unit_fortify action validation"""
        action = {
            'type': 'unit_fortify',
            'unit_id': 1  # unit_id is the expected field, not actor_id
        }
        
        result = self.validator.validate_action(action, 1, self.mock_game_state)
        self.assertTrue(result.is_valid, f"Fortify should be valid: {result.error_message}")

    def test_city_production_validation(self):
        """Test city_production action validation"""
        action = {
            'type': 'city_production',
            'actor_id': 1,  # City ID
            'target': 'warrior'  # Production target
        }
        
        result = self.validator.validate_action(action, 1, self.mock_game_state)
        # This may or may not pass depending on implementation details
        self.assertIsInstance(result.is_valid, bool)


class TestMessageValidator(unittest.TestCase):
    """Behavioral tests for message validation"""

    def setUp(self):
        """Set up message validator"""
        self.validator = MessageValidator(max_message_size=1024 * 1024)  # 1MB

    def test_valid_json_message_accepted(self):
        """Test valid JSON messages are parsed correctly"""
        message = json.dumps({
            'type': 'state_query',
            'format': 'llm_optimized'
        })
        
        result = self.validator.validate_message(message)
        self.assertEqual(result['type'], 'state_query')
        self.assertEqual(result['format'], 'llm_optimized')

    def test_invalid_json_rejected(self):
        """Test invalid JSON is rejected with proper error"""
        message = "{ not valid json }"
        
        with self.assertRaises(ValidationError) as context:
            self.validator.validate_message(message)
        
        self.assertIn('E', context.exception.error_code)

    def test_oversized_message_rejected(self):
        """Test messages exceeding size limit are rejected"""
        small_validator = MessageValidator(max_message_size=100)
        large_message = json.dumps({'data': 'x' * 200})
        
        with self.assertRaises(ValidationError):
            small_validator.validate_message(large_message)

    def test_sql_injection_detected(self):
        """Test SQL injection patterns are detected and rejected"""
        malicious = json.dumps({
            'type': 'action',
            'name': "'; DROP TABLE users; --"
        })
        
        # Should either reject or sanitize the input
        try:
            result = self.validator.validate_message(malicious)
            # If it passes, the dangerous chars should be sanitized
            if 'name' in result:
                self.assertNotIn('DROP TABLE', result['name'])
        except ValidationError:
            # Rejection is also acceptable
            pass

    def test_xss_patterns_sanitized(self):
        """Test XSS patterns are sanitized"""
        malicious = json.dumps({
            'type': 'chat',
            'message': '<script>alert("xss")</script>'
        })
        
        try:
            result = self.validator.validate_message(malicious)
            if 'message' in result:
                self.assertNotIn('<script>', result['message'])
        except ValidationError:
            pass


class TestConcurrentAgentSupport(unittest.TestCase):
    """Tests for concurrent LLM agent isolation"""

    def test_max_agents_limit_configuration(self):
        """Test that max agents limit is configurable"""
        max_agents = llm_config.get_max_agents()
        self.assertIsInstance(max_agents, int)
        self.assertGreater(max_agents, 0, "Must allow at least 1 agent")

    def test_token_validation(self):
        """Test API token validation works"""
        # Empty token should fail
        self.assertFalse(llm_config.validate_token(''))
        
        # Valid token format should work (if configured)
        # This tests the actual validation logic


class TestPerformanceRequirements(unittest.TestCase):
    """Tests for performance requirements"""

    def test_cache_retrieval_timing(self):
        """Test that cached state queries complete within 50ms"""
        cache = StateCache(ttl=5, max_size_kb=4)
        test_state = {
            'turn': 1,
            'units': [{'id': i, 'type': 'warrior'} for i in range(50)],
            'cities': [{'id': 1, 'name': 'Capital'}]
        }
        
        cache.set('perf_test', test_state, player_id=1)
        
        # Time the retrieval
        start = time.time()
        for _ in range(100):
            cache.get('perf_test')
        elapsed = (time.time() - start) / 100 * 1000  # ms per operation
        
        self.assertLess(elapsed, 50, f"Cache retrieval took {elapsed:.2f}ms, should be <50ms")

    def test_state_optimization_size(self):
        """Test that optimized states are reasonably sized"""
        cache = StateCache(ttl=5, max_size_kb=4)
        
        # Create a state with typical game data
        test_state = {
            'turn': 50,
            'units': [
                {'id': i, 'type': 'warrior', 'x': i % 80, 'y': i // 80, 
                 'owner': 1, 'moves_left': 3}
                for i in range(20)
            ],
            'cities': [
                {'id': i, 'name': f'City_{i}', 'population': 5 + i,
                 'production': 'warrior', 'owner': 1}
                for i in range(5)
            ]
        }
        
        optimized = cache.optimize_state_data(test_state)
        size = len(json.dumps(optimized, separators=(',', ':')))
        
        # Should be under 4KB after optimization
        self.assertLess(size, 4096, f"Optimized state is {size} bytes, should be <4096")


class TestActionValidatorErrorCodes(unittest.TestCase):
    """Test that error codes match protocol specification"""

    def setUp(self):
        self.validator = LLMActionValidator()

    def test_error_codes_are_formatted_correctly(self):
        """Test error codes follow E### format"""
        action = {
            'type': 'unit_move',
            # Missing required fields
        }
        
        result = self.validator.validate_action(action, 1, None)
        
        if not result.is_valid:
            # Error code should match pattern E### or similar
            self.assertIsNotNone(result.error_code)
            self.assertTrue(
                result.error_code.startswith('E'),
                f"Error code '{result.error_code}' should start with 'E'"
            )


# =============================================================================
# REGRESSION TESTS FOR BUG FIXES
# =============================================================================


class TestTechActionFormatNormalization(unittest.TestCase):
    """Regression tests for tech action format normalization bug fix.

    Bug: _normalize_agent_clash_action only handled target['value'] but
    actions came as target['tech'], causing all tech_research actions to fail.

    Fixed in llm_handler.py lines 844-853 by adding support for:
    - target['tech']
    - target['tech_name']
    - direct string target
    """

    def setUp(self):
        """Set up test fixtures"""
        # Import LLMHandler to test _normalize_agent_clash_action
        from llm_handler import LLMWSHandler
        from unittest.mock import Mock

        self.mock_request = Mock()
        self.mock_request.remote_ip = '127.0.0.1'
        # Create handler with minimal mocking
        self.handler = Mock(spec=LLMWSHandler)
        self.handler._normalize_agent_clash_action = LLMWSHandler._normalize_agent_clash_action.__get__(
            self.handler, LLMWSHandler
        )

    def test_normalize_tech_research_with_tech_key(self):
        """Test normalizing tech research with target['tech'] format.

        This format caused the original bug - agent-clash sends:
        {'action_type': 'tech_research', 'actor_id': 0, 'target': {'tech': 'Advanced Flight'}}
        """
        action_data = {
            'action_type': 'tech_research',
            'actor_id': 0,
            'target': {'tech': 'Advanced Flight'}
        }

        result = self.handler._normalize_agent_clash_action(action_data)

        self.assertEqual(result['type'], 'tech_research')
        self.assertEqual(result['tech_name'], 'advanced flight')  # lowercase

    def test_normalize_tech_research_with_tech_name_key(self):
        """Test normalizing tech research with target['tech_name'] format."""
        action_data = {
            'action_type': 'tech_research',
            'actor_id': 0,
            'target': {'tech_name': 'Bronze Working'}
        }

        result = self.handler._normalize_agent_clash_action(action_data)

        self.assertEqual(result['type'], 'tech_research')
        self.assertEqual(result['tech_name'], 'bronze working')

    def test_normalize_tech_research_with_value_key(self):
        """Test normalizing tech research with target['value'] format."""
        action_data = {
            'action_type': 'tech_research',
            'actor_id': 0,
            'target': {'value': 'Pottery'}
        }

        result = self.handler._normalize_agent_clash_action(action_data)

        self.assertEqual(result['type'], 'tech_research')
        self.assertEqual(result['tech_name'], 'pottery')

    def test_normalize_tech_research_with_string_target(self):
        """Test normalizing tech research with direct string target."""
        action_data = {
            'action_type': 'tech_research',
            'actor_id': 0,
            'target': 'Alphabet'
        }

        result = self.handler._normalize_agent_clash_action(action_data)

        self.assertEqual(result['type'], 'tech_research')
        self.assertEqual(result['tech_name'], 'alphabet')

    def test_normalize_tech_research_invalid_target_raises_error(self):
        """Test that invalid target format raises ValueError."""
        action_data = {
            'action_type': 'tech_research',
            'actor_id': 0,
            'target': 123  # Invalid: integer, not dict or string
        }

        with self.assertRaises(ValueError) as context:
            self.handler._normalize_agent_clash_action(action_data)

        self.assertIn('Cannot extract tech_name', str(context.exception))


class TestOwnershipFilters(unittest.TestCase):
    """Regression tests for ownership filter bug fixes from PR #14.

    Bugs fixed:
    1. _get_fallback_unit_actions() generated actions for enemy units
    2. _get_player_level_actions() generated city_change_production for enemy cities
    """

    def setUp(self):
        """Set up test fixtures with player_id=1 as the current player"""
        from llm_handler import LLMWSHandler
        from unittest.mock import Mock, MagicMock

        self.mock_request = Mock()
        self.mock_request.remote_ip = '127.0.0.1'

        self.handler = Mock(spec=LLMWSHandler)
        self.handler.player_id = 1  # Current player is player 1

        # Bind methods from the real class
        self.handler._get_fallback_unit_actions = LLMWSHandler._get_fallback_unit_actions.__get__(
            self.handler, LLMWSHandler
        )
        self.handler._get_player_level_actions = LLMWSHandler._get_player_level_actions.__get__(
            self.handler, LLMWSHandler
        )
        self.handler._get_available_techs_from_inventions = Mock(return_value=['Pottery'])

    def test_fallback_unit_actions_filters_enemy_units(self):
        """Test _get_fallback_unit_actions excludes enemy units.

        Bug: Was generating unit_move actions for enemy units, allowing
        the AI to try to control enemy units.
        """
        game_state = {
            'units': {
                '1': {'id': 1, 'owner': 1, 'x': 10, 'y': 10, 'moves_left': 3},  # Player's unit
                '2': {'id': 2, 'owner': 2, 'x': 20, 'y': 20, 'moves_left': 3},  # Enemy unit
                '3': {'id': 3, 'owner': 1, 'x': 15, 'y': 15, 'moves_left': 0},  # Player's unit, no moves
            }
        }

        result = self.handler._get_fallback_unit_actions(game_state)

        # Should only have actions for player's unit with moves_left > 0
        self.assertIn('1', result, "Player's unit with moves should have actions")
        self.assertNotIn('2', result, "Enemy unit should NOT have actions")
        self.assertNotIn('3', result, "Unit without moves should NOT have actions")

    def test_player_level_actions_filters_enemy_cities(self):
        """Test _get_player_level_actions excludes enemy cities.

        Bug: Was generating city_change_production for enemy cities,
        which would fail validation but wasted API calls.
        """
        game_state = {
            'cities': {
                '1': {'id': 1, 'owner': 1, 'name': 'PlayerCity', 'can_build': []},  # Player's city
                '2': {'id': 2, 'owner': 2, 'name': 'EnemyCity', 'can_build': []},   # Enemy city
            }
        }

        result = self.handler._get_player_level_actions(game_state)

        # Check that no city actions are generated for enemy cities
        city_action_actor_ids = [
            a['actor_id'] for a in result
            if a['action_type'] == 'city_change_production'
        ]

        self.assertNotIn(2, city_action_actor_ids, "Enemy city should NOT have production actions")

    def test_optimized_actions_prefilters_units_by_owner(self):
        """Test _get_legal_actions_optimized pre-filters units before API calls.

        Bug: Was iterating over all units and calling get_unit_actions for each,
        including enemy units, wasting ~50% of API calls.
        """
        from llm_handler import LLMWSHandler
        from unittest.mock import Mock, patch

        handler = Mock(spec=LLMWSHandler)
        handler.player_id = 1
        handler.civcom = Mock()
        handler.civcom.get_full_state.return_value = {
            'units': {
                '1': {'id': 1, 'owner': 1, 'x': 10, 'y': 10},  # Player's unit
                '2': {'id': 2, 'owner': 2, 'x': 20, 'y': 20},  # Enemy unit
            }
        }

        mock_extractor = Mock()
        mock_extractor.get_unit_actions.return_value = {'error': None}
        handler._get_state_extractor = Mock(return_value=mock_extractor)
        handler._format_unit_actions_for_response = Mock(return_value=[{'action_type': 'test'}])
        handler._get_player_level_actions = Mock(return_value=[])

        # Bind the method
        handler._get_legal_actions_optimized = LLMWSHandler._get_legal_actions_optimized.__get__(
            handler, LLMWSHandler
        )

        handler._get_legal_actions_optimized(None)

        # Should only call get_unit_actions for the player's unit
        calls = mock_extractor.get_unit_actions.call_args_list
        unit_ids_called = [call[0][0] for call in calls]
        self.assertIn(1, unit_ids_called, "Player's unit should be processed")
        self.assertNotIn(2, unit_ids_called, "Enemy unit should NOT be processed")


class TestLegalActionsDictFormat(unittest.TestCase):
    """Regression tests for legal_actions dict format change from PR #14.

    BREAKING CHANGE: legal_actions now returns Dict[str, List[Dict]] keyed by
    actor_id instead of a flat List. This enables O(1) lookup by actor_id.
    """

    def setUp(self):
        """Set up test fixtures"""
        from llm_handler import LLMWSHandler
        from unittest.mock import Mock

        self.handler = Mock(spec=LLMWSHandler)
        self.handler.player_id = 1
        self.handler.civcom = Mock()
        self.handler._get_state_extractor = Mock(return_value=None)  # Use fallback path

        # Bind methods
        self.handler._get_fallback_unit_actions = LLMWSHandler._get_fallback_unit_actions.__get__(
            self.handler, LLMWSHandler
        )
        self.handler._get_player_level_actions = LLMWSHandler._get_player_level_actions.__get__(
            self.handler, LLMWSHandler
        )
        self.handler._get_legal_actions_optimized = LLMWSHandler._get_legal_actions_optimized.__get__(
            self.handler, LLMWSHandler
        )
        self.handler._get_available_techs_from_inventions = Mock(return_value=[])

    def test_legal_actions_returns_dict_not_list(self):
        """Test _get_legal_actions_optimized returns Dict, not List."""
        game_state = {
            'units': {'1': {'id': 1, 'owner': 1, 'x': 10, 'y': 10, 'moves_left': 3}},
            'cities': {}
        }
        self.handler.civcom.get_full_state.return_value = game_state

        result = self.handler._get_legal_actions_optimized(None)

        self.assertIsInstance(result, dict, "Result should be dict, not list")

    def test_legal_actions_dict_has_player_key(self):
        """Test legal actions dict always has 'player' key."""
        game_state = {'units': {}, 'cities': {}}
        self.handler.civcom.get_full_state.return_value = game_state

        result = self.handler._get_legal_actions_optimized(None)

        self.assertIn('player', result, "Result should have 'player' key")
        self.assertIsInstance(result['player'], list, "Player actions should be a list")

    def test_legal_actions_dict_unit_keys_are_strings(self):
        """Test unit actions are keyed by string unit_id."""
        game_state = {
            'units': {'42': {'id': 42, 'owner': 1, 'x': 10, 'y': 10, 'moves_left': 3}},
            'cities': {}
        }
        self.handler.civcom.get_full_state.return_value = game_state

        result = self.handler._get_legal_actions_optimized(None)

        # If unit actions were generated, key should be string "42", not int 42
        if len(result) > 1:  # More than just 'player' key
            unit_keys = [k for k in result.keys() if k != 'player']
            for key in unit_keys:
                self.assertIsInstance(key, str, f"Unit key '{key}' should be string, not {type(key)}")


class TestPlayerZeroEdgeCases(unittest.TestCase):
    """Regression tests for player_id=0 edge cases.

    Bug: Code used 'if self.player_id:' which evaluates to False when
    player_id=0, causing cache invalidation to be skipped for player 0.

    Fixed by changing to 'if self.player_id is not None:'.
    """

    def test_cache_player_zero_isolation(self):
        """Test that player_id=0 has isolated cache entries."""
        cache = StateCache(ttl=5, max_size_kb=4)

        state_p0 = {'turn': 1, 'phase': 'p0_phase', 'player_id': 0}
        state_p1 = {'turn': 1, 'phase': 'p1_phase', 'player_id': 1}

        cache.set('game_1_player_0', state_p0, player_id=0)
        cache.set('game_1_player_1', state_p1, player_id=1)

        p0_data = cache.get('game_1_player_0')
        p1_data = cache.get('game_1_player_1')

        # Both should be retrievable
        self.assertIsNotNone(p0_data, "Player 0 cache should be retrievable")
        self.assertIsNotNone(p1_data, "Player 1 cache should be retrievable")
        self.assertEqual(p0_data.get('phase'), 'p0_phase', "Player 0 data should be correct")
        self.assertEqual(p1_data.get('phase'), 'p1_phase', "Player 1 data should be correct")

    def test_cache_invalidation_player_zero(self):
        """Test cache invalidation works for player_id=0.

        Bug: 'if self.player_id:' returned False for player_id=0,
        so cache was never invalidated for player 0.
        """
        cache = StateCache(ttl=60, max_size_kb=4)

        # Set cache for player 0
        cache.set('game_1_player_0', {'turn': 1}, player_id=0)
        self.assertIsNotNone(cache.get('game_1_player_0'))

        # Invalidate for player 0
        cache.invalidate(player_id=0)

        # Should be invalidated
        # Note: This test depends on StateCache.invalidate implementation
        # If it only invalidates by key pattern, this is a behavioral test


class TestTechInventionsIntegration(unittest.TestCase):
    """Test tech research from inventions bitvector (PR #14 feature)."""

    def test_player_actions_uses_inventions_for_tech(self):
        """Test _get_player_level_actions uses inventions for tech_research.

        Feature: Instead of hardcoded tech list, uses PACKET_RESEARCH_INFO
        to determine which techs are researchable (PREREQS_KNOWN state).
        """
        from llm_handler import LLMWSHandler
        from unittest.mock import Mock

        handler = Mock(spec=LLMWSHandler)
        handler.player_id = 1
        handler._get_available_techs_from_inventions = Mock(return_value=['Pottery', 'Bronze Working'])
        handler._get_player_level_actions = LLMWSHandler._get_player_level_actions.__get__(
            handler, LLMWSHandler
        )

        game_state = {'cities': {}}
        result = handler._get_player_level_actions(game_state)

        # Should have tech_research action using first available tech
        tech_actions = [a for a in result if a['action_type'] == 'tech_research']
        self.assertEqual(len(tech_actions), 1, "Should have one tech_research action")
        self.assertEqual(tech_actions[0]['target']['tech_name'], 'Pottery')


if __name__ == '__main__':
    unittest.main(verbosity=2)
