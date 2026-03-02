"""
Tests for PACKET_UNIT_COMBAT_INFO handling and combat_log drain behaviour.

Covers:
  1. Combat event field population (types, HP before/after, outcome flags)
  2. Drain semantics: present on first state read, empty on second
  3. Mutual destruction (att_hp=0, def_hp=0)
  4. None-guard for missing unit IDs
  5. Fog-of-war: unit not in tracked state
"""

import json
import os
import secrets
import time
from collections import deque
from unittest.mock import Mock

import pytest

# Environment variables required by transitive imports
os.environ.setdefault('CACHE_HMAC_SECRET', secrets.token_hex(32))
os.environ.setdefault('LLM_API_TOKENS', 'test-token')
os.environ.setdefault('API_KEY_SECRET', 'test-api-key-secret')

from packet_constants import PACKET_UNIT_COMBAT_INFO
from civcom import CivCom


def _make_civcom_stub():
    """Create a minimal CivCom-like object with just the attributes needed
    for parse_and_store_packet's PACKET_UNIT_COMBAT_INFO branch."""
    stub = Mock(spec=CivCom)
    stub.player_units = {}
    stub.other_units = {}
    stub.combat_log = deque(maxlen=500)
    stub.game_turn = 5
    stub.username = 'test_player'
    stub._packet_type_log_count = 999  # suppress debug logging branch
    stub._packet_log_limit = 0
    # Bind the real method so actual logic executes
    stub.parse_and_store_packet = lambda pkt: CivCom.parse_and_store_packet(stub, pkt)
    stub._drain_combat_log = lambda state: CivCom._drain_combat_log(stub, state)
    # Needed for get_full_state / get_full_state_global / build_llm_optimized_state
    stub._normalize_to_dict = CivCom._normalize_to_dict
    return stub


def _combat_packet(attacker_id=10, defender_id=20, att_hp=5, def_hp=0,
                   make_att_vet=False, make_def_vet=False):
    """Build a PACKET_UNIT_COMBAT_INFO JSON string."""
    return json.dumps({
        'pid': PACKET_UNIT_COMBAT_INFO,
        'attacker_unit_id': attacker_id,
        'defender_unit_id': defender_id,
        'attacker_hp': att_hp,
        'defender_hp': def_hp,
        'make_att_veteran': make_att_vet,
        'make_def_veteran': make_def_vet,
    })


