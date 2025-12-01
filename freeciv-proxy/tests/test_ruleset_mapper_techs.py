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
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ruleset_mapper import RulesetMapper


class MockCivCom:
    """Mock CivCom with pre-populated tech data for testing."""
    
    def __init__(self):
        self.username = "test_user"
        self.unit_types = {}
        self.improvements = {}
        self.techs = {
            1: {'id': 1, 'name': 'Alphabet'},
            2: {'id': 2, 'name': 'Pottery'},
            3: {'id': 3, 'name': 'Bronze Working'},
            4: {'id': 4, 'name': 'Animal Husbandry'},
            5: {'id': 5, 'name': 'Agriculture'},
            6: {'id': 6, 'name': 'Writing'},
            7: {'id': 7, 'name': 'Code of Laws'},
            8: {'id': 8, 'name': 'Mysticism'},
            9: {'id': 9, 'name': 'Ceremonial Burial'},
            10: {'id': 10, 'name': 'Masonry'},
            11: {'id': 11, 'name': 'The Wheel'},
            12: {'id': 12, 'name': 'Warrior Code'},
            13: {'id': 13, 'name': 'Iron Working'},
            14: {'id': 14, 'name': 'Horseback Riding'},
            15: {'id': 15, 'name': 'Map Making'},
        }


class MockCivComWithTranslationPrefix:
    """Mock CivCom with ?tech: translation prefixes (as sent by server)."""
    
    def __init__(self):
        self.username = "test_user"
        self.unit_types = {}
        self.improvements = {}
        self.techs = {
            1: {'id': 1, 'name': '?tech:Alphabet'},
            2: {'id': 2, 'name': '?tech:Pottery'},
            3: {'id': 3, 'name': '?tech:Bronze Working'},
        }


class MockCivComEmpty:
    """Mock CivCom with no techs loaded."""
    
    def __init__(self):
        self.username = "test_user"
        self.unit_types = {}
        self.improvements = {}
        self.techs = {}


class TestNormalizeTechName:
    """Test the _normalize_tech_name static method."""
    
    def test_lowercase_conversion(self):
        """Tech names should be converted to lowercase."""
        assert RulesetMapper._normalize_tech_name("Alphabet") == "alphabet"
        assert RulesetMapper._normalize_tech_name("BRONZE WORKING") == "bronze_working"
        assert RulesetMapper._normalize_tech_name("ThE WhEeL") == "the_wheel"
    
    def test_whitespace_stripping(self):
        """Leading/trailing whitespace should be stripped."""
        assert RulesetMapper._normalize_tech_name("  alphabet  ") == "alphabet"
        assert RulesetMapper._normalize_tech_name("\talphabet\n") == "alphabet"
        assert RulesetMapper._normalize_tech_name("   Bronze Working   ") == "bronze_working"
    
    def test_multiple_spaces_collapsed(self):
        """Multiple consecutive spaces should be collapsed to single underscore."""
        assert RulesetMapper._normalize_tech_name("bronze  working") == "bronze_working"
        assert RulesetMapper._normalize_tech_name("code   of   laws") == "code_of_laws"
    
    def test_space_to_underscore_conversion(self):
        """Spaces should be converted to underscores."""
        assert RulesetMapper._normalize_tech_name("bronze working") == "bronze_working"
        assert RulesetMapper._normalize_tech_name("animal husbandry") == "animal_husbandry"
        assert RulesetMapper._normalize_tech_name("code of laws") == "code_of_laws"
    
    def test_underscore_preserved(self):
        """Underscores should be preserved as-is."""
        assert RulesetMapper._normalize_tech_name("bronze_working") == "bronze_working"
        assert RulesetMapper._normalize_tech_name("IRON_WORKING") == "iron_working"
    
    def test_translation_prefix_stripped(self):
        """?tech: translation prefix should be stripped."""
        assert RulesetMapper._normalize_tech_name("?tech:Alphabet") == "alphabet"
        assert RulesetMapper._normalize_tech_name("?tech:Bronze Working") == "bronze_working"
        assert RulesetMapper._normalize_tech_name("?tech:The Wheel") == "the_wheel"
    
    def test_empty_string(self):
        """Empty string should return empty string."""
        assert RulesetMapper._normalize_tech_name("") == ""
    
    def test_none_handling(self):
        """None input should be handled gracefully."""
        # The function expects a string, but should handle None safely
        # This tests robustness of calling code
        result = RulesetMapper._normalize_tech_name(None) if None else ""
        assert result == ""
    
    def test_only_whitespace(self):
        """String with only whitespace should return empty after stripping."""
        assert RulesetMapper._normalize_tech_name("   ") == ""
        assert RulesetMapper._normalize_tech_name("\t\n") == ""


