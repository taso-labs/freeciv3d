/**********************************************************************
    Freeciv-web - the web version of Freeciv. http://www.fciv.net/
    Copyright (C) 2009-2015  The Freeciv-web project

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

***********************************************************************/


var client = {};
client.conn = {};

var client_frozen = false;
var phase_start_time = 0;

var debug_active = false;
var autostart = false;

var username = null;
var userid = null;

var fc_seedrandom = null;

// singleplayer, multiplayer, longturn
var game_type = "";

var music_list = [ ];
var audio = null;
var audio_enabled = false;

var last_turn_change_time = 0;
var turn_change_elapsed = 0;
var seconds_to_phasedone = 0;
var seconds_to_phasedone_sync = 0;
var dialog_close_trigger = "";
var dialog_message_close_task;

// Observer initialization timeout in milliseconds
// Used to detect when observer mode fails to reach C_S_RUNNING state
const OBSERVER_INIT_TIMEOUT_MS = 15000;

// Observer retry configuration
var observer_retry_count = 0;
var observer_retry_in_progress = false;  // Guard against overlapping retry attempts
const OBSERVER_MAX_RETRIES = 4;          // Increased for better recovery from transient failures
const OBSERVER_RETRY_DELAY_MS = 2500;    // Longer delay between retries for server recovery

// Observer connection stagger delays - NOW HANDLED BY API-LEVEL connection_delay PARAM
// The connection_delay URL parameter (set in api_endpoints.py) stagers WebSocket init
// Client-side stagger removed to prevent compounding delays that ate into timeout budget
// See: llm-gateway/api_endpoints.py for the 0/200/400ms stagger timing
const OBSERVER_STAGGER_GLOBAL_MS = 0;     // Stagger handled by connection_delay=0
const OBSERVER_STAGGER_PLAYER1_MS = 0;    // Stagger handled by connection_delay=200
const OBSERVER_STAGGER_PLAYER2_MS = 0;    // Stagger handled by connection_delay=400

// Observer follow mode state
var observer_follow_player = null;        // Player ID to follow, or null for global
var observer_auto_center_interval = null; // Interval timer ID for periodic re-centering
var observer_initial_center_interval = null; // Interval timer ID for initial center polling
var observer_player_search_interval = null; // Interval timer ID for player search polling
var OBSERVER_AUTO_CENTER_MS = 5000;       // Default re-center interval (5 seconds)
var MIN_AUTOCENTER_MS = 1000;             // Minimum autocenter interval (1 second)
var MAX_AUTOCENTER_MS = 60000;            // Maximum autocenter interval (60 seconds)
var MAX_INITIAL_CENTER_ATTEMPTS = 20;     // Max polling attempts for initial center (20 * 500ms = 10 seconds)
var INITIAL_CENTER_POLL_INTERVAL_MS = 500; // Polling interval for initial center (500ms)
var embed_mode = false;                   // Embed mode for iframe viewing
var keyboard_input_enabled = true;        // Keyboard input enabled flag

// Player name validation regex - allows letters, numbers, underscore, asterisk (for AI*1), hyphen
var SAFE_PLAYER_NAME_REGEX = /^[a-zA-Z0-9_*-]+$/;

// Observer player attachment state
var observe_player = null;                // Player name to attach to, or null for global

// Autojoin state
var autojoin_active = false;              // Whether autojoin mode is active

// Parent iframe notification state
var parent_notification_enabled = false;  // Whether to send postMessage to parent
// WARNING: Using '*' allows any parent window to receive messages.
// This is intentional for broad compatibility with different embedding contexts.
// The data sent (game_id, player names, coordinates) is not sensitive.
// For production with sensitive data, consider restricting to known origins.
var parent_notification_origin = '*';

/****************************************************************************
  PARENT IFRAME NOTIFICATION SYSTEM

  When FreeCiv runs inside an iframe (e.g., agent-clash-client), the parent
  window needs to know when the game is ready to display. This system sends
  postMessage events at key milestones so the parent can:
  - Hide loading overlays at the right time
  - Detect and handle errors
  - Track iframe readiness state

  Events sent:
  - preload_complete: Textures and 3D models loaded
  - websocket_connected: Connected to game server
  - game_running: Game state is C_S_RUNNING
  - renderer_ready: Three.js renderer started, map visible
  - terrain_ready: Tile texture populated with terrain data (safe to show map)
  - observer_centered: Camera positioned on followed player
  - error: Any error that prevents proper display
****************************************************************************/

/****************************************************************************
  Initialize parent notification system.
  Detects if running in an iframe and enables notifications.
****************************************************************************/
function init_parent_notification()
{
  // Check if we're running inside an iframe
  try {
    parent_notification_enabled = (window.parent && window.parent !== window);
  } catch (e) {
    // Cross-origin iframe - can't access parent, but can still postMessage
    parent_notification_enabled = true;
  }

  if (parent_notification_enabled) {
    freelog(LOG_DEBUG, '[IframeNotify] Parent notification enabled');
  }
}

/****************************************************************************
  Send a notification to the parent iframe window.

  @param event_type: String identifying the event (e.g., 'renderer_ready')
  @param data: Optional object with additional event data
****************************************************************************/
function notify_parent_iframe(event_type, data)
{
  if (!parent_notification_enabled) return;

  try {
    var message = {
      source: 'freeciv3d',                          // Identifies this as a FreeCiv message
      type: event_type,                             // Event type for routing
      timestamp: Date.now(),                        // When the event occurred
      game_id: $.getUrlVar('game_id') || null,      // Game identifier
      follow: $.getUrlVar('follow') || null,        // Player being followed (for observer)
      observe_player: $.getUrlVar('observe_player') || null,  // Player attached to
      client_state: client_state(),                 // Current client state
      data: data || {}                              // Additional event-specific data
    };

    window.parent.postMessage(message, parent_notification_origin);
    freelog(LOG_DEBUG, '[IframeNotify] Sent: ' + event_type);
  } catch (e) {
    freelog(LOG_DEBUG, '[IframeNotify] Failed to send ' + event_type + ': ' + e);
  }
}

/****************************************************************************
  Notify parent that an error occurred.

  @param error_code: Short error identifier
  @param error_message: Human-readable error description
  @param details: Optional object with additional error context
****************************************************************************/
function notify_parent_error(error_code, error_message, details)
{
  notify_parent_iframe('error', {
    error_code: error_code,
    error_message: error_message,
    details: details || {}
  });
}

// Track if we've sent the initial observer_centered notification (for successful centering)
var observer_centered_notified = false;
// Track if we've sent ANY notification to parent (including "nothing found")
// This prevents duplicate notifications while still allowing retry centering
var observer_parent_notified = false;
// Track if we've sent terrain_ready notification (fires once per game load)
var terrain_ready_notified = false;
// Track if terrain data has been populated into the texture (set by handle_map_info)
// This flag enables renderer_init to know when it's safe to fire terrain_ready
var terrain_data_populated = false;
// Track if renderer has completed initialization (set by renderer_init)
// Used for coordinating terrain_ready notification when packets arrive late
var renderer_initialized = false;

/****************************************************************************
  Helper function for fallback centering and parent notification.
  Attempts to center on any explored tile, or notifies parent of failure.
  Used by multiple timeout/failure code paths to prevent code duplication.

  IMPORTANT: This function ALWAYS tries to center (even if notification already sent).
  This fixes a race condition where early "nothing found" notification would prevent
  later fallback centering when tiles become available.

  @param reason - String describing why fallback was needed (for logging/debugging)
  @param extra_data - Optional object with additional data to include in notification
****************************************************************************/
function notify_observer_centered_fallback(reason, extra_data)
{
  var explored_tile = find_first_explored_tile();
  if (explored_tile) {
    // Always center on the tile (camera positioning)
    center_tile_mapcanvas(explored_tile);
    freelog(LOG_DEBUG, '[Observer] Fallback: Centered on explored tile at (' +
            explored_tile['x'] + ',' + explored_tile['y'] + ') - ' + reason);

    // Only notify parent once (to hide loading overlay)
    if (!observer_centered_notified) {
      observer_centered_notified = true;
      observer_parent_notified = true;
      var notification_data = {
        center_type: 'fallback_explored',
        reason: reason,
        location: { x: explored_tile['x'], y: explored_tile['y'] }
      };
      if (extra_data) {
        for (var key in extra_data) {
          notification_data[key] = extra_data[key];
        }
      }
      notify_parent_iframe('observer_centered', notification_data);
    }
  } else {
    // No explored tiles available - notify parent once but allow retry centering
    // Use separate flag so we don't spam parent but can still center when tiles load
    if (!observer_parent_notified) {
      observer_parent_notified = true;
      console.warn('[Observer] No explored tiles available for fallback centering - ' + reason);
      var notification_data = {
        center_type: 'none',
        reason: reason
      };
      if (extra_data) {
        for (var key in extra_data) {
          notification_data[key] = extra_data[key];
        }
      }
      notify_parent_iframe('observer_centered', notification_data);
      // NOTE: observer_centered_notified stays false so we keep trying to center
    }
  }
}

