#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Configuration settings for LLM API Gateway
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings

try:
    from .utils.constants import (
        MIN_PORT, MAX_PORT, MIN_AGENT_TIMEOUT, MAX_AGENT_TIMEOUT,
        MIN_CONCURRENT_GAMES, MAX_CONCURRENT_GAMES, MIN_HEARTBEAT_INTERVAL,
        MAX_HEARTBEAT_INTERVAL, MIN_RATE_LIMIT, MAX_RATE_LIMIT,
        MAX_CONNECTIONS_PER_AGENT
    )
except ImportError:
    from utils.constants import (
        MIN_PORT, MAX_PORT, MIN_AGENT_TIMEOUT, MAX_AGENT_TIMEOUT,
        MIN_CONCURRENT_GAMES, MAX_CONCURRENT_GAMES, MIN_HEARTBEAT_INTERVAL,
        MAX_HEARTBEAT_INTERVAL, MIN_RATE_LIMIT, MAX_RATE_LIMIT,
        MAX_CONNECTIONS_PER_AGENT
    )


class Settings(BaseSettings):
    """Configuration settings with environment variable support"""

    # FreeCiv Proxy connection settings
    freeciv_proxy_host: str = "localhost"
    freeciv_proxy_port: int = 8002
    freeciv_proxy_ws_path: str = "/llmsocket/8002"  # Use LLM handler endpoint

    # Redis connection for state management
    redis_url: str = "redis://localhost:6379"
    redis_db: int = 0

    # Gateway server settings
    host: str = "0.0.0.0"
    port: int = 8003
    max_concurrent_games: int = 10
    max_agents_per_game: int = 8

    # Agent connection settings
    agent_timeout: int = 600  # seconds (10 minutes for longer games)
    max_connections_per_agent: int = 2
    heartbeat_interval: int = 30  # seconds
    session_resumption_window: int = 3600  # 1 hour - extended for hours-long LLM matches (AGE-298)

    # Security settings
    allowed_origins: List[str] = [
        "http://localhost:3000",
        "http://localhost:8080",
        "https://localhost:3000",
        "https://localhost:8080"
    ]
    api_key_header: str = "Authorization"
    require_api_key: bool = True

    # Rate limiting - optimized for turn-based gameplay
    rate_limit_requests_per_minute: int = 300  # Increased from 200 for concurrent multi-player games
    rate_limit_burst_size: int = 80  # Increased from 40 - allows ~20 actions per turn for 4 players
    rate_limit_grace_period: int = 30  # seconds before blocking on violations
    rate_limit_max_violations: int = 3  # violations before blocking

    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Connection retry settings
    max_retry_attempts: int = 3
    initial_retry_delay: float = 1.0  # seconds
    max_retry_delay: float = 30.0  # seconds
    retry_backoff_multiplier: float = 2.0
    connection_timeout: float = 10.0  # seconds
    websocket_open_timeout: float = 30.0  # WebSocket handshake timeout (addresses E999 errors)

    # Feature flags
    enable_batch_actions: bool = True
    enable_metrics: bool = True
    streaming_enabled: bool = True  # YouTube streaming for matches

    # Observer streaming settings
    freeciv_web_base_url: str = "http://localhost:8080"  # Base URL for FreeCiv web client

    # Local streaming settings (for development when K8s is not available)
    # Set to enable local_stream_urls in observer-urls response
    # Streaming runs by default with `docker-compose up`
    local_stream_base_url: str = "http://localhost:8890"  # MediaMTX HLS base URL (port 8890)

    class Config:
        env_file = ".env"
        env_prefix = "GATEWAY_"


# Global settings instance
settings = Settings()


def get_freeciv_proxy_url() -> str:
    """Get the complete FreeCiv proxy WebSocket URL"""
    return f"ws://{settings.freeciv_proxy_host}:{settings.freeciv_proxy_port}{settings.freeciv_proxy_ws_path}"


def get_cors_origins() -> List[str]:
    """Get CORS allowed origins"""
    return settings.allowed_origins


