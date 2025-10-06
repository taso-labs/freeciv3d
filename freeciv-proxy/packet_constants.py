"""
FreeCiv Network Protocol Packet ID Constants

This module defines packet ID constants used in the FreeCiv network protocol.
All values are extracted from freeciv/freeciv/common/networking/packets.def

Packet Direction Notation:
- cs: Client to Server
- sc: Server to Client
- cs,sc: Bidirectional

Reference: freeciv/freeciv/common/networking/packets.def
"""

# =============================================================================
# CONNECTION AND AUTHENTICATION PACKETS
# =============================================================================

PACKET_PROCESSING_STARTED = 0  # sc - Server started processing
PACKET_PROCESSING_FINISHED = 1  # sc - Server finished processing

PACKET_SERVER_JOIN_REQ = 4  # cs - Client requests to join server
PACKET_SERVER_JOIN_REPLY = 5  # sc - Server responds to join request

PACKET_AUTHENTICATION_REQ = 6  # sc - Server requests authentication
PACKET_AUTHENTICATION_REPLY = 7  # cs - Client provides authentication

PACKET_SERVER_SHUTDOWN = 8  # sc - Server is shutting down

# CRITICAL: Connection info packet contains player_num assignment
# This is sent by server after successful join and before nation selection
PACKET_CONN_INFO = 115  # sc - Connection information (includes player_num)

PACKET_SERVER_INFO = 29  # sc - Server configuration information
PACKET_CONNECT_MSG = 27  # sc - Connection status message


# =============================================================================
# PLAYER MANAGEMENT PACKETS
# =============================================================================

# CRITICAL: Player selection and readiness flow
PACKET_NATION_SELECT_REQ = 10  # cs - Client selects nation (requires player_num)
PACKET_PLAYER_READY = 11  # cs - Player marks themselves as ready to start

# CRITICAL: Player info packet contains detailed player data
# Sent AFTER nation selection, not during initial connection
PACKET_PLAYER_INFO = 51  # sc - Detailed player information (post-nation-select)

PACKET_PLAYER_REMOVE = 50  # sc - Player has been removed
PACKET_PLAYER_PHASE_DONE = 52  # cs - Player finished their phase
PACKET_PLAYER_RATES = 53  # cs - Player tax/science/luxury rates
PACKET_PLAYER_CHANGE_GOVERNMENT = 54  # cs - Player changes government
PACKET_PLAYER_RESEARCH = 55  # cs - Player research selection
PACKET_PLAYER_TECH_GOAL = 56  # cs - Player technology goal
PACKET_PLAYER_ATTRIBUTE_BLOCK = 57  # cs - Player attributes (bulk)
PACKET_PLAYER_ATTRIBUTE_CHUNK = 58  # cs,sc - Player attributes (chunked)
PACKET_PLAYER_DIPLSTATE = 59  # sc - Player diplomatic state
PACKET_PLAYER_PLACE_INFRA = 61  # cs - Player places infrastructure
PACKET_PLAYER_MULTIPLIER = 242  # cs - Player multiplier settings


# =============================================================================
# GAME STATE PACKETS
# =============================================================================

PACKET_GAME_INFO = 16  # sc - Game configuration and state (was 24 in old code - INCORRECT!)
PACKET_GAME_LOAD = 163  # sc - Game loading information
PACKET_MAP_INFO = 17  # sc - Map dimensions and configuration
PACKET_TILE_INFO = 15  # sc - Individual tile information
PACKET_NUKE_TILE_INFO = 18  # sc - Nuclear attack on tile
PACKET_TEAM_NAME_INFO = 19  # sc - Team name information
PACKET_CALENDAR_INFO = 255  # sc - Calendar/turn information
PACKET_TIMEOUT_INFO = 244  # sc - Timeout settings
PACKET_ENDGAME_REPORT = 12  # sc - End of game report
PACKET_ENDGAME_PLAYER = 223  # sc - End of game player stats


# =============================================================================
# CHAT AND MESSAGING PACKETS
# =============================================================================

PACKET_CHAT_MSG = 25  # sc - Chat message from server (includes command responses)
PACKET_CHAT_MSG_REQ = 26  # cs - Chat message request from client
PACKET_EARLY_CHAT_MSG = 28  # sc - Early chat message (pre-game)


# =============================================================================
# UNIT PACKETS
# =============================================================================

