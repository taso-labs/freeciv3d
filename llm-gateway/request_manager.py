#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Request Manager for LLM API Gateway
Handles request correlation with TTL-based cleanup to prevent memory leaks
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

try:
    from .utils.constants import DEFAULT_REQUEST_TIMEOUT, CLEANUP_INTERVAL
except ImportError:
    from utils.constants import DEFAULT_REQUEST_TIMEOUT, CLEANUP_INTERVAL

logger = logging.getLogger("llm-gateway")


@dataclass
class PendingRequest:
    """Represents a pending request waiting for response"""
    future: asyncio.Future
    correlation_id: str
    created_at: datetime
    timeout: float
    agent_id: Optional[str] = None
    request_type: Optional[str] = None


class RequestManager:
    """
    Manages request-response correlation with automatic TTL cleanup
    Prevents memory leaks by cleaning up expired futures
    """

    def __init__(self, default_timeout: float = DEFAULT_REQUEST_TIMEOUT, cleanup_interval: float = CLEANUP_INTERVAL):
        self.pending_requests: Dict[str, PendingRequest] = {}
        self.default_timeout = default_timeout
        self.cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._running = False

        # Statistics for monitoring
        self._stats = {
            "total_requests": 0,
            "completed_requests": 0,
            "timed_out_requests": 0,
            "cleaned_up_requests": 0
        }

    async def start(self):
        """Start the request manager and cleanup task"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"RequestManager started with {self.default_timeout}s timeout")

    async def stop(self):
        """Stop the request manager and cleanup task"""
        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        # Cancel all pending requests
        async with self._lock:
            for request in self.pending_requests.values():
                if not request.future.done():
                    request.future.cancel()
            self.pending_requests.clear()

        logger.info("RequestManager stopped")

    async def create_request(
        self,
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None,
        request_type: Optional[str] = None
    ) -> tuple[str, asyncio.Future]:
        """
        Create a new pending request

        Returns:
            tuple: (correlation_id, future)
        """
        correlation_id = str(uuid.uuid4())
        future = asyncio.Future()

        request = PendingRequest(
            future=future,
            correlation_id=correlation_id,
            created_at=datetime.now(),
            timeout=timeout or self.default_timeout,
            agent_id=agent_id,
            request_type=request_type
        )

        async with self._lock:
            self.pending_requests[correlation_id] = request
            self._stats["total_requests"] += 1

        logger.debug(f"Created request {correlation_id} with {request.timeout}s timeout")
        return correlation_id, future

    async def resolve_request(self, correlation_id: str, response: Any) -> bool:
        """
        Resolve a pending request with response data

        Returns:
            bool: True if request was found and resolved, False otherwise
        """
        async with self._lock:
            request = self.pending_requests.pop(correlation_id, None)

        if request and not request.future.done():
            request.future.set_result(response)
            self._stats["completed_requests"] += 1
            logger.debug(f"Resolved request {correlation_id}")
            return True
        elif request:
            logger.warning(f"Request {correlation_id} already completed")
        else:
            logger.warning(f"Request {correlation_id} not found")

        return False

    async def cancel_request(self, correlation_id: str, reason: str = "cancelled") -> bool:
        """
        Cancel a pending request

        Returns:
            bool: True if request was found and cancelled, False otherwise
        """
        async with self._lock:
            request = self.pending_requests.pop(correlation_id, None)

        if request and not request.future.done():
            request.future.cancel()
            logger.debug(f"Cancelled request {correlation_id}: {reason}")
            return True

        return False

    async def get_request_count(self) -> int:
        """Get current number of pending requests"""
        async with self._lock:
            return len(self.pending_requests)

    async def get_stats(self) -> Dict[str, Any]:
        """Get request manager statistics"""
        async with self._lock:
            pending_count = len(self.pending_requests)

        return {
            **self._stats,
            "pending_requests": pending_count,
            "cleanup_interval": self.cleanup_interval,
            "default_timeout": self.default_timeout
        }

    async def _cleanup_loop(self):
        """Background task to clean up expired requests"""
        logger.info(f"Cleanup loop started (interval: {self.cleanup_interval}s)")

        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_requests()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    async def _cleanup_expired_requests(self):
        """Clean up expired requests"""
        now = datetime.now()
        expired_requests = []

        async with self._lock:
            for correlation_id, request in list(self.pending_requests.items()):
                time_elapsed = now - request.created_at

                if time_elapsed.total_seconds() > request.timeout:
                    expired_requests.append((correlation_id, request))
                    del self.pending_requests[correlation_id]

        # Process expired requests outside the lock
        for correlation_id, request in expired_requests:
            if not request.future.done():
                request.future.set_exception(
                    asyncio.TimeoutError(f"Request {correlation_id} timed out after {request.timeout}s")
                )
                self._stats["timed_out_requests"] += 1

            self._stats["cleaned_up_requests"] += 1
            logger.debug(f"Cleaned up expired request {correlation_id}")

        if expired_requests:
            logger.info(f"Cleaned up {len(expired_requests)} expired requests")

    async def wait_for_response(
        self,
        correlation_id: str,
        timeout: Optional[float] = None
    ) -> Any:
        """
        Wait for response to a specific request

        Args:
            correlation_id: The request correlation ID
            timeout: Optional timeout override

        Returns:
            The response data

        Raises:
            asyncio.TimeoutError: If request times out
            KeyError: If request not found
        """
        async with self._lock:
            request = self.pending_requests.get(correlation_id)

        if not request:
            raise KeyError(f"Request {correlation_id} not found")

        try:
            # Use the request's timeout or override
            wait_timeout = timeout or request.timeout
            return await asyncio.wait_for(request.future, timeout=wait_timeout)
        except asyncio.TimeoutError:
            # Clean up the timed-out request
            await self.cancel_request(correlation_id, "timeout")
            raise

    async def send_request_and_wait(
        self,
        send_callback,
        message: Dict[str, Any],
        timeout: Optional[float] = None,
        agent_id: Optional[str] = None,
        request_type: Optional[str] = None
    ) -> Any:
        """
        Helper method to send a request and wait for response

        Args:
            send_callback: Async function to send the message
            message: Message to send (correlation_id will be added)
            timeout: Request timeout
            agent_id: Agent ID for tracking
            request_type: Type of request for tracking

        Returns:
            Response data
        """
        correlation_id, future = await self.create_request(
            timeout=timeout,
            agent_id=agent_id,
            request_type=request_type
        )

        # Add correlation ID to message
        message["correlation_id"] = correlation_id

        try:
            # Send the message
            await send_callback(message)

            # Wait for response
            return await self.wait_for_response(correlation_id, timeout)

        except Exception as e:
            # Clean up on any error
            await self.cancel_request(correlation_id, f"error: {str(e)}")
            raise


# Global instance for use across the application
request_manager = RequestManager()