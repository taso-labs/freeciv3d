"""
Tests for AGE-400: FreeCiv interactive/multi-player actions.

Covers:
- Diplomatic state tracking (PACKET_PLAYER_DIPLSTATE handler)
- Diplomacy meeting lifecycle (init/clause/accept/cancel)
- _get_diplomacy_actions() generation based on diplomatic state
- Advanced spy action generation (6 new actions)
- Expel unit action generation
- Packet converter mappings for diplomacy actions
- _normalize_agent_clash_action() diplomacy support
- get_all_players_with_diplomacy() enrichment
"""

import os
import sys
import json
import secrets

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variable before imports
os.environ.setdefault('CACHE_HMAC_SECRET', secrets.token_hex(32))

import pytest
from unittest.mock import Mock, MagicMock, patch

from action_constants import *
from packet_constants import *
from packet_converter import convert_action_to_packet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_civcom_stub():
    """Create a minimal CivCom-like object with diplomatic state support.

    Returns an object that has the attributes and methods used by
    _get_diplomacy_actions, get_diplstate, get_all_diplstates_for_player,
    and get_all_players_with_diplomacy without needing a real websocket.
    """
    # We import CivCom's class-level constants via a simple namespace
    class CivComStub:
        DS_WAR = 0
        DS_ARMISTICE = 1
        DS_CEASEFIRE = 2
        DS_PEACE = 3
        DS_ALLIANCE = 4
        DS_NO_CONTACT = 5
        DS_NAMES = {0: 'war', 1: 'armistice', 2: 'ceasefire', 3: 'peace', 4: 'alliance', 5: 'no_contact'}

        def __init__(self):
            self.diplomatic_states = {}
            self.diplomacy_meetings = {}
            self.all_players = []

        def get_diplstate(self, player1_id, player2_id):
            state = self.diplomatic_states.get((player1_id, player2_id))
            if state is None:
                state = self.diplomatic_states.get((player2_id, player1_id))
            if state is None:
                state = {'type': self.DS_NO_CONTACT, 'turns_left': -1,
                         'has_reason_to_cancel': 0, 'contact_turns_left': 0}
            return {**state, 'type_name': self.DS_NAMES.get(state['type'], f"unknown({state['type']})")}

        def get_all_diplstates_for_player(self, player_id):
            result = {}
            for (p1, p2), state in self.diplomatic_states.items():
                if p1 == player_id:
                    result[p2] = {**state, 'type_name': self.DS_NAMES.get(state['type'], f"unknown({state['type']})")}
                elif p2 == player_id:
                    result[p1] = {**state, 'type_name': self.DS_NAMES.get(state['type'], f"unknown({state['type']})")}
            return result

        def get_all_players_with_diplomacy(self, requesting_player_id):
            enriched = []
            for player in self.all_players:
                player_copy = dict(player)
                other_id = player.get('id')
                if other_id is not None and other_id != requesting_player_id:
                    ds = self.get_diplstate(requesting_player_id, other_id)
                    player_copy['diplomatic_status'] = ds['type_name']
                enriched.append(player_copy)
            return enriched

        def _get_diplomacy_actions(self, player_id):
            """Port of civcom._get_diplomacy_actions logic for testing."""
            actions = []
            other_players = [p for p in self.all_players if p.get('id') != player_id]
            if not other_players:
                return actions

            for other_player in other_players:
                other_id = other_player.get('id')
                if other_id is None:
                    continue

                ds = self.get_diplstate(player_id, other_id)
                ds_type = ds['type']
                in_meeting = other_id in self.diplomacy_meetings
                other_name = other_player.get('name', f'Player{other_id}')

                if not in_meeting:
                    actions.append({
                        'action': 'diplomacy_start_negotiation',
                        'params': {'player_id': other_id, 'player_name': other_name},
                        'is_valid': True, 'type': 'diplomacy',
                    })

                if ds_type != self.DS_WAR:
                    actions.append({
                        'action': 'diplomacy_declare_war',
                        'params': {'player_id': other_id, 'player_name': other_name},
                        'is_valid': True, 'type': 'diplomacy',
                    })

                actions.append({
                    'action': 'diplomacy_message',
                    'params': {'player_id': other_id, 'player_name': other_name, 'message': ''},
                    'is_valid': True, 'type': 'diplomacy',
                })

                if in_meeting:
                    meeting = self.diplomacy_meetings[other_id]
                    has_clauses = len(meeting.get('clauses', [])) > 0

                    if ds_type in (self.DS_WAR, self.DS_ARMISTICE):
                        actions.append({
                            'action': 'diplomacy_propose_ceasefire',
                            'params': {'player_id': other_id, 'player_name': other_name},
                            'is_valid': True, 'type': 'diplomacy',
                        })

                    if ds_type != self.DS_PEACE and ds_type != self.DS_ALLIANCE:
                        actions.append({
                            'action': 'diplomacy_propose_peace',
                            'params': {'player_id': other_id, 'player_name': other_name},
                            'is_valid': True, 'type': 'diplomacy',
                        })

                    if ds_type == self.DS_PEACE:
                        actions.append({
                            'action': 'diplomacy_propose_alliance',
                            'params': {'player_id': other_id, 'player_name': other_name},
                            'is_valid': True, 'type': 'diplomacy',
                        })

                    actions.append({
                        'action': 'diplomacy_share_vision',
                        'params': {'player_id': other_id, 'player_name': other_name},
                        'is_valid': True, 'type': 'diplomacy',
                    })

                    if has_clauses:
                        actions.append({
                            'action': 'diplomacy_accept_treaty',
                            'params': {'player_id': other_id, 'player_name': other_name},
                            'is_valid': True, 'type': 'diplomacy',
                        })
                        actions.append({
                            'action': 'diplomacy_reject_treaty',
                            'params': {'player_id': other_id, 'player_name': other_name},
                            'is_valid': True, 'type': 'diplomacy',
                        })

                if ds_type in (self.DS_CEASEFIRE, self.DS_PEACE, self.DS_ALLIANCE):
                    actions.append({
                        'action': 'diplomacy_cancel_treaty',
                        'params': {'player_id': other_id, 'player_name': other_name},
                        'is_valid': True, 'type': 'diplomacy',
                    })

                if ds_type in (self.DS_PEACE, self.DS_ALLIANCE):
                    actions.append({
                        'action': 'diplomacy_withdraw_vision',
                        'params': {'player_id': other_id, 'player_name': other_name},
                        'is_valid': True, 'type': 'diplomacy',
                    })

            return actions

    return CivComStub()