PACKET_UNIT_INFO = 63  # sc - Complete unit information (was 95 in old code - INCORRECT!)
PACKET_UNIT_SHORT_INFO = 64  # sc - Abbreviated unit information
PACKET_UNIT_REMOVE = 62  # sc - Unit has been removed


# =============================================================================
# CITY PACKETS
# =============================================================================

PACKET_CITY_INFO = 31  # sc - Complete city information (was 85 in old code - INCORRECT!)
PACKET_CITY_SHORT_INFO = 32  # sc - Abbreviated city information
PACKET_CITY_REMOVE = 30  # sc - City has been removed
PACKET_CITY_NATIONALITIES = 46  # sc - City population nationalities
PACKET_CITY_UPDATE_COUNTERS = 514  # sc - City counter updates
PACKET_CITY_SELL = 33  # cs - Sell city building
PACKET_CITY_BUY = 34  # cs - Buy city production
PACKET_CITY_CHANGE = 35  # cs - Change city production/settings
PACKET_CITY_WORKLIST = 36  # cs - City work list
PACKET_CITY_MAKE_SPECIALIST = 37  # cs - Convert worker to specialist
PACKET_CITY_MAKE_WORKER = 38  # cs - Convert specialist to worker
PACKET_CITY_CHANGE_SPECIALIST = 39  # cs - Change specialist type
PACKET_CITY_RENAME = 40  # cs - Rename city
PACKET_CITY_OPTIONS_REQ = 41  # cs - City options request
PACKET_CITY_REFRESH = 42  # cs - Refresh city
PACKET_CITY_NAME_SUGGESTION_REQ = 43  # cs - Request city name suggestion
PACKET_CITY_NAME_SUGGESTION_INFO = 44  # sc - City name suggestion
PACKET_CITY_SABOTAGE_LIST = 45  # sc - Available sabotage options
PACKET_CITY_RALLY_POINT = 138  # cs,sc - City rally point
PACKET_WORKER_TASK = 241  # cs,sc - Worker task assignment


# =============================================================================
# RULESET PACKETS (Server Configuration)
# =============================================================================

# Nation ruleset - CRITICAL for nation ID mapping
PACKET_RULESET_NATION = 148  # sc - Nation definition (adjective, plural, rule_name)
PACKET_RULESET_NATION_SETS = 236  # sc - Nation sets
PACKET_RULESET_NATION_GROUPS = 147  # sc - Nation groups
PACKET_NATION_AVAILABILITY = 237  # sc - Which nations are available

# Other ruleset packets
PACKET_RULESETS_READY = 225  # sc - All rulesets loaded
PACKET_RULESET_CONTROL = 155  # sc - Ruleset control information
PACKET_RULESET_SUMMARY = 251  # sc - Ruleset summary
PACKET_RULESET_DESCRIPTION_PART = 247  # sc - Ruleset description (may be chunked)
PACKET_RULESET_GAME = 141  # sc - Game rules
PACKET_RULESET_TECH = 144  # sc - Technology definitions
PACKET_RULESET_TECH_CLASS = 9  # sc - Technology classes
PACKET_RULESET_TECH_FLAG = 234  # sc - Technology flags
PACKET_RULESET_GOVERNMENT = 145  # sc - Government types
PACKET_RULESET_GOVERNMENT_RULER_TITLE = 143  # sc - Government titles
PACKET_RULESET_TERRAIN_CONTROL = 146  # sc - Terrain control rules
PACKET_RULESET_UNIT = 140  # sc - Unit definitions
PACKET_RULESET_UNIT_BONUS = 228  # sc - Unit bonuses
PACKET_RULESET_UNIT_FLAG = 229  # sc - Unit flags
PACKET_RULESET_UNIT_CLASS = 152  # sc - Unit classes
PACKET_RULESET_UNIT_CLASS_FLAG = 230  # sc - Unit class flags
PACKET_RULESET_SPECIALIST = 142  # sc - Specialist types
PACKET_RULESET_CITY = 149  # sc - City rules
PACKET_RULESET_BUILDING = 150  # sc - Building definitions
PACKET_RULESET_IMPR_FLAG = 20  # sc - Improvement flags
PACKET_RULESET_TERRAIN = 151  # sc - Terrain types
PACKET_RULESET_TERRAIN_FLAG = 231  # sc - Terrain flags
PACKET_RULESET_EXTRA = 232  # sc - Extra (special) definitions
PACKET_RULESET_EXTRA_FLAG = 226  # sc - Extra flags
PACKET_RULESET_BASE = 153  # sc - Base definitions
PACKET_RULESET_ROAD = 220  # sc - Road definitions
PACKET_RULESET_GOODS = 248  # sc - Trade goods
PACKET_RULESET_DISASTER = 224  # sc - Disaster types
PACKET_RULESET_ACHIEVEMENT = 233  # sc - Achievement definitions
PACKET_RULESET_TRADE = 227  # sc - Trade rules
PACKET_RULESET_ACTION = 246  # sc - Action definitions
PACKET_RULESET_ACTION_ENABLER = 235  # sc - Action enablers
PACKET_RULESET_ACTION_AUTO = 252  # sc - Automatic actions
PACKET_RULESET_COUNTER = 513  # sc - Counter definitions
PACKET_RULESET_MUSIC = 240  # sc - Music sets
PACKET_RULESET_MULTIPLIER = 243  # sc - Multiplier settings
PACKET_RULESET_CLAUSE = 512  # sc - Treaty clause types
PACKET_RULESET_CHOICES = 162  # sc - Ruleset choices
PACKET_RULESET_SELECT = 171  # cs - Select ruleset
PACKET_RULESET_EFFECT = 175  # sc - Effect definitions
PACKET_RULESET_RESOURCE = 177  # sc - Resource definitions
PACKET_RULESET_STYLE = 239  # sc - City styles


