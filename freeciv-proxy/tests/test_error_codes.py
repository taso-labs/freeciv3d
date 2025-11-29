"""
Tests for LLM WebSocket Protocol v2.0.1 Error Codes

Tests the standardized error code system as defined in the protocol spec:
- E1xx: System & Connection errors
- E22x: Input validation errors  
- E23x: Unit validation errors
- E24x: City validation errors
- E25x: Target validation errors
- E26x: Diplomacy errors
- E4xx/E5xx: Server errors

These tests use mocks and do not require a live FreeCiv server.
"""

import unittest
import sys
import os
import json
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from error_handler import (
    ErrorCode, ErrorResponse, ErrorHandler, 
    ErrorSeverity, ErrorCategory
)


class TestErrorCodeConstants(unittest.TestCase):
    """Test that error code constants match protocol spec v2.0.1"""

    def test_system_connection_error_codes(self):
        """Verify E1xx error codes for system and connection errors"""
        # E101: Missing required field
        self.assertEqual(ErrorCode.MISSING_REQUIRED_FIELD, "E101")
        
        # E102: Invalid API token
        self.assertEqual(ErrorCode.INVALID_API_TOKEN, "E102")
        
        # E103: Unknown message type
        self.assertEqual(ErrorCode.UNKNOWN_MESSAGE_TYPE, "E103")
        
        # E120: Not authenticated
        self.assertEqual(ErrorCode.NOT_AUTHENTICATED, "E120")
        
        # E121: State query failed
        self.assertEqual(ErrorCode.STATE_QUERY_FAILED, "E121")
        
        # E123: Connection lost
        self.assertEqual(ErrorCode.CONNECTION_LOST, "E123")
        
        # E130: Action validation failed
        self.assertEqual(ErrorCode.ACTION_VALIDATION_FAILED, "E130")
        
        # E131: Action execution failed
        self.assertEqual(ErrorCode.ACTION_EXECUTION_FAILED, "E131")

    def test_input_validation_error_codes(self):
        """Verify E22x error codes for input validation"""
        # E220: Missing required field (action-specific)
        self.assertEqual(ErrorCode.INPUT_MISSING_FIELD, "E220")
        
        # E221: Invalid field type
        self.assertEqual(ErrorCode.INPUT_INVALID_TYPE, "E221")
        
        # E222: Value out of range
        self.assertEqual(ErrorCode.INPUT_OUT_OF_RANGE, "E222")
        
        # E223: Invalid characters
        self.assertEqual(ErrorCode.INPUT_INVALID_CHARS, "E223")
        
        # E224: String too long
        self.assertEqual(ErrorCode.INPUT_STRING_TOO_LONG, "E224")

    def test_unit_validation_error_codes(self):
        """Verify E23x error codes for unit validation"""
        # E230: Unit not found
        self.assertEqual(ErrorCode.UNIT_NOT_FOUND, "E230")
        
        # E231: Unit not owned
        self.assertEqual(ErrorCode.UNIT_NOT_OWNED, "E231")
        
        # E232: Unit busy
        self.assertEqual(ErrorCode.UNIT_BUSY, "E232")
        
        # E233: Insufficient movement
        self.assertEqual(ErrorCode.UNIT_NO_MOVES, "E233")
        
        # E234: Missing capability
        self.assertEqual(ErrorCode.UNIT_MISSING_CAPABILITY, "E234")

    def test_city_validation_error_codes(self):
        """Verify E24x error codes for city validation"""
        # E240: City not found
        self.assertEqual(ErrorCode.CITY_NOT_FOUND, "E240")
        
        # E241: City not owned
        self.assertEqual(ErrorCode.CITY_NOT_OWNED, "E241")
        
        # E242: City at capacity
        self.assertEqual(ErrorCode.CITY_AT_CAPACITY, "E242")

    def test_target_validation_error_codes(self):
        """Verify E25x error codes for target validation"""
        # E250: Insufficient resources
        self.assertEqual(ErrorCode.INSUFFICIENT_RESOURCES, "E250")
        
        # E251: Invalid coordinates
        self.assertEqual(ErrorCode.INVALID_COORDINATES, "E251")
        
        # E252: Target out of range
        self.assertEqual(ErrorCode.TARGET_OUT_OF_RANGE, "E252")
        
        # E253: Target not visible
        self.assertEqual(ErrorCode.TARGET_NOT_VISIBLE, "E253")
        
        # E254: Terrain incompatible
        self.assertEqual(ErrorCode.TERRAIN_INCOMPATIBLE, "E254")

    def test_diplomacy_error_codes(self):
        """Verify E26x error codes for diplomacy"""
        # E260: Player not found
        self.assertEqual(ErrorCode.PLAYER_NOT_FOUND, "E260")
        
        # E261: Diplomatic action invalid
        self.assertEqual(ErrorCode.DIPLOMATIC_ACTION_INVALID, "E261")
        
        # E262: Treaty exists
        self.assertEqual(ErrorCode.TREATY_EXISTS, "E262")
        
        # E263: No pending treaty
        self.assertEqual(ErrorCode.NO_PENDING_TREATY, "E263")
        
        # E264: Invalid diplomatic state
        self.assertEqual(ErrorCode.INVALID_DIPLOMATIC_STATE, "E264")

    def test_server_error_codes(self):
        """Verify E4xx/E5xx error codes for server errors"""
        # E429: Rate limit exceeded
        self.assertEqual(ErrorCode.RATE_LIMIT_EXCEEDED, "E429")
        
        # E500: Internal server error
        self.assertEqual(ErrorCode.INTERNAL_ERROR, "E500")
        
        # E503: Query timeout
        self.assertEqual(ErrorCode.QUERY_TIMEOUT, "E503")
        
        # E999: Unknown error
        self.assertEqual(ErrorCode.UNKNOWN_ERROR, "E999")


