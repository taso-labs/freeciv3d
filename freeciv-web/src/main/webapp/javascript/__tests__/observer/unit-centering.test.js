/**
 * Unit & Territory Centering System Test Suite
 *
 * Tests for observer mode centering systems:
 * - Unit-based centering (turn 1 fallback)
 * - Territory-based centering (cities + units with dynamic zoom)
 * - Zoom calculations and hysteresis
 */

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
    global.observer_last_territory_radius = null;

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
    // Uses global mock from jest.setup.js which delegates to
    // compute_wrapped_spread_and_centroid() (same as production)
    const get_player_units_centroid_and_spread = global.get_player_units_centroid_and_spread;

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
      expect(result.spread).toBe(0);
    });

    test('should calculate correct centroid for multiple units', () => {
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
      expect(result.spread).toBe(10);
    });

    test('should ignore units owned by other players', () => {
      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          0: { x: 0, y: 0 },
          10: { x: 10, y: 0 },
          500: { x: 50, y: 50 },
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 10 }),
        3: createMockUnit({ id: 3, owner: 1, tile: 500 }),
      };

      const result = get_player_units_centroid_and_spread(0);

      expect(result.count).toBe(2);
      expect(result.centroid.x).toBe(5);
      expect(result.centroid.y).toBe(0);
      expect(result.spread).toBe(10);
    });

    test('should calculate spread as max of x-spread and y-spread', () => {
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

      expect(result.spread).toBe(20);
    });
  });

  // ===========================================================================
  // calculate_zoom_for_unit_spread() Tests
  // ===========================================================================

  describe('calculate_zoom_for_unit_spread()', () => {
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
      expect(calculate_zoom_for_unit_spread(11)).toBe(450);
    });

    test('should return interpolated value for spread 5', () => {
      expect(calculate_zoom_for_unit_spread(5)).toBe(350);
    });
  });

  // ===========================================================================
  // center_on_player_units_with_zoom() Tests (used by global view)
  // ===========================================================================

  describe('center_on_player_units_with_zoom()', () => {
    // Uses global mocks from jest.setup.js which delegate to
    // compute_wrapped_spread_and_centroid() (same as production)
    const center_on_player_units_with_zoom = global.center_on_player_units_with_zoom;

    test('should return false when player has no units', () => {
      global.units = {};
      const result = center_on_player_units_with_zoom(0);
      expect(result).toBe(false);
      expect(global.center_tile_mapcanvas).not.toHaveBeenCalled();
    });

    test('should return true and center when player has units', () => {
      global.index_to_tile.mockReturnValue({ x: 10, y: 20 });
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

      expect(global.camera_dy).toBe(300);
      expect(global.observer_last_unit_spread).toBe(0);
    });

    test('should NOT update zoom when spread changes by < threshold (5 tiles)', () => {
      global.observer_last_unit_spread = 10;
      global.camera_dy = 450;

      global.index_to_tile.mockImplementation((index) => {
        const positions = { 0: { x: 0, y: 0 }, 12: { x: 12, y: 0 } };
        return positions[index] || { x: 0, y: 0 };
      });
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 12 }),
      };

      center_on_player_units_with_zoom(0);

      expect(global.camera_dy).toBe(450);
      expect(global.observer_last_unit_spread).toBe(10);
    });

    test('should update zoom when spread changes by >= threshold (5 tiles)', () => {
      global.observer_last_unit_spread = 10;
      global.camera_dy = 450;

      global.index_to_tile.mockImplementation((index) => {
        const positions = { 0: { x: 0, y: 0 }, 20: { x: 20, y: 0 } };
        return positions[index] || { x: 0, y: 0 };
      });
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 20 }),
      };

      center_on_player_units_with_zoom(0);

      expect(global.camera_dy).toBe(600);
      expect(global.observer_last_unit_spread).toBe(20);
    });
  });

  // ===========================================================================
  // has_units_for_player() Tests
  // ===========================================================================

  describe('has_units_for_player()', () => {
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
  // Turn 1 Scenario Tests
  // ===========================================================================

  describe('Turn 1 Scenario Integration', () => {
    test('should handle typical turn 1 setup with settler and explorer', () => {
      global.observer_follow_player = 0;
      global.cities = {};

      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          505: { x: 5, y: 5 },
          506: { x: 6, y: 5 },
        };
        return positions[index] || { x: 0, y: 0 };
      });

      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 505, type: 0 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 506, type: 1 }),
      };

      // Test territory centroid calculation
      const territory_data = global.get_player_territory_centroid_and_spread(0);

      expect(territory_data.centroid.x).toBe(5);
      expect(territory_data.centroid.y).toBe(5);
      expect(territory_data.count).toBe(2);
      expect(territory_data.unit_count).toBe(2);
      expect(territory_data.city_count).toBe(0);
      expect(territory_data.spread).toBe(1);

      // effective_radius = 0.5 (both units equidistant from centroid)
      // zoom = floor(250 + 0.5*35) = 267
      expect(global.calculate_zoom_for_territory_spread(territory_data.effective_radius)).toBe(267);
    });
  });
});

