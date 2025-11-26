#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Origin Validation Utilities for LLM API Gateway
Provides WebSocket origin validation for security
"""

import logging
import re
from typing import List, Optional, Dict, Any
from urllib.parse import urlparse, ParseResult
from fastapi import WebSocket

logger = logging.getLogger("llm-gateway")


class OriginValidator:
    """
    WebSocket origin validation for security
    """

    def __init__(self, allowed_origins: List[str], strict_mode: bool = True):
        """
        Initialize the origin validator

        Args:
            allowed_origins: List of allowed origin patterns
            strict_mode: If True, reject connections with no origin header
        """
        self.allowed_origins = allowed_origins
        self.strict_mode = strict_mode
        self._compiled_patterns = self._compile_patterns(allowed_origins)

        # Statistics
        self._stats = {
            "validation_attempts": 0,
            "accepted_connections": 0,
            "rejected_connections": 0,
            "null_origin_connections": 0
        }

    def _compile_patterns(self, origins: List[str]) -> List[Dict[str, Any]]:
        """
        Compile origin patterns for efficient matching

        Args:
            origins: List of origin patterns

        Returns:
            List of compiled pattern dictionaries
        """
        compiled = []

        for origin in origins:
            pattern_info = {
                "raw": origin,
                "type": "exact"
            }

            # Handle wildcard patterns
            if "*" in origin:
                # Convert wildcard pattern to regex
                escaped = re.escape(origin)
                regex_pattern = escaped.replace(r"\*", r".*")
                pattern_info["regex"] = re.compile(f"^{regex_pattern}$", re.IGNORECASE)
                pattern_info["type"] = "wildcard"
            else:
                # Parse exact URL for components
                try:
                    parsed = urlparse(origin)
                    pattern_info["parsed"] = parsed
                    pattern_info["type"] = "exact"
                except Exception as e:
                    logger.warning(f"Invalid origin pattern '{origin}': {e}")
                    continue

            compiled.append(pattern_info)

        return compiled

    def validate_origin(self, origin: Optional[str]) -> bool:
        """
        Validate WebSocket origin header

        Args:
            origin: Origin header value (may be None)

        Returns:
            bool: True if origin is allowed, False otherwise
        """
        self._stats["validation_attempts"] += 1

        # Handle null/missing origin
        if origin is None:
            self._stats["null_origin_connections"] += 1

            if self.strict_mode:
                logger.debug("Rejected connection: null origin in strict mode")
                self._stats["rejected_connections"] += 1
                return False
            else:
                # Allow null origin for non-browser clients (LLM agents)
                logger.debug("Allowed null origin for non-browser client")
                self._stats["accepted_connections"] += 1
                return True

        # Validate against patterns
        for pattern_info in self._compiled_patterns:
            if self._matches_pattern(origin, pattern_info):
                logger.debug(f"Origin '{origin}' matches pattern '{pattern_info['raw']}'")
                self._stats["accepted_connections"] += 1
                return True

        # No match found
        logger.warning(f"Rejected origin: '{origin}' not in allowed list")
        self._stats["rejected_connections"] += 1
        return False

    def _matches_pattern(self, origin: str, pattern_info: Dict[str, Any]) -> bool:
        """
        Check if origin matches a specific pattern

        Args:
            origin: Origin to check
            pattern_info: Compiled pattern information

        Returns:
            bool: True if matches, False otherwise
        """
        if pattern_info["type"] == "wildcard":
            return bool(pattern_info["regex"].match(origin))

        elif pattern_info["type"] == "exact":
            # Parse origin for exact comparison
            try:
                origin_parsed = urlparse(origin)
                pattern_parsed = pattern_info["parsed"]

                # Compare scheme, host, and port
                return (
                    origin_parsed.scheme.lower() == pattern_parsed.scheme.lower() and
                    origin_parsed.netloc.lower() == pattern_parsed.netloc.lower()
                )
            except Exception as e:
                logger.debug(f"Error parsing origin '{origin}': {e}")
                return False

        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get validation statistics"""
        return {
            **self._stats,
            "allowed_origins_count": len(self.allowed_origins),
            "strict_mode": self.strict_mode
        }

    def add_allowed_origin(self, origin: str):
        """
        Add a new allowed origin pattern

        Args:
            origin: Origin pattern to add
        """
        if origin not in self.allowed_origins:
            self.allowed_origins.append(origin)
            self._compiled_patterns = self._compile_patterns(self.allowed_origins)
            logger.info(f"Added allowed origin: {origin}")

    def remove_allowed_origin(self, origin: str):
        """
        Remove an allowed origin pattern

        Args:
            origin: Origin pattern to remove
        """
        if origin in self.allowed_origins:
            self.allowed_origins.remove(origin)
            self._compiled_patterns = self._compile_patterns(self.allowed_origins)
            logger.info(f"Removed allowed origin: {origin}")

    def update_allowed_origins(self, origins: List[str]):
        """
        Update the entire list of allowed origins

        Args:
            origins: New list of allowed origin patterns
        """
        self.allowed_origins = origins
        self._compiled_patterns = self._compile_patterns(origins)
        logger.info(f"Updated allowed origins: {len(origins)} patterns")


