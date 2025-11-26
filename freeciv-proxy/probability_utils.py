#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Probability Encoding Utilities - Protocol v2.0

Utilities for converting between FreeCiv server probability formats and 
protocol v2.0 half-percentage point encoding (0-200 range).

Protocol encoding:
- 0 = 0% (impossible/blocked)
- 1 = 0.5%
- 100 = 50%
- 175 = 87.5%
- 200 = 100% (guaranteed success)
- 253 = Not yet known (server computing)
- 254 = Unknown (requires server query)
"""

from typing import Optional


def encode_probability(server_value: Optional[int], max_value: int = 200) -> int:
    """
    Convert server probability value to protocol encoding (0-200 half-percentage points).
    
    FreeCiv server typically uses 0-200 range where:
    - 0 = impossible
    - 200 = certain
    
    Args:
        server_value: Raw probability from server (typically 0-200)
        max_value: Maximum value in server scale (default: 200)
        
    Returns:
        Protocol-encoded probability (0-200)
    """
    if server_value is None:
        return 254  # Unknown
    
    if server_value < 0:
        return 0  # Impossible
    
    if server_value >= max_value:
        return 200  # Certain
    
    # Direct mapping if already in 0-200 range
    if max_value == 200:
        return max(0, min(200, server_value))
    
    # Scale to 0-200 range
    normalized = (server_value / max_value) * 200
    return max(0, min(200, int(normalized)))


def encode_probability_from_percent(percent: float) -> int:
    """
    Convert percentage (0.0-100.0) to protocol encoding (0-200 half-points).
    
    Args:
        percent: Probability as percentage (0.0-100.0)
        
    Returns:
        Protocol-encoded probability (0-200)
    """
    if percent <= 0:
        return 0
    if percent >= 100:
        return 200
    
    # Convert to half-percentage points
    return max(0, min(200, int(percent * 2)))


def decode_probability_to_percent(encoded: int) -> float:
    """
    Convert protocol encoding (0-200) to percentage (0.0-100.0).
    
    Args:
        encoded: Protocol-encoded probability (0-200)
        
    Returns:
        Probability as percentage (0.0-100.0)
    """
    if encoded == 253:
        return -1.0  # Special: Not yet known
    if encoded == 254:
        return -1.0  # Special: Unknown
    
    # Clamp to valid range
    encoded = max(0, min(200, encoded))
    
    # Convert half-points to percentage
    return encoded / 2.0


def is_certain(encoded: int) -> bool:
    """Check if action is certain (100% success)."""
    return encoded == 200


def is_impossible(encoded: int) -> bool:
    """Check if action is impossible (0% success)."""
    return encoded == 0


def is_unknown(encoded: int) -> bool:
    """Check if action probability is unknown."""
    return encoded in (253, 254)


def get_probability_label(encoded: int) -> str:
    """
    Get human-readable label for probability.
    
    Args:
        encoded: Protocol-encoded probability
        
    Returns:
        Label like "Certain", "Very High", "Moderate", etc.
    """
    if encoded == 253:
        return "Computing..."
    if encoded == 254:
        return "Unknown"
    if encoded == 200:
        return "Certain"
    if encoded >= 180:
        return "Very High"
    if encoded >= 140:
        return "High"
    if encoded >= 100:
        return "Moderate"
    if encoded >= 40:
        return "Low"
    if encoded > 0:
        return "Very Low"
    return "Impossible"
