#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Rate Limiting and DoS Prevention Utilities for LLM API Gateway
Implements token bucket algorithm and various rate limiting strategies
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

try:
    from .constants import MAX_CONNECTIONS_PER_AGENT, MAX_CONNECTION_ATTEMPTS_PER_MINUTE, CONNECTION_ATTEMPT_BLOCK_DURATION
except ImportError:
    from constants import MAX_CONNECTIONS_PER_AGENT, MAX_CONNECTION_ATTEMPTS_PER_MINUTE, CONNECTION_ATTEMPT_BLOCK_DURATION

logger = logging.getLogger("llm-gateway")


class RateLimitType(Enum):
    """Types of rate limits"""
    REQUESTS_PER_MINUTE = "requests_per_minute"
    REQUESTS_PER_SECOND = "requests_per_second"
    BYTES_PER_MINUTE = "bytes_per_minute"
    CONNECTIONS_PER_AGENT = "connections_per_agent"
    BURST_PROTECTION = "burst_protection"


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit"""
    limit_type: RateLimitType
    limit_value: int
    window_seconds: int
    burst_allowance: int = 0
    block_duration: int = 60  # Seconds to block after limit exceeded


class TokenBucket:
    """
    Token bucket algorithm implementation for rate limiting
    """

    def __init__(self, capacity: int, refill_rate: float, refill_period: float = 1.0):
        """
        Initialize token bucket

        Args:
            capacity: Maximum number of tokens
            refill_rate: Tokens added per refill period
            refill_period: How often to refill (seconds)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_period = refill_period
        self.tokens = capacity
        self.last_refill = time.time()
        self._lock = asyncio.Lock()

    async def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from the bucket

        Args:
            tokens: Number of tokens to consume

        Returns:
            bool: True if tokens were consumed, False if not enough tokens
        """
        async with self._lock:
            await self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False

    async def _refill(self):
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill

        if elapsed >= self.refill_period:
            periods = elapsed / self.refill_period
            tokens_to_add = periods * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now

    async def get_status(self) -> Dict[str, Any]:
        """Get current bucket status"""
        async with self._lock:
            await self._refill()
            return {
                "tokens_available": self.tokens,
                "capacity": self.capacity,
                "refill_rate": self.refill_rate,
                "utilization": (self.capacity - self.tokens) / self.capacity
            }


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter with precise tracking
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests: Dict[str, deque] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def is_allowed(self, identifier: str) -> bool:
        """
        Check if request is allowed within rate limit

        Args:
            identifier: Unique identifier (agent_id, IP, etc.)

        Returns:
            bool: True if request is allowed
        """
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds

            # Clean old requests
            request_times = self.requests[identifier]
            while request_times and request_times[0] < window_start:
                request_times.popleft()

            # Check limit
            if len(request_times) >= self.limit:
                return False

            # Record this request
            request_times.append(now)
            return True

    async def get_remaining(self, identifier: str) -> int:
        """Get remaining requests in current window"""
        async with self._lock:
            now = time.time()
            window_start = now - self.window_seconds

            # Clean old requests
            request_times = self.requests[identifier]
            while request_times and request_times[0] < window_start:
                request_times.popleft()

            return max(0, self.limit - len(request_times))

    async def get_reset_time(self, identifier: str) -> float:
        """Get time when rate limit resets"""
        async with self._lock:
            request_times = self.requests.get(identifier)
            if not request_times:
                return time.time()

            return request_times[0] + self.window_seconds


class MessageSizeValidator:
    """
    Validates message sizes to prevent DoS attacks
    """

    def __init__(self, max_message_size: int = 1_000_000, max_json_depth: int = 10):
        """
        Initialize message size validator

        Args:
            max_message_size: Maximum message size in bytes
            max_json_depth: Maximum JSON nesting depth
        """
        self.max_message_size = max_message_size
        self.max_json_depth = max_json_depth

    def validate_size(self, message: str) -> bool:
        """
        Validate message size

        Args:
            message: Message to validate

        Returns:
            bool: True if message size is acceptable
        """
        return len(message.encode('utf-8')) <= self.max_message_size

    def validate_json_depth(self, data: Any, current_depth: int = 0) -> bool:
        """
        Validate JSON nesting depth

        Args:
            data: JSON data to validate
            current_depth: Current nesting depth

        Returns:
            bool: True if depth is acceptable
        """
        if current_depth > self.max_json_depth:
            return False

        if isinstance(data, dict):
            return all(
                self.validate_json_depth(value, current_depth + 1)
                for value in data.values()
            )
        elif isinstance(data, list):
            return all(
                self.validate_json_depth(item, current_depth + 1)
                for item in data
            )

        return True

    def validate_message_content(self, message: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        Comprehensive message validation with parsed JSON return

        Args:
            message: Message to validate

        Returns:
            Tuple of (is_valid, error_message, parsed_data)
            - is_valid: bool indicating if validation passed
            - error_message: str with error details (empty if valid)
            - parsed_data: Dict with parsed JSON if valid, None if invalid
        """
        # Size validation
        if not self.validate_size(message):
            return False, f"Message size exceeds limit ({self.max_message_size} bytes)", None

        # JSON parsing and depth validation
        try:
            import json
            data = json.loads(message)

            if not self.validate_json_depth(data):
                return False, f"JSON nesting depth exceeds limit ({self.max_json_depth})", None

            # Return parsed data to avoid double parsing by caller
            return True, "", data

        except json.JSONDecodeError as e:
            return False, f"Invalid JSON format: {str(e)}", None


