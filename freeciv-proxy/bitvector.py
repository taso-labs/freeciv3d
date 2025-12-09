"""BitVector parser matching JavaScript/C implementations.

This module provides a BitVector class that parses bitvector arrays from FreeCiv
network packets. The format matches both the C server implementation (bitvector.h)
and the JavaScript client implementation (bitvector.js).

Wire Format:
    Array of bytes where bit N is at raw[N//8] & (1 << (N%8))

References:
    - freeciv/freeciv/utility/bitvector.h (C implementation)
    - freeciv-web/src/main/webapp/javascript/bitvector.js (JS implementation)
    - freeciv/freeciv/common/fc_types.h (size constants: MAX_NUM_UNITS=250, MAX_NUM_BUILDINGS=200)
"""

from typing import List, Set, Optional


class BitVector:
    """Parse bitvector arrays from FreeCiv packets.

    The bitvector format uses little-endian bit ordering within each byte:
    - Bit 0 is at byte 0, bit position 0 (mask 0x01)
    - Bit 7 is at byte 0, bit position 7 (mask 0x80)
    - Bit 8 is at byte 1, bit position 0 (mask 0x01)

    This matches the C macros:
        #define _BV_BYTE_INDEX(bits)   ((bits) / 8)
        #define _BV_BITMASK(bit)       (1u << ((bit) & 0x7))
        #define BV_ISSET(bv, bit)      ((bv).vec[_BV_BYTE_INDEX(bit)] & _BV_BITMASK(bit)) != 0

    Example:
        >>> bv = BitVector([3, 128])  # Binary: 00000011, 10000000
        >>> bv.is_set(0)  # True - bit 0 is set
        True
        >>> bv.is_set(1)  # True - bit 1 is set
        True
        >>> bv.is_set(15) # True - bit 15 is set (byte 1, bit 7)
        True
        >>> bv.to_list()
        [0, 1, 15]
    """

    def __init__(self, raw: Optional[List[int]] = None):
        """Initialize BitVector from raw byte array.

        Args:
            raw: List of byte values (0-255). None or empty list creates empty bitvector.
        """
        self.raw = raw if raw else []

    def is_set(self, bit_number: int) -> bool:
        """Check if bit at position is set.

        Args:
            bit_number: Zero-indexed bit position.

        Returns:
            True if the bit is set, False otherwise.
            Returns False for out-of-range bit numbers.
        """
        if bit_number < 0:
            return False
        byte_index = bit_number // 8
        if byte_index >= len(self.raw):
            return False
        bit_mask = 1 << (bit_number % 8)
        return (self.raw[byte_index] & bit_mask) != 0

    def set(self, bit_number: int) -> None:
        """Set bit at position to True.

        Extends the underlying array if necessary.

        Args:
            bit_number: Zero-indexed bit position.
        """
        if bit_number < 0:
            return
        byte_index = bit_number // 8
        # Extend array if needed
        while byte_index >= len(self.raw):
            self.raw.append(0)
        bit_mask = 1 << (bit_number % 8)
        self.raw[byte_index] |= bit_mask

    def unset(self, bit_number: int) -> None:
        """Set bit at position to False.

        Args:
            bit_number: Zero-indexed bit position.
        """
        if bit_number < 0:
            return
        byte_index = bit_number // 8
        if byte_index >= len(self.raw):
            return
        bit_mask = 1 << (bit_number % 8)
        self.raw[byte_index] &= ~bit_mask

    def to_set(self) -> Set[int]:
        """Return set of all bit positions that are set.

        Returns:
            Set of zero-indexed bit positions that are True.
        """
        return {i for i in range(len(self.raw) * 8) if self.is_set(i)}

    def to_list(self) -> List[int]:
        """Return sorted list of all bit positions that are set.

        Returns:
            Sorted list of zero-indexed bit positions that are True.
        """
        return sorted(self.to_set())

    def __len__(self) -> int:
        """Return number of bits that can be stored."""
        return len(self.raw) * 8

    def __repr__(self) -> str:
        """Return string representation showing set bits."""
        bits = self.to_list()
        if len(bits) <= 10:
            return f"BitVector(bits={bits})"
        return f"BitVector(bits={bits[:5]}...{bits[-5:]}, count={len(bits)})"

    def to_binary_string(self) -> str:
        """Return binary string representation (for debugging).

        Returns:
            String of 1s and 0s, one per bit, in order.
        """
        return ''.join('1' if self.is_set(i) else '0' for i in range(len(self)))
