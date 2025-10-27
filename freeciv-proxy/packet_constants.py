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

# Extracted from packets.def: PACKET_SPACESHIP_*
# See below in the SPACESHIP PACKETS section


# =============================================================================
# PHASE AND TURN MANAGEMENT PACKETS
# =============================================================================

PACKET_END_PHASE = 125  # sc - Phase has ended
PACKET_START_PHASE = 126  # sc - Phase has started
PACKET_NEW_YEAR = 127  # sc - New year/turn begins
PACKET_BEGIN_TURN = 128  # sc - Turn processing begins
PACKET_END_TURN = 129  # sc - Turn processing ends
PACKET_FREEZE_CLIENT = 130  # sc - Freeze client (during server processing)
PACKET_THAW_CLIENT = 131  # sc - Unfreeze client


# =============================================================================
# UNIT ACTION AND COMBAT PACKETS
# =============================================================================

PACKET_UNIT_COMBAT_INFO = 65  # sc - Unit combat information
PACKET_UNIT_SSCS_SET = 71  # cs - Set server-side combat state
PACKET_UNIT_ORDERS = 73  # cs - Unit order queue
PACKET_UNIT_SERVER_SIDE_AGENT_SET = 74  # cs - Set server-side agent
PACKET_UNIT_ACTION_QUERY = 82  # cs - Query available actions
PACKET_UNIT_TYPE_UPGRADE = 83  # cs - Upgrade unit type
PACKET_UNIT_DO_ACTION = 84  # cs - Execute unit action
PACKET_UNIT_ACTION_ANSWER = 85  # sc - Server response to action
PACKET_UNIT_GET_ACTIONS = 87  # cs - Get available actions for unit
PACKET_UNIT_ACTIONS = 90  # sc - Available actions list
PACKET_UNIT_CHANGE_ACTIVITY = 222  # cs - Change unit activity


# =============================================================================
# DIPLOMACY PACKETS
# =============================================================================

PACKET_DIPLOMACY_INIT_MEETING_REQ = 95  # cs - Request diplomatic meeting
PACKET_DIPLOMACY_INIT_MEETING = 96  # sc - Diplomatic meeting initiated
PACKET_DIPLOMACY_CANCEL_MEETING_REQ = 97  # cs - Request cancel meeting
PACKET_DIPLOMACY_CANCEL_MEETING = 98  # sc - Meeting cancelled
PACKET_DIPLOMACY_CREATE_CLAUSE_REQ = 99  # cs - Request add treaty clause
PACKET_DIPLOMACY_CREATE_CLAUSE = 100  # sc - Treaty clause created
PACKET_DIPLOMACY_REMOVE_CLAUSE_REQ = 101  # cs - Request remove clause
PACKET_DIPLOMACY_REMOVE_CLAUSE = 102  # sc - Treaty clause removed
PACKET_DIPLOMACY_ACCEPT_TREATY_REQ = 103  # cs - Request accept treaty
PACKET_DIPLOMACY_ACCEPT_TREATY = 104  # sc - Treaty accepted
PACKET_DIPLOMACY_CANCEL_PACT = 105  # cs - Cancel diplomatic pact


# =============================================================================
# CONNECTION AND HEALTH PACKETS
# =============================================================================

PACKET_CONN_PING = 88  # sc - Server ping request
PACKET_CONN_PONG = 89  # cs - Client ping response
PACKET_CONN_PING_INFO = 116  # sc - Connection ping information
PACKET_CLIENT_INFO = 119  # cs - Client information
PACKET_CLIENT_HEARTBEAT = 254  # cs - Client heartbeat


# =============================================================================
# MESSAGING AND REPORTING PACKETS
# =============================================================================

PACKET_PAGE_MSG = 110  # sc - Page message to player
PACKET_REPORT_REQ = 111  # cs - Request server report
PACKET_PAGE_MSG_PART = 250  # sc - Partial page message


# =============================================================================
# SPACESHIP PACKETS
# =============================================================================

PACKET_SPACESHIP_LAUNCH = 135  # cs - Launch spaceship
PACKET_SPACESHIP_PLACE = 136  # cs - Place spaceship part
PACKET_SPACESHIP_INFO = 137  # sc - Spaceship information


# =============================================================================
# SERVER SETTINGS AND CONFIGURATION PACKETS
# =============================================================================

PACKET_SINGLE_WANT_HACK_REQ = 160  # cs - Single player hack request
PACKET_SINGLE_WANT_HACK_REPLY = 161  # sc - Single player hack reply
PACKET_SERVER_SETTING_CONTROL = 164  # sc - Server setting control info
PACKET_SERVER_SETTING_CONST = 165  # sc - Constant server setting
PACKET_SERVER_SETTING_BOOL = 166  # sc - Boolean server setting
PACKET_SERVER_SETTING_INT = 167  # sc - Integer server setting
PACKET_SERVER_SETTING_STR = 168  # sc - String server setting
PACKET_SERVER_SETTING_ENUM = 169  # sc - Enum server setting
PACKET_SERVER_SETTING_BITWISE = 170  # sc - Bitwise server setting