class TestErrorResponse(unittest.TestCase):
    """Test ErrorResponse format matches protocol spec"""

    def test_error_response_structure(self):
        """Error response should have required fields per protocol"""
        response = ErrorResponse(
            code="E120",
            message="Session expired - please reauthenticate",
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.HIGH,
            details={
                "session_valid": False,
                "can_retry": True,
                "reason": "session_expired"
            }
        )
        
        result = response.to_dict()
        
        # Required fields
        self.assertEqual(result["type"], "error")
        self.assertEqual(result["code"], "E120")
        self.assertEqual(result["message"], "Session expired - please reauthenticate")
        self.assertIn("timestamp", result)
        self.assertIsInstance(result["timestamp"], float)
        
        # Details
        self.assertIn("details", result)
        self.assertEqual(result["details"]["session_valid"], False)
        self.assertEqual(result["details"]["can_retry"], True)

    def test_error_response_with_retry_after(self):
        """Rate limit error should include retry_after"""
        response = ErrorResponse(
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message="Rate limit exceeded",
            retry_after=60,
            details={
                "reason": "Request rate limit exceeded",
                "grace_period": {"violations": 4, "max_violations": 3}
            }
        )
        
        result = response.to_dict()
        
        self.assertEqual(result["retry_after"], 60)
        self.assertEqual(result["code"], "E429")

    def test_error_response_json_serialization(self):
        """Error response should serialize to valid JSON"""
        response = ErrorResponse(
            code="E223",
            message="Invalid characters in string field",
            details={
                "field": "target.name",
                "detected_patterns": ["DROP", "--"]
            }
        )
        
        json_str = response.to_json()
        parsed = json.loads(json_str)
        
        self.assertEqual(parsed["code"], "E223")
        self.assertEqual(parsed["details"]["field"], "target.name")
        self.assertIn("DROP", parsed["details"]["detected_patterns"])

    def test_error_response_minimal(self):
        """Error response with only required fields"""
        response = ErrorResponse(code="E500", message="Internal server error")
        result = response.to_dict()
        
        self.assertEqual(result["type"], "error")
        self.assertEqual(result["code"], "E500")
        self.assertEqual(result["message"], "Internal server error")
        self.assertNotIn("retry_after", result)
        self.assertNotIn("details", result)