/****************************************************************************
  Initialize observer follow mode from URL parameter.
  Parses ?follow=player_name and sets up auto-centering on that player.
****************************************************************************/
function init_observer_follow_mode()
{
  // Clear any existing interval first to prevent memory leaks
  cleanup_observer_follow_mode();

  // Register cleanup handler for page unload (important for iframes)
  register_observer_cleanup_handler();

  if (!observing) return;

  // Parse autocenter interval with bounds checking to prevent DoS
  var autocenter_param = $.getUrlVar('autocenter');
  if (autocenter_param) {
    var parsed = parseInt(autocenter_param);
    if (!isNaN(parsed) && parsed >= MIN_AUTOCENTER_MS && parsed <= MAX_AUTOCENTER_MS) {
      OBSERVER_AUTO_CENTER_MS = parsed;
    } else {
      console.warn('[Observer] Invalid autocenter value (must be ' + MIN_AUTOCENTER_MS + '-' + MAX_AUTOCENTER_MS + 'ms), using default:', OBSERVER_AUTO_CENTER_MS);
    }
  }

  // Parse follow parameter
  var follow_param = $.getUrlVar('follow');

  // Global view mode: when follow is missing or explicitly "global"
  if (!follow_param || follow_param === 'global') {
    observer_follow_player = null;
    freelog(LOG_DEBUG, '[Observer] Global view mode - will center on all players');
    start_observer_global_view_intervals();
    return;
  }

  // Decode URL-encoded characters (e.g., AI%2A1 → AI*1)
  follow_param = decodeURIComponent(follow_param);

  // Find player by name, username, or playerno (with null checks for defensive coding)
  for (var player_id in players) {
    var player = players[player_id];
    if (player && (
        player['name'] === follow_param ||
        (player['username'] && player['username'] === follow_param) ||
        (player['playerno'] !== undefined && player['playerno'].toString() === follow_param))) {
      observer_follow_player = player['playerno'];
      freelog(LOG_DEBUG, '[Observer] Following player: ' + (player['name'] || 'Unknown') + ' id: ' + observer_follow_player);
      break;
    }
  }

  if (observer_follow_player !== null) {
    start_observer_follow_intervals();
  } else {
    // Player not found immediately - poll until players list is populated
    freelog(LOG_DEBUG, '[Observer] Player not found yet, polling for: ' + follow_param);
    var player_poll_attempts = 0;
    observer_player_search_interval = setInterval(function() {
      player_poll_attempts++;

      // Search players list again
      for (var player_id in players) {
        var player = players[player_id];
        if (player && (
            player['name'] === follow_param ||
            (player['username'] && player['username'] === follow_param) ||
            (player['playerno'] !== undefined && player['playerno'].toString() === follow_param))) {
          observer_follow_player = player['playerno'];
          freelog(LOG_DEBUG, '[Observer] Found player after polling: ' + (player['name'] || 'Unknown') + ' id: ' + observer_follow_player);
          clearInterval(observer_player_search_interval);
          observer_player_search_interval = null;
          start_observer_follow_intervals();
          return;
        }
      }

      if (player_poll_attempts >= MAX_INITIAL_CENTER_ATTEMPTS) {
        clearInterval(observer_player_search_interval);
        observer_player_search_interval = null;
        console.warn('[Observer] Player not found after', MAX_INITIAL_CENTER_ATTEMPTS, 'polling attempts:', follow_param);
        notify_observer_centered_fallback('player_not_found');
      }
    }, INITIAL_CENTER_POLL_INTERVAL_MS);
  }
}

/****************************************************************************
  Helper function to start the observer follow intervals (auto-centering).
  Called once a player is found, either immediately or after polling.
****************************************************************************/
function start_observer_follow_intervals()
{
  if (observer_follow_player === null) return;

  // Try to center immediately to send notification to parent ASAP.
  // This call will likely fail to find cities/units (data not loaded yet), but that's OK:
  // - If no data: sends 'center_type: none' notification so parent knows iframe is alive
  // - If data exists: centers immediately without waiting for interval
  // Either way, the parent receives observer_centered before its fallback timeout fires.
  observer_center_on_followed_player();

  // Start auto-centering interval
  observer_auto_center_interval = setInterval(
    observer_center_on_followed_player,
    OBSERVER_AUTO_CENTER_MS
  );

  // Initial center with polling to wait for FOLLOWED PLAYER's cities OR units to load
  // IMPORTANT: Check for the followed player's cities/units specifically, not just any cities
  // This fixes a race condition where another player's data loads first
  var initial_center_attempts = 0;
  observer_initial_center_interval = setInterval(function() {
    initial_center_attempts++;
    // Check for cities first (preferred), then units (fallback for turn 1)
    if (has_cities_for_player(observer_follow_player) || has_units_for_player(observer_follow_player)) {
      clearInterval(observer_initial_center_interval);
      observer_initial_center_interval = null;
      observer_center_on_followed_player();
      freelog(LOG_DEBUG, '[Observer] Initial center completed for player ' + observer_follow_player);
    } else if (initial_center_attempts >= MAX_INITIAL_CENTER_ATTEMPTS) {
      clearInterval(observer_initial_center_interval);
      observer_initial_center_interval = null;
      console.warn('[Observer] Cities/units for player', observer_follow_player, 'not loaded after', MAX_INITIAL_CENTER_ATTEMPTS, 'attempts, trying fallback');
      notify_observer_centered_fallback('player_data_timeout', { player_id: observer_follow_player });
    }
  }, INITIAL_CENTER_POLL_INTERVAL_MS);
}

/****************************************************************************
  Check if any cities exist for the specified player.
  Used to determine when to stop polling for initial center.
****************************************************************************/
function has_cities_for_player(player_id)
{
  if (typeof cities === 'undefined' || player_id === null) return false;

  for (var city_id in cities) {
    var pcity = cities[city_id];
    if (city_owner_player_id(pcity) === player_id) {
      return true;
    }
  }
  return false;
}

/****************************************************************************
  Check if any units exist for the specified player.
  Used to determine when to stop polling for initial center (turn 1 fallback).
****************************************************************************/
function has_units_for_player(player_id)
{
  if (typeof units === 'undefined' || player_id === null) return false;

  for (var unit_id in units) {
    var punit = units[unit_id];
    if (punit['owner'] === player_id) {
      return true;
    }
  }
  return false;
}

/****************************************************************************
  Find the first explored tile that the observer can see.
  Returns: ptile object or null if no explored tiles exist.
  Used as fallback when followed player has no cities/units loaded yet.
****************************************************************************/
function find_first_explored_tile()
{
  var first_unseen_tile = null;  // TILE_KNOWN_UNSEEN fallback

  for (var tile_id in tiles) {
    var ptile = tiles[tile_id];
    if (ptile == null) continue;

    var known_status = tile_get_known(ptile);

    // Prefer currently visible tiles
    if (known_status === TILE_KNOWN_SEEN) {
      return ptile;
    }

    // Track unseen but explored tiles as fallback
    if (known_status === TILE_KNOWN_UNSEEN && first_unseen_tile === null) {
      first_unseen_tile = ptile;
    }
  }

  return first_unseen_tile;
}

/****************************************************************************
  Center view on followed player's territory with dynamic zoom.
  Uses territory-aware centering (cities + units) with auto-zoom based on
  empire spread. This ensures the view scales appropriately from turn 1
  through turn 200+ as the player's territory expands.

  On the FIRST successful center (before observer_centered_notified is set),
  uses simple capital/largest-city centering without zoom manipulation.
  This gives the renderer time to populate terrain textures before we start
  adjusting camera_dy. Subsequent calls use full territory + auto-zoom.

  Priority: 1) Capital/city (initial) or territory centroid (ongoing),
            2) Any explored tile
****************************************************************************/
function observer_center_on_followed_player()
{
  if (observer_follow_player === null) return;

  var player = players[observer_follow_player];
  if (!player || !player['is_alive']) {
    freelog(LOG_DEBUG, '[Observer] Followed player not found or dead');
    return;
  }

  // On first center, use simple city centering (capital or largest city) without
  // zoom manipulation. This avoids aggressive camera_dy changes during initial load
  // when terrain textures may still be populating into the DataTexture.
  if (!observer_centered_notified) {
    var target_city = player_capital(player);

    // Fallback: largest city by population
    if (!target_city) {
      var max_size = 0;
      for (var city_id in cities) {
        var pcity = cities[city_id];
        if (city_owner_player_id(pcity) === observer_follow_player) {
          if (pcity['size'] > max_size) {
            max_size = pcity['size'];
            target_city = pcity;
          }
        }
      }
    }

    // Center on city tile if available
    if (target_city) {
      var ptile = city_tile(target_city);
      if (ptile) {
        center_tile_mapcanvas(ptile);
        freelog(LOG_DEBUG, '[Observer] Initial center on ' + (target_city['name'] || 'city') +
                ' (simple mode, no zoom adjustment)');
        observer_centered_notified = true;
        observer_parent_notified = true;
        notify_parent_iframe('observer_centered', {
          center_type: 'city',
          city_name: target_city['name'],
          location: { x: ptile['x'], y: ptile['y'] }
        });
        return;
      }
    }

    // No city or city_tile returned null — try explored tile WITHOUT zoom.
    // We must not fall through to territory centering here, because that
    // would set camera_dy during initial load (defeating the guard's purpose).
    var explored = find_first_explored_tile();
    if (explored) {
      center_tile_mapcanvas(explored);
      freelog(LOG_DEBUG, '[Observer] Initial center on explored tile (' +
              explored['x'] + ',' + explored['y'] + ') - no city tile available');
      observer_centered_notified = true;
      observer_parent_notified = true;
      notify_parent_iframe('observer_centered', {
        center_type: 'explored_tile',
        location: { x: explored['x'], y: explored['y'] }
      });
      return;
    }

    // Nothing available yet — notify parent but keep retrying.
    // Do NOT fall through to territory centering on the first call.
    if (!observer_parent_notified) {
      observer_parent_notified = true;
      console.warn('[Observer] Initial load: no city or explored tiles yet for player ' +
                   observer_follow_player + ' - will retry');
      notify_parent_iframe('observer_centered', {
        center_type: 'none',
        reason: 'no_visible_tiles',
        player_id: observer_follow_player
      });
    }
    return;
  }

  // After initial center: use territory-aware centering with dynamic zoom
  var territory_data = center_on_player_territory_with_zoom(observer_follow_player);
  if (territory_data) {
    return;
  }

  // Priority 2: Fall back to any explored tile (prevents black screen)
  var explored_tile = find_first_explored_tile();
  if (explored_tile) {
    center_tile_mapcanvas(explored_tile);
    freelog(LOG_DEBUG, '[Observer] Centered on explored tile at (' +
            explored_tile['x'] + ',' + explored_tile['y'] + ') - no territory for player ' + observer_follow_player);
    // Notify parent on first successful center (even if fallback)
    if (!observer_centered_notified) {
      observer_centered_notified = true;
      observer_parent_notified = true;
      notify_parent_iframe('observer_centered', {
        center_type: 'explored_tile',
        location: { x: explored_tile['x'], y: explored_tile['y'] }
      });
    }
    return;
  }

  // No territory or explored tiles found - notify parent once but keep trying to center.
  // Use separate flag so we don't spam parent but can still center when tiles load.
  if (!observer_parent_notified) {
    observer_parent_notified = true;
    console.warn('[Observer] No territory or explored tiles found for player ' + observer_follow_player + ' - will retry');
    notify_parent_iframe('observer_centered', {
      center_type: 'none',
      reason: 'no_visible_tiles',
      player_id: observer_follow_player
    });
    // NOTE: observer_centered_notified stays false so we keep trying to center
  }
}

