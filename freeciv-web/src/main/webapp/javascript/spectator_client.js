/**********************************************************************
    FreeCiv3D Spectator Client - Watch LLM Gateway games
    Copyright (C) 2024  FreeCiv3D project

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
***********************************************************************/

var spectator_ws = null;
var spectator_connected = false;
var spectator_game_id = null;
var spectator_game_port = null;
var reconnect_attempts = 0;
var max_reconnect_attempts = 5;

/**
 * Initialize the spectator client
 */
function init_spectator_client() {
  console.log("Initializing spectator client...");

  // Get parameters from global variables set in JSP
  if (typeof spectatorGameId !== 'undefined') {
    spectator_game_id = spectatorGameId;
  }
  if (typeof spectatorGamePort !== 'undefined') {
    spectator_game_port = spectatorGamePort;
  }

  if (!spectator_game_id || !spectator_game_port) {
    show_spectator_error("Missing game parameters (game_id or port)");
    return;
  }

  // Ensure client object exists and has proper structure
  if (typeof client === 'undefined') {
    window.client = {
      conn: {
        playing: null,
        observer: true,
        established: false
      }
    };
  } else if (!client.conn) {
    client.conn = {
      playing: null,
      observer: true,
      established: false
    };
  }

  // Initialize client state for spectator mode
  client.conn.playing = null;
  client.conn.observer = true;
  window.observing = true;
  window.isSpectator = true;

  console.log(`Connecting to spectator game: ${spectator_game_id} on port ${spectator_game_port}`);

  // Initialize game components
  init_spectator_game();

  // Connect to the game server
  connect_to_spectator_game();
}

/**
 * Initialize game components for spectator mode
 */
function init_spectator_game() {
  console.log("Initializing spectator game components...");

  try {
    // Initialize WebGL renderer (reuse existing function)
    if (typeof init_webgl_renderer === 'function') {
      console.log("Initializing WebGL renderer...");
      init_webgl_renderer();
    } else {
      console.warn("init_webgl_renderer not available");
    }

    // Initialize game state (reuse existing function)
    if (typeof game_init === 'function') {
      console.log("Initializing game state...");
      game_init();
    } else {
      console.warn("game_init not available");
    }

    // Initialize controls in spectator mode
    if (typeof control_init === 'function') {
      console.log("Initializing controls...");
      control_init();
    } else {
      console.warn("control_init not available");
    }

    // Initialize map canvas for spectator mode
    if (typeof init_mapcanvas_2d === 'function') {
      console.log("Initializing map canvas...");
      init_mapcanvas_2d();
    } else {
      console.warn("init_mapcanvas_2d not available");
    }

    // Set up UI for spectator mode
    setup_spectator_ui();

    console.log("Spectator game components initialized successfully");
  } catch (error) {
    console.error("Error initializing spectator game components:", error);
    show_spectator_error("Failed to initialize game components: " + error.message);
  }
}

/**
 * Set up UI elements specific to spectator mode
 */
function setup_spectator_ui() {
  console.log("Setting up spectator UI...");

  // Hide player-specific buttons
  $("#turn_done_button_div").hide();
  $("#pregame_buttons").hide();

  // Disable interactive elements
  $("input, button").not("#tabs, #tabs a, .ui-tabs-nav a").prop('disabled', true);

  // Show spectator indicators
  update_connection_status("Connecting...", "orange");
}

/**
 * Connect to the FreeCiv game server as spectator
 */
