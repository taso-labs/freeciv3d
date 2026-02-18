/**
 * Follow Player System Test Suite
 *
 * Tests cover:
 * - observer_follow_player state management
 * - init_observer_follow_mode() initialization from URL
 * - observer_center_on_followed_player() territory-aware centering logic
 * - cleanup_observer_follow_mode() cleanup
 * - URL parameter parsing for follow and autocenter
 * - Territory-based auto-zoom behavior
 */

describe('Follow Player System', () => {
  beforeEach(() => {
    // Reset all mocks
    resetAllMocks();

    // Setup observer mode
    global.observing = true;

    // Setup mock players
    global.players = {
      0: createMockPlayer({ playerno: 0, name: 'Player1', username: 'user1', is_alive: true }),
      1: createMockPlayer({ playerno: 1, name: 'AI*1', username: 'AI*1', is_alive: true }),
      2: createMockPlayer({ playerno: 2, name: 'AI*2', username: 'AI*2', is_alive: true }),
    };

    // Setup mock cities with distinct positions via city_tile mock
    global.cities = {
      100: createMockCity({ id: 100, owner: 0, name: 'PlayerCapital', size: 5, capital: CAPITAL_PRIMARY }),
      101: createMockCity({ id: 101, owner: 0, name: 'PlayerCity2', size: 3, capital: CAPITAL_NOT }),
      102: createMockCity({ id: 102, owner: 1, name: 'AI1Capital', size: 4, capital: CAPITAL_PRIMARY }),
      103: createMockCity({ id: 103, owner: 1, name: 'AI1City2', size: 6, capital: CAPITAL_NOT }),
      104: createMockCity({ id: 104, owner: 2, name: 'AI2Capital', size: 3, capital: CAPITAL_PRIMARY }),
    };

    // Setup empty units by default
    global.units = {};

    // Clear any existing interval
    if (global.observer_auto_center_interval) {
      clearInterval(global.observer_auto_center_interval);
      global.observer_auto_center_interval = null;
    }
  });

  afterEach(() => {
    // Cleanup intervals
    if (global.observer_auto_center_interval) {
      clearInterval(global.observer_auto_center_interval);
      global.observer_auto_center_interval = null;
    }
    jest.useRealTimers();
  });

  // ===========================================================================
  // State Management Tests
  // ===========================================================================

  describe('observer_follow_player state', () => {
    test('should be defined as a global variable', () => {
      expect(typeof observer_follow_player).not.toBe('undefined');
    });

    test('should initialize as null', () => {
      expect(observer_follow_player).toBeNull();
    });

    test('observer_auto_center_interval should be defined', () => {
      expect(typeof observer_auto_center_interval).not.toBe('undefined');
    });

    test('OBSERVER_AUTO_CENTER_MS should default to 5000', () => {
      expect(OBSERVER_AUTO_CENTER_MS).toBe(5000);
    });

    test('observer_last_territory_radius should be defined and null', () => {
      expect(typeof observer_last_territory_radius).not.toBe('undefined');
      expect(observer_last_territory_radius).toBeNull();
    });

    test('observer_last_global_spread should be defined and null', () => {
      expect(typeof global.observer_last_global_spread).not.toBe('undefined');
      expect(global.observer_last_global_spread).toBeNull();
    });
  });

  // ===========================================================================
  // init_observer_follow_mode() Tests
  // ===========================================================================

  describe('init_observer_follow_mode()', () => {
    test('should be defined as a global function', () => {
      expect(typeof init_observer_follow_mode).toBe('function');
    });

    test('should not initialize if not observing', () => {
      global.observing = false;
      setUrlParams({ follow: 'Player1' });

      init_observer_follow_mode();

      expect(observer_follow_player).toBeNull();
    });

    test('should find player by exact name match', () => {
      setUrlParams({ follow: 'Player1' });

      init_observer_follow_mode();

      expect(observer_follow_player).toBe(0);
    });

    test('should find player by AI name (AI*1)', () => {
      setUrlParams({ follow: 'AI*1' });

      init_observer_follow_mode();

      expect(observer_follow_player).toBe(1);
    });

    test('should find player by AI name (AI*2)', () => {
      setUrlParams({ follow: 'AI*2' });

      init_observer_follow_mode();

      expect(observer_follow_player).toBe(2);
    });

    test('should find player by playerno as string', () => {
      setUrlParams({ follow: '0' });

      init_observer_follow_mode();

      expect(observer_follow_player).toBe(0);
    });

    test('should find player by username', () => {
      setUrlParams({ follow: 'user1' });

      init_observer_follow_mode();

      expect(observer_follow_player).toBe(0);
    });

    test('should handle non-existent player gracefully', () => {
      setUrlParams({ follow: 'NonExistentPlayer' });

      init_observer_follow_mode();

      expect(observer_follow_player).toBeNull();
    });

    test('should handle missing follow parameter gracefully', () => {
      setUrlParams({});

      expect(() => init_observer_follow_mode()).not.toThrow();
      expect(observer_follow_player).toBeNull();
    });

    test('should start auto-center interval when player found', () => {
      jest.useFakeTimers();
      setUrlParams({ follow: 'Player1' });

      init_observer_follow_mode();

      expect(observer_auto_center_interval).not.toBeNull();
      jest.useRealTimers();
    });

    test('should not start interval when player not found', () => {
      jest.useFakeTimers();
      setUrlParams({ follow: 'NonExistent' });

      init_observer_follow_mode();

      expect(observer_auto_center_interval).toBeNull();
      jest.useRealTimers();
    });

    test('should parse custom autocenter interval from URL', () => {
      setUrlParams({ follow: 'Player1', autocenter: '3000' });

      init_observer_follow_mode();

      expect(OBSERVER_AUTO_CENTER_MS).toBe(3000);
    });

    test('should use default 5000ms when autocenter param is missing', () => {
      // Reset to non-default value first
      global.OBSERVER_AUTO_CENTER_MS = 1000;

      setUrlParams({ follow: 'Player1' });

      init_observer_follow_mode();

      // Should stay at default or be reset to default
      expect(OBSERVER_AUTO_CENTER_MS).toBe(5000);
    });

    test('should handle invalid autocenter value gracefully', () => {
      setUrlParams({ follow: 'Player1', autocenter: 'invalid' });

      expect(() => init_observer_follow_mode()).not.toThrow();
      // Should fall back to default
      expect(OBSERVER_AUTO_CENTER_MS).toBe(5000);
    });
  });

  // ===========================================================================
  // observer_center_on_followed_player() Tests
  // ===========================================================================

  describe('observer_center_on_followed_player()', () => {
    test('should be defined as a global function', () => {
      expect(typeof observer_center_on_followed_player).toBe('function');
    });

    test('should not throw when observer_follow_player is null', () => {
      global.observer_follow_player = null;

      expect(() => observer_center_on_followed_player()).not.toThrow();
      expect(center_tile_mapcanvas).not.toHaveBeenCalled();
    });

    test('should center on capital city on first call (initial load guard)', () => {
      global.observer_follow_player = 0; // Player1 with cities
      global.observer_centered_notified = false;

      observer_center_on_followed_player();

      // First call uses simple capital/city centering, not territory
      expect(center_tile_mapcanvas).toHaveBeenCalled();
      expect(global.observer_centered_notified).toBe(true);
    });

    test('should use territory centering on subsequent calls', () => {
      global.observer_follow_player = 0;
      // Simulate initial center already done
      global.observer_centered_notified = true;

      observer_center_on_followed_player();

      expect(center_tile_mapcanvas).toHaveBeenCalled();
    });

    test('should use explored tile fallback when no cities on initial load (not territory)', () => {
      global.cities = {};
      global.observer_follow_player = 0;
      global.observer_centered_notified = false;

      // Add units for player 0 — but initial guard won't use territory centering
      global.index_to_tile.mockReturnValue({ x: 10, y: 20 });
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 100 }),
      };

      // Provide an explored tile fallback
      global.find_first_explored_tile.mockReturnValueOnce({ x: 10, y: 20 });

      observer_center_on_followed_player();

      // Initial guard: no city → explored tile fallback (no zoom)
      expect(center_tile_mapcanvas).toHaveBeenCalledWith({ x: 10, y: 20 });
      expect(global.observer_centered_notified).toBe(true);
    });

    test('should not center if player has no cities or units', () => {
      global.cities = {};
      global.units = {};
      global.observer_follow_player = 99; // Non-existent player

      observer_center_on_followed_player();

      expect(center_tile_mapcanvas).not.toHaveBeenCalled();
    });

    test('should not center if player is dead', () => {
      global.players[0].is_alive = false;
      global.observer_follow_player = 0;

      observer_center_on_followed_player();

      expect(center_tile_mapcanvas).not.toHaveBeenCalled();
    });

    test('should not crash if player does not exist', () => {
      global.observer_follow_player = 999; // Non-existent player ID

      expect(() => observer_center_on_followed_player()).not.toThrow();
    });

    test('should handle empty cities and units gracefully', () => {
      global.cities = {};
      global.units = {};
      global.observer_follow_player = 0;

      expect(() => observer_center_on_followed_player()).not.toThrow();
      expect(center_tile_mapcanvas).not.toHaveBeenCalled();
    });

    test('should not fall through to territory zoom when city_tile returns null on initial load', () => {
      // Capital exists but city_tile returns null — guard must NOT fall through
      // to territory centering (which would set camera_dy)
      global.city_tile.mockReturnValue(null);
      global.observer_follow_player = 0;
      global.observer_centered_notified = false;
      global.camera_dy = 150;

      // Provide an explored tile as fallback
      global.find_first_explored_tile.mockReturnValueOnce({ x: 25, y: 25, known: 2 });

      observer_center_on_followed_player();

      // Should center on explored tile, not territory
      expect(center_tile_mapcanvas).toHaveBeenCalledWith({ x: 25, y: 25, known: 2 });
      // camera_dy must remain untouched (no zoom on initial load)
      expect(global.camera_dy).toBe(150);
      expect(global.observer_centered_notified).toBe(true);
    });

    test('should not adjust camera_dy on first call (initial load guard)', () => {
      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },
          101: { x: 30, y: 10 },
        };
        return positions[city.id] || { x: 0, y: 0 };
      });

      global.observer_follow_player = 0;
      global.observer_centered_notified = false;
      global.camera_dy = 150; // default preset value

      observer_center_on_followed_player();

      // First call uses simple city centering — camera_dy should be untouched
      expect(global.camera_dy).toBe(150);
    });

    test('should update camera_dy based on territory spread after initial center', () => {
      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },  // PlayerCapital
          101: { x: 30, y: 10 },  // PlayerCity2 - 20 tiles apart
        };
        return positions[city.id] || { x: 0, y: 0 };
      });

      global.observer_follow_player = 0;
      // Simulate initial center already done
      global.observer_centered_notified = true;
      global.observer_last_territory_radius = null;

      observer_center_on_followed_player();

      // 2 cities 20 tiles apart, centroid at (20,10), both at distance 10
      // effective_radius=10 → dy = floor(250 + 10*28) = 530
      expect(global.camera_dy).toBe(530);
    });
  });

  // ===========================================================================
  // cleanup_observer_follow_mode() Tests
  // ===========================================================================

  describe('cleanup_observer_follow_mode()', () => {
    test('should be defined as a global function', () => {
      expect(typeof cleanup_observer_follow_mode).toBe('function');
    });

    test('should clear the auto-center interval', () => {
      jest.useFakeTimers();

      // Setup an interval
      global.observer_auto_center_interval = setInterval(() => {}, 1000);

      cleanup_observer_follow_mode();

      expect(observer_auto_center_interval).toBeNull();
      jest.useRealTimers();
    });

    test('should reset observer_follow_player to null', () => {
      global.observer_follow_player = 1;

      cleanup_observer_follow_mode();

      expect(observer_follow_player).toBeNull();
    });

    test('should reset territory radius tracker to null', () => {
      global.observer_last_territory_radius = 15;

      cleanup_observer_follow_mode();

      expect(observer_last_territory_radius).toBeNull();
    });

    test('should reset global spread tracker to null', () => {
      global.observer_last_global_spread = 30;

      cleanup_observer_follow_mode();

      expect(global.observer_last_global_spread).toBeNull();
    });

    test('should clear initial center and player search intervals', () => {
      jest.useFakeTimers();
      global.observer_initial_center_interval = setInterval(() => {}, 1000);
      global.observer_player_search_interval = setInterval(() => {}, 1000);

      cleanup_observer_follow_mode();

      expect(global.observer_initial_center_interval).toBeNull();
      expect(global.observer_player_search_interval).toBeNull();
      jest.useRealTimers();
    });

    test('should not throw if called when no interval exists', () => {
      global.observer_auto_center_interval = null;
      global.observer_follow_player = null;

      expect(() => cleanup_observer_follow_mode()).not.toThrow();
    });
  });

  // ===========================================================================
  // Integration Tests
  // ===========================================================================

  describe('follow player integration', () => {
    test('should perform initial center shortly after initialization', () => {
      jest.useFakeTimers();
      setUrlParams({ follow: 'Player1' });

      init_observer_follow_mode();

      // Advance timers to trigger initial center
      jest.advanceTimersByTime(1500);

      expect(center_tile_mapcanvas).toHaveBeenCalled();
      jest.useRealTimers();
    });

    test('should auto-center periodically based on interval', () => {
      jest.useFakeTimers();
      setUrlParams({ follow: 'Player1', autocenter: '2000' });

      init_observer_follow_mode();

      // Clear initial calls
      center_tile_mapcanvas.mockClear();

      // Advance past multiple intervals
      jest.advanceTimersByTime(6500); // Should trigger ~3 times at 2000ms interval

      expect(center_tile_mapcanvas.mock.calls.length).toBeGreaterThanOrEqual(2);
      jest.useRealTimers();
    });

    test('cleanup should stop auto-centering', () => {
      jest.useFakeTimers();
      setUrlParams({ follow: 'Player1', autocenter: '1000' });

      init_observer_follow_mode();
      cleanup_observer_follow_mode();

      // Clear any existing calls
      center_tile_mapcanvas.mockClear();

      // Advance time - should NOT trigger any more centers
      jest.advanceTimersByTime(5000);

      expect(center_tile_mapcanvas).not.toHaveBeenCalled();
      jest.useRealTimers();
    });

    test('should handle player city changes gracefully', () => {
      global.observer_follow_player = 0;

      // First call with cities
      observer_center_on_followed_player();
      expect(center_tile_mapcanvas).toHaveBeenCalled();

      center_tile_mapcanvas.mockClear();

      // Simulate capital being destroyed - still has PlayerCity2
      delete global.cities[100];

      observer_center_on_followed_player();
      expect(center_tile_mapcanvas).toHaveBeenCalled();
    });
  });

  // ===========================================================================
  // Territory Centering Logic Tests
  // ===========================================================================

  describe('territory centering behavior', () => {
    test('should center on capital on initial call (not territory centroid)', () => {
      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },  // PlayerCapital
          101: { x: 20, y: 10 },  // PlayerCity2
        };
        return positions[city.id] || { x: 0, y: 0 };
      });

      global.observer_follow_player = 0;
      global.observer_centered_notified = false;

      observer_center_on_followed_player();

      // First call centers on capital city tile, not territory centroid
      expect(center_tile_mapcanvas).toHaveBeenCalledWith({ x: 10, y: 10 });
    });

    test('should center on territory centroid after initial center', () => {
      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },  // PlayerCapital
          101: { x: 20, y: 10 },  // PlayerCity2
        };
        return positions[city.id] || { x: 0, y: 0 };
      });

      global.observer_follow_player = 0;
      // Simulate initial center already done
      global.observer_centered_notified = true;

      observer_center_on_followed_player();

      // Should center on centroid of (10,10) and (20,10) = (15, 10)
      expect(center_tile_mapcanvas).toHaveBeenCalledWith({ x: 15, y: 10 });
    });

    test('should include units in territory calculation after initial center', () => {
      // One city and one distant unit
      global.city_tile.mockImplementation((city) => {
        if (city.id === 100) return { x: 10, y: 10 };
        return null;
      });
      // Remove player 0's second city
      delete global.cities[101];

      global.index_to_tile.mockImplementation((index) => {
        if (index === 500) return { x: 40, y: 10 };
        return { x: 0, y: 0 };
      });
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 500 }),
      };

      global.observer_follow_player = 0;
      // Simulate initial center already done
      global.observer_centered_notified = true;

      observer_center_on_followed_player();

      // City at (10,10) weighted 3x + unit at (40,10) weighted 1x
      // centroid_x = floor((10*3 + 40) / 4) = floor(70/4) = 17
      expect(center_tile_mapcanvas).toHaveBeenCalledWith({ x: 17, y: 10 });
    });

    test('should use territory centering with units only after initial center', () => {
      global.cities = {};
      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          505: { x: 5, y: 5 },
          506: { x: 6, y: 5 },
        };
        return positions[index] || { x: 0, y: 0 };
      });
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 505 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 506 }),
      };

      global.observer_follow_player = 0;
      // After initial center, territory centering kicks in for units-only
      global.observer_centered_notified = true;

      observer_center_on_followed_player();

      expect(center_tile_mapcanvas).toHaveBeenCalledWith({ x: 5, y: 5 });
    });
  });
});
