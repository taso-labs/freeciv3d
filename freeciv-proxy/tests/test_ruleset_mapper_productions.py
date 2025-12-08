#!/usr/bin/env python3
"""
Unit tests for RulesetMapper production name mapping.

Tests cover:
- Unit type mapping (VUT_UTYPE)
- Building mapping (VUT_IMPROVEMENT)
- Case insensitivity for production names
- Whitespace handling for production names
- Error handling for unknown productions
- Available productions API
- Initialization and loading behavior
"""

from unittest.mock import Mock

import pytest
from ruleset_mapper import VUT_IMPROVEMENT, VUT_UTYPE, RulesetMapper


# Create a proper mock that matches the CivCom interface
def create_mock_civcom_with_data(unit_types=None, improvements=None, techs=None):
    """Create a mock CivCom instance with the specified data."""
    mock = Mock()
    mock.username = "test_user"
    mock.unit_types = unit_types or {}
    mock.improvements = improvements or {}
    mock.techs = techs or {}
    return mock


class TestMapProductionToKindValue:
    """Test the map_production_to_kind_value method."""

    @pytest.fixture
    def mapper(self):
        """Create a RulesetMapper with mock data."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={
                1: {"id": 1, "name": "Warriors"},
                2: {"id": 2, "name": "Settlers"},
                3: {"id": 3, "name": "Archers"},
                4: {"id": 4, "name": "Cavalry"},
            },
            improvements={
                1: {"id": 1, "name": "Barracks"},
                2: {"id": 2, "name": "Granary"},
                3: {"id": 3, "name": "Temple"},
                4: {"id": 4, "name": "Library"},
            },
            techs={
                1: {"id": 1, "name": "Alphabet"},
                2: {"id": 2, "name": "Bronze Working"},
            },
        )
        return RulesetMapper(mock_civcom)

    def test_unit_mapping_returns_correct_kind_and_value(self, mapper: RulesetMapper):
        """Unit names should map to VUT_UTYPE with correct unit_type_id."""
        kind, value = mapper.map_production_to_kind_value("Warriors")
        assert kind == VUT_UTYPE
        assert value == 1

        kind, value = mapper.map_production_to_kind_value("settlers")
        assert kind == VUT_UTYPE
        assert value == 2

    def test_building_mapping_returns_correct_kind_and_value(
        self, mapper: RulesetMapper
    ):
        """Building names should map to VUT_IMPROVEMENT with correct building_id."""
        kind, value = mapper.map_production_to_kind_value("Barracks")
        assert kind == VUT_IMPROVEMENT
        assert value == 1

        kind, value = mapper.map_production_to_kind_value("granary")
        assert kind == VUT_IMPROVEMENT
        assert value == 2

    def test_case_insensitive_lookup(self, mapper: RulesetMapper):
        """Production lookup should be case-insensitive."""
        kind, value = mapper.map_production_to_kind_value("WARRIORS")
        assert kind == VUT_UTYPE
        assert value == 1

        kind, value = mapper.map_production_to_kind_value("barracks")
        assert kind == VUT_IMPROVEMENT
        assert value == 1

    def test_whitespace_tolerance(self, mapper: RulesetMapper):
        """Lookup should tolerate extra whitespace."""
        kind, value = mapper.map_production_to_kind_value("  Warriors  ")
        assert kind == VUT_UTYPE
        assert value == 1

        kind, value = mapper.map_production_to_kind_value("   barracks   ")
        assert kind == VUT_IMPROVEMENT
        assert value == 1

    def test_unknown_production_returns_none(self, mapper: RulesetMapper):
        """Unknown production names should return (None, None)."""
        kind, value = mapper.map_production_to_kind_value("UnknownUnit")
        assert kind is None
        assert value is None

        kind, value = mapper.map_production_to_kind_value("UnknownBuilding")
        assert kind is None
        assert value is None

    def test_empty_string_returns_none(self, mapper: RulesetMapper):
        """Empty string should return (None, None)."""
        kind, value = mapper.map_production_to_kind_value("")
        assert kind is None
        assert value is None


class TestGetAvailableProductions:
    """Test the get_available_productions method."""

    def test_returns_correct_structure(self):
        """Available productions should be returned as dict with 'units' and 'buildings' keys."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={
                1: {"id": 1, "name": "Warriors"},
                2: {"id": 2, "name": "Settlers"},
                3: {"id": 3, "name": "Archers"},
                4: {"id": 4, "name": "Cavalry"},
            },
            improvements={
                1: {"id": 1, "name": "Barracks"},
                2: {"id": 2, "name": "Granary"},
                3: {"id": 3, "name": "Temple"},
                4: {"id": 4, "name": "Library"},
            },
            techs={
                1: {"id": 1, "name": "Alphabet"},
                2: {"id": 2, "name": "Bronze Working"},
            },
        )
        mapper = RulesetMapper(mock_civcom)
        available = mapper.get_available_productions()

        assert isinstance(available, dict)
        assert "units" in available
        assert "buildings" in available
        assert isinstance(available["units"], list)
        assert isinstance(available["buildings"], list)

    def test_units_and_buildings_lists_are_sorted(self):
        """Available units and buildings should be returned as sorted lists."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={
                1: {"id": 1, "name": "Warriors"},
                2: {"id": 2, "name": "Settlers"},
                3: {"id": 3, "name": "Archers"},
                4: {"id": 4, "name": "Cavalry"},
            },
            improvements={
                1: {"id": 1, "name": "Barracks"},
                2: {"id": 2, "name": "Granary"},
                3: {"id": 3, "name": "Temple"},
                4: {"id": 4, "name": "Library"},
            },
            techs={
                1: {"id": 1, "name": "Alphabet"},
                2: {"id": 2, "name": "Bronze Working"},
            },
        )
        mapper = RulesetMapper(mock_civcom)
        available = mapper.get_available_productions()

        assert available["units"] == sorted(available["units"])
        assert available["buildings"] == sorted(available["buildings"])

    def test_all_units_present(self):
        """All loaded units should be in the units list."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={
                1: {"id": 1, "name": "Warriors"},
                2: {"id": 2, "name": "Settlers"},
                3: {"id": 3, "name": "Archers"},
                4: {"id": 4, "name": "Cavalry"},
            },
            improvements={
                1: {"id": 1, "name": "Barracks"},
                2: {"id": 2, "name": "Granary"},
                3: {"id": 3, "name": "Temple"},
                4: {"id": 4, "name": "Library"},
            },
            techs={
                1: {"id": 1, "name": "Alphabet"},
                2: {"id": 2, "name": "Bronze Working"},
            },
        )
        mapper = RulesetMapper(mock_civcom)
        available = mapper.get_available_productions()

        assert "warriors" in available["units"]
        assert "settlers" in available["units"]
        assert "archers" in available["units"]
        assert "cavalry" in available["units"]

    def test_all_buildings_present(self):
        """All loaded buildings should be in the buildings list."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={
                1: {"id": 1, "name": "Warriors"},
                2: {"id": 2, "name": "Settlers"},
                3: {"id": 3, "name": "Archers"},
                4: {"id": 4, "name": "Cavalry"},
            },
            improvements={
                1: {"id": 1, "name": "Barracks"},
                2: {"id": 2, "name": "Granary"},
                3: {"id": 3, "name": "Temple"},
                4: {"id": 4, "name": "Library"},
            },
            techs={
                1: {"id": 1, "name": "Alphabet"},
                2: {"id": 2, "name": "Bronze Working"},
            },
        )
        mapper = RulesetMapper(mock_civcom)
        available = mapper.get_available_productions()

        assert "barracks" in available["buildings"]
        assert "granary" in available["buildings"]
        assert "temple" in available["buildings"]
        assert "library" in available["buildings"]

    def test_empty_when_no_data(self):
        """Empty lists when no units or buildings loaded."""
        mock_civcom = create_mock_civcom_with_data()
        mapper = RulesetMapper(mock_civcom)
        available = mapper.get_available_productions()

        assert available["units"] == []
        assert available["buildings"] == []


class TestInitializationAndLoading:
    """Test initialization and loading behavior."""

    def test_mapper_initializes_with_proper_data(self):
        """Mapper should initialize correctly with unit and building data."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={
                1: {"id": 1, "name": "Warriors"},
                2: {"id": 2, "name": "Settlers"},
                3: {"id": 3, "name": "Archers"},
                4: {"id": 4, "name": "Cavalry"},
            },
            improvements={
                1: {"id": 1, "name": "Barracks"},
                2: {"id": 2, "name": "Granary"},
                3: {"id": 3, "name": "Temple"},
                4: {"id": 4, "name": "Library"},
            },
            techs={
                1: {"id": 1, "name": "Alphabet"},
                2: {"id": 2, "name": "Bronze Working"},
            },
        )
        mapper = RulesetMapper(mock_civcom)

        # Check that mappings were loaded
        assert len(mapper.unit_types) == 4
        assert len(mapper.buildings) == 4
        assert len(mapper.techs) == 2

    def test_mapper_handles_missing_data_gracefully(self):
        """Mapper should handle missing data gracefully."""
        mock_civcom = create_mock_civcom_with_data()
        mapper = RulesetMapper(mock_civcom)

        # Should not crash, but mappings should be empty
        assert len(mapper.unit_types) == 0
        assert len(mapper.buildings) == 0
        assert len(mapper.techs) == 0

    def test_mapper_handles_only_units(self):
        """Mapper should handle case with only units."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={
                1: {"id": 1, "name": "Warriors"},
                2: {"id": 2, "name": "Settlers"},
            },
            improvements={},
            techs={
                1: {"id": 1, "name": "Alphabet"},
            },
        )
        mapper = RulesetMapper(mock_civcom)

        assert len(mapper.unit_types) == 2
        assert len(mapper.buildings) == 0
        assert len(mapper.techs) == 1

    def test_mapper_handles_only_buildings(self):
        """Mapper should handle case with only buildings."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={},
            improvements={
                1: {"id": 1, "name": "Barracks"},
                2: {"id": 2, "name": "Granary"},
            },
            techs={
                1: {"id": 1, "name": "Alphabet"},
            },
        )
        mapper = RulesetMapper(mock_civcom)

        assert len(mapper.unit_types) == 0
        assert len(mapper.buildings) == 2
        assert len(mapper.techs) == 1


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_mapper_with_invalid_unit_data(self):
        """Mapper should handle invalid unit data gracefully."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={
                1: {"id": 1},  # Missing 'name' key
                2: {"name": "Warriors"},  # Missing 'id' key
            },
            improvements={},
            techs={},
        )
        mapper = RulesetMapper(mock_civcom)
        # Should not crash, but mappings should be empty or partial
        assert (
            len(mapper.unit_types) >= 0
        )  # Could be 0 or 1 depending on error handling

    def test_mapper_with_invalid_building_data(self):
        """Mapper should handle invalid building data gracefully."""
        mock_civcom = create_mock_civcom_with_data(
            unit_types={},
            improvements={
                1: {"id": 1},  # Missing 'name' key
                2: {"name": "Barracks"},  # Missing 'id' key
            },
            techs={},
        )
        mapper = RulesetMapper(mock_civcom)
        # Should not crash, but mappings should be empty or partial
        assert len(mapper.buildings) >= 0  # Could be 0 or 1 depending on error handling


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