function connect_to_spectator_game() {
  console.log(`Connecting to game server on port ${spectator_game_port}...`);

  // Determine the WebSocket URL based on the port and game type
  var ws_url;

  // Check if this is an LLM Gateway game
  var isLlmGame = spectator_game_port == 8003 ||
                  spectator_game_id.startsWith('llm_') ||
                  spectator_game_id === 'default';

  if (isLlmGame) {
    // Connect to FreeCiv proxy as observer to get actual map data
    // LLM games run on port 6001, connect as observer to see the map
    var host = window.location.hostname;
    var port = 8002; // FreeCiv proxy port
    ws_url = `ws://${host}:${port}/civsocket/6001`;
    console.log("Connecting to FreeCiv proxy as observer for LLM game:", ws_url);
  } else {
    // Traditional FreeCiv proxy WebSocket
    var host = window.location.hostname;
    var port = 8002; // FreeCiv proxy port
    ws_url = `ws://${host}:${port}/civsocket/${spectator_game_port}`;
    console.log("Connecting to FreeCiv proxy:", ws_url);
  }

  try {
    spectator_ws = new WebSocket(ws_url);

    spectator_ws.onopen = function(event) {
      console.log("WebSocket connection established");
      spectator_connected = true;
      reconnect_attempts = 0;

      update_connection_status("Connected", "green");

      // Initialize map display for connected game
      initialize_spectator_map_display();

      // Send observer connection request (always use FreeCiv protocol now)
      send_spectator_join_game();
    };

    spectator_ws.onmessage = function(event) {
      handle_spectator_message(event.data);
    };

    spectator_ws.onclose = function(event) {
      console.log("WebSocket connection closed:", event.code, event.reason);
      spectator_connected = false;

      // Check if this is initial connection failure (no game running)
      if (reconnect_attempts === 0 && event.code === 1006) {
        update_connection_status("No Game Running", "red");
        show_spectator_message("No active game found on port " + spectator_game_port + ". Please check if a game is running or try a different game ID.");
        return;
      }

      update_connection_status("Disconnected", "red");

      // Attempt to reconnect
      if (reconnect_attempts < max_reconnect_attempts) {
        setTimeout(function() {
          reconnect_attempts++;
          console.log(`Reconnection attempt ${reconnect_attempts}/${max_reconnect_attempts}`);
          update_connection_status(`Reconnecting... (${reconnect_attempts}/${max_reconnect_attempts})`, "orange");
          connect_to_spectator_game();
        }, 3000 * reconnect_attempts); // Exponential backoff
      } else {
        show_spectator_error("Connection lost. Maximum reconnection attempts reached.");
      }
    };

    spectator_ws.onerror = function(error) {
      console.error("WebSocket error:", error);
      update_connection_status("Connection Error", "red");
    };

  } catch (error) {
    console.error("Failed to create WebSocket:", error);
    show_spectator_error("Failed to connect to game server");
  }
}

/**
 * Send join game request as observer
 */
function send_spectator_join_game() {
  console.log("Sending observer join request...");

  var join_message = {
    pid: 4, // PACKET_SERVER_JOIN_REQ
    username: `spectator_${Date.now()}`,
    capability: "+Freeciv-3.3-network",
    version_label: "freeciv-web 3.3",
    major_version: 3,
    minor_version: 3,
    patch_version: 0,
    observer: true
  };

  send_spectator_message(join_message);
}

/**
 * Send LLM Gateway spectator join request
 */
function send_llm_spectator_join() {
  console.log("Sending LLM Gateway spectator join request...");

  var join_message = {
    type: "spectator_join",
    game_id: spectator_game_id,
    spectator_id: `spectator_${Date.now()}`,
    timestamp: Date.now()
  };

  send_spectator_message(join_message);
}

/**
 * Handle incoming messages from the game server
 */
function handle_spectator_message(data) {
  try {
    var message = JSON.parse(data);

    // Log message for debugging
    if (typeof fcwDebug !== 'undefined' && fcwDebug) {
      console.log("Spectator received:", message);
    }

    // Route message to appropriate handler
    // LLM games now connect to FreeCiv proxy, so use standard protocol
    if (message.pid !== undefined) {
      // Standard FreeCiv protocol message
      handle_spectator_freeciv_message(message);
    } else if (message.type !== undefined) {
      // Custom message format
      handle_spectator_custom_message(message);
    }

  } catch (error) {
    console.error("Failed to parse spectator message:", error, data);
  }
}

/**
 * Handle FreeCiv protocol messages
 */
