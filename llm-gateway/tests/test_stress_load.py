#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Stress tests for LLM Gateway under high concurrent load
Tests system behavior under extreme conditions to identify bottlenecks
"""

import asyncio
import json
import logging
import time
import pytest
import random
import string
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Import system components
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from request_manager import RequestManager
from connection_state_manager import ConnectionStateManager, GlobalConnectionTracker
from utils.rate_limiter import ComprehensiveRateLimiter, RateLimitType, RateLimitConfig
from utils.constants import (
    GLOBAL_CONNECTION_LIMIT, MAX_CONNECTIONS_PER_AGENT,
    MAX_MESSAGE_SIZE_BYTES, DEFAULT_REQUEST_TIMEOUT
)


class MockWebSocket:
    """Mock WebSocket for testing"""

    def __init__(self, fail_rate: float = 0.0):
        self.closed = False
        self.fail_rate = fail_rate
        self.messages_sent = []
        self.messages_received = []

    async def send_text(self, message: str):
        if random.random() < self.fail_rate:
            raise ConnectionError("Mock connection failure")
        self.messages_sent.append(message)

    async def receive_text(self) -> str:
        if random.random() < self.fail_rate:
            raise ConnectionError("Mock connection failure")
        if self.messages_received:
            return self.messages_received.pop(0)
        return '{"type": "ping"}'

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = True

    async def ping(self):
        if random.random() < self.fail_rate:
            raise ConnectionError("Mock ping failure")
        return True


class StressTestMetrics:
    """Collect and analyze stress test metrics"""

    def __init__(self):
        self.start_time = time.time()
        self.operation_counts = {}
        self.error_counts = {}
        self.latencies = []
        self.memory_usage = []
        self.concurrent_operations = 0
        self.max_concurrent = 0

    def record_operation(self, operation: str, latency: float = None, success: bool = True):
        self.operation_counts[operation] = self.operation_counts.get(operation, 0) + 1
        if not success:
            self.error_counts[operation] = self.error_counts.get(operation, 0) + 1
        if latency is not None:
            self.latencies.append(latency)

    def start_operation(self):
        self.concurrent_operations += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent_operations)

    def end_operation(self):
        self.concurrent_operations = max(0, self.concurrent_operations - 1)

    def get_summary(self) -> Dict[str, Any]:
        total_time = time.time() - self.start_time
        total_ops = sum(self.operation_counts.values())
        total_errors = sum(self.error_counts.values())

        return {
            "total_time": total_time,
            "total_operations": total_ops,
            "operations_per_second": total_ops / total_time if total_time > 0 else 0,
            "total_errors": total_errors,
            "error_rate": total_errors / total_ops if total_ops > 0 else 0,
            "max_concurrent_operations": self.max_concurrent,
            "average_latency": sum(self.latencies) / len(self.latencies) if self.latencies else 0,
            "operation_breakdown": self.operation_counts,
            "error_breakdown": self.error_counts
        }


@pytest.fixture
def stress_metrics():
    """Fixture providing stress test metrics collector"""
    return StressTestMetrics()


@pytest.fixture
def mock_websockets():
    """Fixture providing mock WebSockets with varying failure rates"""
    return {
        "reliable": [MockWebSocket(fail_rate=0.0) for _ in range(100)],
        "unreliable": [MockWebSocket(fail_rate=0.1) for _ in range(50)],
        "flaky": [MockWebSocket(fail_rate=0.3) for _ in range(25)]
    }


class TestRequestManagerStress:
    """Stress tests for RequestManager under high load"""

    @pytest.mark.asyncio
    async def test_concurrent_request_creation(self, stress_metrics):
        """Test creating many requests concurrently"""
        manager = RequestManager(default_timeout=5.0, cleanup_interval=1.0)
        await manager.start()

        try:
            # Create 1000 concurrent requests
            num_requests = 1000

            async def create_request(i):
                stress_metrics.start_operation()
                start_time = time.time()
                try:
                    correlation_id, future = await manager.create_request(
                        timeout=10.0,
                        agent_id=f"agent_{i % 10}",
                        request_type="test"
                    )
                    stress_metrics.record_operation("request_creation", time.time() - start_time, True)
                    return correlation_id, future
                except Exception as e:
                    stress_metrics.record_operation("request_creation", time.time() - start_time, False)
                    raise
                finally:
                    stress_metrics.end_operation()

            # Execute all requests concurrently
            start_time = time.time()
            tasks = [create_request(i) for i in range(num_requests)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Verify results
            successful_requests = [r for r in results if not isinstance(r, Exception)]
            failed_requests = [r for r in results if isinstance(r, Exception)]

            print(f"Created {len(successful_requests)} requests successfully")
            print(f"Failed to create {len(failed_requests)} requests")

            # Check request manager state
            pending_count = await manager.get_request_count()
            stats = await manager.get_stats()

            assert len(successful_requests) >= num_requests * 0.95  # 95% success rate
            assert pending_count == len(successful_requests)
            assert stats["total_requests"] == num_requests

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_request_resolution_under_load(self, stress_metrics):
        """Test resolving many requests under high load"""
        manager = RequestManager(default_timeout=10.0, cleanup_interval=2.0)
        await manager.start()

        try:
            num_requests = 500
            requests = []

            # Create many requests
            for i in range(num_requests):
                correlation_id, future = await manager.create_request(
                    agent_id=f"agent_{i % 20}",
                    request_type="load_test"
                )
                requests.append((correlation_id, future))

            # Resolve requests concurrently
            async def resolve_request(correlation_id, response_data):
                stress_metrics.start_operation()
                start_time = time.time()
                try:
                    success = await manager.resolve_request(correlation_id, response_data)
                    stress_metrics.record_operation("request_resolution", time.time() - start_time, success)
                    return success
                except Exception as e:
                    stress_metrics.record_operation("request_resolution", time.time() - start_time, False)
                    return False
                finally:
                    stress_metrics.end_operation()

            # Resolve all requests concurrently
            resolution_tasks = [
                resolve_request(correlation_id, f"response_{i}")
                for i, (correlation_id, _) in enumerate(requests)
            ]

            resolution_results = await asyncio.gather(*resolution_tasks)
            successful_resolutions = sum(resolution_results)

            # Wait for futures to complete
            future_results = await asyncio.gather(
                *[future for _, future in requests],
                return_exceptions=True
            )

            successful_futures = sum(1 for r in future_results if not isinstance(r, Exception))

            print(f"Resolved {successful_resolutions} requests successfully")
            print(f"Completed {successful_futures} futures successfully")

            assert successful_resolutions >= num_requests * 0.98  # 98% success rate
            assert successful_futures >= num_requests * 0.98

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_memory_cleanup_under_stress(self, stress_metrics):
        """Test memory cleanup behavior under continuous load"""
        manager = RequestManager(default_timeout=2.0, cleanup_interval=0.5)
        await manager.start()

        try:
            # Continuously create and timeout requests
            duration = 10  # seconds
            start_time = time.time()

            while time.time() - start_time < duration:
                # Create batch of requests
                batch_size = 50
                for i in range(batch_size):
                    correlation_id, future = await manager.create_request(
                        timeout=1.0,  # Short timeout
                        agent_id=f"stress_agent_{i % 5}"
                    )
                    stress_metrics.record_operation("request_creation")

                # Let some requests timeout
                await asyncio.sleep(0.1)

                # Check memory usage
                stats = await manager.get_stats()
                pending_count = await manager.get_request_count()
                stress_metrics.memory_usage.append(pending_count)

                # Ensure memory doesn't grow unbounded
                assert pending_count < 200, f"Too many pending requests: {pending_count}"

            # Wait for cleanup
            await asyncio.sleep(3.0)

            final_pending = await manager.get_request_count()
            final_stats = await manager.get_stats()

            print(f"Final pending requests: {final_pending}")
            print(f"Cleanup efficiency: {final_stats['cleaned_up_requests']} cleaned up")

            # Most requests should be cleaned up
            assert final_pending < 50
            assert final_stats["cleaned_up_requests"] > 0

        finally:
            await manager.stop()


class TestConnectionStateManagerStress:
    """Stress tests for ConnectionStateManager under high load"""

    @pytest.mark.asyncio
    async def test_global_connection_limit_enforcement(self, stress_metrics, mock_websockets):
        """Test global connection limit under concurrent load"""
        manager = ConnectionStateManager(max_connections=100)
        await manager.start()

        # Reset global tracker
        global_tracker = GlobalConnectionTracker()
        global_tracker._global_count = 0

        try:
            # Try to add more connections than global limit
            num_attempts = GLOBAL_CONNECTION_LIMIT + 50

            async def add_connection(game_id):
                stress_metrics.start_operation()
                start_time = time.time()
                try:
                    websocket = MockWebSocket()
                    success = await manager.add_connection(game_id, websocket)
                    stress_metrics.record_operation("connection_add", time.time() - start_time, success)
                    return success
                except Exception as e:
                    stress_metrics.record_operation("connection_add", time.time() - start_time, False)
                    return False
                finally:
                    stress_metrics.end_operation()

            # Execute concurrent connection attempts
            tasks = [add_connection(f"game_{i}") for i in range(num_attempts)]
            results = await asyncio.gather(*tasks)

            successful_connections = sum(results)
            failed_connections = num_attempts - successful_connections

            print(f"Successful connections: {successful_connections}")
            print(f"Failed connections: {failed_connections}")

            # Should not exceed global limit
            assert successful_connections <= GLOBAL_CONNECTION_LIMIT
            assert failed_connections > 0  # Some should be rejected

            # Check global count
            global_count = await global_tracker.get_count()
            assert global_count <= GLOBAL_CONNECTION_LIMIT

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(self, stress_metrics, mock_websockets):
        """Test health check system under concurrent load"""
        manager = ConnectionStateManager(max_connections=50, health_check_interval=0.5)
        await manager.start()

        try:
            # Add many connections with varying reliability
            connections_added = 0

            # Add reliable connections
            for i, ws in enumerate(mock_websockets["reliable"][:30]):
                if await manager.add_connection(f"reliable_game_{i}", ws):
                    connections_added += 1

            # Add unreliable connections
            for i, ws in enumerate(mock_websockets["unreliable"][:15]):
                if await manager.add_connection(f"unreliable_game_{i}", ws):
                    connections_added += 1

            # Add flaky connections
            for i, ws in enumerate(mock_websockets["flaky"][:10]):
                if await manager.add_connection(f"flaky_game_{i}", ws):
                    connections_added += 1

            print(f"Added {connections_added} connections")

            # Let health checks run for a while
            await asyncio.sleep(3.0)

            # Check system state
            all_connections = await manager.get_all_connections()
            stats = await manager.get_stats()

            print(f"Health check failures: {stats['health_check_failures']}")
            print(f"Active connections: {stats['active_connections']}")

            # Some health checks should have failed for unreliable connections
            assert stats["health_check_failures"] > 0

            # System should still be responsive
            assert len(all_connections) > 0

        finally:
            await manager.stop()


class TestRateLimiterStress:
    """Stress tests for ComprehensiveRateLimiter under high load"""

    @pytest.mark.asyncio
    async def test_concurrent_rate_limiting(self, stress_metrics):
        """Test rate limiter under concurrent load from many agents"""
        limiter = ComprehensiveRateLimiter()

        # Configure aggressive rate limits
        limiter.add_rate_limit(
            RateLimitType.REQUESTS_PER_MINUTE,
            RateLimitConfig(
                limit_type=RateLimitType.REQUESTS_PER_MINUTE,
                limit_value=100,
                window_seconds=60
            )
        )

        limiter.add_rate_limit(
            RateLimitType.REQUESTS_PER_SECOND,
            RateLimitConfig(
                limit_type=RateLimitType.REQUESTS_PER_SECOND,
                limit_value=10,
                window_seconds=1
            )
        )

        num_agents = 50
        requests_per_agent = 20

        async def agent_requests(agent_id: str):
            allowed_count = 0
            blocked_count = 0

            for i in range(requests_per_agent):
                stress_metrics.start_operation()
                start_time = time.time()

                try:
                    message = f"Test message {i} from {agent_id}"
                    is_allowed, reason = await limiter.check_rate_limits(
                        agent_id,
                        message_size=len(message.encode('utf-8')),
                        message_content=message
                    )

                    if is_allowed:
                        allowed_count += 1
                        stress_metrics.record_operation("rate_limit_allowed", time.time() - start_time, True)
                    else:
                        blocked_count += 1
                        stress_metrics.record_operation("rate_limit_blocked", time.time() - start_time, True)

                except Exception as e:
                    stress_metrics.record_operation("rate_limit_error", time.time() - start_time, False)
                finally:
                    stress_metrics.end_operation()

                # Small delay to avoid overwhelming
                await asyncio.sleep(0.01)

            return allowed_count, blocked_count

        # Execute concurrent requests from all agents
        tasks = [agent_requests(f"stress_agent_{i}") for i in range(num_agents)]
        results = await asyncio.gather(*tasks)

        total_allowed = sum(allowed for allowed, _ in results)
        total_blocked = sum(blocked for _, blocked in results)
        total_requests = total_allowed + total_blocked

        print(f"Total requests: {total_requests}")
        print(f"Allowed: {total_allowed}")
        print(f"Blocked: {total_blocked}")
        print(f"Block rate: {total_blocked / total_requests * 100:.1f}%")

        # Rate limiter should have blocked some requests
        assert total_blocked > 0
        assert total_allowed < total_requests

        # Get final statistics
        final_stats = await limiter.get_stats()
        print(f"Rate limiter stats: {final_stats}")

    @pytest.mark.asyncio
    async def test_connection_attempt_rate_limiting(self, stress_metrics):
        """Test connection attempt rate limiting under rapid connection attempts"""
        limiter = ComprehensiveRateLimiter()

        # Simulate rapid connection attempts from single agent
        agent_id = "rapid_connector"
        num_attempts = 50

        async def connection_attempt():
            stress_metrics.start_operation()
            start_time = time.time()

            try:
                allowed = await limiter.track_connection(agent_id)
                stress_metrics.record_operation("connection_attempt", time.time() - start_time, allowed)
                return allowed
            except Exception as e:
                stress_metrics.record_operation("connection_attempt", time.time() - start_time, False)
                return False
            finally:
                stress_metrics.end_operation()

        # Execute rapid connection attempts
        tasks = [connection_attempt() for _ in range(num_attempts)]
        results = await asyncio.gather(*tasks)

        allowed_connections = sum(results)
        blocked_connections = num_attempts - allowed_connections

        print(f"Allowed connections: {allowed_connections}")
        print(f"Blocked connections: {blocked_connections}")

        # Should block excessive attempts
        assert blocked_connections > 0
        assert allowed_connections < num_attempts


class TestIntegratedSystemStress:
    """Integration stress tests for the complete system"""

    @pytest.mark.asyncio
    async def test_full_system_under_load(self, stress_metrics):
        """Test complete system under realistic high load"""
        # Initialize all components
        request_manager = RequestManager(default_timeout=30.0)
        connection_manager = ConnectionStateManager(max_connections=100)
        rate_limiter = ComprehensiveRateLimiter()

        await request_manager.start()
        await connection_manager.start()

        try:
            # Simulate realistic mixed workload
            num_agents = 25
            duration = 15  # seconds

            async def agent_workload(agent_id: str):
                """Simulate realistic agent behavior"""
                operations = {
                    "connections": 0,
                    "requests": 0,
                    "rate_limited": 0,
                    "errors": 0
                }

                start_time = time.time()

                while time.time() - start_time < duration:
                    try:
                        # Try to establish connection
                        if await rate_limiter.track_connection(agent_id):
                            operations["connections"] += 1

                            # Simulate WebSocket connection
                            websocket = MockWebSocket(fail_rate=0.05)
                            if await connection_manager.add_connection(f"game_{agent_id}", websocket):

                                # Send some requests
                                for i in range(random.randint(1, 5)):
                                    message = f"Request {i} from {agent_id}"

                                    # Check rate limits
                                    is_allowed, _ = await rate_limiter.check_rate_limits(
                                        agent_id,
                                        message_size=len(message.encode('utf-8'))
                                    )

                                    if is_allowed:
                                        # Create and resolve request
                                        correlation_id, future = await request_manager.create_request(
                                            agent_id=agent_id,
                                            request_type="agent_request"
                                        )

                                        # Simulate async response
                                        await asyncio.sleep(random.uniform(0.1, 0.5))
                                        await request_manager.resolve_request(
                                            correlation_id,
                                            {"status": "success", "data": f"response_{i}"}
                                        )
                                        operations["requests"] += 1
                                    else:
                                        operations["rate_limited"] += 1

                                # Hold connection briefly
                                await asyncio.sleep(random.uniform(0.5, 2.0))

                                # Release connection
                                await connection_manager.remove_connection(f"game_{agent_id}")

                            # Release connection tracking
                            await rate_limiter.release_connection(agent_id)

                        # Wait before next attempt
                        await asyncio.sleep(random.uniform(0.1, 1.0))

                    except Exception as e:
                        operations["errors"] += 1
                        await asyncio.sleep(0.1)  # Brief pause on error

                return operations

            # Execute workload for all agents
            print(f"Starting stress test with {num_agents} agents for {duration} seconds...")

            agent_tasks = [agent_workload(f"stress_agent_{i}") for i in range(num_agents)]
            agent_results = await asyncio.gather(*agent_tasks, return_exceptions=True)

            # Collect results
            total_operations = {
                "connections": 0,
                "requests": 0,
                "rate_limited": 0,
                "errors": 0
            }

            successful_agents = 0
            for result in agent_results:
                if isinstance(result, dict):
                    successful_agents += 1
                    for key in total_operations:
                        total_operations[key] += result[key]

            # Get system statistics
            request_stats = await request_manager.get_stats()
            connection_stats = await connection_manager.get_stats()
            rate_limiter_stats = await rate_limiter.get_stats()

            # Print comprehensive results
            print(f"\n=== STRESS TEST RESULTS ===")
            print(f"Duration: {duration} seconds")
            print(f"Agents: {num_agents} ({successful_agents} successful)")
            print(f"Total connections: {total_operations['connections']}")
            print(f"Total requests: {total_operations['requests']}")
            print(f"Rate limited: {total_operations['rate_limited']}")
            print(f"Errors: {total_operations['errors']}")
            print(f"Requests/second: {total_operations['requests'] / duration:.1f}")

            print(f"\nRequest Manager Stats:")
            for key, value in request_stats.items():
                print(f"  {key}: {value}")

            print(f"\nConnection Manager Stats:")
            for key, value in connection_stats.items():
                print(f"  {key}: {value}")

            print(f"\nRate Limiter Stats:")
            for key, value in rate_limiter_stats.items():
                print(f"  {key}: {value}")

            # Verify system stability
            assert successful_agents >= num_agents * 0.8  # 80% of agents should complete
            assert total_operations["requests"] > 0  # Some requests should succeed
            assert total_operations["errors"] < total_operations["requests"]  # More success than errors

        finally:
            await request_manager.stop()
            await connection_manager.stop()


if __name__ == "__main__":
    # Run stress tests directly
    import pytest
    pytest.main([__file__, "-v", "-s"])