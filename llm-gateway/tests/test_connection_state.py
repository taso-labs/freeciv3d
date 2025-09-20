#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for ConnectionStateManager - Thread-safe connection management
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from connection_state_manager import ConnectionStateManager, ConnectionStatus, ConnectionInfo


class TestConnectionStateManager:
    """Test ConnectionStateManager functionality"""

    @pytest.mark.asyncio
    async def test_connection_manager_initialization(self):
        """Test ConnectionStateManager initializes properly"""
        manager = ConnectionStateManager(max_connections=10)

        assert manager.max_connections == 10
        assert len(manager._connections) == 0

    @pytest.mark.asyncio
    async def test_add_and_get_connection(self):
        """Test adding and retrieving connections"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Mock WebSocket connection
            mock_ws = AsyncMock()
            mock_ws.closed = False

            # Add connection
            success = await manager.add_connection("game1", mock_ws)

            assert success is True

            # Get connection
            connection = await manager.get_connection("game1")

            assert connection == mock_ws

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_connection_capacity_limit(self):
        """Test connection capacity enforcement"""
        manager = ConnectionStateManager(max_connections=2)
        await manager.start()

        try:
            # Add connections up to capacity
            mock_ws1 = AsyncMock()
            mock_ws1.closed = False
            mock_ws2 = AsyncMock()
            mock_ws2.closed = False
            mock_ws3 = AsyncMock()
            mock_ws3.closed = False

            success1 = await manager.add_connection("game1", mock_ws1)
            success2 = await manager.add_connection("game2", mock_ws2)
            success3 = await manager.add_connection("game3", mock_ws3)

            assert success1 is True
            assert success2 is True
            assert success3 is False  # Should be rejected due to capacity

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_remove_connection(self):
        """Test removing connections"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Add connection
            mock_ws = AsyncMock()
            mock_ws.closed = False

            await manager.add_connection("game1", mock_ws)

            # Remove connection
            success = await manager.remove_connection("game1")

            assert success is True

            # Should not be able to get connection anymore
            connection = await manager.get_connection("game1")
            assert connection is None

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_connection_health_check(self):
        """Test connection health checking"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Add healthy connection
            mock_ws = AsyncMock()
            mock_ws.closed = False

            await manager.add_connection("game1", mock_ws)

            # Should be healthy
            is_healthy = await manager.is_connection_healthy("game1")
            assert is_healthy is True

            # Mark as closed
            mock_ws.closed = True

            # Should now be unhealthy
            is_healthy = await manager.is_connection_healthy("game1")
            assert is_healthy is False

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_mark_connection_failed(self):
        """Test marking connections as failed"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Add connection
            mock_ws = AsyncMock()
            mock_ws.closed = False

            await manager.add_connection("game1", mock_ws)

            # Mark as failed
            await manager.mark_connection_failed("game1", "Test error")

            # Connection should not be healthy
            is_healthy = await manager.is_connection_healthy("game1")
            assert is_healthy is False

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_concurrent_access(self):
        """Test thread safety with concurrent access"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Create multiple concurrent operations
            async def add_connections():
                tasks = []
                for i in range(20):
                    mock_ws = AsyncMock()
                    mock_ws.closed = False
                    task = manager.add_connection(f"game{i}", mock_ws)
                    tasks.append(task)
                return await asyncio.gather(*tasks)

            async def get_connections():
                tasks = []
                for i in range(20):
                    task = manager.get_connection(f"game{i}")
                    tasks.append(task)
                return await asyncio.gather(*tasks)

            # Run concurrent operations
            add_results, get_results = await asyncio.gather(
                add_connections(),
                get_connections()
            )

            # Should not crash and should maintain consistency
            # (Some gets might return None due to timing, but no exceptions)
            assert len(add_results) == 20
            assert len(get_results) == 20

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_replace_existing_connection(self):
        """Test replacing an existing connection"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Add first connection
            mock_ws1 = AsyncMock()
            mock_ws1.closed = False

            await manager.add_connection("game1", mock_ws1)

            # Add second connection with same game_id
            mock_ws2 = AsyncMock()
            mock_ws2.closed = False

            success = await manager.add_connection("game1", mock_ws2)

            assert success is True

            # Should get the new connection
            connection = await manager.get_connection("game1")
            assert connection == mock_ws2

            # Old connection should have been closed
            mock_ws1.close.assert_called_once()

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Test statistics tracking"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Add some connections
            for i in range(3):
                mock_ws = AsyncMock()
                mock_ws.closed = False
                await manager.add_connection(f"game{i}", mock_ws)

            # Mark one as failed
            await manager.mark_connection_failed("game1", "Test error")

            stats = await manager.get_stats()

            assert stats["total_managed_connections"] == 3
            assert stats["total_connections"] == 3
            assert stats["failed_connections"] == 1

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_get_all_connections(self):
        """Test getting all connections safely"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Add connections
            for i in range(3):
                mock_ws = AsyncMock()
                mock_ws.closed = False
                await manager.add_connection(f"game{i}", mock_ws)

            # Get all connections
            all_connections = await manager.get_all_connections()

            assert len(all_connections) == 3
            assert "game0" in all_connections
            assert "game1" in all_connections
            assert "game2" in all_connections

            # Should be copies, not references
            assert isinstance(all_connections["game0"], ConnectionInfo)

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_cleanup_failed_connections(self):
        """Test cleanup of failed connections"""
        manager = ConnectionStateManager()
        await manager.start()

        try:
            # Add connection
            mock_ws = AsyncMock()
            mock_ws.closed = False
            await manager.add_connection("game1", mock_ws)

            # Mark as failed multiple times to exceed retry limit
            for _ in range(5):
                await manager.mark_connection_failed("game1", "Test error")

            # Trigger cleanup
            await manager._cleanup_failed_connections()

            # Connection should be removed
            connection = await manager.get_connection("game1")
            assert connection is None

        finally:
            await manager.stop()


if __name__ == "__main__":
    pytest.main([__file__])