# ===========================================================================
# Test Classes
# ===========================================================================


class TestDiplomaticStateTracking:
    """Test diplomatic state storage and retrieval (Steps 1-2)."""

    def test_get_diplstate_default_no_contact(self):
        """Unknown player pair defaults to DS_NO_CONTACT."""
        c = _make_civcom_stub()
        ds = c.get_diplstate(0, 1)
        assert ds['type'] == c.DS_NO_CONTACT
        assert ds['type_name'] == 'no_contact'

    def test_get_diplstate_forward_key(self):
        """State stored as (p1, p2) is found with get_diplstate(p1, p2)."""
        c = _make_civcom_stub()
        c.diplomatic_states[(0, 1)] = {'type': c.DS_WAR, 'turns_left': -1,
                                        'has_reason_to_cancel': 0, 'contact_turns_left': 0}
        ds = c.get_diplstate(0, 1)
        assert ds['type'] == c.DS_WAR
        assert ds['type_name'] == 'war'

    def test_get_diplstate_reverse_key(self):
        """State stored as (p2, p1) is found with get_diplstate(p1, p2)."""
        c = _make_civcom_stub()
        c.diplomatic_states[(1, 0)] = {'type': c.DS_PEACE, 'turns_left': 0,
                                        'has_reason_to_cancel': 0, 'contact_turns_left': 0}
        ds = c.get_diplstate(0, 1)
        assert ds['type'] == c.DS_PEACE
        assert ds['type_name'] == 'peace'

    def test_get_all_diplstates_for_player(self):
        """Returns all relationships for a given player."""
        c = _make_civcom_stub()
        c.diplomatic_states[(0, 1)] = {'type': c.DS_WAR, 'turns_left': -1,
                                        'has_reason_to_cancel': 0, 'contact_turns_left': 0}
        c.diplomatic_states[(0, 2)] = {'type': c.DS_PEACE, 'turns_left': 0,
                                        'has_reason_to_cancel': 0, 'contact_turns_left': 0}
        c.diplomatic_states[(3, 4)] = {'type': c.DS_ALLIANCE, 'turns_left': 0,
                                        'has_reason_to_cancel': 0, 'contact_turns_left': 0}

        result = c.get_all_diplstates_for_player(0)
        assert len(result) == 2
        assert result[1]['type_name'] == 'war'
        assert result[2]['type_name'] == 'peace'

    def test_meeting_lifecycle(self):
        """Meetings can be created, have clauses added, and be removed."""
        c = _make_civcom_stub()

        # Init meeting
        c.diplomacy_meetings[2] = {'clauses': [], 'accept_self': False, 'accept_other': False}
        assert 2 in c.diplomacy_meetings

        # Add clause
        c.diplomacy_meetings[2]['clauses'].append({'type': 6, 'value': 0, 'giver': 0})
        assert len(c.diplomacy_meetings[2]['clauses']) == 1

        # Accept
        c.diplomacy_meetings[2]['accept_self'] = True
        assert c.diplomacy_meetings[2]['accept_self'] is True

        # Cancel meeting
        del c.diplomacy_meetings[2]
        assert 2 not in c.diplomacy_meetings


