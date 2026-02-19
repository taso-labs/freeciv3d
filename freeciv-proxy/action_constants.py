"""
FreeCiv ACTION_* constants used by the proxy.

Values taken from FreeCiv upstream enums (match the ruleset used by the server).
This file centralizes action IDs so code can reference names instead of magic numbers.
"""

# General actions
ACTION_ESTABLISH_EMBASSY = 0

# Spy actions
ACTION_SPY_BRIBE_UNIT = 23
ACTION_SPY_INCITE_CITY = 18
ACTION_SPY_INVESTIGATE_CITY = 2
ACTION_SPY_NUKE = 31
ACTION_SPY_POISON = 4
ACTION_SPY_SABOTAGE_CITY = 8
ACTION_SPY_SPREAD_PLAGUE = 84
ACTION_SPY_STEAL_GOLD = 6
ACTION_SPY_STEAL_TECH = 14
ACTION_SPY_TARGETED_SABOTAGE_CITY = 10
ACTION_SPY_TARGETED_STEAL_TECH = 16
ACTION_STEAL_MAPS = 29

# Trade / city support
ACTION_TRADE_ROUTE = 20
ACTION_MARKETPLACE = 21
ACTION_HELP_WONDER = 22

# Capture / combat / conquest
ACTION_CAPTURE_UNITS = 24
ACTION_FOUND_CITY = 27
ACTION_JOIN_CITY = 28
ACTION_DISBAND_UNIT = 30
ACTION_HOME_CITY = 32
ACTION_NUKE = 33
ACTION_NUKE_CITY = 34
ACTION_NUKE_UNITS = 35
ACTION_CONQUER_CITY = 49
ACTION_CONQUER_EXTRAS = 86
ACTION_EXPEL_UNIT = 37
ACTION_HEAL_UNIT = 98
ACTION_ATTACK = 45
ACTION_SUICIDE_ATTACK = 46
ACTION_BOMBARD = 53

# Transport
ACTION_TRANSPORT_BOARD = 68
ACTION_TRANSPORT_EMBARK = 72
ACTION_TRANSPORT_DISEMBARK1 = 76
ACTION_TRANSPORT_LOAD3 = 82
ACTION_TRANSPORT_UNLOAD = 83

# Unit management
ACTION_UPGRADE_UNIT = 42
ACTION_AIRLIFT = 44
ACTION_PARADROP = 100
ACTION_PILLAGE = 65
ACTION_CULTIVATE = 64
ACTION_PLANT = 66

# User action placeholders (these are often used by web-client as filler)
ACTION_USER_ACTION1 = 113
ACTION_USER_ACTION2 = 114
ACTION_USER_ACTION3 = 115
ACTION_USER_ACTION4 = 116

# ACTION_COUNT is the sentinel value (one past the last action). Use cautiously —
# it may vary by FreeCiv version. Here we set it based on the above enumerations.
ACTION_COUNT = 117

# Semantic alias for 'no action' used in some packet constructions.
# Historically some clients use ACTION_COUNT to signal 'no action'; keep alias for clarity.
ACTION_NONE = ACTION_COUNT