# =============================================================================
# RESEARCH PACKETS
# =============================================================================

PACKET_RESEARCH_INFO = 60  # sc - Research progress information
PACKET_UNKNOWN_RESEARCH = 66  # sc - Unknown research state


# =============================================================================
# TRADE PACKETS
# =============================================================================

PACKET_TRADEROUTE_INFO = 249  # sc - Trade route information


# =============================================================================
# ACHIEVEMENT PACKETS
# =============================================================================

PACKET_ACHIEVEMENT_INFO = 238  # sc - Achievement status


# =============================================================================
# SPACESHIP PACKETS
# =============================================================================

# Note: Spaceship packets not yet extracted - add as needed


# =============================================================================
# WEB CLIENT SPECIFIC PACKETS
# =============================================================================

PACKET_WEB_RULESET_UNIT_ADDITION = 260  # sc - Web client unit additions


# =============================================================================
# EDIT MODE PACKETS
# =============================================================================

PACKET_EDIT_GAME = 218  # cs - Edit game (editor mode)


# =============================================================================
# PACKET ID VALIDATION
# =============================================================================

def get_packet_name(packet_id):
    """
    Get the human-readable name for a packet ID.

    Args:
        packet_id (int): The packet ID number

    Returns:
        str: The packet name, or "UNKNOWN_PACKET_{id}" if not found
    """
    # Build reverse lookup from this module's constants
    for name, value in globals().items():
        if name.startswith('PACKET_') and value == packet_id:
            return name
    return f"UNKNOWN_PACKET_{packet_id}"


def is_valid_packet_id(packet_id):
    """
    Check if a packet ID is defined in this module.

    Args:
        packet_id (int): The packet ID number

    Returns:
        bool: True if the packet ID is defined, False otherwise
    """
    return not get_packet_name(packet_id).startswith('UNKNOWN_PACKET_')


# =============================================================================
# NOTES ON PACKET ID CHANGES
# =============================================================================

# IMPORTANT CORRECTIONS from debugging session:
#
# 1. PACKET_PLAYER_INFO is pid=51, NOT pid=35
#    - pid=35 is PACKET_CITY_CHANGE
#    - This was a critical bug causing "player_id not found" errors
#
# 2. PACKET_CONN_INFO (pid=115) must be handled BEFORE PACKET_PLAYER_INFO
#    - Connection flow: JOIN_REQ → JOIN_REPLY → CONN_INFO → NATION_SELECT → PLAYER_INFO
#    - CONN_INFO contains the initial player_num assignment
#    - PLAYER_INFO only comes AFTER nation selection
#
# 3. Packet IDs from packets.def may differ from hardcoded values in old code
#    - Always verify against packets.def for the correct FreeCiv version
#    - Old code had incorrect assumptions about packet ordering
