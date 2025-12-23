"""Test legal action generation based on pre-conditions for tech research and city production"""

import pytest
from unittest.mock import Mock, patch
from civcom import CivCom, A_UNSET, VUT_UTYPE, VUT_IMPROVEMENT


def create_mock_civcom():
    """Helper to create a mock CivCom instance with required attributes"""
    civcom = Mock(spec=CivCom)
    civcom.game_turn = 1
    civcom.player_cities = {}
    civcom.player_units = {}
    civcom.unit_types = {}
    civcom.improvements = {}
    civcom.research_info = {}
    civcom._action_cache = {}
    civcom.username = "test_player"
    civcom.tiles = {}
    civcom.unit_classes = {}
    civcom.map_info = {'width': 80, 'height': 50}
    
    # Bind the real methods we want to test
    civcom._get_city_production_actions = CivCom._get_city_production_actions.__get__(civcom)
    civcom._get_tech_research_actions = CivCom._get_tech_research_actions.__get__(civcom)
    civcom._get_unit_actions = CivCom._get_unit_actions.__get__(civcom)
    civcom._get_legal_actions_optimized = CivCom._get_legal_actions_optimized.__get__(civcom)
    civcom._is_city_producing_coinage = CivCom._is_city_producing_coinage.__get__(civcom)
    
    return civcom


class TestCityProductionPreconditions:
    """Test city production action generation with various pre-conditions"""

    def test_city_production_actions_when_production_finished(self):
        """Test that production actions are generated when shield_stock == 0"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 0,  # Production just finished
                'x': 10,
                'y': 10
            }
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'},
            2: {'id': 2, 'name': 'Settlers'}
        }
        civcom.improvements = {
            1: {'id': 1, 'name': 'Barracks'},
            2: {'id': 2, 'name': 'Granary'}
        }
        
        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Should generate actions for both units and buildings
        assert len(actions) > 0
        
        # Check that all actions have correct structure
        for action in actions:
            assert action['type'] == 'city_production'
            assert action['city_id'] == '1'
            assert action['city_name'] == 'TestCity'
            assert action['reason'] == 'finished'
            assert 'production_name' in action
            assert 'production_kind' in action
            assert 'production_value' in action
        
        # Verify we have both unit and building options
        unit_actions = [a for a in actions if a['production_kind'] == VUT_UTYPE]
        building_actions = [a for a in actions if a['production_kind'] == VUT_IMPROVEMENT]
        
        assert len(unit_actions) == 2  # Warriors, Settlers
        assert len(building_actions) == 2  # Barracks, Granary

    def test_city_production_actions_when_producing_coinage(self):
        """Test that production actions are generated when city produces Coinage"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 50,  # Mid-production but...
                'production_kind': VUT_IMPROVEMENT,
                'production_value': 999,  # ...producing Coinage
                'x': 10,
                'y': 10
            }
        }
        civcom.improvements = {
            999: {'id': 999, 'name': 'Coinage'},
            1: {'id': 1, 'name': 'Barracks'}
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'}
        }
        
        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Should generate actions because Coinage is infinite production
        assert len(actions) > 0
        
        # All actions should have reason='coinage'
        for action in actions:
            assert action['type'] == 'city_production'
            assert action['reason'] == 'coinage'

    def test_no_city_production_actions_mid_production(self):
        """Test that NO production actions are generated when city is mid-production"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 25,  # Mid-production
                'production_kind': VUT_UTYPE,
                'production_value': 1,  # Warriors
                'x': 10,
                'y': 10
            }
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'},
            2: {'id': 2, 'name': 'Settlers'}
        }
        civcom.improvements = {
            1: {'id': 1, 'name': 'Barracks'}
        }
        
        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Should NOT generate any actions
        assert len(actions) == 0

    def test_city_production_actions_multiple_cities(self):
        """Test production actions for multiple cities with different states"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'City1',
                'owner': 0,
                'shield_stock': 0,  # Finished
                'x': 10,
                'y': 10
            },
            '2': {
                'id': 2,
                'name': 'City2',
                'owner': 0,
                'shield_stock': 30,  # Mid-production (skip)
                'production_kind': VUT_UTYPE,
                'production_value': 1,
                'x': 20,
                'y': 20
            },
            '3': {
                'id': 3,
                'name': 'City3',
                'owner': 0,
                'shield_stock': 0,  # Finished
                'x': 30,
                'y': 30
            }
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'}
        }
        civcom.improvements = {}
        
        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Should only generate actions for City1 and City3 (not City2)
        city_ids = set(a['city_id'] for a in actions)
        assert '1' in city_ids
        assert '3' in city_ids
        assert '2' not in city_ids

    def test_city_production_respects_max_cities_limit(self):
        """Test that max_cities parameter limits action generation"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = {
            str(i): {
                'id': i,
                'name': f'City{i}',
                'owner': 0,
                'shield_stock': 0,  # All finished
                'x': i * 10,
                'y': i * 10
            } for i in range(1, 6)  # 5 cities
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'}
        }
        civcom.improvements = {}
        
        actions = civcom._get_city_production_actions(player_id=0, max_cities=2)
        
        # Should only generate actions for first 2 cities
        city_ids = set(a['city_id'] for a in actions)
        assert len(city_ids) <= 2

    def test_city_production_caching_per_turn(self):
        """Test that city production actions are cached per turn"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 0,
                'x': 10,
                'y': 10
            }
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'}
        }
        civcom.improvements = {}
        
        # First call - should compute
        actions1 = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Second call - should use cache
        actions2 = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Results should be identical (cached)
        assert actions1 is actions2  # Same object reference
        
        # Change turn - cache should be invalidated
        civcom.game_turn = 11
        actions3 = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Should be different object (cache miss)
        assert actions3 is not actions1