def validate_settings() -> bool:
    """Comprehensive validation of configuration settings"""
    errors = []
    warnings = []

    try:
        # Validate port ranges using constants
        if not (MIN_PORT <= settings.port <= MAX_PORT):
            errors.append(f"Invalid port: {settings.port} (must be {MIN_PORT}-{MAX_PORT})")

        if not (MIN_PORT <= settings.freeciv_proxy_port <= MAX_PORT):
            errors.append(f"Invalid FreeCiv proxy port: {settings.freeciv_proxy_port} (must be {MIN_PORT}-{MAX_PORT})")

        # Validate timeout settings
        if not (MIN_AGENT_TIMEOUT <= settings.agent_timeout <= MAX_AGENT_TIMEOUT):
            errors.append(f"Invalid agent_timeout: {settings.agent_timeout} (must be {MIN_AGENT_TIMEOUT}-{MAX_AGENT_TIMEOUT})")

        # Validate session resumption window (extended to 2 hours max for long LLM matches)
        if not (0 <= settings.session_resumption_window <= 7200):
            errors.append(f"Invalid session_resumption_window: {settings.session_resumption_window} (must be 0-7200)")

        # Validate game and connection limits
        if not (MIN_CONCURRENT_GAMES <= settings.max_concurrent_games <= MAX_CONCURRENT_GAMES):
            errors.append(f"Invalid max_concurrent_games: {settings.max_concurrent_games} (must be {MIN_CONCURRENT_GAMES}-{MAX_CONCURRENT_GAMES})")

        if not (1 <= settings.max_connections_per_agent <= MAX_CONNECTIONS_PER_AGENT):
            errors.append(f"Invalid max_connections_per_agent: {settings.max_connections_per_agent} (must be 1-{MAX_CONNECTIONS_PER_AGENT})")

        # Validate heartbeat interval
        if not (MIN_HEARTBEAT_INTERVAL <= settings.heartbeat_interval <= MAX_HEARTBEAT_INTERVAL):
            errors.append(f"Invalid heartbeat_interval: {settings.heartbeat_interval} (must be {MIN_HEARTBEAT_INTERVAL}-{MAX_HEARTBEAT_INTERVAL})")

        # Validate rate limiting settings
        if not (MIN_RATE_LIMIT <= settings.rate_limit_requests_per_minute <= MAX_RATE_LIMIT):
            errors.append(f"Invalid rate_limit_requests_per_minute: {settings.rate_limit_requests_per_minute} (must be {MIN_RATE_LIMIT}-{MAX_RATE_LIMIT})")

        if not (1 <= settings.rate_limit_burst_size <= settings.rate_limit_requests_per_minute):
            errors.append(f"Invalid rate_limit_burst_size: {settings.rate_limit_burst_size} (must be 1-{settings.rate_limit_requests_per_minute})")

        # Validate rate limit grace period and violations
        if not (0 <= settings.rate_limit_grace_period <= 300):
            errors.append(f"Invalid rate_limit_grace_period: {settings.rate_limit_grace_period} (must be 0-300)")

        if not (1 <= settings.rate_limit_max_violations <= 10):
            errors.append(f"Invalid rate_limit_max_violations: {settings.rate_limit_max_violations} (must be 1-10)")

        # Validate retry settings
        if not (1 <= settings.max_retry_attempts <= 10):
            errors.append(f"Invalid max_retry_attempts: {settings.max_retry_attempts} (must be 1-10)")

        if not (0.1 <= settings.initial_retry_delay <= 60.0):
            errors.append(f"Invalid initial_retry_delay: {settings.initial_retry_delay} (must be 0.1-60.0)")

        if not (1.0 <= settings.retry_backoff_multiplier <= 10.0):
            errors.append(f"Invalid retry_backoff_multiplier: {settings.retry_backoff_multiplier} (must be 1.0-10.0)")

        if not (1.0 <= settings.connection_timeout <= 300.0):
            errors.append(f"Invalid connection_timeout: {settings.connection_timeout} (must be 1.0-300.0)")

        if not (5.0 <= settings.websocket_open_timeout <= 120.0):
            errors.append(f"Invalid websocket_open_timeout: {settings.websocket_open_timeout} (must be 5.0-120.0)")

        # Validate Redis URL format
        if not settings.redis_url.startswith(("redis://", "rediss://")):
            errors.append("Invalid Redis URL format (must start with redis:// or rediss://)")

        if not (0 <= settings.redis_db <= 15):
            errors.append(f"Invalid Redis database: {settings.redis_db} (must be 0-15)")

        # Validate log level
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if settings.log_level.upper() not in valid_log_levels:
            errors.append(f"Invalid log_level: {settings.log_level} (must be one of {valid_log_levels})")

        # Validate allowed origins
        if not settings.allowed_origins:
            warnings.append("No allowed_origins specified - this may cause CORS issues")

        for origin in settings.allowed_origins:
            if not origin.startswith(("http://", "https://", "ws://", "wss://")):
                warnings.append(f"Suspicious origin format: {origin}")

        # Security warnings
        if "localhost" in str(settings.allowed_origins) and settings.host == "0.0.0.0":
            warnings.append("Allowing localhost origins while binding to all interfaces (0.0.0.0) may be insecure")

        if not settings.require_api_key:
            warnings.append("API key requirement is disabled - this may be insecure in production")

        # Performance warnings
        if settings.max_concurrent_games > 100:
            warnings.append(f"High max_concurrent_games setting ({settings.max_concurrent_games}) may impact performance")

        if settings.rate_limit_requests_per_minute > 1000:
            warnings.append(f"High rate limit ({settings.rate_limit_requests_per_minute}/min) may allow abuse")

        # Print validation results
        if errors:
            print("❌ Configuration validation FAILED:")
            for error in errors:
                print(f"   • {error}")
            return False

        if warnings:
            print("⚠️  Configuration warnings:")
            for warning in warnings:
                print(f"   • {warning}")

        # Test Redis connection
        try:
            import redis
            redis_client = redis.from_url(
                settings.redis_url,
                db=settings.redis_db,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection with a simple ping
            redis_client.ping()
            print(f"✅ Redis connection successful: {settings.redis_url}")
        except ImportError:
            warnings.append("Redis package not installed - falling back to in-memory storage")
            print("⚠️  Redis package not installed - falling back to in-memory storage")
        except Exception as e:
            warnings.append(f"Redis connection failed: {e}")
            print(f"⚠️  Redis connection failed: {e}")
            print("⚠️  Falling back to in-memory storage (not recommended for production)")

        print("✅ Configuration validation passed")
        return True

    except Exception as e:
        print(f"❌ Configuration validation error: {e}")
        return False