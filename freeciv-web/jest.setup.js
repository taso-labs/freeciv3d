/**
 * Jest Setup File for FreeCiv-web Tests
 *
 * This file runs before each test file and sets up:
 * - Global mocks for browser APIs
 * - Mock implementations for game globals
 * - Testing utilities
 */

// Import jest-dom for extended DOM matchers
require('@testing-library/jest-dom');

// Mock console methods to reduce noise in tests (optional: comment out for debugging)
// global.console = {
//   ...console,
//   log: jest.fn(),
//   warn: jest.fn(),
//   error: jest.fn(),
// };

// =============================================================================
// BROWSER API MOCKS
// =============================================================================

// Mock localStorage
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
  clear: jest.fn(),
};
global.localStorage = localStorageMock;

// Mock sessionStorage
global.sessionStorage = localStorageMock;

// Mock window.location
delete global.window.location;
global.window.location = {
  href: 'http://localhost:8080/webclient/',
  search: '',
  hash: '',
  pathname: '/webclient/',
  origin: 'http://localhost:8080',
  host: 'localhost:8080',
  hostname: 'localhost',
  port: '8080',
  protocol: 'http:',
  assign: jest.fn(),
  reload: jest.fn(),
  replace: jest.fn(),
};

// Mock requestAnimationFrame
global.requestAnimationFrame = jest.fn((callback) => setTimeout(callback, 16));
global.cancelAnimationFrame = jest.fn((id) => clearTimeout(id));

// =============================================================================
// JQUERY MOCK
// =============================================================================

// Create a minimal jQuery mock
const jQueryMock = jest.fn((selector) => ({
  remove: jest.fn(),
  hide: jest.fn(),
  show: jest.fn(),
  addClass: jest.fn(),
  removeClass: jest.fn(),
  css: jest.fn(),
  html: jest.fn(),
  text: jest.fn(),
  val: jest.fn(),
  attr: jest.fn(),
  prop: jest.fn(),
  on: jest.fn(),
  off: jest.fn(),
  click: jest.fn(),
  trigger: jest.fn(),
  append: jest.fn(),
  prepend: jest.fn(),
  empty: jest.fn(),
  find: jest.fn(() => jQueryMock(selector)),
  parent: jest.fn(() => jQueryMock(selector)),
  children: jest.fn(() => jQueryMock(selector)),
  siblings: jest.fn(() => jQueryMock(selector)),
  closest: jest.fn(() => jQueryMock(selector)),
  each: jest.fn(),
  map: jest.fn(),
  filter: jest.fn(),
  first: jest.fn(() => jQueryMock(selector)),
  last: jest.fn(() => jQueryMock(selector)),
  eq: jest.fn(() => jQueryMock(selector)),
  length: 0,
  button: jest.fn(),
  dialog: jest.fn(),
}));

// Add static jQuery methods
jQueryMock.ajax = jest.fn();
jQueryMock.get = jest.fn();
jQueryMock.post = jest.fn();
jQueryMock.getJSON = jest.fn();
jQueryMock.extend = jest.fn((target, ...sources) => Object.assign(target || {}, ...sources));
jQueryMock.blockUI = { defaults: {} };

// URL parameter parsing (commonly used in freeciv-web)
jQueryMock.getUrlVars = jest.fn(() => ({}));
jQueryMock.getUrlVar = jest.fn((name) => undefined);

global.$ = jQueryMock;
global.jQuery = jQueryMock;

// =============================================================================
// THREE.JS MOCK
// =============================================================================

const Vector3Mock = jest.fn((x = 0, y = 0, z = 0) => ({
  x, y, z,
  set: jest.fn(function(newX, newY, newZ) {
    this.x = newX;
    this.y = newY;
    this.z = newZ;
    return this;
  }),
  copy: jest.fn(function(v) {
    this.x = v.x;
    this.y = v.y;
    this.z = v.z;
    return this;
  }),
  clone: jest.fn(function() {
    return Vector3Mock(this.x, this.y, this.z);
  }),
  add: jest.fn(),
  sub: jest.fn(),
  multiply: jest.fn(),
  divide: jest.fn(),
  normalize: jest.fn(),
  length: jest.fn(() => 0),
  distanceTo: jest.fn(() => 0),
}));

global.THREE = {
  Vector3: Vector3Mock,
  PerspectiveCamera: jest.fn(() => ({
    position: { set: jest.fn(), x: 0, y: 0, z: 0 },
    lookAt: jest.fn(),
    updateProjectionMatrix: jest.fn(),
  })),
  Scene: jest.fn(() => ({
    add: jest.fn(),
    remove: jest.fn(),
  })),
  WebGLRenderer: jest.fn(() => ({
    setSize: jest.fn(),
    render: jest.fn(),
    domElement: document.createElement('canvas'),
  })),
  OrbitControls: jest.fn(() => ({
    target: { x: 0, y: 0, z: 0 },
    enabled: true,
    enableDamping: false,
    enablePan: true,
    dampingFactor: 0.05,
    maxPolarAngle: Math.PI / 2,
    update: jest.fn(),
    dispose: jest.fn(),
  })),
};

// =============================================================================
// FREECIV GAME GLOBALS MOCK
// =============================================================================

