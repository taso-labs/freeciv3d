#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unit Action Cache - Protocol v2.0 Server-Authoritative Action System

Caches available actions for units with probabilities and metadata from FreeCiv server.
Cache is keyed by (unit_id, turn) and invalidated on unit state changes.

Thread-safe in-memory cache with TTL and size limits.
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, List, Tuple
from collections import OrderedDict

logger = logging.getLogger("freeciv-proxy")


class UnitActionCache:
    """
    Thread-safe cache for unit action query results.
    
    Cache key: (unit_id, turn)
    Cache value: {
        'actions': [...],      # List of action dicts with probability metadata
        'queried_at': float,   # Timestamp
        'target_unit_id': int, # Query context
        'target_tile_id': int,
        'target_extra_id': int
    }
    """

    def __init__(self, max_entries: int = 10000, ttl_seconds: int = 300):
        """
        Initialize cache.
        
        Args:
            max_entries: Maximum number of cached entries (LRU eviction)
            ttl_seconds: Time-to-live for cache entries (default: 5 minutes)
        """
        self._cache: OrderedDict[Tuple[int, int], Dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        
        # Statistics
        self._stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'invalidations': 0,
            'evictions': 0
        }

    def get(self, unit_id: int, turn: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached actions for a unit at a specific turn.
        
        Args:
            unit_id: Unit ID
            turn: Game turn number
            
        Returns:
            Cached action data or None if not cached/expired
        """
        with self._lock:
            key = (unit_id, turn)
            
            if key not in self._cache:
                self._stats['misses'] += 1
                return None
            
            entry = self._cache[key]
            
            # Check TTL
            if time.time() - entry.get('queried_at', 0) > self._ttl_seconds:
                logger.debug(f"Cache expired for unit {unit_id} turn {turn}")
                del self._cache[key]
                self._stats['misses'] += 1
                return None
            
            # Move to end (LRU)
            self._cache.move_to_end(key)
            self._stats['hits'] += 1
            
            logger.debug(f"Cache hit for unit {unit_id} turn {turn}")
            return entry

    def set(self, unit_id: int, turn: int, actions_data: Dict[str, Any]) -> None:
        """
        Cache actions for a unit at a specific turn.
        
        Args:
            unit_id: Unit ID
            turn: Game turn number
            actions_data: Action data dict with 'actions', 'queried_at', target fields
        """
        with self._lock:
            key = (unit_id, turn)
            
            # LRU eviction if needed
            if key not in self._cache and len(self._cache) >= self._max_entries:
                evicted_key = next(iter(self._cache))
                del self._cache[evicted_key]
                self._stats['evictions'] += 1
                logger.debug(f"Evicted cache entry for unit {evicted_key[0]} turn {evicted_key[1]}")
            
            # Ensure timestamp is present
            if 'queried_at' not in actions_data:
                actions_data['queried_at'] = time.time()
            
            self._cache[key] = actions_data
            self._stats['sets'] += 1
            
            logger.debug(f"Cached {len(actions_data.get('actions', []))} actions for unit {unit_id} turn {turn}")

    def invalidate(self, unit_id: int, turn: Optional[int] = None) -> int:
        """
        Invalidate cached actions for a unit.
        
        Args:
            unit_id: Unit ID to invalidate
            turn: Specific turn to invalidate, or None to invalidate all turns
            
        Returns:
            Number of entries invalidated
        """
        with self._lock:
            if turn is not None:
                # Invalidate specific turn
                key = (unit_id, turn)
                if key in self._cache:
                    del self._cache[key]
                    self._stats['invalidations'] += 1
                    logger.debug(f"Invalidated cache for unit {unit_id} turn {turn}")
                    return 1
                return 0
            else:
                # Invalidate all turns for this unit
                keys_to_remove = [k for k in self._cache if k[0] == unit_id]
                for key in keys_to_remove:
                    del self._cache[key]
                
                count = len(keys_to_remove)
                if count > 0:
                    self._stats['invalidations'] += count
                    logger.debug(f"Invalidated {count} cache entries for unit {unit_id}")
                
                return count

    def invalidate_turn(self, turn: int) -> int:
        """
        Invalidate all cached entries for a specific turn (e.g., on turn change).
        
        Args:
            turn: Turn number to invalidate
            
        Returns:
            Number of entries invalidated
        """
        with self._lock:
            keys_to_remove = [k for k in self._cache if k[1] == turn]
            for key in keys_to_remove:
                del self._cache[key]
            
            count = len(keys_to_remove)
            if count > 0:
                self._stats['invalidations'] += count
                logger.debug(f"Invalidated {count} cache entries for turn {turn}")
            
            return count

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cleared {count} cache entries")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._stats['hits'] + self._stats['misses']
            hit_rate = (self._stats['hits'] / total_requests * 100) if total_requests > 0 else 0
            
            return {
                **self._stats,
                'total_requests': total_requests,
                'hit_rate_percent': round(hit_rate, 2),
                'current_entries': len(self._cache)
            }

    def get_size(self) -> int:
        """Get current number of cached entries."""
        with self._lock:
            return len(self._cache)


# Global singleton instance
_unit_action_cache: Optional[UnitActionCache] = None


def get_unit_action_cache() -> UnitActionCache:
    """Get or create the global unit action cache instance."""
    global _unit_action_cache
    if _unit_action_cache is None:
        _unit_action_cache = UnitActionCache()
        logger.info("Initialized global unit action cache")
    return _unit_action_cache


def invalidate_unit_actions(unit_id: int, turn: Optional[int] = None) -> int:
    """
    Convenience function to invalidate unit actions.
    Should be called when:
    - Unit moves
    - Unit attacks
    - Unit changes activity
    - Unit is loaded/unloaded from transport
    - Tech is researched (changes available actions)
    
    Args:
        unit_id: Unit ID to invalidate
        turn: Specific turn or None for all turns
        
    Returns:
        Number of entries invalidated
    """
    cache = get_unit_action_cache()
    return cache.invalidate(unit_id, turn)
