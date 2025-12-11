"""
Tests for Action Prerequisite Validation

These tests verify that actions are properly validated for their prerequisites:
- Unit type capability checks fail when ruleset data is missing
- City improvement checks work correctly with bitvectors

These tests focus on the civcom validation logic.
"""

import unittest
import sys
import os
from unittest.mock import Mock
import logging
import secrets

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variable for cache - must be 64+ characters with good entropy
os.environ['CACHE_HMAC_SECRET'] = secrets.token_hex(32)  # 64 character hex string

# Suppress logging during tests
logging.disable(logging.CRITICAL)


class TestRulesetDataValidation(unittest.TestCase):
    """Test that missing ruleset data is treated as invalid state"""

    def test_utype_can_do_action_fails_without_unit_type(self):
        """utype_can_do_action should return False when unit type not in ruleset"""
        from civcom import CivCom
        
        # Create a mock civcom with minimal setup
        civcom = Mock(spec=CivCom)
        civcom.unit_types = {}  # Empty - no ruleset data
        
        # Call the real method implementation
        result = CivCom.utype_can_do_action(civcom, 10, 44)  # ACTION_AIRLIFT
        
        self.assertFalse(result, "Should return False when unit type not found")

    def test_utype_can_do_action_fails_without_utype_actions(self):
        """utype_can_do_action should return False when utype_actions missing"""
        from civcom import CivCom
        
        civcom = Mock(spec=CivCom)
        civcom.unit_types = {
            10: {
                'id': 10,
                'name': 'Fighter',
                # Missing 'utype_actions' field
            }
        }
        
        result = CivCom.utype_can_do_action(civcom, 10, 44)  # ACTION_AIRLIFT
        
        self.assertFalse(result, "Should return False when utype_actions not populated")

    def test_utype_can_do_action_succeeds_with_valid_data(self):
        """utype_can_do_action should return True when action bit is set"""
        from civcom import CivCom
        
        civcom = Mock(spec=CivCom)
        civcom.unit_types = {
            10: {
                'id': 10,
                'name': 'Fighter',
                'utype_actions': [0] * 10
            }
        }
        # Set ACTION_AIRLIFT (44) bit: byte 5, bit 4
        civcom.unit_types[10]['utype_actions'][5] = 1 << 4
        
        result = CivCom.utype_can_do_action(civcom, 10, 44)  # ACTION_AIRLIFT
        
        self.assertTrue(result, "Should return True when action bit is set")

    def test_utype_can_do_action_returns_false_when_bit_not_set(self):
        """utype_can_do_action should return False when action bit is not set"""
        from civcom import CivCom
        
        civcom = Mock(spec=CivCom)
        civcom.unit_types = {
            10: {
                'id': 10,
                'name': 'Worker',
                'utype_actions': [0] * 10  # All bits cleared
            }
        }
        
        result = CivCom.utype_can_do_action(civcom, 10, 44)  # ACTION_AIRLIFT
        
        self.assertFalse(result, "Should return False when action bit is not set")

    def test_city_has_improvement_checks_bitvector(self):
        """city_has_improvement should correctly check bitvector"""
        from civcom import CivCom
        
        civcom = Mock(spec=CivCom)
        civcom.improvements = {
            5: {'id': 5, 'name': 'Airport'},
        }
        
        # City with Airport (improvement id 5, byte 0, bit 5)
        city = {
            'id': 1,
            'name': 'Test City',
            'improvements': [1 << 5]  # Bit 5 set in byte 0
        }
        
        result = CivCom.city_has_improvement(civcom, city, 'Airport')
        self.assertTrue(result, "Should detect Airport in city")

    def test_city_has_improvement_returns_false_for_missing(self):
        """city_has_improvement should return False when improvement not present"""
        from civcom import CivCom
        
        civcom = Mock(spec=CivCom)
        civcom.improvements = {
            5: {'id': 5, 'name': 'Airport'},
        }
        
        # City without Airport
        city = {
            'id': 1,
            'name': 'Test City',
            'improvements': [0]  # No improvements
        }
        
        result = CivCom.city_has_improvement(civcom, city, 'Airport')
        self.assertFalse(result, "Should return False when Airport not in city")

    def test_city_has_improvement_handles_unknown_improvement(self):
        """city_has_improvement should return False for unknown improvement name"""
        from civcom import CivCom
        
        civcom = Mock(spec=CivCom)
        civcom.improvements = {
            5: {'id': 5, 'name': 'Airport'},
        }
        
        city = {
            'id': 1,
            'name': 'Test City',
            'improvements': [0xFF]  # All bits set
        }
        
        result = CivCom.city_has_improvement(civcom, city, 'NonExistentBuilding')
        self.assertFalse(result, "Should return False for unknown improvement")

    def test_city_has_improvement_handles_missing_bitvector(self):
        """city_has_improvement should return False when improvements field is missing"""
        from civcom import CivCom
        
        civcom = Mock(spec=CivCom)
        civcom.improvements = {
            5: {'id': 5, 'name': 'Airport'},
        }
        
        # City without improvements field
        city = {
            'id': 1,
            'name': 'Test City'
            # No 'improvements' field
        }
        
        result = CivCom.city_has_improvement(civcom, city, 'Airport')
        self.assertFalse(result, "Should return False when improvements field missing")

    def test_city_has_improvement_case_insensitive(self):
        """city_has_improvement should be case-insensitive"""
        from civcom import CivCom
        
        civcom = Mock(spec=CivCom)
        civcom.improvements = {
            5: {'id': 5, 'name': 'Airport'},
        }
        
        city = {
            'id': 1,
            'name': 'Test City',
            'improvements': [1 << 5]
        }
        
        result = CivCom.city_has_improvement(civcom, city, 'AIRPORT')
        self.assertTrue(result, "Should match improvement name case-insensitively")


if __name__ == "__main__":
    unittest.main()
