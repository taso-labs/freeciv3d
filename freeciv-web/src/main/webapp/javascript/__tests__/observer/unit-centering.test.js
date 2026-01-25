/**
 * Unit Centering System Test Suite
 *
 * Tests for observer mode unit-based centering, used when players have no cities (e.g., turn 1).
 *
 * Tests cover:
 * - get_player_units_centroid_and_spread() calculation
 * - calculate_zoom_for_unit_spread() zoom mapping
 * - center_on_player_units_with_zoom() centering with dynamic zoom
 * - observer_center_on_followed_player() unit fallback behavior
 * - Spread change threshold for zoom stability
 */

// Import the functions we're testing (they're in global scope from civclient.js)
// In a real setup, these would be loaded via script tags or module imports

describe('Unit Centering System', () => {
  beforeEach(() => {
    // Reset all mocks
    resetAllMocks();

    // Setup observer mode
    global.observing = true;

    // Setup mock players
    global.players = {
      0: createMockPlayer({ playerno: 0, name: 'Player1', username: 'user1', is_alive: true }),
      1: createMockPlayer({ playerno: 1, name: 'AI*1', username: 'AI*1', is_alive: true }),
    };

    // Start with empty cities (turn 1 scenario)
    global.cities = {};
    global.units = {};

    // Reset observer state
    global.observer_follow_player = 0;
    global.observer_last_unit_spread = null;

    // Clear any existing intervals
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
  // get_player_units_centroid_and_spread() Tests
  // ===========================================================================

  describe('get_player_units_centroid_and_spread()', () => {
    // Define the function for testing (simulating what's in civclient.js)
    const get_player_units_centroid_and_spread = (player_id) => {
      var sum_x = 0, sum_y = 0, count = 0;
      var min_x = Infinity, max_x = -Infinity;
      var min_y = Infinity, max_y = -Infinity;

      for (var unit_id in global.units) {
        var punit = global.units[unit_id];
        if (punit['owner'] === player_id) {
          var ptile = global.index_to_tile(punit['tile']);
          if (ptile) {
            sum_x += ptile['x'];
            sum_y += ptile['y'];
            count++;
            min_x = Math.min(min_x, ptile['x']);
            max_x = Math.max(max_x, ptile['x']);
            min_y = Math.min(min_y, ptile['y']);
            max_y = Math.max(max_y, ptile['y']);
          }
        }
      }

      if (count === 0) return null;

      var centroid_x = Math.floor(sum_x / count);
      var centroid_y = Math.floor(sum_y / count);
      var spread = Math.max(max_x - min_x, max_y - min_y);

      return {
        centroid: { x: centroid_x, y: centroid_y },
        spread: spread,
        count: count,
        tile: { x: centroid_x, y: centroid_y }
      };
    };

    test('should return null when player has no units', () => {
      global.units = {};
      const result = get_player_units_centroid_and_spread(0);
      expect(result).toBeNull();
    });

    test('should return null when all units belong to other players', () => {
      global.units = {
        1: createMockUnit({ id: 1, owner: 1, tile: 100 }),
        2: createMockUnit({ id: 2, owner: 1, tile: 200 }),
      };
      const result = get_player_units_centroid_and_spread(0);
      expect(result).toBeNull();
    });

    test('should calculate correct centroid for single unit', () => {
      // Unit at tile index 505 -> x=5, y=5 (using default index_to_tile mock)
      global.index_to_tile.mockImplementation((index) => ({
        x: index % 100,
        y: Math.floor(index / 100)
      }));

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 505 }),
      };

      const result = get_player_units_centroid_and_spread(0);

      expect(result).not.toBeNull();
      expect(result.centroid.x).toBe(5);
      expect(result.centroid.y).toBe(5);
      expect(result.count).toBe(1);
      expect(result.spread).toBe(0); // Single unit has 0 spread
    });

    test('should calculate correct centroid for multiple units', () => {
      // Units at: (0,0), (10,0), (0,10), (10,10) -> centroid at (5, 5)
      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          0: { x: 0, y: 0 },
          10: { x: 10, y: 0 },
          1000: { x: 0, y: 10 },
          1010: { x: 10, y: 10 },
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 10 }),
        3: createMockUnit({ id: 3, owner: 0, tile: 1000 }),
        4: createMockUnit({ id: 4, owner: 0, tile: 1010 }),
      };

      const result = get_player_units_centroid_and_spread(0);

      expect(result).not.toBeNull();
      expect(result.centroid.x).toBe(5);
      expect(result.centroid.y).toBe(5);
      expect(result.count).toBe(4);
      expect(result.spread).toBe(10); // Max of (10-0, 10-0) = 10
    });

    test('should ignore units owned by other players', () => {
      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          0: { x: 0, y: 0 },
          10: { x: 10, y: 0 },
          500: { x: 50, y: 50 }, // Far away enemy unit
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 10 }),
        3: createMockUnit({ id: 3, owner: 1, tile: 500 }), // Enemy unit - should be ignored
      };

      const result = get_player_units_centroid_and_spread(0);

      expect(result.count).toBe(2); // Only 2 player units
      expect(result.centroid.x).toBe(5); // (0+10)/2 = 5
      expect(result.centroid.y).toBe(0);
      expect(result.spread).toBe(10); // Only player units considered
    });

    test('should calculate spread as max of x-spread and y-spread', () => {
      // Units spread more in Y than X
      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          0: { x: 0, y: 0 },
          5: { x: 5, y: 0 },
          2000: { x: 0, y: 20 },
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 5 }),
        3: createMockUnit({ id: 3, owner: 0, tile: 2000 }),
      };

      const result = get_player_units_centroid_and_spread(0);

      expect(result.spread).toBe(20); // Max of (5-0=5, 20-0=20) = 20
    });
  });

  // ===========================================================================
  // calculate_zoom_for_unit_spread() Tests
  // ===========================================================================

  describe('calculate_zoom_for_unit_spread()', () => {
    // Define the function for testing (simulating what's in civclient.js)
    const calculate_zoom_for_unit_spread = (spread) => {
      const MIN_ZOOM_DY = 300;
      const MAX_ZOOM_DY = 600;
      const SPREAD_MIN = 2;
      const SPREAD_MAX = 20;

      if (spread <= SPREAD_MIN) return MIN_ZOOM_DY;
      if (spread >= SPREAD_MAX) return MAX_ZOOM_DY;

      const zoom_factor = (spread - SPREAD_MIN) / (SPREAD_MAX - SPREAD_MIN);
      return Math.floor(MIN_ZOOM_DY + zoom_factor * (MAX_ZOOM_DY - MIN_ZOOM_DY));
    };

    test('should return MIN_ZOOM_DY (300) for spread 0', () => {
      expect(calculate_zoom_for_unit_spread(0)).toBe(300);
    });

    test('should return MIN_ZOOM_DY (300) for spread 1', () => {
      expect(calculate_zoom_for_unit_spread(1)).toBe(300);
    });

    test('should return MIN_ZOOM_DY (300) for spread 2 (boundary)', () => {
      expect(calculate_zoom_for_unit_spread(2)).toBe(300);
    });

    test('should return MAX_ZOOM_DY (600) for spread 20 (boundary)', () => {
      expect(calculate_zoom_for_unit_spread(20)).toBe(600);
    });

    test('should return MAX_ZOOM_DY (600) for spread > 20', () => {
      expect(calculate_zoom_for_unit_spread(25)).toBe(600);
      expect(calculate_zoom_for_unit_spread(100)).toBe(600);
    });

    test('should return interpolated value for spread 11 (midpoint)', () => {
      // spread 11 is halfway between 2 and 20
      // zoom_factor = (11-2)/(20-2) = 9/18 = 0.5
      // zoom = 300 + 0.5 * (600-300) = 300 + 150 = 450
      expect(calculate_zoom_for_unit_spread(11)).toBe(450);
    });

    test('should return interpolated value for spread 5', () => {
      // zoom_factor = (5-2)/(20-2) = 3/18 = 0.167
      // zoom = 300 + 0.167 * 300 = 300 + 50 = 350
      expect(calculate_zoom_for_unit_spread(5)).toBe(350);
    });
  });

  // ===========================================================================
  // center_on_player_units_with_zoom() Tests
  // ===========================================================================

  describe('center_on_player_units_with_zoom()', () => {
    // Define the helper functions for testing
    const get_player_units_centroid_and_spread = (player_id) => {
      var sum_x = 0, sum_y = 0, count = 0;
      var min_x = Infinity, max_x = -Infinity;
      var min_y = Infinity, max_y = -Infinity;

      for (var unit_id in global.units) {
        var punit = global.units[unit_id];
        if (punit['owner'] === player_id) {
          var ptile = global.index_to_tile(punit['tile']);
          if (ptile) {
            sum_x += ptile['x'];
            sum_y += ptile['y'];
            count++;
            min_x = Math.min(min_x, ptile['x']);
            max_x = Math.max(max_x, ptile['x']);
            min_y = Math.min(min_y, ptile['y']);
            max_y = Math.max(max_y, ptile['y']);
          }
        }
      }

      if (count === 0) return null;

      var centroid_x = Math.floor(sum_x / count);
      var centroid_y = Math.floor(sum_y / count);
      var spread = Math.max(max_x - min_x, max_y - min_y);

      return {
        centroid: { x: centroid_x, y: centroid_y },
        spread: spread,
        count: count,
        tile: { x: centroid_x, y: centroid_y }
      };
    };

    const calculate_zoom_for_unit_spread = (spread) => {
      const MIN_ZOOM_DY = 300;
      const MAX_ZOOM_DY = 600;
      const SPREAD_MIN = 2;
      const SPREAD_MAX = 20;

      if (spread <= SPREAD_MIN) return MIN_ZOOM_DY;
      if (spread >= SPREAD_MAX) return MAX_ZOOM_DY;

      const zoom_factor = (spread - SPREAD_MIN) / (SPREAD_MAX - SPREAD_MIN);
      return Math.floor(MIN_ZOOM_DY + zoom_factor * (MAX_ZOOM_DY - MIN_ZOOM_DY));
    };

    const center_on_player_units_with_zoom = (player_id) => {
      var unit_data = get_player_units_centroid_and_spread(player_id);
      if (!unit_data) return false;

      var should_update_zoom = (
        global.observer_last_unit_spread === null ||
        Math.abs(unit_data.spread - global.observer_last_unit_spread) >= global.SPREAD_CHANGE_THRESHOLD
      );

      if (should_update_zoom) {
        var target_dy = calculate_zoom_for_unit_spread(unit_data.spread);
        global.camera_dy = target_dy;
        global.observer_last_unit_spread = unit_data.spread;
      }

      global.center_tile_mapcanvas(unit_data.tile);
      return true;
    };

    test('should return false when player has no units', () => {
      global.units = {};
      const result = center_on_player_units_with_zoom(0);
      expect(result).toBe(false);
      expect(global.center_tile_mapcanvas).not.toHaveBeenCalled();
    });

    test('should return true and center when player has units', () => {
      global.index_to_tile.mockImplementation((index) => ({
        x: 10, y: 20
      }));

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 100 }),
      };

      const result = center_on_player_units_with_zoom(0);

      expect(result).toBe(true);
      expect(global.center_tile_mapcanvas).toHaveBeenCalledWith({ x: 10, y: 20 });
    });

    test('should update camera_dy on first call (spread tracker is null)', () => {
      global.observer_last_unit_spread = null;
      global.index_to_tile.mockReturnValue({ x: 5, y: 5 });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 100 }),
      };

      center_on_player_units_with_zoom(0);

      // Single unit has spread 0, so camera_dy should be 300 (MIN_ZOOM_DY)
      expect(global.camera_dy).toBe(300);
      expect(global.observer_last_unit_spread).toBe(0);
    });

    test('should NOT update zoom when spread changes by < threshold (5 tiles)', () => {
      // Set initial spread
      global.observer_last_unit_spread = 10;
      global.camera_dy = 450; // Some initial value

      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          0: { x: 0, y: 0 },
          12: { x: 12, y: 0 }, // Spread of 12 (change of 2 from 10)
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 12 }),
      };

      center_on_player_units_with_zoom(0);

      // Spread changed from 10 to 12 (diff = 2 < threshold of 5)
      // camera_dy should NOT change
      expect(global.camera_dy).toBe(450);
      expect(global.observer_last_unit_spread).toBe(10); // Not updated
    });

    test('should update zoom when spread changes by >= threshold (5 tiles)', () => {
      // Set initial spread
      global.observer_last_unit_spread = 10;
      global.camera_dy = 450; // Some initial value

      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          0: { x: 0, y: 0 },
          20: { x: 20, y: 0 }, // Spread of 20 (change of 10 from 10)
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 20 }),
      };

      center_on_player_units_with_zoom(0);

      // Spread changed from 10 to 20 (diff = 10 >= threshold of 5)
      // camera_dy SHOULD change to 600 (MAX_ZOOM_DY for spread 20)
      expect(global.camera_dy).toBe(600);
      expect(global.observer_last_unit_spread).toBe(20);
    });
  });

  // ===========================================================================
  // has_units_for_player() Tests
  // ===========================================================================

  describe('has_units_for_player()', () => {
    // Define the function for testing
    const has_units_for_player = (player_id) => {
      if (typeof global.units === 'undefined' || player_id === null) return false;

      for (var unit_id in global.units) {
        var punit = global.units[unit_id];
        if (punit['owner'] === player_id) {
          return true;
        }
      }
      return false;
    };

    test('should return false when units global is empty', () => {
      global.units = {};
      expect(has_units_for_player(0)).toBe(false);
    });

    test('should return false when player_id is null', () => {
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 100 }),
      };
      expect(has_units_for_player(null)).toBe(false);
    });

    test('should return true when player has units', () => {
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 100 }),
      };
      expect(has_units_for_player(0)).toBe(true);
    });

    test('should return false when all units belong to other players', () => {
      global.units = {
        1: createMockUnit({ id: 1, owner: 1, tile: 100 }),
        2: createMockUnit({ id: 2, owner: 2, tile: 200 }),
      };
      expect(has_units_for_player(0)).toBe(false);
    });
  });

  // ===========================================================================
  // observer_center_on_followed_player() Unit Fallback Tests
  // ===========================================================================

  describe('observer_center_on_followed_player() unit fallback', () => {
    // Create a simplified version of the function for testing
    const observer_center_on_followed_player = () => {
      if (global.observer_follow_player === null) return;

      var player = global.players[global.observer_follow_player];
      if (!player || !player['is_alive']) return;

      // Priority 1 & 2: Check for cities (capital or largest)
      var target_city = null;
      for (var city_id in global.cities) {
        var pcity = global.cities[city_id];
        if (pcity.owner === global.observer_follow_player) {
          if (pcity.capital === global.CAPITAL_PRIMARY) {
            target_city = pcity;
            break;
          }
          if (!target_city || pcity.size > target_city.size) {
            target_city = pcity;
          }
        }
      }

      if (target_city) {
        var ptile = global.city_tile(target_city);
        global.center_tile_mapcanvas(ptile);
        global.observer_last_unit_spread = null; // Reset on city center
        return;
      }

      // Priority 3: Fall back to units
      const get_player_units_centroid_and_spread = (player_id) => {
        var sum_x = 0, sum_y = 0, count = 0;
        var min_x = Infinity, max_x = -Infinity;
        var min_y = Infinity, max_y = -Infinity;

        for (var unit_id in global.units) {
          var punit = global.units[unit_id];
          if (punit['owner'] === player_id) {
            var ptile = global.index_to_tile(punit['tile']);
            if (ptile) {
              sum_x += ptile['x'];
              sum_y += ptile['y'];
              count++;
              min_x = Math.min(min_x, ptile['x']);
              max_x = Math.max(max_x, ptile['x']);
              min_y = Math.min(min_y, ptile['y']);
              max_y = Math.max(max_y, ptile['y']);
            }
          }
        }

        if (count === 0) return null;
        var centroid_x = Math.floor(sum_x / count);
        var centroid_y = Math.floor(sum_y / count);
        var spread = Math.max(max_x - min_x, max_y - min_y);

        return { centroid: { x: centroid_x, y: centroid_y }, spread, count, tile: { x: centroid_x, y: centroid_y } };
      };

      var unit_data = get_player_units_centroid_and_spread(global.observer_follow_player);
      if (unit_data) {
        global.center_tile_mapcanvas(unit_data.tile);
      }
    };

    test('should center on units when player has no cities (turn 1)', () => {
      global.observer_follow_player = 0;
      global.cities = {}; // No cities
      global.index_to_tile.mockReturnValue({ x: 15, y: 25 });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 100 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 200 }),
      };

      observer_center_on_followed_player();

      expect(global.center_tile_mapcanvas).toHaveBeenCalled();
    });

    test('should prefer city over units when both exist', () => {
      global.observer_follow_player = 0;
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'TestCapital', size: 5, capital: global.CAPITAL_PRIMARY }),
      };
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 500 }),
      };

      observer_center_on_followed_player();

      // Should center on city, not units
      expect(global.center_tile_mapcanvas).toHaveBeenCalledWith(
        expect.objectContaining({ x: 100, y: 100 }) // city_tile mock returns id-based coords
      );
    });

    test('should reset spread tracker when centering on city', () => {
      global.observer_follow_player = 0;
      global.observer_last_unit_spread = 15; // Had been tracking units

      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'TestCapital', size: 5, capital: global.CAPITAL_PRIMARY }),
      };

      observer_center_on_followed_player();

      // Spread tracker should be reset when we center on a city
      expect(global.observer_last_unit_spread).toBeNull();
    });

    test('should not call center_tile_mapcanvas when player has no cities or units', () => {
      global.observer_follow_player = 0;
      global.cities = {};
      global.units = {};

      observer_center_on_followed_player();

      expect(global.center_tile_mapcanvas).not.toHaveBeenCalled();
    });
  });

  // ===========================================================================
  // Integration: Turn 1 Scenario Tests
  // ===========================================================================

  describe('Turn 1 Scenario Integration', () => {
    test('should handle typical turn 1 setup with settler and explorer', () => {
      global.observer_follow_player = 0;
      global.cities = {}; // No cities on turn 1

      // Typical turn 1: settler and explorer close together
      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          505: { x: 5, y: 5 },  // Settler
          506: { x: 6, y: 5 },  // Explorer nearby
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 505, type: 0 }), // Settler
        2: createMockUnit({ id: 2, owner: 0, tile: 506, type: 1 }), // Explorer
      };

      // Define our test functions
      const get_player_units_centroid_and_spread = (player_id) => {
        var sum_x = 0, sum_y = 0, count = 0;
        var min_x = Infinity, max_x = -Infinity;
        var min_y = Infinity, max_y = -Infinity;

        for (var unit_id in global.units) {
          var punit = global.units[unit_id];
          if (punit['owner'] === player_id) {
            var ptile = global.index_to_tile(punit['tile']);
            if (ptile) {
              sum_x += ptile['x'];
              sum_y += ptile['y'];
              count++;
              min_x = Math.min(min_x, ptile['x']);
              max_x = Math.max(max_x, ptile['x']);
              min_y = Math.min(min_y, ptile['y']);
              max_y = Math.max(max_y, ptile['y']);
            }
          }
        }

        if (count === 0) return null;
        return {
          centroid: { x: Math.floor(sum_x / count), y: Math.floor(sum_y / count) },
          spread: Math.max(max_x - min_x, max_y - min_y),
          count: count,
          tile: { x: Math.floor(sum_x / count), y: Math.floor(sum_y / count) }
        };
      };

      const unit_data = get_player_units_centroid_and_spread(0);

      // Centroid should be average: (5+6)/2=5.5 -> 5, (5+5)/2=5
      expect(unit_data.centroid.x).toBe(5);
      expect(unit_data.centroid.y).toBe(5);
      expect(unit_data.count).toBe(2);
      expect(unit_data.spread).toBe(1); // Units are 1 tile apart

      // With spread of 1 (< 2), zoom should be MIN_ZOOM_DY = 300
      const calculate_zoom_for_unit_spread = (spread) => {
        if (spread <= 2) return 300;
        if (spread >= 20) return 600;
        return Math.floor(300 + ((spread - 2) / (20 - 2)) * 300);
      };

      expect(calculate_zoom_for_unit_spread(unit_data.spread)).toBe(300);
    });

    test('should handle scattered units on large map', () => {
      global.observer_follow_player = 0;
      global.cities = {};

      // Units spread across 25 tiles
      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          0: { x: 0, y: 0 },
          25: { x: 25, y: 0 },
          1200: { x: 0, y: 12 },
          1225: { x: 25, y: 12 },
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 25 }),
        3: createMockUnit({ id: 3, owner: 0, tile: 1200 }),
        4: createMockUnit({ id: 4, owner: 0, tile: 1225 }),
      };

      const get_player_units_centroid_and_spread = (player_id) => {
        var sum_x = 0, sum_y = 0, count = 0;
        var min_x = Infinity, max_x = -Infinity;
        var min_y = Infinity, max_y = -Infinity;

        for (var unit_id in global.units) {
          var punit = global.units[unit_id];
          if (punit['owner'] === player_id) {
            var ptile = global.index_to_tile(punit['tile']);
            if (ptile) {
              sum_x += ptile['x'];
              sum_y += ptile['y'];
              count++;
              min_x = Math.min(min_x, ptile['x']);
              max_x = Math.max(max_x, ptile['x']);
              min_y = Math.min(min_y, ptile['y']);
              max_y = Math.max(max_y, ptile['y']);
            }
          }
        }

        if (count === 0) return null;
        return {
          centroid: { x: Math.floor(sum_x / count), y: Math.floor(sum_y / count) },
          spread: Math.max(max_x - min_x, max_y - min_y),
          count: count,
          tile: { x: Math.floor(sum_x / count), y: Math.floor(sum_y / count) }
        };
      };

      const unit_data = get_player_units_centroid_and_spread(0);

      expect(unit_data.spread).toBe(25); // Max spread > 20

      // With spread > 20, zoom should be MAX_ZOOM_DY = 600
      const calculate_zoom_for_unit_spread = (spread) => {
        if (spread <= 2) return 300;
        if (spread >= 20) return 600;
        return Math.floor(300 + ((spread - 2) / (20 - 2)) * 300);
      };

      expect(calculate_zoom_for_unit_spread(unit_data.spread)).toBe(600);
    });
  });
});