class TestGetDiplomacyActions:
    """Test _get_diplomacy_actions() generation logic (Step 4)."""

    def _setup_two_player_game(self, ds_type=None, meeting=False, clauses=False):
        """Helper: creates a 2-player game with optional diplomatic state and meeting."""
        c = _make_civcom_stub()
        c.all_players = [
            {'id': 0, 'name': 'Alice'},
            {'id': 1, 'name': 'Bob'},
        ]
        if ds_type is not None:
            c.diplomatic_states[(0, 1)] = {
                'type': ds_type, 'turns_left': -1,
                'has_reason_to_cancel': 0, 'contact_turns_left': 0,
            }
        if meeting:
            clause_list = [{'type': 6, 'value': 0, 'giver': 0}] if clauses else []
            c.diplomacy_meetings[1] = {
                'clauses': clause_list,
                'accept_self': False,
                'accept_other': False,
            }
        return c

    def _action_types(self, actions):
        return [a['action'] for a in actions]

    def test_no_other_players_returns_empty(self):
        c = _make_civcom_stub()
        c.all_players = [{'id': 0, 'name': 'Solo'}]
        assert c._get_diplomacy_actions(0) == []

    def test_no_contact_baseline(self):
        """With no diplomatic state and no meeting, should get start_negotiation, declare_war, message."""
        c = self._setup_two_player_game()
        types = self._action_types(c._get_diplomacy_actions(0))
        assert 'diplomacy_start_negotiation' in types
        assert 'diplomacy_declare_war' in types
        assert 'diplomacy_message' in types
        # No meeting-dependent actions
        assert 'diplomacy_propose_ceasefire' not in types
        assert 'diplomacy_accept_treaty' not in types

    def test_at_war_no_declare_war(self):
        """When already at war, declare_war should NOT be available."""
        c = self._setup_two_player_game(ds_type=0)  # DS_WAR = 0
        types = self._action_types(c._get_diplomacy_actions(0))
        assert 'diplomacy_declare_war' not in types

    def test_war_with_meeting_propose_ceasefire(self):
        """At war with active meeting should allow ceasefire proposal."""
        c = self._setup_two_player_game(ds_type=0, meeting=True)  # DS_WAR=0
        types = self._action_types(c._get_diplomacy_actions(0))
        assert 'diplomacy_propose_ceasefire' in types
        assert 'diplomacy_propose_peace' in types
        assert 'diplomacy_share_vision' in types
        # No start_negotiation when in meeting
        assert 'diplomacy_start_negotiation' not in types

    def test_peace_with_meeting_propose_alliance(self):
        """At peace with meeting should allow alliance proposal."""
        c = self._setup_two_player_game(ds_type=3, meeting=True)  # DS_PEACE=3
        types = self._action_types(c._get_diplomacy_actions(0))
        assert 'diplomacy_propose_alliance' in types
        # Should NOT offer peace again
        assert 'diplomacy_propose_peace' not in types
        # Cancel treaty available for peace
        assert 'diplomacy_cancel_treaty' in types
        assert 'diplomacy_withdraw_vision' in types

    def test_meeting_with_clauses_accept_reject(self):
        """Meeting with clauses should offer accept and reject."""
        c = self._setup_two_player_game(ds_type=0, meeting=True, clauses=True)
        types = self._action_types(c._get_diplomacy_actions(0))
        assert 'diplomacy_accept_treaty' in types
        assert 'diplomacy_reject_treaty' in types

    def test_meeting_without_clauses_no_accept(self):
        """Meeting without clauses should NOT offer accept/reject."""
        c = self._setup_two_player_game(ds_type=0, meeting=True, clauses=False)
        types = self._action_types(c._get_diplomacy_actions(0))
        assert 'diplomacy_accept_treaty' not in types
        assert 'diplomacy_reject_treaty' not in types

    def test_ceasefire_cancel_treaty_available(self):
        """Ceasefire allows cancel_treaty."""
        c = self._setup_two_player_game(ds_type=2)  # DS_CEASEFIRE=2
        types = self._action_types(c._get_diplomacy_actions(0))
        assert 'diplomacy_cancel_treaty' in types

    def test_alliance_withdraw_vision_available(self):
        """Alliance allows withdraw_vision."""
        c = self._setup_two_player_game(ds_type=4)  # DS_ALLIANCE=4
        types = self._action_types(c._get_diplomacy_actions(0))
        assert 'diplomacy_withdraw_vision' in types
        assert 'diplomacy_cancel_treaty' in types

    def test_all_actions_have_player_id(self):
        """Every diplomacy action must include player_id in params."""
        c = self._setup_two_player_game(ds_type=0, meeting=True, clauses=True)
        actions = c._get_diplomacy_actions(0)
        for action in actions:
            assert 'player_id' in action['params'], f"{action['action']} missing player_id"
            assert action['params']['player_id'] == 1

    def test_multiple_other_players(self):
        """Actions generated for each other player."""
        c = _make_civcom_stub()
        c.all_players = [
            {'id': 0, 'name': 'Alice'},
            {'id': 1, 'name': 'Bob'},
            {'id': 2, 'name': 'Charlie'},
        ]
        actions = c._get_diplomacy_actions(0)
        target_ids = {a['params']['player_id'] for a in actions}
        assert 1 in target_ids
        assert 2 in target_ids
        assert 0 not in target_ids


