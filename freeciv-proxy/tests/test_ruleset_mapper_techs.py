#!/usr/bin/env python3
"""
Unit tests for RulesetMapper tech name normalization and mapping.

Tests cover:
- Case insensitivity: "Alphabet" == "alphabet" == "ALPHABET"
- Whitespace handling: " alphabet ", "bronze  working"
- Underscore/space equivalence: "bronze_working" == "bronze working"
- ?tech: prefix stripping during storage
- Unknown tech names returning None
- Empty/None input handling
"""

import pytest
import unittest
from unittest.mock import MagicMock
from ruleset_mapper import RulesetMapper


def run_normalize_tech_name(tc: unittest.TestCase, cases: dict[str, str]):
    """Helper to run multiple normalization test cases."""
    for input_name, expected in cases.items():
        tc.assertEqual(RulesetMapper.normalize_tech_name(input_name), expected)


class TestNormalizeTechName(unittest.TestCase):
    """Test the _normalize_tech_name static method."""

    def test_lowercase_conversion(self):
        """Tech names should be converted to lowercase."""
        test_cases = {
            "Alphabet": "alphabet",
            "BRONZE WORKING": "bronze_working",
            "ThE WhEeL": "the_wheel",
        }
        run_normalize_tech_name(self, test_cases)

    def test_whitespace_stripping(self):
        """Leading/trailing whitespace should be stripped."""
        test_cases = {
            "  alphabet  ": "alphabet",
            "\talphabet\n": "alphabet",
            "   Bronze Working   ": "bronze_working",
        }
        run_normalize_tech_name(self, test_cases)

    def test_multiple_spaces_collapsed(self):
        """Multiple consecutive spaces should be collapsed to single underscore."""
        test_cases = {
            "bronze  working": "bronze_working",
            "code   of   laws": "code_of_laws",
        }
        run_normalize_tech_name(self, test_cases)

    def test_space_to_underscore_conversion(self):
        """Spaces should be converted to underscores."""
        test_cases = {
            "bronze working": "bronze_working",
            "animal husbandry": "animal_husbandry",
            "code of laws": "code_of_laws",
        }
        run_normalize_tech_name(self, test_cases)

    def test_underscore_preserved(self):
        """Underscores should be preserved as-is."""
        test_cases = {
            "bronze_working": "bronze_working",
            "IRON_WORKING": "iron_working",
        }
        run_normalize_tech_name(self, test_cases)

    def test_translation_prefix_stripped(self):
        """?tech: translation prefix should be stripped."""
        test_cases = {
            "?tech:Alphabet": "alphabet",
            "?tech:Bronze Working": "bronze_working",
            "?tech:The Wheel": "the_wheel",
        }
        run_normalize_tech_name(self, test_cases)

    def test_empty_string(self):
        """Empty string should return empty string."""
        self.assertEqual(RulesetMapper.normalize_tech_name(""), "")

    def test_none_handling(self):
        """None input should be handled gracefully."""
        # The function expects a string, but should handle None safely
        # This tests robustness of calling code
        result = RulesetMapper.normalize_tech_name(None)
        self.assertEqual(result, "")

    def test_only_whitespace(self):
        """String with only whitespace should return empty after stripping."""
        test_cases = {
            "   ": "",
            "\t\n": "",
        }
        run_normalize_tech_name(self, test_cases)


