"""Tests for technology research action generation using ruleset data"""

from unittest.mock import Mock
from civcom import CivCom


class TestTechResearch:
    """Test technology research state tracking and action generation"""

    def test_get_tech_state_known(self):
        """Test get_tech_state returns KNOWN for researched techs"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['0', '2', '1', '0']  # Tech 1 is KNOWN (state=2)
            }
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        
        result = civcom.get_tech_state(1, 1)
        assert result == 'KNOWN'

    def test_get_tech_state_prereqs_known(self):
        """Test get_tech_state returns PREREQS_KNOWN for researchable techs"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['0', '1', '2', '0']  # Tech 1 is PREREQS_KNOWN (state=1)
            }
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        
        result = civcom.get_tech_state(1, 1)
        assert result == 'PREREQS_KNOWN'

    def test_get_tech_state_unknown(self):
        """Test get_tech_state returns UNKNOWN for unavailable techs"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['0', '0', '2', '1']  # Tech 1 is UNKNOWN (state=0)
            }
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        
        result = civcom.get_tech_state(1, 1)
        assert result == 'UNKNOWN'

    def test_get_tech_state_no_research_info(self):
        """Test get_tech_state returns UNKNOWN when no research info exists"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {}
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        
        result = civcom.get_tech_state(1, 1)
        assert result == 'UNKNOWN'

    def test_can_research_tech_true(self):
        """Test can_research_tech returns True when prerequisites met"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['0', '1', '0']  # Tech 1 can be researched
            }
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        civcom.can_research_tech = CivCom.can_research_tech.__get__(civcom)
        
        result = civcom.can_research_tech(1, 1)
        assert result is True

    def test_can_research_tech_false_already_known(self):
        """Test can_research_tech returns False for already researched techs"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['0', '2', '0']  # Tech 1 is KNOWN
            }
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        civcom.can_research_tech = CivCom.can_research_tech.__get__(civcom)
        
        result = civcom.can_research_tech(1, 1)
        assert result is False

    def test_can_research_tech_false_prereqs_missing(self):
        """Test can_research_tech returns False when prerequisites not met"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['0', '0', '0']  # Tech 1 is UNKNOWN
            }
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        civcom.can_research_tech = CivCom.can_research_tech.__get__(civcom)
        
        result = civcom.can_research_tech(1, 1)
        assert result is False

    def test_get_researchable_techs_returns_available(self):
        """Test get_researchable_techs returns all techs with PREREQS_KNOWN"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['0', '1', '2', '1', '0']  # Techs 1 and 3 researchable
            }
        }
        civcom.techs = {
            1: {'id': 1, 'name': 'Alphabet', 'cost': 12, 'rule_name': 'Alphabet'},
            2: {'id': 2, 'name': 'Bronze Working', 'cost': 12, 'rule_name': 'Bronze Working'},
            3: {'id': 3, 'name': 'Pottery', 'cost': 10, 'rule_name': 'Pottery'},
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        civcom.can_research_tech = CivCom.can_research_tech.__get__(civcom)
        civcom.get_researchable_techs = CivCom.get_researchable_techs.__get__(civcom)
        
        result = civcom.get_researchable_techs(1)
        
        assert len(result) == 2
        assert any(t['name'] == 'Alphabet' for t in result)
        assert any(t['name'] == 'Pottery' for t in result)
        assert not any(t['name'] == 'Bronze Working' for t in result)

    def test_get_researchable_techs_empty_when_no_research(self):
        """Test get_researchable_techs returns empty list with no research info"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {}
        civcom.techs = {
            1: {'id': 1, 'name': 'Alphabet', 'cost': 12},
        }
        civcom.get_researchable_techs = CivCom.get_researchable_techs.__get__(civcom)
        
        result = civcom.get_researchable_techs(1)
        
        assert result == []

    def test_get_researchable_techs_includes_cost(self):
        """Test get_researchable_techs includes tech cost in result"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['0', '1']  # Tech 1 researchable
            }
        }
        civcom.techs = {
            1: {'id': 1, 'name': 'Alphabet', 'cost': 42, 'rule_name': 'Alphabet'},
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        civcom.can_research_tech = CivCom.can_research_tech.__get__(civcom)
        civcom.get_researchable_techs = CivCom.get_researchable_techs.__get__(civcom)
        
        result = civcom.get_researchable_techs(1)
        
        assert len(result) == 1
        assert result[0]['cost'] == 42

    def test_tech_state_boundary_conditions(self):
        """Test tech state with boundary conditions (empty inventions, out of bounds)"""
        civcom = Mock(spec=CivCom)
        civcom.research_info = {
            1: {
                'id': 1,
                'inventions': ['1', '2']  # Only 2 techs
            }
        }
        civcom.get_tech_state = CivCom.get_tech_state.__get__(civcom)
        
        # Tech ID 0 - within bounds
        assert civcom.get_tech_state(0, 1) == 'PREREQS_KNOWN'
        
        # Tech ID 1 - within bounds
        assert civcom.get_tech_state(1, 1) == 'KNOWN'
        
        # Tech ID 2 - out of bounds
        assert civcom.get_tech_state(2, 1) == 'UNKNOWN'
        
        # Tech ID 999 - way out of bounds
        assert civcom.get_tech_state(999, 1) == 'UNKNOWN'
