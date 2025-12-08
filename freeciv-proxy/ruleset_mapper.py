#!/usr/bin/env python3
"""
Ruleset Mapper - Maps production and tech names to FreeCiv IDs

This module provides functionality to map human-readable names
(e.g., "Warriors", "Barracks", "Alphabet") to FreeCiv's internal IDs
required by various packets:
- PACKET_CITY_CHANGE (pid=35) for production
- PACKET_PLAYER_RESEARCH (pid=55) for technology

Reads RULESET packets stored in civcom.py during game initialization:
- Unit types (PACKET_RULESET_UNIT, pid=140) → civcom.unit_types
- Buildings (PACKET_RULESET_BUILDING, pid=150) → civcom.improvements
- Technologies (PACKET_RULESET_TECH, pid=144) → civcom.techs

Mirrors FreeCiv web client architecture where RULESET packets are stored
directly in connection objects, ensuring compatibility with all rulesets.
"""

import logging
import re
from typing import Optional, Dict, Tuple, List, TYPE_CHECKING

if TYPE_CHECKING:
    from civcom import CivCom

logger = logging.getLogger("freeciv-proxy")

# VUT (value universals type) constants from fc_types.js
# These define what "kind" of production is being requested
VUT_IMPROVEMENT = 3  # Buildings (Barracks, Granary, Temple, etc.)
VUT_UTYPE = 6        # Units (Warriors, Settlers, Phalanx, etc.)


