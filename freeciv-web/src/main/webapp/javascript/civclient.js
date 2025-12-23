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

// Observer follow mode state
var observer_follow_player = null;        // Player ID to follow, or null for global
var observer_auto_center_interval = null; // Interval timer ID for periodic re-centering
var observer_initial_center_interval = null; // Interval timer ID for initial center polling
var observer_player_search_interval = null; // Interval timer ID for player search polling
var OBSERVER_AUTO_CENTER_MS = 5000;       // Default re-center interval (5 seconds)
var MIN_AUTOCENTER_MS = 1000;             // Minimum autocenter interval (1 second)
var MAX_AUTOCENTER_MS = 60000;            // Maximum autocenter interval (60 seconds)
var MAX_INITIAL_CENTER_ATTEMPTS = 10;     // Max polling attempts for initial center
var INITIAL_CENTER_POLL_INTERVAL_MS = 500; // Polling interval for initial center (500ms)
var embed_mode = false;                   // Embed mode for iframe viewing
var keyboard_input_enabled = true;        // Keyboard input enabled flag

// Player name validation regex - allows letters, numbers, underscore, asterisk (for AI*1), hyphen
var SAFE_PLAYER_NAME_REGEX = /^[a-zA-Z0-9_*-]+$/;

// Observer player attachment state
var observe_player = null;                // Player name to attach to, or null for global

// Autojoin state
var autojoin_active = false;              // Whether autojoin mode is active

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

  // Parse follow parameter
  var follow_param = $.getUrlVar('follow');
  if (!follow_param) return;

  // Decode URL-encoded characters (e.g., AI%2A1 → AI*1)
  follow_param = decodeURIComponent(follow_param);

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

  // Find player by name, username, or playerno (with null checks for defensive coding)
  for (var player_id in players) {
    var player = players[player_id];
    if (player && (
        player['name'] === follow_param ||
        (player['username'] && player['username'] === follow_param) ||
        (player['playerno'] !== undefined && player['playerno'].toString() === follow_param))) {
      observer_follow_player = player['playerno'];
      console.log('[Observer] Following player:', player['name'] || 'Unknown', 'id:', observer_follow_player);
      break;
    }
  }

  if (observer_follow_player !== null) {
    start_observer_follow_intervals();
  } else {
    // Player not found immediately - poll until players list is populated
    console.log('[Observer] Player not found yet, polling for:', follow_param);
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
          console.log('[Observer] Found player after polling:', player['name'] || 'Unknown', 'id:', observer_follow_player);
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

  // Start auto-centering interval
  observer_auto_center_interval = setInterval(
    observer_center_on_followed_player,
    OBSERVER_AUTO_CENTER_MS
  );

  // Initial center with polling to wait for cities to load (more robust than fixed timeout)
  var initial_center_attempts = 0;
  observer_initial_center_interval = setInterval(function() {
    initial_center_attempts++;
    if (typeof cities !== 'undefined' && Object.keys(cities).length > 0) {
      clearInterval(observer_initial_center_interval);
      observer_initial_center_interval = null;
      observer_center_on_followed_player();
    } else if (initial_center_attempts >= MAX_INITIAL_CENTER_ATTEMPTS) {
      clearInterval(observer_initial_center_interval);
      observer_initial_center_interval = null;
      console.warn('[Observer] Cities not loaded after', MAX_INITIAL_CENTER_ATTEMPTS, 'attempts, giving up initial center');
    }
  }, INITIAL_CENTER_POLL_INTERVAL_MS);
}

/****************************************************************************
  Center view on followed player's main population center.
  Priority: 1) Capital city, 2) Largest city by size, 3) Any city
****************************************************************************/
function observer_center_on_followed_player()
{
  if (observer_follow_player === null) return;

  var player = players[observer_follow_player];
  if (!player || !player['is_alive']) {
    console.log('[Observer] Followed player not found or dead');
    return;
  }

  var target_city = null;

  // Priority 1: Capital city
  target_city = player_capital(player);

  // Priority 2: Largest city by population size
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

  // Center on target
  if (target_city) {
    var ptile = city_tile(target_city);
    if (ptile) {
      center_tile_mapcanvas(ptile);
      console.log('[Observer] Centered on', target_city['name'] || 'Unknown', 'size:', target_city['size'] || 0);
    }
  } else {
    console.log('[Observer] No cities found for player', observer_follow_player);
  }
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

  console.log('[Observer] Embed mode enabled - controls and UI disabled');
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

  console.log('[Autojoin] Starting autojoin mode with username:', username);

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

  // Initialize sprites/tileset - this triggers async loading chain:
  // init_sprites() → preload_check() → webgl_preload() → webgl_preload_complete() → network_init()
  // We must NOT call network_init() here - let the callback chain handle it after assets load
  init_sprites();
}

/****************************************************************************
  OBSERVER PLAYER ATTACHMENT SYSTEM
  Functions for attaching to a specific player's fog-of-war view.
****************************************************************************/

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
  if (!Detector.webgl) {
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

  if (dialogs_minimized_setting) {
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
...
**************************************************************************/
function request_observe_game()
{
  send_message("/observe ");
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
  console.log("Freeciv version: " + freeciv_version);
  console.log("Browser useragent: " + navigator.userAgent);
  console.log("jQuery version: " + $().jquery);
  console.log("jQuery UI version: " + $.ui.version);
  console.log("simpleStorage version: " + simpleStorage.version);
  console.log("Touch device: " + is_touch_device());
  console.log("HTTP protocol: " + document.location.protocol);
  if (ws != null && ws.url != null) console.log("WebSocket URL: " + ws.url);

  debug_active = true;
  /* Show average network latency PING (server to client, and back). */
  var sum = 0;
  var max = 0;
  for (var i = 0; i < debug_ping_list.length; i++) {
    sum += debug_ping_list[i];
    if (debug_ping_list[i] > max) max = debug_ping_list[i];
  }
  console.log("Network PING average (server): " + (sum / debug_ping_list.length) + " ms. (Max: " + max +"ms.)");

  /* Show average network latency PING (client to server, and back). */
  sum = 0;
  max = 0;
  for (var j = 0; j < debug_client_speed_list.length; j++) {
    sum += debug_client_speed_list[j];
    if (debug_client_speed_list[j] > max) max = debug_client_speed_list[j];
  }
  console.log("Network PING average (client): " + (sum / debug_client_speed_list.length) + " ms.  (Max: " + max +"ms.)");

  console.log(maprenderer.info);

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