// Camera system globals
global.camera = null;
global.camera_dx = 50;
global.camera_dy = 410;
global.camera_dz = 242;
global.camera_current_x = 0;
global.camera_current_y = 0;
global.camera_current_z = 0;
global.controls = null;
global.spotlight = {
  position: { set: jest.fn() },
  target: { position: { set: jest.fn() } },
  shadow: {
    camera: {
      position: { copy: jest.fn() },
      lookAt: jest.fn(),
    },
  },
};
global.sun_mesh = null;

// Camera presets (from camera.js)
global.camera_presets = {
  'default':    { dx: 50,  dy: 410, dz: 242 },
  'strategic':  { dx: 50,  dy: 800, dz: 100 },
  'cinematic':  { dx: 50,  dy: 300, dz: 400 },
  'isometric':  { dx: 50,  dy: 500, dz: 500 },
};

// Camera preset functions (from camera.js)
global.camera_look_at = jest.fn((x, y, z) => {
  global.camera_current_x = x;
  global.camera_current_y = y;
  global.camera_current_z = z;

  if (global.camera != null) {
    global.camera.position.set(x + global.camera_dx, y + global.camera_dy, z + global.camera_dz);
    global.camera.lookAt(new THREE.Vector3(x, 0, z));
  }

  if (global.controls != null) {
    global.controls.target = new THREE.Vector3(x + 50, 50, z + 50);
  }
});

global.set_camera_preset = function(preset_name) {
  var preset = global.camera_presets[preset_name] || global.camera_presets['default'];
  global.camera_dx = preset.dx;
  global.camera_dy = preset.dy;
  global.camera_dz = preset.dz;

  // Re-apply camera position with new offsets if camera has a current position
  if (global.camera_current_x !== 0 || global.camera_current_z !== 0) {
    global.camera_look_at(global.camera_current_x, global.camera_current_y, global.camera_current_z);
  }
};

global.init_camera_from_url_params = function() {
  if (typeof $ !== 'undefined' && $.getUrlVar) {
    var camera_param = $.getUrlVar('camera');
    if (camera_param) {
      global.set_camera_preset(camera_param);
    }
  }
};

// Observer mode globals
global.observing = false;
global.observer_follow_player = null;
global.observer_auto_center_interval = null;
global.observer_initial_center_interval = null;
global.observer_player_search_interval = null;
global.OBSERVER_AUTO_CENTER_MS = 5000;
global.observer_user_interaction_time = 0;
global.OBSERVER_INTERACTION_COOLDOWN_MS = 45000;
global.observer_interaction_listeners_attached = false;
global.embed_mode = false;

// Parent iframe notification state flags
global.terrain_ready_notified = false;
global.observer_centered_notified = false;
global.observer_parent_notified = false;
// Terrain data population flag (set when texture has actual terrain data)
global.terrain_data_populated = false;
// Renderer initialization flag (set when renderer_init completes)
global.renderer_initialized = false;

// =============================================================================
// FOLLOW PLAYER SYSTEM (from civclient.js)
// =============================================================================

/**
 * Find player's capital city
 * @param {Object} player - Player object
 * @returns {Object|null} Capital city or null
 */
global.player_capital = function(player) {
  if (!player) return null;
  for (const city_id in global.cities) {
    const city = global.cities[city_id];
    if (city.owner === player.playerno && city.capital === global.CAPITAL_PRIMARY) {
      return city;
    }
  }
  return null;
};

/**
 * Mark that the user has interacted with the camera.
 * Suppresses auto-centering for OBSERVER_INTERACTION_COOLDOWN_MS.
 */
global.observer_mark_user_interaction = function() {
  global.observer_user_interaction_time = Date.now();
};

/**
 * Check if user interaction cooldown is active.
 * Returns true if auto-centering should be suppressed.
 */
global.observer_is_interaction_cooldown_active = function() {
  if (global.observer_user_interaction_time === 0) return false;
  return (Date.now() - global.observer_user_interaction_time) < global.OBSERVER_INTERACTION_COOLDOWN_MS;
};

/**
 * Set up event listeners on the map canvas to detect user camera interaction.
 */
global.init_observer_interaction_detection = function() {
  if (global.observer_interaction_listeners_attached) return;
  var canvas = document.getElementById('mapcanvas');
  if (!canvas) return;
  canvas.addEventListener('mousedown', global.observer_mark_user_interaction);
  canvas.addEventListener('wheel', global.observer_mark_user_interaction);
  canvas.addEventListener('touchstart', global.observer_mark_user_interaction, { passive: true });
  global.observer_interaction_listeners_attached = true;
};

/**
 * Initialize observer follow mode from URL parameter.
 * Parses ?follow=player_name and sets up auto-centering.
 */
global.init_observer_follow_mode = function() {
  if (!global.observing) return;

  // Parse follow parameter
  var follow_param = $.getUrlVar('follow');
  if (!follow_param) return;

  // Parse autocenter interval
  var autocenter_param = $.getUrlVar('autocenter');
  if (autocenter_param) {
    var parsed = parseInt(autocenter_param);
    if (!isNaN(parsed) && parsed > 0) {
      global.OBSERVER_AUTO_CENTER_MS = parsed;
    }
  } else {
    global.OBSERVER_AUTO_CENTER_MS = 5000; // Reset to default
  }

  // Find player by name, username, or playerno
  for (var player_id in global.players) {
    var player = global.players[player_id];
    if (player['name'] === follow_param ||
        player['username'] === follow_param ||
        player['playerno'].toString() === follow_param) {
      global.observer_follow_player = player['playerno'];
      console.log('[Observer] Following player:', player['name'], 'id:', global.observer_follow_player);
      break;
    }
  }

  if (global.observer_follow_player !== null) {
    // Start auto-centering interval
    global.observer_auto_center_interval = setInterval(
      global.observer_center_on_followed_player,
      global.OBSERVER_AUTO_CENTER_MS
    );
    // Initial center (with delay to ensure cities loaded)
    setTimeout(global.observer_center_on_followed_player, 1000);
  } else {
    console.warn('[Observer] Could not find player to follow:', follow_param);
  }
};

