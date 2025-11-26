#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tests for probability encoding utilities (protocol v2.0)
Tests conversion between server format (0-200) and percentage format
"""

import pytest

# Import the probability utils module
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from probability_utils import (
    encode_probability,
    encode_probability_from_percent,
    decode_probability_to_percent,
    is_certain,
    is_impossible,
    is_unknown
)

# Define constants for testing
PROB_IMPOSSIBLE = 0
PROB_CERTAIN = 200
PROB_COMPUTING = 253
PROB_UNKNOWN = 254


class TestProbabilityUtils:
    """Test suite for probability encoding/decoding"""

    def test_encode_impossible(self):
        """Test encoding impossible probability (0)"""
        result = encode_probability(0)
        assert result == PROB_IMPOSSIBLE
        assert result == 0

    def test_encode_certain(self):
        """Test encoding certain probability (200)"""
        result = encode_probability(200)
        assert result == PROB_CERTAIN
        assert result == 200

    def test_encode_fifty_percent_from_server(self):
        """Test encoding 50% probability from server value"""
        result = encode_probability(100)
        assert result == 100

    def test_encode_quarter_percent_from_server(self):
        """Test encoding 25% probability from server value"""
        result = encode_probability(50)
        assert result == 50

    def test_encode_from_percent(self):
        """Test encoding from percentage values"""
        assert encode_probability_from_percent(0) == 0
        assert encode_probability_from_percent(50) == 100
        assert encode_probability_from_percent(100) == 200

    def test_encode_half_percent_precision(self):
        """Test encoding with half-percent precision (0.5%)"""
        result = encode_probability_from_percent(0.5)
        assert result == 1

    def test_encode_unknown_special(self):
        """Test encoding UNKNOWN special value"""
        result = encode_probability(None)
        assert result == PROB_UNKNOWN
        assert result == 254

    def test_encode_clamping_above(self):
        """Test that values above 200 are clamped"""
        result = encode_probability(300)
        assert result == PROB_CERTAIN
        assert result == 200

    def test_encode_clamping_below(self):
        """Test that negative values are clamped"""
        result = encode_probability(-10)
        assert result == PROB_IMPOSSIBLE
        assert result == 0

    def test_decode_impossible(self):
        """Test decoding impossible probability"""
        result = decode_probability_to_percent(0)
        assert result == 0.0

    def test_decode_certain(self):
        """Test decoding certain probability"""
        result = decode_probability_to_percent(200)
        assert result == 100.0

    def test_decode_fifty_percent(self):
        """Test decoding 50% probability"""
        result = decode_probability_to_percent(100)
        assert result == 50.0

    def test_decode_quarter_percent(self):
        """Test decoding 25% probability"""
        result = decode_probability_to_percent(50)
        assert result == 25.0

    def test_decode_half_percent_precision(self):
        """Test decoding half-percent precision"""
        result = decode_probability_to_percent(1)
        assert result == 0.5

    def test_decode_computing_special(self):
        """Test decoding COMPUTING special value"""
        result = decode_probability_to_percent(253)
        assert result == -1.0  # Special value indicator

    def test_decode_unknown_special(self):
        """Test decoding UNKNOWN special value"""
        result = decode_probability_to_percent(254)
        assert result == -1.0  # Special value indicator

    def test_encode_decode_roundtrip(self):
        """Test that encoding and decoding are inverse operations"""
        test_percentages = [0, 0.5, 1, 5, 10, 25, 50, 75, 90, 99, 99.5, 100]
        
        for percent in test_percentages:
            encoded = encode_probability_from_percent(percent)
            decoded = decode_probability_to_percent(encoded)
            assert abs(decoded - percent) < 0.01, f"Roundtrip failed for {percent}%"

    def test_encode_fractional_percentages(self):
        """Test encoding fractional percentages"""
        # 33.5% should encode to 67
        result = encode_probability_from_percent(33.5)
        assert result == 67
        
        # 66.5% should encode to 133
        result = encode_probability_from_percent(66.5)
        assert result == 133

    def test_decode_boundary_values(self):
        """Test decoding boundary values"""
        # Just below COMPUTING
        result = decode_probability_to_percent(252)
        assert result == 100.0  # Clamped to maximum (200 -> 100%)
        
        # COMPUTING
        result = decode_probability_to_percent(253)
        assert result == -1.0
        
        # UNKNOWN
        result = decode_probability_to_percent(254)
        assert result == -1.0

    def test_encode_zero_point_five(self):
        """Test encoding 0.5% (minimum non-zero probability)"""
        result = encode_probability_from_percent(0.5)
        assert result == 1
        
        decoded = decode_probability_to_percent(1)
        assert decoded == 0.5

    def test_encode_ninety_nine_point_five(self):
        """Test encoding 99.5% (maximum non-certain probability)"""
        result = encode_probability_from_percent(99.5)
        assert result == 199
        
        decoded = decode_probability_to_percent(199)
        assert decoded == 99.5

    def test_is_certain_helper(self):
        """Test is_certain helper function"""
        assert is_certain(200) is True
        assert is_certain(199) is False
        assert is_certain(0) is False

    def test_is_impossible_helper(self):
        """Test is_impossible helper function"""
        assert is_impossible(0) is True
        assert is_impossible(1) is False
        assert is_impossible(200) is False

    def test_is_unknown_helper(self):
        """Test is_unknown helper function"""
        assert is_unknown(253) is True
        assert is_unknown(254) is True
        assert is_unknown(100) is False

    def test_protocol_compliance(self):
        """Test that encoding produces protocol-compliant values"""
        # All encoded values should be in range [0, 200] or special [253, 254]
        test_values = [0, 50, 100, 150, 200]
        
        for value in test_values:
            encoded = encode_probability(value)
            assert 0 <= encoded <= 200, f"Value {value} encoded to out-of-range {encoded}"

    def test_batch_encoding(self):
        """Test encoding multiple probabilities"""
        probabilities = [0, 25, 50, 75, 100]
        encoded = [encode_probability_from_percent(p) for p in probabilities]
        expected = [0, 50, 100, 150, 200]
        
        assert encoded == expected

    def test_batch_decoding(self):
        """Test decoding multiple probabilities"""
        encoded_values = [0, 50, 100, 150, 200]
        decoded = [decode_probability_to_percent(v) for v in encoded_values]
        expected = [0.0, 25.0, 50.0, 75.0, 100.0]
        
        assert decoded == expected
