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
from typing import Dict, Set, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from state_extractor import civcom_registry

logger = logging.getLogger("freeciv-proxy")


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

    def add_player(self, agent_id: str, player_id: int, handler: Any) -> bool:
        """Add a player to the game session"""
        if len(self.players) >= self.max_players:
            logger.warning(f"Game {self.game_id}: Max players ({self.max_players}) reached")
            return False

        if agent_id in self.players:
            logger.warning(f"Game {self.game_id}: Player {agent_id} already in session")
            return False

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
            civcom.queue_to_civserver(json.dumps({"pid": 26, "message": "/start"}))
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
                    player_info.handler.write_message(json.dumps(game_ready_msg))
                    logger.info(f"✅ Sent game_ready to {player_info.agent_id} (player_id={player_info.player_id})")
                except Exception as e:
                    logger.error(f"❌ Failed to send game_ready to {player_info.agent_id}: {e}")
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

    def __init__(self):
        self.sessions: Dict[str, GameSession] = {}
        self._lock = asyncio.Lock()
        self._next_multiplayer_port = 6001  # Start with first multiplayer server
        self._port_lock = asyncio.Lock()  # Separate lock for port allocation

    async def allocate_civserver_port(self, game_id: str) -> int:
        """Allocate a civserver port for a game, reusing existing if available

        Multiplayer servers run on ODD ports (6001, 6003, 6005, 6007, 6009) and use
        pubscript_multiplayer.serv with aifill=2 (exactly 2 AI players for LLM agents to /take).

        Singleplayer servers run on EVEN ports (6000, 6002, 6004, 6006, 6008) and use
        pubscript_singleplayer.serv with aifill=12.

        CRITICAL: Only allocate ODD ports for LLM multiplayer games!

        THREAD-SAFETY: Creates placeholder session immediately to prevent race condition
        where two players with same game_id could get different ports if allocation
        happens before session creation.
        """
        async with self._port_lock:
            # Check if game already has an allocated port (for second+ player)
            if game_id in self.sessions:
                port = self.sessions[game_id].civserver_port
                existing_session = self.sessions[game_id]
                player_count = len(existing_session.players)
                is_multiplayer = port % 2 == 1  # Odd ports are multiplayer
                logger.info(
                    f"🔄 Game {game_id}: REUSING existing port {port}\n"
                    f"   Current players in session: {player_count}\n"
                    f"   Session phase: {existing_session.phase.value}\n"
                    f"   Port type: {'MULTIPLAYER (odd port)' if is_multiplayer else '⚠️ SINGLEPLAYER (even port) - WRONG!'}"
                )
                return port

            # Allocate next available multiplayer port using round-robin from publite2-created ports
            # NOTE: Publite2 creates ports ON-DEMAND, not upfront. Available ports depend on
            # metaserver activity and may include both multiplayer (odd) and singleplayer (even).
            # We iterate through 6001-6009 and USE WHICHEVER PORT EXISTS, regardless of odd/even.
            #
            # Previous approach (increment by 2 for odd ports) FAILED because:
            # - Assumed ports 6001, 6003, 6005, 6007, 6009 pre-exist (WRONG!)
            # - Publite2 creates ports dynamically: 6001, 6002, 6003, 6004, ...
            # - Allocating port 6005 when only 6001-6003 exist → Connection Refused (E140)
            port = self._next_multiplayer_port
            total_sessions = len(self.sessions)

            # Simple increment with wraparound (6001→6002→6003→...→6009→6001)
            next_port = port + 1
            if next_port > 6009:
                next_port = 6001

            is_multiplayer = port % 2 == 1
            logger.info(
                f"🆕 Game {game_id}: Allocated multiplayer server port {port}\n"
                f"   Total active sessions: {total_sessions}\n"
                f"   Next port will be: {next_port}\n"
                f"   Port type: {'MULTIPLAYER (odd)' if is_multiplayer else 'singleplayer (even)'}\n"
                f"   ⚠️ WARNING: Port allocation is best-effort. Port may not exist yet!"
            )

            # Create placeholder session immediately to reserve this port for this game_id
            # This prevents race condition where Player 2 could allocate different port
            # before Player 1 creates the session via get_or_create_session()
            session = GameSession(game_id, port, min_players=2)
            self.sessions[game_id] = session
            logger.debug(f"Game {game_id}: Created placeholder session to reserve port {port}")

            # Increment for next game (simple sequential)
            self._next_multiplayer_port = next_port

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
