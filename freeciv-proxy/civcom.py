# -*- coding: utf-8 -*-

'''
 Freeciv - Copyright (C) 2009-2014 - Andreas Røsdal   andrearo@pvv.ntnu.no
   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2, or (at your option)
   any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
'''

import socket
from struct import *
from threading import Thread
from typing import Dict, Any, List
import logging
import time
import json
import os
import asyncio
from tornado import ioloop

# Import packet ID constants for type-safe packet handling
from packet_constants import (
    PACKET_CONN_INFO,
    PACKET_PLAYER_INFO,
    PACKET_MAP_INFO,
    PACKET_GAME_INFO,
    PACKET_UNIT_INFO,
    PACKET_UNIT_REMOVE,
    PACKET_UNIT_SHORT_INFO,
    PACKET_CITY_INFO,
    PACKET_TILE_INFO,
    PACKET_CHAT_MSG,
    PACKET_RULESET_NATION,
    PACKET_RULESET_UNIT,
    PACKET_RULESET_BUILDING,
    PACKET_RULESET_TECH,
    PACKET_RULESET_TERRAIN,
    PACKET_RULESET_EXTRA,
    PACKET_RULESET_UNIT_CLASS,
    PACKET_WEB_RULESET_UNIT_ADDITION,
    PACKET_WEB_CITY_INFO_ADDITION,
    PACKET_CONN_PING,
    PACKET_CONN_PONG,
    PACKET_RESEARCH_INFO,
    PACKET_SERVER_JOIN_REPLY,
    PACKET_CLIENT_INFO,
    PACKET_BEGIN_TURN,  # Turn start signal from server
    get_packet_name
)

# Import RulesetMapper for production name to ID conversion
from ruleset_mapper import RulesetMapper, VUT_IMPROVEMENT, VUT_UTYPE

# Import BitVector for parsing bitvector fields from packets
from bitvector import BitVector

# Tech research constants (from freeciv/common/tech.h and fc_types.js)
# A_UNSET indicates that no tech is selected (for research)
MAX_NUM_ADVANCES = 250
A_LAST = MAX_NUM_ADVANCES + 1  # 251
A_UNSET = A_LAST + 2  # 253

# FreeCiv Action IDs - from freeciv/freeciv-web/src/main/webapp/javascript/fc_types.js
# These define the action types that units can perform
ACTION_ESTABLISH_EMBASSY = 0
ACTION_SPY_INVESTIGATE_CITY = 2
ACTION_SPY_POISON = 4
ACTION_SPY_STEAL_GOLD = 6
ACTION_SPY_SABOTAGE_CITY = 8
ACTION_SPY_TARGETED_SABOTAGE_CITY = 10
ACTION_SPY_STEAL_TECH = 14
ACTION_SPY_TARGETED_STEAL_TECH = 16
ACTION_SPY_INCITE_CITY = 18
ACTION_TRADE_ROUTE = 20
ACTION_MARKETPLACE = 21
ACTION_HELP_WONDER = 22
ACTION_SPY_BRIBE_UNIT = 23
ACTION_CAPTURE_UNITS = 24
ACTION_SPY_SABOTAGE_UNIT = 25
ACTION_FOUND_CITY = 27
ACTION_JOIN_CITY = 28
ACTION_STEAL_MAPS = 29
ACTION_SPY_NUKE = 31
ACTION_NUKE = 33
ACTION_NUKE_CITY = 34
ACTION_NUKE_UNITS = 35
ACTION_DESTROY_CITY = 36
ACTION_EXPEL_UNIT = 37
ACTION_RECYCLE_UNIT = 38
ACTION_DISBAND_UNIT = 39
ACTION_HOME_CITY = 40
ACTION_UPGRADE_UNIT = 42
ACTION_CONVERT = 43
ACTION_AIRLIFT = 44
ACTION_ATTACK = 45
ACTION_SUICIDE_ATTACK = 46
ACTION_CONQUER_CITY = 49
ACTION_BOMBARD = 53
ACTION_FORTIFY = 57
ACTION_CULTIVATE = 58
ACTION_PLANT = 59
ACTION_TRANSFORM_TERRAIN = 60
ACTION_ROAD = 61
ACTION_IRRIGATE = 62
ACTION_MINE = 63
ACTION_BASE = 64
ACTION_PILLAGE = 65
ACTION_CLEAN_POLLUTION = 66
ACTION_CLEAN_FALLOUT = 67
ACTION_TRANSPORT_BOARD = 68
ACTION_TRANSPORT_DEBOARD = 71
ACTION_TRANSPORT_EMBARK = 72
ACTION_TRANSPORT_DISEMBARK1 = 76
ACTION_TRANSPORT_LOAD = 80
ACTION_TRANSPORT_UNLOAD = 83
ACTION_SPY_SPREAD_PLAGUE = 84
ACTION_SPY_ATTACK = 85
ACTION_HUT_ENTER = 90
ACTION_HEAL_UNIT = 98
ACTION_PARADROP = 100
ACTION_UNIT_MOVE = 108
ACTION_CLEAN = 111
ACTION_COUNT = 116

# Map FreeCiv action IDs to protocol action type strings
ACTION_ID_TO_TYPE = {
    ACTION_FOUND_CITY: 'unit_build_city',
    ACTION_JOIN_CITY: 'unit_join_city',
    ACTION_ATTACK: 'unit_attack',
    ACTION_SUICIDE_ATTACK: 'unit_suicide_attack',
    ACTION_BOMBARD: 'unit_bombard',
    ACTION_CAPTURE_UNITS: 'unit_capture',
    ACTION_CONQUER_CITY: 'unit_conquer_city',
    ACTION_NUKE: 'unit_nuke',
    ACTION_NUKE_CITY: 'unit_nuke_city',
    ACTION_NUKE_UNITS: 'unit_nuke_units',
    ACTION_FORTIFY: 'unit_fortify',
    ACTION_ROAD: 'unit_build_road',
    ACTION_IRRIGATE: 'unit_build_irrigation',
    ACTION_MINE: 'unit_build_mine',
    ACTION_BASE: 'unit_build_base',
    ACTION_PILLAGE: 'unit_pillage',
    ACTION_CLEAN: 'unit_clean',
    ACTION_CLEAN_POLLUTION: 'unit_clean',
    ACTION_CLEAN_FALLOUT: 'unit_clean',
    ACTION_TRANSFORM_TERRAIN: 'unit_transform',
    ACTION_CULTIVATE: 'unit_cultivate',
    ACTION_PLANT: 'unit_plant',
    ACTION_TRADE_ROUTE: 'unit_trade_route',
    ACTION_MARKETPLACE: 'unit_marketplace',
    ACTION_HELP_WONDER: 'unit_help_wonder',
    ACTION_ESTABLISH_EMBASSY: 'unit_establish_embassy',
    ACTION_SPY_INVESTIGATE_CITY: 'spy_investigate_city',
    ACTION_SPY_POISON: 'spy_poison',
    ACTION_SPY_SABOTAGE_CITY: 'spy_sabotage_city',
    ACTION_SPY_TARGETED_SABOTAGE_CITY: 'spy_targeted_sabotage_city',
    ACTION_SPY_STEAL_TECH: 'spy_steal_tech',
    ACTION_SPY_TARGETED_STEAL_TECH: 'spy_targeted_steal_tech',
    ACTION_SPY_INCITE_CITY: 'spy_incite_city',
    ACTION_SPY_STEAL_GOLD: 'spy_steal_gold',
    ACTION_STEAL_MAPS: 'spy_steal_maps',
    ACTION_SPY_NUKE: 'spy_nuke',
    ACTION_SPY_SPREAD_PLAGUE: 'spy_spread_plague',
    ACTION_SPY_BRIBE_UNIT: 'spy_bribe_unit',
    ACTION_SPY_SABOTAGE_UNIT: 'spy_sabotage_unit',
    ACTION_SPY_ATTACK: 'spy_attack',
    ACTION_DISBAND_UNIT: 'unit_disband',
    ACTION_RECYCLE_UNIT: 'unit_disband',
    ACTION_HOME_CITY: 'unit_home_city',
    ACTION_UPGRADE_UNIT: 'unit_upgrade',
    ACTION_CONVERT: 'unit_convert',
    ACTION_AIRLIFT: 'unit_airlift',
    ACTION_PARADROP: 'unit_paradrop',
    ACTION_TRANSPORT_BOARD: 'unit_board',
    ACTION_TRANSPORT_DEBOARD: 'unit_deboard',
    ACTION_TRANSPORT_EMBARK: 'unit_embark',
    ACTION_TRANSPORT_DISEMBARK1: 'unit_disembark',
    ACTION_TRANSPORT_LOAD: 'unit_load',
    ACTION_TRANSPORT_UNLOAD: 'unit_unload',
    ACTION_EXPEL_UNIT: 'unit_expel',
    ACTION_HEAL_UNIT: 'unit_heal',
    ACTION_HUT_ENTER: 'unit_explore',
    ACTION_UNIT_MOVE: 'unit_move',
}

# Terrain class constants - from freeciv/common/terrain.h
TC_LAND = 0  # Land terrain
TC_OCEAN = 1  # Ocean terrain

# Default citymindist (minimum distance between cities)
DEFAULT_CITYMINDIST = 2

# Packet size limits for large packet handling
# Packets above WARNING_PACKET_SIZE get logged for monitoring
# Packets above CRITICAL_PACKET_SIZE trigger rate limiting (delay between sends)
# to prevent WebSocket buffer overflow and give clients time to process
#
# Threshold rationale:
# - 500KB warning: Most packets are <100KB; this catches unusually large ones
# - 2MB critical: Ruleset packets can exceed 1MB on large maps with many units.
#   This threshold was chosen based on observed max packet sizes in production.
#   Going higher risks WebSocket frame fragmentation issues.
WARNING_PACKET_SIZE = 500 * 1024       # 500KB - warn about large packets
CRITICAL_PACKET_SIZE = 2 * 1024 * 1024 # 2MB - add rate limiting delay
LARGE_PACKET_DELAY_MS = 20             # 20ms delay after critical-size packets

HOST = '127.0.0.1'
logger = logging.getLogger("freeciv-proxy")

# Unit type ID to name mapping (FreeCiv default/classic ruleset)
# Source: freeciv/data/classic/units.ruleset
# Maps integer type IDs from PACKET_UNIT_INFO to human-readable unit names
UNIT_TYPE_NAMES = {
    0: 'settlers', 1: 'workers', 2: 'engineers',
    3: 'warriors', 4: 'phalanx', 5: 'archers', 6: 'legion',
    7: 'pikemen', 8: 'musketeers', 9: 'fanatics', 10: 'partisan',
    11: 'alpine_troops', 12: 'riflemen', 13: 'marines', 14: 'paratroopers',
    15: 'mech_inf', 16: 'horsemen', 17: 'chariot', 18: 'elephants',
    19: 'crusaders', 20: 'knights', 21: 'dragoons', 22: 'cavalry',
    23: 'armor', 24: 'catapult', 25: 'cannon', 26: 'artillery',
    27: 'howitzer', 28: 'fighter', 29: 'bomber', 30: 'helicopter',
    31: 'stealth_fighter', 32: 'stealth_bomber', 33: 'trireme',
    34: 'caravel', 35: 'galleon', 36: 'frigate', 37: 'ironclad',
    38: 'destroyer', 39: 'cruiser', 40: 'aegis_cruiser', 41: 'battleship',
    42: 'submarine', 43: 'carrier', 44: 'transport', 45: 'cruise_missile',
    46: 'nuclear', 47: 'diplomat', 48: 'spy', 49: 'caravan',
    50: 'freight', 51: 'explorer', 52: 'barbarian_leader', 53: 'awacs',
    # Custom rulesets may have different IDs - fallback to unit_<id>
}