// Track last spread to avoid jarring zoom changes
var observer_last_unit_spread = null;
var SPREAD_CHANGE_THRESHOLD = 5;  // Only recalc zoom if spread changes by >5 tiles

// Track last territory effective radius for follow mode auto-zoom hysteresis
var observer_last_territory_radius = null;
// Hysteresis threshold: only recalculate zoom when effective radius changes by
// >= 2 tiles. Prevents jittery zoom from minor unit movements between cycles.
var TERRITORY_RADIUS_CHANGE_THRESHOLD = 2;

/****************************************************************************
  Unwrap a coordinate relative to a reference point on a wrapping axis.
  If the distance exceeds half the map size, adjusts to the closer wrap.
  @returns the unwrapped coordinate value
****************************************************************************/
function unwrap_coordinate(val, ref, wraps, map_size)
{
  if (!wraps || map_size <= 0) return val;
  var delta = val - ref;
  var half = Math.floor(map_size / 2);
  if (delta > half) return val - map_size;
  if (delta < -half) return val + map_size;
  return val;
}

/****************************************************************************
  Compute wrap-aware spread and centroid from an array of {x, y, weight}
  positions. On wrapping maps, detects when positions span the date line
  and adjusts coordinates so spread and centroid are correct.

  For each wrapping axis, if the naive extent (max - min) exceeds half
  the map dimension, positions are "unwrapped" relative to the first
  position so that they cluster together instead of spanning the full map.

  @param {Array<{x: number, y: number, weight: number}>} positions
  @returns {{ centroid_x, centroid_y, spread, effective_radius, total_weight }} or null
****************************************************************************/
function compute_wrapped_spread_and_centroid(positions)
{
  if (!positions || positions.length === 0) return null;

  var wrap_x = (typeof wrap_has_flag === 'function' && typeof WRAP_X !== 'undefined') ? wrap_has_flag(WRAP_X) : false;
  var wrap_y = (typeof wrap_has_flag === 'function' && typeof WRAP_Y !== 'undefined') ? wrap_has_flag(WRAP_Y) : false;
  var map_w = (typeof map !== 'undefined' && map && map['xsize']) ? map['xsize'] : 0;
  var map_h = (typeof map !== 'undefined' && map && map['ysize']) ? map['ysize'] : 0;

  // Reference point for unwrapping: first position
  var ref_x = positions[0].x;
  var ref_y = positions[0].y;

  var sum_x = 0, sum_y = 0, total_weight = 0;
  var min_x = Infinity, max_x = -Infinity;
  var min_y = Infinity, max_y = -Infinity;

  for (var i = 0; i < positions.length; i++) {
    var px = unwrap_coordinate(positions[i].x, ref_x, wrap_x, map_w);
    var py = unwrap_coordinate(positions[i].y, ref_y, wrap_y, map_h);
    var w = positions[i].weight || 1;

    sum_x += px * w;
    sum_y += py * w;
    total_weight += w;
    min_x = Math.min(min_x, px);
    max_x = Math.max(max_x, px);
    min_y = Math.min(min_y, py);
    max_y = Math.max(max_y, py);
  }

  var centroid_raw_x = sum_x / total_weight;
  var centroid_raw_y = sum_y / total_weight;
  var centroid_x = Math.floor(centroid_raw_x);
  var centroid_y = Math.floor(centroid_raw_y);

  // Re-wrap centroid back into valid map coordinates
  if (wrap_x && map_w > 0) centroid_x = ((centroid_x % map_w) + map_w) % map_w;
  if (wrap_y && map_h > 0) centroid_y = ((centroid_y % map_h) + map_h) % map_h;

  var spread = Math.max(max_x - min_x, max_y - min_y);

  // Compute percentile-based effective radius for outlier-robust zoom.
  // Uses Chebyshev distance (max of |dx|,|dy|) from raw centroid, expanded
  // by weight so cities (weight 3) are harder to exclude as outliers.
  var distances = [];
  for (var k = 0; k < positions.length; k++) {
    var px2 = unwrap_coordinate(positions[k].x, ref_x, wrap_x, map_w);
    var py2 = unwrap_coordinate(positions[k].y, ref_y, wrap_y, map_h);
    var w2 = positions[k].weight || 1;

    var dist = Math.max(Math.abs(px2 - centroid_raw_x), Math.abs(py2 - centroid_raw_y));
    for (var j = 0; j < w2; j++) {
      distances.push(dist);
    }
  }

  distances.sort(function(a, b) { return a - b; });
  var coverage = (typeof TERRITORY_COVERAGE_RATIO !== 'undefined') ? TERRITORY_COVERAGE_RATIO : 0.85;
  var percentile_index = Math.min(Math.floor(distances.length * coverage), distances.length - 1);
  var effective_radius = distances[percentile_index];

  return {
    centroid_x: centroid_x,
    centroid_y: centroid_y,
    spread: spread,
    effective_radius: effective_radius,
    total_weight: total_weight
  };
}

/****************************************************************************
  Calculate the centroid and spread of all units owned by a player.
  Handles wrapping maps correctly via compute_wrapped_spread_and_centroid().
  Returns: { centroid: {x, y}, spread: number, count: number, tile: {x, y} }
  Returns null if player has no units.
****************************************************************************/
function get_player_units_centroid_and_spread(player_id)
{
  var positions = [];

  for (var unit_id in units) {
    var punit = units[unit_id];
    if (punit['owner'] === player_id) {
      var ptile = index_to_tile(punit['tile']);
      if (ptile) {
        positions.push({ x: ptile['x'], y: ptile['y'], weight: 1 });
      }
    }
  }

  var result = compute_wrapped_spread_and_centroid(positions);
  if (!result) return null;

  return {
    centroid: { x: result.centroid_x, y: result.centroid_y },
    spread: result.spread,
    count: positions.length,
    tile: { x: result.centroid_x, y: result.centroid_y }
  };
}

/****************************************************************************
  Calculate camera height (zoom) based on unit spread.
  - Close zoom (dy=300) for spread 0-2 tiles
  - Wide zoom (dy=600) for spread 20+ tiles
****************************************************************************/
function calculate_zoom_for_unit_spread(spread)
{
  var MIN_ZOOM_DY = 300;
  var MAX_ZOOM_DY = 600;
  var SPREAD_MIN = 2;
  var SPREAD_MAX = 20;

  if (spread <= SPREAD_MIN) return MIN_ZOOM_DY;
  if (spread >= SPREAD_MAX) return MAX_ZOOM_DY;

  var zoom_factor = (spread - SPREAD_MIN) / (SPREAD_MAX - SPREAD_MIN);
  return Math.floor(MIN_ZOOM_DY + zoom_factor * (MAX_ZOOM_DY - MIN_ZOOM_DY));
}

