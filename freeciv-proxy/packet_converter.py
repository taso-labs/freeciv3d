#!/usr/bin/env python3
"""
Standalone packet converter used by tests and by llm_handler to convert
LLM-style actions into FreeCiv packet dictionaries.
This module is intentionally free of Tornado/websocket dependencies so it
can be imported safely by unit tests.
"""

from typing import Dict, Any, Optional
from ruleset_mapper import RulesetMapper
from packet_constants import (
    PACKET_UNIT_ORDERS,
    PACKET_CITY_CHANGE,
    PACKET_PLAYER_RESEARCH,
    PACKET_PLAYER_PHASE_DONE,
    PACKET_UNIT_DO_ACTION,
    PACKET_UNIT_SERVER_SIDE_AGENT_SET,
    PACKET_UNIT_CHANGE_ACTIVITY,
    PACKET_CITY_BUY,
    PACKET_CITY_SELL,
    PACKET_CITY_RENAME,
    PACKET_CITY_WORKLIST,
    PACKET_DIPLOMACY_INIT_MEETING_REQ,
    PACKET_DIPLOMACY_CANCEL_MEETING_REQ,
    PACKET_DIPLOMACY_ACCEPT_TREATY_REQ,
    PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
    PACKET_DIPLOMACY_CANCEL_PACT,
    PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ,
)
from action_constants import *
from activity_constants import *
from order_constants import *
import re
from pathlib import Path

# Cache mapping pid -> allowed top-level field names parsed from Freeciv packets.def
_PACKET_FIELD_MAP = None


