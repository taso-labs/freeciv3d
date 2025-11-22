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
import threading
import logging
import time
import json
import os
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
    PACKET_RULESET_EXTRA,
    PACKET_RULESET_TERRAIN,
    PACKET_CONN_PING,
    PACKET_CONN_PONG,
    get_packet_name
)
# Import activity constants for worker action validation
from fc_constants import (
    ACTIVITY_IDLE,
    ACTIVITY_POLLUTION,
    ACTIVITY_ROAD,
    ACTIVITY_MINE,
    ACTIVITY_IRRIGATE,
    ACTIVITY_FORTIFIED,
    ACTIVITY_FORTRESS,
    ACTIVITY_SENTRY,
    ACTIVITY_RAILROAD,
    ACTIVITY_PILLAGE,
    ACTIVITY_GOTO,
    ACTIVITY_EXPLORE,
    ACTIVITY_TRANSFORM,
    ACTIVITY_AIRBASE,
    ACTIVITY_FORTIFYING,
    ACTIVITY_FALLOUT,
    ACTIVITY_PATROL,
    ACTIVITY_BASE,
    ACTIVITY_GEN_ROAD,
    BUSY_ACTIVITIES,
    EC_IRRIGATION,
    EC_MINE,
    EC_ROAD,
    EC_BASE,
    EC_POLLUTION,
    EC_FALLOUT
)

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
        self.player_cities = {}  # Dict keyed by city_id for efficient updates
        self.all_players = []
        self.known_techs = []
        self.visible_tiles = {}   # {(x,y): tile_data} - persistent tile state updated by PACKET_TILE_INFO
        self.game_turn = 1
        self.game_phase = 'movement'
        self.player_id = None  # Will be set from PACKET_PLAYER_INFO
        self.nations = {}  # Will be populated from PACKET_RULESET_NATION (pid=148)

        # RULESET packet storage - mirrors FreeCiv web client architecture
        # These define immutable game rules (unit types, buildings, techs, terrain, etc.)
        # Stored directly here instead of separate cache layer for simplicity
        # Matches web client's unit_types[], improvements[], techs[] pattern
        self.unit_types = {}      # {unit_type_id: PACKET_RULESET_UNIT data}
        self.improvements = {}    # {building_id: PACKET_RULESET_BUILDING data}
        self.techs = {}           # {tech_id: PACKET_RULESET_TECH data}
        self.extras = {}          # {extra_id: PACKET_RULESET_EXTRA data} - roads, irrigation, pollution, etc.
        self.terrains = {}        # {terrain_id: PACKET_RULESET_TERRAIN data} - grassland, plains, hills, etc.

        # Core rules values (e.g. minimum city distance). Populated from PACKET_GAME_INFO.
        # citymindist is the minimum allowed distance between any two founded cities.
        # It is used to pre-filter illegal unit_build_city actions before sending to server.
        self.citymindist = None  # Will be set once PACKET_GAME_INFO is received
        # Potential future: store other rules like cityradius, global warming parameters, etc.

        # Goto path cache: maps (unit_id, dest_tile) -> {'length': int, 'dir': [int,...]}
        self._goto_paths = {}
        # Initialize lock eagerly to avoid races during lazy init from multiple threads
        self._goto_paths_lock = threading.RLock()

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
                                    logger.info(f"✓ Received PACKET_UNIT_INFO (pid={pid}) for {self.username}")
                                elif pid == PACKET_CITY_INFO:
                                    logger.info(f"✓ Received PACKET_CITY_INFO (pid={pid}) for {self.username}")
                                elif pid == PACKET_GAME_INFO:
                                    logger.debug(f"Received PACKET_GAME_INFO for {self.username}")
                                elif pid == PACKET_CHAT_MSG:
                                    # Log chat messages to capture server command responses
                                    msg_text = packet_json.get('message', '')
                                    logger.info(f"Chat message for {self.username}: {msg_text}")
                            except:
                                pass  # Not JSON or parsing failed, ignore
                        except Exception as e:
                            logger.warning(f"⚠ Error parsing packet for state storage: {e}", exc_info=True)

                        # ALWAYS forward packet to client (even if parsing disabled/failed)
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
            # Log large packet sizes to track what's being blocked
            packet_size = len(packet.encode('utf-8'))
            if packet_size > 1_000_000:  # Log if >1MB
                logger.warning(
                    f"📦 LARGE PACKET: Sending {packet_size:,} bytes ({packet_size/(1024*1024):.2f}MB) "
                    f"to {self.username}"
                )
                # Log first 200 chars to see packet type
                logger.debug(f"   Packet preview: {packet[:200]}...")

            # Calls the write_message callback on the next Tornado I/O loop iteration (thread safely).
            conn = self.civwebserver
            conn.io_loop.add_callback(lambda: conn.write_message(packet))

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
                    elif pid == 10:  # PACKET_NATION_SELECT_REQ
                        logger.info(f"Sent PACKET_NATION_SELECT_REQ (nation_no={msg_json.get('nation_no')}) for {self.username}")
                    elif pid == 11:  # PACKET_PLAYER_READY
                        logger.info(f"Sent PACKET_PLAYER_READY (player_no={msg_json.get('player_no')}) for {self.username}")
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

            # Map info packet (contains xsize, ysize)
            if packet_type == PACKET_MAP_INFO:
                # Freeciv PACKET_MAP_INFO typically includes: xsize, ysize, topology_id, wrap_id, north_latitude, south_latitude
                # We currently only need width/height and wrap_id for distance calculations.
                self.map_info = {
                    'width': packet.get('xsize', 0),
                    'height': packet.get('ysize', 0),
                    'wrap_id': packet.get('wrap_id'),  # raw wrap identifier (mapping to axis wrap can be added later)
                    'topology_id': packet.get('topology_id'),
                    'tiles': [],
                    'visibility': {}
                }
                logger.info(f"Stored map info: {self.map_info['width']}x{self.map_info['height']} wrap_id={self.map_info.get('wrap_id')}")

            # Game info packet (turn number, etc)
            elif packet_type == PACKET_GAME_INFO:
                self.game_turn = packet.get('turn', self.game_turn)
                # Capture minimum city distance rule if present.
                # Field name in Freeciv packets.def: citymindist (UINT8)
                if 'citymindist' in packet:
                    previous = self.citymindist
                    self.citymindist = packet.get('citymindist')
                    if previous is None and self.citymindist is not None:
                        logger.info(f"Rule: citymindist set to {self.citymindist}")
                logger.debug(f"Updated game turn: {self.game_turn}; citymindist={self.citymindist}")

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
                    self.all_players.append({
                        'id': player_id,
                        'name': packet.get('username', f'Player{player_id}'),
                        'nation': nation_name,  # String name (e.g., 'Romans', 'Americans')
                        'score': packet.get('score', 0),
                        'gold': packet.get('gold', 0)
                    })

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
                    logger.info(f"✓ Stored unit {unit_id} (type={unit_type_name}, type_id={unit_type_raw}) for owner {owner}")

            # City info packet - stores cities by ID for all players
            elif packet_type == PACKET_CITY_INFO:
                city_id = packet.get('id')
                owner = packet.get('owner')
                if city_id is not None and owner is not None:
                    tile_idx = packet.get('tile')
                    # Compute x,y from tile index if map size known
                    x = y = None
                    width_val = self.map_info.get('width')
                    if isinstance(tile_idx, int) and isinstance(width_val, int) and width_val > 0:
                        xsize = width_val
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
                        'production': packet.get('production'),
                        'food_stock': packet.get('food_stock', 0),
                        'shield_stock': packet.get('shield_stock', 0),
                        'trade': packet.get('trade', [0, 0, 0]),
                        'luxury': packet.get('luxury', 0),
                        'science': packet.get('science', 0),
                        'tax': packet.get('tax', 0)
                    }

                    # Convert player_cities to dict if it's still a list
                    if not isinstance(self.player_cities, dict):
                        self.player_cities = {}

                    self.player_cities[city_id] = city_data
                    logger.info(f"✓ Stored city {city_id} ({city_data['name']}, size={city_data['size']}) for owner {owner}")

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
            # Critical for handling unit_move responses
            elif packet_type == PACKET_TILE_INFO:
                tile_x = packet.get('x')
                tile_y = packet.get('y')
                terrain = packet.get('terrain')
                extras_bitvector = packet.get('extras')  # Bit vector of extras on this tile
                
                if tile_x is not None and tile_y is not None:
                    # Parse extras bit vector to get list of extra names on this tile
                    extras_names = self._parse_tile_extras(extras_bitvector)
                    
                    # Store tile data in persistent visible_tiles dict
                    tile_data = {
                        'x': tile_x,
                        'y': tile_y,
                        'terrain': terrain,
                        'extras_names': extras_names,
                        'extras_bitvector': extras_bitvector
                    }
                    self.visible_tiles[(tile_x, tile_y)] = tile_data
                    
                    logger.debug(f"Tile update at ({tile_x}, {tile_y}) - terrain={terrain}, extras={extras_names}")

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
                    logger.debug(f"Registered unit type: {unit_name} (id={unit_id})")

            # RULESET building packet - defines improvements (Barracks, Granary, etc.)
            # Mirrors FreeCiv web client's improvements[] storage pattern
            # Used by RulesetMapper for production name→ID mapping
            elif packet_type == PACKET_RULESET_BUILDING:
                building_id = packet.get('id')
                building_name = packet.get('name')
                if building_id is not None and building_name:
                    self.improvements[building_id] = packet
                    logger.debug(f"Registered building: {building_name} (id={building_id})")

            # RULESET extra packet - defines extras (irrigation, mine, road, pollution, etc.)
            # Used for tile improvement validation and worker action generation
            elif packet_type == PACKET_RULESET_EXTRA:
                extra_id = packet.get('id')
                extra_name = packet.get('name')
                if extra_id is not None and extra_name:
                    self.extras[extra_id] = packet
                    logger.debug(f"Registered extra: {extra_name} (id={extra_id})")

            # RULESET terrain packet - defines terrain types with activity times
            # Used for validating which improvements can be built on which terrain
            elif packet_type == PACKET_RULESET_TERRAIN:
                terrain_id = packet.get('id')
                terrain_name = packet.get('name')
                if terrain_id is not None and terrain_name:
                    self.terrains[terrain_id] = packet
                    logger.debug(f"Registered terrain: {terrain_name} (id={terrain_id})")

            # CRITICAL: Connection ping packet - MUST respond with pong to keep connection alive
            # FreeCiv civserver sends PACKET_CONN_PING every ~2 minutes to verify connection health
            # Without responding with PACKET_CONN_PONG, the server will timeout and disconnect with "ping timeout"
            # This was causing agents to disconnect at exactly ~2 minutes after connection
            elif packet_type == PACKET_CONN_PING:
                # Immediately respond with pong packet to keep connection alive
                pong_packet = json.dumps({"pid": PACKET_CONN_PONG})
                logger.debug(f"[PING] Received PACKET_CONN_PING from civserver, responding with PACKET_CONN_PONG for {self.username}")
                self.queue_to_civserver(pong_packet)

            # Web goto path (server-provided directions for movement)
            elif packet_type == 288:  # PACKET_WEB_GOTO_PATH
                try:
                    unit_id = packet.get('unit_id') or packet.get('actor_id') or packet.get('unit')
                    # Server sends destination as 'dest' for PACKET_WEB_GOTO_PATH
                    dest_tile = (packet.get('dest') or packet.get('dest_tile')
                                 or packet.get('target') or packet.get('tile'))
                    length = packet.get('length') or (len(packet.get('dir', [])) if isinstance(packet.get('dir'), list) else 0)
                    dirs = packet.get('dir') or packet.get('dirs') or []
                    if unit_id is not None and dest_tile is not None and isinstance(dirs, list):
                        if self._goto_paths_lock is None:
                            # simple lock substitute; not critical if absent
                            import threading
                            self._goto_paths_lock = threading.RLock()
                        with self._goto_paths_lock:
                            self._goto_paths[(unit_id, dest_tile)] = {
                                'length': int(length) if length is not None else len(dirs),
                                'dir': dirs
                            }
                        logger.debug(f"Stored WEB_GOTO_PATH for unit {unit_id} to {dest_tile}: length={length}, dir_count={len(dirs)}")
                    else:
                        logger.debug(f"WEB_GOTO_PATH missing fields: {packet}")
                except Exception as e:
                    logger.debug(f"Failed to parse WEB_GOTO_PATH: {e}")

            # Default handler for unknown/unhandled packet types
            # This prevents "unsupported packet type" disconnects from civserver
            else:
                # Log debug info for unhandled packets (helps identify missing handlers)
                logger.debug(f"Received unhandled packet type {packet_type} for {self.username}")
                # Don't crash - just acknowledge and continue

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"Could not parse packet for state storage: {e}")

    # Worker action validation helper methods
    def _parse_tile_extras(self, extras_bitvector):
        """
        Parse extras bit vector to list of extra names.
        
        Args:
            extras_bitvector: Integer bit vector from PACKET_TILE_INFO
            
        Returns:
            List of extra names (e.g., ['Irrigation', 'Road', 'Pollution'])
            Empty list if bitvector is None or no extras present
        """
        if extras_bitvector is None or not self.extras:
            return []
        
        extras_names = []
        for extra_id, extra_packet in self.extras.items():
            # Check if bit at position extra_id is set in bitvector
            if (extras_bitvector >> extra_id) & 1:
                extra_name = extra_packet.get('name', '')
                if extra_name:
                    # Preserve original casing from ruleset
                    extras_names.append(extra_name)
        
        return extras_names
    
    def _get_extras_by_cause(self, cause_bit):
        """
        Get all extras that can be created by a specific cause.
        
        Args:
            cause_bit: EC_* constant from fc_constants (EC_IRRIGATION, EC_MINE, etc.)
            
        Returns:
            List of dicts with {'id': extra_id, 'name': extra_name}
        """
        if not self.extras:
            return []
        
        matching_extras = []
        for extra_id, extra_packet in self.extras.items():
            causes = extra_packet.get('causes', 0)
            # Check if the cause bit is set in the extra's causes bitvector
            if (causes >> cause_bit) & 1:
                extra_name = extra_packet.get('name', '')
                if extra_name:
                    matching_extras.append({
                        'id': extra_id,
                        'name': extra_name
                    })
        
        return matching_extras
    
    def _can_terrain_support_activity(self, terrain_id, activity_type):
        """
        Check if terrain supports a specific activity type.
        
        Args:
            terrain_id: Terrain type ID from tile data
            activity_type: ACTIVITY_* constant from fc_constants
            
        Returns:
            True if terrain supports activity, False otherwise
        """
        if terrain_id is None or terrain_id not in self.terrains:
            return False
        
        terrain = self.terrains[terrain_id]
        
        # Map activity types to terrain time fields
        # If time field is 0, activity is not possible on this terrain
        if activity_type == ACTIVITY_IRRIGATE:
            return terrain.get('irrigation_time', 0) != 0
        elif activity_type == ACTIVITY_MINE:
            return terrain.get('mining_time', 0) != 0
        elif activity_type == ACTIVITY_ROAD:
            return terrain.get('road_time', 0) != 0
        elif activity_type == ACTIVITY_TRANSFORM:
            return terrain.get('transform_time', 0) != 0
        elif activity_type == ACTIVITY_POLLUTION:
            return terrain.get('clean_pollution_time', 0) != 0
        elif activity_type == ACTIVITY_FALLOUT:
            return terrain.get('clean_fallout_time', 0) != 0
        
        # Unknown activity type - default to True to avoid blocking
        return True

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

        # CRITICAL: Always include 'game' dict at top level for game_arena compatibility
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

    def _get_legal_actions_optimized(self, player_id):
        """Pre-compute and cache top legal actions for LLM"""
        # Simplified legal actions (would normally compute from game state)
        actions = []

        # Unit movement actions (most common)
        units = getattr(self, 'player_units', [])
        for unit in units[:5]:  # Limit to 5 units for size
            if isinstance(unit, dict) and unit.get('moves_left', 0) > 0:
                unit_id = unit.get('id')
                x, y = unit.get('x', 0), unit.get('y', 0)

                # Add movement options
                for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                    actions.append({
                        'type': 'unit_move',
                        'unit_id': unit_id,
                        'dest_x': x + dx,
                        'dest_y': y + dy,
                        'priority': 'medium'
                    })

        # City production actions
        cities = getattr(self, 'player_cities', [])
        for city in cities[:3]:  # Limit to 3 cities
            if isinstance(city, dict):
                city_id = city.get('id')
                actions.append({
                    'type': 'city_production',
                    'city_id': city_id,
                    'production_type': 'warrior',
                    'priority': 'high'
                })

        # Research actions
        if not getattr(self, 'current_research', None):
            actions.append({
                'type': 'tech_research',
                'tech_name': 'pottery',
                'priority': 'high'
            })

        # Score and filter actions to top 20
        return self._score_and_filter_actions(actions, 20)

    # --- Goto path utilities for LLM movement ---
    def request_goto_path(self, unit_id: int, dest_tile: int):
        """Request server-computed path for a unit to destination tile.

        Stores the result in internal cache when the server responds with PACKET_WEB_GOTO_PATH.
        """
        packet = json.dumps({
            'pid': 287,  # PACKET_WEB_GOTO_PATH_REQ
            'unit_id': unit_id,
            # Freeciv expects field name 'goal' for destination tile id
            'goal': dest_tile
        })
        self.queue_to_civserver(packet)

    def get_goto_path(self, unit_id: int, dest_tile: int, timeout_sec: float = 1.0):
        """Wait briefly for a goto path response and return it if available."""
        start = time.time()
        # ensure messages are flushed so request is sent
        self.send_packets_to_civserver()
        while time.time() - start < timeout_sec:
            if self._goto_paths_lock is None:
                import threading
                self._goto_paths_lock = threading.RLock()
            with self._goto_paths_lock:
                key = (unit_id, dest_tile)
                if key in self._goto_paths:
                    return self._goto_paths.pop(key)
            time.sleep(0.01)
        return None

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
            for unit_id, unit in units_dict.items():
                if unit.get('owner') == player_id:
                    player_units_dict[str(unit_id)] = unit
            logger.debug(f"Filtered {len(player_units_dict)} units for player {player_id} from {len(units_dict)} total")

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

        # CRITICAL: Always include 'game' dict at top level for game_arena compatibility
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
            'rules': {
                'citymindist': self.citymindist
            },
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
