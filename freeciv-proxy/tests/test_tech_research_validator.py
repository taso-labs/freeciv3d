"""Tests for tech_research action validator"""

import unittest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import LLMActionValidator


class TestTechResearchValidator(unittest.TestCase):
    def setUp(self):
        self.validator = LLMActionValidator()

    def test_tech_research_valid(self):
        action = {'type': 'tech_research', 'tech_name': 'alphabet', 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        self.assertTrue(result.is_valid)

    def test_tech_research_case_insensitive(self):
        action = {'type': 'tech_research', 'tech_name': 'AgriCulture', 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        self.assertTrue(result.is_valid)

    def test_tech_research_invalid(self):
        action = {'type': 'tech_research', 'tech_name': 'dragonriding', 'player_id': 0}
        result = self.validator.validate_action(action, player_id=0, game_state=None)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, 'E041')
