#!/usr/bin/env python3
"""
Shared coordinate utilities for FreeCiv proxy.

This module provides common constants and functions for handling map coordinates
across the proxy codebase, ensuring consistency between validation and packet
conversion.
"""

from typing import Any, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# Map Dimension Constants
# =============================================================================
# These defaults are used when civcom/game_state is not available.
# The actual map dimensions come from the game server at runtime.
#
# LLM multiplayer games use 64x64 maps (per pubscript_multiplayer.serv)
# for faster 1v1 gameplay. These defaults match that configuration.

DEFAULT_MAP_WIDTH = 64
DEFAULT_MAP_HEIGHT = 64


# =============================================================================
# Coordinate Extraction and Resolution
# =============================================================================

def extract_target_coordinates(action: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """Extract target coordinates from action, supporting multiple formats.

    Supports:
    - Flat format: {'target_x': 10, 'target_y': 20}
    - Nested format: {'target': {'x': 10, 'y': 20}}

    Args:
        action: Action dict to extract coordinates from

    Returns:
        Tuple of (target_x, target_y) or (None, None) if not found
    """
    # Try flat format first
    if 'target_x' in action and 'target_y' in action:
        return action['target_x'], action['target_y']

    # Try nested format (target.x, target.y)
    if 'target' in action and isinstance(action['target'], dict):
        target = action['target']
        if 'x' in target and 'y' in target:
            return target['x'], target['y']

    return None, None


def resolve_target_tile_id(
    action: Dict[str, Any],
    civcom: Optional[Any] = None
) -> int:
    """Resolve target_id (tile index) for actions from various input formats.

    Supports multiple ways to specify the target:
    1. Direct target_id: {'target_id': 123}
    2. Tile ID: {'tile_id': 123}
    3. Flat coordinates: {'target_x': 10, 'target_y': 20}
    4. Nested coordinates: {'target': {'x': 10, 'y': 20}}

    Args:
        action: Action dict containing target specification
        civcom: Optional civcom instance for map dimensions

    Returns:
        Resolved target_id (tile index), or -1 if cannot resolve
    """
    # Priority 1: Direct target_id
    target_id = action.get('target_id')
    if target_id is not None and target_id != -1:
        try:
            tid = int(target_id)
            if tid >= 0:
                return tid
        except (ValueError, TypeError):
            logger.warning(f"Invalid target_id value: {target_id}")

    # Priority 2: tile_id
    tile_id = action.get('tile_id')
    if tile_id is not None and tile_id != -1:
        try:
            tid = int(tile_id)
            if tid >= 0:
                return tid
        except (ValueError, TypeError):
            logger.warning(f"Invalid tile_id value: {tile_id}")

    # Priority 3: Coordinates (flat or nested)
    target_x, target_y = extract_target_coordinates(action)
    if target_x is not None and target_y is not None:
        try:
            x = int(target_x)
            y = int(target_y)

            # Validate bounds - negative coordinates are invalid
            if x < 0 or y < 0:
                logger.warning(f"Negative coordinates rejected: ({x}, {y})")
                return -1

            # Get map width from civcom or use default
            map_width = DEFAULT_MAP_WIDTH
            if civcom and hasattr(civcom, 'map_info') and civcom.map_info:
                map_width = civcom.map_info.get('width', DEFAULT_MAP_WIDTH)

            # Calculate tile index: tile_index = x + y * map_width
            tile_index = x + y * map_width
            logger.debug(f"Resolved coordinates ({x}, {y}) to tile_id {tile_index} (map_width={map_width})")
            return tile_index

        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to convert coordinates to integers: {e}")
            return -1

    return -1