class TestErrorHandler(unittest.TestCase):
    """Test ErrorHandler methods return correct error codes"""

    def setUp(self):
        self.handler = ErrorHandler()

    def test_handle_authentication_error_invalid_token(self):
        """Invalid token should return E102"""
        response = self.handler.handle_authentication_error(
            agent_id="test-agent",
            reason="Invalid API token provided"
        )
        
        self.assertEqual(response.code, ErrorCode.INVALID_API_TOKEN)
        self.assertIn("token", response.message.lower())

    def test_handle_authentication_error_session_expired(self):
        """Expired session should return E120"""
        response = self.handler.handle_authentication_error(
            agent_id="test-agent",
            reason="Session has expired"
        )
        
        self.assertEqual(response.code, ErrorCode.NOT_AUTHENTICATED)

    def test_handle_rate_limit_error(self):
        """Rate limit should return E429 with retry_after"""
        response = self.handler.handle_rate_limit_error(
            agent_id="test-agent",
            limit_type="requests_per_minute",
            retry_after=58
        )
        
        self.assertEqual(response.code, ErrorCode.RATE_LIMIT_EXCEEDED)
        self.assertEqual(response.retry_after, 58)

    def test_handle_validation_error_missing_field(self):
        """Missing field should return E220"""
        response = self.handler.handle_validation_error(
            agent_id="test-agent",
            error_code=ErrorCode.INPUT_MISSING_FIELD,
            message="Missing required field: unit_id",
            details={"field": "unit_id", "action_type": "unit_move"}
        )
        
        self.assertEqual(response.code, ErrorCode.INPUT_MISSING_FIELD)
        self.assertIn("unit_id", response.message)

    def test_handle_validation_error_invalid_chars(self):
        """SQL injection attempt should return E223"""
        response = self.handler.handle_validation_error(
            agent_id="test-agent",
            error_code=ErrorCode.INPUT_INVALID_CHARS,
            message="Invalid characters in string field",
            details={
                "field": "target.name",
                "reason": "SQL injection pattern detected",
                "detected_patterns": ["DROP", "--"]
            }
        )
        
        self.assertEqual(response.code, ErrorCode.INPUT_INVALID_CHARS)
        self.assertIn("DROP", response.details["detected_patterns"])

    def test_handle_validation_error_string_too_long(self):
        """Over-length string should return E224"""
        response = self.handler.handle_validation_error(
            agent_id="test-agent",
            error_code=ErrorCode.INPUT_STRING_TOO_LONG,
            message="String exceeds maximum length",
            details={
                "field": "target.name",
                "max_length": 50,
                "actual_length": 68
            }
        )
        
        self.assertEqual(response.code, ErrorCode.INPUT_STRING_TOO_LONG)
        self.assertEqual(response.details["max_length"], 50)
        self.assertEqual(response.details["actual_length"], 68)

    def test_handle_unit_not_found_error(self):
        """Unit not found should return E230"""
        response = self.handler.handle_entity_error(
            agent_id="test-agent",
            error_code=ErrorCode.UNIT_NOT_FOUND,
            message="Unit not found",
            details={"unit_id": 999}
        )
        
        self.assertEqual(response.code, ErrorCode.UNIT_NOT_FOUND)

    def test_handle_unit_not_owned_error(self):
        """Unit not owned should return E231"""
        response = self.handler.handle_entity_error(
            agent_id="test-agent",
            error_code=ErrorCode.UNIT_NOT_OWNED,
            message="Unit not owned by player",
            details={"unit_id": 42, "owner": 2, "player_id": 1}
        )
        
        self.assertEqual(response.code, ErrorCode.UNIT_NOT_OWNED)

    def test_handle_city_not_found_error(self):
        """City not found should return E240"""
        response = self.handler.handle_entity_error(
            agent_id="test-agent",
            error_code=ErrorCode.CITY_NOT_FOUND,
            message="City not found",
            details={"city_id": 999}
        )
        
        self.assertEqual(response.code, ErrorCode.CITY_NOT_FOUND)

    def test_handle_invalid_coordinates_error(self):
        """Invalid coordinates should return E251"""
        response = self.handler.handle_target_error(
            agent_id="test-agent",
            error_code=ErrorCode.INVALID_COORDINATES,
            message="Invalid coordinates",
            details={
                "x": -5,
                "y": 20,
                "reason": "negative_coordinate_not_allowed"
            }
        )
        
        self.assertEqual(response.code, ErrorCode.INVALID_COORDINATES)

    def test_handle_player_not_found_error(self):
        """Player not found should return E260"""
        response = self.handler.handle_diplomacy_error(
            agent_id="test-agent",
            error_code=ErrorCode.PLAYER_NOT_FOUND,
            message="Target player does not exist",
            details={"player_id": 99}
        )
        
        self.assertEqual(response.code, ErrorCode.PLAYER_NOT_FOUND)

    def test_handle_query_timeout_error(self):
        """Query timeout should return E503"""
        response = self.handler.handle_system_error(
            agent_id="test-agent",
            error_code=ErrorCode.QUERY_TIMEOUT,
            message="Query timeout - server did not respond in time",
            details={"timeout_seconds": 15, "query_type": "state_query"}
        )
        
        self.assertEqual(response.code, ErrorCode.QUERY_TIMEOUT)

    def test_handle_connection_lost_error(self):
        """Connection lost should return E123"""
        response = self.handler.handle_system_error(
            agent_id="test-agent",
            error_code=ErrorCode.CONNECTION_LOST,
            message="Connection to game server was lost",
            details={"can_retry": True}
        )
        
        self.assertEqual(response.code, ErrorCode.CONNECTION_LOST)


