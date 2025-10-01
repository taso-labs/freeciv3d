#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Connection State Manager for LLM API Gateway
Thread-safe management of proxy connections to prevent race conditions
"""

import asyncio
import logging
import time
import websockets
from typing import Dict, Any, Optional, Set, List
from dataclasses import dataclass
from enum import Enum

try:
    from .utils.constants import CONNECTION_POOL_MAX, HEALTH_CHECK_INTERVAL, HEALTH_CHECK_TIMEOUT, CLEANUP_CYCLE_SECONDS, GLOBAL_CONNECTION_LIMIT
except ImportError:
    from utils.constants import CONNECTION_POOL_MAX, HEALTH_CHECK_INTERVAL, HEALTH_CHECK_TIMEOUT, CLEANUP_CYCLE_SECONDS, GLOBAL_CONNECTION_LIMIT

logger = logging.getLogger("llm-gateway")


# Global connection counter to track across all instances
class GlobalConnectionTracker:
    """Tracks global connection count across all managers"""
    _instance = None
    _lock = asyncio.Lock()
    _global_count = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def can_add_connection(self) -> bool:
        """Check if we can add a new connection without exceeding global limit"""
        async with self._lock:
            return self._global_count < GLOBAL_CONNECTION_LIMIT

    async def add_connection(self) -> bool:
        """Add a connection to global count"""
        async with self._lock:
            if self._global_count >= GLOBAL_CONNECTION_LIMIT:
                return False
            self._global_count += 1
            return True

    async def remove_connection(self):
        """Remove a connection from global count"""
        async with self._lock:
            if self._global_count > 0:
                self._global_count -= 1

    async def get_count(self) -> int:
        """Get current global connection count"""
        async with self._lock:
            return self._global_count


# Global instance
global_connection_tracker = GlobalConnectionTracker()


class ConnectionStatus(Enum):
    """Connection status enumeration"""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    RECONNECTING = "reconnecting"


@dataclass
class ConnectionInfo:
    """Information about a proxy connection"""
    connection: Optional[websockets.WebSocketServerProtocol]
    status: ConnectionStatus
    game_id: str
    created_at: float
    last_used: float
    retry_count: int = 0
    last_error: Optional[str] = None
    health_check_failures: int = 0


class ConnectionStateManager:
    """
    Thread-safe manager for proxy connections
    Prevents race conditions when modifying shared connection state
    """

    def __init__(self, max_connections: int = CONNECTION_POOL_MAX, health_check_interval: float = HEALTH_CHECK_INTERVAL):
        self._connections: Dict[str, ConnectionInfo] = {}
        self._connection_lock = asyncio.Lock()
        self._health_lock = asyncio.Lock()

        # Connection limits and timeouts
        self.max_connections = max_connections
        self.global_connection_limit = GLOBAL_CONNECTION_LIMIT
        self.health_check_interval = health_check_interval
        self.connection_timeout = 10.0
        self.max_retry_count = 3
        self.max_health_failures = 3

        # Background tasks
        self._health_check_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

        # Statistics
        self._stats = {
            "total_connections": 0,
            "active_connections": 0,
            "failed_connections": 0,
            "reconnections": 0,
            "health_check_failures": 0,
            "global_connections": 0,
            "rejected_global_limit": 0
        }

    async def start(self):
        """Start the connection state manager"""
        self._running = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("ConnectionStateManager started")

    async def stop(self):
        """Stop the connection state manager"""
        self._running = False

        # Cancel background tasks
        if self._health_check_task:
            self._health_check_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()

        # Wait for tasks to complete
        for task in [self._health_check_task, self._cleanup_task]:
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close all connections
        await self._close_all_connections()
        logger.info("ConnectionStateManager stopped")

    async def add_connection(
        self,
        game_id: str,
        connection: websockets.WebSocketServerProtocol
    ) -> bool:
        """
        Add a new proxy connection (thread-safe)

        Args:
            game_id: Game identifier
            connection: WebSocket connection

        Returns:
            bool: True if added successfully, False if at capacity
        """
        # Check global connection limit first
        if not await global_connection_tracker.can_add_connection():
            logger.warning(f"Global connection limit reached ({self.global_connection_limit})")
            self._stats["rejected_global_limit"] += 1
            return False

        async with self._connection_lock:
            # Check local capacity
            if len(self._connections) >= self.max_connections:
                logger.warning(f"Local connection capacity reached ({self.max_connections})")
                return False

            # Reserve global connection slot
            if not await global_connection_tracker.add_connection():
                logger.warning(f"Failed to reserve global connection slot")
                return False

            try:
                # Close existing connection if any
                if game_id in self._connections:
                    await self._close_connection_unsafe(game_id)

                # Add new connection
                connection_info = ConnectionInfo(
                    connection=connection,
                    status=ConnectionStatus.CONNECTED,
                    game_id=game_id,
                    created_at=time.time(),
                    last_used=time.time()
                )

                self._connections[game_id] = connection_info
                self._stats["total_connections"] += 1
                self._stats["active_connections"] += 1
                self._stats["global_connections"] = await global_connection_tracker.get_count()

                logger.info(f"Added connection for game {game_id} (global: {self._stats['global_connections']})")
                return True

            except Exception as e:
                # Release global connection slot on error
                await global_connection_tracker.remove_connection()
                logger.error(f"Failed to add connection for game {game_id}: {e}")
                return False

    async def remove_connection(self, game_id: str) -> bool:
        """
        Remove a proxy connection (thread-safe)

        Args:
            game_id: Game identifier

        Returns:
            bool: True if removed, False if not found
        """
        async with self._connection_lock:
            return await self._remove_connection_unsafe(game_id)

    async def get_connection(self, game_id: str) -> Optional[websockets.WebSocketServerProtocol]:
        """
        Get a proxy connection (thread-safe)

        Args:
            game_id: Game identifier

        Returns:
            WebSocket connection or None if not found/not healthy
        """
        async with self._connection_lock:
            connection_info = self._connections.get(game_id)

            if not connection_info:
                return None

            if connection_info.status != ConnectionStatus.CONNECTED:
                return None

            # Update last used time
            connection_info.last_used = time.time()

            return connection_info.connection

    async def mark_connection_failed(self, game_id: str, error: str = None):
        """
        Mark a connection as failed (thread-safe)

        Args:
            game_id: Game identifier
            error: Optional error message
        """
        async with self._connection_lock:
            connection_info = self._connections.get(game_id)

            if connection_info:
                connection_info.status = ConnectionStatus.FAILED
                connection_info.last_error = error
                connection_info.retry_count += 1
                self._stats["failed_connections"] += 1

                logger.warning(f"Connection failed for game {game_id}: {error}")

    async def is_connection_healthy(self, game_id: str) -> bool:
        """
        Check if connection is healthy (thread-safe)

        Args:
            game_id: Game identifier

        Returns:
            bool: True if healthy, False otherwise
        """
        async with self._connection_lock:
            connection_info = self._connections.get(game_id)

            if not connection_info:
                return False

            if connection_info.status != ConnectionStatus.CONNECTED:
                return False

            if not connection_info.connection:
                return False

            # Check if WebSocket is closed (close_code is None when open)
            if connection_info.connection.close_code is not None:
                await self._mark_connection_unhealthy_unsafe(game_id)
                return False

            return True

    async def get_all_connections(self) -> Dict[str, ConnectionInfo]:
        """
        Get all connections (thread-safe copy)

        Returns:
            Dict of game_id -> ConnectionInfo
        """
        async with self._connection_lock:
            # Return a copy to avoid external modifications
            return {
                game_id: ConnectionInfo(
                    connection=info.connection,
                    status=info.status,
                    game_id=info.game_id,
                    created_at=info.created_at,
                    last_used=info.last_used,
                    retry_count=info.retry_count,
                    last_error=info.last_error,
                    health_check_failures=info.health_check_failures
                )
                for game_id, info in self._connections.items()
            }

    async def get_stats(self) -> Dict[str, Any]:
        """Get connection statistics"""
        async with self._connection_lock:
            active_count = sum(
                1 for info in self._connections.values()
                if info.status == ConnectionStatus.CONNECTED
            )

            self._stats["active_connections"] = active_count

            return {
                **self._stats,
                "total_managed_connections": len(self._connections),
                "max_connections": self.max_connections,
                "health_check_interval": self.health_check_interval
            }

    # Internal methods (require lock to be held)

    async def _remove_connection_unsafe(self, game_id: str) -> bool:
        """Remove connection without acquiring lock (unsafe)"""
        connection_info = self._connections.pop(game_id, None)

        if connection_info:
            await self._close_connection_info(connection_info)
            self._stats["active_connections"] = max(0, self._stats["active_connections"] - 1)

            # Release global connection slot
            await global_connection_tracker.remove_connection()
            self._stats["global_connections"] = await global_connection_tracker.get_count()

            logger.info(f"Removed connection for game {game_id} (global: {self._stats['global_connections']})")
            return True

        return False

    async def _close_connection_unsafe(self, game_id: str):
        """Close connection without acquiring lock (unsafe)"""
        connection_info = self._connections.get(game_id)
        if connection_info:
            await self._close_connection_info(connection_info)

    async def _close_connection_info(self, connection_info: ConnectionInfo):
        """Close a connection info object"""
        if connection_info.connection:
            try:
                if connection_info.connection.close_code is None:
                    await connection_info.connection.close()
            except Exception as e:
                logger.debug(f"Error closing connection: {e}")

    async def _mark_connection_unhealthy_unsafe(self, game_id: str):
        """Mark connection as unhealthy without acquiring lock (unsafe)"""
        connection_info = self._connections.get(game_id)
        if connection_info:
            connection_info.status = ConnectionStatus.FAILED
            connection_info.health_check_failures += 1

    async def _close_all_connections(self):
        """Close all connections"""
        async with self._connection_lock:
            for game_id in list(self._connections.keys()):
                await self._remove_connection_unsafe(game_id)

    # Background tasks

    async def _health_check_loop(self):
        """Background task to check connection health"""
        logger.info(f"Health check loop started (interval: {self.health_check_interval}s)")

        while self._running:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._perform_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")

    async def _perform_health_checks(self):
        """Perform health checks on all connections"""
        # Get a snapshot of connections
        connections = await self.get_all_connections()

        unhealthy_connections = []

        for game_id, connection_info in connections.items():
            if connection_info.status != ConnectionStatus.CONNECTED:
                continue

            try:
                # Check if connection is still open (close_code is None when open)
                if connection_info.connection and connection_info.connection.close_code is None:
                    # Send ping to test connection
                    await asyncio.wait_for(
                        connection_info.connection.ping(),
                        timeout=HEALTH_CHECK_TIMEOUT
                    )
                else:
                    unhealthy_connections.append(game_id)

            except Exception as e:
                logger.debug(f"Health check failed for game {game_id}: {e}")
                unhealthy_connections.append(game_id)
                self._stats["health_check_failures"] += 1

        # Mark unhealthy connections (with race condition protection)
        async with self._connection_lock:
            validated_unhealthy = []
            for game_id in unhealthy_connections:
                # Check if connection still exists and is in the same state
                connection_info = self._connections.get(game_id)
                if (connection_info and
                    connection_info.status == ConnectionStatus.CONNECTED):
                    await self._mark_connection_unhealthy_unsafe(game_id)
                    validated_unhealthy.append(game_id)

        if validated_unhealthy:
            logger.info(f"Marked {len(validated_unhealthy)} connections as unhealthy")

    async def _cleanup_loop(self):
        """Background task to clean up failed connections"""
        while self._running:
            try:
                await asyncio.sleep(CLEANUP_CYCLE_SECONDS)  # Run cleanup every minute
                await self._cleanup_failed_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    async def _cleanup_failed_connections(self):
        """Clean up connections that have failed beyond retry limits"""
        cleanup_candidates = []

        async with self._connection_lock:
            for game_id, connection_info in list(self._connections.items()):
                # Clean up connections that have failed too many times
                if (connection_info.health_check_failures >= self.max_health_failures or
                    connection_info.retry_count >= self.max_retry_count):
                    cleanup_candidates.append(game_id)

                # Clean up very old disconnected connections
                elif (connection_info.status in [ConnectionStatus.FAILED, ConnectionStatus.DISCONNECTED] and
                      time.time() - connection_info.last_used > 3600):  # 1 hour
                    cleanup_candidates.append(game_id)

        # Remove failed connections
        for game_id in cleanup_candidates:
            await self.remove_connection(game_id)

        if cleanup_candidates:
            logger.info(f"Cleaned up {len(cleanup_candidates)} failed connections")


# Global instance for use across the application
connection_state_manager = ConnectionStateManager()