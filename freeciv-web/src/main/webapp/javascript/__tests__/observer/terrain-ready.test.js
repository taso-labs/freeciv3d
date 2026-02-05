/**
 * Tests for terrain_ready notification event
 *
 * The terrain_ready event fires after tile data is populated in the texture,
 * solving a race condition where iframes show sky-only backgrounds.
 */

describe('terrain_ready notification', () => {
  beforeEach(() => {
    global.resetAllMocks();
    global.observing = true;
  });

  describe('flag behavior', () => {
    test('terrain_ready_notified flag starts as false', () => {
      expect(global.terrain_ready_notified).toBe(false);
    });

    test('flag resets to false via resetAllMocks', () => {
      global.terrain_ready_notified = true;
      global.resetAllMocks();
      expect(global.terrain_ready_notified).toBe(false);
    });
  });

  describe('notification trigger simulation', () => {
    // Simulates the logic in handle_map_info() after replay_pending_tile_packets()
    function simulateTerrainReadyNotification(map, buffered_count) {
      if (typeof global.terrain_ready_notified !== 'undefined' && !global.terrain_ready_notified
          && typeof global.notify_parent_iframe === 'function'
          && map && typeof map.xsize === 'number' && typeof map.ysize === 'number') {
        global.terrain_ready_notified = true;
        global.notify_parent_iframe('terrain_ready', {
          map_xsize: map.xsize,
          map_ysize: map.ysize,
          total_tiles: map.xsize * map.ysize,
          buffered_tiles_replayed: buffered_count
        });
      }
    }

    test('fires notification with correct map dimensions', () => {
      const mockMap = { xsize: 80, ysize: 50 };

      simulateTerrainReadyNotification(mockMap, 100);

      expect(global.notify_parent_iframe).toHaveBeenCalledTimes(1);
      expect(global.notify_parent_iframe).toHaveBeenCalledWith('terrain_ready', {
        map_xsize: 80,
        map_ysize: 50,
        total_tiles: 4000,
        buffered_tiles_replayed: 100
      });
    });

    test('sets terrain_ready_notified flag to true after firing', () => {
      const mockMap = { xsize: 80, ysize: 50 };

      expect(global.terrain_ready_notified).toBe(false);
      simulateTerrainReadyNotification(mockMap, 0);
      expect(global.terrain_ready_notified).toBe(true);
    });

    test('fires only once even when called multiple times', () => {
      const mockMap = { xsize: 80, ysize: 50 };

      simulateTerrainReadyNotification(mockMap, 100);
      simulateTerrainReadyNotification(mockMap, 200);
      simulateTerrainReadyNotification(mockMap, 300);

      expect(global.notify_parent_iframe).toHaveBeenCalledTimes(1);
    });

    test('does not fire when map is null', () => {
      simulateTerrainReadyNotification(null, 100);

      expect(global.notify_parent_iframe).not.toHaveBeenCalled();
      expect(global.terrain_ready_notified).toBe(false);
    });

    test('does not fire when map.xsize is not a number', () => {
      const mockMap = { xsize: 'invalid', ysize: 50 };

      simulateTerrainReadyNotification(mockMap, 100);

      expect(global.notify_parent_iframe).not.toHaveBeenCalled();
      expect(global.terrain_ready_notified).toBe(false);
    });

    test('does not fire when map.ysize is not a number', () => {
      const mockMap = { xsize: 80, ysize: undefined };

      simulateTerrainReadyNotification(mockMap, 100);

      expect(global.notify_parent_iframe).not.toHaveBeenCalled();
      expect(global.terrain_ready_notified).toBe(false);
    });

    test('includes buffered_tiles_replayed count in payload', () => {
      const mockMap = { xsize: 100, ysize: 100 };

      simulateTerrainReadyNotification(mockMap, 5432);

      expect(global.notify_parent_iframe).toHaveBeenCalledWith('terrain_ready',
        expect.objectContaining({
          buffered_tiles_replayed: 5432
        })
      );
    });
  });

  describe('flag reset on retry', () => {
    // Simulates reset_observer_state_for_retry() logic for terrain_ready_notified
    function simulateRetryReset() {
      if (typeof global.terrain_ready_notified !== 'undefined') {
        global.terrain_ready_notified = false;
      }
    }

    test('resets flag allowing re-notification after retry', () => {
      const mockMap = { xsize: 80, ysize: 50 };

      // Simulate first notification
      function simulateTerrainReadyNotification(map, buffered_count) {
        if (typeof global.terrain_ready_notified !== 'undefined' && !global.terrain_ready_notified
            && typeof global.notify_parent_iframe === 'function'
            && map && typeof map.xsize === 'number' && typeof map.ysize === 'number') {
          global.terrain_ready_notified = true;
          global.notify_parent_iframe('terrain_ready', {
            map_xsize: map.xsize,
            map_ysize: map.ysize,
            total_tiles: map.xsize * map.ysize,
            buffered_tiles_replayed: buffered_count
          });
        }
      }

      simulateTerrainReadyNotification(mockMap, 100);
      expect(global.notify_parent_iframe).toHaveBeenCalledTimes(1);
      expect(global.terrain_ready_notified).toBe(true);

      // Simulate retry reset
      simulateRetryReset();
      expect(global.terrain_ready_notified).toBe(false);

      // Should be able to fire again after reset
      simulateTerrainReadyNotification(mockMap, 200);
      expect(global.notify_parent_iframe).toHaveBeenCalledTimes(2);
    });
  });
});