/****************************************************************************
  Center view on player's units with dynamic zoom.
  Used when player has no cities (e.g., turn 1).
  Zoom only updates if spread changes significantly (>5 tiles).
****************************************************************************/
function center_on_player_units_with_zoom(player_id)
{
  var unit_data = get_player_units_centroid_and_spread(player_id);
  if (!unit_data) return false;

  // Only recalculate zoom if spread changed significantly or first time
  var should_update_zoom = (
    observer_last_unit_spread === null ||
    Math.abs(unit_data.spread - observer_last_unit_spread) >= SPREAD_CHANGE_THRESHOLD
  );

  // Center first — enable_mapview_slide_3d() recalculates camera_dy from current position.
  center_tile_mapcanvas(unit_data.tile);

  // Always enforce camera_dy to prevent race with camera preset init.
  var target_dy = calculate_zoom_for_unit_spread(unit_data.spread);
  camera_dy = target_dy;

  if (should_update_zoom) {
    observer_last_unit_spread = unit_data.spread;
    freelog(LOG_DEBUG, '[Observer] Zoom updated: spread=' + unit_data.spread +
            ' tiles, dy=' + target_dy);
  }

  freelog(LOG_DEBUG, '[Observer] Centered on ' + unit_data.count +
          ' unit(s) at (' + unit_data.centroid.x + ',' + unit_data.centroid.y + ')');

  return true;
}

// City centroid weight: each city contributes this many points to the centroid
// to anchor the view near the empire core and prevent distant military
// expeditions from pulling the camera away from the player's cities.
var TERRITORY_CITY_WEIGHT = 3;

/****************************************************************************
  Calculate the centroid and spread of all territory (cities + units) owned
  by a player. Territory provides a more stable and comprehensive view than
  either cities or units alone.
  Cities are weighted more heavily (TERRITORY_CITY_WEIGHT per city) so the
  centroid stays anchored near the empire core.
  Handles wrapping maps correctly via compute_wrapped_spread_and_centroid().
  Returns: { centroid: {x, y}, spread: number, city_count: number,
             unit_count: number, count: number, tile: {x, y} }
  Returns null if player has no cities or units.
****************************************************************************/
function get_player_territory_centroid_and_spread(player_id)
{
  var positions = [];
  var city_count = 0, unit_count = 0;

  // Include all cities owned by this player (weighted for centroid stability)
  for (var city_id in cities) {
    var pcity = cities[city_id];
    if (city_owner_player_id(pcity) === player_id) {
      var ptile = city_tile(pcity);
      if (ptile) {
        positions.push({ x: ptile['x'], y: ptile['y'], weight: TERRITORY_CITY_WEIGHT });
        city_count++;
      }
    }
  }

  // Include all units owned by this player (weight 1 each)
  for (var unit_id in units) {
    var punit = units[unit_id];
    if (punit['owner'] === player_id) {
      var ptile = index_to_tile(punit['tile']);
      if (ptile) {
        positions.push({ x: ptile['x'], y: ptile['y'], weight: 1 });
        unit_count++;
      }
    }
  }

  var result = compute_wrapped_spread_and_centroid(positions);
  if (!result) return null;

  return {
    centroid: { x: result.centroid_x, y: result.centroid_y },
    spread: result.spread,
    effective_radius: result.effective_radius,
    city_count: city_count,
    unit_count: unit_count,
    count: result.total_weight,
    tile: { x: result.centroid_x, y: result.centroid_y }
  };
}

// Territory observer zoom configuration
// Uses effective_radius (85th-percentile Chebyshev distance from centroid)
// to compute camera height, ignoring distant outlier units.
//
// Calibrated for the FreeCiv3D WebGL viewport at 1920x1080:
// - Single city (radius ~0): dy=250 gives a close overhead view of the city area
// - Mid-game empire (~10 tile radius): dy=530 keeps 2-3 cities in frame
// - Late-game continental empire (~20+ tiles): dy=810+ shows the full territory
// - DY_PER_TILE=28 was chosen so the zoom transition feels smooth across these stages
var TERRITORY_BASE_DY = 250;
var TERRITORY_DY_PER_TILE = 28;
var TERRITORY_MIN_ZOOM_DY = 200;
var TERRITORY_MAX_ZOOM_DY = 900;
// 85th percentile: includes the main empire cluster while excluding the ~15% most
// distant units (scouts, expeditionary forces) that would otherwise over-zoom.
var TERRITORY_COVERAGE_RATIO = 0.85;

/****************************************************************************
  Calculate camera height (zoom) based on territory effective radius.
  Uses a simple linear formula: dy = BASE + radius * DY_PER_TILE,
  clamped to [MIN, MAX]. The effective radius is the 85th-percentile
  Chebyshev distance from centroid, which naturally excludes distant
  outlier units while keeping the full city cluster in view.
****************************************************************************/
function calculate_zoom_for_territory_spread(effective_radius)
{
  var dy = TERRITORY_BASE_DY + effective_radius * TERRITORY_DY_PER_TILE;
  return Math.floor(Math.max(TERRITORY_MIN_ZOOM_DY, Math.min(TERRITORY_MAX_ZOOM_DY, dy)));
}

/****************************************************************************
  Center view on player's territory centroid with dynamic zoom.
  Used in follow mode when player has cities and/or units.
  Zoom only updates if effective radius changes significantly (>2 tiles).
  Returns territory_data object if successfully centered, null if no territory.
****************************************************************************/
function center_on_player_territory_with_zoom(player_id)
{
  var territory_data = get_player_territory_centroid_and_spread(player_id);
  if (!territory_data) return null;

  // Only recalculate zoom if effective radius changed significantly or first time
  var should_update_zoom = (
    observer_last_territory_radius === null ||
    Math.abs(territory_data.effective_radius - observer_last_territory_radius) >= TERRITORY_RADIUS_CHANGE_THRESHOLD
  );

  // Center first — this triggers enable_mapview_slide_3d() which recalculates
  // camera_dy from the current camera position. We must set camera_dy AFTER.
  center_tile_mapcanvas(territory_data.tile);

  // Always set camera_dy to prevent race with camera preset init (?camera=cinematic)
  // which can reset camera_dy=150 after our first centering call. Hysteresis only
  // controls logging to avoid log spam — camera_dy must be enforced every cycle.
  var target_dy = calculate_zoom_for_territory_spread(territory_data.effective_radius);
  camera_dy = target_dy;

  if (should_update_zoom) {
    observer_last_territory_radius = territory_data.effective_radius;
    freelog(LOG_DEBUG, '[Observer] Territory: centroid=(' + territory_data.centroid.x + ',' +
            territory_data.centroid.y + ') radius=' + territory_data.effective_radius +
            ' spread=' + territory_data.spread +
            ' (' + territory_data.city_count + 'c/' + territory_data.unit_count + 'u) dy=' + target_dy);
  }

  return territory_data;
}

// Track last global spread for hysteresis to avoid jarring zoom changes
var observer_last_global_spread = null;
var GLOBAL_SPREAD_CHANGE_THRESHOLD = 10;  // Only recalc zoom if spread changes by >10 tiles

// Global observer zoom configuration (camera height values)
var GLOBAL_OBSERVER_MIN_ZOOM_DY = 300;   // Close view for clustered units (spread 0-5 tiles)
var GLOBAL_OBSERVER_MID_ZOOM_DY = 600;   // Medium view for moderate spread (~40 tiles)
var GLOBAL_OBSERVER_MAX_ZOOM_DY = 1200;  // Far view for maximum spread (80+ tiles)
var GLOBAL_OBSERVER_SPREAD_MIN = 5;      // Spread threshold for minimum zoom
var GLOBAL_OBSERVER_SPREAD_MID = 40;     // Spread threshold for medium zoom
var GLOBAL_OBSERVER_SPREAD_MAX = 80;     // Spread threshold for maximum zoom

/****************************************************************************
  Calculate the centroid and spread of all units from ALL non-barbarian
  alive players. Used for global observer view to fit all players in view.
  Handles wrapping maps correctly via compute_wrapped_spread_and_centroid().
  Returns: { centroid: {x, y}, spread: number, count: number, player_count: number }
  Returns null if no non-barbarian players have units.
****************************************************************************/
function get_all_players_units_centroid_and_spread()
{
  if (typeof units === 'undefined' || typeof players === 'undefined') return null;

  var positions = [];
  var players_with_units = {};

  for (var unit_id in units) {
    var punit = units[unit_id];
    var owner_id = punit['owner'];

    // Skip barbarian players
    if (is_barbarian_player(owner_id)) continue;

    // Skip dead players
    var player = players[owner_id];
    if (!player || !player['is_alive']) continue;

    // Defensive check: ensure unit has valid tile index before lookup
    if (punit['tile'] == null) continue;

    var ptile = index_to_tile(punit['tile']);
    if (ptile) {
      positions.push({ x: ptile['x'], y: ptile['y'], weight: 1 });
      players_with_units[owner_id] = true;
    }
  }

  var result = compute_wrapped_spread_and_centroid(positions);
  if (!result) return null;

  var player_count = Object.keys(players_with_units).length;

  return {
    centroid: { x: result.centroid_x, y: result.centroid_y },
    spread: result.spread,
    count: positions.length,
    player_count: player_count,
    tile: { x: result.centroid_x, y: result.centroid_y }
  };
}

