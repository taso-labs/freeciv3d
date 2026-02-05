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
global.OBSERVER_AUTO_CENTER_MS = 5000;
global.embed_mode = false;

// Parent iframe notification state flags
global.terrain_ready_notified = false;
global.observer_centered_notified = false;
global.observer_parent_notified = false;

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
 * Center view on followed player's main population center.
 * Priority: 1) Capital city, 2) Largest city by size, 3) Any city
 */
global.observer_center_on_followed_player = function() {
  if (global.observer_follow_player === null) return;

  var player = global.players[global.observer_follow_player];
  if (!player || !player['is_alive']) {
    console.log('[Observer] Followed player not found or dead');
    return;
  }

  var target_city = null;

  // Priority 1: Capital city
  target_city = global.player_capital(player);

  // Priority 2: Largest city by population size
  if (!target_city) {
    var max_size = 0;
    for (var city_id in global.cities) {
      var pcity = global.cities[city_id];
      if (pcity.owner === global.observer_follow_player) {
        if (pcity['size'] > max_size) {
          max_size = pcity['size'];
          target_city = pcity;
        }
      }
    }
  }

  // Center on target
  if (target_city) {
    var ptile = global.city_tile(target_city);
    if (ptile) {
      global.center_tile_mapcanvas(ptile);
      console.log('[Observer] Centered on', target_city['name'], 'size:', target_city['size']);
    }
  } else {
    console.log('[Observer] No cities found for player', global.observer_follow_player);
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
  global.observer_follow_player = null;
};

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

// Unit spread tracking for observer mode
global.observer_last_unit_spread = null;
global.SPREAD_CHANGE_THRESHOLD = 5;

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
  if (global.observer_auto_center_interval) {
    clearInterval(global.observer_auto_center_interval);
  }
  global.observer_auto_center_interval = null;
  global.OBSERVER_AUTO_CENTER_MS = 5000;
  global.embed_mode = false;
  global.players = {};
  global.cities = {};
  global.units = {};
  global.client = { conn: { playing: null, observer: false } };

  // Reset parent iframe notification state flags
  global.terrain_ready_notified = false;
  global.observer_centered_notified = false;
  global.observer_parent_notified = false;

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