// ===========================================================================
// Territory Centering System Tests
// ===========================================================================

describe('Territory Centering System', () => {
  beforeEach(() => {
    resetAllMocks();
    global.observing = true;
    global.players = {
      0: createMockPlayer({ playerno: 0, name: 'Player1', username: 'user1', is_alive: true }),
      1: createMockPlayer({ playerno: 1, name: 'AI*1', username: 'AI*1', is_alive: true }),
    };
    global.cities = {};
    global.units = {};
    global.observer_follow_player = 0;
    global.observer_last_territory_radius = null;
  });

  // ===========================================================================
  // get_player_territory_centroid_and_spread() Tests
  // ===========================================================================

  describe('get_player_territory_centroid_and_spread()', () => {
    test('should return null when player has no cities or units', () => {
      const result = global.get_player_territory_centroid_and_spread(0);
      expect(result).toBeNull();
    });

    test('should calculate centroid from cities only', () => {
      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },
          101: { x: 30, y: 10 },
        };
        return positions[city.id] || null;
      });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'City1', size: 3 }),
        101: createMockCity({ id: 101, owner: 0, name: 'City2', size: 2 }),
      };

      const result = global.get_player_territory_centroid_and_spread(0);

      expect(result).not.toBeNull();
      expect(result.centroid.x).toBe(20);
      expect(result.centroid.y).toBe(10);
      expect(result.city_count).toBe(2);
      expect(result.unit_count).toBe(0);
      expect(result.spread).toBe(20);
    });

    test('should calculate centroid from units only', () => {
      global.index_to_tile.mockImplementation((index) => {
        const positions = {
          505: { x: 5, y: 5 },
          510: { x: 10, y: 5 },
        };
        return positions[index] || { x: 0, y: 0 };
      });
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 505 }),
        2: createMockUnit({ id: 2, owner: 0, tile: 510 }),
      };

      const result = global.get_player_territory_centroid_and_spread(0);

      expect(result).not.toBeNull();
      expect(result.centroid.x).toBe(7);
      expect(result.centroid.y).toBe(5);
      expect(result.city_count).toBe(0);
      expect(result.unit_count).toBe(2);
      expect(result.spread).toBe(5);
    });

    test('should combine cities and units with city weighting in centroid', () => {
      global.city_tile.mockImplementation((city) => {
        if (city.id === 100) return { x: 10, y: 10 };
        return null;
      });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'City1', size: 3 }),
      };

      global.index_to_tile.mockImplementation((index) => {
        if (index === 500) return { x: 40, y: 10 };
        return { x: 0, y: 0 };
      });
      global.units = {
        1: createMockUnit({ id: 1, owner: 0, tile: 500 }),
      };

      const result = global.get_player_territory_centroid_and_spread(0);

      expect(result).not.toBeNull();
      // City at (10,10) weighted 3x + unit at (40,10) weighted 1x
      // centroid_x = floor((10*3 + 40*1) / 4) = floor(70/4) = 17
      expect(result.centroid.x).toBe(17);
      expect(result.centroid.y).toBe(10);
      expect(result.city_count).toBe(1);
      expect(result.unit_count).toBe(1);
      expect(result.spread).toBe(30);
    });

    test('should ignore cities and units owned by other players', () => {
      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },
          200: { x: 50, y: 50 },
        };
        return positions[city.id] || null;
      });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'MyCity', size: 3 }),
        200: createMockCity({ id: 200, owner: 1, name: 'EnemyCity', size: 5 }),
      };
      global.index_to_tile.mockReturnValue({ x: 80, y: 80 });
      global.units = {
        1: createMockUnit({ id: 1, owner: 1, tile: 500 }),
      };

      const result = global.get_player_territory_centroid_and_spread(0);

      expect(result).not.toBeNull();
      expect(result.city_count).toBe(1);
      expect(result.unit_count).toBe(0);
      // count = city_count * TERRITORY_CITY_WEIGHT = 1 * 3 = 3 (weighted)
      expect(result.count).toBe(3);
    });
  });

  // ===========================================================================
  // calculate_zoom_for_territory_spread() Tests
  // ===========================================================================

  describe('calculate_zoom_for_territory_spread()', () => {
    // Linear formula: dy = floor(max(MIN, min(MAX, BASE + radius * DY_PER_TILE)))
    // BASE=250, DY_PER_TILE=28, MIN=200, MAX=900

    test('should return BASE (250) for radius 0', () => {
      expect(global.calculate_zoom_for_territory_spread(0)).toBe(250);
    });

    test('should compute linearly for small radius', () => {
      // radius 5: floor(250 + 5*35) = floor(425) = 425
      expect(global.calculate_zoom_for_territory_spread(5)).toBe(425);
    });

    test('should compute linearly for medium radius', () => {
      // radius 10: floor(250 + 10*35) = floor(600) = 600
      expect(global.calculate_zoom_for_territory_spread(10)).toBe(600);
    });

    test('should compute linearly for large radius', () => {
      // radius 20: floor(250 + 20*35) = floor(950) = 950
      expect(global.calculate_zoom_for_territory_spread(20)).toBe(950);
    });

    test('should clamp to MAX (1200) for very large radius', () => {
      // radius 30: floor(250 + 30*35) = 1300 -> clamped to 1200
      expect(global.calculate_zoom_for_territory_spread(30)).toBe(1200);
      expect(global.calculate_zoom_for_territory_spread(100)).toBe(1200);
    });

    test('should clamp to MIN (200) for negative radius', () => {
      expect(global.calculate_zoom_for_territory_spread(-5)).toBe(200);
    });
  });

  // ===========================================================================
  // center_on_player_territory_with_zoom() Tests
  // ===========================================================================

  describe('center_on_player_territory_with_zoom()', () => {
    test('should return null when player has no territory', () => {
      const result = global.center_on_player_territory_with_zoom(0);
      expect(result).toBeNull();
      expect(global.center_tile_mapcanvas).not.toHaveBeenCalled();
    });

    test('should center and return territory data when territory exists', () => {
      global.city_tile.mockReturnValue({ x: 10, y: 10 });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'City1', size: 3 }),
      };

      const result = global.center_on_player_territory_with_zoom(0);

      expect(result).not.toBeNull();
      expect(result.city_count).toBe(1);
      expect(global.center_tile_mapcanvas).toHaveBeenCalled();
    });

    test('should update camera_dy on first call (spread tracker null)', () => {
      global.observer_last_territory_radius = null;
      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },
          101: { x: 30, y: 10 },
        };
        return positions[city.id] || null;
      });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'City1', size: 3 }),
        101: createMockCity({ id: 101, owner: 0, name: 'City2', size: 2 }),
      };

      global.center_on_player_territory_with_zoom(0);

      // 2 cities weight 3 each: centroid at (20, 10)
      // Chebyshev distances: city(10,10)=10 x3, city(30,10)=10 x3 → all 10
      // effective_radius = 10 → dy = floor(250 + 10*35) = 600
      expect(global.camera_dy).toBe(600);
      expect(global.observer_last_territory_radius).toBe(10);
    });

    test('should NOT update zoom when effective radius changes by < threshold (2 tiles)', () => {
      global.observer_last_territory_radius = 10;
      global.camera_dy = 600;

      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },
          101: { x: 31, y: 10 },
        };
        return positions[city.id] || null;
      });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'City1', size: 3 }),
        101: createMockCity({ id: 101, owner: 0, name: 'City2', size: 2 }),
      };

      global.center_on_player_territory_with_zoom(0);

      // centroid at (20.5, 10), distances all ~10.5
      // effective_radius ≈ 10.5, diff from 10 = 0.5 < threshold 2
      expect(global.camera_dy).toBe(600);
      expect(global.observer_last_territory_radius).toBe(10); // Not updated
    });

    test('should update zoom when effective radius changes by >= threshold (2 tiles)', () => {
      global.observer_last_territory_radius = 10;
      global.camera_dy = 600;

      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 10, y: 10 },
          101: { x: 40, y: 10 },
        };
        return positions[city.id] || null;
      });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'City1', size: 3 }),
        101: createMockCity({ id: 101, owner: 0, name: 'City2', size: 2 }),
      };

      global.center_on_player_territory_with_zoom(0);

      // centroid at (25, 10), distances all 15
      // effective_radius = 15, diff from 10 = 5 >= threshold 2
      // dy = floor(250 + 15*35) = 775
      expect(global.camera_dy).toBe(775);
      expect(global.observer_last_territory_radius).toBe(15);
    });
  });

  // ===========================================================================
  // Wrap-Aware Centroid/Spread Tests
  // ===========================================================================

  describe('compute_wrapped_spread_and_centroid()', () => {
    test('should return null for empty positions array', () => {
      expect(global.compute_wrapped_spread_and_centroid([])).toBeNull();
      expect(global.compute_wrapped_spread_and_centroid(null)).toBeNull();
    });

    test('should compute correctly for single position', () => {
      const result = global.compute_wrapped_spread_and_centroid([
        { x: 10, y: 20, weight: 1 }
      ]);
      expect(result.centroid_x).toBe(10);
      expect(result.centroid_y).toBe(20);
      expect(result.spread).toBe(0);
      expect(result.effective_radius).toBe(0);
      expect(result.total_weight).toBe(1);
    });

    test('should compute correctly with no wrapping (flat map)', () => {
      // Default map has wrap_id=0, so no wrapping
      const result = global.compute_wrapped_spread_and_centroid([
        { x: 10, y: 10, weight: 1 },
        { x: 30, y: 10, weight: 1 },
      ]);
      expect(result.centroid_x).toBe(20);
      expect(result.centroid_y).toBe(10);
      expect(result.spread).toBe(20);
      // Both equidistant from centroid: Chebyshev dist = 10
      expect(result.effective_radius).toBe(10);
    });

    test('should respect weights in centroid calculation', () => {
      const result = global.compute_wrapped_spread_and_centroid([
        { x: 10, y: 10, weight: 3 },
        { x: 40, y: 10, weight: 1 },
      ]);
      // centroid_x = floor((10*3 + 40*1) / 4) = floor(70/4) = 17
      expect(result.centroid_x).toBe(17);
      expect(result.centroid_y).toBe(10);
      expect(result.total_weight).toBe(4);
    });

    test('should default weight to 1 when not specified', () => {
      const result = global.compute_wrapped_spread_and_centroid([
        { x: 0, y: 0 },
        { x: 10, y: 0 },
      ]);
      expect(result.centroid_x).toBe(5);
      expect(result.total_weight).toBe(2);
    });

    test('effective_radius should exclude outlier via percentile', () => {
      // 3 cities (weight 3 each) clustered + 1 distant scout (weight 1)
      // Total weighted entries: 9 city + 1 unit = 10
      // 85th percentile index = floor(10 * 0.85) = 8 → distances[8]
      const result = global.compute_wrapped_spread_and_centroid([
        { x: 10, y: 10, weight: 3 },  // city
        { x: 12, y: 10, weight: 3 },  // city
        { x: 14, y: 10, weight: 3 },  // city
        { x: 60, y: 10, weight: 1 },  // distant scout
      ]);
      // centroid_raw_x = (10*3 + 12*3 + 14*3 + 60*1) / 10 = (30+36+42+60)/10 = 16.8
      // centroid_raw_y = 10
      // Distances (Chebyshev from 16.8, 10):
      //   city(10,10): |10-16.8| = 6.8, x3 → [6.8, 6.8, 6.8]
      //   city(12,10): |12-16.8| = 4.8, x3 → [4.8, 4.8, 4.8]
      //   city(14,10): |14-16.8| = 2.8, x3 → [2.8, 2.8, 2.8]
      //   scout(60,10): |60-16.8| = 43.2, x1 → [43.2]
      // Sorted: [2.8, 2.8, 2.8, 4.8, 4.8, 4.8, 6.8, 6.8, 6.8, 43.2]
      // Index 8 → 6.8 (scout excluded!)
      expect(result.effective_radius).toBeCloseTo(6.8, 1);

      // Full spread still includes the scout: 60-10 = 50
      expect(result.spread).toBe(50);
    });
  });

  describe('Wrapping map centroid calculations', () => {
    beforeEach(() => {
      // Configure a wrapping map (X-wrap, 80x50)
      global.map = { xsize: 80, ysize: 50, topology_id: 0, wrap_id: 1 }; // WRAP_X only
    });

    afterEach(() => {
      // Restore default non-wrapping map
      global.map = { xsize: 0, ysize: 0, topology_id: 0, wrap_id: 0 };
    });

    test('should unwrap positions that span the X date line', () => {
      // Two positions near x=0 and x=75 on an 80-wide map
      // Without wrapping: centroid at x=37, spread=75 (wrong, they're 5 tiles apart)
      // With wrapping: positions unwrap to be adjacent, spread=5
      const result = global.compute_wrapped_spread_and_centroid([
        { x: 75, y: 10, weight: 1 },
        { x: 2, y: 10, weight: 1 },
      ]);

      // Ref is x=75. Point x=2 has dx = 2-75 = -73 < -half_w(-40), so unwraps to 2+80=82
      // centroid_x = floor((75+82)/2) = floor(157/2) = 78
      // Re-wrap: 78 % 80 = 78
      expect(result.centroid_x).toBe(78);
      expect(result.centroid_y).toBe(10);
      expect(result.spread).toBe(7); // max(82-75, 0) = 7
    });

    test('should unwrap correctly when centroid wraps around to low x', () => {
      // Cluster near x=78 and x=1 on an 80-wide map
      const result = global.compute_wrapped_spread_and_centroid([
        { x: 78, y: 10, weight: 1 },
        { x: 79, y: 10, weight: 1 },
        { x: 0, y: 10, weight: 1 },
        { x: 1, y: 10, weight: 1 },
      ]);

      // Ref x=78. dx for 79=1, dx for 0=-78 < -40 -> 0+80=80, dx for 1=-77 < -40 -> 1+80=81
      // Unwrapped: 78, 79, 80, 81. centroid_x = floor((78+79+80+81)/4) = floor(318/4) = 79
      // Re-wrap: 79 % 80 = 79
      expect(result.centroid_x).toBe(79);
      expect(result.spread).toBe(3); // 81-78 = 3
    });

    test('should NOT unwrap when positions are close (within half map)', () => {
      // Two positions at x=10 and x=30 on an 80-wide map — within half
      const result = global.compute_wrapped_spread_and_centroid([
        { x: 10, y: 10, weight: 1 },
        { x: 30, y: 10, weight: 1 },
      ]);

      expect(result.centroid_x).toBe(20);
      expect(result.spread).toBe(20);
    });

    test('should handle Y-wrapping when enabled', () => {
      // Enable both X and Y wrapping
      global.map = { xsize: 80, ysize: 50, topology_id: 0, wrap_id: 3 }; // WRAP_X | WRAP_Y

      const result = global.compute_wrapped_spread_and_centroid([
        { x: 10, y: 48, weight: 1 },
        { x: 10, y: 2, weight: 1 },
      ]);

      // Ref y=48. dy for 2 = 2-48 = -46 < -half_h(-25), so unwraps to 2+50=52
      // centroid_y = floor((48+52)/2) = 50. Re-wrap: 50 % 50 = 0
      expect(result.centroid_y).toBe(0);
      expect(result.spread).toBe(4); // 52-48 = 4
    });

    test('territory centroid should use wrapping for cities across date line', () => {
      // Setup wrapping map
      global.map = { xsize: 80, ysize: 50, topology_id: 0, wrap_id: 1 };

      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 78, y: 10 },
          101: { x: 2, y: 10 },
        };
        return positions[city.id] || null;
      });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'WestCity' }),
        101: createMockCity({ id: 101, owner: 0, name: 'EastCity' }),
      };

      const result = global.get_player_territory_centroid_and_spread(0);

      expect(result).not.toBeNull();
      // Both cities weighted at 3 each. Ref x=78.
      // City2: dx = 2-78 = -76 < -40 -> unwraps to 82
      // centroid_x = floor((78*3 + 82*3) / 6) = floor(480/6) = 80
      // Re-wrap: 80 % 80 = 0
      expect(result.centroid.x).toBe(0);
      expect(result.centroid.y).toBe(10);
      // Spread: 82-78 = 4
      expect(result.spread).toBe(4);
    });

    test('territory centroid without wrapping treats same positions as distant', () => {
      // Non-wrapping map — same positions should give naive spread
      global.map = { xsize: 80, ysize: 50, topology_id: 0, wrap_id: 0 };

      global.city_tile.mockImplementation((city) => {
        const positions = {
          100: { x: 78, y: 10 },
          101: { x: 2, y: 10 },
        };
        return positions[city.id] || null;
      });
      global.cities = {
        100: createMockCity({ id: 100, owner: 0, name: 'WestCity' }),
        101: createMockCity({ id: 101, owner: 0, name: 'EastCity' }),
      };

      const result = global.get_player_territory_centroid_and_spread(0);

      expect(result).not.toBeNull();
      // Without wrapping: centroid_x = floor((78*3 + 2*3) / 6) = floor(240/6) = 40
      expect(result.centroid.x).toBe(40);
      // Spread: 78-2 = 76
      expect(result.spread).toBe(76);
    });
  });
});