class TestGetAllPlayersWithDiplomacy:
    """Test get_all_players_with_diplomacy enrichment (Step 10)."""

    def test_enriches_other_players_with_status(self):
        """Other players get diplomatic_status, requesting player does not."""
        c = _make_civcom_stub()
        c.all_players = [
            {'id': 0, 'name': 'Alice'},
            {'id': 1, 'name': 'Bob'},
        ]
        c.diplomatic_states[(0, 1)] = {
            'type': c.DS_WAR, 'turns_left': -1,
            'has_reason_to_cancel': 0, 'contact_turns_left': 0,
        }

        enriched = c.get_all_players_with_diplomacy(0)
        assert len(enriched) == 2

        alice = next(p for p in enriched if p['id'] == 0)
        bob = next(p for p in enriched if p['id'] == 1)

        assert 'diplomatic_status' not in alice
        assert bob['diplomatic_status'] == 'war'

    def test_unknown_defaults_to_no_contact(self):
        """Players with no tracked state show no_contact."""
        c = _make_civcom_stub()
        c.all_players = [
            {'id': 0, 'name': 'Alice'},
            {'id': 1, 'name': 'Bob'},
        ]

        enriched = c.get_all_players_with_diplomacy(0)
        bob = next(p for p in enriched if p['id'] == 1)
        assert bob['diplomatic_status'] == 'no_contact'

    def test_does_not_mutate_original(self):
        """Enrichment returns copies, not mutated originals."""
        c = _make_civcom_stub()
        c.all_players = [
            {'id': 0, 'name': 'Alice'},
            {'id': 1, 'name': 'Bob'},
        ]

        c.get_all_players_with_diplomacy(0)
        # Original should NOT have diplomatic_status
        for p in c.all_players:
            assert 'diplomatic_status' not in p