/****************************************************************************
  Calculate camera height (zoom) based on global unit spread.
  Extended zoom range for multi-player scenarios:
  - dy=300 for spread 0-5 tiles (clustered)
  - dy=600 for spread ~40 tiles (medium)
  - dy=1200 for spread 80+ tiles (very spread out)
  Uses two-phase linear interpolation for smooth curve.
****************************************************************************/
function calculate_zoom_for_global_spread(spread)
{
  if (spread <= GLOBAL_OBSERVER_SPREAD_MIN) return GLOBAL_OBSERVER_MIN_ZOOM_DY;
  if (spread >= GLOBAL_OBSERVER_SPREAD_MAX) return GLOBAL_OBSERVER_MAX_ZOOM_DY;

  // Two-phase interpolation for smooth curve
  if (spread <= GLOBAL_OBSERVER_SPREAD_MID) {
    // Phase 1: MIN to MID (5-40 tiles -> dy 300-600)
    var zoom_factor = (spread - GLOBAL_OBSERVER_SPREAD_MIN) / (GLOBAL_OBSERVER_SPREAD_MID - GLOBAL_OBSERVER_SPREAD_MIN);
    return Math.floor(GLOBAL_OBSERVER_MIN_ZOOM_DY + zoom_factor * (GLOBAL_OBSERVER_MID_ZOOM_DY - GLOBAL_OBSERVER_MIN_ZOOM_DY));
  } else {
    // Phase 2: MID to MAX (40-80 tiles -> dy 600-1200)
    var zoom_factor = (spread - GLOBAL_OBSERVER_SPREAD_MID) / (GLOBAL_OBSERVER_SPREAD_MAX - GLOBAL_OBSERVER_SPREAD_MID);
    return Math.floor(GLOBAL_OBSERVER_MID_ZOOM_DY + zoom_factor * (GLOBAL_OBSERVER_MAX_ZOOM_DY - GLOBAL_OBSERVER_MID_ZOOM_DY));
  }
}

/****************************************************************************
  Center view on ALL players' units with dynamic zoom.
  Zoom only updates if spread changes significantly (>10 tiles).
  Returns unit_data object if successfully centered, null if no units found.
****************************************************************************/
function center_on_all_players_with_zoom()
{
  var unit_data = get_all_players_units_centroid_and_spread();
  if (!unit_data) return null;

  // Only recalculate zoom if spread changed significantly or first time
  var should_update_zoom = (
    observer_last_global_spread === null ||
    Math.abs(unit_data.spread - observer_last_global_spread) >= GLOBAL_SPREAD_CHANGE_THRESHOLD
  );

  // Center first — enable_mapview_slide_3d() recalculates camera_dy from current position.
  center_tile_mapcanvas(unit_data.tile);

  // Always enforce camera_dy to prevent race with camera preset init.
  var target_dy = calculate_zoom_for_global_spread(unit_data.spread);
  camera_dy = target_dy;

  if (should_update_zoom) {
    observer_last_global_spread = unit_data.spread;
    freelog(LOG_DEBUG, '[Observer Global] Zoom updated: spread=' + unit_data.spread +
            ' tiles, ' + unit_data.player_count + ' players, dy=' + target_dy);
  }

  freelog(LOG_DEBUG, '[Observer Global] Centered on ' + unit_data.count +
          ' unit(s) from ' + unit_data.player_count + ' player(s) at (' +
          unit_data.centroid.x + ',' + unit_data.centroid.y + ')');

  return unit_data;
}

/****************************************************************************
  Main entry point for global observer view (no specific player followed).
  Centers on combined centroid of all players with appropriate zoom.
  Falls back to explored tile if no units exist.
****************************************************************************/
function observer_center_global_view()
{
  // Try to center on all players' units with dynamic zoom
  // center_on_all_players_with_zoom() returns unit_data on success, null on failure
  var unit_data = center_on_all_players_with_zoom();
  if (unit_data) {
    // Notify parent on first successful center
    if (!observer_centered_notified) {
      observer_centered_notified = true;
      observer_parent_notified = true;
      notify_parent_iframe('observer_centered', {
        center_type: 'global_units',
        player_count: unit_data.player_count,
        unit_count: unit_data.count,
        spread: unit_data.spread
      });
    }
    return;
  }

  // Fall back to any explored tile (prevents black screen)
  var explored_tile = find_first_explored_tile();
  if (explored_tile) {
    center_tile_mapcanvas(explored_tile);
    freelog(LOG_DEBUG, '[Observer Global] Centered on explored tile at (' +
            explored_tile['x'] + ',' + explored_tile['y'] + ') - no player units found');
    if (!observer_centered_notified) {
      observer_centered_notified = true;
      observer_parent_notified = true;
      notify_parent_iframe('observer_centered', {
        center_type: 'fallback_explored',
        reason: 'no_player_units',
        location: { x: explored_tile['x'], y: explored_tile['y'] }
      });
    }
    return;
  }

  // No units or explored tiles - notify parent once but keep trying
  if (!observer_parent_notified) {
    observer_parent_notified = true;
    console.warn('[Observer Global] No units or explored tiles found - will retry');
    notify_parent_iframe('observer_centered', {
      center_type: 'none',
      reason: 'no_visible_content'
    });
  }
}

/****************************************************************************
  Check if any non-barbarian alive player has units.
  Quick check used for polling before expensive centroid calculation.
****************************************************************************/
function has_units_for_any_player()
{
  if (typeof units === 'undefined' || typeof players === 'undefined') return false;

  for (var unit_id in units) {
    var punit = units[unit_id];
    var owner_id = punit['owner'];

    // Skip barbarians
    if (is_barbarian_player(owner_id)) continue;

    // Skip dead players
    var player = players[owner_id];
    if (!player || !player['is_alive']) continue;

    return true;  // Found at least one valid unit
  }
  return false;
}

/****************************************************************************
  Start global view intervals for observer without a specific follow target.
  Sets up periodic centering on all players' combined units.
****************************************************************************/
function start_observer_global_view_intervals()
{
  // Try to center immediately
  observer_center_global_view();

  // Start auto-centering interval
  observer_auto_center_interval = setInterval(
    observer_center_global_view,
    OBSERVER_AUTO_CENTER_MS
  );

  // Poll for any player units to load
  var initial_center_attempts = 0;
  observer_initial_center_interval = setInterval(function() {
    initial_center_attempts++;

    if (has_units_for_any_player()) {
      clearInterval(observer_initial_center_interval);
      observer_initial_center_interval = null;
      // Center immediately when units are found (don't wait for auto-center interval)
      observer_center_global_view();
      freelog(LOG_DEBUG, '[Observer Global] Initial center completed - centered on player units');
    } else if (initial_center_attempts >= MAX_INITIAL_CENTER_ATTEMPTS) {
      clearInterval(observer_initial_center_interval);
      observer_initial_center_interval = null;
      console.warn('[Observer Global] No player units loaded after', MAX_INITIAL_CENTER_ATTEMPTS, 'attempts');
      notify_observer_centered_fallback('global_units_timeout');
    }
  }, INITIAL_CENTER_POLL_INTERVAL_MS);
}

/****************************************************************************
  Clean up observer follow mode - clear interval and reset state.
****************************************************************************/
function cleanup_observer_follow_mode()
{
  if (observer_auto_center_interval) {
    clearInterval(observer_auto_center_interval);
    observer_auto_center_interval = null;
  }
  if (observer_initial_center_interval) {
    clearInterval(observer_initial_center_interval);
    observer_initial_center_interval = null;
  }
  if (observer_player_search_interval) {
    clearInterval(observer_player_search_interval);
    observer_player_search_interval = null;
  }
  observer_follow_player = null;
  observer_last_unit_spread = null;
  observer_last_territory_radius = null;
  observer_last_global_spread = null;
}

/****************************************************************************
  Register beforeunload handler for observer cleanup.
  Ensures interval timers are cleared when the page/iframe is closed.
  Uses namespaced event to prevent listener accumulation on repeated calls.
****************************************************************************/
function register_observer_cleanup_handler()
{
  // Remove any existing handler first to prevent accumulation
  $(window).off('beforeunload.observer_cleanup');
  // Add namespaced event handler
  $(window).on('beforeunload.observer_cleanup', function() {
    cleanup_observer_follow_mode();
  });
}

/****************************************************************************
  Initialize embed mode from URL parameter.
  Parses ?embed=1 and disables user interaction for iframe viewing.
****************************************************************************/
function init_embed_mode()
{
  var embed_param = $.getUrlVar('embed');
  if (embed_param === '1' || embed_param === 'true') {
    embed_mode = true;
    apply_embed_mode_settings();
  }
}

/****************************************************************************
  Apply embed mode settings - disable audio, controls, keyboard, and reduce UI.
****************************************************************************/
function apply_embed_mode_settings()
{
  if (!embed_mode) return;

  // Disable audio
  audio_enabled = false;
  sounds_enabled = false;

  // Disable keyboard input
  keyboard_input_enabled = false;

  // Add CSS class for styling
  document.body.classList.add('embed-mode');

  // Disable OrbitControls if available
  if (typeof controls !== 'undefined' && controls !== null) {
    controls.enabled = false;
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.enableRotate = false;
  }

  // Hide UI elements in embed mode
  var embed_hidden_elements = [
    'game_menu_panel',
    'game_chatbox_panel',  // The actual chatbox element (not 'chat_panel')
    'turn_done_button',
    'unit_orders_bar',
    'minimap_panel',
    'info_panel',
    'civ_status_bar'
  ];

  embed_hidden_elements.forEach(function(elementId) {
    var el = document.getElementById(elementId);
    if (el) {
      el.style.display = 'none';
    }
  });

  // Also hide the jQuery UI dialog wrapper for chatbox (has class .chatbox_dialog)
  $(".chatbox_dialog").hide();
  // And hide the dialog's parent container
  $("#game_chatbox_panel").parent().hide();

  freelog(LOG_DEBUG, '[Observer] Embed mode enabled - controls and UI disabled');
}