class TestTechResearchPreconditions:
    """Test tech research action generation with various pre-conditions"""

    def test_tech_research_actions_when_no_tech_selected(self):
        """Test that tech actions are generated when researching == A_UNSET"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.research_info = {
            0: {
                'researching': A_UNSET,  # No tech selected
                'inventions': []
            }
        }
        
        # Mock get_researchable_techs
        with patch.object(civcom, 'get_researchable_techs') as mock_researchable:
            mock_researchable.return_value = [
                {'id': 1, 'name': 'Writing', 'cost': 50},
                {'id': 2, 'name': 'Bronze Working', 'cost': 60},
                {'id': 3, 'name': 'Pottery', 'cost': 40}
            ]
            
            actions = civcom._get_tech_research_actions(player_id=0)
            
            # Should generate actions for all researchable techs
            assert len(actions) == 3
            
            # Check action structure
            for action in actions:
                assert action['type'] == 'tech_research'
                assert action['reason'] == 'tech_completed'
                assert 'tech_id' in action
                assert 'tech_name' in action
                assert 'tech_cost' in action
            
            # Verify tech names
            tech_names = [a['tech_name'] for a in actions]
            assert 'Writing' in tech_names
            assert 'Bronze Working' in tech_names
            assert 'Pottery' in tech_names

    def test_no_tech_research_actions_when_already_researching(self):
        """Test that NO tech actions are generated when already researching"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.research_info = {
            0: {
                'researching': 5,  # Already researching tech ID 5
                'inventions': []
            }
        }
        
        actions = civcom._get_tech_research_actions(player_id=0)
        
        # Should NOT generate any actions
        assert len(actions) == 0

    def test_no_tech_research_actions_when_no_research_info(self):
        """Test that NO tech actions when research_info is missing"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.research_info = {}  # No research info for player
        
        actions = civcom._get_tech_research_actions(player_id=0)
        
        # Should return empty list
        assert len(actions) == 0

    def test_tech_research_caching_per_turn(self):
        """Test that tech research actions are cached per turn"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.research_info = {
            0: {
                'researching': A_UNSET,
                'inventions': []
            }
        }
        
        with patch.object(civcom, 'get_researchable_techs') as mock_researchable:
            mock_researchable.return_value = [
                {'id': 1, 'name': 'Writing', 'cost': 50}
            ]
            
            # First call
            actions1 = civcom._get_tech_research_actions(player_id=0)
            
            # Second call - should use cache
            actions2 = civcom._get_tech_research_actions(player_id=0)
            
            # Should be same object (cached)
            assert actions1 is actions2
            
            # get_researchable_techs should only be called once
            assert mock_researchable.call_count == 1
            
            # Change turn - should invalidate cache
            civcom.game_turn = 11
            actions3 = civcom._get_tech_research_actions(player_id=0)
            
            # Should be different object
            assert actions3 is not actions1
            
            # get_researchable_techs called again
            assert mock_researchable.call_count == 2