class TestGetTechId(unittest.TestCase):
    """Test the get_tech_id method with various input formats."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock CivCom object with tech data
        self.mock_civcom = MagicMock()
        self.mock_civcom.username = "test_user"
        self.mock_civcom.unit_types = {}
        self.mock_civcom.improvements = {}
        self.mock_civcom.techs = {
            1: {"id": 1, "name": "Alphabet"},
            2: {"id": 2, "name": "Pottery"},
            3: {"id": 3, "name": "Bronze Working"},
            4: {"id": 4, "name": "Animal Husbandry"},
            5: {"id": 5, "name": "Agriculture"},
            6: {"id": 6, "name": "Writing"},
            7: {"id": 7, "name": "Code of Laws"},
            8: {"id": 8, "name": "Mysticism"},
            9: {"id": 9, "name": "Ceremonial Burial"},
            10: {"id": 10, "name": "Masonry"},
            11: {"id": 11, "name": "The Wheel"},
            12: {"id": 12, "name": "Warrior Code"},
            13: {"id": 13, "name": "Iron Working"},
            14: {"id": 14, "name": "Horseback Riding"},
            15: {"id": 15, "name": "Map Making"},
        }
        self.mapper = RulesetMapper(self.mock_civcom)

    def test_exact_match(self):
        """Exact tech name (case-sensitive from server) should be found."""
        # After normalization, "Alphabet" becomes "alphabet"
        self.assertEqual(self.mapper.get_tech_id("Alphabet"), 1)
        self.assertEqual(self.mapper.get_tech_id("Bronze Working"), 3)

    def test_case_insensitive_lookup(self):
        """Tech lookup should be case-insensitive."""
        self.assertEqual(self.mapper.get_tech_id("alphabet"), 1)
        self.assertEqual(self.mapper.get_tech_id("ALPHABET"), 1)
        self.assertEqual(self.mapper.get_tech_id("AlPhAbEt"), 1)
        self.assertEqual(self.mapper.get_tech_id("bronze working"), 3)
        self.assertEqual(self.mapper.get_tech_id("BRONZE WORKING"), 3)

    def test_underscore_space_equivalence(self):
        """Underscores and spaces should be treated as equivalent."""
        self.assertEqual(self.mapper.get_tech_id("bronze working"), 3)
        self.assertEqual(self.mapper.get_tech_id("bronze_working"), 3)
        self.assertEqual(self.mapper.get_tech_id("Bronze_Working"), 3)
        self.assertEqual(self.mapper.get_tech_id("animal husbandry"), 4)
        self.assertEqual(self.mapper.get_tech_id("animal_husbandry"), 4)

    def test_whitespace_tolerance(self):
        """Lookup should tolerate extra whitespace."""
        self.assertEqual(self.mapper.get_tech_id("  alphabet  "), 1)
        self.assertEqual(self.mapper.get_tech_id(" bronze  working "), 3)

    def test_unknown_tech_returns_none(self):
        """Unknown tech names should return None."""
        self.assertIsNone(self.mapper.get_tech_id("Unknown Tech"))
        self.assertIsNone(self.mapper.get_tech_id("Laser Cannons"))
        self.assertIsNone(self.mapper.get_tech_id("Warp Drive"))

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        self.assertIsNone(self.mapper.get_tech_id(""))
        self.assertIsNone(self.mapper.get_tech_id("   "))

    def test_partial_match_returns_none(self):
        """Partial matches should not be found (exact normalized match only)."""
        self.assertIsNone(self.mapper.get_tech_id("Alpha"))
        self.assertIsNone(self.mapper.get_tech_id("Bronze"))
        self.assertIsNone(self.mapper.get_tech_id("Working"))


class TestGetTechIdWithTranslationPrefix(unittest.TestCase):
    """Test tech ID lookup when server sends ?tech: prefixed names."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock CivCom object with tech data containing ?tech: prefixes
        self.mock_civcom = MagicMock()
        self.mock_civcom.username = "test_user"
        self.mock_civcom.unit_types = {}
        self.mock_civcom.improvements = {}
        self.mock_civcom.techs = {
            1: {"id": 1, "name": "?tech:Alphabet"},
            2: {"id": 2, "name": "?tech:Pottery"},
            3: {"id": 3, "name": "?tech:Bronze Working"},
        }
        self.mapper = RulesetMapper(self.mock_civcom)

    def test_prefix_stripped_during_load(self):
        """?tech: prefix should be stripped when techs are loaded."""
        # The mock has ?tech:Alphabet, but after normalization it's stored as "alphabet"
        self.assertEqual(self.mapper.get_tech_id("Alphabet"), 1)
        self.assertEqual(self.mapper.get_tech_id("alphabet"), 1)

    def test_lookup_without_prefix(self):
        """Lookup without ?tech: prefix should still work."""
        self.assertEqual(self.mapper.get_tech_id("Bronze Working"), 3)
        self.assertEqual(self.mapper.get_tech_id("bronze_working"), 3)

    def test_lookup_with_prefix_also_works(self):
        """Lookup WITH ?tech: prefix should also work (normalized away)."""
        self.assertEqual(self.mapper.get_tech_id("?tech:Alphabet"), 1)
        self.assertEqual(self.mapper.get_tech_id("?tech:Bronze Working"), 3)