/****************************************************************************
  Check if embed mode is currently active.
  Returns true if embed_mode flag is set.
****************************************************************************/
function is_embed_mode()
{
  return embed_mode;
}

/****************************************************************************
  AUTOJOIN MODE SYSTEM
  Functions for automatic connection without username dialog.
****************************************************************************/

/****************************************************************************
  Check if autojoin mode should be activated from URL parameters.
  Returns true if autojoin=1 or autojoin=true in URL.
****************************************************************************/
function should_autojoin()
{
  var autojoin_param = $.getUrlVar('autojoin');
  return autojoin_param === '1' || autojoin_param === 'true';
}

/****************************************************************************
  Generate a random observer username in format: observer_XXXXX
  Used when no username is provided in URL.
****************************************************************************/
function generate_observer_name()
{
  var chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  var suffix = '';
  for (var i = 0; i < 8; i++) {
    suffix += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return 'observer_' + suffix;
}

/****************************************************************************
  Validate a username for autojoin.
  Rules: 3-31 chars, alphanumeric + underscore, starts with letter or underscore
****************************************************************************/
function validate_autojoin_username(name)
{
  if (name === null || name === undefined) {
    return false;
  }

  if (typeof name !== 'string') {
    return false;
  }

  // Length check: 3-31 characters
  if (name.length < 3 || name.length > 31) {
    return false;
  }

  // Must start with letter or underscore
  if (!/^[a-zA-Z_]/.test(name)) {
    return false;
  }

  // Must only contain letters, numbers, and underscores
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name)) {
    return false;
  }

  return true;
}

/****************************************************************************
  Get the username for autojoin mode.
  Uses URL param base if provided, with random suffix for uniqueness.
  This ensures page refreshes don't cause "username already connected" errors.
****************************************************************************/
function get_autojoin_username()
{
  var name_param = $.getUrlVar('name');
  // Use 8 random chars for better uniqueness with many concurrent viewers
  var random_suffix = '_' + Math.random().toString(36).substring(2, 10);

  if (name_param) {
    // Trim whitespace and any existing random suffix
    name_param = name_param.trim();
    // Remove any existing suffix (e.g., global_view_abc12345 -> global_view)
    var base_name = name_param.replace(/_[a-z0-9]{4,8}$/, '');

    // Add new random suffix to make connection unique
    var unique_name = base_name + random_suffix;

    // Ensure total length is valid (3-31 chars)
    if (unique_name.length > 31) {
      unique_name = base_name.substring(0, 22) + random_suffix;
    }

    if (validate_autojoin_username(unique_name)) {
      return unique_name;
    }
  }

  // Generate random name
  return generate_observer_name();
}

/****************************************************************************
  Calculate stagger delay for observer connections to prevent race conditions.
  When multiple observers (global, player1, player2) connect simultaneously,
  staggering prevents server-side packet ordering issues.
  Returns delay in milliseconds based on observer name or explicit URL param.
****************************************************************************/
function get_observer_stagger_delay()
{
  // First check for explicit stagger parameter (overrides name-based detection)
  var stagger_param = $.getUrlVar('stagger');
  if (stagger_param) {
    var delay = parseInt(stagger_param);
    if (!isNaN(delay) && delay >= 0 && delay <= 5000) {
      return delay;
    }
    console.warn('[Observer] Invalid stagger parameter ignored:', stagger_param);
  }

  var name_param = $.getUrlVar('name');
  if (!name_param || !observing) return OBSERVER_STAGGER_GLOBAL_MS;

  // Stagger based on observer type in name
  if (name_param.indexOf('global') !== -1) return OBSERVER_STAGGER_GLOBAL_MS;
  if (name_param.indexOf('player1') !== -1) return OBSERVER_STAGGER_PLAYER1_MS;
  if (name_param.indexOf('player2') !== -1) return OBSERVER_STAGGER_PLAYER2_MS;
  return OBSERVER_STAGGER_GLOBAL_MS;
}

/****************************************************************************
  Handle observer timeout with automatic retry logic.
  Shared helper to avoid duplicate code in request_observe_game() and
  execute_observe_player_attachment().
  @param context - Context string for logging (e.g., 'global' or player name)
****************************************************************************/
function handle_observer_timeout_with_retry(context)
{
  if (client_state() === C_S_RUNNING || !observing || observer_retry_in_progress) {
    return; // Successfully connected, retry in progress, or no action needed
  }

  if (observer_retry_count < OBSERVER_MAX_RETRIES) {
    observer_retry_count++;
    observer_retry_in_progress = true;
    console.warn('[Observer] Retry ' + observer_retry_count + '/' + OBSERVER_MAX_RETRIES +
                 ' - state: ' + client_state() + (context ? ', context: ' + context : ''));

    // Reset and retry
    reset_observer_state_for_retry();

    setTimeout(function() {
      if (typeof network_init === 'function') {
        network_init();
      }
      observer_retry_in_progress = false;
    }, OBSERVER_RETRY_DELAY_MS);
  } else {
    console.error('[Observer] TIMEOUT: Failed to reach C_S_RUNNING state after ' +
                  (OBSERVER_INIT_TIMEOUT_MS / 1000) + ' seconds and ' +
                  OBSERVER_MAX_RETRIES + ' retries', {
      current_state: client_state(),
      map_xsize: (typeof map !== 'undefined' && map != null) ? map['xsize'] : 'undefined',
      game_turn: (typeof game_info !== 'undefined' && game_info != null) ? game_info['turn'] : 'undefined',
      tiles_allocated: (typeof tiles !== 'undefined' && tiles != null),
      tiles_initialized: (typeof tiles_initialized !== 'undefined') ? tiles_initialized : 'undefined',
      buffered_packets: (typeof pending_tile_packets !== 'undefined') ? pending_tile_packets.length : 0,
      player_count: (typeof players !== 'undefined') ? Object.keys(players).length : 0,
      context: context || 'global'
    });

    // Notify parent of failure so it can hide loading overlay and show error
    notify_parent_iframe('observer_centered', {
      center_type: 'error',
      reason: 'connection_timeout',
      context: context || 'global'
    });

    alert('Observer mode failed to initialize. The map is not loading.\n\nThis could be due to network issues or the game not being ready.\n\nPlease try reloading the page.');
  }
}

/****************************************************************************
  Set up observer timeout with retry logic.
  @param context - Context string for logging
****************************************************************************/
function setup_observer_timeout_with_retry(context)
{
  setTimeout(function() {
    handle_observer_timeout_with_retry(context);
  }, OBSERVER_INIT_TIMEOUT_MS);
}

/****************************************************************************
  Reset observer state for retry.
  Clears network state, tiles, and buffered packets.
****************************************************************************/
function reset_observer_state_for_retry()
{
  // Reset network state
  if (typeof network_stop === 'function') {
    try {
      network_stop();
    } catch (e) {
      console.warn('[Observer] network_stop() failed:', e);
    }
  }
  network_init_called = false;

  // Reset retry-in-progress flag (in case called from elsewhere)
  observer_retry_in_progress = false;

  // CRITICAL: Reset map to empty object to prevent handle_game_info() from
  // triggering C_S_RUNNING before handle_map_info() runs on retry.
  // This was causing the terrain texture race condition.
  if (typeof map !== 'undefined') {
    map = {};
  }

  // Reset tile state (defined in packhand.js)
  if (typeof tiles_initialized !== 'undefined') {
    tiles_initialized = false;
  }
  if (typeof pending_tile_packets !== 'undefined') {
    pending_tile_packets = [];
  }

  // Reset terrain texture state to force re-creation on retry
  if (typeof maptiletypes !== 'undefined') {
    maptiletypes = null;
  }
  if (typeof maptiles_data !== 'undefined') {
    maptiles_data = null;
  }
  if (typeof freeciv_uniforms !== 'undefined') {
    freeciv_uniforms = null;
  }

  // Reset parent notification state so retry can send notifications again
  observer_centered_notified = false;
  observer_parent_notified = false;
  if (typeof terrain_ready_notified !== 'undefined') {
    terrain_ready_notified = false;
  }
  if (typeof terrain_data_populated !== 'undefined') {
    terrain_data_populated = false;
  }
  if (typeof renderer_initialized !== 'undefined') {
    renderer_initialized = false;
  }
}