def _load_packet_field_map() -> dict:
    """Parse the Freeciv `packets.def` to extract allowed fields for each
    packet numeric id. Returns a mapping {pid: set(field_names)}.

    We only extract top-level field names (we do not recurse into struct
    members). The parser is intentionally simple but robust enough for the
    packet.def format used by Freeciv.
    """
    global _PACKET_FIELD_MAP
    if _PACKET_FIELD_MAP is not None:
        return _PACKET_FIELD_MAP

    field_map = {}
    packets_path = (
        Path(".")
        / ".."
        / "freeciv"
        / "freeciv"
        / "common"
        / "networking"
        / "packets.def"
    )
    try:
        with open(packets_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        # If we cannot load the file, fall back to empty map (no filtering)
        _PACKET_FIELD_MAP = {}
        return _PACKET_FIELD_MAP

    i = 0
    header_re = re.compile(r"^\s*(PACKET_[A-Z0-9_]+)\s*=\s*(\d+)\s*;")
    field_re = re.compile(r"^\s*([A-Za-z0-9_<>\[\]\(\)]+)\s+([^;]+);")
    while i < len(lines):
        line = lines[i]
        m = header_re.match(line)
        if m:
            pkt_name = m.group(1)
            pid = int(m.group(2))
            # parse following field lines until 'end'
            i += 1
            fields = set()
            while i < len(lines):
                l = lines[i].strip()
                i += 1
                if not l:
                    continue
                if l == "end":
                    break
                # skip comments
                if l.startswith("#") or l.startswith("//") or l.startswith("/*"):
                    continue
                fm = field_re.match(l)
                if fm:
                    names_part = fm.group(2)
                    # split by comma
                    for raw in names_part.split(","):
                        name = raw.strip()
                        # remove array specifiers like [10] or [20:len]
                        name = re.sub(r"\[.*\]", "", name)
                        # remove parentheses or pointers if any
                        name = name.split()[0]
                        # keep only identifier characters
                        name = re.sub(r"[^A-Za-z0-9_]+", "", name)
                        if name:
                            fields.add(name)
                # otherwise ignore complicated lines
            # always allow 'pid'
            fields.add("pid")
            field_map[pid] = fields
        else:
            i += 1

    _PACKET_FIELD_MAP = field_map
    return _PACKET_FIELD_MAP


def _sanitize_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Return a new packet containing only fields declared for the packet
    id in packets.def. If we can't find the pid mapping, return the packet
    unchanged.
    """
    try:
        pid = int(packet.get("pid"))
    except Exception:
        return packet

    field_map = _load_packet_field_map()
    allowed = field_map.get(pid)
    if not allowed:
        return packet

    filtered = {}
    for k, v in packet.items():
        if k in allowed:
            filtered[k] = v
    return filtered


def _get_unit_tile(unit_id: int, civcom: Optional[Any]) -> int:
    """Return unit tile index. If civcom is not provided, return -1 as a stub.
    Tests that previously exec()'d the method relied on -1 being used.
    """
    try:
        if civcom and hasattr(civcom, "get_unit_tile"):
            return civcom.get_unit_tile(unit_id)
    except Exception:
        pass
    return -1


def _convert_action_to_packet_impl(
    action: Dict[str, Any], civcom: Optional[Any] = None
) -> Dict[str, Any]:
    """Convert an action dict to a FreeCiv packet dict.

    This is a near drop-in replacement for the previous instance method
    _convert_action_to_packet. It uses the canonical constants from
    action_constants/activity_constants/order_constants and expects a
    RulesetMapper-capable civcom when mapping names to IDs.
    """
    action_type = action.get("type")

    # Default values (canonical upstream values from constants modules)
    # If civcom is provided and contains ruleset data, RulesetMapper will be used

    if action_type == "unit_move":
        # Accept both formats for flexibility:
        # 1. target: {"x": int, "y": int} (nested object format)
        # 2. dest_x, dest_y (flat coordinate format)
        # Internally normalize to dest_x, dest_y for consistency
        
        map_width = 80
        if (
            civcom
            and hasattr(civcom, "map_info")
            and civcom.map_info
            and civcom.map_info.get("width")
        ):
            map_width = civcom.map_info.get("width", 80)
        
        # Extract coordinates from either format
        dest_x = None
        dest_y = None
        
        # Try nested target format first
        target = action.get("target")
        if target and isinstance(target, dict) and "x" in target and "y" in target:
            dest_x = int(target["x"])
            dest_y = int(target["y"])
        # Try flat format
        elif "dest_x" in action and "dest_y" in action:
            dest_x = int(action["dest_x"])
            dest_y = int(action["dest_y"])
        else:
            raise ValueError(
                "unit_move requires either 'target' dict with 'x' and 'y' keys, "
                "or 'dest_x' and 'dest_y' integer fields"
            )
        
        dest_tile = dest_x + dest_y * map_width

        src_tile = _get_unit_tile(action.get("unit_id", -1), civcom)

        src_x = src_tile % map_width if src_tile >= 0 else 0
        src_y = src_tile // map_width if src_tile >= 0 else 0
        dx = dest_x - src_x
        dy = dest_y - src_y
        dx = max(-1, min(1, dx))
        dy = max(-1, min(1, dy))
        dir_map = {
            (-1, -1): 0,
            (0, -1): 1,
            (1, -1): 2,
            (-1, 0): 3,
            (1, 0): 4,
            (-1, 1): 5,
            (0, 1): 6,
            (1, 1): 7,
        }
        direction = dir_map.get((dx, dy), -1)
        if dx == 0 and dy == 0:
            direction = -1

        return _sanitize_packet(
            {
                "pid": PACKET_UNIT_ORDERS,
                "unit_id": action["unit_id"],
                "src_tile": src_tile,
                "dest_tile": dest_tile,
                "length": 1,
                "repeat": False,
                "vigilant": False,
                "orders": [
                    {
                        "order": ORDER_ACTION_MOVE,
                        "activity": ACTIVITY_LAST,
                        "target": 0,
                        "sub_target": 0,
                        "action": ACTION_NONE,
                        "dir": direction,
                    }
                ],
            }
        )

    elif action_type in ("city_production", "city_change_production"):
        production_name = action.get("production_type", "")
        if not production_name:
            raise ValueError("city_production requires 'production_type' field")
        mapper = RulesetMapper(civcom) if civcom else None
        if not mapper:
            # If no mapper available, tests generally provide production_kind/value
            kind = action.get("production_kind")
            value = action.get("production_value")
        else:
            if not hasattr(convert_action_to_packet, "_ruleset_mapper_cache"):
                convert_action_to_packet._ruleset_mapper_cache = mapper
            kind, value = mapper.map_production_to_kind_value(production_name)
            if kind is None:
                available = mapper.get_available_productions()
                raise ValueError(f"Unknown production: '{production_name}'")
        return _sanitize_packet(
            {
                "pid": PACKET_CITY_CHANGE,
                "city_id": action["city_id"],
                "production_kind": kind,
                "production_value": value,
            }
        )

    elif action_type == "tech_research":
        # Accept both canonical format (target: {"tech": "name"}) and
        # normalized format (tech_name: "name") from llm_handler normalization
        # A RulesetMapper (via civcom) is required to convert the name to an ID.
        tech_name = action.get("tech_name")
        if not tech_name:
            # Fall back to canonical format
            target = action.get("target")
            if isinstance(target, dict):
                tech_name = target.get("tech") or target.get("tech_name")
        if not tech_name:
            raise ValueError(
                "tech_research requires 'tech_name' or 'target.tech' with tech name string"
            )
        if not civcom:
            raise ValueError(
                "tech_research requires a civcom with ruleset info to map tech names to IDs"
            )
        mapper = RulesetMapper(civcom)
        tech_id = mapper.get_tech_id(tech_name)
        if tech_id is None:
            raise ValueError(f"Unknown technology '{tech_name}'")
        return _sanitize_packet({"pid": PACKET_PLAYER_RESEARCH, "tech": tech_id})

    elif action_type == "end_turn":
        turn = 1
        if civcom and hasattr(civcom, "game_turn"):
            turn = civcom.game_turn
        return _sanitize_packet({"pid": PACKET_PLAYER_PHASE_DONE, "turn": turn})

    elif action_type == "unit_build_city":
        unit_id = action["unit_id"]
        tile_id = _get_unit_tile(unit_id, civcom)
        city_name = action.get("name", f"City{unit_id}")
        return _sanitize_packet(
            {
                "pid": PACKET_UNIT_DO_ACTION,
                "action_type": ACTION_FOUND_CITY,
                "actor_id": unit_id,
                "target_id": tile_id,
                "sub_tgt_id": 0,
                "sub_target": 0,
                "name": city_name,
            }
        )

    elif action_type == "unit_explore":
        return _sanitize_packet(
            {
                "pid": PACKET_UNIT_SERVER_SIDE_AGENT_SET,
                "unit_id": action["unit_id"],
                "agent": 1,
            }
        )

    # Unit activity changes
    elif action_type == "unit_fortify":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_FORTIFYING,
            "target": -1,
        }
    elif action_type == "unit_sentry":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_SENTRY,
            "target": -1,
        }
    elif action_type == "unit_build_road":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_GEN_ROAD,
            "target": -1,
        }
    elif action_type == "unit_build_irrigation":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_IRRIGATE,
            "target": -1,
        }
    elif action_type == "unit_build_mine":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_MINE,
            "target": -1,
        }

    # Combat and many unit actions follow similar pattern
    elif action_type in (
        "unit_attack",
        "unit_suicide_attack",
        "unit_bombard",
        "unit_capture",
        "unit_conquer_city",
        "unit_nuke",
        "unit_nuke_city",
        "unit_nuke_units",
        "unit_expel",
        "unit_heal",
    ):
        action_map = {
            "unit_attack": ACTION_ATTACK,
            "unit_suicide_attack": ACTION_SUICIDE_ATTACK,
            "unit_bombard": ACTION_BOMBARD,
            "unit_capture": ACTION_CAPTURE_UNITS,
            "unit_conquer_city": ACTION_CONQUER_CITY,
            "unit_nuke": ACTION_NUKE,
            "unit_nuke_city": ACTION_NUKE_CITY,
            "unit_nuke_units": ACTION_NUKE_UNITS,
            "unit_expel": ACTION_EXPEL_UNIT,
            "unit_heal": ACTION_HEAL_UNIT,
        }
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("target_id", action.get("tile_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", action.get("extra_id", -1)),
            "sub_target": action.get("sub_tgt_id", action.get("extra_id", -1)),
            "name": "",
            "action_type": action_map[action_type],
        }

    # Terrain improvement actions
    elif action_type == "unit_pillage":
        # pillage passes an extra_id to indicate what to pillage; include as sub_target
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("tile_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", action.get("extra_id", -1)),
            "sub_target": action.get("sub_tgt_id", action.get("extra_id", -1)),
            "name": "",
            "action_type": ACTION_PILLAGE,
        }

    # Transport
    elif action_type == "unit_board":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("transport_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_TRANSPORT_BOARD,
        }
    elif action_type == "unit_embark":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("transport_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_TRANSPORT_EMBARK,
        }
    elif action_type == "unit_disembark":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("tile_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_TRANSPORT_DISEMBARK1,
        }
    elif action_type == "unit_unload":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action.get("transport_id", action["unit_id"]),
            "target_id": action.get("cargo_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_TRANSPORT_UNLOAD,
        }
    elif action_type == "unit_airlift":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_AIRLIFT,
        }
    elif action_type == "unit_paradrop":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("tile_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_PARADROP,
        }

    # Espionage
    elif action_type == "spy_investigate_city":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_SPY_INVESTIGATE_CITY,
        }
    elif action_type == "spy_poison":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_SPY_POISON,
        }
    elif action_type == "spy_sabotage_city":
        sub = action.get("building_id", -1)
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": sub,
            "sub_target": sub,
            "name": "",
            "action_type": ACTION_SPY_SABOTAGE_CITY,
        }
    elif action_type == "spy_targeted_sabotage_city":
        sub = action.get("building_id")
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": sub,
            "sub_target": sub,
            "name": "",
            "action_type": ACTION_SPY_TARGETED_SABOTAGE_CITY,
        }
    elif action_type == "spy_steal_tech":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_SPY_STEAL_TECH,
        }
    elif action_type == "spy_targeted_steal_tech":
        tech = action.get("tech_id")
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": tech,
            "sub_target": tech,
            "name": "",
            "action_type": ACTION_SPY_TARGETED_STEAL_TECH,
        }
    elif action_type == "spy_incite_city":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_SPY_INCITE_CITY,
        }
    elif action_type == "spy_bribe_unit":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("target_unit_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_SPY_BRIBE_UNIT,
        }
    elif action_type == "establish_embassy":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_ESTABLISH_EMBASSY,
        }
    elif action_type == "spy_steal_gold":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            # Use canonical upstream action ID for spy_steal_gold
            "action_type": ACTION_SPY_STEAL_GOLD,
        }
    elif action_type == "spy_spread_plague":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_SPY_SPREAD_PLAGUE,
        }
    elif action_type == "spy_nuke_city":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            # Use canonical spy nuke action id
            "action_type": ACTION_SPY_NUKE,
        }

    # Trade
    elif action_type == "unit_trade_route":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_TRADE_ROUTE,
        }
    elif action_type == "unit_marketplace":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_MARKETPLACE,
        }
    elif action_type == "unit_help_wonder":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_HELP_WONDER,
        }

    # Diplomacy – use numeric packet IDs for these as in existing code
    elif action_type == "diplomacy_start_negotiation":
        return {"pid": PACKET_DIPLOMACY_INIT_MEETING_REQ, "counterpart": action["player_id"]}
    elif action_type == "diplomacy_cancel_meeting":
        return {"pid": PACKET_DIPLOMACY_CANCEL_MEETING_REQ, "counterpart": action["player_id"]}
    elif action_type == "diplomacy_accept_treaty":
        # Accept treaty should use the ACCEPT_TREATY request packet
        return {"pid": PACKET_DIPLOMACY_ACCEPT_TREATY_REQ, "counterpart": action["player_id"]}
    elif action_type == "diplomacy_cancel_pact":
        clause_type = action.get("clause_type", 6)
        return {
            "pid": PACKET_DIPLOMACY_CANCEL_PACT,
            "other_player_id": action["player_id"],
            "clause": clause_type,
        }
    elif action_type == "diplomacy_declare_war":
        return {"pid": PACKET_DIPLOMACY_CANCEL_PACT, "other_player_id": action["player_id"], "clause": 5}
    elif action_type == "diplomacy_propose_ceasefire":
        return {
            "pid": PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
            "counterpart": action["player_id"],
            "giver": action.get("giver", -1),
            "type": 5,
            "value": 0,
        }
    elif action_type == "diplomacy_propose_peace":
        return {
            "pid": PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
            "counterpart": action["player_id"],
            "giver": action.get("giver", -1),
            "type": 6,
            "value": 0,
        }
    elif action_type == "diplomacy_propose_alliance":
        return {
            "pid": PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
            "counterpart": action["player_id"],
            "giver": action.get("giver", -1),
            "type": 7,
            "value": 0,
        }
    elif action_type == "diplomacy_share_vision":
        return {
            "pid": PACKET_DIPLOMACY_CREATE_CLAUSE_REQ,
            "counterpart": action["player_id"],
            "giver": action.get("giver", -1),
            "type": 8,
            "value": 0,
        }
    elif action_type == "diplomacy_withdraw_vision":
        # Use REMOVE_CLAUSE request packet (pid 101) for withdrawing vision
        return {
            "pid": PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ,
            "counterpart": action["player_id"],
            "giver": action.get("giver", -1),
            "type": 8,
            "value": 0,
        }

    # City actions
    elif action_type == "city_buy":
        return {"pid": PACKET_CITY_BUY, "city_id": action["city_id"]}
    elif action_type == "city_sell_improvement":
        return {
            "pid": PACKET_CITY_SELL,
            "city_id": action["city_id"],
            "build_id": action["improvement_id"],
        }
    elif action_type == "city_unload":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action.get("unit_id", -1),
            "activity": ACTIVITY_IDLE,
            "target": -1,
        }
    elif action_type == "city_rename":
        return {
            "pid": PACKET_CITY_RENAME,
            "city_id": action["city_id"],
            "name": action["name"],
        }
    elif action_type == "city_worklist":
        return {
            "pid": PACKET_CITY_CHANGE,
            "city_id": action["city_id"],
            "production_kind": action.get("production_kind", 0),
            "production_value": action.get("production_value", 0),
        }

    # Additional unit actions
    elif action_type == "unit_upgrade":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_UPGRADE_UNIT,
        }
    elif action_type == "unit_join_city":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_JOIN_CITY,
        }
    elif action_type == "unit_clean_pollution":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_POLLUTION,
            "target": action.get("tile_id", -1),
        }
    elif action_type == "unit_clean_fallout":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_FALLOUT,
            "target": action.get("tile_id", -1),
        }
    elif action_type == "unit_transform":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_TRANSFORM,
            "target": -1,
        }
    elif action_type == "unit_cultivate":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("tile_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_CULTIVATE,
        }
    elif action_type == "unit_plant":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("tile_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_PLANT,
        }
    elif action_type == "unit_disband":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("target_id", -1),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_DISBAND_UNIT,
        }
    elif action_type == "unit_home_city":
        return {
            "pid": PACKET_UNIT_DO_ACTION,
            "actor_id": action["unit_id"],
            "target_id": action.get("city_id", action.get("target_id", -1)),
            "sub_tgt_id": action.get("sub_tgt_id", -1),
            "sub_target": action.get("sub_tgt_id", -1),
            "name": "",
            "action_type": ACTION_HOME_CITY,
        }
    elif action_type == "unit_wake":
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_IDLE,
            "target": -1,
        }
    elif action_type == "unit_skip":
        # unit_skip makes unit idle for current turn (same as unit_wake)
        return {
            "pid": PACKET_UNIT_CHANGE_ACTIVITY,
            "unit_id": action["unit_id"],
            "activity": ACTIVITY_IDLE,
            "target": -1,
        }
    elif action_type == "unit_auto_worker":
        return {
            "pid": PACKET_UNIT_SERVER_SIDE_AGENT_SET,
            "unit_id": action["unit_id"],
            "agent": 1,
        }

    # Fallback: return original action unchanged
    return action


def convert_action_to_packet(
    action: Dict[str, Any], civcom: Optional[Any] = None
) -> Dict[str, Any]:
    """Public wrapper: call implementation then sanitize top-level fields
    according to packets.def so the server won't disconnect on unexpected
    fields.
    """
    res = _convert_action_to_packet_impl(action, civcom)
    if isinstance(res, dict) and "pid" in res:
        return _sanitize_packet(res)
    return res