class TestLegalActionsOptimizedIntegration:
    """Test _get_legal_actions_optimized with all pre-conditions"""

    def test_legal_actions_combines_all_categories(self):
        """Test that all action categories are combined correctly"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        
        # Setup for unit actions
        civcom.player_units = {
            '1': {
                'id': 1,
                'type': 'Warriors',
                'type_id': 1,
                'owner': 0,
                'x': 10,
                'y': 10,
                'moves_left': 3,
                'tile': 100
            }
        }
        
        # Setup for city production actions
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 0,  # Production finished
                'x': 10,
                'y': 10
            }
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'}
        }
        civcom.improvements = {
            1: {'id': 1, 'name': 'Barracks'}
        }
        
        # Setup for tech research actions
        civcom.research_info = {
            0: {
                'researching': A_UNSET,  # No tech selected
                'inventions': []
            }
        }
        
        with patch.object(civcom, 'get_researchable_techs') as mock_researchable:
            mock_researchable.return_value = [
                {'id': 1, 'name': 'Writing', 'cost': 50}
            ]
            
            with patch('state_extractor.StateExtractor') as MockExtractor:
                mock_extractor = MockExtractor.return_value
                mock_extractor.get_unit_actions.return_value = {
                    'actions': [
                        {
                            'action': 'move',
                            'params': {'direction': 'n'},
                            'is_valid': True,
                            'unit_id': 1,
                            'action_id': 45
                        }
                    ]
                }
                
                actions = civcom._get_legal_actions_optimized(player_id=0)
                
                # Should have actions from all three categories
                action_types = [a.get('type') for a in actions]
                
                # Unit actions
                assert 'unit_move' in action_types or 'unit_action' in action_types
                
                # City production actions
                city_actions = [a for a in actions if a.get('type') == 'city_production']
                assert len(city_actions) > 0
                
                # Tech research actions
                tech_actions = [a for a in actions if a.get('type') == 'tech_research']
                assert len(tech_actions) > 0

    def test_legal_actions_skips_categories_with_no_actions(self):
        """Test that categories with pre-conditions not met are skipped"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        
        # Units with no moves (no unit actions)
        civcom.player_units = {
            '1': {
                'id': 1,
                'type': 'Warriors',
                'owner': 0,
                'moves_left': 0,  # No moves
                'x': 10,
                'y': 10
            }
        }
        
        # Cities mid-production (no city actions)
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 50,  # Mid-production
                'production_kind': VUT_UTYPE,
                'production_value': 1,
                'x': 10,
                'y': 10
            }
        }
        civcom.unit_types = {}
        civcom.improvements = {}
        
        # Already researching tech (no tech actions)
        civcom.research_info = {
            0: {
                'researching': 5,  # Already researching
                'inventions': []
            }
        }
        
        with patch('state_extractor.StateExtractor') as MockExtractor:
            mock_extractor = MockExtractor.return_value
            mock_extractor.get_unit_actions.return_value = {
                'actions': []  # No actions for unit with no moves
            }
            
            actions = civcom._get_legal_actions_optimized(player_id=0)
            
            # Should have no actions from any category
            assert len(actions) == 0

    def test_legal_actions_respects_per_category_limits(self):
        """Test that each category respects its own limit"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        
        # 10 units (should limit to 5)
        civcom.player_units = {
            str(i): {
                'id': i,
                'type': 'Warriors',
                'type_id': 1,
                'owner': 0,
                'x': 10,
                'y': 10,
                'moves_left': 3,
                'tile': 100
            } for i in range(1, 11)
        }
        
        # 10 cities with production finished (should limit to 3)
        civcom.player_cities = {
            str(i): {
                'id': i,
                'name': f'City{i}',
                'owner': 0,
                'shield_stock': 0,
                'x': i * 10,
                'y': i * 10
            } for i in range(1, 11)
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'}
        }
        civcom.improvements = {}
        
        # Tech research (no limit)
        civcom.research_info = {
            0: {
                'researching': A_UNSET,
                'inventions': []
            }
        }
        
        with patch.object(civcom, 'get_researchable_techs') as mock_researchable:
            mock_researchable.return_value = [
                {'id': i, 'name': f'Tech{i}', 'cost': 50} for i in range(1, 21)  # 20 techs
            ]
            
            with patch('state_extractor.StateExtractor') as MockExtractor:
                mock_extractor = MockExtractor.return_value
                # Return one action per unit
                def mock_unit_actions(unit_id, player_id):
                    return {
                        'actions': [
                            {
                                'action': 'move',
                                'params': {'direction': 'n'},
                                'is_valid': True,
                                'unit_id': unit_id,
                                'action_id': 45
                            }
                        ]
                    }
                mock_extractor.get_unit_actions.side_effect = mock_unit_actions
                
                actions = civcom._get_legal_actions_optimized(player_id=0)
                
                # Count actions per category
                unit_actions = [a for a in actions if a.get('type') in ('unit_move', 'unit_action')]
                city_actions = [a for a in actions if a.get('type') == 'city_production']
                tech_actions = [a for a in actions if a.get('type') == 'tech_research']
                
                # Unit actions: max 5 units, each with 1 action = 5 actions
                assert len(unit_actions) <= 5
                
                # City actions: max 3 cities, each with 1 unit type = 3 actions
                city_ids = set(a['city_id'] for a in city_actions)
                assert len(city_ids) <= 3
                
                # Tech actions: all 20 techs (no limit)
                assert len(tech_actions) == 20


class TestActionPreconditionEdgeCases:
    """Test edge cases in action pre-condition handling"""

    def test_city_production_with_wrong_owner(self):
        """Test that cities with wrong owner are skipped"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 1,  # Different owner
                'shield_stock': 0,
                'x': 10,
                'y': 10
            }
        }
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'}
        }
        civcom.improvements = {}
        
        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Should skip city with wrong owner
        assert len(actions) == 0

    def test_city_production_with_list_format(self):
        """Test that city production handles list format for cities"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = [
            {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 0,
                'x': 10,
                'y': 10
            }
        ]
        civcom.unit_types = {
            1: {'id': 1, 'name': 'Warriors'}
        }
        civcom.improvements = {}
        
        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Should convert list to dict and process
        assert len(actions) > 0

    def test_unit_actions_with_list_format(self):
        """Test that unit actions handle list format for units"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_units = [
            {
                'id': 1,
                'type': 'Warriors',
                'type_id': 1,
                'owner': 0,
                'x': 10,
                'y': 10,
                'moves_left': 3,
                'tile': 100
            }
        ]
        
        with patch('state_extractor.StateExtractor') as MockExtractor:
            mock_extractor = MockExtractor.return_value
            mock_extractor.get_unit_actions.return_value = {
                'actions': [
                    {
                        'action': 'move',
                        'params': {'direction': 'n'},
                        'is_valid': True,
                        'unit_id': 1,
                        'action_id': 45
                    }
                ]
            }
            
            actions = civcom._get_unit_actions(player_id=0, max_units=5)
            
            # Should convert list to dict and process
            assert len(actions) > 0

    def test_empty_unit_types_and_improvements(self):
        """Test city production with empty unit_types and improvements"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 0,
                'x': 10,
                'y': 10
            }
        }
        civcom.unit_types = {}
        civcom.improvements = {}
        
        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)
        
        # Should return empty list (no production options)
        assert len(actions) == 0

    def test_tech_research_with_empty_researchable_techs(self):
        """Test tech research when no techs are researchable"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.research_info = {
            0: {
                'researching': A_UNSET,
                'inventions': []
            }
        }
        
        with patch.object(civcom, 'get_researchable_techs') as mock_researchable:
            mock_researchable.return_value = []  # No researchable techs
            
            actions = civcom._get_tech_research_actions(player_id=0)
            
            # Should return empty list
            assert len(actions) == 0