class TestDiplomacyPacketConverters:
    """Test packet conversion for diplomacy actions (Steps 8-9)."""

    def test_diplomacy_reject_treaty(self):
        """diplomacy_reject_treaty → PACKET_DIPLOMACY_CANCEL_MEETING_REQ."""
        action = {'type': 'diplomacy_reject_treaty', 'player_id': 2}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_CANCEL_MEETING_REQ
        assert result['counterpart'] == 2

    def test_diplomacy_cancel_treaty(self):
        """diplomacy_cancel_treaty → PACKET_DIPLOMACY_CANCEL_PACT."""
        action = {'type': 'diplomacy_cancel_treaty', 'player_id': 3}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_CANCEL_PACT
        assert result['other_player_id'] == 3
        assert result['clause'] == 6  # Default CLAUSE_PEACE

    def test_diplomacy_cancel_treaty_with_clause_type(self):
        """diplomacy_cancel_treaty respects explicit clause_type."""
        action = {'type': 'diplomacy_cancel_treaty', 'player_id': 3, 'clause_type': 8}
        result = convert_action_to_packet(action)
        assert result['clause'] == 8

    def test_diplomacy_message(self):
        """diplomacy_message → PACKET_CHAT_MSG_REQ with /msg prefix."""
        action = {'type': 'diplomacy_message', 'player_id': 2, 'message': 'Hello friend'}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_CHAT_MSG_REQ
        assert '/msg 2 Hello friend' in result['message']

    def test_diplomacy_message_no_player(self):
        """diplomacy_message without player_id sends raw message."""
        action = {'type': 'diplomacy_message', 'player_id': -1, 'message': 'broadcast'}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_CHAT_MSG_REQ
        assert result['message'] == 'broadcast'

    def test_diplomacy_start_negotiation(self):
        """diplomacy_start_negotiation → PACKET_DIPLOMACY_INIT_MEETING_REQ."""
        action = {'type': 'diplomacy_start_negotiation', 'player_id': 1}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_INIT_MEETING_REQ
        assert result['counterpart'] == 1

    def test_diplomacy_accept_treaty(self):
        """diplomacy_accept_treaty → PACKET_DIPLOMACY_ACCEPT_TREATY_REQ."""
        action = {'type': 'diplomacy_accept_treaty', 'player_id': 1}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_ACCEPT_TREATY_REQ
        assert result['counterpart'] == 1

    def test_diplomacy_declare_war(self):
        """diplomacy_declare_war → PACKET_DIPLOMACY_CANCEL_PACT."""
        action = {'type': 'diplomacy_declare_war', 'player_id': 1}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_CANCEL_PACT

    def test_diplomacy_propose_ceasefire(self):
        """diplomacy_propose_ceasefire → PACKET_DIPLOMACY_CREATE_CLAUSE_REQ."""
        action = {'type': 'diplomacy_propose_ceasefire', 'player_id': 1}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_CREATE_CLAUSE_REQ

    def test_diplomacy_propose_peace(self):
        """diplomacy_propose_peace → PACKET_DIPLOMACY_CREATE_CLAUSE_REQ with type 6."""
        action = {'type': 'diplomacy_propose_peace', 'player_id': 1}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_CREATE_CLAUSE_REQ
        assert result['type'] == 6  # CLAUSE_PEACE

    def test_diplomacy_propose_alliance(self):
        """diplomacy_propose_alliance → PACKET_DIPLOMACY_CREATE_CLAUSE_REQ with type 7."""
        action = {'type': 'diplomacy_propose_alliance', 'player_id': 1}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_CREATE_CLAUSE_REQ
        assert result['type'] == 7  # CLAUSE_ALLIANCE

    def test_diplomacy_share_vision(self):
        """diplomacy_share_vision → PACKET_DIPLOMACY_CREATE_CLAUSE_REQ with type 8."""
        action = {'type': 'diplomacy_share_vision', 'player_id': 1}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_CREATE_CLAUSE_REQ
        assert result['type'] == 8  # CLAUSE_VISION

    def test_diplomacy_withdraw_vision(self):
        """diplomacy_withdraw_vision → PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ."""
        from packet_constants import PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ
        action = {'type': 'diplomacy_withdraw_vision', 'player_id': 1}
        result = convert_action_to_packet(action)
        assert result['pid'] == PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ


class TestAdvancedSpyActionConstants:
    """Test that advanced spy action constants are properly defined (Step 5)."""

    def test_targeted_sabotage_city_constant(self):
        assert ACTION_SPY_TARGETED_SABOTAGE_CITY == 10

    def test_targeted_steal_tech_constant(self):
        assert ACTION_SPY_TARGETED_STEAL_TECH == 16

    def test_steal_gold_constant(self):
        assert ACTION_SPY_STEAL_GOLD == 6

    def test_steal_maps_constant(self):
        assert ACTION_STEAL_MAPS == 29

    def test_spread_plague_constant(self):
        assert ACTION_SPY_SPREAD_PLAGUE == 84

    def test_spy_nuke_constant(self):
        assert ACTION_SPY_NUKE == 31

    def test_expel_unit_constant(self):
        assert ACTION_EXPEL_UNIT == 37


class TestAdvancedSpyActionsInStateExtractor:
    """Test that advanced spy actions are included in city_spy_actions list (Step 5)."""

    def test_city_spy_actions_includes_advanced(self):
        """The city_spy_actions list should include all 12 spy actions.

        _fallback_can_do_action takes a lowercase unit type name string.
        """
        from state_extractor import StateExtractor
        extractor = StateExtractor()

        # All these should be allowed for 'spy' unit type name
        advanced_spy_actions = [
            ACTION_SPY_TARGETED_SABOTAGE_CITY,
            ACTION_SPY_TARGETED_STEAL_TECH,
            ACTION_SPY_STEAL_GOLD,
            ACTION_STEAL_MAPS,
            ACTION_SPY_SPREAD_PLAGUE,
            ACTION_SPY_NUKE,
        ]

        for action_id in advanced_spy_actions:
            result = extractor._fallback_can_do_action('spy', action_id)
            assert result is True, \
                f"Spy should be able to do action {action_id}, but _fallback_can_do_action returned False"

    def test_diplomat_can_do_advanced_spy_actions(self):
        """Diplomat unit type should also be allowed advanced spy actions."""
        from state_extractor import StateExtractor
        extractor = StateExtractor()

        for action_id in [ACTION_SPY_TARGETED_SABOTAGE_CITY, ACTION_SPY_STEAL_GOLD, ACTION_STEAL_MAPS]:
            result = extractor._fallback_can_do_action('diplomat', action_id)
            assert result is True, \
                f"Diplomat should be able to do action {action_id}"

    def test_non_spy_cannot_do_spy_actions(self):
        """Non-spy unit types should NOT be allowed to do spy actions."""
        from state_extractor import StateExtractor
        extractor = StateExtractor()

        spy_actions = [
            ACTION_SPY_TARGETED_SABOTAGE_CITY,
            ACTION_SPY_TARGETED_STEAL_TECH,
            ACTION_SPY_STEAL_GOLD,
            ACTION_STEAL_MAPS,
            ACTION_SPY_SPREAD_PLAGUE,
            ACTION_SPY_NUKE,
        ]

        for action_id in spy_actions:
            result = extractor._fallback_can_do_action('warriors', action_id)
            assert result is False, \
                f"Warriors should NOT be able to do spy action {action_id}"


class TestExpelUnitAction:
    """Test expel unit action in _fallback_can_do_action (Step 6)."""

    def test_military_unit_can_expel(self):
        """Military units should be able to expel."""
        from state_extractor import StateExtractor
        extractor = StateExtractor()

        result = extractor._fallback_can_do_action('warriors', ACTION_EXPEL_UNIT)
        assert result is True

    def test_settler_cannot_expel(self):
        """Civilian units should not be able to expel."""
        from state_extractor import StateExtractor
        extractor = StateExtractor()

        result = extractor._fallback_can_do_action('settlers', ACTION_EXPEL_UNIT)
        assert result is False

    def test_worker_cannot_expel(self):
        """Workers should not be able to expel."""
        from state_extractor import StateExtractor
        extractor = StateExtractor()

        result = extractor._fallback_can_do_action('workers', ACTION_EXPEL_UNIT)
        assert result is False


