#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for unit action cache module (protocol v2.0)
Tests LRU eviction, TTL expiration, thread safety, and statistics tracking
"""

import pytest
import time
import threading
from unittest.mock import Mock

# Import the cache module
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from unit_action_cache import UnitActionCache


class TestUnitActionCache:
    """Test suite for UnitActionCache"""

    def test_cache_basic_set_get(self):
        """Test basic cache set and get operations"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=300)
        
        # Set cache entry
        actions = [
            {'action_type': 'move', 'probability': 200},
            {'action_type': 'attack', 'probability': 150}
        ]
        cache_entry = {
            'actions': actions,
            'timestamp': time.time(),
            'turn': 5
        }
        
        cache.set(unit_id=123, turn=5, actions_data=cache_entry)
        
        # Get cache entry
        result = cache.get(unit_id=123, turn=5)
        
        assert result is not None
        assert result['actions'] == actions
        assert result['turn'] == 5
        assert 'timestamp' in result

    def test_cache_miss(self):
        """Test cache miss returns None"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=300)
        
        result = cache.get(unit_id=999, turn=1)
        assert result is None

    def test_cache_turn_mismatch(self):
        """Test that cache misses on turn mismatch"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=300)
        
        cache_entry = {
            'actions': [],
            'timestamp': time.time(),
            'turn': 5
        }
        cache.set(unit_id=123, turn=5, actions_data=cache_entry)
        
        # Query with different turn
        result = cache.get(unit_id=123, turn=6)
        assert result is None

    def test_cache_ttl_expiration(self):
        """Test that entries expire after TTL"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=0.1)  # 100ms TTL
        
        cache_entry = {
            'actions': [],
            'timestamp': time.time(),
            'turn': 1
        }
        cache.set(unit_id=123, turn=1, actions_data=cache_entry)
        
        # Should hit within TTL
        result = cache.get(unit_id=123, turn=1)
        assert result is not None
        
        # Wait for expiration
        time.sleep(0.15)
        
        # Should miss after TTL
        result = cache.get(unit_id=123, turn=1)
        assert result is None

    def test_cache_lru_eviction(self):
        """Test LRU eviction when max_entries exceeded"""
        cache = UnitActionCache(max_entries=3, ttl_seconds=300)
        
        # Fill cache to capacity
        for unit_id in [1, 2, 3]:
            cache_entry = {
                'actions': [],
                'timestamp': time.time(),
                'turn': 1
            }
            cache.set(unit_id=unit_id, turn=1, actions_data=cache_entry)
        
        # All entries should be present
        assert cache.get(unit_id=1, turn=1) is not None
        assert cache.get(unit_id=2, turn=1) is not None
        assert cache.get(unit_id=3, turn=1) is not None
        
        # Add fourth entry - should evict unit_id=1 (least recently used)
        cache_entry = {
            'actions': [],
            'timestamp': time.time(),
            'turn': 1
        }
        cache.set(unit_id=4, turn=1, actions_data=cache_entry)
        
        # Unit 1 should be evicted
        assert cache.get(unit_id=1, turn=1) is None
        assert cache.get(unit_id=2, turn=1) is not None
        assert cache.get(unit_id=3, turn=1) is not None
        assert cache.get(unit_id=4, turn=1) is not None

    def test_cache_lru_access_order(self):
        """Test that accessing entries updates LRU order"""
        cache = UnitActionCache(max_entries=3, ttl_seconds=300)
        
        # Fill cache
        for unit_id in [1, 2, 3]:
            cache_entry = {
                'actions': [],
                'timestamp': time.time(),
                'turn': 1
            }
            cache.set(unit_id=unit_id, turn=1, actions_data=cache_entry)
        
        # Access unit 1 to make it recently used
        cache.get(unit_id=1, turn=1)
        
        # Add fourth entry - should evict unit_id=2 (now least recently used)
        cache_entry = {
            'actions': [],
            'timestamp': time.time(),
            'turn': 1
        }
        cache.set(unit_id=4, turn=1, actions_data=cache_entry)
        
        # Unit 2 should be evicted, unit 1 should remain
        assert cache.get(unit_id=1, turn=1) is not None
        assert cache.get(unit_id=2, turn=1) is None
        assert cache.get(unit_id=3, turn=1) is not None
        assert cache.get(unit_id=4, turn=1) is not None

    def test_cache_invalidate(self):
        """Test cache invalidation for specific unit"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=300)
        
        cache_entry = {
            'actions': [],
            'timestamp': time.time(),
            'turn': 1
        }
        cache.set(unit_id=123, turn=1, actions_data=cache_entry)
        
        assert cache.get(unit_id=123, turn=1) is not None
        
        # Invalidate
        cache.invalidate(unit_id=123)
        
        # Should be gone
        assert cache.get(unit_id=123, turn=1) is None

    def test_cache_clear(self):
        """Test clearing entire cache"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=300)
        
        # Add multiple entries
        for unit_id in [1, 2, 3]:
            cache_entry = {
                'actions': [],
                'timestamp': time.time(),
                'turn': 1
            }
            cache.set(unit_id=unit_id, turn=1, actions_data=cache_entry)
        
        # Clear cache
        cache.clear()
        
        # All should be gone
        assert cache.get(unit_id=1, turn=1) is None
        assert cache.get(unit_id=2, turn=1) is None
        assert cache.get(unit_id=3, turn=1) is None

    def test_cache_statistics(self):
        """Test cache statistics tracking"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=0.1)
        
        cache_entry = {
            'actions': [],
            'timestamp': time.time(),
            'turn': 1
        }
        cache.set(unit_id=123, turn=1, actions_data=cache_entry)
        
        # Hit
        cache.get(unit_id=123, turn=1)
        
        # Miss
        cache.get(unit_id=999, turn=1)
        
        # Expire and access
        time.sleep(0.15)
        cache.get(unit_id=123, turn=1)
        
        stats = cache.get_stats()
        assert stats['hits'] == 1
        assert stats['misses'] == 2  # 999 not found + 123 expired
        assert stats['current_entries'] == 0  # Expired entry cleaned up

    def test_cache_thread_safety(self):
        """Test thread-safe concurrent access"""
        cache = UnitActionCache(max_entries=100, ttl_seconds=300)
        errors = []
        
        def worker(worker_id):
            try:
                for i in range(50):
                    unit_id = (worker_id * 100) + i
                    cache_entry = {
                        'actions': [{'action_type': 'move', 'probability': 200}],
                        'timestamp': time.time(),
                        'turn': 1
                    }
                    cache.set(unit_id=unit_id, turn=1, actions_data=cache_entry)
                    
                    result = cache.get(unit_id=unit_id, turn=1)
                    assert result is not None
                    assert result['actions'][0]['action_type'] == 'move'
            except Exception as e:
                errors.append(e)
        
        # Run multiple threads concurrently
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # No errors should occur
        assert len(errors) == 0

    def test_cache_eviction_count(self):
        """Test eviction statistics"""
        cache = UnitActionCache(max_entries=2, ttl_seconds=300)
        
        # Add 3 entries to trigger eviction
        for unit_id in [1, 2, 3]:
            cache_entry = {
                'actions': [],
                'timestamp': time.time(),
                'turn': 1
            }
            cache.set(unit_id=unit_id, turn=1, actions_data=cache_entry)
        
        stats = cache.get_stats()
        assert stats['evictions'] == 1

    def test_cache_empty_actions(self):
        """Test caching empty actions list"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=300)
        
        cache_entry = {
            'actions': [],
            'timestamp': time.time(),
            'turn': 1
        }
        cache.set(unit_id=123, turn=1, actions_data=cache_entry)
        
        result = cache.get(unit_id=123, turn=1)
        assert result is not None
        assert result['actions'] == []

    def test_cache_complex_actions(self):
        """Test caching complex action structures"""
        cache = UnitActionCache(max_entries=10, ttl_seconds=300)
        
        complex_actions = [
            {
                'action_type': 'attack',
                'probability': 150,
                'target_unit_id': 456,
                'target_tile_id': 789,
                'metadata': {'damage': 25, 'defense': 10}
            },
            {
                'action_type': 'fortify',
                'probability': 200,
                'target_unit_id': None,
                'target_tile_id': None
            }
        ]
        
        cache_entry = {
            'actions': complex_actions,
            'timestamp': time.time(),
            'turn': 5
        }
        cache.set(unit_id=123, turn=5, actions_data=cache_entry)
        
        result = cache.get(unit_id=123, turn=5)
        assert result is not None
        assert len(result['actions']) == 2
        assert result['actions'][0]['metadata']['damage'] == 25