class RulesetMapper:
    """
    Maps production and tech names to FreeCiv IDs.

    This class reads RULESET packets from civcom and builds case-insensitive
    name→ID mappings for units, buildings, and technologies.

    Example:
        mapper = RulesetMapper(civcom)
        kind, value = mapper.map_production_to_kind_value("Warriors")
        # Returns: (6, 3)  where 6=VUT_UTYPE, 3=Warriors unit_type_id
        
        tech_id = mapper.get_tech_id("Bronze Working")
        # Returns: 3  (tech ID for Bronze Working)
    """

    def __init__(self, civcom: 'CivCom'):
        """
        Initialize mapper for a specific civcom connection.

        Args:
            civcom: CivCom instance containing RULESET packets in unit_types, improvements, techs
        """
        self.civcom = civcom
        self.unit_types: Dict[str, int] = {}      # {name_lower: unit_type_id}
        self.buildings: Dict[str, int] = {}       # {name_lower: building_id}
        self.techs: Dict[str, int] = {}           # {normalized_name: tech_id}
        self._loaded = False
        self._load_mappings()

    def _load_mappings(self):
        """
        Load unit, building, and tech mappings from civcom RULESET storage.

        Reads PACKET_RULESET_UNIT (140), PACKET_RULESET_BUILDING (150), and
        PACKET_RULESET_TECH (144) packets stored in civcom.

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

        # Build techs mapping from civcom.techs
        # civcom.techs is {tech_id: {id, name, ...}}
        if hasattr(self.civcom, 'techs'):
            for tech_id, packet in self.civcom.techs.items():
                try:
                    name = packet.get('name', '')
                    if name and tech_id is not None:
                        # Normalize name for flexible lookup
                        normalized = self.normalize_tech_name(name)
                        self.techs[normalized] = tech_id
                        logger.debug(f"Mapped tech: '{name}' -> tech_id {tech_id} (normalized: '{normalized}')")
                except (KeyError, TypeError, AttributeError) as e:
                    logger.debug(f"Skipping invalid tech packet (id={tech_id}): {e}")

        self._loaded = True
        logger.info(f"RulesetMapper initialized for {self.civcom.username}: "
                   f"{len(self.unit_types)} unit types, {len(self.buildings)} buildings, "
                   f"{len(self.techs)} technologies")

    @staticmethod
    def normalize_tech_name(name: str | None) -> str:
        """
        Normalize technology name for reliable lookup.

        Handles various input formats LLMs might use:
        - Case insensitivity: "Alphabet" == "alphabet" == "ALPHABET"
        - Whitespace: " alphabet " -> "alphabet"
        - Underscore/space equivalence: "bronze_working" == "bronze working"
        - Multiple spaces: "bronze  working" -> "bronze working"
        - Translation prefix: "?tech:Alphabet" -> "alphabet"

        Args:
            name: Raw technology name from user input or packet

        Returns:
            Normalized string suitable for dictionary lookup

        Examples:
            >>> RulesetMapper._normalize_tech_name("Bronze Working")
            'bronze_working'
            >>> RulesetMapper._normalize_tech_name("  ALPHABET  ")
            'alphabet'
            >>> RulesetMapper._normalize_tech_name("bronze_working")
            'bronze_working'
            >>> RulesetMapper._normalize_tech_name("?tech:The Wheel")
            'the_wheel'
        """
        if not name:
            return ''

        # Strip ?tech: translation prefix (FreeCiv uses this for i18n)
        if name.startswith('?tech:'):
            name = name[6:]

        # Lowercase and strip whitespace
        normalized = name.lower().strip()

        # Normalize whitespace: collapse multiple spaces to single space
        normalized = re.sub(r'\s+', ' ', normalized)

        # Convert spaces to underscores for canonical form
        # This allows "bronze working" to match "bronze_working"
        normalized = normalized.replace(' ', '_')

        return normalized

    def get_tech_id(self, tech_name: str) -> Optional[int]:
        """
        Map technology name to FreeCiv tech ID for PACKET_PLAYER_RESEARCH.

        This method handles various input formats and returns the tech ID
        needed for the research packet.

        Args:
            tech_name: Name of technology (case-insensitive, flexible whitespace)
                      Examples: "Alphabet", "bronze working", "IRON_WORKING"

        Returns:
            int: Tech ID if found
            None: If technology not found or mapper not loaded

        Examples:
            >>> mapper.get_tech_id("Alphabet")
            1
            >>> mapper.get_tech_id("bronze working")
            3
            >>> mapper.get_tech_id("UnknownTech")
            None
        """
        # Ensure we have loaded mappings (lazy load if needed)
        self._ensure_loaded()
        
        if not self._loaded:
            logger.warning("RulesetMapper not loaded. Cannot map tech names. "
                          "Ensure RULESET packets have been received.")
            return None

        if not tech_name:
            return None

        normalized = self.normalize_tech_name(tech_name)
        tech_id = self.techs.get(normalized)

        if tech_id is not None:
            logger.debug(f"Tech '{tech_name}' -> tech_id {tech_id} (normalized: '{normalized}')")
        else:
            logger.debug(f"Tech '{tech_name}' not found (normalized: '{normalized}'). "
                        f"Available: {list(self.techs.keys())[:10]}...")

        return tech_id

    def get_available_techs(self) -> List[str]:
        """
        Get all available technology names for this game.

        Useful for debugging, error messages, and validating research requests.

        Returns:
            list: Sorted list of normalized technology names

        Example:
            >>> available = mapper.get_available_techs()
            >>> print(available[:5])
            ['alphabet', 'animal_husbandry', 'bronze_working', 'ceremonial_burial', 'code_of_laws']
        """
        return sorted(self.techs.keys())

    def _ensure_loaded(self):
        """
        Ensure mappings are loaded from civcom.
        
        Lazily reloads if mappings are empty but civcom has data.
        This handles the case where the mapper was created before
        RULESET packets were received.
        """
        # If we have no unit types but civcom does, reload
        if not self.unit_types and hasattr(self.civcom, 'unit_types') and self.civcom.unit_types:
            logger.info(f"RulesetMapper: Lazy loading - civcom has {len(self.civcom.unit_types)} unit types")
            self._load_mappings()
        # Same for buildings
        if not self.buildings and hasattr(self.civcom, 'improvements') and self.civcom.improvements:
            logger.info(f"RulesetMapper: Lazy loading - civcom has {len(self.civcom.improvements)} improvements")
            self._load_mappings()

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
        # Ensure we have loaded mappings (lazy load if needed)
        self._ensure_loaded()
        
        if not self._loaded:
            logger.error(f"RulesetMapper not loaded. Cannot map production names.")
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
