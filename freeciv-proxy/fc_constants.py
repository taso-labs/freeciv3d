"""
Freeciv Constants
"""

# Value Universals Type (VUT) - Requirement Types
# Based on freeciv/common/fc_types.h
VUT_ADVANCE = 1        # Tech
VUT_IMPROVEMENT = 3    # Building
VUT_MINSIZE = 12       # City Size

# Activity Type Constants
# Based on freeciv/common/unit.h enum unit_activity
# Used for PACKET_UNIT_CHANGE_ACTIVITY and unit state tracking
ACTIVITY_IDLE = 0
ACTIVITY_POLLUTION = 1      # Clean pollution
ACTIVITY_ROAD = 2            # Build road (deprecated, use ACTIVITY_GEN_ROAD)
ACTIVITY_MINE = 3            # Build mine (deprecated, use ACTIVITY_IRRIGATE with mine target)
ACTIVITY_IRRIGATE = 4        # Build irrigation (deprecated, use ACTIVITY_IRRIGATE with irrigation target)
ACTIVITY_FORTIFIED = 5
ACTIVITY_FORTRESS = 6        # Build fortress (deprecated, use ACTIVITY_BASE)
ACTIVITY_SENTRY = 7
ACTIVITY_RAILROAD = 8        # Build railroad (deprecated, use ACTIVITY_GEN_ROAD)
ACTIVITY_PILLAGE = 9
ACTIVITY_GOTO = 10
ACTIVITY_EXPLORE = 11
ACTIVITY_TRANSFORM = 12      # Transform terrain
ACTIVITY_AIRBASE = 13        # Build airbase (deprecated, use ACTIVITY_BASE)
ACTIVITY_FORTIFYING = 14
ACTIVITY_FALLOUT = 15        # Clean fallout
ACTIVITY_PATROL = 16
ACTIVITY_BASE = 17           # Build base (fortress/airbase)
ACTIVITY_GEN_ROAD = 20       # Build road/railroad (modern, with target extra)

# Activities that indicate unit is busy and cannot take new actions
# Excludes IDLE, SENTRY, FORTIFIED, GOTO as these can be interrupted
BUSY_ACTIVITIES = [
    ACTIVITY_POLLUTION,
    ACTIVITY_ROAD,
    ACTIVITY_MINE,
    ACTIVITY_IRRIGATE,
    ACTIVITY_FORTRESS,
    ACTIVITY_RAILROAD,
    ACTIVITY_PILLAGE,
    ACTIVITY_EXPLORE,
    ACTIVITY_TRANSFORM,
    ACTIVITY_AIRBASE,
    ACTIVITY_FORTIFYING,
    ACTIVITY_FALLOUT,
    ACTIVITY_PATROL,
    ACTIVITY_BASE,
    ACTIVITY_GEN_ROAD,
]

# Extra Cause Constants
# Based on freeciv/common/extras.h enum extra_cause
# Used to identify what creates an extra (irrigation, mine, road, pollution, etc.)
EC_IRRIGATION = 0
EC_MINE = 1
EC_ROAD = 2
EC_BASE = 3
EC_POLLUTION = 4
EC_FALLOUT = 5
EC_HUT = 6
EC_APPEARANCE = 7
EC_RESOURCE = 8
EC_SPECIAL = 9
EC_NONE = 10

# Extra Removal Cause Constants
# Based on freeciv/common/extras.h enum extra_rmcause
# Used to identify what removes an extra (pillage, clean pollution, etc.)
ERM_ENTER = 0            # Removed by unit entering tile
ERM_CLEAN = 1            # Removed by clean activity (generic)
ERM_PILLAGE = 2          # Removed by pillage
ERM_CLEANPOLLUTION = 3   # Removed by clean pollution activity
ERM_CLEANFALLOUT = 4     # Removed by clean fallout activity
ERM_NONE = 5
