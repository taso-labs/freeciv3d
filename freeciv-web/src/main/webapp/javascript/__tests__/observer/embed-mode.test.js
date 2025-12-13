/**
 * Embed Mode Test Suite
 *
 * TDD RED PHASE: These tests are written BEFORE the implementation.
 * They should FAIL initially until embed mode is implemented.
 *
 * Tests cover:
 * - embed_mode flag detection from URL parameter
 * - Audio/sound disabling
 * - OrbitControls disabling (no pan/zoom)
 * - Keyboard input disabling
 * - UI element hiding
 * - CSS class application
 */

describe('Embed Mode', () => {
  beforeEach(() => {
    // Reset all mocks
    resetAllMocks();

    // Setup document body for CSS class tests
    document.body.className = '';
  });

  // ===========================================================================
  // State Management Tests
  // ===========================================================================

  describe('embed_mode state', () => {
    test('should be defined as a global variable', () => {
      expect(typeof embed_mode).not.toBe('undefined');
    });

    test('should initialize as false', () => {
      expect(embed_mode).toBe(false);
    });
  });

  // ===========================================================================
  // init_embed_mode() Tests
  // ===========================================================================

  describe('init_embed_mode()', () => {
    test('should be defined as a global function', () => {
      expect(typeof init_embed_mode).toBe('function');
    });

    test('should set embed_mode to true when URL has embed=1', () => {
      setUrlParams({ embed: '1' });

      init_embed_mode();

      expect(embed_mode).toBe(true);
    });

    test('should set embed_mode to true when URL has embed=true', () => {
      setUrlParams({ embed: 'true' });

      init_embed_mode();

      expect(embed_mode).toBe(true);
    });

    test('should keep embed_mode false when URL has no embed param', () => {
      setUrlParams({});

      init_embed_mode();

      expect(embed_mode).toBe(false);
    });

    test('should keep embed_mode false when URL has embed=0', () => {
      setUrlParams({ embed: '0' });

      init_embed_mode();

      expect(embed_mode).toBe(false);
    });

    test('should keep embed_mode false when URL has embed=false', () => {
      setUrlParams({ embed: 'false' });

      init_embed_mode();

      expect(embed_mode).toBe(false);
    });

    test('should not throw when called multiple times', () => {
      setUrlParams({ embed: '1' });

      expect(() => {
        init_embed_mode();
        init_embed_mode();
      }).not.toThrow();
    });
  });

  // ===========================================================================
  // apply_embed_mode_settings() Tests
  // ===========================================================================

  describe('apply_embed_mode_settings()', () => {
    test('should be defined as a global function', () => {
      expect(typeof apply_embed_mode_settings).toBe('function');
    });

    test('should not apply settings when embed_mode is false', () => {
      global.embed_mode = false;

      apply_embed_mode_settings();

      expect(document.body.classList.contains('embed-mode')).toBe(false);
    });

    test('should add embed-mode CSS class to body when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(document.body.classList.contains('embed-mode')).toBe(true);
    });

    test('should not throw if called when embed_mode is false', () => {
      global.embed_mode = false;

      expect(() => apply_embed_mode_settings()).not.toThrow();
    });
  });

  // ===========================================================================
  // Audio Disabling Tests
  // ===========================================================================

  describe('audio disabling in embed mode', () => {
    beforeEach(() => {
      // Mock audio-related globals
      global.audio_enabled = true;
      global.sounds_enabled = true;
      global.music_enabled = true;
    });

    test('should disable audio_enabled when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(global.audio_enabled).toBe(false);
    });

    test('should disable sounds_enabled when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(global.sounds_enabled).toBe(false);
    });

    test('should disable music_enabled when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(global.music_enabled).toBe(false);
    });

    test('should not disable audio when embed_mode is false', () => {
      global.embed_mode = false;
      global.audio_enabled = true;
      global.sounds_enabled = true;
      global.music_enabled = true;

      apply_embed_mode_settings();

      expect(global.audio_enabled).toBe(true);
      expect(global.sounds_enabled).toBe(true);
      expect(global.music_enabled).toBe(true);
    });
  });

  // ===========================================================================
  // OrbitControls Disabling Tests
  // ===========================================================================

  describe('OrbitControls disabling in embed mode', () => {
    beforeEach(() => {
      // Mock OrbitControls
      global.controls = {
        enabled: true,
        enablePan: true,
        enableZoom: true,
        enableRotate: true,
      };
    });

    test('should disable controls.enabled when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(global.controls.enabled).toBe(false);
    });

    test('should disable controls.enablePan when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(global.controls.enablePan).toBe(false);
    });

    test('should disable controls.enableZoom when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(global.controls.enableZoom).toBe(false);
    });

    test('should disable controls.enableRotate when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(global.controls.enableRotate).toBe(false);
    });

    test('should not disable controls when embed_mode is false', () => {
      global.embed_mode = false;

      apply_embed_mode_settings();

      expect(global.controls.enabled).toBe(true);
      expect(global.controls.enablePan).toBe(true);
      expect(global.controls.enableZoom).toBe(true);
      expect(global.controls.enableRotate).toBe(true);
    });

    test('should handle null controls gracefully', () => {
      global.embed_mode = true;
      global.controls = null;

      expect(() => apply_embed_mode_settings()).not.toThrow();
    });
  });

  // ===========================================================================
  // Keyboard Input Disabling Tests
  // ===========================================================================

  describe('keyboard input disabling in embed mode', () => {
    beforeEach(() => {
      global.keyboard_input_enabled = true;
    });

    test('should disable keyboard_input_enabled when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      expect(global.keyboard_input_enabled).toBe(false);
    });

    test('should not disable keyboard input when embed_mode is false', () => {
      global.embed_mode = false;
      global.keyboard_input_enabled = true;

      apply_embed_mode_settings();

      expect(global.keyboard_input_enabled).toBe(true);
    });
  });

  // ===========================================================================
  // UI Element Hiding Tests
  // ===========================================================================

  describe('UI element hiding in embed mode', () => {
    beforeEach(() => {
      // Create mock UI elements in DOM
      const elementsToHide = [
        'game_menu_panel',
        'chat_panel',
        'turn_done_button',
        'unit_orders_bar',
        'minimap_panel',
        'info_panel',
        'civ_status_bar',
      ];

      elementsToHide.forEach(id => {
        const el = document.createElement('div');
        el.id = id;
        el.style.display = 'block';
        document.body.appendChild(el);
      });
    });

    afterEach(() => {
      // Clean up DOM
      const elementsToClean = [
        'game_menu_panel',
        'chat_panel',
        'turn_done_button',
        'unit_orders_bar',
        'minimap_panel',
        'info_panel',
        'civ_status_bar',
      ];

      elementsToClean.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.remove();
      });
    });

    test('should hide game_menu_panel when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      const el = document.getElementById('game_menu_panel');
      expect(el.style.display).toBe('none');
    });

    test('should hide chat_panel when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      const el = document.getElementById('chat_panel');
      expect(el.style.display).toBe('none');
    });

    test('should hide turn_done_button when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      const el = document.getElementById('turn_done_button');
      expect(el.style.display).toBe('none');
    });

    test('should hide unit_orders_bar when embed_mode is true', () => {
      global.embed_mode = true;

      apply_embed_mode_settings();

      const el = document.getElementById('unit_orders_bar');
      expect(el.style.display).toBe('none');
    });

    test('should not hide UI elements when embed_mode is false', () => {
      global.embed_mode = false;

      apply_embed_mode_settings();

      const el = document.getElementById('game_menu_panel');
      expect(el.style.display).toBe('block');
    });

    test('should handle missing UI elements gracefully', () => {
      global.embed_mode = true;

      // Remove an element
      const el = document.getElementById('game_menu_panel');
      el.remove();

      // Should not throw
      expect(() => apply_embed_mode_settings()).not.toThrow();
    });
  });

  // ===========================================================================
  // Integration Tests
  // ===========================================================================

  describe('embed mode integration', () => {
    beforeEach(() => {
      // Set up complete environment
      global.audio_enabled = true;
      global.sounds_enabled = true;
      global.music_enabled = true;
      global.keyboard_input_enabled = true;
      global.controls = {
        enabled: true,
        enablePan: true,
        enableZoom: true,
        enableRotate: true,
      };
    });

    test('should fully initialize embed mode from URL param', () => {
      setUrlParams({ embed: '1' });

      init_embed_mode();
      apply_embed_mode_settings();

      expect(embed_mode).toBe(true);
      expect(document.body.classList.contains('embed-mode')).toBe(true);
      expect(global.audio_enabled).toBe(false);
      expect(global.controls.enabled).toBe(false);
      expect(global.keyboard_input_enabled).toBe(false);
    });

    test('should not modify anything when embed param is missing', () => {
      setUrlParams({});

      init_embed_mode();
      apply_embed_mode_settings();

      expect(embed_mode).toBe(false);
      expect(document.body.classList.contains('embed-mode')).toBe(false);
      expect(global.audio_enabled).toBe(true);
      expect(global.controls.enabled).toBe(true);
      expect(global.keyboard_input_enabled).toBe(true);
    });

    test('should work with other URL params like camera and follow', () => {
      setUrlParams({ embed: '1', camera: 'strategic', follow: 'Player1' });

      init_embed_mode();

      expect(embed_mode).toBe(true);
    });
  });

  // ===========================================================================
  // is_embed_mode() Helper Tests
  // ===========================================================================

  describe('is_embed_mode()', () => {
    test('should be defined as a global function', () => {
      expect(typeof is_embed_mode).toBe('function');
    });

    test('should return true when embed_mode is true', () => {
      global.embed_mode = true;

      expect(is_embed_mode()).toBe(true);
    });

    test('should return false when embed_mode is false', () => {
      global.embed_mode = false;

      expect(is_embed_mode()).toBe(false);
    });
  });
});
