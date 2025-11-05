#!/usr/bin/env python3
"""
Ruleset Mapper - Maps production names to FreeCiv IDs

This module provides functionality to map human-readable production names
(e.g., "Warriors", "Barracks") to FreeCiv's internal (kind, value) tuples
required by PACKET_CITY_CHANGE.

Reads RULESET packets stored in civcom.py during game initialization:
- Unit types (PACKET_RULESET_UNIT, pid=140) → civcom.unit_types
- Buildings (PACKET_RULESET_BUILDING, pid=150) → civcom.improvements

Mirrors FreeCiv web client architecture where RULESET packets are stored
directly in connection objects, ensuring compatibility with all rulesets.
"""

import logging
from typing import Optional, Dict, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from civcom import CivCom

logger = logging.getLogger("freeciv-proxy")

# VUT (value universals type) constants from fc_types.js
# These define what "kind" of production is being requested
VUT_IMPROVEMENT = 3  # Buildings (Barracks, Granary, Temple, etc.)
VUT_UTYPE = 6        # Units (Warriors, Settlers, Phalanx, etc.)


class RulesetMapper:
    """
    Maps production names to (kind, value) tuples for PACKET_CITY_CHANGE.

    This class reads RULESET packets from civcom and builds case-insensitive
    name→ID mappings for both units and buildings.

    Example:
        mapper = RulesetMapper(civcom)
        kind, value = mapper.map_production_to_kind_value("Warriors")
        # Returns: (6, 3)  where 6=VUT_UTYPE, 3=Warriors unit_type_id
    """

    def __init__(self, civcom: 'CivCom'):
        """
        Initialize mapper for a specific civcom connection.

        Args:
            civcom: CivCom instance containing RULESET packets in unit_types and improvements
        """
        self.civcom = civcom
        self.unit_types: Dict[str, int] = {}      # {name_lower: unit_type_id}
        self.buildings: Dict[str, int] = {}       # {name_lower: building_id}
        self._loaded = False
        self._load_mappings()

    def _load_mappings(self):
        """
        Load unit and building mappings from civcom RULESET storage.

        Reads PACKET_RULESET_UNIT (140) and PACKET_RULESET_BUILDING (150)
        packets stored in civcom.unit_types and civcom.improvements.

        This method is called automatically during __init__.
        """
        # Check if civcom has RULESET packets loaded
        if not hasattr(self.civcom, 'unit_types') or not hasattr(self.civcom, 'improvements'):
            logger.warning(f"CivCom instance for {self.civcom.username} does not have RULESET storage. "
                          "Production mapping will not work until RULESET packets are received.")
            return

        # Build unit_types mapping from civcom.unit_types
        # civcom.unit_types is {unit_type_id: {id, name, ...}}
        for unit_id, packet in self.civcom.unit_types.items():
            try:
                name = packet.get('name', '')
                if name and unit_id is not None:
                    # Store lowercase for case-insensitive lookup
                    self.unit_types[name.lower()] = unit_id
                    logger.debug(f"Mapped unit: '{name}' -> unit_type_id {unit_id}")
            except (KeyError, TypeError, AttributeError) as e:
                logger.debug(f"Skipping invalid unit packet (id={unit_id}): {e}")

        # Build buildings mapping from civcom.improvements
        # civcom.improvements is {building_id: {id, name, ...}}
        for building_id, packet in self.civcom.improvements.items():
            try:
                name = packet.get('name', '')
                if name and building_id is not None:
                    # Store lowercase for case-insensitive lookup
                    self.buildings[name.lower()] = building_id
                    logger.debug(f"Mapped building: '{name}' -> building_id {building_id}")
            except (KeyError, TypeError, AttributeError) as e:
                logger.debug(f"Skipping invalid building packet (id={building_id}): {e}")

        self._loaded = True
        logger.info(f"RulesetMapper initialized for {self.civcom.username}: "
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
