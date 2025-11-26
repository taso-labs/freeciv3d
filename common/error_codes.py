#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Canonical error code definitions for both llm_gateway and freeciv-proxy.

This module centralizes protocol error codes so both components use the same
values and semantics. Keep these aligned with docs/llm_websocket_protocol.md.

Ranges (per protocol spec):
- E001–E099: Core/common (structure, capability, lookup)
- E100–E199: Unit/city tactical
- E200–E299: Economy/production
- E300–E309: Session/lifecycle
- E310–E349: Diplomacy/relations
- E350–E399: Transport/logistics
- E400–E449: Espionage/covert
- E500–E549: Action queries & server-side
- E900–E999: System/internal
"""

# ============================================================================
# Core/common validation errors (E001-E099)
# ============================================================================

# Action structure validation (E001-E005)
E_INVALID_STRUCTURE = "E001"           # Action must be a dictionary
E_MISSING_TYPE = "E002"                # Action must specify a type
E_UNKNOWN_ACTION = "E003"              # Unknown action type
E_ACTION_NOT_PERMITTED = "E004"        # Action type not permitted for agent
E_PLAYER_MISMATCH = "E005"             # Action player_id doesn't match authenticated player

# Unit movement errors (E010-E014)
E_MOVE_MISSING_UNIT = "E010"           # Unit move requires unit_id
E_MOVE_NOT_OWNER = "E011"              # Player does not own this unit
E_MOVE_UNIT_BUSY = "E012"              # Unit is busy or has no moves left
E_MOVE_INVALID_DEST = "E013"           # Invalid destination (missing coords or direction)
E_MOVE_TILE_OCCUPIED = "E014"          # Destination tile is occupied

# Build city errors (E020-E023)
E_BUILD_CITY_MISSING_UNIT = "E020"     # Build city requires unit_id
E_BUILD_CITY_NOT_OWNER = "E021"        # Player does not own this unit
E_BUILD_CITY_CANNOT = "E022"           # Unit cannot build cities
E_BUILD_CITY_NOT_FOUND = "E023"        # Unit not found

# City production errors (E030-E033)
E_PRODUCTION_NOT_FOUND = "E030"        # City not found
E_PRODUCTION_NOT_OWNER = "E031"        # Player does not own this city
E_PRODUCTION_INVALID_TYPE = "E032"     # Invalid production type
E_PRODUCTION_MISSING_FIELD = "E033"    # Missing required field

# Tech research errors (E040-E041)
E_TECH_MISSING_NAME = "E040"           # Tech research requires tech_name
E_TECH_INVALID = "E041"                # Invalid or unavailable tech

# Unit fortify errors (E050-E052)
E_FORTIFY_MISSING_UNIT = "E050"        # Unit fortify requires unit_id
E_FORTIFY_NOT_FOUND = "E051"           # Unit not found
E_FORTIFY_NOT_OWNER = "E052"           # Player does not own unit

# Unit sentry errors (E060-E062)
E_SENTRY_MISSING_UNIT = "E060"         # Unit sentry requires unit_id
E_SENTRY_NOT_FOUND = "E061"            # Unit not found
E_SENTRY_NOT_OWNER = "E062"            # Player does not own unit

# Build road errors (E070-E072)
E_ROAD_MISSING_FIELD = "E070"          # Missing unit_id or coordinates
E_ROAD_NOT_OWNER = "E071"              # Player does not own unit
E_ROAD_INVALID = "E072"                # Unit busy, no moves, or coords out of bounds

# Build irrigation errors (E080-E082)
E_IRRIGATION_MISSING_FIELD = "E080"    # Missing unit_id or coordinates
E_IRRIGATION_NOT_OWNER = "E081"        # Player does not own unit
E_IRRIGATION_INVALID = "E082"          # Unit has no moves or coords out of bounds

# Build mine errors (E090-E092)
E_MINE_MISSING_FIELD = "E090"          # Missing unit_id or coordinates
E_MINE_NOT_OWNER = "E091"              # Player does not own unit
E_MINE_INVALID = "E092"                # Unit has no moves or coords out of bounds

# ============================================================================
# Unit/city tactical errors (E100-E199)
# ============================================================================

# Terrain cleanup/transform (E100-E108)
E_CLEAN_POLLUTION_MISSING = "E100"     # Clean pollution requires unit_id
E_CLEAN_POLLUTION_NOT_OWNER = "E101"   # Player does not own unit
E_CLEAN_POLLUTION_NOT_FOUND = "E102"   # Unit not found
E_CLEAN_FALLOUT_MISSING = "E103"       # Clean fallout requires unit_id
E_CLEAN_FALLOUT_NOT_OWNER = "E104"     # Player does not own unit
E_CLEAN_FALLOUT_NOT_FOUND = "E105"     # Unit not found
E_TRANSFORM_MISSING = "E106"           # Transform terrain requires unit_id
E_TRANSFORM_NOT_OWNER = "E107"         # Player does not own unit
E_TRANSFORM_NOT_FOUND = "E108"         # Unit not found

# Tactical unit operations (E109-E116) - Core tactical errors used across actions
E_TACTICAL_MISSING_OR_NOT_FOUND = "E109"  # Missing field or unit/actor not found
E_TACTICAL_UNIT_BUSY = "E110"             # Unit is busy
E_TACTICAL_NO_MOVES = "E111"              # Unit has no movement points or attacks left
E_TACTICAL_ADJACENT_REQUIRED = "E112"     # Target not adjacent (for non-ranged)
E_TACTICAL_OWNER_OR_CAPABILITY = "E113"   # Not owner or unit lacks capability
E_TACTICAL_RESERVED = "E114"              # Reserved for future use
E_TACTICAL_INVALID_TARGET = "E115"        # Invalid target (unit/city/tile)
E_TACTICAL_NOT_POSSIBLE = "E116"          # Server-authoritative action not possible

# Government change errors (E117-E122)
E_GOV_MISSING_NAME = "E117"            # Government change requires government_name
E_GOV_UNRECOGNIZED = "E118"            # Unrecognized government
E_GOV_ALREADY_ACTIVE = "E119"          # Government already active
E_GOV_NOT_AVAILABLE = "E120"           # Government not yet available (NOTE: conflicts with E_NOT_AUTHENTICATED)
E_GOV_REVOLUTION_COOLDOWN = "E121"     # Cannot change during revolution cooldown
E_GOV_DATA_UNAVAILABLE = "E122"        # Government data unavailable

# Disband unit errors (E123-E125)
E_DISBAND_MISSING = "E123"             # Disband unit requires unit_id (NOTE: conflicts with E_CONNECTION_LOST)
E_DISBAND_NOT_OWNER = "E124"           # Player does not own unit
E_DISBAND_NOT_FOUND = "E125"           # Unit not found

# Join city errors (E126-E130)
E_JOIN_MISSING_FIELD = "E126"          # Join city requires unit_id and city_id
E_JOIN_NOT_OWNER_UNIT = "E127"         # Player does not own unit
E_JOIN_NOT_FOUND_UNIT = "E128"         # Unit not found
E_JOIN_CANNOT = "E129"                 # Unit type cannot join city
E_JOIN_CITY_ISSUE = "E130"             # City not found or not owned by player

# City specialist errors (E131-E135)
E_SPECIALIST_MISSING_FIELD = "E131"    # Missing city_id, from_specialist, or to_specialist
E_SPECIALIST_CITY_NOT_FOUND = "E132"   # City not found
E_SPECIALIST_NOT_OWNER = "E133"        # City not owned by player
E_SPECIALIST_INVALID_FROM = "E134"     # Invalid from_specialist
E_SPECIALIST_INVALID_TO = "E135"       # Invalid to_specialist

# City sell improvement errors (E142-E144)
E_SELL_MISSING_FIELD = "E142"          # Missing city_id or improvement identifier
E_SELL_CITY_ISSUE = "E143"             # City not found or not owned
E_SELL_IMPROVEMENT_ISSUE = "E144"      # Improvement not present, unsellable, or already sold

# Cultivate errors (E145-E147)
E_CULTIVATE_MISSING = "E145"           # Cultivate requires unit_id
E_CULTIVATE_NOT_OWNER = "E146"         # Player does not own unit or unit not found
E_CULTIVATE_INVALID = "E147"           # Unit busy or has no moves left

# Plant errors (E148-E150)
E_PLANT_MISSING = "E148"               # Plant requires unit_id
E_PLANT_NOT_OWNER = "E149"             # Player does not own unit or unit not found
E_PLANT_INVALID = "E150"               # Unit busy or has no moves left

# Build base errors (E151-E153)
E_BASE_MISSING = "E151"                # Base requires unit_id
E_BASE_NOT_OWNER = "E152"              # Player does not own unit or unit not found
E_BASE_INVALID = "E153"                # Unit busy or has no moves left

# Authentication/session errors (NOTE: Session codes moved to avoid conflicts)
E_NOT_AUTHENTICATED = "E902"           # Not authenticated (session invalid or missing) - MOVED from E120
E_STATE_QUERY_FAILED = "E903"          # State query failed - MOVED from E121
E_CONNECTION_LOST = "E904"             # Connection to game server lost - MOVED from E123

# ============================================================================
# Economy/production errors (E200-E299)
# ============================================================================

# City buy errors (E201-E204)
E_BUY_INSUFFICIENT_GOLD = "E201"       # Insufficient gold
E_BUY_CITY_ISSUE = "E202"              # Invalid city, city not found, or not owned
E_BUY_NOTHING_TO_BUY = "E203"          # Production queue empty or nothing to buy
E_BUY_UNAVAILABLE = "E204"             # Purchase unavailable

# Upgrade unit errors (E205-E206)
E_UPGRADE_UNAVAILABLE = "E205"         # No upgrade path available
E_UPGRADE_INSUFFICIENT_GOLD = "E206"   # Insufficient gold for upgrade

# Security errors (E200 used by old error_handler - avoid conflicts)
# Consider moving to E9xx range if needed

# ============================================================================
# Session/lifecycle errors (E300-E309)
# ============================================================================

E_SESSION_WRONG_PHASE = "E300"         # Cannot ready up in current phase
E_SESSION_ALREADY_READY = "E301"       # Player already marked ready (idempotent)
E_SESSION_NOT_ENOUGH_PLAYERS = "E302"  # Not enough players to start
E_SESSION_PLAYER_NOT_FOUND = "E303"    # Player not found in game state
E_SESSION_UNKNOWN = "E304"             # Unknown session error

# ============================================================================
# Diplomacy/relations errors (E310-E349)
# ============================================================================

E_EMBASSY_MISSING_FIELD = "E310"       # Missing unit_id or target_city_id
E_EMBASSY_UNIT_ISSUE = "E311"          # Unit not found or not owned
E_EMBASSY_CANNOT = "E312"              # Unit cannot establish embassies

# ============================================================================
# Transport/logistics errors (E350-E399)
# ============================================================================

# Transport board/deboard/unload (E350-E353)
E_TRANSPORT_UNIT_NOT_FOUND = "E350"    # Unit (cargo) not found
E_TRANSPORT_NOT_FOUND = "E351"         # Transport not found
E_TRANSPORT_NOT_OWNER = "E352"         # Not owner of unit/transport
E_TRANSPORT_CAPACITY_OR_NOT_ON = "E353" # Transport at full capacity or unit not on transport

# Airlift errors (E354-E356)
E_AIRLIFT_UNIT_NOT_FOUND = "E354"      # Unit not found
E_AIRLIFT_CITY_NOT_FOUND = "E355"      # Target city not found
E_AIRLIFT_NOT_OWNER = "E356"           # Not owner of unit

# ============================================================================
# Espionage/covert errors (E400-E449)
# ============================================================================

E_VALIDATION = "E400"                  # Generic validation error (structure issues)
E_SPY_WOULD_BE_DETECTED = "E400"       # Mission would be detected (same as E_VALIDATION for now)
E_SPY_WOULD_FAIL = "E401"              # Mission would fail according to server
E_SPY_NOT_SPY = "E402"                 # Unit is not a diplomat or spy
E_SPY_INSUFFICIENT_GOLD = "E403"       # Insufficient gold for bribe/incite (NOTE: conflicts with E_UNAUTHORIZED)
E_TRADE_NOT_TRADER = "E410"            # Unit cannot create trade routes

# ============================================================================
# HTTP-style/system errors (E400s, E500s, E900s)
# ============================================================================

# HTTP-style codes
E_UNAUTHORIZED = "E403"                # Unauthorized (conflicts with E_SPY_INSUFFICIENT_GOLD)
E_NOT_FOUND = "E404"                   # Not found
E_RATE_LIMIT = "E429"                  # Rate limit exceeded
E_INTERNAL = "E500"                    # Internal server error

# System/internal errors (E900-E999)
E_UNKNOWN = "E999"                     # Unknown error (with diagnostic context)

# Phase 8 action errors (E600-E699) - From test_phase8_actions.py
# Note: These appear to be test-specific codes that may need review
E_PHASE8_BASE = "E600"                 # Base phase 8 error codes start here
# E600-E605, E610-E616, E620-E624, E630-E636, E640-E642, E650-E655 used in tests

# ============================================================================
# Backward-compatibility helpers (legacy -> canonical)
# ============================================================================

LEGACY_TO_CANONICAL = {
    # Old authentication codes that conflicted with tactical codes
    "E120": "E902",  # E_NOT_AUTHENTICATED moved
    "E121": "E903",  # E_STATE_QUERY_FAILED moved
    "E123": "E904",  # E_CONNECTION_LOST moved
    
    # Proxy error_handler legacy mapping cleanup
    "E101": E_RATE_LIMIT,        # Old rate limit mapping -> E429
    "E140": "E904",              # Old civserver connection mapping -> E904 (was E123)
}

def to_canonical(code: str) -> str:
    """Translate a legacy error code to its canonical value if needed."""
    return LEGACY_TO_CANONICAL.get(code, code)