class TestCombatPacketHandler:
    """Tests for PACKET_UNIT_COMBAT_INFO parsing into combat_log."""

    def test_basic_combat_event_fields(self):
        """Injecting a combat packet populates all expected fields."""
        stub = _make_civcom_stub()
        stub.player_units = {
            10: {'type': 'Warriors', 'hp': 10, 'owner': 1},
        }
        stub.other_units = {
            20: {'type': 'Phalanx', 'hp': 10, 'owner': 2},
        }

        stub.parse_and_store_packet(_combat_packet(
            attacker_id=10, defender_id=20, att_hp=5, def_hp=0,
            make_att_vet=True, make_def_vet=False,
        ))

        assert len(stub.combat_log) == 1
        event = stub.combat_log[0]

        assert event['attacker_unit_id'] == 10
        assert event['defender_unit_id'] == 20
        assert event['attacker_unit_type'] == 'Warriors'
        assert event['defender_unit_type'] == 'Phalanx'
        assert event['attacker_hp_before'] == 10
        assert event['attacker_hp_after'] == 5
        assert event['defender_hp_before'] == 10
        assert event['defender_hp_after'] == 0
        assert event['attacker_won'] is True
        assert event['defender_won'] is False
        assert event['mutual_destruction'] is False
        assert event['make_att_veteran'] is True
        assert event['make_def_veteran'] is False
        assert event['turn'] == 5
        assert 'timestamp' in event

    def test_defender_won(self):
        """When attacker_hp=0 and defender_hp>0, defender_won is True."""
        stub = _make_civcom_stub()
        stub.player_units = {10: {'type': 'Warriors', 'hp': 10}}
        stub.other_units = {20: {'type': 'Phalanx', 'hp': 10}}

        stub.parse_and_store_packet(_combat_packet(att_hp=0, def_hp=7))

        event = stub.combat_log[0]
        assert event['attacker_won'] is False
        assert event['defender_won'] is True
        assert event['mutual_destruction'] is False

    def test_mutual_destruction(self):
        """When both HP reach 0, mutual_destruction is True."""
        stub = _make_civcom_stub()
        stub.player_units = {10: {'type': 'Warriors', 'hp': 10}}
        stub.other_units = {20: {'type': 'Phalanx', 'hp': 10}}

        stub.parse_and_store_packet(_combat_packet(att_hp=0, def_hp=0))

        event = stub.combat_log[0]
        assert event['attacker_won'] is False
        assert event['defender_won'] is False
        assert event['mutual_destruction'] is True

    def test_fog_of_war_unknown_units(self):
        """Units not in tracked state produce 'unknown' type and None hp_before."""
        stub = _make_civcom_stub()
        # Neither unit is tracked
        stub.player_units = {}
        stub.other_units = {}

        stub.parse_and_store_packet(_combat_packet(att_hp=5, def_hp=0))

        event = stub.combat_log[0]
        assert event['attacker_unit_type'] == 'unknown'
        assert event['defender_unit_type'] == 'unknown'
        assert event['attacker_hp_before'] is None
        assert event['defender_hp_before'] is None

    def test_missing_attacker_id_skips_event(self):
        """Packet with None attacker_unit_id is silently skipped."""
        stub = _make_civcom_stub()

        packet = json.dumps({
            'pid': PACKET_UNIT_COMBAT_INFO,
            'attacker_unit_id': None,
            'defender_unit_id': 20,
            'attacker_hp': 5,
            'defender_hp': 0,
        })
        stub.parse_and_store_packet(packet)

        assert len(stub.combat_log) == 0

    def test_missing_defender_id_skips_event(self):
        """Packet with None defender_unit_id is silently skipped."""
        stub = _make_civcom_stub()

        packet = json.dumps({
            'pid': PACKET_UNIT_COMBAT_INFO,
            'attacker_unit_id': 10,
            'defender_unit_id': None,
            'attacker_hp': 5,
            'defender_hp': 0,
        })
        stub.parse_and_store_packet(packet)

        assert len(stub.combat_log) == 0

    def test_missing_both_ids_skips_event(self):
        """Packet missing both unit ID fields entirely is skipped."""
        stub = _make_civcom_stub()

        packet = json.dumps({
            'pid': PACKET_UNIT_COMBAT_INFO,
            'attacker_hp': 5,
            'defender_hp': 0,
        })
        stub.parse_and_store_packet(packet)

        assert len(stub.combat_log) == 0

    def test_multiple_combat_events_accumulate(self):
        """Multiple combat packets accumulate in the deque."""
        stub = _make_civcom_stub()
        stub.player_units = {10: {'type': 'Warriors', 'hp': 10}}
        stub.other_units = {20: {'type': 'Phalanx', 'hp': 10}}

        stub.parse_and_store_packet(_combat_packet(att_hp=5, def_hp=0))
        stub.parse_and_store_packet(_combat_packet(att_hp=0, def_hp=7))
        stub.parse_and_store_packet(_combat_packet(att_hp=0, def_hp=0))

        assert len(stub.combat_log) == 3


class TestCombatLogDrain:
    """Tests for the _drain_combat_log helper and drain-on-read semantics."""

    def test_drain_moves_events_to_state(self):
        """_drain_combat_log moves events into state dict and clears the deque."""
        stub = _make_civcom_stub()
        stub.combat_log.append({'event': 'a'})
        stub.combat_log.append({'event': 'b'})

        state = {}
        stub._drain_combat_log(state)

        assert state['combat_log'] == [{'event': 'a'}, {'event': 'b'}]
        assert len(stub.combat_log) == 0

    def test_drain_empty_log_does_not_add_key(self):
        """Empty combat_log does not add 'combat_log' key to state."""
        stub = _make_civcom_stub()

        state = {}
        stub._drain_combat_log(state)

        assert 'combat_log' not in state

    def test_drain_is_one_shot(self):
        """First drain gets events; second drain gets nothing."""
        stub = _make_civcom_stub()
        stub.combat_log.append({'event': 'x'})

        state1 = {}
        stub._drain_combat_log(state1)
        assert 'combat_log' in state1
        assert len(state1['combat_log']) == 1

        state2 = {}
        stub._drain_combat_log(state2)
        assert 'combat_log' not in state2

    def test_drain_preserves_maxlen(self):
        """After drain, the new deque retains maxlen=500."""
        stub = _make_civcom_stub()
        stub.combat_log.append({'event': 'y'})

        state = {}
        stub._drain_combat_log(state)

        assert stub.combat_log.maxlen == 500
