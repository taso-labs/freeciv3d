#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Game Session Manager
Coordinates multi-player game initialization to prevent race conditions
"""

import asyncio
import json
import logging
import threading
import time
import aiohttp
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from tornado.ioloop import IOLoop

from state_extractor import civcom_registry
from packet_constants import PACKET_CHAT_MSG_REQ

logger = logging.getLogger("freeciv-proxy")

# Constants for timeout validation
DEFAULT_GAME_TIMEOUT = 60  # seconds - default timeout if unknown
MAX_GAME_TIMEOUT = 3600  # 1 hour max - prevents command injection via oversized values


class GamePhase(Enum):
    """Game session phases"""
    WAITING_FOR_PLAYERS = "waiting_for_players"
    NATIONS_SELECTING = "nations_selecting"
    READY_TO_START = "ready_to_start"
    STARTING = "starting"
    RUNNING = "running"
    ENDED = "ended"


@dataclass
class PlayerInfo:
    """Information about a player in a game session"""
    agent_id: str
    player_id: int
    handler: Any  # LLMWSHandler instance
    nation_selected: bool = False
    marked_ready: bool = False
    connected_at: float = field(default_factory=time.time)


# Map size name to (xsize, ysize) dimensions
MAP_SIZE_DIMENSIONS = {
    "tiny": (50, 50),
    "small": (64, 64),
    "medium": (80, 80),
    "large": (96, 96),
    "huge": (128, 128),
}


class GameSession:
    """Manages a single game session with multiple players"""

    def __init__(self, game_id: str, civserver_port: int, min_players: int = 2):
        self.game_id = game_id
        self.civserver_port = civserver_port
        self.min_players = min_players
        self.max_players = 30  # FreeCiv default

        self.phase = GamePhase.WAITING_FOR_PLAYERS
        self.players: Dict[str, PlayerInfo] = {}
        self.game_started = False
        self.start_task: Optional[asyncio.Task] = None
        self.created_at = time.time()
        self._next_ai_slot = 1  # AI slot counter
        self._ai_slot_lock = threading.Lock()  # Lock for thread-safe AI slot allocation
        self._players_lock = threading.Lock()  # Lock for thread-safe player handler mutations

        # Game configuration (applied by first player)
        self.config_applied = False
        self.game_config: Optional[Dict[str, Any]] = None

        # Pause/resume state for coordinated disconnection handling
        self.original_timeout: Optional[int] = None  # Store original timeout for resume
        self.is_paused: bool = False  # Track if game is currently paused

    def allocate_ai_slot(self) -> int:
        """Thread-safe AI slot allocation for /take commands

        Returns the next available AI slot (1, 2, 3, ...) for this game session.
        Each call increments the counter atomically using a threading.Lock, ensuring
        unique AI slot assignment even when multiple async coroutines call simultaneously.

        Thread Safety: Uses threading.Lock (not asyncio.Lock) because this method
        is called from async contexts but the increment operation must be atomic
        at the OS thread level, not just within the asyncio event loop.

        For multiplayer servers (ports 6001-6009) with aifill=2:
          - First call returns 1 (AI*1)
          - Second call returns 2 (AI*2)

        Returns:
            int: AI slot number (1-indexed)
        """
        with self._ai_slot_lock:
            slot = self._next_ai_slot
            self._next_ai_slot += 1
            logger.info(
                f"🎯 Allocated AI slot {slot} for game {self.game_id}\n"
                f"   Next available slot: {self._next_ai_slot}\n"
                f"   Total players in session: {len(self.players)}"
            )
            return slot

    def pause_game(self, civcom: Any, disconnect_reason: str = "agent_disconnected") -> bool:
        """Pause the game by setting timeout to 0 with retry logic.

        This prevents AI takeover when an agent disconnects mid-game.
        The civserver's autotoggle feature won't trigger because no turn
        timer is running.

        Args:
            civcom: CivCom instance to send the /set timeout command through
            disconnect_reason: Reason for pausing (for logging)

        Returns:
            True if pause command was sent, False if already paused or failed
        """
        if self.is_paused:
            logger.debug(f"Game {self.game_id} already paused")
            return False

        if not civcom:
            logger.error(f"Game {self.game_id}: Cannot pause - no civcom connection")
            return False

        # Store original timeout if not already stored
        if self.original_timeout is None:
            timeout = getattr(civcom, 'game_timeout', None)
            # Validate and sanitize timeout value
            if timeout and isinstance(timeout, int) and 0 < timeout <= MAX_GAME_TIMEOUT:
                self.original_timeout = timeout
            else:
                self.original_timeout = DEFAULT_GAME_TIMEOUT
            logger.info(f"Game {self.game_id}: Captured original timeout: {self.original_timeout}s")

        # Send /set timeout 0 to pause the game - with retry logic
        MAX_RETRIES = 3
        RETRY_DELAY = 0.1  # 100ms between retries

        for attempt in range(MAX_RETRIES):
            try:
                pause_packet = json.dumps({"pid": PACKET_CHAT_MSG_REQ, "message": "/set timeout 0"})
                civcom.queue_to_civserver(pause_packet)
                civcom.send_packets_to_civserver()
                # State update immediately after successful send
                self.is_paused = True

                # Success logging
                logger.info(
                    f"✅ Game {self.game_id} PAUSED (attempt {attempt + 1}/{MAX_RETRIES}): {disconnect_reason}\n"
                    f"   Original timeout: {self.original_timeout}s\n"
                    f"   Players: {list(self.players.keys())}"
                )
                return True

            except Exception as e:
                logger.warning(f"Game {self.game_id}: Pause attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    import time
                    time.sleep(RETRY_DELAY)

        # All retries failed
        logger.error(f"❌ Game {self.game_id}: Failed to pause after {MAX_RETRIES} attempts")
        return False

    def resume_game(self, civcom: Any) -> bool:
        """Resume the game by restoring original timeout.

        Called when all players have reconnected after a coordinated
        disconnect.

        Args:
            civcom: CivCom instance to send the /set timeout command through

        Returns:
            True if resume command was sent, False if not paused or failed
        """
        if not self.is_paused:
            logger.debug(f"Game {self.game_id} not paused, nothing to resume")
            return False

        if not civcom:
            logger.error(f"Game {self.game_id}: Cannot resume - no civcom connection")
            return False

        timeout = self.original_timeout or DEFAULT_GAME_TIMEOUT

        # Validate timeout is within bounds (security: prevents command injection)
        if not isinstance(timeout, int) or timeout < 0 or timeout > MAX_GAME_TIMEOUT:
            logger.warning(f"Game {self.game_id}: Invalid timeout {timeout}, using default {DEFAULT_GAME_TIMEOUT}")
            timeout = DEFAULT_GAME_TIMEOUT

        try:
            resume_packet = json.dumps({"pid": PACKET_CHAT_MSG_REQ, "message": f"/set timeout {timeout}"})
            civcom.queue_to_civserver(resume_packet)
            civcom.send_packets_to_civserver()

            self.is_paused = False
            logger.info(
                f"▶️ Game {self.game_id} RESUMED: timeout restored to {timeout}s\n"
                f"   Players: {list(self.players.keys())}"
            )
            return True
        except Exception as e:
            logger.error(f"Game {self.game_id}: Failed to resume game: {e}")
            return False

    async def configure_game_settings(self, config: Dict[str, Any], civcom: Any) -> bool:
        """Apply game settings via chat commands BEFORE any player selects nation.

        CRITICAL TIMING: This must be called:
        1. AFTER civcom connection is established (need connection to send commands)
        2. BEFORE nation selection (to avoid resetting ready flags that matter)
        3. ONLY by first player (subsequent players' config is ignored)

        The /set commands reset all is_ready flags, but that's fine if no player
        has selected a nation or marked ready yet.

        Args:
            config: Game configuration dict with keys like map_size, map_generator, etc.
            civcom: CivCom instance to send commands through

        Returns:
            True if config was applied, False if already configured or failed
        """
        if self.config_applied:
            logger.info(
                f"Game {self.game_id}: Configuration already applied, ignoring\n"
                f"   Existing config: {self.game_config}"
            )
            return False

        if not civcom:
            logger.error(f"Game {self.game_id}: Cannot configure - no civcom connection")
            return False

        # Build list of /set commands from config
        commands = []

        # Map size
        if 'map_size' in config:
            dims = MAP_SIZE_DIMENSIONS.get(config['map_size'], (80, 80))
            commands.append(f"/set xsize {dims[0]}")
            commands.append(f"/set ysize {dims[1]}")

        # Map generator
        if 'map_generator' in config:
            commands.append(f"/set generator {config['map_generator']}")

        # Landmass percentage
        if 'landmass' in config:
            commands.append(f"/set landmass {config['landmass']}")

        # Start position
        if 'startpos' in config:
            commands.append(f"/set startpos {config['startpos']}")

        # Tiny isles
        if 'tinyisles' in config:
            value = "TRUE" if config['tinyisles'] else "FALSE"
            commands.append(f"/set tinyisles {value}")

        # Steepness (hills/mountains)
        if 'steepness' in config:
            commands.append(f"/set steepness {config['steepness']}")

        # Wetness (rivers/swamps)
        if 'wetness' in config:
            commands.append(f"/set wetness {config['wetness']}")

        # Turn timeout
        if 'turn_timeout' in config:
            commands.append(f"/set timeout {config['turn_timeout']}")

        if not commands:
            logger.info(f"Game {self.game_id}: No configuration changes requested")
            self.config_applied = True
            self.game_config = config
            return True

        # Send all /set commands
        logger.info(
            f"Game {self.game_id}: Applying {len(commands)} configuration commands:\n"
            + "\n".join(f"   {cmd}" for cmd in commands)
        )

        for cmd in commands:
            try:
                civcom.queue_to_civserver(json.dumps({
                    "pid": PACKET_CHAT_MSG_REQ,
                    "message": cmd
                }))
            except Exception as e:
                logger.error(f"Game {self.game_id}: Failed to send config command '{cmd}': {e}")
                return False

        # Flush all commands to civserver
        civcom.send_packets_to_civserver()

        # Brief delay to let civserver process settings
        await asyncio.sleep(0.3)

        self.config_applied = True
        self.game_config = config
        logger.info(f"Game {self.game_id}: ✅ Configuration applied successfully")
        return True

    def add_player(self, agent_id: str, player_id: int, handler: Any) -> bool:
        """Add a player to the game session, or update handler on reconnection"""
        if len(self.players) >= self.max_players:
            logger.warning(f"Game {self.game_id}: Max players ({self.max_players}) reached")
            return False

        if agent_id in self.players:
            # Player already exists - this is a reconnection scenario
            # Update the handler reference while preserving player state
            with self._players_lock:
                existing_info = self.players[agent_id]
                existing_info.handler = handler
            logger.info(
                f"Game {self.game_id}: 🔄 Reconnected player {agent_id} "
                f"(player_id={player_id}, nation_selected={existing_info.nation_selected})"
            )
            return True

        player_info = PlayerInfo(
            agent_id=agent_id,
            player_id=player_id,
            handler=handler
        )
        self.players[agent_id] = player_info

        logger.info(f"Game {self.game_id}: Added player {agent_id} (player_id={player_id}), "
                   f"total players: {len(self.players)}/{self.min_players}")

        # Check if we can move to nation selection
        if len(self.players) >= self.min_players and self.phase == GamePhase.WAITING_FOR_PLAYERS:
            self.phase = GamePhase.NATIONS_SELECTING
            logger.info(f"Game {self.game_id}: Transitioning to NATIONS_SELECTING phase")

        return True

    def mark_nation_selected(self, agent_id: str) -> None:
        """Mark that a player has selected their nation"""
        if agent_id not in self.players:
            return

        self.players[agent_id].nation_selected = True
        logger.info(f"Game {self.game_id}: Player {agent_id} selected nation "
                   f"({self._count_nations_selected()}/{len(self.players)})")

        self._check_ready_to_start()

    def mark_player_ready(self, agent_id: str) -> None:
        """Mark that a player has sent PACKET_PLAYER_READY"""
        if agent_id not in self.players:
            return

        self.players[agent_id].marked_ready = True
        logger.info(f"Game {self.game_id}: Player {agent_id} marked ready "
                   f"({self._count_players_ready()}/{len(self.players)})")

        self._check_ready_to_start()

    def _count_nations_selected(self) -> int:
        """Count how many players have selected nations"""
        return sum(1 for p in self.players.values() if p.nation_selected)

    def _count_players_ready(self) -> int:
        """Count how many players have marked ready"""
        return sum(1 for p in self.players.values() if p.marked_ready)

    def _check_ready_to_start(self) -> None:
        """Check if all conditions are met to start the game"""
        logger.debug(f"Game {self.game_id}: Checking ready to start (game_started={self.game_started}, phase={self.phase.value})")

        if self.game_started or self.phase in [GamePhase.STARTING, GamePhase.RUNNING]:
            logger.debug(f"Game {self.game_id}: Already started or starting, skipping check")
            return

        # Need minimum players
        if len(self.players) < self.min_players:
            logger.debug(f"Game {self.game_id}: Waiting for players ({len(self.players)}/{self.min_players})")
            return

        # All players must have selected nations
        nations_count = self._count_nations_selected()
        if nations_count < len(self.players):
            logger.debug(f"Game {self.game_id}: Waiting for nation selection "
                        f"({nations_count}/{len(self.players)})")
            return

        # All players must be marked ready
        ready_count = self._count_players_ready()
        if ready_count < len(self.players):
            logger.debug(f"Game {self.game_id}: Waiting for players to mark ready "
                        f"({ready_count}/{len(self.players)})")
            return

        # All conditions met - ready to start!
        logger.debug(f"Game {self.game_id}: All conditions met for start (phase={self.phase.value})")
        if self.phase != GamePhase.READY_TO_START:
            self.phase = GamePhase.READY_TO_START
            logger.info(f"Game {self.game_id}: All {len(self.players)} players ready - scheduling game start")

            # Schedule game start after a brief delay
            if not self.start_task or self.start_task.done():
                self.start_task = asyncio.create_task(self._initiate_game_start())
                logger.debug(f"Game {self.game_id}: Created start task")
            else:
                logger.debug(f"Game {self.game_id}: Start task already exists")

    async def _initiate_game_start(self) -> None:
        """Initiate the game start sequence (called once when all players ready)"""
        logger.debug(f"Game {self.game_id}: Initiating game start sequence")
        try:
            # Brief delay to ensure PACKET_PLAYER_READY packets have been fully processed by civserver
            # This is minimal (0.5s) to avoid race conditions but not waste time
            logger.debug(f"Game {self.game_id}: Waiting 0.5s for packet processing")
            await asyncio.sleep(0.5)

            # Double-check we're still ready
            ready_count = self._count_players_ready()
            logger.debug(f"Game {self.game_id}: Double-checking readiness ({ready_count}/{len(self.players)})")
            if ready_count < len(self.players):
                logger.warning(f"Game {self.game_id}: Players no longer ready, aborting start")
                self.phase = GamePhase.NATIONS_SELECTING
                return

            self.phase = GamePhase.STARTING
            logger.info(f"Game {self.game_id}: Starting game with {len(self.players)} players")

            # Get all CivComs for this game (all players connect to same civserver)
            all_civcoms = civcom_registry.get_all_for_game(self.game_id)
            logger.debug(f"Game {self.game_id}: Retrieved {len(all_civcoms)} civcom(s) from registry")
            if not all_civcoms:
                logger.error(f"Game {self.game_id}: No CivComs registered for game; cannot start")
                self.phase = GamePhase.NATIONS_SELECTING
                return

            # Use first available CivCom (they all connect to same civserver port)
            registry_civcom = next(iter(all_civcoms.values()))
            logger.debug(f"Game {self.game_id}: Using civcom from {next(iter(all_civcoms.keys()))}")

            if hasattr(registry_civcom, 'is_alive') and not registry_civcom.is_alive():
                logger.error(f"Game {self.game_id}: Selected CivCom thread is not alive")
                self.phase = GamePhase.NATIONS_SELECTING
                return

            # Ensure all player handlers still have active civcom connections
            inactive_players = [
                info.agent_id for info in self.players.values()
                if not getattr(info.handler, 'civcom', None)
                or (hasattr(info.handler.civcom, 'is_alive') and not info.handler.civcom.is_alive())
            ]
            if inactive_players:
                logger.error(f"Game {self.game_id}: CivCom missing or dead for players: {inactive_players}")
                self.phase = GamePhase.NATIONS_SELECTING
                return

            # Get first player's handler to send commands
            first_player = next(iter(self.players.values()))
            civcom = first_player.handler.civcom

            if not civcom:
                logger.error(f"Game {self.game_id}: No civcom connection available!")
                return

            # Check if civcom connection is alive
            if not civcom.is_alive():
                logger.error(f"Game {self.game_id}: civcom connection is dead!")
                return

            # DO NOT send /set commands here!
            # Each /set command triggers reset_all_start_commands() in civserver,
            # which RESETS all players' is_ready flags to FALSE.
            # This undoes the PACKET_PLAYER_READY that players already sent!
            #
            # All settings (minplayers, maxplayers, aifill, autotoggle, timeout)
            # are already configured in pubscript_multiplayer.serv BEFORE players connect.
            #
            # GameSessionManager's ONLY job is to send /start when all players are ready.
            logger.info(f"Game {self.game_id}: All settings pre-configured in pubscript_multiplayer.serv")

            # Send explicit /start command to start the game
            # Multi-player games require /start command - they don't auto-start like single-player
            # All players have sent PACKET_PLAYER_READY, now we initiate the game
            logger.info(f"Game {self.game_id}: All {len(self.players)} players ready - sending /start command")
            civcom.queue_to_civserver(json.dumps({"pid": PACKET_CHAT_MSG_REQ, "message": "/start"}))
            civcom.send_packets_to_civserver()
            logger.info(f"Game {self.game_id}: ✅ /start command sent to civserver")

            # Mark as started
            self.game_started = True

            # Verify game actually started instead of blindly waiting
            # Poll civserver to confirm game initialization completed successfully
            logger.info(f"Game {self.game_id}: Verifying game start (waiting for turn > 0)...")
            start_time = time.time()
            max_wait = 10.0  # 10 seconds timeout for game to start
            game_confirmed = False

            while time.time() - start_time < max_wait:
                try:
                    # Check if civcom has received game state with turn > 0
                    if civcom and hasattr(civcom, 'get_full_state'):
                        # Try to get state from first player's civcom
                        state = civcom.get_full_state(first_player.player_id)
                        current_turn = state.get('turn', 0)

                        if current_turn > 0:
                            logger.info(f"✅ Game {self.game_id}: Game start verified! Turn={current_turn}")
                            game_confirmed = True
                            break

                    # Wait briefly before checking again
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.debug(f"Game {self.game_id}: State check failed (game may still be initializing): {e}")
                    await asyncio.sleep(0.5)

            if not game_confirmed:
                logger.warning(
                    f"⚠️ Game {self.game_id}: Could not verify game start after {max_wait}s\n"
                    f"   This may indicate civserver didn't start the game properly.\n"
                    f"   Proceeding anyway, but agents may receive empty game state."
                )
            else:
                elapsed = time.time() - start_time
                logger.info(f"Game {self.game_id}: Game confirmed started in {elapsed:.1f}s")

            self.phase = GamePhase.RUNNING
            logger.info(f"Game {self.game_id}: Game is now running")

            # Broadcast game_ready to all agents now that game has started
            # This notifies agents that the game is fully initialized and ready for state queries
            logger.info(f"Game {self.game_id}: Broadcasting game_ready signal to all {len(self.players)} players")
            for player_info in self.players.values():
                try:
                    # Send game_ready message to each player's handler
                    game_ready_msg = {
                        'type': 'game_ready',
                        'agent_id': player_info.agent_id,
                        'player_id': player_info.player_id,
                        'game_id': self.game_id,
                        'civserver_port': self.civserver_port,  # SPECTATOR FIX: Port for spectator URL generation
                        'turn': 1,  # Game just started at turn 1
                        'players': len(self.players),
                        'message': 'Game fully initialized - ready to accept state queries and actions',
                        'timestamp': time.time()
                    }
                    message_json = json.dumps(game_ready_msg)
                    # Schedule write on IOLoop to handle potential thread context issues
                    # This ensures write_message is called from the main Tornado thread
                    IOLoop.current().add_callback(player_info.handler.write_message, message_json)
                    logger.info(f"✅ Scheduled game_ready to {player_info.agent_id} (player_id={player_info.player_id})")
                except Exception as e:
                    logger.error(f"❌ Failed to schedule game_ready to {player_info.agent_id}: {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

        except Exception as e:
            logger.exception(f"Game {self.game_id}: Error starting game: {e}")
            self.phase = GamePhase.NATIONS_SELECTING

    def remove_player(self, agent_id: str) -> None:
        """Remove a player from the session"""
        if agent_id in self.players:
            del self.players[agent_id]
            logger.info(f"Game {self.game_id}: Removed player {agent_id}, "
                       f"remaining: {len(self.players)}")

    def get_status(self) -> Dict[str, Any]:
        """Get current session status"""
        return {
            "game_id": self.game_id,
            "phase": self.phase.value,
            "civserver_port": self.civserver_port,
            "player_count": len(self.players),
            "min_players": self.min_players,
            "nations_selected": self._count_nations_selected(),
            "players_ready": self._count_players_ready(),
            "game_started": self.game_started,
            "uptime": time.time() - self.created_at
        }


class GameSessionManager:
    """Global manager for all game sessions"""

    def __init__(self, metaserver_url: str = "http://localhost:8080"):
        self.sessions: Dict[str, GameSession] = {}
        self._lock = asyncio.Lock()
        self._port_lock = asyncio.Lock()  # Separate lock for port allocation
        self.metaserver_url = metaserver_url
        self._last_port_used = None  # Track last allocated port for round-robin

    async def _allocate_port_from_metaserver(self, game_id: str) -> Optional[int]:
        """Allocate a port from metaserver with game_id for persistent mapping.

        Makes a POST to /meta/allocate with game_id parameter. The metaserver will:
        - Return the same port if game_id already has an active allocation (reconnection)
        - Allocate a new port and store the mapping if game_id is new

        Args:
            game_id: Unique game identifier (e.g., match_id from agent-clash)

        Returns:
            Allocated port number, or None if allocation failed
        """
        try:
            async with aiohttp.ClientSession(self.metaserver_url) as session:
                # Make POST request with type=multiplayer and game_id for persistent mapping
                # The endpoint will return the same port for the same game_id on reconnection
                async with session.post(
                    "/meta/allocate",
                    params={"type": "multiplayer", "game_id": game_id},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success") and "port" in data:
                            port = data["port"]
                            reused = data.get("reused", False)
                            logger.info(
                                f"Metaserver allocated port {port} for game {game_id}\n"
                                f"   Reused existing allocation: {reused}"
                            )
                            return port
                        else:
                            logger.error(f"Metaserver allocate returned unexpected response: {data}")
                            return None
                    elif response.status == 503:
                        # No available servers
                        logger.warning(f"Metaserver reports no available multiplayer servers (503)")
                        return None
                    else:
                        logger.error(f"Metaserver allocate failed with status {response.status}")
                        return None

        except Exception as e:
            logger.error(f"Error allocating port from metaserver for game {game_id}: {e}")
            return None

    async def _query_metaserver_for_multiplayer_ports(self) -> list[int]:
        """Query metaserver /meta/allocate to find available multiplayer ports

        DEPRECATED: Use _allocate_port_from_metaserver() with game_id instead.
        This method is kept for backwards compatibility but will allocate without
        game_id persistence.

        Queries the metaserver's allocation endpoint to discover which ports
        are running multiplayer servers (type='multiplayer', available >= 1).

        Returns:
            List of available multiplayer server ports
            Empty list if query fails
        """
        try:
            async with aiohttp.ClientSession(self.metaserver_url) as session:
                # Make POST request with type=multiplayer to trigger allocation logic
                # The endpoint queries: SELECT * FROM servers WHERE type='multiplayer' AND available != 0
                # ROOT.war deploys at / context, so no /freeciv-web prefix
                async with session.post(
                    "/meta/allocate",
                    params={"type": "multiplayer"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success") and "port" in data:
                            # Got an allocated port - this is ONE available port
                            port = data["port"]
                            logger.info(f"Metaserver allocated port {port} for multiplayer game")

                            # Release it immediately since we're just querying
                            release_url = f"{self.metaserver_url}/meta/release"
                            async with session.post(
                                release_url,
                                data={"host": "localhost", "port": port},
                                timeout=aiohttp.ClientTimeout(total=5)
                            ) as release_response:
                                if release_response.status == 200:
                                    logger.debug(f"Released port {port} back to pool")

                            # Return this port as available
                            return [port]
                    elif response.status == 503:
                        # No available servers
                        logger.warning(f"Metaserver reports no available multiplayer servers (503), {response}")
                        return []
                    else:
                        logger.error(f"Metaserver allocate failed with status {response.status}")
                        return []

        except Exception as e:
            logger.error(f"Error querying metaserver for multiplayer ports: {e}")
            return []

    async def allocate_civserver_port(self, game_id: str) -> int:
        """Allocate a civserver port for a game by querying metaserver with game_id.

        Uses the metaserver /meta/allocate endpoint with game_id parameter for
        persistent game-port mapping. This enables:
        - Same port returned for same game_id on reconnection
        - Prevents the issue where reconnecting agents get a different port

        IMPORTANT: The metaserver now handles game_id -> port persistence in the
        game_allocations database table. This method passes game_id to leverage
        that persistence layer.

        THREAD-SAFETY: Creates placeholder session immediately to prevent race
        condition where two players with same game_id could get different ports
        within the same process.
        """
        async with self._port_lock:
            # Check if game already has an allocated port in local session cache (for second+ player)
            if game_id in self.sessions:
                port = self.sessions[game_id].civserver_port
                existing_session = self.sessions[game_id]
                player_count = len(existing_session.players)
                logger.info(
                    f"🔄 Game {game_id}: REUSING existing port {port} from local session\n"
                    f"   Current players in session: {player_count}\n"
                    f"   Session phase: {existing_session.phase.value}"
                )
                return port

            # Allocate port from metaserver with game_id for persistent mapping
            # The metaserver will return the same port for the same game_id (reconnection case)
            logger.info(f"🔍 Game {game_id}: Requesting port allocation from metaserver (with game_id persistence)")
            port = await self._allocate_port_from_metaserver(game_id)

            if port is None:
                # No servers available - fail allocation
                logger.error(
                    f"❌ Game {game_id}: No multiplayer servers available\n"
                    f"   Metaserver returned no available ports\n"
                    f"   This means either:\n"
                    f"   1. All multiplayer servers are in use\n"
                    f"   2. Metaserver is unreachable\n"
                    f"   3. Publite2 hasn't created any multiplayer servers yet\n"
                    f"   Cannot allocate port for this game."
                )
                raise RuntimeError(
                    "No multiplayer servers available. "
                    "Please wait for servers to become available or check metaserver status."
                )

            logger.info(f"✅ Game {game_id}: Allocated port {port} from metaserver (game_id persisted)")
            self._last_port_used = port

            total_sessions = len(self.sessions)
            logger.info(
                f"🆕 Game {game_id}: Allocated server port {port}\n"
                f"   Total active sessions: {total_sessions}\n"
                f"   Game-port mapping persisted in metaserver database"
            )

            # Create placeholder session immediately to reserve this port for this game_id
            # This prevents race condition where Player 2 could allocate different port
            # before Player 1 creates the session via get_or_create_session()
            session = GameSession(game_id, port, min_players=2)
            self.sessions[game_id] = session
            logger.debug(f"Game {game_id}: Created placeholder session to reserve port {port}")

            return port

    async def get_or_create_session(self, game_id: str, civserver_port: int,
                                   min_players: int = 2) -> GameSession:
        """Get existing session or create new one (thread-safe)"""
        logger.debug(f"GameSessionManager: get_or_create_session called for {game_id}")
        async with self._lock:
            logger.debug(f"GameSessionManager: Lock acquired for {game_id}")
            if game_id not in self.sessions:
                logger.debug(f"GameSessionManager: Creating new session for {game_id}")
                session = GameSession(game_id, civserver_port, min_players)
                self.sessions[game_id] = session
                logger.info(f"Created new game session: {game_id} on port {civserver_port}")
            else:
                logger.debug(f"GameSessionManager: Reusing existing session for {game_id}")
            return self.sessions[game_id]

    def get_session(self, game_id: str) -> Optional[GameSession]:
        """Get existing session"""
        return self.sessions.get(game_id)

    def remove_session(self, game_id: str) -> None:
        """Remove a game session"""
        if game_id in self.sessions:
            del self.sessions[game_id]
            logger.info(f"Removed game session: {game_id}")

    def get_all_sessions(self) -> Dict[str, GameSession]:
        """Get all active sessions"""
        return self.sessions.copy()

    def cleanup_old_sessions(self, max_age: float = 3600.0) -> None:
        """Remove sessions older than max_age seconds"""
        current_time = time.time()
        to_remove = []

        for game_id, session in self.sessions.items():
            if current_time - session.created_at > max_age:
                to_remove.append(game_id)

        for game_id in to_remove:
            logger.info(f"Cleaning up old session: {game_id}")
            self.remove_session(game_id)


# Global instance
game_session_manager = GameSessionManager()