/****************************************************************************
  Initialize autojoin mode - skip username dialog and connect directly.
****************************************************************************/
function init_autojoin_mode()
{
  if (!should_autojoin()) {
    return;
  }

  autojoin_active = true;
  username = get_autojoin_username();

  // Check if provided name is invalid and regenerate
  var name_param = $.getUrlVar('name');
  if (name_param && !validate_autojoin_username(name_param.trim())) {
    username = generate_observer_name();
  }

  freelog(LOG_DEBUG, '[Autojoin] Starting autojoin mode with username: ' + username);

  // Hide intro elements (same as pregame_handle_user)
  // Check if dialog is initialized before trying to close it
  try {
    if ($("#dialog").hasClass('ui-dialog-content')) {
      $("#dialog").dialog('close');
    }
  } catch (e) {
    // Dialog was never initialized, ignore
  }
  $("#fciv-intro").hide();

  // Initialize embed mode if URL has embed=1 (hides UI elements, disables audio)
  init_embed_mode();

  // Initialize observe_player mode if URL has observe_player param
  // Note: Actual /observe command is sent after login via execute_observe_player_attachment()
  init_observe_player_mode();

  // Apply stagger delay for multiple simultaneous observers to prevent race conditions
  var stagger = get_observer_stagger_delay();
  if (stagger > 0) {
    freelog(LOG_DEBUG, '[Autojoin] Staggering connection by ' + stagger + 'ms');
    setTimeout(function() {
      // Initialize sprites/tileset - this triggers async loading chain:
      // init_sprites() → preload_check() → webgl_preload() → webgl_preload_complete() → network_init()
      init_sprites();
    }, stagger);
  } else {
    // Initialize sprites/tileset - this triggers async loading chain:
    // init_sprites() → preload_check() → webgl_preload() → webgl_preload_complete() → network_init()
    // We must NOT call network_init() here - let the callback chain handle it after assets load
    init_sprites();
  }
}

/****************************************************************************
  OBSERVER PLAYER ATTACHMENT SYSTEM
  Functions for attaching to a specific player's fog-of-war view.
****************************************************************************/

/****************************************************************************
  Find a player by name using case-insensitive matching.
  Returns the actual player name with correct case, or null if not found.
  This is needed because URL parameters may have different case than actual
  player names (e.g., "grok-41_fast" vs "Grok-41_Fast").
****************************************************************************/
function find_player_name_case_insensitive(name)
{
  if (!name || typeof players === 'undefined') {
    return null;
  }

  // SECURITY: Validate player name format before lookup
  if (!SAFE_PLAYER_NAME_REGEX.test(name)) {
    console.error('[Observer] Invalid player name format:', name);
    return null;
  }

  var name_lower = name.toLowerCase();

  for (var player_id in players) {
    if (players[player_id] && players[player_id]['name']) {
      if (players[player_id]['name'].toLowerCase() === name_lower) {
        return players[player_id]['name'];
      }
    }
  }

  return null;
}

/****************************************************************************
  Get the observe_player URL parameter, handling URL encoding.
  Returns player name to observe, or null if not specified.
****************************************************************************/
function get_observe_player_param()
{
  var param = $.getUrlVar('observe_player');

  if (!param || param === '') {
    return null;
  }

  // Trim whitespace
  return param.trim();
}

/****************************************************************************
  Send /observe command to attach to a specific player or observe globally.
  player_name: Player name to observe, or null for global observation.
  SECURITY: Validates player_name to prevent command injection attacks.
****************************************************************************/
function request_observe_player(player_name)
{
  // SECURITY: Validate player name contains only safe characters
  if (player_name && !SAFE_PLAYER_NAME_REGEX.test(player_name)) {
    console.error('[Observer] Invalid player name contains unsafe characters:', player_name);
    return;
  }

  // Try to resolve the player name with correct case (case-insensitive lookup)
  if (player_name) {
    var actual_player_name = find_player_name_case_insensitive(player_name);
    if (actual_player_name) {
      player_name = actual_player_name;
    }
  }

  observe_player = player_name;

  if (typeof send_message === 'function') {
    if (player_name) {
      send_message('/observe ' + player_name);
    } else {
      send_message('/observe ');
    }
  }
}

/****************************************************************************
  Initialize observe player mode from URL parameter.
  Does NOT send command - that happens after login via execute_observe_player_attachment.
****************************************************************************/
function init_observe_player_mode()
{
  var player_param = get_observe_player_param();

  if (player_param) {
    observe_player = player_param;
  }
}

/****************************************************************************
  Execute observer attachment after successful login.
  Sends /observe command if observe_player was set during initialization.
  SECURITY: Validates player name format to prevent command injection.
  Includes retry logic for failed connections.
****************************************************************************/
function execute_observe_player_attachment()
{
  if (!observe_player || observe_player === '') {
    return;
  }

  // SECURITY: Validate player name format to prevent command injection
  if (!SAFE_PLAYER_NAME_REGEX.test(observe_player)) {
    console.error('[Observer] Invalid player name contains unsafe characters:', observe_player);
    return;
  }

  // VALIDATION: Check if player exists (optional - warn but proceed, server will reject if invalid)
  var player_exists = false;
  if (typeof players !== 'undefined') {
    for (var player_id in players) {
      if (players[player_id] && players[player_id]['name'] === observe_player) {
        player_exists = true;
        break;
      }
    }
    if (!player_exists) {
      console.warn('[Observer] Player not found:', observe_player, '- proceeding anyway');
    }
  }

  if (typeof send_message === 'function') {
    send_message('/observe ' + observe_player);
    setup_observer_timeout_with_retry(observe_player);
  }
}

/****************************************************************************
  Check if observer is attached to a specific player (vs global observer).
  Returns true if attached to a player's fog-of-war view.
****************************************************************************/
function is_attached_observer()
{
  return observe_player !== null && observe_player !== '';
}

/**************************************************************************
 Main starting point for FCIV.NET
**************************************************************************/
$(document).ready(function() {
  civclient_init();
});

/**************************************************************************
 This function is called on page load.
**************************************************************************/
function civclient_init()
{
  // Initialize parent iframe notification system first (for error reporting)
  init_parent_notification();

  if (!Detector.webgl) {
    notify_parent_error('WEBGL_NOT_SUPPORTED', 'WebGL not supported by browser');
    swal("3D WebGL not supported by your browser or you don't have a 3D graphics card.  ");
    return;
  }

  $("#introtxtja").hide();

  $.blockUI.defaults['css']['backgroundColor'] = "#222";
  $.blockUI.defaults['css']['color'] = "#fff";
  $.blockUI.defaults['theme'] = true;

  var action = $.getUrlVar('action');
  game_type = $.getUrlVar('type');
  if (game_type == null) {
    if (action == null) {
      game_type = 'singleplayer';
    } else if (action == 'pbem') {
      game_type = 'pbem';
    } else {
      game_type = 'singleplayer';
    }
  }

  if (action == "observe") {
    observing = true;
    $("#pregame_buttons").remove();
    $("#civ_dialog").remove();
  }

  //initialize a seeded random number generator
  fc_seedrandom = new Math.seedrandom('freeciv-web');

  // Wait for DOM to be ready before initializing WebGL
  setTimeout(function() {
    if (document.getElementById('mapcanvas')) {
      init_webgl_renderer();
    } else {
      console.error("mapcanvas element not found, retrying WebGL initialization...");
      setTimeout(function() {
        if (document.getElementById('mapcanvas')) {
          init_webgl_renderer();
        } else {
          console.error("Failed to initialize WebGL: mapcanvas element not available");
        }
      }, 1000);
    }
  }, 100);

  game_init();
  $('#tabs').tabs({ heightStyle: "fill" });
  control_init();

  timeoutTimerId = setInterval(update_timeout, 1000);

  update_game_status_panel();
  statusTimerId = setInterval(update_game_status_panel, 6000);

  motd_init();


  $('#tabs').css("height", $(window).height());
  $("#tabs-map").height("auto");
  $("#tabs-civ").height("auto");
  $("#tabs-tec").height("auto");
  $("#tabs-nat").height("auto");
  $("#tabs-cities").height("auto");
  $("#tabs-opt").height("auto");
  $("#tabs-hel").height("auto");
  $("#tabs-mentat").height("auto");

  $(".button").button();

  sounds_enabled = simpleStorage.get('sndFX');

  if (sounds_enabled == null) {
    // Default to true, except when known to be problematic.
    if (platform.name == 'Safari') {
      sounds_enabled = false;
    } else {
      sounds_enabled = true;
    }
  }

  mentat_enabled = simpleStorage.get('mentat_setting');
  if (mentat_enabled == null || !is_webgpu_supported()) {
    mentat_enabled = false;
  }

  dialogs_minimized_setting = simpleStorage.get('dialogs_minimized_setting');

  init_common_intro_dialog();
  setup_window_size();

 $("#mapcanvas").hide();

  setInterval(updateElementsPosition, 2000);

}

/**************************************************************************
 Shows a intro dialog depending on game type.
**************************************************************************/
function init_common_intro_dialog() {
  if (observing) {
    show_intro_dialog("Welcome to Fciv.net",
      "You have joined the game as an observer. Please enter your name:");
    $("#turn_done_button").button( "option", "disabled", true);

  } else if (is_small_screen()) {
      show_intro_dialog("Welcome to Fciv.net",
        "You are about to join the game. Please enter your name:");
  } else if ($.getUrlVar('action') == "earthload") {
    show_intro_dialog("Welcome to Freeciv-web",
      "You can now play Freeciv-web on the earth map you have chosen. " +
      "Please enter your name: ");

  } else if ($.getUrlVar('action') == "load") {
    show_intro_dialog("Welcome to Fciv.net",
      "You are about to join this game server, where you can " +
      "load a savegame, tutorial, custom map generated from an image or a historical scenario map. " +
      "Please enter your name: ");

  } else if ($.getUrlVar('action') == "multi") {

      var msg = "You are about to join this game server, where you can "  +
                  "participate in a multiplayer game. You can customize the game " +
                  "settings, and wait for the minimum number of players before " +
                  "the game can start. ";
      show_intro_dialog("Welcome to Fciv.net", msg);

  } else {
    show_intro_dialog("Welcome to Fciv.net",
      "You can now play a game of Freeciv, where you can " +
      "play a singleplayer game against the Freeciv AI or multiplayer. You can " +
      "start the game directly by entering any name, or customize the game settings. " +
      "Creating a user account is optional, but savegame support requires that you create a user account.");
      $(".pwd_reset").click(forgot_pbem_password);
  }
}