def get_unit_type_name(type_id):
    """Convert FreeCiv unit type ID to human-readable name.

    This function normalizes unit types to lowercase string names for consistency
    across the system. It handles both integer type IDs from the FreeCiv server
    and string types that may already be normalized.

    Args:
        type_id: Integer type ID from PACKET_UNIT_INFO, or string name

    Returns:
        String type name in lowercase (e.g., 'warrior', 'settler')

    Examples:
        >>> get_unit_type_name(3)
        'warriors'
        >>> get_unit_type_name(0)
        'settlers'
        >>> get_unit_type_name('Warrior')
        'warrior'
        >>> get_unit_type_name(999)  # Unknown custom unit
        'unit_999'
    """
    if isinstance(type_id, str):
        return type_id.lower()  # Already a string, normalize case
    if isinstance(type_id, int):
        return UNIT_TYPE_NAMES.get(type_id, f'unit_{type_id}')
    return 'unknown'

# Activity type ID to name mapping (FreeCiv activity enum)
# Source: freeciv/common/unit.h enum unit_activity
# Maps integer activity IDs from PACKET_UNIT_INFO to human-readable activity names
ACTIVITY_NAMES = {
    0: 'idle',           # ACTIVITY_IDLE
    1: 'pollution',      # ACTIVITY_POLLUTION
    2: 'road',           # ACTIVITY_ROAD
    3: 'mine',           # ACTIVITY_MINE
    4: 'irrigate',       # ACTIVITY_IRRIGATE
    5: 'fortified',      # ACTIVITY_FORTIFIED
    6: 'fortress',       # ACTIVITY_FORTRESS
    7: 'sentry',         # ACTIVITY_SENTRY
    8: 'railroad',       # ACTIVITY_RAILROAD
    9: 'pillage',        # ACTIVITY_PILLAGE
    10: 'goto',          # ACTIVITY_GOTO
    11: 'explore',       # ACTIVITY_EXPLORE
    12: 'transform',     # ACTIVITY_TRANSFORM
    13: 'airbase',       # ACTIVITY_AIRBASE
    14: 'fortifying',    # ACTIVITY_FORTIFYING
    15: 'fallout',       # ACTIVITY_FALLOUT
    16: 'patrol',        # ACTIVITY_PATROL
    17: 'base',          # ACTIVITY_BASE
}

def get_activity_name(activity_id):
    """Convert FreeCiv activity ID to human-readable name.

    Args:
        activity_id: Integer activity ID from PACKET_UNIT_INFO, string name, or None

    Returns:
        String activity name (e.g., 'idle', 'sentry') or None for no activity

    Examples:
        >>> get_activity_name(0)
        'idle'
        >>> get_activity_name(7)
        'sentry'
        >>> get_activity_name(None)
        None
        >>> get_activity_name('sentry')
        'sentry'
    """
    if activity_id is None:
        return None
    if isinstance(activity_id, str):
        return activity_id.lower()
    if isinstance(activity_id, int):
        return ACTIVITY_NAMES.get(activity_id, 'idle')
    return 'idle'

# The CivCom handles communication between freeciv-proxy and the Freeciv C
# server.


