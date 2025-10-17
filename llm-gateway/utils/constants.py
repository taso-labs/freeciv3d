#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Constants for LLM API Gateway
Centralizes magic numbers and configuration values
"""

# Time constants (seconds)
COOLDOWN_PERIOD = 60  # Connection failure cooldown
DEFAULT_REQUEST_TIMEOUT = 30.0  # Default request timeout
CLEANUP_INTERVAL = 5.0  # Request cleanup interval
HEALTH_CHECK_TIMEOUT = 5.0  # Health check ping timeout
CLEANUP_CYCLE_SECONDS = 60  # Connection cleanup cycle
TOKEN_TTL_SECONDS = 86400  # Token time-to-live (24 hours)
SESSION_TIMEOUT_SECONDS = 3600  # Session timeout (1 hour)

# Rate limiting constants
DEFAULT_REQUESTS_PER_MINUTE = 100
DEFAULT_BURST_SIZE = 20
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_TIMED_OUT_REQUESTS_WARNING = 10  # Warning threshold for timed out requests

# Connection constants
CONNECTION_POOL_MAX = 50  # Maximum connections per pool
GLOBAL_CONNECTION_LIMIT = 200  # Global connection limit across all pools
MAX_CONNECTIONS_PER_AGENT = 5  # Maximum connections per agent
MAX_CONNECTION_ATTEMPTS_PER_MINUTE = 10  # Maximum connection attempts per agent per minute
CONNECTION_ATTEMPT_BLOCK_DURATION = 300  # Block duration for excessive connection attempts (5 minutes)
REDIS_CONNECTION_TIMEOUT = 5  # Redis connection timeout
HEALTH_CHECK_INTERVAL = 30.0  # Health check interval

# Message and data size limits
# CRITICAL FIX: Increased to 100MB to handle large FreeCiv game state packets
# FreeCiv sends map data, player info, city data that can exceed 1MB
MAX_MESSAGE_SIZE_BYTES = 100 * 1024 * 1024  # 100MB for FreeCiv game state packets
MAX_JSON_DEPTH = 10  # Maximum JSON nesting depth
MAX_VALIDATION_ATTEMPTS = 5  # Maximum validation attempts per window
VALIDATION_WINDOW_SECONDS = 300  # Validation rate limit window (5 minutes)

# Retry and backoff constants
MAX_RETRY_ATTEMPTS = 3
INITIAL_RETRY_DELAY = 1.0  # seconds
MAX_RETRY_DELAY = 30.0  # seconds
RETRY_BACKOFF_MULTIPLIER = 2.0

# Cryptographic constants
PBKDF2_ITERATIONS = 100_000  # PBKDF2 iteration count
SALT_LENGTH = 16  # Salt length in bytes
KEY_LENGTH = 32  # Derived key length in bytes

# Port ranges
MIN_PORT = 1
MAX_PORT = 65535

# Validation limits
MIN_AGENT_TIMEOUT = 1
MAX_AGENT_TIMEOUT = 3600
MIN_CONCURRENT_GAMES = 1
MAX_CONCURRENT_GAMES = 1000
MIN_HEARTBEAT_INTERVAL = 1
MAX_HEARTBEAT_INTERVAL = 300
MIN_RATE_LIMIT = 1
MAX_RATE_LIMIT = 10000

# Error codes
ERROR_CODE_INTERNAL = "E500"
ERROR_CODE_RATE_LIMIT = "E429"
ERROR_CODE_UNAUTHORIZED = "E403"
ERROR_CODE_NOT_FOUND = "E404"
ERROR_CODE_VALIDATION = "E400"

# HTTP status codes
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429
HTTP_INTERNAL_ERROR = 500
HTTP_SERVICE_UNAVAILABLE = 503