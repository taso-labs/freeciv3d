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

  console.log(`Preparing spectator for game: ${spectator_game_id} on port ${spectator_game_port}`);

  // Initialize game components (loads sprites and 3D models)
  init_spectator_game();

  // SPECTATOR FIX: Don't connect WebSocket yet!
  // Wait for 3D models to finish loading to avoid race condition.
  // Connection will be triggered by spectator_models_ready() when models finish.
  console.log("[SPECTATOR] Waiting for 3D models to load before connecting WebSocket...");
}

/**
 * Called when 3D models finish loading - safe to connect WebSocket now
 */
function spectator_models_ready() {
  console.log("[SPECTATOR] ✅ 3D models loaded, connecting to game server...");

  // Now it's safe to connect - models are ready for rendering
  connect_to_spectator_game();
}

/**
 * Initialize game components for spectator mode
 */
function init_spectator_game() {
  console.log("Initializing spectator game components...");

  try {
    // SPECTATOR FIX: Verify mapcanvas element exists before initializing WebGL
    var mapcanvas = document.getElementById('mapcanvas');
    if (!mapcanvas) {
      console.error("mapcanvas element not found - cannot initialize WebGL");
      show_spectator_error("Map canvas element not found. Please reload the page.");
      return;
    }

    console.log("mapcanvas element found, proceeding with initialization");

    // SPECTATOR FIX: Load tilesets before initializing WebGL
    // init_sprites() loads tileset images, then calls webgl_preload() automatically
    if (typeof init_sprites === 'function') {
      console.log("Loading tilesets for spectator mode...");
      init_sprites();  // Shows "Loading graphics..." → loads tiles → inits WebGL with textures
    } else {
      console.warn("init_sprites not available - falling back to direct WebGL init");
      if (typeof init_webgl_renderer === 'function') {
        init_webgl_renderer();
      }
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

    // Note: FreeCiv3D uses WebGL rendering only, no 2D canvas initialization needed

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

  // Determine the WebSocket URL based on the game type
  var ws_url;

  // Check if this is an LLM Gateway game (detect by game_id pattern)
  // LLM games have game_id starting with "game_" or "llm_"
  var isLlmGame = spectator_game_id.startsWith('game_') ||
                  spectator_game_id.startsWith('llm_') ||
                  spectator_game_id === 'default';

  var host = window.location.hostname;

  if (isLlmGame) {
    // LLM GAMES: Connect to LLM Gateway spectator broadcast endpoint
    // This receives FreeCiv protocol packets relayed from agent connections
    var gateway_port = 8003;  // LLM Gateway port
    ws_url = `ws://${host}:${gateway_port}/ws/spectator/${spectator_game_id}`;
    console.log("Connecting to LLM Gateway spectator broadcast:", spectator_game_id);
    console.log(`  WebSocket URL: ${ws_url}`);
    console.log(`  View: Player 1 perspective (MVP)`);
  } else {
    // TRADITIONAL GAMES: Connect via FreeCiv proxy
    var proxy_port = 8002;  // FreeCiv proxy port
    ws_url = `ws://${host}:${proxy_port}/civsocket/${spectator_game_port}`;
    console.log("Connecting to FreeCiv proxy as observer for traditional game");
    console.log(`  WebSocket URL: ${ws_url}`);
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

    // Filter console logs to reduce noise - only log important packets
    // PIDs of interest: 126 (START_PHASE), 140 (RULESET_UNIT), 16 (GAME_INFO), 17 (MAP_INFO)
    var important_pids = [16, 17, 126, 140];
    var should_log = !message.pid || important_pids.indexOf(message.pid) !== -1 || message.type === 'freeciv_update';

    if (should_log) {
      console.log("Spectator received:", message);
    }

    // Route message to appropriate handler
    // LLM games now connect to FreeCiv proxy, so use standard protocol
    if (message.pid !== undefined) {
      // Standard FreeCiv protocol message
      try {
        handle_spectator_freeciv_message(message);
      } catch (handlerError) {
        console.error("Error handling FreeCiv packet (PID " + message.pid + "):", handlerError);
        console.error("Problematic packet:", message);
        // Don't let one packet error kill the whole connection - keep going
      }
    } else if (message.type !== undefined) {
      // Custom message format
      try {
        handle_spectator_custom_message(message);
      } catch (handlerError) {
        console.error("Error handling custom message (type " + message.type + "):", handlerError);
        console.error("Problematic message:", message);
        // Don't let one message error kill the whole connection - keep going
      }
    }

  } catch (error) {
    console.error("Failed to parse spectator message:", error, data);
    // Don't throw - keep connection alive even if one message fails
  }
}

/**
 * Handle FreeCiv protocol messages
 */
function handle_spectator_freeciv_message(message) {
  // Reuse existing packet handlers where possible
  // PIDs from freeciv/common/networking/packets.def
  switch (message.pid) {
    case 5: // PACKET_SERVER_JOIN_REPLY
      handle_spectator_join_reply(message);
      break;

    case 16: // PACKET_GAME_INFO (was incorrectly 15)
      if (typeof handle_game_info === 'function') {
        handle_game_info(message);
      }
      break;

    case 17: // PACKET_MAP_INFO (was incorrectly 25) - CRITICAL for map rendering
      if (typeof handle_map_info === 'function') {
        console.log("[SPECTATOR] Processing PACKET_MAP_INFO (PID 17) - map data received");
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
        console.log("[SPECTATOR] Map info processed, map object:", typeof map !== 'undefined' ? "set" : "undefined");
      }
      break;

    case 15: // PACKET_TILE_INFO (was incorrectly 55)
      if (typeof handle_tile_info === 'function') {
        handle_tile_info(message);

        // Trigger map redraw to show updated tiles
        if (typeof webgl_render_scene === 'function') {
          webgl_render_scene();
        }
      }
      break;

    case 51: // PACKET_PLAYER_INFO (was incorrectly 75)
      if (typeof handle_player_info === 'function') {
        handle_player_info(message);
      }
      break;

    case 31: // PACKET_CITY_INFO (was incorrectly 85)
      if (typeof handle_city_info === 'function') {
        handle_city_info(message);
      }
      break;

    case 63: // PACKET_UNIT_INFO (was incorrectly 95)
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
      console.log("✅ Successfully joined LLM game as spectator");
      update_connection_status("Observing LLM Game", "green");

      // SPECTATOR FIX: Mark connection as established so packet handlers work correctly
      if (client && client.conn) {
        client.conn.established = true;
        console.log("[SPECTATOR] Connection marked as established");
      }

      // SPECTATOR FIX: The Gateway sends cached packets automatically after spectator_joined
      // These packets include PACKET_START_PHASE which should trigger renderer_init()
      // If renderer doesn't initialize within 2 seconds, force initialization
      console.log("[SPECTATOR] Cached packets will arrive shortly, waiting for PACKET_START_PHASE...");

      setTimeout(function() {
        // Check if renderer was initialized by PACKET_START_PHASE
        if (typeof scene === 'undefined' || scene === null) {
          console.warn("[SPECTATOR] Renderer not initialized after 2s, forcing initialization...");
          console.log("[SPECTATOR] Current client_state:", typeof client_state === 'function' ? client_state() : 'undefined');

          // Force renderer initialization
          if (typeof renderer_init === 'function') {
            renderer_init();
          } else {
            console.error("[SPECTATOR] renderer_init() not available!");
          }
        } else {
          console.log("[SPECTATOR] ✅ Renderer already initialized by packet handler");
        }
      }, 2000);
      break;

    case 'state_response':
      // Game state message from LLM Gateway/agent
      console.log("📦 Received state_response message");

      // state_response can have different formats:
      // 1. Message with nested packets array: {type: "state_response", state: {packets: [...]}}
      // 2. Message with data field: {type: "state_response", data: {...}}
      // 3. Simple acknowledgment: {type: "state_response", success: true}

      if (message.state && message.state.packets) {
        // Format 1: Nested packets array
        console.log(`Processing ${message.state.packets.length} FreeCiv packets from state_response`);
        message.state.packets.forEach(function(packet, index) {
          try {
            if (packet.pid !== undefined) {
              handle_spectator_freeciv_message(packet);
            }
          } catch (error) {
            console.error(`Error processing packet ${index} (pid: ${packet.pid}):`, error);
          }
        });
      } else if (message.data) {
        // Format 2: Data field - treat as game state update
        console.log("Processing state data:", message.data);
        handle_llm_game_state_update({type: 'game_state', data: message.data});
      } else {
        // Format 3: Simple acknowledgment or unknown format
        console.log("state_response acknowledged (no packet data):", message);
      }
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
  // Route LLM Gateway messages to the appropriate handler
  if (message.type === 'spectator_joined' ||
      message.type === 'state_response' ||
      message.type === 'game_state' ||
      message.type === 'turn_update' ||
      message.type === 'player_action' ||
      message.type === 'game_ended') {
    // These are LLM Gateway broadcast messages
    handle_llm_spectator_message(message);
    return;
  }

  // Handle other custom message types
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