class TestGetAvailableTechs(unittest.TestCase):
    """Test the get_available_techs method."""

    def test_returns_sorted_list(self):
        """Available techs should be returned as sorted list."""
        # Create mock CivCom object with tech data
        mock_civcom = MagicMock()
        mock_civcom.username = "test_user"
        mock_civcom.unit_types = {}
        mock_civcom.improvements = {}
        mock_civcom.techs = {
            1: {"id": 1, "name": "Alphabet"},
            2: {"id": 2, "name": "Pottery"},
            3: {"id": 3, "name": "Bronze Working"},
            4: {"id": 4, "name": "Animal Husbandry"},
            5: {"id": 5, "name": "Agriculture"},
            6: {"id": 6, "name": "Writing"},
            7: {"id": 7, "name": "Code of Laws"},
            8: {"id": 8, "name": "Mysticism"},
            9: {"id": 9, "name": "Ceremonial Burial"},
            10: {"id": 10, "name": "Masonry"},
            11: {"id": 11, "name": "The Wheel"},
            12: {"id": 12, "name": "Warrior Code"},
            13: {"id": 13, "name": "Iron Working"},
            14: {"id": 14, "name": "Horseback Riding"},
            15: {"id": 15, "name": "Map Making"},
        }
        mapper = RulesetMapper(mock_civcom)
        available = mapper.get_available_techs()

        self.assertIsInstance(available, list)
        self.assertEqual(available, sorted(available))

    def test_all_techs_present(self):
        """All loaded techs should be in the list."""
        # Create mock CivCom object with tech data
        mock_civcom = MagicMock()
        mock_civcom.username = "test_user"
        mock_civcom.unit_types = {}
        mock_civcom.improvements = {}
        mock_civcom.techs = {
            1: {"id": 1, "name": "Alphabet"},
            2: {"id": 2, "name": "Pottery"},
            3: {"id": 3, "name": "Bronze Working"},
            4: {"id": 4, "name": "Animal Husbandry"},
            5: {"id": 5, "name": "Agriculture"},
            6: {"id": 6, "name": "Writing"},
            7: {"id": 7, "name": "Code of Laws"},
            8: {"id": 8, "name": "Mysticism"},
            9: {"id": 9, "name": "Ceremonial Burial"},
            10: {"id": 10, "name": "Masonry"},
            11: {"id": 11, "name": "The Wheel"},
            12: {"id": 12, "name": "Warrior Code"},
            13: {"id": 13, "name": "Iron Working"},
            14: {"id": 14, "name": "Horseback Riding"},
            15: {"id": 15, "name": "Map Making"},
        }
        mapper = RulesetMapper(mock_civcom)
        available = mapper.get_available_techs()

        # Check some known techs are present (normalized form)
        self.assertIn("alphabet", available)
        self.assertIn("bronze_working", available)
        self.assertIn("the_wheel", available)

    def test_empty_when_no_techs(self):
        """Empty list when no techs loaded."""
        # Create mock CivCom object with no techs
        mock_civcom = MagicMock()
        mock_civcom.username = "test_user"
        mock_civcom.unit_types = {}
        mock_civcom.improvements = {}
        mock_civcom.techs = {}
        mapper = RulesetMapper(mock_civcom)
        available = mapper.get_available_techs()

        self.assertEqual(available, [])


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_mapper_not_loaded(self):
        """Test behavior when mapper hasn't loaded data."""

        # Create mapper with no techs attribute
        class BrokenCivCom(MagicMock):
            username = "test"

        mapper = RulesetMapper(BrokenCivCom())

        # Should return None gracefully, not crash
        self.assertIsNone(mapper.get_tech_id("Alphabet"))

    def test_special_characters_in_tech_name(self):
        """Test handling of special characters."""
        # Normal case - no special chars in FreeCiv tech names
        # Create mock CivCom object with tech data
        mock_civcom = MagicMock()
        mock_civcom.username = "test_user"
        mock_civcom.unit_types = {}
        mock_civcom.improvements = {}
        mock_civcom.techs = {
            1: {"id": 1, "name": "Alphabet"},
            2: {"id": 2, "name": "Pottery"},
            3: {"id": 3, "name": "Bronze Working"},
            4: {"id": 4, "name": "Animal Husbandry"},
            5: {"id": 5, "name": "Agriculture"},
            6: {"id": 6, "name": "Writing"},
            7: {"id": 7, "name": "Code of Laws"},
            8: {"id": 8, "name": "Mysticism"},
            9: {"id": 9, "name": "Ceremonial Burial"},
            10: {"id": 10, "name": "Masonry"},
            11: {"id": 11, "name": "The Wheel"},
            12: {"id": 12, "name": "Warrior Code"},
            13: {"id": 13, "name": "Iron Working"},
            14: {"id": 14, "name": "Horseback Riding"},
            15: {"id": 15, "name": "Map Making"},
        }
        mapper = RulesetMapper(mock_civcom)

        # These shouldn't match anything
        self.assertIsNone(mapper.get_tech_id("Alpha@bet"))
        self.assertIsNone(mapper.get_tech_id("Bronze#Working"))

    def test_unicode_tech_names(self):
        """Test handling of unicode characters."""
        # FreeCiv uses ASCII for tech names, but test robustness
        # Create mock CivCom object with tech data
        mock_civcom = MagicMock()
        mock_civcom.username = "test_user"
        mock_civcom.unit_types = {}
        mock_civcom.improvements = {}
        mock_civcom.techs = {
            1: {"id": 1, "name": "Alphabet"},
            2: {"id": 2, "name": "Pottery"},
            3: {"id": 3, "name": "Bronze Working"},
            4: {"id": 4, "name": "Animal Husbandry"},
            5: {"id": 5, "name": "Agriculture"},
            6: {"id": 6, "name": "Writing"},
            7: {"id": 7, "name": "Code of Laws"},
            8: {"id": 8, "name": "Mysticism"},
            9: {"id": 9, "name": "Ceremonial Burial"},
            10: {"id": 10, "name": "Masonry"},
            11: {"id": 11, "name": "The Wheel"},
            12: {"id": 12, "name": "Warrior Code"},
            13: {"id": 13, "name": "Iron Working"},
            14: {"id": 14, "name": "Horseback Riding"},
            15: {"id": 15, "name": "Map Making"},
        }
        mapper = RulesetMapper(mock_civcom)

        # Unicode input shouldn't crash, just not match
        self.assertIsNone(mapper.get_tech_id("Αλφαβητ"))  # Greek letters
        self.assertIsNone(mapper.get_tech_id("青铜工艺"))  # Chinese characters