class TestCityProductionBuildPermissions:
    """Test that city production filters by server-provided build permissions"""

    def test_city_production_filters_by_can_build_unit(self):
        """Test that units are filtered by can_build_unit bitvector"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10

        # Create bitvector where only unit 0 can be built (bit 0 set = 0x01)
        # Units 1 and 2 cannot be built
        can_build_unit_bitvector = [0x01]  # Only unit ID 0 can be built

        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 0,
                'can_build_unit': can_build_unit_bitvector,
                'can_build_improvement': []  # No improvements can be built
            }
        }
        civcom.unit_types = {
            0: {'id': 0, 'name': 'Warriors'},
            1: {'id': 1, 'name': 'Settlers'},
            2: {'id': 2, 'name': 'Archers'}
        }
        civcom.improvements = {}

        # Bind the build permission check methods
        civcom.can_city_build_unit = CivCom.can_city_build_unit.__get__(civcom)
        civcom.can_city_build_improvement = CivCom.can_city_build_improvement.__get__(civcom)

        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)

        # Should only include Warriors (unit 0)
        assert len(actions) == 1
        assert actions[0]['production_name'] == 'Warriors'
        assert actions[0]['production_kind'] == VUT_UTYPE

    def test_city_production_filters_by_can_build_improvement(self):
        """Test that improvements are filtered by can_build_improvement bitvector"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10

        # Create bitvector where only improvement 1 can be built (bit 1 set = 0x02)
        can_build_improvement_bitvector = [0x02]  # Only improvement ID 1 can be built

        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 0,
                'can_build_unit': [],  # No units can be built
                'can_build_improvement': can_build_improvement_bitvector
            }
        }
        civcom.unit_types = {}
        civcom.improvements = {
            0: {'id': 0, 'name': 'Barracks'},
            1: {'id': 1, 'name': 'Granary'},
            2: {'id': 2, 'name': 'Temple'}
        }

        # Bind the build permission check methods
        civcom.can_city_build_unit = CivCom.can_city_build_unit.__get__(civcom)
        civcom.can_city_build_improvement = CivCom.can_city_build_improvement.__get__(civcom)

        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)

        # Should only include Granary (improvement 1)
        assert len(actions) == 1
        assert actions[0]['production_name'] == 'Granary'
        assert actions[0]['production_kind'] == VUT_IMPROVEMENT

    def test_city_production_allows_all_when_no_bitvector(self):
        """Test that all production is allowed when bitvectors are missing (server hasn't sent them)"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10

        # No can_build bitvectors - fallback behavior should allow all
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'TestCity',
                'owner': 0,
                'shield_stock': 0
                # No can_build_unit or can_build_improvement
            }
        }
        civcom.unit_types = {
            0: {'id': 0, 'name': 'Warriors'},
            1: {'id': 1, 'name': 'Settlers'}
        }
        civcom.improvements = {
            0: {'id': 0, 'name': 'Barracks'}
        }

        # Bind the build permission check methods
        civcom.can_city_build_unit = CivCom.can_city_build_unit.__get__(civcom)
        civcom.can_city_build_improvement = CivCom.can_city_build_improvement.__get__(civcom)

        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)

        # Should include all units and improvements (fallback when no bitvector)
        assert len(actions) == 3  # 2 units + 1 improvement

        unit_actions = [a for a in actions if a['production_kind'] == VUT_UTYPE]
        improvement_actions = [a for a in actions if a['production_kind'] == VUT_IMPROVEMENT]

        assert len(unit_actions) == 2
        assert len(improvement_actions) == 1

    def test_city_production_filters_multiple_cities(self):
        """Test that each city uses its own build permissions"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10

        # City 1 can only build Warriors, City 2 can only build Settlers
        civcom.player_cities = {
            '1': {
                'id': 1,
                'name': 'City1',
                'owner': 0,
                'shield_stock': 0,
                'can_build_unit': [0x01],  # Only unit 0 (Warriors)
                'can_build_improvement': []
            },
            '2': {
                'id': 2,
                'name': 'City2',
                'owner': 0,
                'shield_stock': 0,
                'can_build_unit': [0x02],  # Only unit 1 (Settlers)
                'can_build_improvement': []
            }
        }
        civcom.unit_types = {
            0: {'id': 0, 'name': 'Warriors'},
            1: {'id': 1, 'name': 'Settlers'}
        }
        civcom.improvements = {}

        # Bind the build permission check methods
        civcom.can_city_build_unit = CivCom.can_city_build_unit.__get__(civcom)
        civcom.can_city_build_improvement = CivCom.can_city_build_improvement.__get__(civcom)

        actions = civcom._get_city_production_actions(player_id=0, max_cities=3)

        # Should have 2 actions total - 1 for each city
        assert len(actions) == 2

        # Verify correct units for each city
        city1_actions = [a for a in actions if a['city_name'] == 'City1']
        city2_actions = [a for a in actions if a['city_name'] == 'City2']

        assert len(city1_actions) == 1
        assert city1_actions[0]['production_name'] == 'Warriors'

        assert len(city2_actions) == 1
        assert city2_actions[0]['production_name'] == 'Settlers'


