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

# Core/common canonical codes
E_VALIDATION = "E400"            # Generic validation error (structure issues)
E_NOT_AUTHENTICATED = "E120"     # Not authenticated (session invalid or missing)
E_STATE_QUERY_FAILED = "E121"    # State query failed
E_CONNECTION_LOST = "E123"       # Connection to game server lost
E_UNKNOWN = "E999"               # Unknown error (with diagnostic context)

# HTTP-style mapping
E_UNAUTHORIZED = "E403"
E_NOT_FOUND = "E404"
E_RATE_LIMIT = "E429"            # Rate limit exceeded
E_INTERNAL = "E500"              # Internal server error

# Tactical codes (keep aligned with current validator usage)
E_TACTICAL_MISSING_OR_NOT_FOUND = "E109"  # Missing field or unit not found (validator usage)
E_TACTICAL_UNIT_BUSY = "E110"
E_TACTICAL_NO_MOVES = "E111"
E_TACTICAL_ADJACENT_REQUIRED = "E112"
E_TACTICAL_OWNER_OR_CAPABILITY = "E113"
E_TACTICAL_NOT_POSSIBLE = "E116"         # Server-authoritative action not possible

# Note:
# - Do NOT repurpose these canonical codes for different meanings in other layers.
# - If more granular codes are needed, allocate within the appropriate range and
#   update both this module and the protocol docs together.

# Backward-compatibility helpers (legacy -> canonical)
LEGACY_TO_CANONICAL = {
    # Proxy error_handler legacy mapping cleanup
    "E101": E_RATE_LIMIT,        # Old rate limit mapping -> E429
    "E140": E_CONNECTION_LOST,   # Old civserver connection mapping -> E123
}

def to_canonical(code: str) -> str:
    """Translate a legacy error code to its canonical value if needed."""
    return LEGACY_TO_CANONICAL.get(code, code)
