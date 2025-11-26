#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for connection race conditions
Addresses critical issue: Race conditions when modifying shared connection state
"""

import pytest
import pytest_asyncio
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from connection_state_manager import (
    ConnectionStateManager,
    ConnectionStatus,
    GlobalConnectionTracker,
    global_connection_tracker
)


class MockWebSocket:
    """Mock WebSocket for testing"""
    def __init__(self, closed=False):
        self.closed = closed
        self.close_code = None if not closed else 1000
        self.close_called = False

    async def close(self):
        self.close_called = True
        self.closed = True
        self.close_code = 1000

    async def send(self, message):
        if self.closed:
            raise Exception("Connection closed")

    async def recv(self):
        if self.closed:
            raise Exception("Connection closed")
        await asyncio.sleep(0.1)
        return '{"type": "test"}'


class TestConnectionRaceConditions:
    """Test suite for connection race condition handling"""

    @pytest_asyncio.fixture
    async def manager(self):
        """Create a fresh connection manager for each test"""
        mgr = ConnectionStateManager(max_connections=100)
        await mgr.start()
        yield mgr
        await mgr.stop()

    @pytest_asyncio.fixture
    async def reset_global_tracker(self):
        """Reset global connection tracker before each test"""
        # Reset the global tracker
        global global_connection_tracker
        async with global_connection_tracker._lock:
            global_connection_tracker._global_count = 0
        yield
        # Clean up after test
        async with global_connection_tracker._lock:
            global_connection_tracker._global_count = 0

    @pytest.mark.asyncio
    async def test_concurrent_connection_additions(self, manager, reset_global_tracker):
        """Multiple coroutines adding connections shouldn't corrupt state"""
        # RED: This test should initially fail if there are race conditions

        async def add_connections(start_idx, count):
            """Add multiple connections concurrently"""
            results = []
            for i in range(count):
                game_id = f"game_{start_idx + i}"
                ws = MockWebSocket()
                result = await manager.add_connection(game_id, ws)
                results.append(result)
            return results

        # Run 10 concurrent tasks, each adding 10 connections
        tasks = [add_connections(i * 10, 10) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Verify no lost updates
        total_added = sum(sum(r) for r in results)
        assert total_added == 100, f"Expected 100 connections added, got {total_added}"

        # Verify internal state consistency
        stats = await manager.get_stats()
        assert stats["active_connections"] == 100
        assert len(manager._connections) == 100

    @pytest.mark.asyncio
    async def test_concurrent_add_and_remove(self, manager, reset_global_tracker):
        """Adding and removing connections concurrently should be safe"""
        # RED: Should detect race conditions in add/remove operations

        # First add some connections
        for i in range(20):
            await manager.add_connection(f"game_{i}", MockWebSocket())

        async def add_task():
            for i in range(20, 30):
                await manager.add_connection(f"game_{i}", MockWebSocket())
                await asyncio.sleep(0.001)

        async def remove_task():
            for i in range(0, 10):
                await manager.remove_connection(f"game_{i}")
                await asyncio.sleep(0.001)

        # Run concurrently
        await asyncio.gather(add_task(), remove_task())

        # Should have 20 connections (started with 20, added 10, removed 10)
        stats = await manager.get_stats()
        assert stats["active_connections"] == 20

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, manager, reset_global_tracker):
        """Concurrent health checks shouldn't corrupt connection state"""
        # RED: Tests health check locking

        # Add connections
        for i in range(10):
            await manager.add_connection(f"game_{i}", MockWebSocket())

        # Run multiple health checks concurrently
        async def run_health_check(game_id):
            return await manager.is_connection_healthy(game_id)

        # Check health of first game concurrently from multiple tasks
        tasks = [run_health_check("game_0") for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # All health checks should return same result (no corruption)
        first_result = results[0]
        for result in results[1:]:
            assert result == first_result

    @pytest.mark.asyncio
    async def test_connection_replacement_race(self, manager, reset_global_tracker):
        """Replacing existing connection should be atomic"""
        # RED: Tests atomic connection replacement

        game_id = "game_test"
        original_ws = MockWebSocket()
        await manager.add_connection(game_id, original_ws)

        async def replace_connection(replacement_id):
            new_ws = MockWebSocket()
            # Mark as specific replacement for tracking
            new_ws.replacement_id = replacement_id
            return await manager.add_connection(game_id, new_ws)

        # Try to replace connection from multiple tasks
        tasks = [replace_connection(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # All should succeed (each replaces the previous)
        assert all(results), "All replacements should succeed"

        # Should have exactly 1 connection
        conn = await manager.get_connection(game_id)
        assert conn is not None
        assert hasattr(conn, 'replacement_id')

        # Original connection should be closed
        assert original_ws.close_called

    @pytest.mark.asyncio
    async def test_global_connection_limit_race(self, reset_global_tracker):
        """Global connection tracker should prevent race conditions"""
        # RED: Tests GlobalConnectionTracker locking

        tracker = GlobalConnectionTracker()

        async def try_add_connection():
            return await tracker.add_connection()

        # Try to add 50 connections concurrently (well within limit)
        # This tests that concurrent adds don't cause lost updates
        tasks = [try_add_connection() for _ in range(50)]
        results = await asyncio.gather(*tasks)

        # All should succeed since we're under the limit
        added_count = sum(results)
        current_count = await tracker.get_count()

        # Count should match successful additions
        assert added_count == current_count, f"Mismatch: added={added_count}, count={current_count}"
        assert current_count == 50, f"Expected 50 connections, got {current_count}"

    @pytest.mark.asyncio
    async def test_concurrent_stats_access(self, manager, reset_global_tracker):
        """Accessing stats while connections change shouldn't crash"""
        # RED: Tests stats consistency during concurrent operations

        async def modify_connections():
            for i in range(20):
                await manager.add_connection(f"game_modify_{i}", MockWebSocket())
                await asyncio.sleep(0.001)

        async def read_stats():
            stats_list = []
            for _ in range(50):
                stats = await manager.get_stats()
                stats_list.append(stats["active_connections"])
                await asyncio.sleep(0.001)
            return stats_list

        # Run modifications and stats reading concurrently
        modify_task = asyncio.create_task(modify_connections())
        stats_task = asyncio.create_task(read_stats())

        await asyncio.gather(modify_task, stats_task)
        stats_history = stats_task.result()

        # Stats should be monotonically increasing (or stable)
        # and never inconsistent
        for stat_value in stats_history:
            assert isinstance(stat_value, int)
            assert stat_value >= 0
            assert stat_value <= 100

    @pytest.mark.asyncio
    async def test_connection_leak_under_concurrent_failures(self, manager, reset_global_tracker):
        """Failed connection additions shouldn't leak resources"""
        # RED: Tests cleanup on concurrent failures

        class FailingWebSocket(MockWebSocket):
            def __init__(self, should_fail=False):
                super().__init__()
                self.should_fail = should_fail

        async def try_add_connection(idx):
            ws = FailingWebSocket(should_fail=(idx % 3 == 0))
            try:
                if ws.should_fail:
                    raise Exception("Simulated connection failure")
                return await manager.add_connection(f"game_{idx}", ws)
            except Exception:
                return False

        # Try to add 30 connections, every 3rd fails
        tasks = [try_add_connection(i) for i in range(30)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successes (should be ~20)
        successes = sum(1 for r in results if r is True)

        # Verify no resource leaks
        stats = await manager.get_stats()
        assert stats["active_connections"] == successes

        # Global tracker should match
        global_count = await global_connection_tracker.get_count()
        assert global_count == successes

    @pytest.mark.asyncio
    async def test_concurrent_connection_retrieval(self, manager, reset_global_tracker):
        """Multiple tasks retrieving same connection should be safe"""
        # RED: Tests safe concurrent reads

        # Add a connection
        game_id = "game_shared"
        ws = MockWebSocket()
        await manager.add_connection(game_id, ws)

        async def get_connection():
            return await manager.get_connection(game_id)

        # Retrieve same connection from 50 concurrent tasks
        tasks = [get_connection() for _ in range(50)]
        results = await asyncio.gather(*tasks)

        # All should get the same connection
        assert all(r is ws for r in results)

    @pytest.mark.asyncio
    async def test_connection_status_update_race(self, manager, reset_global_tracker):
        """Updating connection status should be atomic"""
        # RED: Tests status update atomicity

        game_id = "game_status"
        ws = MockWebSocket()
        await manager.add_connection(game_id, ws)

        async def update_status(new_status):
            # Simulate status update
            async with manager._connection_lock:
                if game_id in manager._connections:
                    manager._connections[game_id].status = new_status
                    return True
            return False

        # Try to update status from multiple tasks
        statuses = [
            ConnectionStatus.CONNECTED,
            ConnectionStatus.DISCONNECTED,
            ConnectionStatus.RECONNECTING,
            ConnectionStatus.FAILED
        ]

        tasks = [update_status(status) for status in statuses * 10]
        results = await asyncio.gather(*tasks)

        # All updates should succeed
        assert all(results)

        # Final status should be one of the valid statuses
        conn_info = manager._connections.get(game_id)
        assert conn_info is not None
        assert conn_info.status in statuses

    @pytest.mark.asyncio
    async def test_cleanup_during_active_operations(self, manager, reset_global_tracker):
        """Cleanup task running shouldn't interfere with active operations"""
        # RED: Tests cleanup/operation coordination

        # Add connections
        for i in range(10):
            ws = MockWebSocket()
            await manager.add_connection(f"game_{i}", ws)

        async def add_new_connections():
            for i in range(10, 20):
                await manager.add_connection(f"game_{i}", MockWebSocket())
                await asyncio.sleep(0.01)

        async def remove_connections():
            for i in range(5):
                await manager.remove_connection(f"game_{i}")
                await asyncio.sleep(0.01)

        # Run additions and removals concurrently
        add_task = asyncio.create_task(add_new_connections())
        remove_task = asyncio.create_task(remove_connections())

        await asyncio.gather(add_task, remove_task)

        # Should have 15 connections (started with 10, added 10, removed 5)
        stats = await manager.get_stats()
        assert stats["active_connections"] == 15


class TestGlobalConnectionTracker:
    """Test the global connection tracker specifically"""

    @pytest_asyncio.fixture
    async def reset_tracker(self):
        """Reset tracker before each test"""
        async with global_connection_tracker._lock:
            global_connection_tracker._global_count = 0
        yield
        async with global_connection_tracker._lock:
            global_connection_tracker._global_count = 0

    @pytest.mark.asyncio
    async def test_tracker_is_singleton(self):
        """GlobalConnectionTracker should be a singleton"""
        tracker1 = GlobalConnectionTracker()
        tracker2 = GlobalConnectionTracker()

        assert tracker1 is tracker2

    @pytest.mark.asyncio
    async def test_tracker_concurrent_additions(self, reset_tracker):
        """Tracker should handle concurrent additions safely"""
        tracker = GlobalConnectionTracker()

        async def add_multiple():
            count = 0
            for _ in range(10):
                if await tracker.add_connection():
                    count += 1
            return count

        # Run 10 tasks, each trying to add 10 connections
        tasks = [add_multiple() for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # Total added should match tracker count
        total_added = sum(results)
        current_count = await tracker.get_count()

        assert total_added == current_count
        assert current_count <= 100  # Should not exceed limit

    @pytest.mark.asyncio
    async def test_tracker_concurrent_add_remove(self, reset_tracker):
        """Tracker should handle concurrent add/remove safely"""
        tracker = GlobalConnectionTracker()

        # Add initial connections
        for _ in range(50):
            await tracker.add_connection()

        async def add_task():
            for _ in range(25):
                await tracker.add_connection()
                await asyncio.sleep(0.001)

        async def remove_task():
            for _ in range(25):
                await tracker.remove_connection()
                await asyncio.sleep(0.001)

        # Run concurrently
        await asyncio.gather(add_task(), remove_task())

        # Should still have 50 connections
        count = await tracker.get_count()
        assert count == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
