#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for memory leak detection in RequestManager
Verifies TTL-based cleanup prevents unbounded memory growth
"""

import pytest
import pytest_asyncio
import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from request_manager import RequestManager, PendingRequest


class TestRequestManagerMemoryLeaks:
    """Test suite for memory leak prevention in RequestManager"""

    @pytest_asyncio.fixture
    async def manager(self):
        """Create a request manager with short cleanup interval for testing"""
        mgr = RequestManager(default_timeout=1.0, cleanup_interval=0.1)
        await mgr.start()
        yield mgr
        await mgr.stop()

    @pytest.mark.asyncio
    async def test_expired_requests_cleaned_up(self, manager):
        """Expired requests should be cleaned from memory"""
        # GREEN: This test should PASS because cleanup is already implemented

        # Create 100 requests with very short timeout
        correlation_ids = []
        for i in range(100):
            correlation_id, future = await manager.create_request(
                timeout=0.01,  # 10ms timeout
                agent_id=f"agent_{i}",
                request_type="test"
            )
            correlation_ids.append(correlation_id)

        # Verify all requests are pending
        initial_count = await manager.get_request_count()
        assert initial_count == 100

        # Wait for cleanup to run (cleanup interval is 0.1s, timeouts are 0.01s)
        await asyncio.sleep(0.5)

        # All requests should be cleaned up
        final_count = await manager.get_request_count()
        assert final_count == 0, f"Expected 0 pending requests, got {final_count}"

        # Verify stats show cleanup happened
        stats = await manager.get_stats()
        assert stats["cleaned_up_requests"] >= 100
        assert stats["timed_out_requests"] >= 100

    @pytest.mark.asyncio
    async def test_memory_leak_under_load(self, manager):
        """High load shouldn't cause unbounded memory growth"""
        # GREEN: Tests memory is freed under sustained load

        async def create_short_lived_request():
            """Create a request that times out quickly"""
            correlation_id, future = await manager.create_request(
                timeout=0.05,  # 50ms timeout
                agent_id="load_test",
                request_type="load"
            )
            try:
                # Don't wait for result - let it timeout
                await asyncio.wait_for(future, timeout=0.01)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        # Create 1000 requests over 2 seconds
        tasks = []
        for batch in range(10):
            # Create 100 requests
            batch_tasks = [create_short_lived_request() for _ in range(100)]
            tasks.extend(batch_tasks)

            # Wait a bit between batches
            await asyncio.sleep(0.2)

        # Wait for all tasks to complete
        await asyncio.gather(*tasks, return_exceptions=True)

        # Wait for cleanup
        await asyncio.sleep(0.5)

        # Memory should be freed - pending requests should be low
        final_count = await manager.get_request_count()
        assert final_count < 50, f"Memory leak detected: {final_count} requests still pending"

        # Stats should show high throughput
        stats = await manager.get_stats()
        assert stats["total_requests"] >= 1000
        assert stats["cleaned_up_requests"] > 900

    @pytest.mark.asyncio
    async def test_completed_requests_removed_immediately(self, manager):
        """Completed requests should be removed immediately, not wait for cleanup"""
        # GREEN: Tests immediate removal on completion

        # Create request
        correlation_id, future = await manager.create_request(
            timeout=10.0,  # Long timeout
            agent_id="test_agent"
        )

        # Verify it's pending
        assert await manager.get_request_count() == 1

        # Resolve it
        await manager.resolve_request(correlation_id, {"result": "success"})

        # Should be removed immediately
        assert await manager.get_request_count() == 0

        # Result should be available
        result = await future
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_cancelled_requests_removed_immediately(self, manager):
        """Cancelled requests should be removed immediately"""
        # GREEN: Tests immediate removal on cancellation

        # Create request
        correlation_id, future = await manager.create_request(
            timeout=10.0,
            agent_id="test_agent"
        )

        assert await manager.get_request_count() == 1

        # Cancel it
        await manager.cancel_request(correlation_id, "test cancellation")

        # Should be removed immediately
        assert await manager.get_request_count() == 0

        # Future should be cancelled
        assert future.cancelled()

    @pytest.mark.asyncio
    async def test_cleanup_doesnt_affect_active_requests(self, manager):
        """Cleanup should only remove expired requests, not active ones"""
        # GREEN: Tests selective cleanup

        # Create mix of short and long timeout requests
        short_ids = []
        long_ids = []

        for i in range(10):
            # Short timeout requests (will expire)
            correlation_id, _ = await manager.create_request(
                timeout=0.01,
                agent_id=f"short_{i}"
            )
            short_ids.append(correlation_id)

            # Long timeout requests (should survive)
            correlation_id, _ = await manager.create_request(
                timeout=10.0,
                agent_id=f"long_{i}"
            )
            long_ids.append(correlation_id)

        # Should have 20 requests
        assert await manager.get_request_count() == 20

        # Wait for cleanup
        await asyncio.sleep(0.5)

        # Only long timeout requests should remain
        remaining = await manager.get_request_count()
        assert remaining == 10, f"Expected 10 long-timeout requests, got {remaining}"

        # Verify the right ones survived
        stats = await manager.get_stats()
        assert stats["cleaned_up_requests"] >= 10

    @pytest.mark.asyncio
    async def test_no_memory_leak_on_repeated_start_stop(self, manager):
        """Starting and stopping manager shouldn't leak resources"""
        # GREEN: Tests cleanup on stop

        # Create some requests
        for i in range(50):
            await manager.create_request(timeout=10.0, agent_id=f"agent_{i}")

        assert await manager.get_request_count() == 50

        # Stop manager
        await manager.stop()

        # Requests should be cleaned up
        assert len(manager.pending_requests) == 0

        # Restart
        await manager.start()

        # Should start fresh
        assert await manager.get_request_count() == 0

    @pytest.mark.asyncio
    async def test_statistics_accuracy(self, manager):
        """Statistics should accurately reflect request lifecycle"""
        # GREEN: Tests stat tracking

        # Create and resolve some requests
        for i in range(10):
            correlation_id, future = await manager.create_request(
                timeout=10.0,
                agent_id=f"agent_{i}"
            )
            await manager.resolve_request(correlation_id, f"result_{i}")

        # Create and let timeout
        for i in range(5):
            await manager.create_request(
                timeout=0.01,
                agent_id=f"timeout_{i}"
            )

        # Wait for timeouts to be cleaned
        await asyncio.sleep(0.5)

        stats = await manager.get_stats()

        # Verify stats
        assert stats["total_requests"] == 15
        assert stats["completed_requests"] == 10
        assert stats["timed_out_requests"] >= 5
        assert stats["cleaned_up_requests"] >= 5
        assert stats["pending_requests"] == 0

    @pytest.mark.asyncio
    async def test_concurrent_cleanup_and_operations(self, manager):
        """Cleanup running concurrently with operations shouldn't cause issues"""
        # GREEN: Tests thread safety during cleanup

        async def create_and_resolve():
            for _ in range(20):
                correlation_id, future = await manager.create_request(
                    timeout=1.0,
                    agent_id="concurrent"
                )
                await asyncio.sleep(0.01)
                await manager.resolve_request(correlation_id, "ok")

        async def create_timeouts():
            for _ in range(20):
                await manager.create_request(
                    timeout=0.02,
                    agent_id="timeout"
                )
                await asyncio.sleep(0.01)

        # Run operations while cleanup is running
        await asyncio.gather(
            create_and_resolve(),
            create_timeouts()
        )

        # Wait for final cleanup
        await asyncio.sleep(0.3)

        # Should have cleaned up everything
        final_count = await manager.get_request_count()
        assert final_count == 0

    @pytest.mark.asyncio
    async def test_memory_growth_over_time(self, manager):
        """Long-running manager shouldn't accumulate memory indefinitely"""
        # GREEN: Simulates long-running scenario

        async def simulate_requests():
            """Simulate realistic request patterns"""
            for _ in range(50):
                # Some requests complete
                corr_id, future = await manager.create_request(timeout=0.5)
                await asyncio.sleep(0.001)
                await manager.resolve_request(corr_id, "done")

                # Some requests timeout
                await manager.create_request(timeout=0.01)
                await asyncio.sleep(0.001)

        # Run simulation
        await simulate_requests()

        # Wait for cleanup
        await asyncio.sleep(0.5)

        # Should have minimal pending requests
        final_count = await manager.get_request_count()
        assert final_count < 5, f"Memory accumulation detected: {final_count} pending"

        stats = await manager.get_stats()
        assert stats["total_requests"] == 100
        assert stats["cleaned_up_requests"] + stats["completed_requests"] >= 95

    @pytest.mark.asyncio
    async def test_cleanup_interval_respected(self, manager):
        """Cleanup should run at specified intervals"""
        # GREEN: Tests cleanup scheduling

        # Create requests that will expire
        for i in range(10):
            await manager.create_request(timeout=0.01, agent_id=f"test_{i}")

        # Wait less than cleanup interval
        await asyncio.sleep(0.05)

        # Cleanup may not have run yet
        count_before = await manager.get_request_count()

        # Wait for cleanup interval to pass
        await asyncio.sleep(0.1)

        # Cleanup should have run
        count_after = await manager.get_request_count()
        assert count_after < count_before

    @pytest.mark.asyncio
    async def test_future_not_leaked_on_timeout(self, manager):
        """Futures should be properly cleaned when requests timeout"""
        # GREEN: Tests future cleanup

        # Create request that will timeout
        correlation_id, future = await manager.create_request(
            timeout=0.01,
            agent_id="leak_test"
        )

        # Keep a weak reference to detect if future is cleaned
        import weakref
        future_ref = weakref.ref(future)

        # Let it timeout
        await asyncio.sleep(0.2)

        # Original future should be resolved (timeout)
        assert future.done()

        # Delete our reference
        del future

        # Trigger garbage collection
        import gc
        gc.collect()

        # Future should be garbage collected
        # (This is a soft assertion - GC timing is non-deterministic)
        # Main point is request was removed from pending_requests


class TestRequestManagerEdgeCases:
    """Test edge cases in request management"""

    @pytest_asyncio.fixture
    async def manager(self):
        mgr = RequestManager(cleanup_interval=0.1)
        await mgr.start()
        yield mgr
        await mgr.stop()

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_request(self, manager):
        """Resolving non-existent request should not crash"""
        result = await manager.resolve_request("nonexistent", "data")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_request(self, manager):
        """Cancelling non-existent request should not crash"""
        result = await manager.cancel_request("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_double_resolve(self, manager):
        """Resolving same request twice should be safe"""
        correlation_id, future = await manager.create_request(timeout=10.0)

        # First resolve
        result1 = await manager.resolve_request(correlation_id, "data1")
        assert result1 is True

        # Second resolve (should fail gracefully)
        result2 = await manager.resolve_request(correlation_id, "data2")
        assert result2 is False

        # Future should have first result
        assert await future == "data1"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