class ComprehensiveRateLimiter:
    """
    Comprehensive rate limiter with multiple strategies
    """

    def __init__(self):
        self.rate_limiters: Dict[RateLimitType, SlidingWindowRateLimiter] = {}
        self.token_buckets: Dict[str, TokenBucket] = {}
        self.blocked_identifiers: Dict[str, float] = {}  # identifier -> block_until_time
        self.size_validator = MessageSizeValidator()

        # Connection tracking
        self.active_connections: Dict[str, int] = defaultdict(int)
        self.connection_timestamps: Dict[str, List[float]] = defaultdict(list)

        # Grace period tracking (identifier -> (violation_count, last_violation_time))
        self.grace_period_violations: Dict[str, Tuple[int, float]] = {}
        self.grace_period_seconds = 30  # Default grace period
        self.max_violations_before_block = 3  # Default max violations

        self._lock = asyncio.Lock()

        # Statistics
        self._stats = {
            "total_requests": 0,
            "blocked_requests": 0,
            "size_violations": 0,
            "rate_limit_violations": 0,
            "active_blocks": 0,
            "grace_period_warnings": 0
        }

    def add_rate_limit(self, limit_type: RateLimitType, config: RateLimitConfig):
        """Add a rate limit configuration"""
        self.rate_limiters[limit_type] = SlidingWindowRateLimiter(
            config.limit_value,
            config.window_seconds
        )

    def configure_grace_period(self, grace_period_seconds: int, max_violations: int):
        """
        Configure grace period settings for rate limiting

        Args:
            grace_period_seconds: Time window to track violations before blocking
            max_violations: Number of violations allowed before blocking
        """
        self.grace_period_seconds = grace_period_seconds
        self.max_violations_before_block = max_violations
        logger.info(f"Grace period configured: {grace_period_seconds}s, max violations: {max_violations}")

    async def check_rate_limits(
        self,
        identifier: str,
        message_size: int = 0,
        message_content: str = None
    ) -> Tuple[bool, str]:
        """
        Check all applicable rate limits with message-type-specific limits

        Args:
            identifier: Unique identifier (agent_id, IP, etc.)
            message_size: Size of the message in bytes
            message_content: Optional message content for validation

        Returns:
            Tuple of (is_allowed, reason)
        """
        self._stats["total_requests"] += 1

        # Check if identifier is currently blocked
        if await self._is_blocked(identifier):
            self._stats["blocked_requests"] += 1
            return False, "Temporarily blocked due to rate limit violation"

        # Message size validation and type extraction
        msg_type = "unknown"
        if message_content:
            is_valid, error_msg, parsed_data = self.size_validator.validate_message_content(message_content)
            if not is_valid:
                self._stats["size_violations"] += 1
                await self._add_violation(identifier)
                return False, f"Message validation failed: {error_msg}"

            # Extract message type for type-specific rate limiting
            if parsed_data and isinstance(parsed_data, dict):
                msg_type = parsed_data.get("type", "unknown")

        # Message-type-specific rate limiting for turn-based gameplay
        # Different message types have different performance impacts:
        # - 'action': Cheap (just forwarding JSON) - allow high burst
        # - 'state_query': Expensive (builds game state) - limit more strictly
        # - 'llm_connect': One-time (connection setup) - very permissive
        if msg_type == "action":
            # Actions: Allow 80 per minute with burst of 80 (full turn execution)
            action_bucket_key = f"action_{identifier}"
            if action_bucket_key not in self.token_buckets:
                self.token_buckets[action_bucket_key] = TokenBucket(
                    capacity=80,
                    refill_rate=80.0 / 60.0  # 80 per minute
                )
            if not await self.token_buckets[action_bucket_key].consume(1):
                self._stats["rate_limit_violations"] += 1
                await self._add_violation(identifier)
                return False, "Action rate limit exceeded (80/min)"

        elif msg_type == "state_query":
            # State queries: More restrictive - 20 per minute with burst of 20
            query_bucket_key = f"query_{identifier}"
            if query_bucket_key not in self.token_buckets:
                self.token_buckets[query_bucket_key] = TokenBucket(
                    capacity=20,
                    refill_rate=20.0 / 60.0  # 20 per minute
                )
            if not await self.token_buckets[query_bucket_key].consume(1):
                self._stats["rate_limit_violations"] += 1
                await self._add_violation(identifier)
                return False, "State query rate limit exceeded (20/min)"

        else:
            # All other message types: Use default rate limits
            for limit_type, limiter in self.rate_limiters.items():
                if limit_type == RateLimitType.REQUESTS_PER_MINUTE:
                    if not await limiter.is_allowed(identifier):
                        self._stats["rate_limit_violations"] += 1
                        await self._add_violation(identifier)
                        return False, "Request rate limit exceeded"

                elif limit_type == RateLimitType.BYTES_PER_MINUTE and message_size > 0:
                    # Check byte rate limit using token bucket
                    bucket_key = f"bytes_{identifier}"
                    if bucket_key not in self.token_buckets:
                        # Create bucket with byte limit
                        capacity = self.rate_limiters[limit_type].limit
                        self.token_buckets[bucket_key] = TokenBucket(
                            capacity=capacity,
                            refill_rate=capacity / 60.0  # Refill over 1 minute
                        )

                    if not await self.token_buckets[bucket_key].consume(message_size):
                        self._stats["rate_limit_violations"] += 1
                        await self._add_violation(identifier)
                        return False, "Byte rate limit exceeded"

        return True, ""

    async def track_connection(self, identifier: str) -> bool:
        """
        Track new connection and check connection limits

        Args:
            identifier: Unique identifier

        Returns:
            bool: True if connection is allowed
        """
        async with self._lock:
            # Check if identifier is blocked
            if identifier in self.blocked_identifiers:
                if time.time() < self.blocked_identifiers[identifier]:
                    return False
                else:
                    # Block expired
                    del self.blocked_identifiers[identifier]
                    self._stats["active_blocks"] = max(0, self._stats["active_blocks"] - 1)

            # Check connection attempt rate limiting
            now = time.time()
            recent_attempts = [ts for ts in self.connection_timestamps[identifier] if now - ts < 60]
            if len(recent_attempts) >= MAX_CONNECTION_ATTEMPTS_PER_MINUTE:
                # Too many connection attempts, block for specified duration
                self.blocked_identifiers[identifier] = now + CONNECTION_ATTEMPT_BLOCK_DURATION
                self._stats["active_blocks"] += 1
                logger.warning(f"Blocking {identifier} for excessive connection attempts: {len(recent_attempts)} in 60s")
                return False

            # Check connection per agent limit
            max_connections = MAX_CONNECTIONS_PER_AGENT
            if RateLimitType.CONNECTIONS_PER_AGENT in self.rate_limiters:
                max_connections = self.rate_limiters[RateLimitType.CONNECTIONS_PER_AGENT].limit

            if self.active_connections[identifier] >= max_connections:
                return False

            # Track connection
            self.active_connections[identifier] += 1
            self.connection_timestamps[identifier].append(now)

            return True

    async def release_connection(self, identifier: str):
        """Release a connection"""
        async with self._lock:
            if self.active_connections[identifier] > 0:
                self.active_connections[identifier] -= 1

    async def _is_blocked(self, identifier: str) -> bool:
        """Check if identifier is currently blocked"""
        async with self._lock:
            if identifier in self.blocked_identifiers:
                if time.time() < self.blocked_identifiers[identifier]:
                    return True
                else:
                    # Block expired
                    del self.blocked_identifiers[identifier]
                    self._stats["active_blocks"] = max(0, self._stats["active_blocks"] - 1)

            return False

    async def _add_violation(self, identifier: str, block_duration: int = 60):
        """
        Add a rate limit violation with grace period tracking
        Only blocks after exceeding max_violations within grace_period_seconds
        """
        async with self._lock:
            now = time.time()

            # Get current violation info
            if identifier in self.grace_period_violations:
                violation_count, last_violation_time = self.grace_period_violations[identifier]

                # Check if within grace period window
                if now - last_violation_time <= self.grace_period_seconds:
                    violation_count += 1
                else:
                    # Grace period expired, reset counter
                    violation_count = 1
            else:
                # First violation
                violation_count = 1

            # Update violation tracking
            self.grace_period_violations[identifier] = (violation_count, now)
            self._stats["grace_period_warnings"] += 1

            # Check if should block
            if violation_count >= self.max_violations_before_block:
                # Exceeded max violations - block identifier
                self.blocked_identifiers[identifier] = now + block_duration
                self._stats["active_blocks"] += 1

                # Clear grace period tracking (will restart after block expires)
                del self.grace_period_violations[identifier]

                logger.warning(
                    f"Rate limit violation: blocking {identifier} for {block_duration}s "
                    f"(exceeded {violation_count} violations in {self.grace_period_seconds}s grace period)"
                )
            else:
                # Still within grace period
                remaining_violations = self.max_violations_before_block - violation_count
                logger.info(
                    f"Rate limit warning for {identifier}: violation {violation_count}/{self.max_violations_before_block} "
                    f"({remaining_violations} remaining before block)"
                )

    async def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics"""
        async with self._lock:
            # Update active blocks count
            current_time = time.time()
            active_blocks = sum(
                1 for block_time in self.blocked_identifiers.values()
                if block_time > current_time
            )
            self._stats["active_blocks"] = active_blocks

            return {
                **self._stats,
                "active_connections": sum(self.active_connections.values()),
                "unique_identifiers": len(self.active_connections),
                "rate_limiters_configured": len(self.rate_limiters)
            }

    async def get_identifier_status(self, identifier: str) -> Dict[str, Any]:
        """Get status for a specific identifier including grace period info"""
        status = {
            "identifier": identifier,
            "is_blocked": await self._is_blocked(identifier),
            "active_connections": self.active_connections.get(identifier, 0),
            "remaining_limits": {},
            "grace_period": {}
        }

        # Get grace period violation status
        async with self._lock:
            if identifier in self.grace_period_violations:
                violation_count, last_violation_time = self.grace_period_violations[identifier]
                time_since_last = time.time() - last_violation_time

                status["grace_period"] = {
                    "violations": violation_count,
                    "max_violations": self.max_violations_before_block,
                    "remaining_violations": self.max_violations_before_block - violation_count,
                    "time_since_last_violation": time_since_last,
                    "grace_period_window": self.grace_period_seconds,
                    "will_reset_in": max(0, self.grace_period_seconds - time_since_last)
                }

        # Get remaining limits for each type
        for limit_type, limiter in self.rate_limiters.items():
            if limit_type in [RateLimitType.REQUESTS_PER_MINUTE, RateLimitType.REQUESTS_PER_SECOND]:
                remaining = await limiter.get_remaining(identifier)
                reset_time = await limiter.get_reset_time(identifier)
                status["remaining_limits"][limit_type.value] = {
                    "remaining": remaining,
                    "reset_time": reset_time
                }

        # Token bucket status
        for bucket_key, bucket in self.token_buckets.items():
            if identifier in bucket_key:
                bucket_status = await bucket.get_status()
                status[f"bucket_{bucket_key}"] = bucket_status

        return status


# Global rate limiter instance
comprehensive_rate_limiter = ComprehensiveRateLimiter()

# Default configuration
def setup_default_rate_limits():
    """Setup default rate limiting configuration"""
    try:
        from .constants import (
            DEFAULT_REQUESTS_PER_MINUTE, DEFAULT_BURST_SIZE,
            RATE_LIMIT_GRACE_PERIOD, RATE_LIMIT_MAX_VIOLATIONS_BEFORE_BLOCK
        )
    except ImportError:
        from constants import (
            DEFAULT_REQUESTS_PER_MINUTE, DEFAULT_BURST_SIZE,
            RATE_LIMIT_GRACE_PERIOD, RATE_LIMIT_MAX_VIOLATIONS_BEFORE_BLOCK
        )

    # Requests per minute
    comprehensive_rate_limiter.add_rate_limit(
        RateLimitType.REQUESTS_PER_MINUTE,
        RateLimitConfig(
            limit_type=RateLimitType.REQUESTS_PER_MINUTE,
            limit_value=DEFAULT_REQUESTS_PER_MINUTE,  # 300 requests per minute (increased for concurrent multi-player games)
            window_seconds=60
        )
    )

    # Burst protection (requests per second)
    # Use DEFAULT_BURST_SIZE as requests per second limit to handle turn spikes
    comprehensive_rate_limiter.add_rate_limit(
        RateLimitType.REQUESTS_PER_SECOND,
        RateLimitConfig(
            limit_type=RateLimitType.REQUESTS_PER_SECOND,
            limit_value=DEFAULT_BURST_SIZE,  # 80 requests per second (allows ~20 actions per turn for 4 players)
            window_seconds=1
        )
    )

    # Bytes per minute (2MB - increased for larger state queries)
    comprehensive_rate_limiter.add_rate_limit(
        RateLimitType.BYTES_PER_MINUTE,
        RateLimitConfig(
            limit_type=RateLimitType.BYTES_PER_MINUTE,
            limit_value=2_000_000,  # 2MB per minute (increased from 1MB)
            window_seconds=60
        )
    )

    # Configure grace period
    comprehensive_rate_limiter.configure_grace_period(
        grace_period_seconds=RATE_LIMIT_GRACE_PERIOD,
        max_violations=RATE_LIMIT_MAX_VIOLATIONS_BEFORE_BLOCK
    )

    logger.info(
        f"Default rate limits configured: {DEFAULT_REQUESTS_PER_MINUTE} req/min, "
        f"{DEFAULT_BURST_SIZE} req/sec burst, 2MB/min bandwidth, "
        f"{RATE_LIMIT_GRACE_PERIOD}s grace period with {RATE_LIMIT_MAX_VIOLATIONS_BEFORE_BLOCK} max violations"
    )


# Initialize with default configuration
setup_default_rate_limits()