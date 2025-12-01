#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Input validation and sanitization for LLM WebSocket connections
Protocol v2.0.1 compliant input validation

This module provides:
- String length validation per field type
- Character allowlist validation
- SQL injection pattern detection
- XSS pattern detection
- Coordinate range validation
- Input sanitization

Error codes:
- E220: Missing required field
- E221: Invalid field type
- E222: Value out of range
- E223: Invalid characters (includes injection detection)
- E224: String too long
- E251: Invalid coordinate
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("freeciv-proxy")

from action_validator import ValidationResult


class InputValidationError(Exception):
    """Exception for input validation failures"""

    def __init__(self, message: str, error_code: str, field: Optional[str] = None):
        self.message = message
        self.error_code = error_code
        self.field = field
        super().__init__(message)


# Maximum input length for ReDoS protection
# Any string longer than this is rejected before regex matching
MAX_INPUT_LENGTH_FOR_REGEX = 10000


class InputValidator:
    """
    Input validation and sanitization per Protocol v2.0.1

    Validation constraints:
    - City names: max 50 chars, pattern [a-zA-Z0-9 _-]
    - Building names: max 30 chars, pattern [a-zA-Z0-9_ ]
    - Tech names: max 50 chars, pattern [a-zA-Z0-9_ ]
    - Messages: max 256 chars, pattern [a-zA-Z0-9 .,!?'"()-]
    - Agent IDs: max 50 chars, pattern [a-zA-Z0-9_-]
    - Coordinates: 0-9999, integers only

    Security:
    - Input length pre-check before regex matching prevents ReDoS attacks
    """

    # Error codes per Protocol v2.0.1
    E220_MISSING_FIELD = "E220"
    E221_INVALID_TYPE = "E221"
    E222_OUT_OF_RANGE = "E222"
    E223_INVALID_CHARS = "E223"
    E224_STRING_TOO_LONG = "E224"
    E251_INVALID_COORDINATE = "E251"

    # Field validation constraints
    FIELD_CONSTRAINTS = {
        "city_name": {
            "max_length": 50,
            "pattern": r"^[a-zA-Z0-9 _\-]+$",
            "description": "City names must be alphanumeric with spaces, underscores, hyphens",
        },
        "building_name": {
            "max_length": 30,
            "pattern": r"^[a-zA-Z0-9_ ]+$",
            "description": "Building names must be alphanumeric with spaces, underscores",
        },
        "tech_name": {
            "max_length": 50,
            "pattern": r"^[a-zA-Z0-9_ ]+$",
            "description": "Tech names must be alphanumeric with spaces, underscores",
        },
        "message": {
            "max_length": 256,
            "pattern": r'^[a-zA-Z0-9 .,!?\'"()\-]*$',
            "description": "Messages may contain alphanumeric and basic punctuation",
        },
        "agent_id": {
            "max_length": 50,
            "pattern": r"^[a-zA-Z0-9_\-]+$",
            "description": "Agent IDs must be alphanumeric with underscores, hyphens",
        },
        "unit_name": {
            "max_length": 50,
            "pattern": r"^[a-zA-Z0-9_ ]+$",
            "description": "Unit names must be alphanumeric with spaces, underscores",
        },
        "improvement_name": {
            "max_length": 30,
            "pattern": r"^[a-zA-Z0-9_ ]+$",
            "description": "Improvement names must be alphanumeric with spaces, underscores",
        },
        "nation_name": {
            "max_length": 50,
            "pattern": r"^[a-zA-Z0-9_ ]+$",
            "description": "Nation names must be alphanumeric with spaces, underscores",
        },
    }

    # SQL injection patterns to detect
    # NOTE: These patterns are only applied to free-text fields like 'message'.
    # Fields with character allowlists (city_name, building_name, etc.) are already
    # protected and don't need injection detection, which could cause false positives.
    SQL_INJECTION_PATTERNS = [
        r"\bSELECT\b.*\bFROM\b",  # SELECT ... FROM (more specific)
        r"\bDROP\b.*\bTABLE\b",  # DROP TABLE (more specific)
        r"\bINSERT\b.*\bINTO\b",  # INSERT INTO (more specific)
        r"\bUPDATE\b.*\bSET\b",  # UPDATE ... SET (more specific)
        r"\bDELETE\b.*\bFROM\b",  # DELETE FROM (more specific)
        r"\bUNION\b.*\bSELECT\b",  # UNION SELECT (more specific)
        r"'\s*OR\s+'?\d+\s*=\s*'?\d+",  # ' OR '1'='1' style
        r'"\s*OR\s+"?\d+\s*=\s*"?\d+',  # " OR "1"="1" style
        r"'\s*AND\s+'?\d+\s*=\s*'?\d+",  # ' AND '1'='1' style
        r'"\s*AND\s+"?\d+\s*=\s*"?\d+',  # " AND "1"="1" style
        r"'--",  # SQL comment after quote (injection attempt)
        r"/\*.*\*/",  # Block comment (injection attempt)
        r";\s*(DROP|SELECT|INSERT|UPDATE|DELETE)\b",  # Chained SQL commands
        r"\bEXEC(UTE)?\s+\w+",  # EXEC/EXECUTE procedure
        r"\bxp_\w+",  # Extended stored procedures
        r"\bsp_\w+",  # System stored procedures
    ]

    # XSS patterns to detect and strip
    XSS_PATTERNS = [
        r"<script\b[^>]*>",
        r"</script>",
        r"javascript:",
        r"on\w+\s*=",  # onclick=, onerror=, etc.
        r"<iframe\b",
        r"<object\b",
        r"<embed\b",
        r"<svg\b[^>]*onload",
        r"<img\b[^>]*onerror",
        r"expression\s*\(",
        r'url\s*\(\s*["\']?\s*data:',
    ]

    # Coordinate validation
    COORDINATE_MIN = 0
    COORDINATE_MAX = 9999

    # Entity ID validation
    ENTITY_ID_MAX = 999999

    def __init__(self):
        # Compile regex patterns for performance
        # Combine SQL patterns into single regex for O(1) matching instead of O(n)
        self._sql_combined_pattern = re.compile(
            "|".join(f"({p})" for p in self.SQL_INJECTION_PATTERNS), re.IGNORECASE
        )
        # Combine XSS patterns into single regex for O(1) matching
        self._xss_combined_pattern = re.compile(
            "|".join(f"({p})" for p in self.XSS_PATTERNS), re.IGNORECASE
        )

        # Statistics
        self._stats = {
            'validations': 0,
            'failures': 0,
            'sql_injections_blocked': 0,
            'xss_blocked': 0,
        }

    def validate_string_field(self, value, field_type: str) -> ValidationResult:
        """
        Validate a string field against its constraints

        Args:
            value: The string value to validate
            field_type: The type of field (city_name, building_name, etc.)

        Returns:
            ValidationResult with is_valid, error_code, error_message
        """
        self._stats['validations'] += 1

        if value is None:
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E220_MISSING_FIELD,
                error_message=f"Missing required field: {field_type}"
            )

        if not isinstance(value, str):
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E221_INVALID_TYPE,
                error_message=f"Field {field_type} must be a string, got {type(value).__name__}"
            )

        constraints = self.FIELD_CONSTRAINTS.get(field_type)
        if not constraints:
            # Unknown field type - apply generic validation
            return self._validate_generic_string(value, field_type)

        # Length check
        max_length = constraints.get('max_length', 1000)
        if len(value) > max_length:
            self._stats["failures"] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E224_STRING_TOO_LONG,
                error_message=f"Field {field_type} exceeds max length: {len(value)} > {max_length}",
            )

        # Pattern check
        pattern = constraints.get("pattern")
        if pattern and not re.match(pattern, value):
            self._stats["failures"] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E223_INVALID_CHARS,
                error_message=f"Field {field_type} contains invalid characters. {constraints.get('description', '')}",
            )

        return ValidationResult(is_valid=True)

    def _validate_generic_string(self, value: str, field_type: str) -> ValidationResult:
        """Validate an unknown string field with generic constraints"""
        if len(value) > 1000:
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E224_STRING_TOO_LONG,
                error_message=f"Field {field_type} exceeds generic max length: {len(value)} > 1000"
            )
        return ValidationResult(is_valid=True)

    def validate_coordinate(self, value, field_name: str = "coordinate") -> ValidationResult:
        """
        Validate a coordinate value (x, y, tile index)

        Coordinates must be:
        - Integers
        - In range 0-9999
        """
        self._stats['validations'] += 1

        if value is None:
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E220_MISSING_FIELD,
                error_message=f"Missing required coordinate: {field_name}"
            )

        # In Python, bool is a subclass of int, so isinstance(True, int) returns True.
        # We must explicitly exclude booleans to ensure coordinates are actual integers.
        if not isinstance(value, int) or isinstance(value, bool):
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E221_INVALID_TYPE,
                error_message=f"Coordinate {field_name} must be an integer, got {type(value).__name__}"
            )

        if value < self.COORDINATE_MIN or value > self.COORDINATE_MAX:
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E251_INVALID_COORDINATE,
                error_message=f"Coordinate {field_name} out of range: {value} (must be {self.COORDINATE_MIN}-{self.COORDINATE_MAX})"
            )

        return ValidationResult(is_valid=True)

    def detect_sql_injection(self, value: str) -> ValidationResult:
        """
        Detect SQL injection patterns in input

        Returns:
            ValidationResult - invalid if SQL injection detected
        """
        if not isinstance(value, str):
            return ValidationResult(is_valid=True)

        # ReDoS protection: reject overly long inputs before regex matching
        if len(value) > MAX_INPUT_LENGTH_FOR_REGEX:
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E224_STRING_TOO_LONG,
                error_message=f"Input too long for security scanning: {len(value)} > {MAX_INPUT_LENGTH_FOR_REGEX}"
            )

        match = self._sql_combined_pattern.search(value)
        if match:
            self._stats['sql_injections_blocked'] += 1
            matched_pattern = match.group(0)
            logger.warning(f"SQL injection attempt blocked: {matched_pattern}")
            return ValidationResult(
                is_valid=False,
                error_code=self.E223_INVALID_CHARS,
                error_message=f"Potential SQL injection detected"
            )

        return ValidationResult(is_valid=True)

    def detect_xss(self, value: str) -> ValidationResult:
        """
        Detect XSS patterns in input

        Returns:
            ValidationResult - invalid if XSS detected
        """
        if not isinstance(value, str):
            return ValidationResult(is_valid=True)

        # ReDoS protection: reject overly long inputs before regex matching
        if len(value) > MAX_INPUT_LENGTH_FOR_REGEX:
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E224_STRING_TOO_LONG,
                error_message=f"Input too long for security scanning: {len(value)} > {MAX_INPUT_LENGTH_FOR_REGEX}"
            )

        match = self._xss_combined_pattern.search(value)
        if match:
            self._stats["xss_blocked"] += 1
            matched_pattern = match.group(0)
            logger.warning(f"XSS attempt blocked: {matched_pattern}")
            return ValidationResult(
                is_valid=False,
                error_code=self.E223_INVALID_CHARS,
                error_message=f"Potential XSS detected",
            )

        return ValidationResult(is_valid=True)

    def validate_entity_id(
        self, value, field_name: str = "entity_id"
    ) -> ValidationResult:
        """
        Validate an entity ID (unit_id, city_id, player_id, etc.)

        Entity IDs must be:
        - Non-negative integers
        - In reasonable range (0-999999)
        """
        self._stats['validations'] += 1

        if value is None:
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E220_MISSING_FIELD,
                error_message=f"Missing required entity ID: {field_name}"
            )

        # In Python, bool is a subclass of int, so isinstance(True, int) returns True.
        # We must explicitly exclude booleans to ensure entity IDs are actual integers.
        if not isinstance(value, int) or isinstance(value, bool):
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E221_INVALID_TYPE,
                error_message=f"Entity ID {field_name} must be an integer, got {type(value).__name__}"
            )

        if value < 0 or value > self.ENTITY_ID_MAX:
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E222_OUT_OF_RANGE,
                error_message=f"Entity ID {field_name} out of range: {value} (must be 0-{self.ENTITY_ID_MAX})"
            )

        return ValidationResult(is_valid=True)

    def validate_action_params(self, action_type: str, params: dict) -> ValidationResult:
        """
        Validate action parameters based on action type

        Applies field-specific validation rules based on the action type
        """
        self._stats['validations'] += 1

        if not isinstance(params, dict):
            self._stats['failures'] += 1
            return ValidationResult(
                is_valid=False,
                error_code=self.E221_INVALID_TYPE,
                error_message="Action parameters must be a dictionary"
            )

        # Validate common entity ID fields
        for id_field in ['unit_id', 'city_id', 'target_id', 'player_id']:
            if id_field in params:
                result = self.validate_entity_id(params[id_field], id_field)
                if not result.is_valid:
                    return result

        # Validate coordinates
        for coord_field in ['x', 'y', 'dest_x', 'dest_y', 'tile']:
            if coord_field in params:
                result = self.validate_coordinate(params[coord_field], coord_field)
                if not result.is_valid:
                    return result

        # Validate string fields based on action type
        if action_type in ['unit_found_city', 'unit_build_city']:
            if 'city_name' in params:
                result = self.validate_string_field(params['city_name'], 'city_name')
                if not result.is_valid:
                    return result
                # Also check for injection
                result = self.detect_sql_injection(params['city_name'])
                if not result.is_valid:
                    return result
                result = self.detect_xss(params['city_name'])
                if not result.is_valid:
                    return result

        if action_type in ['city_production']:
            if 'building' in params:
                result = self.validate_string_field(params['building'], 'building_name')
                if not result.is_valid:
                    return result

        if action_type in ['tech_research']:
            if 'tech' in params:
                result = self.validate_string_field(params['tech'], 'tech_name')
                if not result.is_valid:
                    return result

        if action_type in ['diplomacy_message']:
            if 'message' in params:
                result = self.validate_string_field(params['message'], 'message')
                if not result.is_valid:
                    return result
                result = self.detect_sql_injection(params['message'])
                if not result.is_valid:
                    return result
                result = self.detect_xss(params['message'])
                if not result.is_valid:
                    return result

        return ValidationResult(is_valid=True)

    def get_stats(self) -> dict:
        """Get validation statistics"""
        return dict(self._stats)

    def reset_stats(self):
        """Reset validation statistics"""
        self._stats = {
            'validations': 0,
            'failures': 0,
            'sql_injections_blocked': 0,
            'xss_blocked': 0,
        }


# Singleton instance for global use
_input_validator = None

def get_input_validator() -> InputValidator:
    """Get or create the singleton InputValidator instance"""
    global _input_validator
    if _input_validator is None:
        _input_validator = InputValidator()
    return _input_validator
