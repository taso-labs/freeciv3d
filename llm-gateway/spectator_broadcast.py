#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Spectator Broadcast System for LLM Gateway Games

Broadcasts FreeCiv protocol packets to web spectators in real-time.
Supports multiple viewing modes: player perspective, god mode, and player switching.

Architecture:
- LLM agents connect to freeciv-proxy and receive game packets
- LLM Gateway intercepts these packets and broadcasts to spectators
- Spectators connect via WebSocket and receive FreeCiv protocol packets
- View modes control which packets are forwarded (player perspective vs god mode)
"""

import json
import logging
import time
import aiohttp
from collections import deque
from enum import Enum
from typing import Dict, List, Any, Optional, Set
from fastapi import WebSocket

logger = logging.getLogger("llm-gateway")

# FreeCiv proxy configuration
FREECIV_PROXY_HOST = "localhost"
FREECIV_PROXY_PORT = 8002


class ViewMode(Enum):
    """Spectator view mode options"""
    PLAYER_1 = "player1"      # MVP: Player 1's fog of war perspective
    PLAYER_2 = "player2"      # Player 2's fog of war perspective
    GOD_MODE = "god"          # Combined view of both players (future)
    SWITCHABLE = "switchable"  # Spectator can choose player (future)


class SpectatorConnection:
    """Represents a single spectator WebSocket connection"""

    def __init__(self, websocket: WebSocket, view_mode: ViewMode = ViewMode.PLAYER_1):
        self.websocket = websocket
        self.view_mode = view_mode
        self.connected_at = time.time()
        self.packets_sent = 0

    async def send_packet(self, packet: dict):
        """Send packet to spectator"""
        try:
            await self.websocket.send_text(json.dumps(packet))
            self.packets_sent += 1
        except Exception as e:
            logger.error(f"Error sending packet to spectator: {e}")
            raise


class PacketCache:
    """Cached packets for mid-game spectator joins"""

    def __init__(self, maxlen: int = 10000):
        # SPECTATOR FIX: Increased cache from 1000 to 10000 packets
        # Map generation sends ~4096 PACKET_TILE_INFO (one per tile on 64x64 map)
        # Plus RULESET, UNIT_INFO, CITY_INFO, PLAYER_INFO, etc.
        # Need larger cache to retain tile data for late-joining spectators
        self.packets_p1 = deque(maxlen=maxlen)  # Player 1's packets
        self.packets_p2 = deque(maxlen=maxlen)  # Player 2's packets
        self.maxlen = maxlen

    def add_packet(self, packet: dict, player_id: int):
        """Add packet to appropriate player cache"""
        if player_id == 0:
            self.packets_p1.append((time.time(), packet))
        elif player_id == 1:
            self.packets_p2.append((time.time(), packet))

    def get_packets_for_view(self, view_mode: ViewMode) -> List[dict]:
        """Get cached packets based on view mode"""
        if view_mode == ViewMode.PLAYER_1:
            return [pkt for _, pkt in self.packets_p1]
        elif view_mode == ViewMode.PLAYER_2:
            return [pkt for _, pkt in self.packets_p2]
        elif view_mode == ViewMode.GOD_MODE:
            # Merge packets from both players (future implementation)
            all_packets = list(self.packets_p1) + list(self.packets_p2)
            all_packets.sort(key=lambda x: x[0])  # Sort by timestamp
            return [pkt for _, pkt in all_packets]
        else:
            return []


class SpectatorBroadcaster:
    """Manages spectator connections and broadcasts game packets"""

    def __init__(self):
        # {game_id: [SpectatorConnection]}
        self.spectators: Dict[str, List[SpectatorConnection]] = {}

        # {game_id: PacketCache}
        self.packet_cache: Dict[str, PacketCache] = {}

        # Track active games
        self.active_games: Set[str] = set()

        logger.info("SpectatorBroadcaster initialized")

    async def _fetch_ruleset_packets(self, game_id: str) -> Optional[List[str]]:
        """
        Fetch cached RULESET packets from freeciv-proxy.

        These packets define game constants like EXTRA_MINE, unit_types[], terrain types, etc.
        Spectators need these to initialize their client state properly.

        Args:
            game_id: Game identifier

        Returns:
            List of JSON packet strings, or None if not available
        """
        url = f"http://{FREECIV_PROXY_HOST}:{FREECIV_PROXY_PORT}/api/rulesets/{game_id}"

        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('success'):
                            packets = data.get('packets', [])
                            packet_count = data.get('packet_count', 0)
                            logger.info(f"✓ Fetched {packet_count} RULESET packets for game {game_id}")
                            return packets
                        else:
                            logger.warning(f"RULESET fetch failed for game {game_id}: {data.get('error')}")
                            return None
                    elif response.status == 404:
                        logger.warning(f"No RULESET cache found for game {game_id} (may be early in game initialization)")
                        return None
                    else:
                        logger.error(f"RULESET fetch error for game {game_id}: HTTP {response.status}")
                        return None

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching RULESET packets for game {game_id}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error fetching RULESET packets for game {game_id}: {e}")
            return None

    async def register_spectator(
        self,
        game_id: str,
        websocket: WebSocket,
        view_mode: ViewMode = ViewMode.PLAYER_1
    ) -> SpectatorConnection:
        """
        Register new spectator connection.

        CRITICAL: Sends RULESET packets FIRST to initialize client constants
        (EXTRA_MINE, unit_types[], etc.) before sending game state packets.
        """

        # Create spectator connection
        spec_conn = SpectatorConnection(websocket, view_mode)

        # Add to spectators list
        if game_id not in self.spectators:
            self.spectators[game_id] = []
        self.spectators[game_id].append(spec_conn)

        # Mark game as active
        self.active_games.add(game_id)

        # Ensure packet cache exists for this game
        if game_id not in self.packet_cache:
            self.packet_cache[game_id] = PacketCache()

        logger.info(
            f"Spectator registered for game {game_id} "
            f"(view: {view_mode.value}, total spectators: {len(self.spectators[game_id])})"
        )

        # SPECTATOR FIX: Send RULESET packets FIRST to initialize client
        # Without these, client has undefined EXTRA_MINE, unit_types[], etc.
        try:
            ruleset_packets = await self._fetch_ruleset_packets(game_id)
            if ruleset_packets:
                logger.info(f"📤 Sending {len(ruleset_packets)} RULESET packets to spectator...")
                for packet_json in ruleset_packets:
                    try:
                        # Parse and send each packet
                        packet = json.loads(packet_json)
                        await spec_conn.send_packet(packet)
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in cached RULESET packet: {e}")
                    except Exception as e:
                        logger.error(f"Error sending RULESET packet: {e}")

                logger.info(f"✓ RULESET packets sent to spectator for game {game_id}")
            else:
                logger.warning(f"⚠️ No RULESET packets available for game {game_id} - spectator may not render correctly")
        except Exception as e:
            logger.exception(f"Error sending RULESET packets to spectator: {e}")

        return spec_conn

    def unregister_spectator(self, game_id: str, spec_conn: SpectatorConnection):
        """Remove spectator connection"""
        if game_id in self.spectators:
            try:
                self.spectators[game_id].remove(spec_conn)
                logger.info(
                    f"Spectator unregistered from game {game_id} "
                    f"(remaining: {len(self.spectators[game_id])})"
                )

                # Clean up empty game entries
                if not self.spectators[game_id]:
                    del self.spectators[game_id]
                    if game_id in self.active_games:
                        self.active_games.remove(game_id)
            except ValueError:
                pass  # Spectator not in list

    async def forward_packet(
        self,
        game_id: str,
        packet: dict,
        from_player_id: int
    ):
        """Broadcast packet to spectators based on their view modes"""

        # Cache the packet for mid-game joins (auto-create cache if needed)
        # SPECTATOR FIX: Create cache on first packet, not when spectator connects
        # This ensures late-joining spectators get full game history including map data
        if game_id not in self.packet_cache:
            self.packet_cache[game_id] = PacketCache()
            logger.info(f"Created packet cache for game {game_id} on first packet broadcast")
        self.packet_cache[game_id].add_packet(packet, from_player_id)

        # Get spectators for this game
        spectators = self.spectators.get(game_id, [])
        if not spectators:
            return  # No spectators, skip broadcast

        # Broadcast to each spectator based on view mode
        disconnected_spectators = []
        for spec_conn in spectators:
            try:
                if self._should_forward_packet(spec_conn.view_mode, from_player_id):
                    await spec_conn.send_packet(packet)
            except Exception as e:
                logger.warning(f"Failed to send packet to spectator: {e}")
                disconnected_spectators.append(spec_conn)

        # Clean up disconnected spectators
        for spec_conn in disconnected_spectators:
            self.unregister_spectator(game_id, spec_conn)

    def _should_forward_packet(self, view_mode: ViewMode, from_player_id: int) -> bool:
        """Determine if packet should be forwarded based on view mode"""

        if view_mode == ViewMode.PLAYER_1:
            return from_player_id == 0  # Only Player 1's packets

        elif view_mode == ViewMode.PLAYER_2:
            return from_player_id == 1  # Only Player 2's packets

        elif view_mode == ViewMode.GOD_MODE:
            return True  # All packets from all players

        elif view_mode == ViewMode.SWITCHABLE:
            # For switchable mode, would need to track current selection
            # Default to player 1 for now
            return from_player_id == 0

        return False

    async def send_initial_state(
        self,
        game_id: str,
        websocket: WebSocket,
        view_mode: ViewMode
    ):
        """Send cached packets to new spectator for mid-game joins"""

        if game_id not in self.packet_cache:
            logger.warning(f"No packet cache found for game {game_id}")
            return

        cache = self.packet_cache[game_id]
        cached_packets = cache.get_packets_for_view(view_mode)

        if not cached_packets:
            logger.info(f"No cached packets for game {game_id} (view: {view_mode.value})")
            return

        logger.info(
            f"Sending {len(cached_packets)} cached packets to spectator "
            f"(game: {game_id}, view: {view_mode.value})"
        )

        # Send all cached packets in sequence
        for packet in cached_packets:
            try:
                await websocket.send_text(json.dumps(packet))
            except Exception as e:
                logger.error(f"Error sending cached packet: {e}")
                break

    def get_spectator_count(self, game_id: str) -> int:
        """Get number of spectators for a game"""
        return len(self.spectators.get(game_id, []))

    def get_active_games(self) -> List[str]:
        """Get list of games with active spectators"""
        return list(self.active_games)

    def cleanup_game(self, game_id: str):
        """Clean up spectator data for ended game"""
        if game_id in self.spectators:
            del self.spectators[game_id]
        if game_id in self.packet_cache:
            del self.packet_cache[game_id]
        if game_id in self.active_games:
            self.active_games.remove(game_id)

        logger.info(f"Cleaned up spectator data for game {game_id}")


# Global spectator broadcaster instance
spectator_broadcaster = SpectatorBroadcaster()