/**************************************************************************
 Closes a generic message dialog.
**************************************************************************/
function close_dialog_message() {
  $("#generic_dialog").dialog('close');
}

function closing_dialog_message() {
  clearTimeout(dialog_message_close_task);
  $("#game_text_input").blur();
}

/**************************************************************************
 Shows a generic message dialog.
**************************************************************************/
function show_dialog_message(title, message) {

  // reset dialog page.
  $("#generic_dialog").remove();
  $("<div id='generic_dialog'></div>").appendTo("div#game_page");

  speak(title);
  speak(message);

  $("#generic_dialog").html(message);
  $("#generic_dialog").attr("title", title);
  $("#generic_dialog").dialog({
			bgiframe: true,
			modal: false,
			width: is_small_screen() ? "90%" : "50%",
			close: closing_dialog_message,
			buttons: {
				Ok: close_dialog_message
			}
		}).dialogExtend({
                   "minimizable" : true,
                   "closable" : true,
                   "icons" : {
                     "minimize" : "ui-icon-circle-minus",
                     "restore" : "ui-icon-newwin"
                   }});

  $("#generic_dialog").dialog('open');
  $("#game_text_input").blur();

  $('#generic_dialog').css("max-height", "450px");

  // Auto-minimize dialogs for observers (non-interactive viewing)
  // or when user has enabled the dialogs_minimized_setting
  if (dialogs_minimized_setting || client_is_observer()) {
    $("#generic_dialog").dialogExtend("minimize");
  }

}


/**************************************************************************
 ...
**************************************************************************/
function validate_username() {
  username = $("#username_req").val();

  if (!is_username_valid_show(username)) {
    return false;
  }

  simpleStorage.set("username", username);

  return true;
}

/**************************************************************************
 Checks if the username is valid and shows the reason if it is not.
 Returns whether the username is valid.
**************************************************************************/
function is_username_valid_show(username) {
  var reason = get_invalid_username_reason(username);
  if (reason != null) {
    $("#username_validation_result").html("The username '"
                + username.replace(/&/g, "&amp;").replace(/</g, "&lt;")
                + "' is " + reason + ".");
    $("#username_validation_result").show();
    return false;
  }
  return true;
}




/* Webclient is always client. */
function is_server()
{
  return false;
}

/**************************************************************************
 ...
**************************************************************************/
function update_timeout()
{
  var now = new Date().getTime();
  if (game_info != null
      && current_turn_timeout() != null && current_turn_timeout() > 0) {
    var remaining = Math.floor(seconds_to_phasedone - ((now - seconds_to_phasedone_sync) / 1000));

    if (remaining >= 0 && turn_change_elapsed == 0) {
      if (is_small_screen()) {
        $("#turn_done_button").button("option", "label", "Turn " + remaining);
        $("#turn_done_button .ui-button-text").css("padding", "3px");
      } else {
        $("#turn_done_button").button("option", "label", "Turn Done (" + seconds_to_human_time(remaining) + ")");
      }
      if (!is_touch_device()) {
        $("#turn_done_button").tooltip({ disabled: false });
      }
    }
  }
}


/**************************************************************************
 shows the remaining time of the turn change on the turn done button.
**************************************************************************/
function update_turn_change_timer()
{
  turn_change_elapsed += 1;
  if (turn_change_elapsed < last_turn_change_time) {
    setTimeout(update_turn_change_timer, 1000);
    $("#turn_done_button").button("option", "label", "Please wait (" 
        + (last_turn_change_time - turn_change_elapsed) + ")");
  } else {
    turn_change_elapsed = 0;
    $("#turn_done_button").button("option", "label", "Turn Done"); 
  }
}

/**************************************************************************
 ...
**************************************************************************/
function set_phase_start()
{
  phase_start_time = new Date().getTime();
}

/**************************************************************************
  Request to observe the game. Supports both global observation and
  player-specific FOW attachment via the observe_player URL parameter.
  Includes retry logic for failed connections.

  @param player_to_attach - Optional player name to attach to. If not provided,
                           falls back to the observe_player global (from URL).
                           Pass null explicitly for global observation.
**************************************************************************/
function request_observe_game(player_to_attach)
{
  // Use explicit parameter if provided, otherwise check URL-param global
  var target_player = player_to_attach;
  if (target_player === undefined) {
    target_player = observe_player;  // From URL param via init_observe_player_mode()
  }

  if (target_player && target_player !== '') {
    // Player-specific FOW observation
    // SECURITY: Validate player name to prevent command injection
    if (!SAFE_PLAYER_NAME_REGEX.test(target_player)) {
      console.error('[Observer] Invalid player name contains unsafe characters:', target_player);
      send_message("/observe ");
      setup_observer_timeout_with_retry('global');
      return;
    }
    send_message('/observe ' + target_player);
    setup_observer_timeout_with_retry(target_player);
  } else {
    // Global observer
    send_message("/observe ");
    setup_observer_timeout_with_retry('global');
  }
}

/**************************************************************************
...
**************************************************************************/
function surrender_game()
{
  send_surrender_game();
  set_default_mapview_active();

}

/**************************************************************************
...
**************************************************************************/
function send_surrender_game()
{
  if (!client_is_observer() && ws != null && ws.readyState === 1) {
    send_message("/surrender ");
  }
}

/**************************************************************************
...
**************************************************************************/
function show_fullscreen_window()
{
  if (BigScreen.enabled) {
    BigScreen.toggle();
  } else {
   show_dialog_message('Fullscreen', 'Press F11 for fullscreen mode.');
  }

}

/**************************************************************************
...
**************************************************************************/
function show_debug_info()
{
  // Enable debug logging when this function is called
  debug_active = true;

  freelog(LOG_DEBUG, "Freeciv version: " + freeciv_version);
  freelog(LOG_DEBUG, "Browser useragent: " + navigator.userAgent);
  freelog(LOG_DEBUG, "jQuery version: " + $().jquery);
  freelog(LOG_DEBUG, "jQuery UI version: " + $.ui.version);
  freelog(LOG_DEBUG, "simpleStorage version: " + simpleStorage.version);
  freelog(LOG_DEBUG, "Touch device: " + is_touch_device());
  freelog(LOG_DEBUG, "HTTP protocol: " + document.location.protocol);
  if (ws != null && ws.url != null) freelog(LOG_DEBUG, "WebSocket URL: " + ws.url);

  /* Show average network latency PING (server to client, and back). */
  var sum = 0;
  var max = 0;
  for (var i = 0; i < debug_ping_list.length; i++) {
    sum += debug_ping_list[i];
    if (debug_ping_list[i] > max) max = debug_ping_list[i];
  }
  freelog(LOG_DEBUG, "Network PING average (server): " + (sum / debug_ping_list.length) + " ms. (Max: " + max +"ms.)");

  /* Show average network latency PING (client to server, and back). */
  sum = 0;
  max = 0;
  for (var j = 0; j < debug_client_speed_list.length; j++) {
    sum += debug_client_speed_list[j];
    if (debug_client_speed_list[j] > max) max = debug_client_speed_list[j];
  }
  freelog(LOG_DEBUG, "Network PING average (client): " + (sum / debug_client_speed_list.length) + " ms.  (Max: " + max +"ms.)");

  try {
    freelog(LOG_DEBUG, "Renderer info: " + JSON.stringify(maprenderer.info));
  } catch (e) {
    freelog(LOG_DEBUG, "Renderer info: [unable to serialize]");
  }

}

/**************************************************************************
  This function can be used to display a message of the day to users.
  It is run on startup of the game, and every 30 minutes after that.
  The /motd.js Javascript file is fetched using AJAX, and executed
  so it can run any Javascript code. See motd.js also.
**************************************************************************/
function motd_init()
{
  $.getScript("/motd.js");
  setTimeout(motd_init, 1000*60*30);
}

/**************************************************************************
 Shows the authentication and password dialog.
**************************************************************************/
function show_auth_dialog(packet) {

  // reset dialog page.
  $("#dialog").remove();
  $("<div id='dialog'></div>").appendTo("div#game_page");

  var intro_html = packet['message']
      + "<br><br> Password: <input id='password_req' type='text' size='25'>";
  $("#dialog").html(intro_html);
  $("#dialog").attr("title", "Private server needs password to enter");
  $("#dialog").dialog({
			bgiframe: true,
			modal: true,
			width: is_small_screen() ? "80%" : "60%",
			buttons:
			{
				"Ok" : function() {
                                  var pwd_packet = {"pid" : packet_authentication_reply, "password" : $('#password_req').val()};
                                  var myJSONText = JSON.stringify(pwd_packet);
                                  send_request(myJSONText);

                                  $("#dialog").dialog('close');
				}
			}
		});


  $("#dialog").dialog('open');


}

