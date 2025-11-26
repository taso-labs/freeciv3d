#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for RequestManager - TTL-based cleanup to prevent memory leaks
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from request_manager import RequestManager, PendingRequest


class TestRequestManager:
    """Test RequestManager functionality"""

    @pytest.mark.asyncio
    async def test_request_manager_initialization(self):
        """Test RequestManager initializes properly"""
        manager = RequestManager(default_timeout=10.0, cleanup_interval=1.0)

        assert manager.default_timeout == 10.0
        assert manager.cleanup_interval == 1.0
        assert len(manager.pending_requests) == 0

    @pytest.mark.asyncio
    async def test_create_and_resolve_request(self):
        """Test creating and resolving a request"""
        manager = RequestManager()
        await manager.start()

        try:
            # Create request
            correlation_id, future = await manager.create_request(timeout=5.0)

            assert correlation_id is not None
            assert not future.done()
            assert correlation_id in manager.pending_requests

            # Resolve request
            test_response = {"success": True, "data": "test"}
            success = await manager.resolve_request(correlation_id, test_response)

            assert success is True
            assert future.done()
            assert future.result() == test_response
            assert correlation_id not in manager.pending_requests

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_request_timeout_cleanup(self):
        """Test that expired requests are cleaned up"""
        manager = RequestManager(default_timeout=1.0, cleanup_interval=0.5)
        await manager.start()

        try:
            # Create request
            correlation_id, future = await manager.create_request(timeout=0.1)

            assert correlation_id in manager.pending_requests

            # Wait for cleanup
            await asyncio.sleep(1.5)

            # Request should be cleaned up
            assert correlation_id not in manager.pending_requests
            assert future.done()

            # Should raise TimeoutError
            with pytest.raises(asyncio.TimeoutError):
                future.result()

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_send_request_and_wait_success(self):
        """Test successful request/response cycle"""
        manager = RequestManager()
        await manager.start()

        try:
            # Mock send callback
            async def mock_send(message):
                # Simulate async send
                await asyncio.sleep(0.1)
                # Simulate response
                correlation_id = message["correlation_id"]
                response = {"success": True, "correlation_id": correlation_id}
                await manager.resolve_request(correlation_id, response)

            message = {"type": "test_request"}
            response = await manager.send_request_and_wait(
                mock_send, message, timeout=2.0
            )

            assert response["success"] is True
            assert "correlation_id" in response

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_send_request_and_wait_timeout(self):
        """Test request timeout handling"""
        manager = RequestManager()
        await manager.start()

        try:
            # Mock send callback that never responds
            async def mock_send_no_response(message):
                await asyncio.sleep(0.1)
                # Don't resolve the request

            message = {"type": "test_request"}

            with pytest.raises(asyncio.TimeoutError):
                await manager.send_request_and_wait(
                    mock_send_no_response, message, timeout=0.2
                )

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_cancel_request(self):
        """Test request cancellation"""
        manager = RequestManager()
        await manager.start()

        try:
            correlation_id, future = await manager.create_request()

            assert not future.done()

            # Cancel request
            success = await manager.cancel_request(correlation_id, "test cancellation")

            assert success is True
            assert future.cancelled()
            assert correlation_id not in manager.pending_requests

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        """Test statistics tracking"""
        manager = RequestManager()
        await manager.start()

        try:
            # Create and resolve some requests
            correlation_id1, future1 = await manager.create_request()
            correlation_id2, future2 = await manager.create_request()

            await manager.resolve_request(correlation_id1, {"success": True})
            await manager.cancel_request(correlation_id2, "test")

            stats = await manager.get_stats()

            assert stats["total_requests"] == 2
            assert stats["completed_requests"] == 1
            assert stats["pending_requests"] == 0

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """Test handling multiple concurrent requests"""
        manager = RequestManager()
        await manager.start()

        try:
            # Create multiple requests
            requests = []
            for i in range(10):
                correlation_id, future = await manager.create_request()
                requests.append((correlation_id, future))

            # Resolve all requests
            for i, (correlation_id, future) in enumerate(requests):
                await manager.resolve_request(correlation_id, {"id": i})

            # Check all were resolved
            for i, (correlation_id, future) in enumerate(requests):
                assert future.done()
                assert future.result()["id"] == i

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_memory_leak_prevention(self):
        """Test that memory usage doesn't grow unbounded"""
        manager = RequestManager(default_timeout=0.1, cleanup_interval=0.1)
        await manager.start()

        try:
            # Create many requests and let them timeout
            for i in range(100):
                await manager.create_request(timeout=0.05)
                if i % 20 == 0:
                    await asyncio.sleep(0.2)  # Allow cleanup to run

            # Wait for cleanup
            await asyncio.sleep(0.5)

            # Should have cleaned up most/all requests
            pending_count = await manager.get_request_count()
            assert pending_count < 10  # Some tolerance for timing

        finally:
            await manager.stop()


if __name__ == "__main__":
    pytest.main([__file__])
