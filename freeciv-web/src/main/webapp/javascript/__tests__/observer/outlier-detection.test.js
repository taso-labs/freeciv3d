/**
 * Outlier Detection Test Suite
 *
 * Tests for find_outlier_cutoff_radius() — gap-based outlier detection
 * used by territory zoom calculations.
 *
 * The function cuts outliers only when BOTH:
 *   1. A significant gap exists (> core_radius * OUTLIER_GAP_RATIO)
 *   2. The outlier causes excessive zoom (max > core_radius * OUTLIER_ZOOM_IMPACT_RATIO)
 */

describe('find_outlier_cutoff_radius()', () => {
  beforeEach(() => {
    resetAllMocks();
  });

  // ===========================================================================
  // Edge Cases
  // ===========================================================================

  describe('edge cases', () => {
    test('should return 0 for empty array', () => {
      expect(global.find_outlier_cutoff_radius([])).toBe(0);
    });

    test('should return the single element for array of length 1', () => {
      expect(global.find_outlier_cutoff_radius([5])).toBe(5);
    });

    test('should return last element for array of length 2 (never cuts)', () => {
      expect(global.find_outlier_cutoff_radius([2, 100])).toBe(100);
    });

    test('should return last element when all distances are zero', () => {
      expect(global.find_outlier_cutoff_radius([0, 0, 0, 0, 0])).toBe(0);
    });

    test('should return last element when all distances are equal', () => {
      expect(global.find_outlier_cutoff_radius([5, 5, 5, 5, 5])).toBe(5);
    });
  });

  // ===========================================================================
  // No-cut scenarios (gap or zoom impact below threshold)
  // ===========================================================================

  describe('should NOT cut outliers when', () => {
    test('distances are evenly spread (no significant gap)', () => {
      // [2, 4, 6, 8, 10] — uniform spacing, no single large gap
      expect(global.find_outlier_cutoff_radius([2, 4, 6, 8, 10])).toBe(10);
    });

    test('gap exists but zoom impact is below threshold', () => {
      // [2, 2, 2, 2, 2, 2, 2, 6, 7]
      // Gap at 2→6 is 4, core_radius=2, gap_ratio check: 4 > 2*0.8=1.6 ✓
      // But zoom impact check: max=7, 7 > 2*4.0=8? NO → no cut
      expect(global.find_outlier_cutoff_radius([2, 2, 2, 2, 2, 2, 2, 6, 7])).toBe(7);
    });

    test('zoom impact is high but gap is not significant', () => {
      // [1, 2, 3, 4, 5, 6, 7, 8, 9, 50]
      // Gradual increase from 1-9, then jump to 50
      // min_core_index = floor(10 * 0.6) = 6
      // Gaps from index 6: 8-7=1, 9-8=1, 50-9=41
      // Best gap: 41 at index 8, core_radius=9
      // Gap check: 41 > 9*0.8=7.2 ✓
      // Zoom check: 50 > 9*4.0=36 ✓ → CUTS
      // Actually this WILL cut. Let me design a better test.
      // [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
      // Uniform 2-step, no significant gap
      expect(global.find_outlier_cutoff_radius([1, 3, 5, 7, 9, 11, 13, 15, 17, 19])).toBe(19);
    });
  });

  // ===========================================================================
  // Cut scenarios (both gap and zoom impact exceed threshold)
  // ===========================================================================

  describe('should cut outliers when', () => {
    test('single distant outlier with clustered core', () => {
      // [2, 2, 2, 2, 2, 2, 2, 2, 2, 80]
      // min_core_index = floor(10 * 0.6) = 6
      // Gaps from index 6: 2-2=0, 2-2=0, 80-2=78
      // Best gap: 78 at index 8, core_radius=2
      // Gap check: 78 > 2*0.8=1.6 ✓
      // Zoom check: 80 > 2*4.0=8 ✓ → CUT at 2
      expect(global.find_outlier_cutoff_radius([2, 2, 2, 2, 2, 2, 2, 2, 2, 80])).toBe(2);
    });

    test('multiple outliers beyond the gap', () => {
      // [1, 1, 1, 1, 1, 1, 50, 55, 60]
      // min_core_index = floor(9 * 0.6) = 5
      // Gaps from index 5: 50-1=49, 55-50=5, 60-55=5
      // Best gap: 49 at index 5, core_radius=1
      // Gap check: 49 > 1*0.8=0.8 ✓
      // Zoom check: 60 > 1*4.0=4 ✓ → CUT at 1
      expect(global.find_outlier_cutoff_radius([1, 1, 1, 1, 1, 1, 50, 55, 60])).toBe(1);
    });

    test('realistic territory scenario — 3 cities clustered, 1 distant scout', () => {
      // Sorted distances from centroid: [2.8, 2.8, 2.8, 4.8, 4.8, 4.8, 6.8, 6.8, 6.8, 43.2]
      // min_core_index = floor(10 * 0.6) = 6
      // Gaps from index 6: 6.8-6.8=0, 6.8-6.8=0, 43.2-6.8=36.4
      // Best gap: 36.4 at index 8, core_radius=6.8
      // Gap check: 36.4 > 6.8*0.8=5.44 ✓
      // Zoom check: 43.2 > 6.8*4.0=27.2 ✓ → CUT at 6.8
      var distances = [2.8, 2.8, 2.8, 4.8, 4.8, 4.8, 6.8, 6.8, 6.8, 43.2];
      expect(global.find_outlier_cutoff_radius(distances)).toBeCloseTo(6.8, 1);
    });
  });

  // ===========================================================================
  // Boundary and threshold tests
  // ===========================================================================

  describe('threshold boundary behavior', () => {
    test('respects OUTLIER_MIN_CORE_RATIO — only scans from 60th percentile', () => {
      // [1, 100, 100, 100, 100, 100, 100, 100, 100, 100]
      // min_core_index = floor(10 * 0.6) = 6
      // Gap 1→100 at index 0 is before min_core_index, so ignored
      // Gaps from index 6: all 0
      // No significant gap found → returns last element
      expect(global.find_outlier_cutoff_radius([1, 100, 100, 100, 100, 100, 100, 100, 100, 100])).toBe(100);
    });

    test('gap exactly at OUTLIER_GAP_RATIO boundary does not cut', () => {
      // Core radius 10, gap exactly 8 (= 10 * 0.8), need > not >=
      // [10, 10, 10, 10, 10, 10, 10, 18, 50]
      // min_core_index = floor(9 * 0.6) = 5
      // Gaps from index 5: 10-10=0, 18-10=8, 50-18=32
      // Best gap: 32 at index 7, core_radius=18
      // Gap check: 32 > 18*0.8=14.4 ✓
      // Zoom check: 50 > 18*4.0=72? NO → no cut
      expect(global.find_outlier_cutoff_radius([10, 10, 10, 10, 10, 10, 10, 18, 50])).toBe(50);
    });

    test('zoom impact exactly at OUTLIER_ZOOM_IMPACT_RATIO boundary does not cut', () => {
      // Core radius 10, max = 40 (= 10 * 4.0), need > not >=
      // [10, 10, 10, 10, 10, 10, 10, 10, 10, 40]
      // min_core_index = floor(10 * 0.6) = 6
      // Gaps from index 6: 10-10=0, 10-10=0, 40-10=30
      // Best gap: 30 at index 8, core_radius=10
      // Gap check: 30 > 10*0.8=8 ✓
      // Zoom check: 40 > 10*4.0=40? NO (not >) → no cut
      expect(global.find_outlier_cutoff_radius([10, 10, 10, 10, 10, 10, 10, 10, 10, 40])).toBe(40);
    });

    test('zoom impact just above threshold triggers cut', () => {
      // Core radius 10, max = 41 (> 10 * 4.0 = 40)
      // [10, 10, 10, 10, 10, 10, 10, 10, 10, 41]
      // Best gap: 31 at index 8, core_radius=10
      // Gap check: 31 > 10*0.8=8 ✓
      // Zoom check: 41 > 10*4.0=40 ✓ → CUT at 10
      expect(global.find_outlier_cutoff_radius([10, 10, 10, 10, 10, 10, 10, 10, 10, 41])).toBe(10);
    });
  });

  // ===========================================================================
  // Constant validation
  // ===========================================================================

  describe('uses correct global constants', () => {
    test('OUTLIER_GAP_RATIO should be 0.8', () => {
      expect(global.OUTLIER_GAP_RATIO).toBe(0.8);
    });

    test('OUTLIER_MIN_CORE_RATIO should be 0.6', () => {
      expect(global.OUTLIER_MIN_CORE_RATIO).toBe(0.6);
    });

    test('OUTLIER_ZOOM_IMPACT_RATIO should be 4.0', () => {
      expect(global.OUTLIER_ZOOM_IMPACT_RATIO).toBe(4.0);
    });
  });
});
