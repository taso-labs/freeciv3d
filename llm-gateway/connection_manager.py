#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Connection Manager for LLM API Gateway
Handles WebSocket connections, heartbeats, and cleanup
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Any, Optional, Set, List
from fastapi import WebSocket, WebSocketDisconnect
try:
    from .config import settings
except ImportError:
    from config import settings

logger = logging.getLogger("llm-gateway")


class ConnectionInfo:
    """Information about a WebSocket connection"""

    def __init__(self, websocket: WebSocket, connection_type: str, identifier: str, session_id: Optional[str] = None):
        self.websocket = websocket
        self.connection_type = connection_type  # "agent" or "spectator"
        self.identifier = identifier  # agent_id or game_id
        self.connection_id = str(uuid.uuid4())
        self.session_id = session_id or str(uuid.uuid4())  # Persistent session ID
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.authenticated = False
        self.metadata: Dict[str, Any] = {}

        # Session persistence fields
        self.player_id: Optional[int] = None
        self.game_id: Optional[str] = None
        self.civserver_port: Optional[int] = None  # Port for observer URL generation
        self.disconnected_at: Optional[float] = None

    def update_activity(self):
        """Update last seen timestamp"""
        self.last_seen = time.time()

    def is_expired(self, timeout: int) -> bool:
        """Check if connection has expired"""
        return (time.time() - self.last_seen) > timeout

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/monitoring"""
        return {
            "connection_id": self.connection_id,
            "session_id": self.session_id,
            "type": self.connection_type,
            "identifier": self.identifier,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
            "authenticated": self.authenticated,
            "duration": time.time() - self.connected_at,
            "player_id": self.player_id,
            "game_id": self.game_id,
            "civserver_port": self.civserver_port,
            "disconnected_at": self.disconnected_at
        }


class ConnectionManager:
    """Manages WebSocket connections with heartbeat and cleanup"""

    def __init__(self):
        self.connections: Dict[str, ConnectionInfo] = {}
        self.agent_connections: Dict[str, Set[str]] = {}  # agent_id -> set of connection_ids
        self.spectator_connections: Dict[str, Set[str]] = {}  # game_id -> set of connection_ids
        self.disconnected_sessions: Dict[str, ConnectionInfo] = {}  # agent_id -> last ConnectionInfo for session resumption
        self.heartbeat_interval = settings.heartbeat_interval
        self.session_resumption_window = settings.session_resumption_window
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the connection manager"""
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Connection manager started")

    async def stop(self):
        """Stop the connection manager"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Close all connections
        await self._close_all_connections()
        logger.info("Connection manager stopped")

    async def check_resumable_session(self, identifier: str) -> Optional[ConnectionInfo]:
        """
        Check if a resumable session exists for the identifier

        Returns:
            ConnectionInfo if session can be resumed, None otherwise
        """
        if identifier not in self.disconnected_sessions:
            return None

        cached_session = self.disconnected_sessions[identifier]

        # Check if within resumption window
        if cached_session.disconnected_at is None:
            return None

        time_since_disconnect = time.time() - cached_session.disconnected_at

        if time_since_disconnect <= self.session_resumption_window:
            logger.info(
                f"Found resumable session for {identifier}: "
                f"session_id={cached_session.session_id}, "
                f"player_id={cached_session.player_id}, "
                f"disconnected {time_since_disconnect:.1f}s ago"
            )
            return cached_session
        else:
            # Session expired, clean it up
            logger.info(
                f"Cached session for {identifier} expired "
                f"({time_since_disconnect:.1f}s > {self.session_resumption_window}s)"
            )
            del self.disconnected_sessions[identifier]
            return None

    async def add_connection(self, websocket: WebSocket, connection_type: str, identifier: str) -> str:
        """Add a new WebSocket connection, potentially resuming a session"""
        # Check for resumable session
        cached_session = await self.check_resumable_session(identifier)

        if cached_session:
            # Resume existing session
            connection_info = ConnectionInfo(
                websocket, connection_type, identifier,
                session_id=cached_session.session_id  # Reuse session ID
            )
            connection_info.player_id = cached_session.player_id
            connection_info.game_id = cached_session.game_id
            connection_info.authenticated = cached_session.authenticated

            # Remove from disconnected cache
            del self.disconnected_sessions[identifier]

            logger.info(
                f"Resuming session for {connection_type} {identifier}: "
                f"session_id={connection_info.session_id}, player_id={connection_info.player_id}"
            )
        else:
            # Create new session
            connection_info = ConnectionInfo(websocket, connection_type, identifier)
            logger.info(
                f"Creating new session for {connection_type} {identifier}: "
                f"session_id={connection_info.session_id}"
            )

        connection_id = connection_info.connection_id

        # Check connection limits
        if connection_type == "agent":
            if identifier in self.agent_connections:
                if len(self.agent_connections[identifier]) >= settings.max_connections_per_agent:
                    raise ValueError(f"Too many connections for agent {identifier}")
            else:
                self.agent_connections[identifier] = set()

            self.agent_connections[identifier].add(connection_id)

        elif connection_type == "spectator":
            if identifier not in self.spectator_connections:
                self.spectator_connections[identifier] = set()
            self.spectator_connections[identifier].add(connection_id)

        self.connections[connection_id] = connection_info

        logger.info(f"Added {connection_type} connection {connection_id} for {identifier}")
        return connection_id

    async def remove_connection(self, connection_id: str):
        """Remove a WebSocket connection"""
        if connection_id not in self.connections:
            return

        connection_info = self.connections[connection_id]
        identifier = connection_info.identifier
        connection_type = connection_info.connection_type

        # Remove from type-specific tracking
        if connection_type == "agent" and identifier in self.agent_connections:
            self.agent_connections[identifier].discard(connection_id)
            if not self.agent_connections[identifier]:
                del self.agent_connections[identifier]

        elif connection_type == "spectator" and identifier in self.spectator_connections:
            self.spectator_connections[identifier].discard(connection_id)
            if not self.spectator_connections[identifier]:
                del self.spectator_connections[identifier]

        # Close WebSocket if still open
        try:
            await connection_info.websocket.close()
        except Exception as e:
            logger.warning(f"Error closing WebSocket {connection_id}: {e}")

        del self.connections[connection_id]
        logger.info(f"Removed {connection_type} connection {connection_id} for {identifier}")

    async def handle_disconnect(self, connection_id: str):
        """Handle graceful disconnection"""
        if connection_id in self.connections:
            connection_info = self.connections[connection_id]
            logger.info(f"Handling disconnect for {connection_info.connection_type} {connection_info.identifier}")

            # Perform cleanup based on connection type
            if connection_info.connection_type == "agent":
                await self._cleanup_agent_disconnect(connection_info)
            elif connection_info.connection_type == "spectator":
                await self._cleanup_spectator_disconnect(connection_info)

            await self.remove_connection(connection_id)

    async def maintain_connections(self):
        """Perform connection maintenance (heartbeat, cleanup, session cache cleanup)"""
        expired_connections = []

        for connection_id, connection_info in self.connections.items():
            try:
                # Check if connection has expired
                if connection_info.is_expired(settings.agent_timeout):
                    expired_connections.append(connection_id)
                    continue

                # Send heartbeat ping
                if connection_info.authenticated:
                    await self._send_heartbeat(connection_info)

            except Exception as e:
                logger.warning(f"Error maintaining connection {connection_id}: {e}")
                expired_connections.append(connection_id)

        # Remove expired connections
        for connection_id in expired_connections:
            await self.handle_disconnect(connection_id)

        # Clean up expired cached sessions
        now = time.time()
        expired_sessions = [
            agent_id for agent_id, session_info in self.disconnected_sessions.items()
            if session_info.disconnected_at and (now - session_info.disconnected_at) > self.session_resumption_window
        ]

        for agent_id in expired_sessions:
            session_info = self.disconnected_sessions[agent_id]
            logger.info(
                f"Removing expired cached session for {agent_id}: "
                f"session_id={session_info.session_id}, "
                f"disconnected {now - session_info.disconnected_at:.1f}s ago"
            )
            del self.disconnected_sessions[agent_id]

    async def get_agent_connections(self, agent_id: str) -> List[ConnectionInfo]:
        """Get all connections for a specific agent"""
        if agent_id not in self.agent_connections:
            return []

        connections = []
        for connection_id in self.agent_connections[agent_id]:
            if connection_id in self.connections:
                connections.append(self.connections[connection_id])

        return connections

    async def get_spectator_connections(self, game_id: str) -> List[ConnectionInfo]:
        """Get all spectator connections for a game"""
        if game_id not in self.spectator_connections:
            return []

        connections = []
        for connection_id in self.spectator_connections[game_id]:
            if connection_id in self.connections:
                connections.append(self.connections[connection_id])

        return connections

    async def send_to_agent(self, agent_id: str, message: Dict[str, Any]) -> bool:
        """Send message to a specific agent (first available connection)"""
        agent_connections = await self.get_agent_connections(agent_id)

        if not agent_connections:
            return False

        # Use the first authenticated connection
        for connection_info in agent_connections:
            if connection_info.authenticated:
                try:
                    await connection_info.websocket.send_text(json.dumps(message))
                    return True
                except Exception as e:
                    logger.warning(f"Error sending to agent {agent_id}: {e}")
                    asyncio.create_task(self.handle_disconnect(connection_info.connection_id))

        return False

    async def broadcast_to_spectators(self, game_id: str, message: Dict[str, Any]):
        """Broadcast message to all spectators of a game"""
        spectator_connections = await self.get_spectator_connections(game_id)

        if not spectator_connections:
            logger.debug(f"No spectators connected to game {game_id}")
            return

        failed_connections = []
        successful_broadcasts = 0

        for connection_info in spectator_connections:
            try:
                await connection_info.websocket.send_text(json.dumps(message))
                connection_info.update_activity()
                successful_broadcasts += 1
            except Exception as e:
                logger.warning(f"Error broadcasting to spectator {connection_info.connection_id}: {e}")
                failed_connections.append(connection_info.connection_id)

        # Clean up failed connections
        for connection_id in failed_connections:
            asyncio.create_task(self.handle_disconnect(connection_id))

        if successful_broadcasts > 0:
            logger.debug(f"Broadcasted to {successful_broadcasts} spectators of game {game_id}")

    async def update_agent_auth(
        self,
        agent_id: str,
        player_id: int,
        game_id: Optional[str] = None,
        civserver_port: Optional[int] = None
    ):
        """Update agent authentication info after receiving auth_success from proxy

        Args:
            agent_id: Agent identifier
            player_id: Player ID from civserver
            game_id: Optional game ID
            civserver_port: Optional civserver port for observer URL generation
        """
        agent_connections = await self.get_agent_connections(agent_id)

        for connection_info in agent_connections:
            connection_info.player_id = player_id
            connection_info.authenticated = True
            if game_id:
                connection_info.game_id = game_id
            if civserver_port:
                connection_info.civserver_port = civserver_port

            logger.info(
                f"✅ Updated auth for agent {agent_id}: "
                f"player_id={player_id}, game_id={game_id}, "
                f"civserver_port={civserver_port}, "
                f"session_id={connection_info.session_id}"
            )

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        total_connections = len(self.connections)
        agent_count = len(self.agent_connections)
        spectator_count = sum(len(connections) for connections in self.spectator_connections.values())

        return {
            "total_connections": total_connections,
            "agent_connections": agent_count,
            "spectator_connections": spectator_count,
            "active_games": len(self.spectator_connections),
            "connections_by_type": {
                "agent": agent_count,
                "spectator": spectator_count
            }
        }

    async def get_game_info(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Get game info by game_id from authenticated agent connections.

        Searches all agent connections for one with matching game_id and returns
        its game-related info (port, player_id, agent_id). Used by observer-urls
        endpoint to retrieve civserver port for URL generation.

        Args:
            game_id: The game ID to search for

        Returns:
            Dict with civserver_port, player_id, agent_id if found, None otherwise
        """
        for conn_id, conn_info in self.connections.items():
            if (conn_info.connection_type == "agent"
                and conn_info.game_id == game_id
                and conn_info.authenticated):
                return {
                    "civserver_port": conn_info.civserver_port,
                    "player_id": conn_info.player_id,
                    "agent_id": conn_info.identifier,
                    "session_id": conn_info.session_id,
                    "connected_at": conn_info.connected_at,
                }
        return None

    async def _heartbeat_loop(self):
        """Background task for connection maintenance"""
        while self._running:
            try:
                await self.maintain_connections()
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(5)  # Brief pause before retrying

    async def _send_heartbeat(self, connection_info: ConnectionInfo):
        """Send heartbeat ping to a connection"""
        try:
            ping_message = {
                "type": "ping",
                "timestamp": time.time(),
                "connection_id": connection_info.connection_id
            }
            await connection_info.websocket.send_text(json.dumps(ping_message))
            connection_info.update_activity()

        except Exception as e:
            logger.warning(f"Heartbeat failed for {connection_info.connection_id}: {e}")
            raise

    async def _cleanup_agent_disconnect(self, connection_info: ConnectionInfo):
        """Cleanup when an agent disconnects - cache session for potential resumption"""
        agent_id = connection_info.identifier

        # Log agent disconnection
        duration = time.time() - connection_info.connected_at
        logger.info(
            f"Agent {agent_id} disconnected after {duration:.1f}s "
            f"(session_id={connection_info.session_id}, player_id={connection_info.player_id})"
        )

        # Cache ALL sessions for resumption (even if not fully authenticated)
        # This allows agents to recover from early disconnects before auth completes
        connection_info.disconnected_at = time.time()
        self.disconnected_sessions[agent_id] = connection_info
        logger.info(
            f"Cached session for agent {agent_id} (will expire in {self.session_resumption_window}s): "
            f"session_id={connection_info.session_id}, player_id={connection_info.player_id}, "
            f"authenticated={connection_info.authenticated}"
        )

    async def _cleanup_spectator_disconnect(self, connection_info: ConnectionInfo):
        """Cleanup when a spectator disconnects"""
        game_id = connection_info.identifier

        # Log spectator disconnection
        logger.info(f"Spectator disconnected from game {game_id}")

        # Minimal cleanup needed for spectators

    async def _close_all_connections(self):
        """Close all connections during shutdown"""
        connection_ids = list(self.connections.keys())

        for connection_id in connection_ids:
            try:
                await self.handle_disconnect(connection_id)
            except Exception as e:
                logger.warning(f"Error closing connection {connection_id}: {e}")


# Global connection manager instance
connection_manager = ConnectionManager()