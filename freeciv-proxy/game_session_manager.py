#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Game Session Manager
Coordinates multi-player game initialization to prevent race conditions
"""

import asyncio
import json
import logging
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
            # Brief delay to ensure all packets have been processed
            logger.debug(f"Game {self.game_id}: Waiting 2s before start for packet processing")
            await asyncio.sleep(2.0)

            # Double-check we're still ready
            ready_count = self._count_players_ready()
            logger.debug(f"Game {self.game_id}: Double-checking readiness ({ready_count}/{len(self.players)})")
            if ready_count < len(self.players):
                logger.warning(f"Game {self.game_id}: Players no longer ready, aborting start")
                self.phase = GamePhase.NATIONS_SELECTING
                return

            self.phase = GamePhase.STARTING
            logger.info(f"Game {self.game_id}: Starting game with {len(self.players)} players")

            registry_civcom = civcom_registry.get_civcom(self.game_id)
            logger.debug(f"Game {self.game_id}: Retrieved civcom from registry: {registry_civcom is not None}")
            if not registry_civcom:
                logger.error(f"Game {self.game_id}: No CivCom registered for game; cannot start")
                self.phase = GamePhase.NATIONS_SELECTING
                return

            if hasattr(registry_civcom, 'is_alive') and not registry_civcom.is_alive():
                logger.error(f"Game {self.game_id}: Registered CivCom thread is not alive")
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

            # Send game settings
            logger.info(f"Game {self.game_id}: Configuring game settings")

            # NOTE: We do NOT remove AI players because agents use /take to control them
            # AI players AI*1, AI*2, etc. are taken over by the LLM agents
            # IMPORTANT: Do NOT set aifill to 0 here - it will remove AI players that agents are trying to /take!

            logger.debug(f"Game {self.game_id}: Setting game parameters")
            civcom.queue_to_civserver(json.dumps({"pid": 26, "message": f"/set minplayers {len(self.players)}"}))
            # DO NOT SET aifill 0 - removed to prevent removing AI players before /take completes
            # civcom.queue_to_civserver(json.dumps({"pid": 26, "message": "/set aifill 0"}))
            civcom.queue_to_civserver(json.dumps({"pid": 26, "message": f"/set maxplayers {len(self.players)}"}))
            civcom.queue_to_civserver(json.dumps({"pid": 26, "message": "/set autotoggle enabled"}))
            civcom.queue_to_civserver(json.dumps({"pid": 26, "message": "/set timeout 0"}))

            # Wait for settings to apply
            logger.debug(f"Game {self.game_id}: Waiting 2s for settings to apply")
            await asyncio.sleep(2.0)

            # FIXED: Game auto-starts when all players send PACKET_PLAYER_READY (pid=11)
            # See llm_handler.py:342-347 where PACKET_PLAYER_READY is sent
            # FreeCiv's handle_player_ready() automatically calls start_game() when all ready
            # No need to send /start or /mapgen - they're redundant and /mapgen doesn't exist!
            logger.info(f"Game {self.game_id}: All {len(self.players)} players ready - waiting for auto-start")

            # Mark as started
            self.game_started = True

            # Wait for game to initialize
            await asyncio.sleep(3.0)

            self.phase = GamePhase.RUNNING
            logger.info(f"Game {self.game_id}: Game is now running")

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
