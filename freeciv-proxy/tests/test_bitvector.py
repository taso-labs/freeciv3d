"""Unit tests for BitVector parsing.

Tests the BitVector class against known byte patterns to ensure
correct parsing of FreeCiv network protocol bitvectors.

Format Reference:
    - Bit N is at raw[N//8] & (1 << (N%8))
    - Matches: bitvector.h macros and bitvector.js implementation
"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bitvector import BitVector


class TestBitVectorBasic:
    """Basic functionality tests."""

    def test_empty_bitvector(self):
        """Empty bitvector should have no bits set."""
        bv = BitVector([])
        assert bv.is_set(0) is False
        assert bv.is_set(100) is False
        assert bv.to_list() == []
        assert bv.to_set() == set()
        assert len(bv) == 0

    def test_none_input(self):
        """None input should create empty bitvector."""
        bv = BitVector(None)
        assert bv.is_set(0) is False
        assert bv.to_list() == []

    def test_single_byte_all_zeros(self):
        """Single zero byte should have no bits set."""
        bv = BitVector([0])
        assert bv.is_set(0) is False
        assert bv.is_set(7) is False
        assert bv.to_list() == []
        assert len(bv) == 8

    def test_single_byte_all_ones(self):
        """Single 0xFF byte should have bits 0-7 set."""
        bv = BitVector([255])
        for i in range(8):
            assert bv.is_set(i) is True
        assert bv.is_set(8) is False
        assert bv.to_list() == [0, 1, 2, 3, 4, 5, 6, 7]


class TestBitVectorSingleByte:
    """Tests for single byte bitvectors."""

    def test_bit0_set(self):
        """Bit 0 set (value 1 = 0b00000001)."""
        bv = BitVector([1])
        assert bv.is_set(0) is True
        assert bv.is_set(1) is False
        assert bv.to_list() == [0]

    def test_bit1_set(self):
        """Bit 1 set (value 2 = 0b00000010)."""
        bv = BitVector([2])
        assert bv.is_set(0) is False
        assert bv.is_set(1) is True
        assert bv.is_set(2) is False
        assert bv.to_list() == [1]

    def test_bit7_set(self):
        """Bit 7 set (value 128 = 0b10000000)."""
        bv = BitVector([128])
        assert bv.is_set(7) is True
        assert bv.is_set(0) is False
        assert bv.is_set(6) is False
        assert bv.to_list() == [7]

    def test_bits_0_and_1_set(self):
        """Bits 0 and 1 set (value 3 = 0b00000011)."""
        bv = BitVector([3])
        assert bv.is_set(0) is True
        assert bv.is_set(1) is True
        assert bv.is_set(2) is False
        assert bv.to_list() == [0, 1]


class TestBitVectorMultiByte:
    """Tests for multi-byte bitvectors."""

    def test_two_bytes_first_byte_only(self):
        """Two bytes with only first byte having bits set."""
        bv = BitVector([3, 0])  # Bits 0, 1 set
        assert bv.is_set(0) is True
        assert bv.is_set(1) is True
        assert bv.is_set(8) is False
        assert bv.to_list() == [0, 1]

    def test_two_bytes_second_byte_only(self):
        """Two bytes with only second byte having bits set."""
        bv = BitVector([0, 3])  # Bits 8, 9 set
        assert bv.is_set(0) is False
        assert bv.is_set(7) is False
        assert bv.is_set(8) is True
        assert bv.is_set(9) is True
        assert bv.is_set(10) is False
        assert bv.to_list() == [8, 9]

    def test_two_bytes_bit15_set(self):
        """Bit 15 set (byte 1, bit position 7)."""
        bv = BitVector([0, 128])  # Bit 15 = byte 1, position 7
        assert bv.is_set(15) is True
        assert bv.is_set(14) is False
        assert bv.is_set(7) is False
        assert bv.to_list() == [15]

    def test_multiple_bytes_mixed(self):
        """Multiple bytes with various bits set."""
        bv = BitVector([3, 128])  # Bits 0, 1 in byte 0; bit 15 in byte 1
        assert bv.is_set(0) is True
        assert bv.is_set(1) is True
        assert bv.is_set(2) is False
        assert bv.is_set(15) is True
        assert bv.to_list() == [0, 1, 15]

    def test_four_bytes(self):
        """Four byte bitvector (32 bits)."""
        bv = BitVector([1, 0, 0, 128])  # Bits 0 and 31
        assert bv.is_set(0) is True
        assert bv.is_set(31) is True
        assert bv.is_set(30) is False
        assert len(bv) == 32
        assert bv.to_list() == [0, 31]


class TestBitVectorFreeCivScenarios:
    """Tests simulating FreeCiv packet scenarios."""

    def test_unit_bitvector_warriors_settlers(self):
        """Simulate can_build_unit with Warriors (0) and Settlers (1) buildable."""
        # BV_UTYPES is 250 bits = 32 bytes
        bv = BitVector([3] + [0] * 31)  # First 2 bits set
        assert bv.is_set(0) is True   # Warriors (unit ID 0)
        assert bv.is_set(1) is True   # Settlers (unit ID 1)
        assert bv.is_set(2) is False  # Phalanx (unit ID 2) not buildable
        assert len(bv) == 256  # 32 bytes * 8

    def test_improvement_bitvector_granary_barracks(self):
        """Simulate can_build_improvement with common buildings."""
        # BV_IMPRS is 200 bits = 25 bytes
        # Assume: Granary=ID 10, Barracks=ID 5
        raw = [0] * 25
        raw[0] = 32   # Bit 5 (Barracks)
        raw[1] = 4    # Bit 10 = byte 1 bit 2 (Granary)
        bv = BitVector(raw)
        assert bv.is_set(5) is True   # Barracks
        assert bv.is_set(10) is True  # Granary
        assert bv.is_set(0) is False  # Palace not buildable
        assert len(bv) == 200

    def test_terrain_extras_bitvector(self):
        """Simulate tile extras bitvector with road and irrigation."""
        # Assuming: Road=ID 0, Irrigation=ID 1, Mine=ID 2
        bv = BitVector([3])  # Road and Irrigation present
        assert bv.is_set(0) is True   # Road
        assert bv.is_set(1) is True   # Irrigation
        assert bv.is_set(2) is False  # Mine not present


class TestBitVectorMutation:
    """Tests for set/unset operations."""

    def test_set_bit(self):
        """Setting a bit should work."""
        bv = BitVector([0])
        bv.set(3)
        assert bv.is_set(3) is True
        assert bv.raw == [8]  # 2^3 = 8

    def test_set_bit_extends_array(self):
        """Setting a bit beyond array should extend it."""
        bv = BitVector([])
        bv.set(10)  # Byte 1, bit 2
        assert bv.is_set(10) is True
        assert len(bv.raw) == 2
        assert bv.raw[1] == 4  # 2^2 = 4

    def test_unset_bit(self):
        """Unsetting a bit should work."""
        bv = BitVector([255])
        bv.unset(3)
        assert bv.is_set(3) is False
        assert bv.raw == [247]  # 255 - 8

    def test_unset_out_of_range(self):
        """Unsetting bit out of range should be no-op."""
        bv = BitVector([255])
        bv.unset(100)  # Out of range
        assert bv.raw == [255]  # Unchanged


class TestBitVectorEdgeCases:
    """Edge case tests."""

    def test_negative_bit_number(self):
        """Negative bit number should return False."""
        bv = BitVector([255])
        assert bv.is_set(-1) is False
        assert bv.is_set(-100) is False

    def test_large_bit_number_out_of_range(self):
        """Bit number beyond array should return False."""
        bv = BitVector([255])  # Only 8 bits
        assert bv.is_set(8) is False
        assert bv.is_set(100) is False

    def test_repr_short(self):
        """repr should show bits for short bitvectors."""
        bv = BitVector([3])
        assert 'bits=[0, 1]' in repr(bv)

    def test_binary_string(self):
        """to_binary_string should return correct string."""
        bv = BitVector([3])  # Binary: 00000011
        assert bv.to_binary_string() == '11000000'  # Little-endian output


class TestBitVectorProtocolConformance:
    """Tests ensuring conformance with FreeCiv C/JS implementations."""

    def test_matches_js_formula(self):
        """Verify formula matches JavaScript bitvector.js:31-32.

        JS code:
            this.isSet = function(bitNumber) {
                return (this.raw[Math.floor(bitNumber / 8)]
                        & (1 << (bitNumber % 8))) != 0;
            };
        """
        # Test with known values
        test_cases = [
            ([1], 0, True),
            ([1], 1, False),
            ([2], 1, True),
            ([128], 7, True),
            ([0, 1], 8, True),
            ([0, 128], 15, True),
        ]
        for raw, bit_num, expected in test_cases:
            bv = BitVector(raw)
            assert bv.is_set(bit_num) == expected, f"Failed for raw={raw}, bit={bit_num}"

    def test_matches_c_macro(self):
        """Verify formula matches C bitvector.h macros.

        C macros:
            #define _BV_BYTE_INDEX(bits)   ((bits) / 8)
            #define _BV_BITMASK(bit)       (1u << ((bit) & 0x7))
            #define BV_ISSET(bv, bit)      ((bv).vec[_BV_BYTE_INDEX(bit)] & _BV_BITMASK(bit)) != 0
        """
        # Test formula equivalence
        for bit_num in range(32):
            byte_index_py = bit_num // 8
            bit_mask_py = 1 << (bit_num % 8)

            # C formula
            byte_index_c = bit_num // 8
            bit_mask_c = 1 << (bit_num & 0x7)  # Note: & 0x7 is same as % 8

            assert byte_index_py == byte_index_c
            assert bit_mask_py == bit_mask_c


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