function handle_spectator_freeciv_message(message) {
  // Reuse existing packet handlers where possible
  switch (message.pid) {
    case 5: // PACKET_SERVER_JOIN_REPLY
      handle_spectator_join_reply(message);
      break;

    case 15: // PACKET_GAME_INFO
      if (typeof handle_game_info === 'function') {
        handle_game_info(message);
      }
      break;

    case 25: // PACKET_MAP_INFO
      if (typeof handle_map_info === 'function') {
        handle_map_info(message);
        // Ensure map canvas is visible for spectator
        $("#mapcanvas").show();

        // Force map rendering initialization for spectators
        if (typeof webgl_init_mapview === 'function') {
          webgl_init_mapview();
        }
        if (typeof init_mapcanvas_2d === 'function') {
          init_mapcanvas_2d();
        }
      }
      break;

    case 55: // PACKET_TILE_INFO
      if (typeof handle_tile_info === 'function') {
        handle_tile_info(message);

        // Trigger map redraw to show updated tiles
        if (typeof webgl_render_scene === 'function') {
          webgl_render_scene();
        }
      }
      break;

    case 75: // PACKET_PLAYER_INFO
      if (typeof handle_player_info === 'function') {
        handle_player_info(message);
      }
      break;

    case 85: // PACKET_CITY_INFO
      if (typeof handle_city_info === 'function') {
        handle_city_info(message);
      }
      break;

    case 95: // PACKET_UNIT_INFO
      if (typeof handle_unit_info === 'function') {
        handle_unit_info(message);
      }
      break;

    default:
      // Try to route to existing packet handlers
      if (typeof packet_handlers !== 'undefined' && packet_handlers[message.pid]) {
        packet_handlers[message.pid](message);
      }
      break;
  }
}

/**
 * Handle LLM Gateway spectator messages
 */
function handle_llm_spectator_message(message) {
  switch (message.type) {
    case 'spectator_joined':
      console.log("Successfully joined LLM game as spectator");
      update_connection_status("Observing LLM Game", "green");
      break;

    case 'game_state':
      handle_llm_game_state_update(message);
      break;

    case 'turn_update':
      handle_llm_turn_update(message);
      break;

    case 'player_action':
      handle_llm_player_action(message);
      break;

    case 'game_ended':
      handle_llm_game_ended(message);
      break;

    case 'error':
      show_spectator_error(message.message || "LLM Gateway error occurred");
      break;

    default:
      console.log("Unknown LLM Gateway spectator message type:", message.type);
      break;
  }
}

/**
 * Handle custom message types
 */
function handle_spectator_custom_message(message) {
  switch (message.type) {
    case 'game_update':
      handle_spectator_game_update(message);
      break;

    case 'turn_change':
      handle_spectator_turn_change(message);
      break;

    case 'error':
      show_spectator_error(message.message || "Game error occurred");
      break;

    default:
      console.log("Unknown spectator message type:", message.type);
      break;
  }
}

/**
 * Handle join reply from server
 */
function handle_spectator_join_reply(message) {
  console.log("Join reply received:", message);

  if (message.you_can_join) {
    console.log("Successfully joined as observer");
    update_connection_status("Observing Game", "green");

    // Request initial game state
    request_spectator_game_state();
  } else {
    console.error("Failed to join game:", message.message);
    show_spectator_error(message.message || "Failed to join game as observer");
  }
}

/**
 * Request current game state
 */
function request_spectator_game_state() {
  console.log("Requesting game state...");

  // Send request for game info
  send_spectator_message({
    pid: 14 // PACKET_GAME_INFO_REQ
  });

  // Send request for map info
  send_spectator_message({
    pid: 24 // PACKET_MAP_INFO_REQ
  });
}

/**
 * Handle game update messages
 */
function handle_spectator_game_update(message) {
  console.log("Game update received:", message.data);

  if (message.data.turn !== undefined) {
    // Update turn display
    if (typeof update_game_status_panel === 'function') {
      update_game_status_panel();
    }
  }

  if (message.data.players !== undefined) {
    // Update player information
    message.data.players.forEach(function(player_data) {
      if (typeof handle_player_info === 'function') {
        handle_player_info(player_data);
      }
    });
  }
}

/**
 * Handle turn change notifications
 */
function handle_spectator_turn_change(message) {
  console.log("Turn change:", message.turn);

  // Update UI to reflect new turn
  if (typeof update_game_status_panel === 'function') {
    update_game_status_panel();
  }

  // Refresh the map display
  if (typeof init_mapcanvas_2d === 'function') {
    init_mapcanvas_2d();
  }
  if (typeof webgl_render_scene === 'function') {
    webgl_render_scene();
  }
}

/**
 * Send message to game server
 */
