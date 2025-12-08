"""
FreeCiv ACTIVITY_* constants used by the proxy.

Centralizes activity enum values to avoid magic numbers in the codebase.
"""

ACTIVITY_IDLE = 0
# POLLUTION/cleanup activity (value 7 in FreeCiv enums)
ACTIVITY_POLLUTION = 7
ACTIVITY_MINE = 2
ACTIVITY_IRRIGATE = 3
ACTIVITY_SENTRY = 5
ACTIVITY_TRANSFORM = 8
ACTIVITY_FORTIFYING = 10
ACTIVITY_FALLOUT = 11
ACTIVITY_GEN_ROAD = 13
# ACTIVITY_LAST is used by the web client as a filler value in some packet fields
ACTIVITY_LAST = 18