/**
 * Unwrap a coordinate relative to a reference point on a wrapping axis.
 * Mirrors production unwrap_coordinate() in civclient.js.
 */
global.unwrap_coordinate = function(val, ref, wraps, map_size) {
  if (!wraps || map_size <= 0) return val;
  var delta = val - ref;
  var half = Math.floor(map_size / 2);
  if (delta > half) return val - map_size;
  if (delta < -half) return val + map_size;
  return val;
};

/**
 * Compute wrap-aware spread and centroid from position array.
 * Mirrors the production compute_wrapped_spread_and_centroid() in civclient.js.
 */
global.compute_wrapped_spread_and_centroid = function(positions) {
  if (!positions || positions.length === 0) return null;

  var wrap_x = (typeof global.wrap_has_flag === 'function' && typeof global.WRAP_X !== 'undefined') ? global.wrap_has_flag(global.WRAP_X) : false;
  var wrap_y = (typeof global.wrap_has_flag === 'function' && typeof global.WRAP_Y !== 'undefined') ? global.wrap_has_flag(global.WRAP_Y) : false;
  var map_w = (global.map && global.map['xsize']) ? global.map['xsize'] : 0;
  var map_h = (global.map && global.map['ysize']) ? global.map['ysize'] : 0;

  var ref_x = positions[0].x;
  var ref_y = positions[0].y;

  var sum_x = 0, sum_y = 0, total_weight = 0;
  var min_x = Infinity, max_x = -Infinity;
  var min_y = Infinity, max_y = -Infinity;

  for (var i = 0; i < positions.length; i++) {
    var px = global.unwrap_coordinate(positions[i].x, ref_x, wrap_x, map_w);
    var py = global.unwrap_coordinate(positions[i].y, ref_y, wrap_y, map_h);
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

  if (wrap_x && map_w > 0) centroid_x = ((centroid_x % map_w) + map_w) % map_w;
  if (wrap_y && map_h > 0) centroid_y = ((centroid_y % map_h) + map_h) % map_h;

  var spread = Math.max(max_x - min_x, max_y - min_y);

  // Compute percentile-based effective radius (mirrors production code)
  var distances = [];
  for (var k = 0; k < positions.length; k++) {
    var px2 = global.unwrap_coordinate(positions[k].x, ref_x, wrap_x, map_w);
    var py2 = global.unwrap_coordinate(positions[k].y, ref_y, wrap_y, map_h);
    var w2 = positions[k].weight || 1;

    var dist = Math.max(Math.abs(px2 - centroid_raw_x), Math.abs(py2 - centroid_raw_y));
    for (var j = 0; j < w2; j++) {
      distances.push(dist);
    }
  }

  distances.sort(function(a, b) { return a - b; });
  var effective_radius = find_outlier_cutoff_radius(distances);

  return {
    centroid_x: centroid_x,
    centroid_y: centroid_y,
    spread: spread,
    effective_radius: effective_radius,
    total_weight: total_weight
  };
};

/**
 * Get city owner player ID (matches real city_owner_player_id from city.js)
 */
global.city_owner_player_id = function(city) {
  if (!city) return null;
  return city.owner;
};

/**
 * Calculate the centroid and spread of all territory (cities + units) owned by a player.
 * Cities are weighted by TERRITORY_CITY_WEIGHT to anchor centroid near empire core.
 * Uses compute_wrapped_spread_and_centroid() for wrap-aware calculations.
 */
global.get_player_territory_centroid_and_spread = function(player_id) {
  var positions = [];
  var city_count = 0, unit_count = 0;

  for (var city_id in global.cities) {
    var pcity = global.cities[city_id];
    if (global.city_owner_player_id(pcity) === player_id) {
      var ptile = global.city_tile(pcity);
      if (ptile) {
        positions.push({ x: ptile['x'], y: ptile['y'], weight: global.TERRITORY_CITY_WEIGHT });
        city_count++;
      }
    }
  }

  for (var unit_id in global.units) {
    var punit = global.units[unit_id];
    if (punit['owner'] === player_id) {
      var ptile = global.index_to_tile(punit['tile']);
      if (ptile) {
        positions.push({ x: ptile['x'], y: ptile['y'], weight: 1 });
        unit_count++;
      }
    }
  }

  var result = global.compute_wrapped_spread_and_centroid(positions);
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
};

/**
 * Find the effective radius from sorted distances using gap-based outlier detection.
 * Cuts only when both: a significant gap exists AND the outlier would cause
 * excessive zoom-out (>4x the core radius). Otherwise includes everything.
 */
global.find_outlier_cutoff_radius = function(distances) {
  if (distances.length === 0) return 0;
  if (distances.length <= 2) return distances[distances.length - 1];

  var min_core_index = Math.floor(distances.length * global.OUTLIER_MIN_CORE_RATIO);
  var best_gap = 0;
  var cutoff_index = distances.length - 1;

  for (var i = min_core_index; i < distances.length - 1; i++) {
    var gap = distances[i + 1] - distances[i];
    if (gap > best_gap) {
      best_gap = gap;
      cutoff_index = i;
    }
  }

  var core_radius = distances[cutoff_index];
  var max_distance = distances[distances.length - 1];

  if (core_radius > 0 &&
      best_gap > core_radius * global.OUTLIER_GAP_RATIO &&
      max_distance > core_radius * global.OUTLIER_ZOOM_IMPACT_RATIO) {
    return distances[cutoff_index];
  }

  return distances[distances.length - 1];
};

/**
 * Calculate camera height based on territory effective radius.
 * Linear formula: dy = BASE + radius * DY_PER_TILE, clamped to [MIN, MAX].
 */
global.calculate_zoom_for_territory_spread = function(effective_radius) {
  var dy = global.TERRITORY_BASE_DY + effective_radius * global.TERRITORY_DY_PER_TILE;
  return Math.floor(Math.max(global.TERRITORY_MIN_ZOOM_DY, Math.min(global.TERRITORY_MAX_ZOOM_DY, dy)));
};

/**
 * Center view on player's territory centroid with dynamic zoom.
 * Uses effective_radius (percentile-based) for zoom calculation.
 */
global.center_on_player_territory_with_zoom = function(player_id) {
  var territory_data = global.get_player_territory_centroid_and_spread(player_id);
  if (!territory_data) return null;

  var should_update_zoom = (
    global.observer_last_territory_radius === null ||
    Math.abs(territory_data.effective_radius - global.observer_last_territory_radius) >= global.TERRITORY_RADIUS_CHANGE_THRESHOLD
  );

  if (should_update_zoom) {
    var target_dy = global.calculate_zoom_for_territory_spread(territory_data.effective_radius);
    global.camera_dy = target_dy;
    global.observer_last_territory_radius = territory_data.effective_radius;
  }

  global.center_tile_mapcanvas(territory_data.tile);
  return territory_data;
};

/**
 * Calculate centroid and spread of all units owned by a player.
 * Mirrors production get_player_units_centroid_and_spread() in civclient.js.
 * Uses compute_wrapped_spread_and_centroid() for wrap-aware calculations.
 */
global.get_player_units_centroid_and_spread = function(player_id) {
  var positions = [];

  for (var unit_id in global.units) {
    var punit = global.units[unit_id];
    if (punit['owner'] === player_id) {
      var ptile = global.index_to_tile(punit['tile']);
      if (ptile) {
        positions.push({ x: ptile['x'], y: ptile['y'], weight: 1 });
      }
    }
  }

  var result = global.compute_wrapped_spread_and_centroid(positions);
  if (!result) return null;

  return {
    centroid: { x: result.centroid_x, y: result.centroid_y },
    spread: result.spread,
    count: positions.length,
    tile: { x: result.centroid_x, y: result.centroid_y }
  };
};

/**
 * Calculate camera height based on unit spread.
 * Mirrors production calculate_zoom_for_unit_spread() in civclient.js.
 */
global.calculate_zoom_for_unit_spread = function(spread) {
  var MIN_ZOOM_DY = 300, MAX_ZOOM_DY = 600, SPREAD_MIN = 2, SPREAD_MAX = 20;
  if (spread <= SPREAD_MIN) return MIN_ZOOM_DY;
  if (spread >= SPREAD_MAX) return MAX_ZOOM_DY;
  var zoom_factor = (spread - SPREAD_MIN) / (SPREAD_MAX - SPREAD_MIN);
  return Math.floor(MIN_ZOOM_DY + zoom_factor * (MAX_ZOOM_DY - MIN_ZOOM_DY));
};

/**
 * Center view on player's units with dynamic zoom.
 * Mirrors production center_on_player_units_with_zoom() in civclient.js.
 */
global.center_on_player_units_with_zoom = function(player_id) {
  var unit_data = global.get_player_units_centroid_and_spread(player_id);
  if (!unit_data) return false;

  var should_update_zoom = (
    global.observer_last_unit_spread === null ||
    Math.abs(unit_data.spread - global.observer_last_unit_spread) >= global.SPREAD_CHANGE_THRESHOLD
  );

  if (should_update_zoom) {
    var target_dy = global.calculate_zoom_for_unit_spread(unit_data.spread);
    global.camera_dy = target_dy;
    global.observer_last_unit_spread = unit_data.spread;
  }

  global.center_tile_mapcanvas(unit_data.tile);
  return true;
};

/**
 * Center view on followed player's territory with dynamic zoom.
 * On first center: simple capital/largest-city centering (no zoom manipulation).
 * After initial center: territory centroid with auto-zoom.
 * Fallback: any explored tile.
 * Mirrors production observer_center_on_followed_player() in civclient.js.
 */
global.observer_center_on_followed_player = function() {
  if (global.observer_follow_player === null) return;

  var player = global.players[global.observer_follow_player];
  if (!player || !player['is_alive']) {
    console.log('[Observer] Followed player not found or dead');
    return;
  }

  // On first center, use simple city centering without zoom manipulation.
  // Avoids aggressive camera_dy changes during initial load.
  if (!global.observer_centered_notified) {
    var target_city = global.player_capital(player);

    // Fallback: largest city by population
    if (!target_city) {
      var max_size = 0;
      for (var city_id in global.cities) {
        var pcity = global.cities[city_id];
        if (global.city_owner_player_id(pcity) === global.observer_follow_player) {
          if (pcity['size'] > max_size) {
            max_size = pcity['size'];
            target_city = pcity;
          }
        }
      }
    }

    if (target_city) {
      var ptile = global.city_tile(target_city);
      if (ptile) {
        global.center_tile_mapcanvas(ptile);
        global.observer_centered_notified = true;
        global.observer_parent_notified = true;
        global.notify_parent_iframe('observer_centered', {
          center_type: 'city',
          city_name: target_city['name'],
          location: { x: ptile['x'], y: ptile['y'] }
        });
        return;
      }
    }

    // No city or city_tile returned null — try explored tile WITHOUT zoom.
    var explored = global.find_first_explored_tile();
    if (explored) {
      global.center_tile_mapcanvas(explored);
      global.observer_centered_notified = true;
      global.observer_parent_notified = true;
      global.notify_parent_iframe('observer_centered', {
        center_type: 'explored_tile',
        location: { x: explored['x'], y: explored['y'] }
      });
      return;
    }

    // Nothing available yet — notify parent but keep retrying.
    if (!global.observer_parent_notified) {
      global.observer_parent_notified = true;
      console.warn('[Observer] Initial load: no city or explored tiles yet for player ' +
                   global.observer_follow_player + ' - will retry');
      global.notify_parent_iframe('observer_centered', {
        center_type: 'none',
        reason: 'no_visible_tiles',
        player_id: global.observer_follow_player
      });
    }
    return;
  }

  // Skip auto-center if user recently interacted with the camera
  if (global.observer_is_interaction_cooldown_active()) {
    return;
  }

  // After initial center: territory-aware centering with dynamic zoom
  var territory_data = global.center_on_player_territory_with_zoom(global.observer_follow_player);
  if (territory_data) {
    return;
  }

  // Fallback: any explored tile (prevents black screen)
  var explored_tile = global.find_first_explored_tile();
  if (explored_tile) {
    global.center_tile_mapcanvas(explored_tile);
    if (!global.observer_centered_notified) {
      global.observer_centered_notified = true;
      global.observer_parent_notified = true;
      global.notify_parent_iframe('observer_centered', {
        center_type: 'explored_tile',
        location: { x: explored_tile['x'], y: explored_tile['y'] }
      });
    }
    return;
  }

  // No territory or explored tiles - notify parent once
  if (!global.observer_parent_notified) {
    global.observer_parent_notified = true;
    console.warn('[Observer] No territory or explored tiles found for player ' + global.observer_follow_player + ' - will retry');
    global.notify_parent_iframe('observer_centered', {
      center_type: 'none',
      reason: 'no_visible_tiles',
      player_id: global.observer_follow_player
    });
  }
};

/**
 * Clean up observer follow mode - clear interval and reset state.
 */
global.cleanup_observer_follow_mode = function() {
  if (global.observer_auto_center_interval) {
    clearInterval(global.observer_auto_center_interval);
    global.observer_auto_center_interval = null;
  }
  if (global.observer_initial_center_interval) {
    clearInterval(global.observer_initial_center_interval);
    global.observer_initial_center_interval = null;
  }
  if (global.observer_player_search_interval) {
    clearInterval(global.observer_player_search_interval);
    global.observer_player_search_interval = null;
  }
  global.observer_follow_player = null;
  global.observer_last_unit_spread = null;
  global.observer_last_territory_radius = null;
  global.observer_last_global_spread = null;
  global.observer_user_interaction_time = 0;
};

/**
 * Get centroid and spread of all non-barbarian alive players' units.
 * Mirrors production get_all_players_units_centroid_and_spread().
 */
global.get_all_players_units_centroid_and_spread = function() {
  var positions = [];
  var players_with_units = {};

  for (var unit_id in global.units) {
    var punit = global.units[unit_id];
    var owner_id = punit['owner'];
    if (global.is_barbarian_player && global.is_barbarian_player(owner_id)) continue;
    var player = global.players[owner_id];
    if (!player || !player['is_alive']) continue;
    var ptile = global.index_to_tile(punit['tile']);
    if (ptile) {
      positions.push({ x: ptile['x'], y: ptile['y'], weight: 1 });
      players_with_units[owner_id] = true;
    }
  }

  var result = global.compute_wrapped_spread_and_centroid(positions);
  if (!result) return null;

  return {
    centroid: { x: result.centroid_x, y: result.centroid_y },
    spread: result.spread,
    count: positions.length,
    player_count: Object.keys(players_with_units).length,
    tile: { x: result.centroid_x, y: result.centroid_y }
  };
};

/**
 * Center on all players' units with dynamic zoom.
 * Mirrors production center_on_all_players_with_zoom().
 */
global.center_on_all_players_with_zoom = function() {
  var unit_data = global.get_all_players_units_centroid_and_spread();
  if (!unit_data) return null;
  global.center_tile_mapcanvas(unit_data.tile);
  return unit_data;
};

/**
 * Global observer view centering.
 * Mirrors production observer_center_global_view().
 */
global.observer_center_global_view = function() {
  if (global.observer_centered_notified && global.observer_is_interaction_cooldown_active()) {
    return;
  }

  var unit_data = global.center_on_all_players_with_zoom();
  if (unit_data) {
    if (!global.observer_centered_notified) {
      global.observer_centered_notified = true;
      global.observer_parent_notified = true;
      global.notify_parent_iframe('observer_centered', {
        center_type: 'global_units',
        player_count: unit_data.player_count,
        unit_count: unit_data.count,
        spread: unit_data.spread
      });
    }
    return;
  }

  var explored_tile = global.find_first_explored_tile();
  if (explored_tile) {
    global.center_tile_mapcanvas(explored_tile);
    if (!global.observer_centered_notified) {
      global.observer_centered_notified = true;
      global.observer_parent_notified = true;
      global.notify_parent_iframe('observer_centered', {
        center_type: 'fallback_explored',
        reason: 'no_player_units',
        location: { x: explored_tile['x'], y: explored_tile['y'] }
      });
    }
    return;
  }

  if (!global.observer_parent_notified) {
    global.observer_parent_notified = true;
    global.notify_parent_iframe('observer_centered', {
      center_type: 'none',
      reason: 'no_visible_content'
    });
  }
};

// Barbarian player check (defaults to false for tests)
global.is_barbarian_player = jest.fn(() => false);

// =============================================================================
// EMBED MODE SYSTEM (from civclient.js)
// =============================================================================

// Audio globals
global.audio_enabled = true;
global.sounds_enabled = true;
global.music_enabled = true;

// Keyboard input global
global.keyboard_input_enabled = true;

// List of UI elements to hide in embed mode
var EMBED_MODE_HIDDEN_ELEMENTS = [
  'game_menu_panel',
  'chat_panel',
  'turn_done_button',
  'unit_orders_bar',
  'minimap_panel',
  'info_panel',
  'civ_status_bar',
];

/**
 * Initialize embed mode from URL parameter.
 * Parses ?embed=1 or ?embed=true and sets embed_mode flag.
 */
global.init_embed_mode = function() {
  var embed_param = $.getUrlVar('embed');
  if (embed_param === '1' || embed_param === 'true') {
    global.embed_mode = true;
  } else {
    global.embed_mode = false;
  }
};

/**
 * Apply embed mode settings if embed_mode is true.
 * Disables controls, audio, keyboard input, and hides UI elements.
 */
global.apply_embed_mode_settings = function() {
  if (!global.embed_mode) {
    return;
  }

  // Add CSS class to body
  document.body.classList.add('embed-mode');

  // Disable audio
  global.audio_enabled = false;
  global.sounds_enabled = false;
  global.music_enabled = false;

  // Disable keyboard input
  global.keyboard_input_enabled = false;

  // Disable OrbitControls (if present)
  if (global.controls) {
    global.controls.enabled = false;
    global.controls.enablePan = false;
    global.controls.enableZoom = false;
    global.controls.enableRotate = false;
  }

  // Hide UI elements
  EMBED_MODE_HIDDEN_ELEMENTS.forEach(function(elementId) {
    var el = document.getElementById(elementId);
    if (el) {
      el.style.display = 'none';
    }
  });
};

/**
 * Check if embed mode is currently active.
 * @returns {boolean} True if embed mode is enabled
 */
global.is_embed_mode = function() {
  return global.embed_mode;
};

// =============================================================================
// AUTOJOIN MODE SYSTEM (from civclient.js / pregame.js)
// =============================================================================

// Autojoin state globals
global.autojoin_active = false;
global.username = '';

/**
 * Check if autojoin mode should be activated from URL parameters.
 * @returns {boolean} True if autojoin=1 or autojoin=true in URL
 */
global.should_autojoin = function() {
  var autojoin_param = $.getUrlVar('autojoin');
  return autojoin_param === '1' || autojoin_param === 'true';
};

/**
 * Generate a random observer username in format: observer_XXXXX
 * @returns {string} Generated username
 */
global.generate_observer_name = function() {
  var chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
  var suffix = '';
  for (var i = 0; i < 8; i++) {  // Match production: 8 chars for better uniqueness
    suffix += chars.charAt(Math.floor(Math.random() * chars.length));
  }
  return 'observer_' + suffix;
};

/**
 * Validate a username for autojoin.
 * Rules: 3-31 chars, alphanumeric + underscore, starts with letter or underscore
 * @param {string} name - Username to validate
 * @returns {boolean} True if valid
 */
global.validate_autojoin_username = function(name) {
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
};

/**
 * Get the username for autojoin mode.
 * Uses URL param if provided and valid, otherwise generates a random name.
 * @returns {string} Username for autojoin
 */
global.get_autojoin_username = function() {
  var name_param = $.getUrlVar('name');

  if (name_param) {
    // Trim whitespace
    name_param = name_param.trim();

    if (global.validate_autojoin_username(name_param)) {
      return name_param;
    }
  }

  // Generate random name
  return global.generate_observer_name();
};

/**
 * Initialize autojoin mode - skip username dialog and connect directly.
 */
global.init_autojoin_mode = function() {
  if (!global.should_autojoin()) {
    return;
  }

  global.autojoin_active = true;
  global.username = global.get_autojoin_username();

  // Check if provided name is invalid and regenerate
  var name_param = $.getUrlVar('name');
  if (name_param && !global.validate_autojoin_username(name_param.trim())) {
    global.username = global.generate_observer_name();
  }

  // Initialize network connection
  global.network_init();
};

// =============================================================================
// OBSERVER PLAYER ATTACHMENT SYSTEM (from civclient.js / packhand.js)
// =============================================================================

// Observer player attachment state
global.observe_player = null;

/**
 * Get the observe_player URL parameter, handling URL encoding.
 * @returns {string|null} Player name to observe, or null if not specified
 */
global.get_observe_player_param = function() {
  var param = $.getUrlVar('observe_player');

  if (!param || param === '') {
    return null;
  }

  // Trim whitespace
  return param.trim();
};

// Player name validation regex - allows letters, numbers, underscore, asterisk (for AI*1), hyphen
global.SAFE_PLAYER_NAME_REGEX = /^[a-zA-Z0-9_*-]+$/;

/**
 * Send /observe command to attach to a specific player or observe globally.
 * SECURITY: Validates player_name to prevent command injection attacks.
 * @param {string|null} player_name - Player name to observe, or null for global
 */
global.request_observe_player = function(player_name) {
  // SECURITY: Validate player name contains only safe characters
  if (player_name && !global.SAFE_PLAYER_NAME_REGEX.test(player_name)) {
    console.error('[Observer] Invalid player name contains unsafe characters:', player_name);
    return;
  }

  global.observe_player = player_name;

  if (typeof global.send_message === 'function') {
    if (player_name) {
      global.send_message('/observe ' + player_name);
    } else {
      global.send_message('/observe ');
    }
  }
};

/**
 * Initialize observe player mode from URL parameter.
 * Does NOT send command - that happens after login via execute_observe_player_attachment.
 */
global.init_observe_player_mode = function() {
  var player_param = global.get_observe_player_param();

  if (player_param) {
    global.observe_player = player_param;
  }
};

/**
 * Execute observer attachment after successful login.
 * Sends /observe command if observe_player was set during initialization.
 * SECURITY: Validates player name format to prevent command injection.
 */
global.execute_observe_player_attachment = function() {
  if (!global.observe_player || global.observe_player === '') {
    return;
  }

  // SECURITY: Validate player name format to prevent command injection
  if (!global.SAFE_PLAYER_NAME_REGEX.test(global.observe_player)) {
    console.error('[Observer] Invalid player name contains unsafe characters:', global.observe_player);
    return;
  }

  if (typeof global.send_message === 'function') {
    global.send_message('/observe ' + global.observe_player);
  }
};

/**
 * Check if observer is attached to a specific player (vs global observer).
 * @returns {boolean} True if attached to a player
 */
global.is_attached_observer = function() {
  return global.observe_player !== null && global.observe_player !== '';
};

/**
 * Request to observe the game. Supports both global observation and
 * player-specific FOW attachment via the observe_player global variable.
 * Sends /observe command to server and sets up retry timeout.
 *
 * @param player_to_attach - Optional player name to attach to. If not provided,
 *                          falls back to the observe_player global (from URL).
 *                          Pass null explicitly for global observation.
 */
global.request_observe_game = function(player_to_attach) {
  // Use explicit parameter if provided, otherwise check URL-param global
  var target_player = player_to_attach;
  if (target_player === undefined) {
    target_player = global.observe_player;  // From URL param via init_observe_player_mode()
  }

  if (target_player && target_player !== '') {
    // Player-specific FOW observation
    // SECURITY: Validate player name to prevent command injection
    if (!global.SAFE_PLAYER_NAME_REGEX.test(target_player)) {
      console.error('[Observer] Invalid player name contains unsafe characters:', target_player);
      global.send_message("/observe ");
      global.setup_observer_timeout_with_retry('global');
      return;
    }
    global.send_message('/observe ' + target_player);
    global.setup_observer_timeout_with_retry(target_player);
  } else {
    // Global observer
    global.send_message("/observe ");
    global.setup_observer_timeout_with_retry('global');
  }
};

/**
 * Setup observer timeout with retry logic (mock for tests)
 */
global.setup_observer_timeout_with_retry = jest.fn();

// Player/city/unit globals
global.players = {};
global.cities = {};
global.units = {};
global.client = {
  conn: {
    playing: null,
    observer: false,
  },
};

// Map wrapping globals (defaults to non-wrapping for tests)
global.WRAP_X = 1;
global.WRAP_Y = 2;
global.map = { xsize: 0, ysize: 0, topology_id: 0, wrap_id: 0 };
global.wrap_has_flag = function(flag) {
  return ((global.map['wrap_id'] & flag) !== 0);
};

// Unit spread tracking for observer mode
global.observer_last_unit_spread = null;
global.SPREAD_CHANGE_THRESHOLD = 5;

// Global view spread tracking
global.observer_last_global_spread = null;

// Territory spread tracking for follow mode with cities
global.observer_last_territory_radius = null;
global.TERRITORY_RADIUS_CHANGE_THRESHOLD = 2;
global.TERRITORY_CITY_WEIGHT = 3;
global.TERRITORY_BASE_DY = 250;
global.TERRITORY_DY_PER_TILE = 35;
global.TERRITORY_MIN_ZOOM_DY = 200;
global.TERRITORY_MAX_ZOOM_DY = 1200;
global.OUTLIER_GAP_RATIO = 0.8;
global.OUTLIER_MIN_CORE_RATIO = 0.6;
global.OUTLIER_ZOOM_IMPACT_RATIO = 4.0;

// Constants
global.CAPITAL_PRIMARY = 1;
global.CAPITAL_NOT = 0;

// Game state functions
global.send_message = jest.fn();
global.center_tile_mapcanvas = jest.fn();
global.city_tile = jest.fn((city) => city ? { x: city.id || 0, y: city.id || 0 } : null);
global.network_init = jest.fn();
global.get_invalid_username_reason = jest.fn(() => null);

// Tile index to tile object conversion for unit positioning
// By default, creates a tile at (index % 100, floor(index / 100))
global.index_to_tile = jest.fn((index) => ({
  x: index % 100,
  y: Math.floor(index / 100)
}));

// Logging function mock
global.freelog = jest.fn();
global.LOG_DEBUG = 0;

// Parent iframe notification mock
global.notify_parent_iframe = jest.fn();
global.notify_parent_error = jest.fn();

// Explored tile fallback (returns null by default, tests can override)
global.find_first_explored_tile = jest.fn(() => null);

// =============================================================================
// TEST UTILITIES
// =============================================================================

/**
 * Set URL search params for testing URL parameter parsing
 * @param {Object} params - Key-value pairs to set as URL params
 */
global.setUrlParams = (params) => {
  const searchParams = new URLSearchParams(params);
  global.window.location.search = '?' + searchParams.toString();
  global.window.location.href = `http://localhost:8080/webclient/?${searchParams.toString()}`;

  // Update jQuery mock to return these params
  jQueryMock.getUrlVars.mockReturnValue(params);
  jQueryMock.getUrlVar.mockImplementation((name) => params[name]);
};

/**
 * Reset all mocks to initial state
 */
global.resetAllMocks = () => {
  jest.clearAllMocks();

  // Reset camera globals
  global.camera_dx = 50;
  global.camera_dy = 410;
  global.camera_dz = 242;
  global.camera_current_x = 0;
  global.camera_current_y = 0;
  global.camera_current_z = 0;
  global.camera = null;
  global.controls = null;
  global.spotlight = {
    position: { set: jest.fn() },
    target: { position: { set: jest.fn() } },
    shadow: {
      camera: {
        position: { copy: jest.fn() },
        lookAt: jest.fn(),
      },
    },
  };

  // Reset observer globals
  global.observing = false;
  global.observer_follow_player = null;
  global.observer_last_unit_spread = null;
  global.observer_last_territory_radius = null;
  global.observer_last_global_spread = null;
  if (global.observer_auto_center_interval) {
    clearInterval(global.observer_auto_center_interval);
  }
  global.observer_auto_center_interval = null;
  if (global.observer_initial_center_interval) {
    clearInterval(global.observer_initial_center_interval);
  }
  global.observer_initial_center_interval = null;
  if (global.observer_player_search_interval) {
    clearInterval(global.observer_player_search_interval);
  }
  global.observer_player_search_interval = null;
  global.OBSERVER_AUTO_CENTER_MS = 5000;
  global.observer_user_interaction_time = 0;
  global.observer_interaction_listeners_attached = false;
  global.embed_mode = false;
  global.players = {};
  global.cities = {};
  global.units = {};
  global.client = { conn: { playing: null, observer: false } };

  // Reset parent iframe notification state flags
  global.terrain_ready_notified = false;
  global.observer_centered_notified = false;
  global.observer_parent_notified = false;
  global.terrain_data_populated = false;
  global.renderer_initialized = false;

  // Reset embed mode globals
  global.audio_enabled = true;
  global.sounds_enabled = true;
  global.music_enabled = true;
  global.keyboard_input_enabled = true;

  // Reset autojoin globals
  global.autojoin_active = false;
  global.username = '';

  // Reset observe player globals
  global.observe_player = null;

  // Reset URL
  global.window.location.search = '';
  global.window.location.href = 'http://localhost:8080/webclient/';
  jQueryMock.getUrlVars.mockReturnValue({});
  jQueryMock.getUrlVar.mockReturnValue(undefined);
};

/**
 * Create mock player data
 * @param {Object} overrides - Properties to override
 * @returns {Object} Mock player object
 */
global.createMockPlayer = (overrides = {}) => ({
  playerno: 0,
  name: 'TestPlayer',
  username: 'testuser',
  is_alive: true,
  nation: 0,
  team: 0,
  ...overrides,
});

/**
 * Create mock city data
 * @param {Object} overrides - Properties to override
 * @returns {Object} Mock city object
 */
global.createMockCity = (overrides = {}) => ({
  id: 100,
  owner: 0,
  name: 'TestCity',
  size: 1,
  capital: 0,
  tile: 0,
  ...overrides,
});

/**
 * Create mock unit data
 * @param {Object} overrides - Properties to override
 * @returns {Object} Mock unit object
 */
global.createMockUnit = (overrides = {}) => ({
  id: 1,
  owner: 0,
  tile: 100,  // Will resolve to {x: 0, y: 1} via index_to_tile
  type: 0,
  ...overrides,
});

// =============================================================================
// RESET BEFORE EACH TEST
// =============================================================================

beforeEach(() => {
  global.resetAllMocks();
});