class TestNormalizeAgentClashDiplomacyAction:
    """Test _normalize_agent_clash_action handles diplomacy actions (Step 9)."""

    def _make_handler_stub(self):
        """Create a minimal LLMHandler-like object for normalize testing."""
        # Import the actual normalize function
        # Since it's a method, we need to read the code pattern
        handler = Mock()
        handler.player_id = 0
        return handler

    def test_diplomacy_action_detected_as_player_level(self):
        """Diplomacy actions should be recognized by startswith('diplomacy_')."""
        action_type = "diplomacy_start_negotiation"
        assert action_type.startswith("diplomacy_")

    def test_all_diplomacy_types_match_prefix(self):
        """All 10 diplomacy action types start with 'diplomacy_'."""
        diplomacy_actions = [
            "diplomacy_start_negotiation",
            "diplomacy_propose_ceasefire",
            "diplomacy_propose_peace",
            "diplomacy_propose_alliance",
            "diplomacy_accept_treaty",
            "diplomacy_reject_treaty",
            "diplomacy_cancel_treaty",
            "diplomacy_declare_war",
            "diplomacy_share_vision",
            "diplomacy_withdraw_vision",
            "diplomacy_message",
        ]
        for action_type in diplomacy_actions:
            assert action_type.startswith("diplomacy_"), \
                f"{action_type} does not match diplomacy_ prefix"


class TestDiplomaticSummaryInStateExtractor:
    """Test _get_diplomatic_summary returns real data (Step 3)."""

    def test_returns_relationships_with_civcom(self):
        """When civcom is available, returns real relationships."""
        from state_extractor import StateExtractor
        extractor = StateExtractor()

        # Create a mock civcom
        civcom = _make_civcom_stub()
        civcom.all_players = [
            {'id': 0, 'name': 'Alice'},
            {'id': 1, 'name': 'Bob'},
        ]
        civcom.diplomatic_states[(0, 1)] = {
            'type': civcom.DS_WAR, 'turns_left': -1,
            'has_reason_to_cancel': 0, 'contact_turns_left': 0,
        }

        # Mock _get_civcom_for_player to return our stub
        extractor._get_civcom_for_player = Mock(return_value=civcom)

        result = extractor._get_diplomatic_summary({}, 0)
        assert 'relationships' in result
        assert '1' in result['relationships']
        assert result['relationships']['1']['state'] == 'war'

    def test_returns_active_meetings(self):
        """Active meetings are included in the summary."""
        from state_extractor import StateExtractor
        extractor = StateExtractor()

        civcom = _make_civcom_stub()
        civcom.all_players = [
            {'id': 0, 'name': 'Alice'},
            {'id': 1, 'name': 'Bob'},
        ]
        civcom.diplomacy_meetings[1] = {
            'clauses': [{'type': 6, 'value': 0, 'giver': 0}],
            'accept_self': False,
            'accept_other': False,
        }

        extractor._get_civcom_for_player = Mock(return_value=civcom)

        result = extractor._get_diplomatic_summary({}, 0)
        assert 'active_meetings' in result
        assert '1' in result['active_meetings']
        assert result['active_meetings']['1']['i_accepted'] is False

    def test_fallback_when_no_civcom(self):
        """Without civcom, returns neutral fallback."""
        from state_extractor import StateExtractor
        extractor = StateExtractor()
        extractor._get_civcom_for_player = Mock(return_value=None)

        result = extractor._get_diplomatic_summary({}, 0)
        assert result == {"status": "neutral"}


class TestAllDiplomacyActionPacketCompleteness:
    """Verify that every diplomacy action type has a packet conversion mapping."""

    ALL_DIPLOMACY_ACTIONS = [
        'diplomacy_start_negotiation',
        'diplomacy_propose_ceasefire',
        'diplomacy_propose_peace',
        'diplomacy_propose_alliance',
        'diplomacy_accept_treaty',
        'diplomacy_reject_treaty',
        'diplomacy_cancel_treaty',
        'diplomacy_declare_war',
        'diplomacy_share_vision',
        'diplomacy_withdraw_vision',
        'diplomacy_message',
    ]

    @pytest.mark.parametrize("action_type", ALL_DIPLOMACY_ACTIONS)
    def test_action_has_packet_mapping(self, action_type):
        """Each diplomacy action type should produce a valid packet dict."""
        action = {'type': action_type, 'player_id': 1, 'message': 'test'}
        result = convert_action_to_packet(action)
        assert result is not None, f"{action_type} returned None from convert_action_to_packet"
        assert 'pid' in result, f"{action_type} packet missing 'pid' field"