def validate_websocket_origin(
    websocket: WebSocket,
    allowed_origins: List[str],
    strict_mode: bool = True
) -> bool:
    """
    Convenience function to validate WebSocket origin

    Args:
        websocket: WebSocket connection
        allowed_origins: List of allowed origin patterns
        strict_mode: Whether to reject null origins

    Returns:
        bool: True if origin is valid, False otherwise
    """
    origin = websocket.headers.get("origin")
    validator = OriginValidator(allowed_origins, strict_mode)
    return validator.validate_origin(origin)


def get_websocket_origin_info(websocket: WebSocket) -> Dict[str, Any]:
    """
    Get origin information from WebSocket headers

    Args:
        websocket: WebSocket connection

    Returns:
        Dictionary with origin information
    """
    origin = websocket.headers.get("origin")
    user_agent = websocket.headers.get("user-agent", "")
    host = websocket.headers.get("host", "")

    info = {
        "origin": origin,
        "user_agent": user_agent,
        "host": host,
        "is_browser_request": bool(origin),  # Browsers typically send origin
        "remote_address": getattr(websocket.client, 'host', 'unknown') if websocket.client else 'unknown'
    }

    # Parse origin if present
    if origin:
        try:
            parsed = urlparse(origin)
            info["origin_parsed"] = {
                "scheme": parsed.scheme,
                "hostname": parsed.hostname,
                "port": parsed.port,
                "netloc": parsed.netloc
            }
        except Exception as e:
            logger.debug(f"Error parsing origin '{origin}': {e}")
            info["origin_parse_error"] = str(e)

    return info


def create_origin_rejection_response(origin: Optional[str], reason: str = "Unauthorized origin") -> Dict[str, Any]:
    """
    Create a standardized rejection response for invalid origins

    Args:
        origin: The rejected origin
        reason: Reason for rejection

    Returns:
        Error response dictionary
    """
    return {
        "type": "connection_rejected",
        "error_code": "E403",
        "error_message": reason,
        "details": {
            "rejected_origin": origin,
            "reason": reason,
            "timestamp": __import__("time").time()
        }
    }


# Default configurations for common scenarios

def get_development_origins() -> List[str]:
    """Get common development origins"""
    return [
        "http://localhost:*",
        "https://localhost:*",
        "http://127.0.0.1:*",
        "https://127.0.0.1:*",
        "http://0.0.0.0:*"
    ]


def get_production_origins(domain: str) -> List[str]:
    """
    Get production origins for a domain

    Args:
        domain: Production domain

    Returns:
        List of production origin patterns
    """
    return [
        f"https://{domain}",
        f"https://www.{domain}",
        f"https://*.{domain}"  # Subdomains
    ]


def get_mixed_origins(production_domain: str = None) -> List[str]:
    """
    Get origins for mixed development/production environment

    Args:
        production_domain: Optional production domain

    Returns:
        Combined list of development and production origins
    """
    origins = get_development_origins()

    if production_domain:
        origins.extend(get_production_origins(production_domain))

    return origins