class TestCacheInvalidation:
    """Test cache invalidation behavior for stale action prevention (E041, E023)"""

    def test_invalidate_action_cache_clears_all(self):
        """Test that invalidate_action_cache() clears all cached actions"""
        civcom = create_mock_civcom()
        civcom.invalidate_action_cache = CivCom.invalidate_action_cache.__get__(civcom)

        # Pre-populate cache
        civcom._action_cache = {
            '10_0_tech_actions': [{'type': 'tech_research', 'tech_id': 1}],
            '10_0_city_actions': [{'type': 'city_production', 'city_id': 1}],
            '10_1_tech_actions': [{'type': 'tech_research', 'tech_id': 2}],
        }

        # Invalidate all cache
        civcom.invalidate_action_cache()

        # All entries should be cleared
        assert len(civcom._action_cache) == 0

    def test_invalidate_action_cache_clears_specific_player(self):
        """Test that invalidate_action_cache() can clear only specific player's cache"""
        civcom = create_mock_civcom()
        civcom.invalidate_action_cache = CivCom.invalidate_action_cache.__get__(civcom)

        # Pre-populate cache for multiple players
        civcom._action_cache = {
            '10_0_tech_actions': [{'type': 'tech_research', 'tech_id': 1}],
            '10_1_tech_actions': [{'type': 'tech_research', 'tech_id': 2}],
            '10_0_city_actions': [{'type': 'city_production', 'city_id': 1}],
        }

        # Invalidate only player 0's cache
        civcom.invalidate_action_cache(player_id=0)

        # Only player 1's cache should remain
        assert '10_1_tech_actions' in civcom._action_cache
        assert '10_0_tech_actions' not in civcom._action_cache
        assert '10_0_city_actions' not in civcom._action_cache

    def test_invalidate_action_cache_clears_specific_type(self):
        """Test that invalidate_action_cache() can clear only specific cache type"""
        civcom = create_mock_civcom()
        civcom.invalidate_action_cache = CivCom.invalidate_action_cache.__get__(civcom)

        # Pre-populate cache
        civcom._action_cache = {
            '10_0_tech_actions': [{'type': 'tech_research', 'tech_id': 1}],
            '10_0_city_actions': [{'type': 'city_production', 'city_id': 1}],
        }

        # Invalidate only tech actions
        civcom.invalidate_action_cache(cache_type='tech')

        # Only city cache should remain
        assert '10_0_city_actions' in civcom._action_cache
        assert '10_0_tech_actions' not in civcom._action_cache

    def test_invalidate_action_cache_with_player_and_type(self):
        """Test that invalidate_action_cache() can filter by both player and type"""
        civcom = create_mock_civcom()
        civcom.invalidate_action_cache = CivCom.invalidate_action_cache.__get__(civcom)

        # Pre-populate cache
        civcom._action_cache = {
            '10_0_tech_actions': [{'type': 'tech_research', 'tech_id': 1}],
            '10_0_city_actions': [{'type': 'city_production', 'city_id': 1}],
            '10_1_tech_actions': [{'type': 'tech_research', 'tech_id': 2}],
        }

        # Invalidate only player 0's tech actions
        civcom.invalidate_action_cache(player_id=0, cache_type='tech')

        # Other caches should remain
        assert '10_0_city_actions' in civcom._action_cache
        assert '10_1_tech_actions' in civcom._action_cache
        assert '10_0_tech_actions' not in civcom._action_cache

    def test_tech_cache_invalidated_on_research_state_change(self):
        """Test that tech actions are invalidated when research state changes"""
        civcom = create_mock_civcom()
        civcom.invalidate_action_cache = CivCom.invalidate_action_cache.__get__(civcom)
        civcom.game_turn = 10
        civcom.research_info = {
            0: {
                'researching': A_UNSET,  # No tech selected
                'inventions': []
            }
        }

        with patch.object(civcom, 'get_researchable_techs') as mock_researchable:
            mock_researchable.return_value = [
                {'id': 1, 'name': 'Writing', 'cost': 50},
                {'id': 2, 'name': 'Bronze Working', 'cost': 60}
            ]

            # First call - populates cache
            actions1 = civcom._get_tech_research_actions(player_id=0)
            assert len(actions1) == 2

            # Simulate tech selection - research state changes
            civcom.research_info[0]['researching'] = 1  # Now researching Writing

            # Without invalidation, cache would return stale data
            # After invalidation, should return empty (already researching)
            civcom.invalidate_action_cache(player_id=0, cache_type='tech')

            actions2 = civcom._get_tech_research_actions(player_id=0)

            # Should return empty - already researching a tech
            assert len(actions2) == 0

    def test_tech_cache_returns_stale_without_invalidation(self):
        """Test that without invalidation, cache returns stale tech actions (the bug)"""
        civcom = create_mock_civcom()
        civcom.game_turn = 10
        civcom.research_info = {
            0: {
                'researching': A_UNSET,
                'inventions': []
            }
        }

        with patch.object(civcom, 'get_researchable_techs') as mock_researchable:
            mock_researchable.return_value = [
                {'id': 1, 'name': 'Writing', 'cost': 50}
            ]

            # First call - populates cache
            actions1 = civcom._get_tech_research_actions(player_id=0)
            assert len(actions1) == 1

            # Simulate tech selection without cache invalidation
            civcom.research_info[0]['researching'] = 1

            # Second call - returns cached (stale!) data
            actions2 = civcom._get_tech_research_actions(player_id=0)

            # Bug behavior: cache returns stale tech actions
            # This demonstrates why we need cache invalidation
            assert actions2 is actions1  # Same cached object
            assert len(actions2) == 1  # Stale: should be 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