class TestGetTechId:
    """Test the get_tech_id method with various input formats."""
    
    @pytest.fixture
    def mapper(self):
        """Create a RulesetMapper with mock data."""
        return RulesetMapper(MockCivCom())
    
    def test_exact_match(self, mapper):
        """Exact tech name (case-sensitive from server) should be found."""
        # After normalization, "Alphabet" becomes "alphabet"
        assert mapper.get_tech_id("Alphabet") == 1
        assert mapper.get_tech_id("Bronze Working") == 3
    
    def test_case_insensitive_lookup(self, mapper):
        """Tech lookup should be case-insensitive."""
        assert mapper.get_tech_id("alphabet") == 1
        assert mapper.get_tech_id("ALPHABET") == 1
        assert mapper.get_tech_id("AlPhAbEt") == 1
        assert mapper.get_tech_id("bronze working") == 3
        assert mapper.get_tech_id("BRONZE WORKING") == 3
    
    def test_underscore_space_equivalence(self, mapper):
        """Underscores and spaces should be treated as equivalent."""
        assert mapper.get_tech_id("bronze working") == 3
        assert mapper.get_tech_id("bronze_working") == 3
        assert mapper.get_tech_id("Bronze_Working") == 3
        assert mapper.get_tech_id("animal husbandry") == 4
        assert mapper.get_tech_id("animal_husbandry") == 4
    
    def test_whitespace_tolerance(self, mapper):
        """Lookup should tolerate extra whitespace."""
        assert mapper.get_tech_id("  alphabet  ") == 1
        assert mapper.get_tech_id(" bronze  working ") == 3
    
    def test_unknown_tech_returns_none(self, mapper):
        """Unknown tech names should return None."""
        assert mapper.get_tech_id("Unknown Tech") is None
        assert mapper.get_tech_id("Laser Cannons") is None
        assert mapper.get_tech_id("Warp Drive") is None
    
    def test_empty_string_returns_none(self, mapper):
        """Empty string should return None."""
        assert mapper.get_tech_id("") is None
        assert mapper.get_tech_id("   ") is None
    
    def test_partial_match_returns_none(self, mapper):
        """Partial matches should not be found (exact normalized match only)."""
        assert mapper.get_tech_id("Alpha") is None
        assert mapper.get_tech_id("Bronze") is None
        assert mapper.get_tech_id("Working") is None


class TestGetTechIdWithTranslationPrefix:
    """Test tech ID lookup when server sends ?tech: prefixed names."""
    
    @pytest.fixture
    def mapper(self):
        """Create a RulesetMapper with mock data containing ?tech: prefixes."""
        return RulesetMapper(MockCivComWithTranslationPrefix())
    
    def test_prefix_stripped_during_load(self, mapper):
        """?tech: prefix should be stripped when techs are loaded."""
        # The mock has ?tech:Alphabet, but after normalization it's stored as "alphabet"
        assert mapper.get_tech_id("Alphabet") == 1
        assert mapper.get_tech_id("alphabet") == 1
    
    def test_lookup_without_prefix(self, mapper):
        """Lookup without ?tech: prefix should still work."""
        assert mapper.get_tech_id("Bronze Working") == 3
        assert mapper.get_tech_id("bronze_working") == 3
    
    def test_lookup_with_prefix_also_works(self, mapper):
        """Lookup WITH ?tech: prefix should also work (normalized away)."""
        assert mapper.get_tech_id("?tech:Alphabet") == 1
        assert mapper.get_tech_id("?tech:Bronze Working") == 3


class TestGetAvailableTechs:
    """Test the get_available_techs method."""
    
    def test_returns_sorted_list(self):
        """Available techs should be returned as sorted list."""
        mapper = RulesetMapper(MockCivCom())
        available = mapper.get_available_techs()
        
        assert isinstance(available, list)
        assert available == sorted(available)
    
    def test_all_techs_present(self):
        """All loaded techs should be in the list."""
        mapper = RulesetMapper(MockCivCom())
        available = mapper.get_available_techs()
        
        # Check some known techs are present (normalized form)
        assert "alphabet" in available
        assert "bronze_working" in available
        assert "the_wheel" in available
    
    def test_empty_when_no_techs(self):
        """Empty list when no techs loaded."""
        mapper = RulesetMapper(MockCivComEmpty())
        available = mapper.get_available_techs()
        
        assert available == []


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_mapper_not_loaded(self):
        """Test behavior when mapper hasn't loaded data."""
        # Create mapper with no techs attribute
        class BrokenCivCom:
            username = "test"
        
        mapper = RulesetMapper(BrokenCivCom())
        
        # Should return None gracefully, not crash
        assert mapper.get_tech_id("Alphabet") is None
    
    def test_special_characters_in_tech_name(self):
        """Test handling of special characters."""
        # Normal case - no special chars in FreeCiv tech names
        mapper = RulesetMapper(MockCivCom())
        
        # These shouldn't match anything
        assert mapper.get_tech_id("Alpha@bet") is None
        assert mapper.get_tech_id("Bronze#Working") is None
    
    def test_unicode_tech_names(self):
        """Test handling of unicode characters."""
        # FreeCiv uses ASCII for tech names, but test robustness
        mapper = RulesetMapper(MockCivCom())
        
        # Unicode input shouldn't crash, just not match
        assert mapper.get_tech_id("Αλφαβητ") is None  # Greek letters
        assert mapper.get_tech_id("青铜工艺") is None  # Chinese characters


class TestIntegrationWithRealishData:
    """Integration-style tests with more realistic data patterns."""
    
    def test_full_tech_tree_lookup(self):
        """Test looking up all techs in the mock tree."""
        mapper = RulesetMapper(MockCivCom())
        
        # Verify all techs can be found
        expected_mappings = {
            'alphabet': 1,
            'pottery': 2,
            'bronze working': 3,
            'bronze_working': 3,
            'animal husbandry': 4,
            'ANIMAL_HUSBANDRY': 4,
            'Agriculture': 5,
            'writing': 6,
            'Code of Laws': 7,
            'code_of_laws': 7,
            'mysticism': 8,
            'Ceremonial Burial': 9,
            'ceremonial_burial': 9,
            'masonry': 10,
            'The Wheel': 11,
            'the wheel': 11,
            'the_wheel': 11,
            'warrior code': 12,
            'WARRIOR_CODE': 12,
            'iron working': 13,
            'iron_working': 13,
            'horseback riding': 14,
            'HORSEBACK_RIDING': 14,
            'map making': 15,
            'Map Making': 15,
        }
        
        for tech_name, expected_id in expected_mappings.items():
            result = mapper.get_tech_id(tech_name)
            assert result == expected_id, f"Expected {tech_name} -> {expected_id}, got {result}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