function send_spectator_message(message) {
  if (spectator_ws && spectator_ws.readyState === WebSocket.OPEN) {
    var json_message = JSON.stringify(message);
    spectator_ws.send(json_message);

    if (typeof fcwDebug !== 'undefined' && fcwDebug) {
      console.log("Spectator sent:", message);
    }
  } else {
    console.error("Cannot send message: WebSocket not connected");
  }
}

/**
 * Update connection status indicator
 */
function update_connection_status(status, color) {
  $("#connection_indicator").text(status).css("color", color);

  // Also update map status if it exists
  if ($("#map_status").length > 0) {
    $("#map_status").text(status).css("color", color);
  }
}

/**
 * Show spectator error message
 */
function show_spectator_error(message) {
  console.error("Spectator error:", message);

  update_connection_status("Error", "red");

  // Show error in UI
  if (typeof swal !== 'undefined') {
    swal("Spectator Error", message, "error");
  } else {
    alert("Spectator Error: " + message);
  }
}

/**
 * Show spectator info message
 */
function show_spectator_message(message) {
  console.log("Spectator info:", message);

  // Show info in UI
  if (typeof swal !== 'undefined') {
    swal("Spectator Info", message, "info");
  } else {
    alert("Spectator Info: " + message);
  }
}

/**
 * Initialize map display for spectator mode
 */
function initialize_spectator_map_display() {
  console.log("Initializing spectator map display...");

  // Replace the placeholder with actual map canvas
  $("#tabs-map").html('<jsp:include page="canvas.jsp" flush="false"/>');

  // Show the map canvas
  $("#mapcanvas").show();

  // Initialize map rendering if functions are available
  if (typeof init_mapcanvas_2d === 'function') {
    try {
      init_mapcanvas_2d();
    } catch (e) {
      console.log("Could not initialize 2D map canvas:", e);
    }
  }

  if (typeof webgl_init_mapview === 'function') {
    try {
      webgl_init_mapview();
    } catch (e) {
      console.log("Could not initialize WebGL mapview:", e);
    }
  }
}

/**
 * Handle LLM game state updates
 */
function handle_llm_game_state_update(message) {
  console.log("LLM game state update:", message.data);

  if (message.data.game_info) {
    // Update game information display
    $("#spectator_header .spectator-info").last().html(`Turn: <strong>${message.data.game_info.turn || 0}</strong>`);
  }

  if (message.data.map_info) {
    // Update map information
    console.log("Map info received:", message.data.map_info);

    // Initialize map if not already done
    if (typeof init_mapcanvas_2d === 'function') {
      init_mapcanvas_2d();
    }
  }

  if (message.data.players) {
    // Update player information in the Nations tab
    console.log("Player info received:", message.data.players);
  }
}

/**
 * Handle LLM turn updates
 */
function handle_llm_turn_update(message) {
  console.log("LLM turn update:", message.turn);

  // Update turn display in header
  $("#spectator_header .spectator-info").last().html(`Turn: <strong>${message.turn}</strong>`);

  // Force map refresh
  if (typeof webgl_render_scene === 'function') {
    webgl_render_scene();
  }
}

/**
 * Handle LLM player actions
 */
function handle_llm_player_action(message) {
  console.log("LLM player action:", message.action);

  // Update UI based on player action
  if (message.action.type === 'move_unit') {
    // Animate unit movement if possible
    console.log(`Player ${message.player_id} moved unit from ${message.action.from} to ${message.action.to}`);
  }

  // Force map refresh
  if (typeof webgl_render_scene === 'function') {
    webgl_render_scene();
  }
}

/**
 * Handle LLM game ended
 */
function handle_llm_game_ended(message) {
  console.log("LLM game ended:", message.result);

  update_connection_status("Game Ended", "orange");

  // Show game result
  if (typeof swal !== 'undefined') {
    swal("Game Ended", `Result: ${message.result.winner || 'Game completed'}`, "info");
  }
}

/**
 * Clean up spectator client resources
 */
function cleanup_spectator_client() {
  console.log("Cleaning up spectator client...");

  if (spectator_ws) {
    spectator_ws.close();
    spectator_ws = null;
  }

  spectator_connected = false;
}

// Cleanup on page unload
$(window).on('beforeunload', function() {
  cleanup_spectator_client();
});