class TestIntegrationWithRealishData(unittest.TestCase):
    """Integration-style tests with more realistic data patterns."""

    def test_full_tech_tree_lookup(self):
        """Test looking up all techs in the mock tree."""
        # Create mock CivCom object with tech data
        mock_civcom = MagicMock()
        mock_civcom.username = "test_user"
        mock_civcom.unit_types = {}
        mock_civcom.improvements = {}
        mock_civcom.techs = {
            1: {"id": 1, "name": "Alphabet"},
            2: {"id": 2, "name": "Pottery"},
            3: {"id": 3, "name": "Bronze Working"},
            4: {"id": 4, "name": "Animal Husbandry"},
            5: {"id": 5, "name": "Agriculture"},
            6: {"id": 6, "name": "Writing"},
            7: {"id": 7, "name": "Code of Laws"},
            8: {"id": 8, "name": "Mysticism"},
            9: {"id": 9, "name": "Ceremonial Burial"},
            10: {"id": 10, "name": "Masonry"},
            11: {"id": 11, "name": "The Wheel"},
            12: {"id": 12, "name": "Warrior Code"},
            13: {"id": 13, "name": "Iron Working"},
            14: {"id": 14, "name": "Horseback Riding"},
            15: {"id": 15, "name": "Map Making"},
        }
        mapper = RulesetMapper(mock_civcom)

        # Verify all techs can be found
        expected_mappings = {
            "alphabet": 1,
            "pottery": 2,
            "bronze working": 3,
            "bronze_working": 3,
            "animal husbandry": 4,
            "ANIMAL_HUSBANDRY": 4,
            "Agriculture": 5,
            "writing": 6,
            "Code of Laws": 7,
            "code_of_laws": 7,
            "mysticism": 8,
            "Ceremonial Burial": 9,
            "ceremonial_burial": 9,
            "masonry": 10,
            "The Wheel": 11,
            "the wheel": 11,
            "the_wheel": 11,
            "warrior code": 12,
            "WARRIOR_CODE": 12,
            "iron working": 13,
            "iron_working": 13,
            "horseback riding": 14,
            "HORSEBACK_RIDING": 14,
            "map making": 15,
            "Map Making": 15,
        }

        for tech_name, expected_id in expected_mappings.items():
            result = mapper.get_tech_id(tech_name)
            self.assertEqual(
                result,
                expected_id,
                f"Expected {tech_name} -> {expected_id}, got {result}",
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
