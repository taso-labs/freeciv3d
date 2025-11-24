"""
Freeciv Constants
"""

# Value Universals Type (VUT) - Requirement Types
# Based on freeciv/common/fc_types.h
VUT_ADVANCE = 1        # Tech
VUT_IMPROVEMENT = 3    # Building
VUT_MINSIZE = 12       # City Size

# Activity Type Constants
# Based on freeciv/common/fc_types.h enum unit_activity
# Used for PACKET_UNIT_CHANGE_ACTIVITY and unit state tracking
ACTIVITY_IDLE = 0
ACTIVITY_POLLUTION = 1       # Clean pollution (ACTRES_CLEAN_POLLUTION)
ACTIVITY_MINE = 2            # Mine action (deprecated in favor of actions)
ACTIVITY_IRRIGATE = 3        # Irrigate action (deprecated in favor of actions)
ACTIVITY_FORTIFIED = 4       # Has completed ACTIVITY_FORTIFYING
ACTIVITY_SENTRY = 5          # Server side client state (UI)
ACTIVITY_PILLAGE = 6         # Pillage action (ACTRES_PILLAGE)
ACTIVITY_GOTO = 7            # AI compatibility (not orders' goto)
ACTIVITY_EXPLORE = 8         # Server side agent
ACTIVITY_TRANSFORM = 9       # Transform terrain (ACTRES_TRANSFORM_TERRAIN)
ACTIVITY_FORTIFYING = 10     # Fortify action (ACTRES_FORTIFY)
ACTIVITY_FALLOUT = 11        # Clean fallout (ACTRES_CLEAN_FALLOUT)
ACTIVITY_BASE = 12           # Build base (ACTRES_BASE)
ACTIVITY_GEN_ROAD = 13       # Build road/railroad (ACTRES_ROAD)
ACTIVITY_CONVERT = 14        # Convert unit type (ACTRES_CONVERT)
ACTIVITY_CULTIVATE = 15      # Cultivate terrain (ACTRES_CULTIVATE)
ACTIVITY_PLANT = 16          # Plant terrain (ACTRES_PLANT)
ACTIVITY_CLEAN = 17          # Clean activity (ACTRES_CLEAN)

# Activities that indicate unit is busy and cannot take new actions
# Excludes IDLE, SENTRY, FORTIFIED, GOTO as these can be interrupted
BUSY_ACTIVITIES = [
    ACTIVITY_POLLUTION,      # 1
    ACTIVITY_MINE,           # 2
    ACTIVITY_IRRIGATE,       # 3
    ACTIVITY_PILLAGE,        # 6
    ACTIVITY_EXPLORE,        # 8
    ACTIVITY_TRANSFORM,      # 9
    ACTIVITY_FORTIFYING,     # 10
    ACTIVITY_FALLOUT,        # 11
    ACTIVITY_BASE,           # 12
    ACTIVITY_GEN_ROAD,       # 13
    ACTIVITY_CONVERT,        # 14
    ACTIVITY_CULTIVATE,      # 15
    ACTIVITY_PLANT,          # 16
    ACTIVITY_CLEAN,          # 17
]

# Extra Cause Constants
# Based on freeciv/common/fc_types.h enum extra_cause
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
EC_COUNT = 9           # Total number of extra causes in enum
EC_NONE = 9            # EC_COUNT - No specific cause
EC_SPECIAL = 10        # EC_NONE + 1
EC_DEFENSIVE = 11      # EC_NONE + 2
EC_NATURAL_DEFENSIVE = 12  # EC_NONE + 3
EC_NOT_AGGRESSIVE = 13  # EC_NONE + 4
EC_LAST = 14           # EC_NONE + 5

# Extra Removal Cause Constants
# Based on freeciv/common/fc_types.h enum extra_rmcause
# Used to identify what removes an extra (pillage, clean pollution, etc.)
ERM_PILLAGE = 0          # Removed by pillage
ERM_CLEAN = 1            # Removed by clean activity (generic)
ERM_CLEANFALLOUT = 2     # Removed by clean fallout activity
ERM_DISAPPEARANCE = 3    # Removed by disappearance
ERM_ENTER = 4            # Removed by unit entering tile
ERM_CLEANPOLLUTION = 5   # Removed by clean pollution activity
ERM_COUNT = 6            # Total number of removal causes
ERM_NONE = 6             # ERM_COUNT - No specific removal cause

# Action Type Constants - Transport Actions
# Based on freeciv/common/actions.h
ACTION_TRANSPORT_BOARD = 68     # Board a transport (adjacent tile)
ACTION_TRANSPORT_DEBOARD = 71   # Exit transport to adjacent tile
ACTION_TRANSPORT_EMBARK = 72    # Board transport on same tile
ACTION_TRANSPORT_UNLOAD = 83    # Unload cargo from transport

# Action Type Constants - Diplomacy and Strategic Actions
ACTION_ESTABLISH_EMBASSY = 0    # Establish embassy with another player
ACTION_AIRLIFT = 44             # Airlift unit between cities with airports

# Action Type Constants - Spy / Espionage & Trade
ACTION_SPY_INVESTIGATE_CITY = 2
ACTION_SPY_POISON = 4
ACTION_SPY_STEAL_GOLD = 6
ACTION_SPY_SABOTAGE_CITY = 8
ACTION_SPY_STEAL_TECH = 14
ACTION_SPY_INCITE_CITY = 18
ACTION_TRADE_ROUTE = 20
ACTION_SPY_BRIBE_UNIT = 23