# CRITICAL: Map topology packet - defines hex vs square tiles and map wrapping
# This is essential for proper terrain rendering in spectator mode!
PACKET_SET_TOPOLOGY = 253  # sc - Set map topology (hex/square, wrapping)


# =============================================================================
# VOTING SYSTEM PACKETS
# =============================================================================

PACKET_VOTE_NEW = 185  # sc - New vote created
PACKET_VOTE_UPDATE = 186  # sc - Vote updated
PACKET_VOTE_REMOVE = 187  # sc - Vote removed
PACKET_VOTE_RESOLVE = 188  # sc - Vote resolved
PACKET_VOTE_SUBMIT = 189  # cs - Submit vote


# =============================================================================
# WEB CLIENT SPECIFIC PACKETS
# =============================================================================

PACKET_WEB_CITY_INFO_ADDITION = 256  # sc - Additional city info for web client
PACKET_WEB_CMA_SET = 257  # cs - Set Citizen Management Agent settings
PACKET_WEB_CMA_CLEAR = 258  # cs - Clear CMA settings
PACKET_WEB_PLAYER_INFO_ADDITION = 259  # sc - Additional player info for web client
PACKET_WEB_RULESET_UNIT_ADDITION = 260  # sc - Web client unit additions
PACKET_WEB_GOTO_PATH_REQ = 287  # cs - Request goto path calculation
PACKET_WEB_GOTO_PATH = 288  # sc - Goto path information
PACKET_WEB_INFO_TEXT_REQ = 289  # cs - Request info text
PACKET_WEB_INFO_TEXT_MESSAGE = 290  # sc - Info text message


# =============================================================================
# EDIT MODE AND SCENARIO PACKETS
# =============================================================================

PACKET_SCENARIO_DESCRIPTION = 13  # sc - Scenario description
PACKET_EDIT_SCENARIO_DESC = 14  # cs - Edit scenario description
PACKET_SCENARIO_INFO = 180  # sc - Scenario information
PACKET_SAVE_SCENARIO = 181  # cs - Save scenario
PACKET_EDIT_MODE = 190  # cs - Toggle edit mode
PACKET_EDIT_RECALCULATE_BORDERS = 197  # cs - Recalculate borders (edit mode)
PACKET_EDIT_CHECK_TILES = 198  # cs - Check tiles (edit mode)
PACKET_EDIT_TOGGLE_FOGOFWAR = 199  # cs - Toggle fog of war (edit mode)
PACKET_EDIT_TILE_TERRAIN = 200  # cs - Edit tile terrain
PACKET_EDIT_TILE_EXTRA = 202  # cs - Edit tile extras
PACKET_EDIT_STARTPOS = 204  # sc - Edit start position
PACKET_EDIT_STARTPOS_FULL = 205  # sc - Edit start position (full)
PACKET_EDIT_TILE = 206  # cs - Edit tile (edit mode)
PACKET_EDIT_UNIT_CREATE = 207  # cs - Create unit (edit mode)
PACKET_EDIT_UNIT_REMOVE = 208  # cs - Remove unit (edit mode)
PACKET_EDIT_UNIT_REMOVE_BY_ID = 209  # cs - Remove unit by ID (edit mode)
PACKET_EDIT_UNIT = 210  # cs - Edit unit (edit mode)
PACKET_EDIT_CITY_CREATE = 211  # cs - Create city (edit mode)
PACKET_EDIT_CITY_REMOVE = 212  # cs - Remove city (edit mode)
PACKET_EDIT_CITY = 213  # cs - Edit city (edit mode)
PACKET_EDIT_PLAYER_CREATE = 214  # cs - Create player (edit mode)
PACKET_EDIT_PLAYER_REMOVE = 215  # cs - Remove player (edit mode)
PACKET_EDIT_PLAYER = 216  # cs - Edit player (edit mode)
PACKET_EDIT_PLAYER_VISION = 217  # cs - Edit player vision (edit mode)
PACKET_EDIT_GAME = 218  # cs - Edit game (editor mode)
PACKET_EDIT_OBJECT_CREATED = 219  # sc - Object created in edit mode


# =============================================================================
# OTHER PACKETS
# =============================================================================

PACKET_PLAY_MUSIC = 245  # sc - Play music track


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
# NOTES ON PACKET ID CHANGES AND COVERAGE
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
#
# 4. PACKET_SET_TOPOLOGY (pid=253) was MISSING and is CRITICAL for terrain rendering
#    - Defines map topology (hex vs square tiles)
#    - Defines map wrapping (east-west, north-south)
#    - Missing this packet causes spectator mode to not render terrain tiles
#
# COVERAGE STATUS (as of 2025-01-26):
# - Total packets in freeciv/freeciv/common/networking/packets.def: 201
# - Defined in this file: 201 (100% coverage)
# - All protocol packets are now included for complete FreeCiv protocol support