class TestErrorCodeCategories(unittest.TestCase):
    """Test error code categorization for retry logic"""

    def test_retryable_errors(self):
        """Certain errors should be marked as retryable"""
        retryable_codes = [
            ErrorCode.NOT_AUTHENTICATED,  # E120 - reconnect and reauthenticate
            ErrorCode.STATE_QUERY_FAILED,  # E121 - retry with backoff
            ErrorCode.CONNECTION_LOST,  # E123 - reconnect
            ErrorCode.RATE_LIMIT_EXCEEDED,  # E429 - wait for retry_after
            ErrorCode.INTERNAL_ERROR,  # E500 - retry with backoff
            ErrorCode.QUERY_TIMEOUT,  # E503 - retry with backoff
        ]
        
        for code in retryable_codes:
            self.assertTrue(
                ErrorCode.is_retryable(code),
                f"Error code {code} should be retryable"
            )

    def test_non_retryable_errors(self):
        """Validation errors should not be retryable"""
        non_retryable_codes = [
            ErrorCode.INPUT_MISSING_FIELD,  # E220
            ErrorCode.INPUT_INVALID_TYPE,  # E221
            ErrorCode.INPUT_OUT_OF_RANGE,  # E222
            ErrorCode.INPUT_INVALID_CHARS,  # E223
            ErrorCode.INPUT_STRING_TOO_LONG,  # E224
            ErrorCode.UNIT_NOT_FOUND,  # E230
            ErrorCode.UNIT_NOT_OWNED,  # E231
            ErrorCode.CITY_NOT_FOUND,  # E240
            ErrorCode.CITY_NOT_OWNED,  # E241
            ErrorCode.INVALID_COORDINATES,  # E251
            ErrorCode.PLAYER_NOT_FOUND,  # E260
        ]
        
        for code in non_retryable_codes:
            self.assertFalse(
                ErrorCode.is_retryable(code),
                f"Error code {code} should NOT be retryable"
            )


class TestLegacyErrorCodeMigration(unittest.TestCase):
    """Test that old error codes have been migrated or removed"""

    def test_old_codes_not_present(self):
        """Old error codes should not exist in ErrorCode class with their old meanings"""
        # These old code VALUES should no longer exist (they've been reassigned or removed)
        # Note: E101 is now MISSING_REQUIRED_FIELD (valid new code)
        # Note: E102 is now INVALID_API_TOKEN (valid new code)
        old_code_meanings = {
            "E100": "system capacity (now E500)",
            # E101 was rate limit, now is MISSING_REQUIRED_FIELD - OK
            # E102 was AUTH_SESSION_EXPIRED, now is INVALID_API_TOKEN - OK
            "E110": "auth invalid token (merged to E102)",
            "E111": "auth failed (merged to E102)",
            "E112": "session capacity (now E500)",
            "E116": "validation failed (now E130)",
            "E140": "civserver connection (now E123)",
            "E199": "system internal (now E500)",
            "E200": "security violation (now E223)",
            "E201": "injection attempt (now E223)",
            "E202": "cache poisoning (now E500)",
            "V001": "message size validation (migrated)",
            "V002": "json invalid (migrated)",
            "V003": "json structure (migrated)",
        }
        
        # Get all values from ErrorCode class
        error_code_values = [
            getattr(ErrorCode, attr) 
            for attr in dir(ErrorCode) 
            if not attr.startswith('_') and isinstance(getattr(ErrorCode, attr), str)
        ]
        
        for old_code, meaning in old_code_meanings.items():
            self.assertNotIn(
                old_code, 
                error_code_values,
                f"Old error code {old_code} ({meaning}) should have been migrated"
            )


if __name__ == '__main__':
    unittest.main()
