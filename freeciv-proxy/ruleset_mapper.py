#!/usr/bin/env python3
"""
Ruleset Mapper - Maps production names to FreeCiv IDs

This module provides functionality to map human-readable production names
(e.g., "Warriors", "Barracks") to FreeCiv's internal (kind, value) tuples
required by PACKET_CITY_CHANGE.

Uses cached RULESET packets to build name→ID mappings for:
- Unit types (PACKET_RULESET_UNIT, pid=140)
- Buildings (PACKET_RULESET_BUILDING, pid=150)

The mapping is built from packets cached by ruleset_cache.py during game
initialization, ensuring compatibility with all rulesets (classic, civ2civ3, etc.).
"""

import json
import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger("freeciv-proxy")

# VUT (value universals type) constants from fc_types.js
# These define what "kind" of production is being requested
VUT_IMPROVEMENT = 3  # Buildings (Barracks, Granary, Temple, etc.)
VUT_UTYPE = 6        # Units (Warriors, Settlers, Phalanx, etc.)


class RulesetMapper:
    """
    Maps production names to (kind, value) tuples for PACKET_CITY_CHANGE.

    This class reads cached RULESET packets and builds case-insensitive
    name→ID mappings for both units and buildings.

    Example:
        mapper = RulesetMapper(game_id)
        kind, value = mapper.map_production_to_kind_value("Warriors")
        # Returns: (6, 3)  where 6=VUT_UTYPE, 3=Warriors unit_type_id
    """

    def __init__(self, game_id: str):
        """
        Initialize mapper for a specific game.

        Args:
            game_id: The game identifier used to lookup cached RULESET packets
        """
        self.game_id = game_id
        self.unit_types: Dict[str, int] = {}      # {name_lower: unit_type_id}
        self.buildings: Dict[str, int] = {}       # {name_lower: building_id}
        self._loaded = False
        self._load_mappings()

    def _load_mappings(self):
        """
        Load unit and building mappings from ruleset_cache.

        Reads cached PACKET_RULESET_UNIT (140) and PACKET_RULESET_BUILDING (150)
        packets and extracts name→ID mappings.

        This method is called automatically during __init__.
        """
        # Import here to avoid circular dependency issues
        # ruleset_cache and packet_constants are available after freeciv-proxy startup
        try:
            from ruleset_cache import ruleset_cache
            from packet_constants import PACKET_RULESET_UNIT, PACKET_RULESET_BUILDING
        except ImportError as e:
            logger.error(f"Failed to import dependencies for RulesetMapper: {e}")
            return

        packets = ruleset_cache.get_packets(self.game_id)
        if not packets:
            logger.warning(f"No RULESET cache available for game {self.game_id}. "
                          "Production mapping will not work until RULESET packets are received.")
            return

        # Parse each cached RULESET packet and extract relevant mappings
        for packet_json in packets:
            try:
                packet = json.loads(packet_json)
                pid = packet.get('pid')

                if pid == PACKET_RULESET_UNIT:  # 140
                    # PACKET_RULESET_UNIT contains: {id: <unit_type_id>, name: "Warriors", ...}
                    name = packet.get('name', '')
                    unit_id = packet.get('id')
                    if name and unit_id is not None:
                        # Store lowercase for case-insensitive lookup
                        self.unit_types[name.lower()] = unit_id
                        logger.debug(f"Mapped unit: '{name}' -> unit_type_id {unit_id}")

                elif pid == PACKET_RULESET_BUILDING:  # 150
                    # PACKET_RULESET_BUILDING contains: {id: <building_id>, name: "Barracks", ...}
                    name = packet.get('name', '')
                    building_id = packet.get('id')
                    if name and building_id is not None:
                        # Store lowercase for case-insensitive lookup
                        self.buildings[name.lower()] = building_id
                        logger.debug(f"Mapped building: '{name}' -> building_id {building_id}")

            except (json.JSONDecodeError, KeyError, TypeError) as e:
                # Skip malformed packets without crashing
                logger.debug(f"Skipping invalid RULESET packet: {e}")

        self._loaded = True
        logger.info(f"RulesetMapper initialized for game {self.game_id}: "
                   f"{len(self.unit_types)} unit types, {len(self.buildings)} buildings")

    def map_production_to_kind_value(self, production_name: str) -> Tuple[Optional[int], Optional[int]]:
        """
        Map production name to (kind, value) tuple for PACKET_CITY_CHANGE.

        This is the main API method for converting human-readable production names
        into the (production_kind, production_value) format required by FreeCiv.

        Args:
            production_name: Name of unit or building (case-insensitive)
                            Examples: "Warriors", "settlers", "BARRACKS", "Granary"

        Returns:
            tuple: (production_kind, production_value) where:
                   - For units: (6, unit_type_id)
                   - For buildings: (3, building_id)
                   - On error: (None, None)

        Examples:
            >>> mapper.map_production_to_kind_value("Warriors")
            (6, 3)  # VUT_UTYPE=6, Warriors unit_type_id=3

            >>> mapper.map_production_to_kind_value("barracks")
            (3, 5)  # VUT_IMPROVEMENT=3, Barracks building_id=5

            >>> mapper.map_production_to_kind_value("InvalidName")
            (None, None)  # Unknown production
        """
        if not self._loaded:
            logger.error(f"RulesetMapper not loaded for game {self.game_id}. "
                        "Cannot map production names.")
            return (None, None)

        # Normalize to lowercase and strip whitespace for reliable lookup
        name_lower = production_name.lower().strip()

        # Try units first (more common in early game)
        if name_lower in self.unit_types:
            unit_id = self.unit_types[name_lower]
            logger.debug(f"Production '{production_name}' mapped to unit "
                        f"(kind={VUT_UTYPE}, value={unit_id})")
            return (VUT_UTYPE, unit_id)

        # Try buildings
        if name_lower in self.buildings:
            building_id = self.buildings[name_lower]
            logger.debug(f"Production '{production_name}' mapped to building "
                        f"(kind={VUT_IMPROVEMENT}, value={building_id})")
            return (VUT_IMPROVEMENT, building_id)

        # Not found in either category
        logger.error(f"Unknown production name: '{production_name}'. "
                    f"Not found in {len(self.unit_types)} units or "
                    f"{len(self.buildings)} buildings.")
        return (None, None)

    def get_available_productions(self) -> Dict[str, list]:
        """
        Get all available production names for this game.

        Useful for debugging, error messages, and validating production requests.

        Returns:
            dict: {'units': [sorted unit names], 'buildings': [sorted building names]}

        Example:
            >>> available = mapper.get_available_productions()
            >>> print(available['units'][:5])
            ['archers', 'armor', 'artillery', 'bomber', 'cannon']
            >>> print(available['buildings'][:5])
            ['airport', 'aqueduct', 'bank', 'barracks', 'cathedral']
        """
        return {
            'units': sorted(self.unit_types.keys()),
            'buildings': sorted(self.buildings.keys())
        }
