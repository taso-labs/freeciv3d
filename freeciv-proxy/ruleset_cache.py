#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RULESET Packet Caching for FreeCiv Spectator Mode

This module provides in-memory caching of immutable RULESET packets that define
game rules, unit types, terrain types, and other constants. These packets are
sent once at game start and never change during gameplay.

Spectators need these packets to initialize client-side constants like EXTRA_MINE,
unit_types[], terrain definitions, etc. Without them, the client has undefined
references causing thousands of console errors and rendering failures.
"""

import time
import json
import logging
import threading
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from collections import OrderedDict

logger = logging.getLogger("freeciv-proxy")

# Game ID validation pattern: alphanumeric, underscore, dash, max 64 chars
# Prevents cache poisoning via malicious game_id values
GAME_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')

# Maximum packet size to prevent memory exhaustion (10MB per packet)
MAX_PACKET_SIZE_BYTES = 10 * 1024 * 1024

# RULESET packet ID ranges from packet_constants.py
# These packets define immutable game rules and are sent once at game start
RULESET_PIDS = {
    # Core ruleset packets
    9,    # PACKET_RULESET_TECH_CLASS
    20,   # PACKET_RULESET_IMPR_FLAG
    140,  # PACKET_RULESET_UNIT
    141,  # PACKET_RULESET_GAME
    142,  # PACKET_RULESET_SPECIALIST
    143,  # PACKET_RULESET_GOVERNMENT_RULER_TITLE
    144,  # PACKET_RULESET_TECH
    145,  # PACKET_RULESET_GOVERNMENT
    146,  # PACKET_RULESET_TERRAIN_CONTROL
    147,  # PACKET_RULESET_NATION_GROUPS
    148,  # PACKET_RULESET_NATION
    149,  # PACKET_RULESET_CITY
    150,  # PACKET_RULESET_BUILDING
    151,  # PACKET_RULESET_TERRAIN
    152,  # PACKET_RULESET_UNIT_CLASS
    153,  # PACKET_RULESET_BASE
    155,  # PACKET_RULESET_CONTROL
    162,  # PACKET_RULESET_CHOICES
    171,  # PACKET_RULESET_SELECT
    175,  # PACKET_RULESET_EFFECT
    177,  # PACKET_RULESET_RESOURCE
    220,  # PACKET_RULESET_ROAD
    224,  # PACKET_RULESET_DISASTER
    225,  # PACKET_RULESETS_READY
    226,  # PACKET_RULESET_EXTRA_FLAG
    227,  # PACKET_RULESET_TRADE
    228,  # PACKET_RULESET_UNIT_BONUS
    229,  # PACKET_RULESET_UNIT_FLAG
    230,  # PACKET_RULESET_UNIT_CLASS_FLAG
    231,  # PACKET_RULESET_TERRAIN_FLAG
    232,  # PACKET_RULESET_EXTRA (defines EXTRA_MINE, EXTRA_HUT, etc.)
    233,  # PACKET_RULESET_ACHIEVEMENT
    234,  # PACKET_RULESET_TECH_FLAG
    235,  # PACKET_RULESET_ACTION_ENABLER
    236,  # PACKET_RULESET_NATION_SETS
    237,  # PACKET_NATION_AVAILABILITY
    239,  # PACKET_RULESET_STYLE
    240,  # PACKET_RULESET_MUSIC
    243,  # PACKET_RULESET_MULTIPLIER
    246,  # PACKET_RULESET_ACTION
    247,  # PACKET_RULESET_DESCRIPTION_PART
    248,  # PACKET_RULESET_GOODS
    251,  # PACKET_RULESET_SUMMARY
    252,  # PACKET_RULESET_ACTION_AUTO
    260,  # PACKET_WEB_RULESET_UNIT_ADDITION
    512,  # PACKET_RULESET_CLAUSE
    513,  # PACKET_RULESET_COUNTER
}


@dataclass
class RulesetCacheEntry:
    """Cached RULESET packets for a game"""
    game_id: str
    packets: List[str]  # JSON-encoded packet strings
    timestamp: float  # When cache was created
    last_accessed: float  # For LRU eviction
    packet_count: int  # Number of packets cached
    total_bytes: int  # Total size of all packets


class RulesetPacketCache:
    """
    In-memory cache for immutable RULESET packets per game.

    RULESET packets are sent once at game start and define:
    - Unit types (unit_types[])
    - Terrain types
    - Extra definitions (EXTRA_MINE, EXTRA_HUT, etc.)
    - Technologies, buildings, governments, nations, etc.

    These packets are immutable during gameplay and can be safely cached
    and reused for all spectators joining the same game.
    """

    def __init__(self, ttl_seconds: int = 3600, max_games: int = 10,
                 max_cache_size_mb: int = 50):
        """
        Initialize RULESET packet cache.

        Args:
            ttl_seconds: Time-to-live for cached entries (default 1 hour)
            max_games: Maximum number of games to cache
            max_cache_size_mb: Maximum total cache size in MB
        """
        self.ttl = ttl_seconds
        self.max_games = max_games
        self.max_cache_size_bytes = max_cache_size_mb * 1024 * 1024

        # Use OrderedDict for LRU eviction
        self.cache: OrderedDict[str, RulesetCacheEntry] = OrderedDict()

        # Thread safety
        self._lock = threading.RLock()

        # Statistics
        self.stats = {
            'total_packets_cached': 0,
            'total_bytes_cached': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'evictions': 0,
        }

        logger.info(f"RulesetPacketCache initialized: ttl={ttl_seconds}s, "
                   f"max_games={max_games}, max_size={max_cache_size_mb}MB")

    def _validate_game_id(self, game_id: str) -> bool:
        """
        Validate game_id format to prevent cache poisoning.

        Args:
            game_id: Game identifier to validate

        Returns:
            True if game_id is valid

        Raises:
            ValueError: If game_id is invalid
        """
        if not game_id or not isinstance(game_id, str):
            raise ValueError(f"Invalid game_id: must be non-empty string")

        if not GAME_ID_PATTERN.match(game_id):
            raise ValueError(
                f"Invalid game_id format: '{game_id}'. "
                f"Must be alphanumeric with dash/underscore, max 64 chars"
            )

        return True

    def _validate_packet(self, packet_json: str) -> Dict[str, Any]:
        """
        Validate packet structure and size to prevent memory exhaustion.

        Args:
            packet_json: JSON-encoded packet string

        Returns:
            Parsed packet dict

        Raises:
            ValueError: If packet is invalid
        """
        if not packet_json or not isinstance(packet_json, str):
            raise ValueError("Packet must be non-empty string")

        # Check packet size
        packet_size = len(packet_json.encode('utf-8'))
        if packet_size > MAX_PACKET_SIZE_BYTES:
            raise ValueError(
                f"Packet size {packet_size} bytes exceeds maximum "
                f"{MAX_PACKET_SIZE_BYTES} bytes"
            )

        # Validate JSON structure
        try:
            packet = json.loads(packet_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON packet: {e}")

        # Validate packet has 'pid' field
        if not isinstance(packet, dict):
            raise ValueError("Packet must be JSON object")

        if 'pid' not in packet:
            raise ValueError("Packet must have 'pid' field")

        if not isinstance(packet['pid'], int):
            raise ValueError("Packet 'pid' must be integer")

        return packet

    def is_ruleset_packet(self, pid: int) -> bool:
        """
        Check if a packet ID is a RULESET packet.

        Args:
            pid: Packet ID

        Returns:
            True if packet is a RULESET packet
        """
        return pid in RULESET_PIDS

    def add_packet(self, game_id: str, packet_json: str) -> bool:
        """
        Add a RULESET packet to the cache for a game.

        Args:
            game_id: Game identifier
            packet_json: JSON-encoded packet string

        Returns:
            True if packet was added, False otherwise

        Raises:
            ValueError: If game_id or packet format is invalid
        """
        # Validate game_id format
        self._validate_game_id(game_id)

        # Validate packet structure and size
        packet = self._validate_packet(packet_json)

        with self._lock:
            # Create cache entry if it doesn't exist
            if game_id not in self.cache:
                self.cache[game_id] = RulesetCacheEntry(
                    game_id=game_id,
                    packets=[],
                    timestamp=time.time(),
                    last_accessed=time.time(),
                    packet_count=0,
                    total_bytes=0
                )
                logger.info(f"Created new RULESET cache entry for game: {game_id}")

            entry = self.cache[game_id]

            # Add packet
            packet_bytes = len(packet_json.encode('utf-8'))
            entry.packets.append(packet_json)
            entry.packet_count += 1
            entry.total_bytes += packet_bytes
            entry.last_accessed = time.time()

            # Update stats
            self.stats['total_packets_cached'] += 1
            self.stats['total_bytes_cached'] += packet_bytes

            # Move to end for LRU
            self.cache.move_to_end(game_id)

            # Check if we need to evict
            self._ensure_cache_capacity()

            logger.debug(f"Added RULESET packet (pid={packet['pid']}) to cache: "
                        f"game={game_id}, count={entry.packet_count}, size={packet_bytes} bytes")

            return True

    def get_packets(self, game_id: str) -> Optional[List[str]]:
        """
        Get all cached RULESET packets for a game.

        Args:
            game_id: Game identifier

        Returns:
            List of JSON-encoded packet strings, or None if not found/expired

        Raises:
            ValueError: If game_id format is invalid
        """
        # Validate game_id format
        self._validate_game_id(game_id)

        with self._lock:
            if game_id not in self.cache:
                self.stats['cache_misses'] += 1
                logger.debug(f"Cache miss: game={game_id}")
                return None

            entry = self.cache[game_id]
            current_time = time.time()

            # Check TTL
            if current_time - entry.timestamp > self.ttl:
                logger.info(f"Cache entry expired: game={game_id}, "
                           f"age={current_time - entry.timestamp:.1f}s")
                self.cache.pop(game_id, None)
                self.stats['cache_misses'] += 1
                return None

            # Update access time and move to end for LRU
            entry.last_accessed = current_time
            self.cache.move_to_end(game_id)

            self.stats['cache_hits'] += 1
            logger.info(f"Cache hit: game={game_id}, packets={entry.packet_count}, "
                       f"size={entry.total_bytes} bytes")

            return entry.packets.copy()

    def invalidate(self, game_id: str) -> bool:
        """
        Remove a game's RULESET cache.

        Args:
            game_id: Game identifier

        Returns:
            True if entry was removed
        """
        with self._lock:
            if game_id in self.cache:
                entry = self.cache.pop(game_id)
                logger.info(f"Invalidated cache: game={game_id}, "
                           f"packets={entry.packet_count}")
                return True
            return False

    def _ensure_cache_capacity(self):
        """Evict LRU entries if cache is full"""
        # Evict by max games
        while len(self.cache) > self.max_games:
            lru_game_id, lru_entry = self.cache.popitem(last=False)
            self.stats['evictions'] += 1
            logger.info(f"Evicted cache entry (max_games): game={lru_game_id}, "
                       f"packets={lru_entry.packet_count}")

        # Evict by total size
        total_size = sum(entry.total_bytes for entry in self.cache.values())
        while total_size > self.max_cache_size_bytes and len(self.cache) > 0:
            lru_game_id, lru_entry = self.cache.popitem(last=False)
            total_size -= lru_entry.total_bytes
            self.stats['evictions'] += 1
            logger.info(f"Evicted cache entry (max_size): game={lru_game_id}, "
                       f"packets={lru_entry.packet_count}, size={lru_entry.total_bytes}")

    def get_cache_info(self, game_id: str) -> Optional[Dict[str, Any]]:
        """
        Get metadata about a cached game.

        Args:
            game_id: Game identifier

        Returns:
            Dict with cache metadata or None
        """
        with self._lock:
            if game_id not in self.cache:
                return None

            entry = self.cache[game_id]
            current_time = time.time()

            return {
                'game_id': game_id,
                'packet_count': entry.packet_count,
                'total_bytes': entry.total_bytes,
                'age_seconds': current_time - entry.timestamp,
                'seconds_since_last_access': current_time - entry.last_accessed,
                'ttl_remaining_seconds': max(0, self.ttl - (current_time - entry.timestamp)),
            }

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total_size = sum(entry.total_bytes for entry in self.cache.values())
            total_packets = sum(entry.packet_count for entry in self.cache.values())

            hit_rate = 0.0
            total_requests = self.stats['cache_hits'] + self.stats['cache_misses']
            if total_requests > 0:
                hit_rate = self.stats['cache_hits'] / total_requests

            return {
                'games_cached': len(self.cache),
                'total_packets': total_packets,
                'total_bytes': total_size,
                'cache_utilization_percent': (total_size / self.max_cache_size_bytes) * 100,
                'hit_rate': hit_rate,
                'cache_hits': self.stats['cache_hits'],
                'cache_misses': self.stats['cache_misses'],
                'evictions': self.stats['evictions'],
                'max_games': self.max_games,
                'max_cache_size_bytes': self.max_cache_size_bytes,
                'ttl_seconds': self.ttl,
            }

    def clear(self):
        """Clear all cache entries"""
        with self._lock:
            self.cache.clear()
            logger.info("RULESET cache cleared")


# Global cache instance
ruleset_cache = RulesetPacketCache()