class CivCom(Thread):

    def __init__(self, username, civserverport, key, civwebserver):
        Thread.__init__(self)
        self.socket = None
        self.username = username
        self.civserverport = civserverport
        self.key = key
        self.send_buffer = []
        self.connect_time = time.time()
        self.civserver_messages = []
        self.stopped = False
        self.packet_size = -1
        self.net_buf = bytearray(0)
        self.header_buf = bytearray(0)
        self.daemon = True
        self.civwebserver = civwebserver

        # Game state tracking - populated from parsed packets
        self.map_info = {}
        self.player_units = {}  # Dict keyed by unit_id for efficient updates
        self.other_units = {}   # Dict keyed by unit_id for non-player units
        self.player_cities = {}  # Dict keyed by city_id for efficient updates
        self.all_players = []
        self.known_techs = []
        self.visible_tiles = []
        self.game_turn = 1
        self.game_info_received = False  # True after PACKET_GAME_INFO received
        self.turn_started = True  # True when in active turn, False after end_turn until PACKET_BEGIN_TURN
        self.turn_advance_event = asyncio.Event()  # Event for efficient turn waiting (replaces polling)
        self.turn_advance_event.set()  # Start with event set (turn is active)
        self.game_phase = 'movement'
        self.player_id = None  # Will be set from PACKET_PLAYER_INFO
        self.nations = {}  # Will be populated from PACKET_RULESET_NATION (pid=148)
        self.research_info = {}  # {player_id: PACKET_RESEARCH_INFO} - tracks tech progress
        self.initial_units_received = False  # Set True when first PACKET_UNIT_INFO for our player arrives

        # RULESET packet storage - mirrors FreeCiv web client architecture
        # These define immutable game rules (unit types, buildings, techs, terrain, etc.)
        # Stored directly here instead of separate cache layer for simplicity
        # Matches web client's unit_types[], improvements[], techs[] pattern
        self.unit_types = {}      # {unit_type_id: PACKET_RULESET_UNIT data}
        self.improvements = {}    # {building_id: PACKET_RULESET_BUILDING data}
        self.techs = {}           # {tech_id: PACKET_RULESET_TECH data}
        self.terrains = {}        # {terrain_id: PACKET_RULESET_TERRAIN data}
        self.extras = {}          # {extra_id: PACKET_RULESET_EXTRA data}
        self.unit_classes = {}    # {unit_class_id: PACKET_RULESET_UNIT_CLASS data}

        # Per-turn action cache - stores generated city production and tech research actions
        # Cache keys: "{turn}_{player_id}_city_actions" and "{turn}_{player_id}_tech_actions"
        # Unit actions are NOT cached because every unit move affects other units' possibilities
        self._action_cache = {}  # {cache_key: list of action dicts}
        
        # Game settings from PACKET_GAME_INFO
        self.citymindist = DEFAULT_CITYMINDIST  # Minimum distance between cities
        self.game_timeout = None  # Turn timeout for pause/resume functionality

        # Tile data storage for terrain lookups
        self.tiles = {}  # {tile_index: {terrain, extras, ...}}

        logger.info(
            f"🆕 CivCom instance created:\n"
            f"   username={username}, port={civserverport}, key={key}\n"
            f"   player_units initialized as: {type(self.player_units).__name__}"
        )

    def invalidate_action_cache(self, player_id=None, cache_type=None):
        """Invalidate cached actions when game state changes.

        This should be called when:
        - Tech research state changes (PACKET_RESEARCH_INFO with new researching value)
        - City production completes
        - Any state change that affects legal actions

        Args:
            player_id: Specific player to invalidate, or None for all players
            cache_type: 'tech', 'city', or None for all types
        """
        keys_to_remove = []

        for key in self._action_cache:
            # Cache key format: "{turn}_{player_id}_{type}_actions"
            if player_id is not None and f"_{player_id}_" not in key:
                continue
            if cache_type is not None and f"_{cache_type}_" not in key:
                continue
            keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._action_cache[key]

        if keys_to_remove:
            logger.debug(f"Invalidated {len(keys_to_remove)} action cache entries for player={player_id}, type={cache_type}")

    def _safe_write_message(self, conn, packet: str, packet_size: int):
        """Safely write a message to the WebSocket with error tracking.

        This wrapper catches write failures and reports them to the handler's
        connection health monitoring, enabling proactive pause before full disconnect.

        Args:
            conn: The WebSocket connection (civwebserver)
            packet: The packet string to send
            packet_size: Size of packet in bytes (pre-calculated for efficiency)
        """
        # ERR-P-003 FIX: Basic connection check - don't be too aggressive
        # Tornado's WebSocketHandler doesn't expose ws_connection the way we were checking
        if not conn:
            logger.warning(
                f"⚠️ Skipping write to {self.username}: No connection object "
                f"(packet size: {packet_size:,} bytes)"
            )
            return

        try:
            conn.write_message(packet)
            # Reset failure count on successful send if handler supports it
            if hasattr(conn, '_reset_send_failure_count'):
                conn._reset_send_failure_count()
        except Exception as e:
            # Enhanced error logging with exception type and details
            error_type = type(e).__name__
            logger.error(
                f"❌ WebSocket write failed for {self.username}: {error_type}: {e} "
                f"(packet size: {packet_size:,} bytes)"
            )
            # Log additional context for debugging observer disconnections
            if "observer" in self.username.lower() or "_view_" in self.username:
                logger.error(
                    f"   ⚠️ Observer connection failure detected for {self.username}"
                )

            # Track failure for connection health monitoring
            if hasattr(conn, '_track_send_failure'):
                conn._track_send_failure(e)
            # Don't re-raise - the error is tracked and handler will take action if needed

    def get_unit_tile(self, unit_id: int) -> int:
        """Return the tile index of a unit by id. Returns -1 if unknown.

        This is used by packet_converter when constructing PACKET_UNIT_ORDERS.
        """
        # Prefer our own units (player_units)
        if isinstance(self.player_units, dict):
            unit = self.player_units.get(unit_id)
            if unit and 'tile' in unit:
                return unit.get('tile', -1)

        # Fall back to other players' units if available
        if hasattr(self, 'other_units') and isinstance(self.other_units, dict):
            unit = self.other_units.get(unit_id)
            if unit and 'tile' in unit:
                return unit.get('tile', -1)

        return -1

    def _get_nation_name(self, nation_id):
        """Convert nation ID to human-readable name using nations registry.

        Args:
            nation_id: Integer nation ID from PACKET_PLAYER_INFO, or string name

        Returns:
            String nation name (e.g., 'Romans', 'Americans') or 'Unknown' if not found

        Examples:
            >>> civcom._get_nation_name(1)
            'Romans'
            >>> civcom._get_nation_name('Romans')
            'Romans'
            >>> civcom._get_nation_name(999)
            'Unknown'
        """
        if nation_id is None:
            return 'Unknown'
        if isinstance(nation_id, str):
            return nation_id  # Already a string name
        if isinstance(nation_id, int):
            # Reverse lookup: nations dict is {name: id}, we need {id: name}
            for name, nid in self.nations.items():
                if nid == nation_id:
                    return name
            # If not found in registry, return generic name
            return f'Nation{nation_id}'
        return 'Unknown'

    def get_tech_state(self, tech_id: int, player_id: int) -> str:
        """Get the research state of a tech for a player.
        
        Returns:
            'KNOWN' - tech is researched
            'PREREQS_KNOWN' - prerequisites met, can research
            'UNKNOWN' - prerequisites not met
        """
        research = self.research_info.get(player_id)
        if not research:
            return 'UNKNOWN'
        
        inventions = research.get('inventions', [])
        if tech_id < len(inventions):
            state = inventions[tech_id]
            # States: 0=UNKNOWN, 1=PREREQS_KNOWN, 2=KNOWN
            if state == '2':
                return 'KNOWN'
            elif state == '1':
                return 'PREREQS_KNOWN'
        return 'UNKNOWN'
    
    def can_research_tech(self, tech_id: int, player_id: int) -> bool:
        """Check if a tech can be researched (prerequisites are met).
        
        Args:
            tech_id: Technology ID
            player_id: Player ID
            
        Returns:
            True if tech can be researched (state is PREREQS_KNOWN)
        """
        return self.get_tech_state(tech_id, player_id) == 'PREREQS_KNOWN'
    
    def get_researchable_techs(self, player_id: int) -> List[Dict[str, Any]]:
        """Get all technologies that can currently be researched.
        
        Args:
            player_id: Player ID
            
        Returns:
            List of tech dicts with id, name, and cost
        """
        researchable = []
        research = self.research_info.get(player_id)
        
        if not research:
            return researchable
        
        for tech_id, tech_data in self.techs.items():
            if self.can_research_tech(tech_id, player_id):
                researchable.append({
                    'id': tech_id,
                    'name': tech_data.get('name', ''),
                    'cost': tech_data.get('cost', 0),
                    'rule_name': tech_data.get('rule_name', '')
                })
        
        return researchable

    def utype_can_do_action(self, unit_type_id: int, action_id: int) -> bool:
        """Check if a unit type can perform a specific action.
        
        Uses the utype_actions bitfield from PACKET_RULESET_UNIT to determine
        if the unit type has the capability to perform the given action.
        
        This mirrors the FreeCiv web client's utype_can_do_action() function.
        
        Args:
            unit_type_id: The unit type ID from PACKET_UNIT_INFO
            action_id: The action ID (e.g., ACTION_FOUND_CITY, ACTION_ATTACK)
            
        Returns:
            True if the unit type can perform the action, False otherwise
        """
        if action_id < 0 or action_id >= ACTION_COUNT:
            return False
            
        unit_type = self.unit_types.get(unit_type_id)
        if not unit_type:
            # Unit type not found - ruleset data not loaded (invalid state)
            logger.error(
                f"utype_can_do_action: unit_type_id={unit_type_id} not found in unit_types "
                f"(have {len(self.unit_types)} unit types). "
                f"PACKET_RULESET_UNIT not received - invalid state. Blocking action {action_id}."
            )
            return False  # Block action when ruleset data missing
            
        # The utype_actions is a byte array (list of bytes, not 32-bit integers)
        # Each byte contains 8 bits of action capability flags
        # This is populated from PACKET_WEB_RULESET_UNIT_ADDITION (pid=260)
        utype_actions = unit_type.get('utype_actions', [])
        if not utype_actions:
            # Missing utype_actions indicates ruleset not fully loaded (invalid state)
            unit_name = unit_type.get('name', f'unit_type_{unit_type_id}')
            logger.error(
                f"utype_actions not populated for unit type {unit_name} (id={unit_type_id}). "
                f"PACKET_WEB_RULESET_UNIT_ADDITION not received - invalid state. "
                f"Blocking action {action_id}."
            )
            return False
            
        # Calculate which byte in the array and which bit within that byte
        # utype_actions is a byte array where each byte contains 8 action bits
        byte_index = action_id // 8
        bit_index = action_id % 8
        
        if byte_index >= len(utype_actions):
            return False
            
        # Check if the bit is set (bit order within byte: LSB first)
        return bool(utype_actions[byte_index] & (1 << bit_index))
    
    def city_has_improvement(self, city: Dict[str, Any], improvement_name: str) -> bool:
        """Check if a city has a specific improvement/building.
        
        Args:
            city: City data dict from PACKET_CITY_INFO
            improvement_name: Name of the improvement (e.g., 'Airport', 'Barracks')
            
        Returns:
            True if city has the improvement, False otherwise
        """
        improvements_bitvector = city.get('improvements')
        if not improvements_bitvector:
            return False
            
        # Find improvement ID by name
        improvement_id = None
        for imp_id, imp_data in self.improvements.items():
            if imp_data.get('name', '').lower() == improvement_name.lower():
                improvement_id = imp_id
                break
        
        if improvement_id is None:
            logger.warning(f"Improvement '{improvement_name}' not found in ruleset")
            return False
        
        # Check if the bit is set in the bitvector
        # improvements_bitvector is a list of bytes
        byte_index = improvement_id // 8
        bit_index = improvement_id % 8
        
        if byte_index >= len(improvements_bitvector):
            return False
            
        return bool(improvements_bitvector[byte_index] & (1 << bit_index))

    def can_city_build_unit(self, city: dict, unit_type_id: int) -> bool:
        """Check if a city can build a specific unit type.

        Uses the server-provided can_build_unit bitvector from PACKET_WEB_CITY_INFO_ADDITION
        which accounts for tech prerequisites, obsolescence, and other game rules.

        Args:
            city: City data dict with can_build_unit bitvector
            unit_type_id: The unit type ID to check

        Returns:
            True if city can build the unit, False otherwise
        """
        can_build_bitvector = city.get('can_build_unit')
        if not can_build_bitvector:
            # No bitvector available - fallback to allowing (server hasn't sent build info yet)
            return True

        # Check if the bit is set in the bitvector
        byte_index = unit_type_id // 8
        bit_index = unit_type_id % 8

        if byte_index >= len(can_build_bitvector):
            return False

        return bool(can_build_bitvector[byte_index] & (1 << bit_index))

    def can_city_build_improvement(self, city: dict, improvement_id: int) -> bool:
        """Check if a city can build a specific improvement/building.

        Uses the server-provided can_build_improvement bitvector from PACKET_WEB_CITY_INFO_ADDITION
        which accounts for tech prerequisites, obsolescence, whether already built, and other rules.

        Args:
            city: City data dict with can_build_improvement bitvector
            improvement_id: The improvement/building ID to check

        Returns:
            True if city can build the improvement, False otherwise
        """
        can_build_bitvector = city.get('can_build_improvement')
        if not can_build_bitvector:
            # No bitvector available - fallback to allowing (server hasn't sent build info yet)
            return True

        # Check if the bit is set in the bitvector
        byte_index = improvement_id // 8
        bit_index = improvement_id % 8

        if byte_index >= len(can_build_bitvector):
            return False

        return bool(can_build_bitvector[byte_index] & (1 << bit_index))

    def get_unit_type_actions(self, unit_type_id: int) -> list:
        """Get all actions a unit type can perform.
        
        Returns a list of action IDs that the unit type is capable of performing.
        
        Args:
            unit_type_id: The unit type ID from PACKET_UNIT_INFO
            
        Returns:
            List of action IDs the unit type can perform
        """
        actions = []
        for action_id in range(ACTION_COUNT):
            if self.utype_can_do_action(unit_type_id, action_id):
                actions.append(action_id)
        return actions
    
    def get_terrain_class(self, terrain_id: int) -> int:
        """Get the terrain class (land/ocean) for a terrain type.
        
        Args:
            terrain_id: The terrain type ID
            
        Returns:
            TC_LAND (0) for land terrain, TC_OCEAN (1) for ocean terrain
        """
        terrain = self.terrains.get(terrain_id)
        if not terrain:
            return TC_LAND  # Default to land if unknown
        return terrain.get('tclass', TC_LAND)
    
    def get_tile_terrain_class(self, tile_index: int) -> int:
        """Get the terrain class for a tile.
        
        Args:
            tile_index: The tile index
            
        Returns:
            TC_LAND (0) for land, TC_OCEAN (1) for ocean
        """
        tile = self.tiles.get(tile_index)
        if not tile:
            return TC_LAND  # Default to land if unknown
        terrain_id = tile.get('terrain')
        if terrain_id is None:
            return TC_LAND
        return self.get_terrain_class(terrain_id)
    
    def is_unit_class_native_to_terrain(self, unit_class_id: int, terrain_id: int) -> bool:
        """Check if a unit class can move on a terrain type.
        
        The native_to field from PACKET_RULESET_TERRAIN is a multi-word bitvector
        where each integer represents 32 bits of the bitvector.
        
        Format: native_to = [word0, word1, word2, word3]
        - word0 contains bits 0-31 (unit classes 0-31)
        - word1 contains bits 32-63 (unit classes 32-63)
        - etc.
        
        To check if unit class N is native:
        - word_index = N // 32
        - bit_position = N % 32
        - is_native = (native_to[word_index] & (1 << bit_position)) != 0
        
        Args:
            unit_class_id: The unit class ID
            terrain_id: The terrain type ID
            
        Returns:
            True if the unit class can move on the terrain
        """
        unit_class = self.unit_classes.get(unit_class_id)
        terrain = self.terrains.get(terrain_id)
        
        if not unit_class or not terrain:
            return True  # Allow by default if data not available
            
        native_to = terrain.get('native_to', [])
        
        if not native_to:
            return True  # Allow all if no native_to data
        
        # native_to is a multi-word bitvector: list of integers where each int is 32 bits
        # e.g., [61, 0, 0, 0] means bits 0,2,3,4,5 are set (61 = 0b111101)
        if isinstance(native_to, list) and native_to and isinstance(native_to[0], int):
            word_index = unit_class_id // 32
            bit_position = unit_class_id % 32
            
            if word_index < len(native_to):
                is_native = bool(native_to[word_index] & (1 << bit_position))
            else:
                is_native = False  # Bit not in range
            
            return is_native
        elif isinstance(native_to, int):
            # Single integer bitvector (unlikely but handle it)
            return bool(native_to & (1 << unit_class_id))
        else:
            return True  # Unknown format, allow
    
    def can_city_be_founded_at(self, tile_index: int) -> tuple:
        """Check if a city can be founded at the given tile.
        
        Checks the citymindist constraint against all known cities.
        
        Args:
            tile_index: The tile index where the city would be founded
            
        Returns:
            Tuple of (can_found: bool, reason: str or None)
        """
        xsize = self.map_info.get('width', 80)
        ysize = self.map_info.get('height', 50)
        
        # Calculate coordinates from tile index
        tile_x = tile_index % xsize
        tile_y = tile_index // xsize
        
        # Check terrain - can't build on ocean
        tile = self.tiles.get(tile_index)
        if tile:
            terrain_id = tile.get('terrain')
            if terrain_id is not None and self.get_terrain_class(terrain_id) == TC_OCEAN:
                return (False, "Cannot found city on ocean")
        
        # Check distance to all cities
        for city_id, city in self.player_cities.items():
            city_tile = city.get('tile')
            if city_tile is not None:
                city_x = city_tile % xsize
                city_y = city_tile // xsize
                
                # Calculate distance (Chebyshev distance for FreeCiv)
                dx = abs(tile_x - city_x)
                dy = abs(tile_y - city_y)
                
                # Handle map wrapping if applicable
                if self.map_info.get('wrap_x', False):
                    dx = min(dx, xsize - dx)
                if self.map_info.get('wrap_y', False):
                    dy = min(dy, ysize - dy)
                
                distance = max(dx, dy)
                
                if distance < self.citymindist:
                    return (False, f"Too close to city {city.get('name', city_id)} (distance {distance}, min {self.citymindist})")
        
        return (True, None)

    def run(self):
        try:
            # setup connection to civserver
            logger.info(f"[{self.username}] Starting connection to civserver on port {self.civserverport}")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setblocking(True)
            self.socket.settimeout(2)
            try:
                logger.info(f"[{self.username}] Attempting to connect to {HOST}:{self.civserverport}")
                self.socket.connect((HOST, self.civserverport))
                self.socket.settimeout(0.01)
                logger.info(f"[{self.username}] Successfully connected to {HOST}:{self.civserverport}")
            except socket.error as reason:
                logger.error(f"[{self.username}] Failed to connect to {HOST}:{self.civserverport}: {reason}")
                self.send_error_to_client(
                    "Proxy unable to connect to civserver. Error: %s" %
                    (reason))
                self.close_connection()
                return

            # send initial login packet to civserver
            logger.debug(f"Sending login packet for {self.username}")
            self.civserver_messages = [self.civwebserver.loginpacket]
            self.send_packets_to_civserver()
            logger.debug(f"Login packet sent for {self.username}")

            # receive packets from server
            logger.debug(f"Starting packet receive loop for {self.username}")
            packet_count = 0
            while True:
                packet = self.read_from_connection()

                if (self.stopped):
                    logger.debug(f"Packet loop stopped for {self.username} after {packet_count} packets")
                    return

                if (packet is not None):
                    packet_count += 1
                    if packet_count <= 3:  # Log first 3 packets only
                        logger.debug(f"Received packet #{packet_count} ({len(packet)} bytes) for {self.username}")
                    self.net_buf += packet

                    if (len(self.net_buf) == self.packet_size and self.net_buf[-1] == 0):
                        # valid packet received from freeciv server
                        # Parse and store game state ONLY if packet_constants module is available
                        try:
                            packet_str = self.net_buf[:-1].decode('utf-8')
                            self.parse_and_store_packet(packet_str)

                            # Log important packet types
                            try:
                                packet_json = json.loads(packet_str)
                                pid = packet_json.get('pid')
                                if pid == PACKET_UNIT_INFO:
                                    unit_id = packet_json.get('id')
                                    owner = packet_json.get('owner')
                                    current_count = len(self.player_units) if isinstance(self.player_units, dict) else 0
                                    logger.info(
                                        f"📦 PACKET_UNIT_INFO received by CivCom[{self.username}]:\n"
                                        f"   unit_id={unit_id}, owner={owner}\n"
                                        f"   CivCom's player_units count BEFORE store: {current_count}"
                                    )
                                elif pid == PACKET_CITY_INFO:
                                    logger.info(f"✓ Received PACKET_CITY_INFO (pid={pid}) for {self.username}")
                                elif pid == PACKET_GAME_INFO:
                                    logger.debug(f"Received PACKET_GAME_INFO for {self.username}")
                                elif pid == PACKET_CHAT_MSG:
                                    # Log chat messages to capture server command responses
                                    msg_text = packet_json.get('message', '')
                                    logger.info(f"Chat message for {self.username}: {msg_text}")
                                    
                                    # For LLM agents, emit structured chat_message event
                                    if self.civwebserver and hasattr(self.civwebserver, 'is_llm_agent') and self.civwebserver.is_llm_agent:
                                        import time as time_module
                                        chat_event = json.dumps({
                                            'type': 'chat_message',
                                            'timestamp': time_module.time(),
                                            'data': {
                                                'message': msg_text,
                                                'event': packet_json.get('event', 0),
                                                'conn_id': packet_json.get('conn_id', -1)
                                            }
                                        })
                                        # Send chat_message event via WebSocket
                                        try:
                                            conn = self.civwebserver
                                            conn.io_loop.add_callback(lambda msg=chat_event: conn.write_message(msg))
                                        except Exception as chat_err:
                                            logger.debug(f"Could not send chat_message event: {chat_err}")
                            except Exception:
                                pass  # Not JSON or parsing failed, ignore
                        except Exception as e:
                            logger.warning(f"⚠ Error parsing packet for state storage: {e}", exc_info=True)

                        # Forward packet to client UNLESS it's a PACKET_CONN_PING
                        # PACKET_CONN_PING is handled internally (we respond with pong automatically)
                        # Forwarding it to agents causes unnecessary ping/pong that triggers E101 errors
                        should_forward = True
                        try:
                            pkt = json.loads(self.net_buf[:-1].decode('utf-8'))
                            if pkt.get('pid') == PACKET_CONN_PING:
                                should_forward = False
                                logger.debug(f"[PING] Not forwarding PACKET_CONN_PING to client for {self.username} (handled internally)")
                        except Exception:
                            pass  # If we can't parse, forward anyway

                        if should_forward:
                            self.send_buffer_append(self.net_buf[:-1])
                        self.packet_size = -1
                        self.net_buf = bytearray(0)
                        continue

                time.sleep(0.01)
                # prevent max CPU usage in case of error
        except Exception as e:
            # logger.exception() already includes full traceback
            logger.exception(f"CivCom thread crashed for {self.username}: {e}")
            try:
                self.send_error_to_client(f"Connection thread crashed: {e}")
            except:
                pass  # If send fails, we're already in trouble
            try:
                self.close_connection()
            except:
                pass

    def read_from_connection(self):
        try:
            if (self.socket is not None and not self.stopped):
                if (self.packet_size == -1):
                    self.header_buf += self.socket.recv(2 -
                                                        len(self.header_buf))
                    if (len(self.header_buf) == 0):
                        logger.warning(
                            f"🔴 CIVSERVER CLOSED CONNECTION (header read): {self.username}\n"
                            f"   Port: {self.civserverport}\n"
                            f"   Connection age: {time.time() - self.connect_time:.1f}s\n"
                            f"   This indicates civserver initiated disconnect\n"
                            f"   Calling close_connection()..."
                        )
                        self.close_connection()
                        return None
                    if (len(self.header_buf) == 2):
                        header_pck = unpack('>H', self.header_buf)
                        self.header_buf = bytearray(0)
                        self.packet_size = header_pck[0] - 2
                        if (self.packet_size <= 0 or self.packet_size > 32767):
                            logger.error("Invalid packet size " + str(self.packet_size))
                    else:
                        # complete header not read yet. return now, and read
                        # the rest next time.
                        return None

            if (self.socket is not None and self.net_buf is not None and self.packet_size > 0):
                data = self.socket.recv(self.packet_size - len(self.net_buf))
                if (len(data) == 0):
                    logger.warning(
                        f"🔴 CIVSERVER CLOSED CONNECTION (data read): {self.username}\n"
                        f"   Port: {self.civserverport}\n"
                        f"   Connection age: {time.time() - self.connect_time:.1f}s\n"
                        f"   Expected packet size: {self.packet_size} bytes\n"
                        f"   Buffer length: {len(self.net_buf)} bytes\n"
                        f"   This indicates civserver initiated disconnect\n"
                        f"   Calling close_connection()..."
                    )
                    self.close_connection()
                    return None

                return data
        except socket.timeout:
            self.send_packets_to_client()
            self.send_packets_to_civserver()
            return None
        except OSError:
            return None

    def close_connection(self):
        import traceback

        if (logger.isEnabledFor(logging.INFO)):
            logger.info(
                f"Server connection closed. Removing civcom thread for {self.username}\n"
                f"   Connection age: {time.time() - self.connect_time:.1f}s\n"
                f"   Call stack:\n{''.join(traceback.format_stack())}"
            )

        # Flush buffers
        self.send_packets_to_client()
        self.send_packets_to_civserver()

        if (hasattr(self.civwebserver, "civcoms") and self.key in list(self.civwebserver.civcoms.keys())):
            del self.civwebserver.civcoms[self.key]

        if (self.socket is not None):
            self.socket.close()
            self.socket = None
        self.civwebserver = None
        self.stopped = True

    # queue messages to be sent to client.
    def send_buffer_append(self, data):
        try:
            self.send_buffer.append(
                data.decode(
                    encoding="utf-8",
                    errors="ignore"))
        except UnicodeDecodeError:
            if (logger.isEnabledFor(logging.ERROR)):
                logger.error(
                    "Unable to decode string from civcom socket, for user: " +
                    self.username)
            return

    # sends packets to client (WebSockets client / browser)
    def send_packets_to_client(self):
        packet = self.get_client_result_string()
        if (packet is not None and self.civwebserver is not None):
            # Check if handler has buffering enabled (LLM agents buffer during auth)
            # If buffer_enabled=True, store packets instead of sending them immediately
            if hasattr(self.civwebserver, 'buffer_enabled') and self.civwebserver.buffer_enabled:
                # Buffer the packet instead of sending it
                if hasattr(self.civwebserver, 'packet_buffer'):
                    # Check buffer size limits to prevent memory exhaustion
                    # Import limits from llm_handler at runtime to avoid circular import
                    try:
                        from llm_handler import MAX_PACKET_BUFFER_SIZE, MAX_PACKET_BUFFER_BYTES

                        buffer_count = len(self.civwebserver.packet_buffer)
                        current_size = sum(len(p.encode('utf-8')) for p in self.civwebserver.packet_buffer)
                        packet_size = len(packet.encode('utf-8'))

                        # Check if adding this packet would exceed limits
                        if buffer_count >= MAX_PACKET_BUFFER_SIZE:
                            logger.error(
                                f"❌ PACKET BUFFER OVERFLOW for {self.username}: "
                                f"{buffer_count} packets exceeds limit of {MAX_PACKET_BUFFER_SIZE}. "
                                f"Closing connection to prevent memory exhaustion."
                            )
                            self.civwebserver.buffer_enabled = False
                            self.civwebserver.packet_buffer.clear()
                            self.civwebserver.close()
                            return

                        if current_size + packet_size > MAX_PACKET_BUFFER_BYTES:
                            logger.error(
                                f"❌ PACKET BUFFER SIZE OVERFLOW for {self.username}: "
                                f"{(current_size + packet_size)/(1024*1024):.2f}MB exceeds limit of "
                                f"{MAX_PACKET_BUFFER_BYTES/(1024*1024):.0f}MB. "
                                f"Closing connection to prevent memory exhaustion."
                            )
                            self.civwebserver.buffer_enabled = False
                            self.civwebserver.packet_buffer.clear()
                            self.civwebserver.close()
                            return

                        # Buffer is within limits - add packet
                        self.civwebserver.packet_buffer.append(packet)
                        buffer_count += 1
                        logger.debug(
                            f"🔒 BUFFERING PACKET during auth for {self.username}: "
                            f"{packet_size:,} bytes ({packet_size/(1024*1024):.2f}MB), "
                            f"buffer count: {buffer_count}, "
                            f"total size: {(current_size + packet_size)/(1024*1024):.2f}MB"
                        )
                    except ImportError:
                        # Fallback if llm_handler not available (shouldn't happen in production)
                        logger.warning(f"Could not import buffer limits - buffering without size checks")
                        self.civwebserver.packet_buffer.append(packet)
                        packet_size = len(packet.encode('utf-8'))
                        buffer_count = len(self.civwebserver.packet_buffer)
                        logger.debug(
                            f"🔒 BUFFERING PACKET during auth for {self.username}: "
                            f"{packet_size:,} bytes ({packet_size/(1024*1024):.2f}MB), "
                            f"buffer count: {buffer_count}"
                        )
                return  # Don't send, just buffer

            # Normal flow: send packet immediately
            # Log large packet sizes and apply rate limiting for critical-size packets
            packet_size = len(packet.encode('utf-8'))

            # Rate limiting and logging based on packet size
            if packet_size > CRITICAL_PACKET_SIZE:
                logger.warning(
                    f"📦 CRITICAL PACKET SIZE: Sending {packet_size:,} bytes ({packet_size/(1024*1024):.2f}MB) "
                    f"to {self.username} - applying {LARGE_PACKET_DELAY_MS}ms rate limit"
                )
                # Log first 200 chars to see packet type
                logger.debug(f"   Packet preview: {packet[:200]}...")
            elif packet_size > WARNING_PACKET_SIZE:
                logger.info(
                    f"📦 Large packet: Sending {packet_size:,} bytes ({packet_size/(1024*1024):.2f}MB) "
                    f"to {self.username}"
                )

            # Calls the write_message callback on the next Tornado I/O loop iteration (thread safely).
            # Uses _safe_write_message for error tracking and proactive pause capability.
            conn = self.civwebserver
            # Capture packet and size for the lambda closure
            p, ps = packet, packet_size

            # Apply rate limiting for critical-size packets to prevent WebSocket buffer overflow
            if packet_size > CRITICAL_PACKET_SIZE:
                # Schedule send with delay to give client time to process
                delay_seconds = LARGE_PACKET_DELAY_MS / 1000.0
                conn.io_loop.call_later(delay_seconds, lambda: self._safe_write_message(conn, p, ps))
            else:
                # Normal send - no delay
                conn.io_loop.add_callback(lambda: self._safe_write_message(conn, p, ps))

    def get_client_result_string(self):
        result = ""
        try:
            if len(self.send_buffer) > 0:
                result = "[" + ",".join(self.send_buffer) + "]"
            else:
                result = None
        finally:
            del self.send_buffer[:]
        return result

    def send_error_to_client(self, message):
        if (logger.isEnabledFor(logging.ERROR)):
            logger.error(message)
        self.send_buffer_append(
            ("{\"pid\":25,\"event\":100,\"message\":\"" + message + "\"}").encode("utf-8"))

    # Send packets from freeciv-proxy to civserver
    def send_packets_to_civserver(self):
        if (self.civserver_messages is None or self.socket is None):
            logger.debug(f"Cannot send packets for {self.username}: messages={'set' if self.civserver_messages else 'None'}, socket={'set' if self.socket else 'None'}")
            return

        if len(self.civserver_messages) > 0:
            logger.debug(f"Sending {len(self.civserver_messages)} packet(s) to civserver for {self.username}")

        try:
            for net_message in self.civserver_messages:
                utf8_encoded = net_message.encode('utf-8')
                header = pack('>H', len(utf8_encoded) + 3)
                self.socket.sendall(
                    header +
                    utf8_encoded +
                    b'\0')

                # Log important packets
                try:
                    msg_json = json.loads(net_message)
                    pid = msg_json.get('pid')
                    message_text = msg_json.get('message', '')

                    if pid == PACKET_CHAT_MSG and '/start' in message_text:
                        logger.info(f"Sent /start command to civserver on port {self.civserverport} for {self.username}")
                    elif pid == PACKET_CHAT_MSG:
                        logger.debug(f"Sent chat message to civserver: {message_text}")
                    elif pid == PACKET_NATION_SELECT_REQ:  # PACKET_NATION_SELECT_REQ
                        logger.info(f"Sent PACKET_NATION_SELECT_REQ (nation_no={msg_json.get('nation_no')}) for {self.username}")
                    elif pid == PACKET_PLAYER_READY:  # PACKET_PLAYER_READY
                        logger.info(f"Sent PACKET_PLAYER_READY (player_no={msg_json.get('player_no')}) for {self.username}")
                    elif pid == PACKET_UNIT_ORDERS:  # PACKET_UNIT_ORDERS - log all unit orders for debugging
                        unit_id = msg_json.get('unit_id')
                        dest_tile = msg_json.get('dest_tile')
                        orders = msg_json.get('orders', [])
                        logger.info(f"📦 Sent PACKET_UNIT_ORDERS pid=73: unit={unit_id} dest_tile={dest_tile} orders={orders}")
                    else:
                        logger.debug(f"Sent packet pid={pid} for {self.username}")
                except:
                    logger.debug(f"Sent packet to civserver for {self.username}")
        except Exception as e:
            logger.error(f"Failed to send packet to civserver port {self.civserverport}: {e}")
            self.send_error_to_client(
                "Proxy unable to communicate with civserver on port " + str(self.civserverport))
        finally:
            self.civserver_messages = []

    # queue message for the civserver
    def queue_to_civserver(self, message):
        self.civserver_messages.append(message)

    def parse_and_store_packet(self, packet_json):
        """Parse incoming packets and store relevant game state"""
        try:
            packet = json.loads(packet_json)
            packet_type = packet.get('pid')

            # Configurable packet logging for debugging (set CIVCOM_PACKET_LOG_LIMIT env var)
            if not hasattr(self, '_packet_type_log_count'):
                self._packet_type_log_count = 0
                self._packet_log_limit = int(os.getenv('CIVCOM_PACKET_LOG_LIMIT', '10'))

            if self._packet_type_log_count < self._packet_log_limit:
                self._packet_type_log_count += 1
                packet_name = get_packet_name(packet_type)
                logger.debug(f"Received packet: {packet_name} (pid={packet_type}) for {self.username}")
                # Log details for critical packets
                if packet_type in [PACKET_CONN_INFO, PACKET_PLAYER_INFO]:
                    logger.debug(f"Packet details: {str(packet)[:200]}")

            # CRITICAL: Server join reply - must respond with PACKET_CLIENT_INFO to complete handshake
            # Without this response, civserver rejects the connection as "incomplete"
            if packet_type == PACKET_SERVER_JOIN_REPLY:
                you_can_join = packet.get('you_can_join', False)
                conn_id = packet.get('conn_id', -1)
                logger.info(f"Received PACKET_SERVER_JOIN_REPLY: you_can_join={you_can_join}, conn_id={conn_id} for {self.username}")

                if you_can_join:
                    # Send PACKET_CLIENT_INFO to complete the connection handshake
                    # gui=7 is GUI_WEB (matches the web client)
                    client_info_packet = json.dumps({
                        'pid': PACKET_CLIENT_INFO,
                        'gui': 7,  # GUI_WEB
                        'emerg_version': 0,
                        'distribution': ''
                    })
                    logger.info(f"Sending PACKET_CLIENT_INFO to complete handshake for {self.username}")
                    self.queue_to_civserver(client_info_packet)
                else:
                    message = packet.get('message', 'Unknown rejection reason')
                    logger.error(f"Server rejected join request for {self.username}: {message}")

            # Map info packet (contains xsize, ysize)
            elif packet_type == PACKET_MAP_INFO:
                self.map_info = {
                    'width': packet.get('xsize', 0),
                    'height': packet.get('ysize', 0),
                    'tiles': [],
                    'visibility': {}
                }
                logger.info(f"Stored map info: {self.map_info['width']}x{self.map_info['height']}")

            # Game info packet (turn number, citymindist, timeout, etc)
            elif packet_type == PACKET_GAME_INFO:
                new_turn = packet.get('turn', self.game_turn)
                if new_turn > self.game_turn:
                    logger.info(f"Turn advanced: {self.game_turn} -> {new_turn}")
                self.game_turn = new_turn
                self.game_info_received = True  # Mark that we received real game info from server
                # Extract citymindist (minimum distance between cities) from game info
                # This is critical for validating city founding actions
                citymindist = packet.get('citymindist')
                if citymindist is not None:
                    self.citymindist = citymindist
                    logger.debug(f"Updated citymindist: {self.citymindist}")
                # Capture timeout for pause/resume functionality
                # Only store positive timeouts - zero means game is paused (no turn timer)
                # We preserve the original positive timeout so we can restore it on resume
                timeout = packet.get('timeout')
                if timeout is not None and timeout > 0:
                    self.game_timeout = timeout
                    logger.debug(f"Stored game timeout: {self.game_timeout}s")
                logger.debug(f"Updated game turn: {self.game_turn}")

            # Begin turn packet - authoritative server signal that new turn has started
            # This is sent when ALL players have finished their turn
            elif packet_type == PACKET_BEGIN_TURN:
                new_turn = packet.get('turn', self.game_turn)
                logger.info(f"🔄 PACKET_BEGIN_TURN received: turn {new_turn}")
                self.game_turn = new_turn
                self.turn_started = True  # Signal to state_query that turn is active
                self.turn_advance_event.set()  # Wake up any coroutines waiting for turn start

            # CRITICAL: Connection info packet - contains player_num assignment
            # This is the FIX for the PACKET_CONN_INFO bug
            elif packet_type == PACKET_CONN_INFO:
                # This packet is sent after successful join and contains the player_num
                conn_id = packet.get('id')
                player_num = packet.get('player_num')
                packet_username = packet.get('username', '')
                logger.debug(f"Received PACKET_CONN_INFO: conn_id={conn_id}, player_num={player_num}, username='{packet_username}' for {self.username}")

                # Check if this is our connection by matching username
                # CRITICAL: FreeCiv uses MAX_NUM_PLAYER_SLOTS (512) as sentinel for "no player assigned"
                # Only accept player_num < 512 as valid player IDs
                if packet_username == self.username and player_num is not None and player_num < 512:
                    # Store player_num as player_id - CRITICAL for game flow
                    self.player_id = player_num
                    logger.info(f"Player number {player_num} assigned to connection {self.username} via PACKET_CONN_INFO")
                elif packet_username == self.username and player_num == 512:
                    logger.debug(f"PACKET_CONN_INFO has player_num=512 (unassigned sentinel) - waiting for PACKET_PLAYER_INFO")

            # Player info packet (detailed player data sent AFTER nation selection)
            elif packet_type == PACKET_PLAYER_INFO:
                # Update or add player to list
                player_id = packet.get('playerno')
                packet_username = packet.get('username', '')
                logger.debug(f"Received PACKET_PLAYER_INFO: playerno={player_id}, username='{packet_username}' for {self.username}")
                if player_id is not None:
                    # Check if this player info is for our connection
                    if packet_username == self.username:
                        # This is OUR player! Store the player_id (fallback if CONN_INFO didn't set it)
                        self.player_id = player_id
                        logger.info(f"Player ID {player_id} assigned to connection {self.username} via PACKET_PLAYER_INFO")

                    # Remove old entry if exists
                    self.all_players = [p for p in self.all_players if p.get('id') != player_id]

                    # Normalize nation field: convert integer ID to string name
                    nation_raw = packet.get('nation')
                    nation_name = self._get_nation_name(nation_raw)

                    # Add updated player
                    # Note: PACKET_PLAYER_INFO has 'name' (leader name) and 'username' (connection name)
                    # Use 'name' for display as it contains the agent/player name (e.g., "Claude_Sonnet_45")
                    # 'username' is the WebSocket connection identifier which may differ
                    player_name = packet.get('name')
                    if player_name is None:
                        # Log if name field is missing - helps debug protocol issues
                        logger.warning(f"PACKET_PLAYER_INFO missing 'name' field for player {player_id}, using fallback")
                        player_name = f'Player{player_id}'
                    self.all_players.append({
                        'id': player_id,
                        'name': player_name,
                        'nation': nation_name,  # String name (e.g., 'Romans', 'Americans')
                        'score': packet.get('score', 0),
                        'gold': packet.get('gold', 0)
                    })

            # NOTE: PACKET_RESEARCH_INFO is handled later in the packet processing chain
            # at line ~1465 where it's stored in self.research_info (the authoritative store)

            # Unit info packet - stores units by ID for all players
            elif packet_type == PACKET_UNIT_INFO:
                unit_id = packet.get('id')
                owner = packet.get('owner')
                if unit_id is not None and owner is not None:
                    # Get raw type ID (integer from FreeCiv server)
                    unit_type_raw = packet.get('type')

                    # Convert integer type ID to human-readable string name
                    unit_type_name = get_unit_type_name(unit_type_raw)

                    def get_coords_from_tile_index(tile_idx):
                        # tile['index'] = x + y * map['xsize'];
                        # tile['x'] = x;
                        # tile['y'] = y;
                        xsize = self.map_info.get('width', 1)
                        x = tile_idx % xsize
                        y = tile_idx // xsize
                        return x, y

                    tile_idx = packet.get("tile")
                    x, y = get_coords_from_tile_index(tile_idx)

                    # Normalize activity field: convert integer ID to string name
                    activity_raw = packet.get('activity')
                    activity_name = get_activity_name(activity_raw)

                    unit_data = {
                        'id': unit_id,
                        'owner': owner,
                        'type': unit_type_name,  # String name (e.g., 'warriors', 'settlers')
                        'type_id': unit_type_raw,  # Preserve original integer for debugging/reference
                        'tile': tile_idx,
                        'homecity': packet.get('homecity', 0),
                        'moves_left': packet.get('movesleft', 0), 
                        'hp': packet.get('hp', 0),
                        'veteran': packet.get('veteran', 0),
                        'transported': packet.get('transported', False),
                        'done_moving': packet.get('done_moving', False),
                        'activity': activity_name,  # String name (e.g., 'idle', 'sentry') or None
                        'x': x,
                        'y': y
                    }

                    # Convert player_units to dict if it's still a list
                    if not isinstance(self.player_units, dict):
                        self.player_units = {}

                    self.player_units[unit_id] = unit_data
                    total_units = len(self.player_units)

                    # Track when we receive our first unit (for initial state readiness)
                    if not self.initial_units_received and self.player_id is not None and owner == self.player_id:
                        self.initial_units_received = True
                        logger.info(f"🎯 CivCom[{self.username}] received first unit for player {self.player_id} - initial state ready")
                        # Notify LLM handler that game state is ready (if connected via LLM gateway)
                        # This allows agents to wait for this signal before querying state
                        if hasattr(self.civwebserver, 'send_game_ready'):
                            try:
                                self.civwebserver.send_game_ready()
                            except Exception as e:
                                logger.error(f"Failed to send game_ready signal: {e}", exc_info=True)

                    logger.info(
                        f"✅ CivCom[{self.username}] stored unit:\n"
                        f"   unit_id={unit_id}, type={unit_type_name}, owner={owner}\n"
                        f"   Total units in this CivCom: {total_units}"
                    )

            # City info packet - stores cities by ID for all players
            # NOTE: Verified against packets.def - production is split into production_kind/production_value
            elif packet_type == PACKET_CITY_INFO:
                city_id = packet.get('id')
                owner = packet.get('owner')
                if city_id is not None and owner is not None:
                    # Calculate x/y from tile index
                    tile_idx = packet.get('tile')
                    x, y = None, None
                    if tile_idx is not None:
                        xsize = self.map_info.get('width', 80)
                        x = tile_idx % xsize
                        y = tile_idx // xsize
                    
                    city_data = {
                        'id': city_id,
                        'owner': owner,
                        'name': packet.get('name', f'City{city_id}'),
                        'tile': tile_idx,
                        'x': x,
                        'y': y,
                        'size': packet.get('size', 1),
                        # Production is split into kind (0=unit, 1=improvement) and value (type id)
                        'production_kind': packet.get('production_kind'),
                        'production_value': packet.get('production_value'),
                        'food_stock': packet.get('food_stock', 0),
                        'shield_stock': packet.get('shield_stock', 0),
                        # surplus and prod are arrays indexed by O_FOOD, O_SHIELD, O_TRADE, etc.
                        'surplus': packet.get('surplus', []),
                        'prod': packet.get('prod', []),
                    }

                    # Convert player_cities to dict if it's still a list
                    if not isinstance(self.player_cities, dict):
                        self.player_cities = {}

                    self.player_cities[city_id] = city_data
                    logger.info(f"✓ Stored city {city_id} ({city_data['name']}, size={city_data['size']}) for owner {owner}")

            # Web city info addition packet - contains buildable units/improvements as bitvectors
            # This packet follows PACKET_CITY_INFO and provides additional web-specific data
            elif packet_type == PACKET_WEB_CITY_INFO_ADDITION:
                city_id = packet.get('id')
                if city_id is not None and city_id in self.player_cities:
                    city = self.player_cities[city_id]

                    # Parse bitvectors for buildable options
                    can_build_unit_raw = packet.get('can_build_unit', [])
                    can_build_impr_raw = packet.get('can_build_improvement', [])

                    can_build_unit_bv = BitVector(can_build_unit_raw)
                    can_build_impr_bv = BitVector(can_build_impr_raw)

                    # Resolve bit positions to unit/improvement names using ruleset data
                    can_build = []

                    # Units - bit position corresponds to unit type ID
                    for unit_id in can_build_unit_bv.to_list():
                        utype = self.unit_types.get(unit_id)
                        if utype:
                            can_build.append({
                                'type': 'unit',
                                'id': unit_id,
                                'name': utype.get('name', f'Unit{unit_id}')
                            })

                    # Improvements - bit position corresponds to improvement ID
                    for impr_id in can_build_impr_bv.to_list():
                        impr = self.improvements.get(impr_id)
                        if impr:
                            can_build.append({
                                'type': 'improvement',
                                'id': impr_id,
                                'name': impr.get('name', f'Building{impr_id}')
                            })

                    city['can_build'] = can_build

                    # Also store granary info if present
                    if 'granary_size' in packet:
                        city['granary_size'] = packet['granary_size']
                    if 'granary_turns' in packet:
                        city['granary_turns'] = packet['granary_turns']

                    logger.debug(f"Updated city {city_id} with {len(can_build)} buildable options")

            # Unit removal packet - remove unit when consumed or destroyed
            # This is sent when:
            # - Settlers build a city (unit is consumed)
            # - Unit is destroyed in combat
            # - Unit is disbanded by player
            elif packet_type == PACKET_UNIT_REMOVE:
                unit_id = packet.get('unit_id')
                if unit_id is not None and isinstance(self.player_units, dict):
                    if unit_id in self.player_units:
                        removed_unit = self.player_units.pop(unit_id)
                        unit_type = removed_unit.get('utype', 'unknown')
                        logger.info(f"✓ Removed unit {unit_id} (type={unit_type}) - consumed/destroyed")
                    else:
                        logger.debug(f"Received PACKET_UNIT_REMOVE for unit {unit_id} (not in our tracked units)")

            # Tile info packet - visibility/fog-of-war updates after movement
            # Sent by server when units move and reveal new tiles
            # Critical for action validation (terrain checks, city proximity)
            # NOTE: packets.def shows PACKET_TILE_INFO has 'tile' (index), not 'x'/'y'
            elif packet_type == PACKET_TILE_INFO:
                tile_index = packet.get('tile')
                terrain = packet.get('terrain')
                # Calculate x/y from tile index (same formula as PACKET_UNIT_INFO)
                if tile_index is not None:
                    xsize = self.map_info.get('width', 80)
                    tile_x = tile_index % xsize
                    tile_y = tile_index // xsize
                    # Store comprehensive tile data for action validation
                    self.tiles[tile_index] = {
                        'x': tile_x,
                        'y': tile_y,
                        'terrain': terrain,
                        'extras': packet.get('extras', []),
                        'resource': packet.get('resource'),
                        'owner': packet.get('owner'),
                        'worked': packet.get('worked'),
                        'known': packet.get('known', 0),
                    }
                    logger.debug(f"Tile update at ({tile_x}, {tile_y}) - terrain={terrain}, index={tile_index}")

            # Unit short info packet - abbreviated unit updates
            # Sent by server for units entering/leaving vision range
            # More efficient than full PACKET_UNIT_INFO for frequent updates
            elif packet_type == PACKET_UNIT_SHORT_INFO:
                unit_id = packet.get('id')
                owner = packet.get('owner')
                if unit_id is not None:
                    logger.debug(f"Unit short info for unit {unit_id} (owner={owner})")
                    # Could update existing unit data in self.player_units if needed

            # Ruleset nation packet - stores nation ID to name mappings
            elif packet_type == PACKET_RULESET_NATION:
                nation_id = packet.get('id')
                # Try multiple fields for nation name (different packet versions use different fields)
                nation_name = packet.get('adjective') or packet.get('plural') or packet.get('rule_name', '')
                if nation_id is not None and nation_name:
                    self.nations[nation_name] = nation_id
                    logger.debug(f"Registered nation: {nation_name} -> ID {nation_id}")

            # RULESET unit packet - defines unit types (Warriors, Settlers, etc.)
            # Mirrors FreeCiv web client's unit_types[] storage pattern
            # Used by RulesetMapper for production name→ID mapping
            elif packet_type == PACKET_RULESET_UNIT:
                unit_id = packet.get('id')
                unit_name = packet.get('name')
                if unit_id is not None and unit_name:
                    self.unit_types[unit_id] = packet
                    # Check for pending utype_actions from PACKET_WEB_RULESET_UNIT_ADDITION
                    # (handles case where addition packet arrived before base packet)
                    if hasattr(self, '_pending_unit_additions') and unit_id in self._pending_unit_additions:
                        self.unit_types[unit_id]['utype_actions'] = self._pending_unit_additions.pop(unit_id)
                        logger.debug(f"Merged buffered utype_actions for unit type: {unit_name} (id={unit_id})")
                    logger.debug(f"Registered unit type: {unit_name} (id={unit_id})")

            # WEB_RULESET_UNIT_ADDITION packet - contains utype_actions bitfield
            # This packet is sent AFTER PACKET_RULESET_UNIT and contains the action
            # capability bitfield that defines what actions each unit type can perform.
            # Must be merged into existing unit_types entry (mirrors web client behavior).
            # See: freeciv-web/src/main/webapp/javascript/packhand.js handle_web_ruleset_unit_addition()
            elif packet_type == PACKET_WEB_RULESET_UNIT_ADDITION:
                unit_id = packet.get('id')
                if unit_id is not None:
                    if unit_id in self.unit_types:
                        # Merge utype_actions into existing unit type entry
                        # utype_actions is a list of integers representing the action bitfield
                        utype_actions = packet.get('utype_actions', [])
                        self.unit_types[unit_id]['utype_actions'] = utype_actions
                        unit_name = self.unit_types[unit_id].get('name', f'unit_{unit_id}')
                        logger.debug(f"Merged utype_actions for unit type: {unit_name} (id={unit_id}, actions_len={len(utype_actions)})")
                    else:
                        # Handle case where addition packet arrives before base packet
                        # Store it for later merging when PACKET_RULESET_UNIT arrives
                        if not hasattr(self, '_pending_unit_additions'):
                            self._pending_unit_additions = {}
                        self._pending_unit_additions[unit_id] = packet.get('utype_actions', [])
                        logger.debug(f"Buffered utype_actions for unit type id={unit_id} (base packet not yet received)")

            # RULESET building packet - defines improvements (Barracks, Granary, etc.)
            # Mirrors FreeCiv web client's improvements[] storage pattern
            # Used by RulesetMapper for production name→ID mapping
            elif packet_type == PACKET_RULESET_BUILDING:
                building_id = packet.get('id')
                building_name = packet.get('name')
                if building_id is not None and building_name:
                    self.improvements[building_id] = packet
                    logger.debug(f"Registered building: {building_name} (id={building_id})")

            # RULESET tech packet - defines technologies (Alphabet, Bronze Working, etc.)
            # Mirrors FreeCiv web client's techs[] storage pattern
            # Used by RulesetMapper for tech name→ID mapping in PACKET_PLAYER_RESEARCH
            elif packet_type == PACKET_RULESET_TECH:
                tech_id = packet.get('id')
                # Strip ?tech: translation prefix (e.g., "?tech:Alphabet" -> "Alphabet")
                # This matches FreeCiv web client's handle_ruleset_tech() behavior
                tech_name = packet.get('name', '').replace('?tech:', '')
                if tech_id is not None and tech_name:
                    self.techs[tech_id] = packet
                    # Store normalized name in packet for easier lookup
                    self.techs[tech_id]['name'] = tech_name
                    logger.debug(f"Registered tech: {tech_name} (id={tech_id})")

            # RESEARCH INFO packet - tracks tech progress and inventions for each player
            # Contains inventions array showing which techs are KNOWN/PREREQS_KNOWN/UNKNOWN
            elif packet_type == PACKET_RESEARCH_INFO:
                research_id = packet.get('id')
                if research_id is not None:
                    # Check if research state changed to invalidate tech action cache
                    old_research = self.research_info.get(research_id, {})
                    old_researching = old_research.get('researching')
                    new_researching = packet.get('researching')

                    # Update research info
                    self.research_info[research_id] = packet

                    # If researching state changed, invalidate tech action cache
                    # This ensures legal_actions returns fresh tech choices after selection
                    if old_researching != new_researching:
                        self.invalidate_action_cache(research_id, 'tech')
                        logger.info(
                            f"Research state changed for player {research_id}: "
                            f"{old_researching} -> {new_researching}, tech action cache invalidated"
                        )
                    else:
                        logger.debug(
                            f"Updated research info for player {research_id}: "
                            f"researching={new_researching}, "
                            f"techs_researched={packet.get('techs_researched')}"
                        )

            # RULESET terrain packet - defines terrain types (Plains, Ocean, Hills, etc.)
            # Used for movement cost calculations and action validity checks
            elif packet_type == PACKET_RULESET_TERRAIN:
                terrain_id = packet.get('id')
                terrain_name = packet.get('name', '')
                native_to = packet.get('native_to', [])
                tclass = packet.get('tclass', 0)
                if terrain_id is not None:
                    self.terrains[terrain_id] = packet
                    logger.debug(
                        f"Registered terrain: {terrain_name} (id={terrain_id}, "
                        f"tclass={tclass}, native_to={native_to})"
                    )
            
            # RULESET extra packet - defines extras (roads, irrigation, mines, etc.)
            # Used for terrain improvement action validity
            elif packet_type == PACKET_RULESET_EXTRA:
                extra_id = packet.get('id')
                extra_name = packet.get('name', '')
                if extra_id is not None:
                    self.extras[extra_id] = packet
                    logger.debug(f"Registered extra: {extra_name} (id={extra_id})")
            
            # RULESET unit class packet - defines unit classes (Land, Sea, Air, etc.)
            # Used for terrain accessibility checks
            elif packet_type == PACKET_RULESET_UNIT_CLASS:
                class_id = packet.get('id')
                class_name = packet.get('name', '')
                if class_id is not None:
                    self.unit_classes[class_id] = packet
                    logger.debug(f"Registered unit class: {class_name} (id={class_id})")

            # CRITICAL: Connection ping packet - MUST respond with pong to keep connection alive
            # FreeCiv civserver sends PACKET_CONN_PING every ~2 minutes to verify connection health
            # Without responding with PACKET_CONN_PONG, the server will timeout and disconnect with "ping timeout"
            # This was causing agents to disconnect at exactly ~2 minutes after connection
            elif packet_type == PACKET_CONN_PING:
                # Immediately respond with pong packet to keep connection alive
                pong_packet = json.dumps({"pid": PACKET_CONN_PONG})
                logger.debug(f"[PING] Received PACKET_CONN_PING from civserver, responding with PACKET_CONN_PONG for {self.username}")
                self.queue_to_civserver(pong_packet)

            # Default handler for unknown/unhandled packet types
            # This prevents "unsupported packet type" disconnects from civserver
            else:
                # Log debug info for unhandled packets (helps identify missing handlers)
                logger.debug(f"Received unhandled packet type {packet_type} for {self.username}")
                # Don't crash - just acknowledge and continue

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"Could not parse packet for state storage: {e}")

    # LLM-optimized state query methods
    def handle_state_query(self, player_id, format='full'):
        """Handle LLM state query requests with different formats"""
        if format == 'llm_optimized':
            return self.build_llm_optimized_state(player_id)
        elif format == 'delta':
            return self.get_state_delta(player_id)
        else:
            return self.get_full_state(player_id)

    def build_llm_optimized_state(self, player_id):
        """Build compressed state for LLMs (target < 4KB)"""
        # Ensure we always have valid game state values (defensive against early queries)
        game_turn = getattr(self, 'game_turn', 1)
        game_phase = getattr(self, 'game_phase', 'movement')

        # CRITICAL: Always include 'game' dict at top level for agent-clash compatibility
        # This dict is REQUIRED by freeciv_state.py validation
        game_dict = {
            'turn': game_turn,
            'phase': game_phase,
            'is_over': getattr(self, 'game_is_over', False),
            'current_player': player_id
        }

        # Basic game state structure for LLM consumption
        state = {
            'turn': game_turn,
            'phase': game_phase,
            'player_id': player_id,
            'game': game_dict,  # Required field - must always be present
            'strategic': self._build_strategic_view(player_id),
            'tactical': self._build_tactical_view(player_id),
            'economic': self._build_economic_view(player_id),
            'legal_actions': self._get_legal_actions_optimized(player_id)
        }
        return state

    def _build_strategic_view(self, player_id):
        """Build strategic overview for LLM decision making"""
        return {
            'score': getattr(self, 'player_score', 0),
            'cities_count': len(getattr(self, 'player_cities', [])),
            'units_count': len(getattr(self, 'player_units', [])),
            'tech_level': getattr(self, 'tech_count', 0),
            'gold': getattr(self, 'player_gold', 0),
            'turn_progress': getattr(self, 'turn_progress', 'beginning')
        }

    def _build_tactical_view(self, player_id):
        """Build tactical view focusing on immediate unit/city actions"""
        tactical = {
            'active_units': [],
            'cities_needing_orders': [],
            'visible_threats': [],
            'exploration_targets': []
        }

        # Add simplified unit info (limit to 10 most important units)
        units = getattr(self, 'player_units', [])[:10]
        for unit in units:
            if isinstance(unit, dict):
                tactical['active_units'].append({
                    'id': unit.get('id'),
                    'type': unit.get('type'),
                    'x': unit.get('x'),
                    'y': unit.get('y'),
                    'moves_left': unit.get('moves_left', 0),
                    'can_act': unit.get('moves_left', 0) > 0
                })

        return tactical

    def _build_economic_view(self, player_id):
        """Build economic overview for resource management decisions"""
        return {
            'gold': getattr(self, 'player_gold', 0),
            'gold_per_turn': getattr(self, 'gold_income', 0),
            'research': getattr(self, 'research_progress', 0),
            'research_target': getattr(self, 'research_target', ''),
            'total_production': getattr(self, 'total_production', 0),
            'total_trade': getattr(self, 'total_trade', 0)
        }

    def _is_city_producing_coinage(self, city):
        """Check if a city is producing Coinage (infinite gold generation)
        
        Args:
            city: City packet dict with production_kind and production_value
            
        Returns:
            bool: True if city is producing Coinage, False otherwise
        """
        production_kind = city.get('production_kind')
        production_value = city.get('production_value')
        
        # Check if producing an improvement (VUT_IMPROVEMENT = 3)
        if production_kind != VUT_IMPROVEMENT:
            return False
        
        # Look up the improvement by ID
        improvement = self.improvements.get(production_value)
        if not improvement:
            return False
        
        # Check if improvement name is "Coinage"
        return improvement.get('name') == 'Coinage'

    def _get_unit_actions(self, player_id, max_units=5):
        """Get per-unit legal actions (NOT CACHED - regenerated every call).
        
        Unit actions are not cached because every unit move affects what other units can do.
        
        Uses StateExtractor.get_unit_actions() to ensure consistency with
        unit_actions_query endpoint - same logic, same results.
        
        Returns complete action format from StateExtractor with all validation fields:
        - 'action': action name (e.g., 'move', 'build_city', 'fortify')
        - 'params': dict of action parameters (e.g., {'direction': 'n'} for move)
        - 'is_valid': boolean indicating if action can be executed
        - 'reason': optional string explaining why action is invalid
        - 'action_id': FreeCiv action constant ID
        - 'unit_id': unit ID this action applies to
        - 'type': added field for LLM categorization ('unit_move' or 'unit_action')
        
        Args:
            player_id: The player ID
            max_units: Maximum number of units to generate actions for
            
        Returns:
            list: List of complete unit action dicts with full validation info
        """
        actions = []
        
        # Import StateExtractor to reuse unit action generation logic
        from state_extractor import StateExtractor
        
        # Handle both dict and list formats for player_units
        units = self.player_units
        if isinstance(units, list):
            units = {str(u.get('id', i)): u for i, u in enumerate(units) if isinstance(u, dict)}
        elif not isinstance(units, dict):
            return actions  # Return empty if invalid format
        
        # Create StateExtractor instance for action generation
        # Pass self as civcom to ensure consistent data source
        extractor = StateExtractor(civcom=self)
        
        unit_count = 0
        for unit_id, unit in units.items():
            if unit_count >= max_units:
                break
            
            # Only include units with moves remaining
            if unit.get('moves_left', 0) <= 0:
                continue
            
            unit_count += 1
            
            # Use StateExtractor's get_unit_actions which calls _generate_unit_actions
            # This ensures consistency with unit_actions_query
            try:
                result = extractor.get_unit_actions(int(unit_id), player_id)
                if result.get('error'):
                    # Skip units with errors
                    continue
                
                # Keep all actions with full detail from StateExtractor
                # Format: {'action': 'move', 'params': {...}, 'is_valid': True, 'unit_id': ...}
                # We need to preserve ALL fields for validation
                for action in result.get('actions', []):
                    # Skip low-value generic actions
                    if action.get('action') in ('skip', 'sentry', 'continue_work'):
                        continue
                    
                    # Add type field for LLM categorization while preserving all other fields
                    action_copy = action.copy()
                    action_name = action_copy.get('action')
                    
                    if action_name == 'move':
                        action_copy['type'] = 'unit_move'
                    else:
                        action_copy['type'] = 'unit_action'
                    
                    actions.append(action_copy)
            except Exception as e:
                # Log at warning level so errors are visible, but continue processing other units
                logger.warning(f"Failed to get actions for unit {unit_id}: {e}")
                continue
        
        return actions

    def _get_city_production_actions(self, player_id, max_cities=3):
        """Get per-city production change actions (CACHED per turn).
        
        Only returns production actions if:
        - shield_stock == 0 (production just finished, need new selection)
        - OR production is Coinage (infinite production, can always change)
        
        Args:
            player_id: The player ID
            max_cities: Maximum number of cities to generate actions for
            
        Returns:
            list: List of city production action dicts
        """
        turn = self.game_turn
        cache_key = f"{turn}_{player_id}_city_actions"
        
        # Check cache first
        if cache_key in self._action_cache:
            return self._action_cache[cache_key]
        
        actions = []
        
        # Handle both dict and list formats for player_cities
        cities = self.player_cities
        if isinstance(cities, list):
            cities = {str(c.get('id', i)): c for i, c in enumerate(cities) if isinstance(c, dict)}
        elif not isinstance(cities, dict):
            self._action_cache[cache_key] = actions
            return actions  # Return empty if invalid format
        
        city_count = 0
        for city_id, city in cities.items():
            if city_count >= max_cities:
                break
            
            # Check if city owner matches player
            if city.get('owner') != player_id:
                continue
            
            # Only include cities that need production selection:
            # 1. Production just finished (shield_stock == 0)
            # 2. OR producing Coinage (infinite, can always change)
            shield_stock = city.get('shield_stock', 0)
            is_coinage = self._is_city_producing_coinage(city)
            
            if shield_stock != 0 and not is_coinage:
                continue  # Skip cities that are mid-production
            
            city_count += 1

            # Generate production options from unit_types and improvements
            # Filter by server-provided can_build bitvectors (tech prerequisites, obsolescence, etc.)

            # Units - only include those the city can actually build
            for unit_type_id, unit_type in self.unit_types.items():
                unit_name = unit_type.get('name', '')
                if not unit_name:
                    continue

                # Check if city can build this unit (tech prereqs, not obsolete, etc.)
                unit_id_int = int(unit_type_id) if isinstance(unit_type_id, str) else unit_type_id
                if not self.can_city_build_unit(city, unit_id_int):
                    continue

                actions.append({
                    'type': 'city_production',
                    'city_id': city_id,
                    'city_name': city.get('name', ''),
                    'production_name': unit_name,
                    'production_kind': VUT_UTYPE,
                    'production_value': unit_type_id,
                    'reason': 'finished' if shield_stock == 0 else 'coinage'
                })

            # Buildings (improvements) - only include those the city can actually build
            for building_id, building in self.improvements.items():
                building_name = building.get('name', '')
                if not building_name:
                    continue

                # Check if city can build this improvement (tech prereqs, not already built, etc.)
                building_id_int = int(building_id) if isinstance(building_id, str) else building_id
                if not self.can_city_build_improvement(city, building_id_int):
                    continue

                actions.append({
                    'type': 'city_production',
                    'city_id': city_id,
                    'city_name': city.get('name', ''),
                    'production_name': building_name,
                    'production_kind': VUT_IMPROVEMENT,
                    'production_value': building_id,
                    'reason': 'finished' if shield_stock == 0 else 'coinage'
                })
        
        # Cache for this turn
        self._action_cache[cache_key] = actions
        
        return actions

    def _get_tech_research_actions(self, player_id):
        """Get tech research selection actions (CACHED per turn).
        
        Only returns tech research actions if:
        - researching field == A_UNSET (no tech selected, need new selection)
        
        This mirrors the city production semantics where we only offer choices
        when the previous item finished.
        
        Args:
            player_id: The player ID
            
        Returns:
            list: List of tech research action dicts, or empty list if no selection needed
        """
        turn = self.game_turn
        cache_key = f"{turn}_{player_id}_tech_actions"
        
        # Check cache first
        if cache_key in self._action_cache:
            return self._action_cache[cache_key]
        
        actions = []
        
        # Check if player needs to select new tech
        research = self.research_info.get(player_id)
        if not research:
            # No research info yet, return empty
            self._action_cache[cache_key] = actions
            return actions
        
        researching = research.get('researching')
        
        # Only generate actions if researching == A_UNSET (no tech selected)
        if researching != A_UNSET:
            # Already researching something, no action needed
            self._action_cache[cache_key] = actions
            return actions
        
        # Get all researchable techs using existing method
        researchable_techs = self.get_researchable_techs(player_id)
        
        # Convert to action format
        for tech in researchable_techs:
            actions.append({
                'type': 'tech_research',
                'tech_id': tech['id'],
                'tech_name': tech['name'],
                'tech_cost': tech.get('cost', 0),
                'reason': 'tech_completed'
            })
        
        # Cache for this turn
        self._action_cache[cache_key] = actions
        
        return actions

    def _get_legal_actions_optimized(self, player_id):
        """Pre-compute top legal actions for LLM with per-category limits.
        
        Generates actions using helper methods with smart caching:
        - Unit actions: NOT cached (regenerated every call)
        - City production: Cached per turn, only when shield_stock==0 OR Coinage
        - Tech research: Cached per turn, only when researching==A_UNSET
        
        Per-category limits (not global):
        - Unit actions: max 5 units
        - City production: max 3 cities  
        - Tech research: all researchable techs (when needed)
        
        Args:
            player_id: The player ID
            
        Returns:
            list: Combined list of all legal actions from all categories
        """
        all_actions = []
        
        # Get unit actions (NOT CACHED - always fresh)
        unit_actions = self._get_unit_actions(player_id, max_units=5)
        all_actions.extend(unit_actions)
        
        # Get city production actions (CACHED per turn, with smart filtering)
        city_actions = self._get_city_production_actions(player_id, max_cities=3)
        all_actions.extend(city_actions)
        
        # Get tech research actions (CACHED per turn, only when needed)
        tech_actions = self._get_tech_research_actions(player_id)
        all_actions.extend(tech_actions)
        
        return all_actions

    def _score_and_filter_actions(self, actions, max_actions):
        """Score actions and return top N most important"""
        # Simple scoring based on priority
        priority_scores = {'high': 3, 'medium': 2, 'low': 1}

        scored_actions = []
        for action in actions:
            priority = action.get('priority', 'low')
            score = priority_scores.get(priority, 1)
            scored_actions.append((score, action))

        # Sort by score and return top actions
        scored_actions.sort(key=lambda x: x[0], reverse=True)
        return [action for score, action in scored_actions[:max_actions]]

    def get_full_state(self, player_id):
        """Get complete game state - returns dict format for units/cities/players"""
        # Ensure map_info has valid dimensions
        map_info = getattr(self, 'map_info', {})
        if not map_info or map_info.get('width', 0) < 1 or map_info.get('height', 0) < 1:
            map_info = {'width': 80, 'height': 50, 'tiles': [], 'visibility': {}}

        # Convert players list to dict keyed by ID
        all_players_raw = getattr(self, 'all_players', [])
        players_dict = {}
        if isinstance(all_players_raw, list):
            for p in all_players_raw:
                if isinstance(p, dict) and 'id' in p:
                    players_dict[str(p['id'])] = p
        elif isinstance(all_players_raw, dict):
            players_dict = all_players_raw

        # Keep units as dict, filtering by player_id
        units_dict = getattr(self, 'player_units', {})
        player_units_dict = {}
        if isinstance(units_dict, dict):
            # Debug: Log CivCom identity and unit state
            logger.info(
                f"🔍 get_full_state called on CivCom[{self.username}]:\n"
                f"   Requested player_id={player_id} (type={type(player_id).__name__})\n"
                f"   CivCom's self.player_id={self.player_id}\n"
                f"   Total units in this CivCom's player_units: {len(units_dict)}"
            )
            if units_dict:
                owner_types = set(type(u.get('owner')).__name__ for u in units_dict.values())
                owner_values = set(u.get('owner') for u in units_dict.values())
                logger.info(
                    f"   Owner types in units: {owner_types}\n"
                    f"   Owner values in units: {owner_values}"
                )
            else:
                logger.warning(f"⚠️ CivCom[{self.username}] has ZERO units stored!")
            for unit_id, unit in units_dict.items():
                if unit.get('owner') == player_id:
                    player_units_dict[str(unit_id)] = unit
            logger.info(f"✓ Filtered {len(player_units_dict)} units for player {player_id} from {len(units_dict)} total")

        # Keep cities as dict, filtering by player_id
        cities_dict = getattr(self, 'player_cities', {})
        player_cities_dict = {}
        if isinstance(cities_dict, dict):
            for city_id, city in cities_dict.items():
                if city.get('owner') == player_id:
                    player_cities_dict[str(city_id)] = city
            logger.debug(f"Filtered {len(player_cities_dict)} cities for player {player_id} from {len(cities_dict)} total")

        # Ensure we always have valid game state values (defensive against early queries)
        game_turn = getattr(self, 'game_turn', 1)
        game_phase = getattr(self, 'game_phase', 'movement')

        # CRITICAL: Always include 'game' dict at top level for agent-clash compatibility
        # This dict is REQUIRED by freeciv_state.py validation
        game_dict = {
            'turn': game_turn,
            'phase': game_phase,
            'is_over': getattr(self, 'game_is_over', False),
            'current_player': player_id
        }

        return {
            'turn': game_turn,
            'phase': game_phase,
            'player_id': player_id,
            'units': player_units_dict,  # Dict of player's units keyed by ID
            'cities': player_cities_dict,  # Dict of player's cities keyed by ID
            'visible_tiles': getattr(self, 'visible_tiles', []),
            'players': players_dict,  # Dict of all players keyed by ID
            'techs': getattr(self, 'known_techs', []),
            'map': map_info,
            'game': game_dict  # Required field - must always be present
        }

    def get_state_delta(self, player_id):
        """Get state changes since last query"""
        last_query_time = getattr(self, 'last_state_query_time', 0)
        current_time = time.time()

        delta = {
            'turn': getattr(self, 'game_turn', 1),
            'time_range': [last_query_time, current_time],
            'new_units': getattr(self, 'units_since_last_query', []),
            'moved_units': getattr(self, 'moved_units_since_last_query', []),
            'completed_production': getattr(self, 'completed_production_since_last_query', []),
            'tech_progress': getattr(self, 'tech_progress_since_last_query', {}),
            'gold_change': getattr(self, 'gold_change_since_last_query', 0)
        }

        # Update last query time
        self.last_state_query_time = current_time
        return delta
