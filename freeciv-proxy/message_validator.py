#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Message validation system for LLM WebSocket connections
Provides input validation, size limits, and schema validation

Error codes per LLM WebSocket Protocol v2.0.1:
- E101: Missing required field
- E103: Unknown message type  
- E220: Missing required field (action-specific)
- E221: Invalid field type
- E222: Value out of range
- E223: Invalid characters
- E224: String too long
"""

import json
import logging
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger("freeciv-proxy")


# Protocol v2.0.1 Error Codes
class ErrorCodes:
    """Error codes for message validation"""
    MISSING_REQUIRED_FIELD = "E101"
    UNKNOWN_MESSAGE_TYPE = "E103"
    INPUT_MISSING_FIELD = "E220"
    INPUT_INVALID_TYPE = "E221"
    INPUT_OUT_OF_RANGE = "E222"
    INPUT_INVALID_CHARS = "E223"
    INPUT_STRING_TOO_LONG = "E224"


class ValidationError(Exception):
    """Custom exception for validation errors"""
    def __init__(self, message: str, error_code: str):
        self.message = message
        self.error_code = error_code
        super().__init__(message)

class MessageType(Enum):
    """Supported message types"""
    LLM_CONNECT = "llm_connect"
    STATE_QUERY = "state_query"
    ACTION = "action"
    PING = "ping"
    PLAYER_READY = "player_ready"
    CONN_PING = "conn_ping"  # FreeCiv keepalive ping from civserver
    CONN_PONG = "conn_pong"  # FreeCiv keepalive pong response
    UNIT_ACTIONS_QUERY = "unit_actions_query"  # Query available actions for a unit
    CITY_ACTIONS_QUERY = "city_actions_query"  # Query available actions for a city
    CHAT = "chat"  # Send chat message/command to game server

class MessageValidator:
    """
    Validates WebSocket messages for security and structure
    Prevents DoS attacks via large payloads or deep JSON structures
    """

    # Security limits
    MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB default
    MAX_JSON_DEPTH = 10
    MAX_STRING_LENGTH = 1000
    MAX_ARRAY_LENGTH = 100
    MAX_OBJECT_KEYS = 50

    # Message schemas
    SCHEMAS = {
        MessageType.LLM_CONNECT: {
            "required_fields": ["type", "agent_id", "api_token"],
            "optional_fields": [
                "port",
                "nation",
                "leader_name",
                "game_id",
                "auto_ready",
                "trace_context",  # OpenTelemetry trace propagation
                "game_config",  # Custom game settings (map size, landmass, etc.)
            ],
            "field_types": {
                "type": str,
                "agent_id": str,
                "api_token": str,
                "port": int,
                "nation": str,
                "leader_name": str,
                "game_id": str,
                "trace_context": dict,
                "game_config": dict,
            },
            "field_constraints": {
                "agent_id": {"max_length": 50, "pattern": r"^[a-zA-Z0-9_-]+$"},
                "api_token": {"min_length": 10, "max_length": 100},
                "port": {"min_value": 1000, "max_value": 65535},
                "game_id": {"max_length": 64, "pattern": r"^[a-zA-Z0-9_-]+$"},
                "nation": {"max_length": 50},
                "leader_name": {"max_length": 100},
                "trace_context": {"max_keys": 5},  # trace_id, span_id, trace_flags, trace_state
                "game_config": {"max_keys": 20},  # Limit config keys to prevent oversized payloads
            },
        },
        MessageType.STATE_QUERY: {
            "required_fields": ["type"],
            "optional_fields": ["format", "include_actions", "player_id", "trace_context", "correlation_id"],
            "field_types": {
                "type": str,
                "format": str,
                "include_actions": bool,
                "player_id": int,
                "trace_context": dict,
                "correlation_id": str,
            },
            "field_constraints": {
                "format": {"allowed_values": ["full", "delta", "llm_optimized"]},
                "player_id": {"min_value": 1, "max_value": 8},
                "trace_context": {"max_keys": 5},
                "correlation_id": {"max_length": 64, "pattern": r"^[a-zA-Z0-9_-]+$"},
            },
        },
        MessageType.ACTION: {
            "required_fields": ["type", "action"],
            "optional_fields": ["timestamp", "trace_context", "correlation_id"],
            "field_types": {
                "type": str,
                "action": dict,
                "timestamp": (int, float),
                "trace_context": dict,
                "correlation_id": str,
            },
            "field_constraints": {
                "action": {"max_keys": 20},
                "trace_context": {"max_keys": 5},
                "correlation_id": {"max_length": 64, "pattern": r"^[a-zA-Z0-9_-]+$"},
            },
        },
        MessageType.PING: {
            "required_fields": ["type"],
            "optional_fields": ["timestamp", "trace_context"],
            "field_types": {
                "type": str,
                "timestamp": (int, float),
                "trace_context": dict,
            },
            "field_constraints": {
                "trace_context": {"max_keys": 5},
            },
        },
        MessageType.PLAYER_READY: {
            "required_fields": ["type"],
            "optional_fields": ["trace_context"],
            "field_types": {"type": str, "trace_context": dict},
            "field_constraints": {"trace_context": {"max_keys": 5}},
        },
        MessageType.CONN_PING: {
            "required_fields": ["type"],
            "optional_fields": ["trace_context"],
            "field_types": {"type": str, "trace_context": dict},
            "field_constraints": {"trace_context": {"max_keys": 5}},
        },
        MessageType.CONN_PONG: {
            "required_fields": ["type"],
            "optional_fields": ["trace_context"],
            "field_types": {"type": str, "trace_context": dict},
            "field_constraints": {"trace_context": {"max_keys": 5}},
        },
        MessageType.UNIT_ACTIONS_QUERY: {
            "required_fields": ["type", "agent_id"],
            "optional_fields": ["timestamp", "correlation_id", "data", "unit_ids", "trace_context"],
            "field_types": {
                "type": str,
                "agent_id": str,
                "data": dict,
                "unit_ids": list,
                "timestamp": (int, float),
                "correlation_id": str,
                "trace_context": dict,
            },
            "field_constraints": {
                "correlation_id": {"max_length": 64, "pattern": r"^[a-zA-Z0-9_-]+$"},
                "data": {"required_keys": ["unit_ids"]},
                "trace_context": {"max_keys": 5},
            },
        },
        MessageType.CITY_ACTIONS_QUERY: {
            "required_fields": ["type", "data"],
            "optional_fields": ["agent_id", "timestamp", "correlation_id", "trace_context"],
            "field_types": {
                "type": str,
                "data": dict,
                "agent_id": str,
                "timestamp": (int, float),
                "correlation_id": str,
                "trace_context": dict,
            },
            "field_constraints": {
                "correlation_id": {"max_length": 64, "pattern": r"^[a-zA-Z0-9_-]+$"},
                "data": {"required_keys": ["city_ids"]},
                "trace_context": {"max_keys": 5},
            },
        },
        MessageType.CHAT: {
            "required_fields": ["type"],
            "optional_fields": [
                "message",
                "data",
                "agent_id",
                "timestamp",
                "correlation_id",
                "trace_context",
            ],
            "field_types": {
                "type": str,
                "message": str,
                "data": dict,
                "agent_id": str,
                "timestamp": (int, float),
                "correlation_id": str,
                "trace_context": dict,
            },
            "field_constraints": {
                "message": {"max_length": 500},
                "correlation_id": {"max_length": 64, "pattern": r"^[a-zA-Z0-9_-]+$"},
                "trace_context": {"max_keys": 5},
            },
        },
    }

    def __init__(self, max_message_size: int = None):
        self.max_message_size = max_message_size or self.MAX_MESSAGE_SIZE
        self.validation_stats = {
            'total_messages': 0,
            'valid_messages': 0,
            'validation_errors': 0,
            'errors_by_type': {}
        }

    def validate_message(self, raw_message: str) -> Dict[str, Any]:
        """
        Validate a raw WebSocket message

        Args:
            raw_message: Raw message string

        Returns:
            Parsed and validated message dictionary

        Raises:
            ValidationError: If validation fails
        """
        self.validation_stats['total_messages'] += 1

        try:
            # Size validation
            self._validate_message_size(raw_message)

            # JSON parsing with depth validation
            message = self._parse_json_safely(raw_message)

            # Schema validation
            self._validate_message_schema(message)

            # Content validation
            self._validate_message_content(message)

            self.validation_stats['valid_messages'] += 1
            return message

        except ValidationError as e:
            self.validation_stats['validation_errors'] += 1
            error_type = e.error_code
            self.validation_stats['errors_by_type'][error_type] = (
                self.validation_stats['errors_by_type'].get(error_type, 0) + 1
            )
            logger.warning(f"Message validation failed: {e.error_code} - {e.message}, message_size={len(raw_message)} bytes")
            raise

    def _validate_message_size(self, message: str):
        """Validate message size limits"""
        size = len(message.encode('utf-8'))
        if size > self.max_message_size:
            raise ValidationError(
                f"Message too large: {size} bytes (max: {self.max_message_size})",
                ErrorCodes.INPUT_OUT_OF_RANGE
            )

    def _parse_json_safely(self, message: str) -> Dict[str, Any]:
        """Parse JSON with depth and structure validation"""
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON: {e}", ErrorCodes.INPUT_INVALID_TYPE)

        if not isinstance(parsed, dict):
            raise ValidationError("Message must be a JSON object", ErrorCodes.INPUT_INVALID_TYPE)

        # Validate JSON depth and structure
        self._validate_json_structure(parsed, depth=0)

        return parsed

    def _validate_json_structure(self, obj: Any, depth: int = 0):
        """Recursively validate JSON structure limits"""
        if depth > self.MAX_JSON_DEPTH:
            raise ValidationError(
                f"JSON too deep: {depth} levels (max: {self.MAX_JSON_DEPTH})",
                ErrorCodes.INPUT_OUT_OF_RANGE
            )

        if isinstance(obj, dict):
            if len(obj) > self.MAX_OBJECT_KEYS:
                raise ValidationError(
                    f"Too many object keys: {len(obj)} (max: {self.MAX_OBJECT_KEYS})",
                    ErrorCodes.INPUT_OUT_OF_RANGE
                )
            for key, value in obj.items():
                if not isinstance(key, str) or len(key) > self.MAX_STRING_LENGTH:
                    raise ValidationError(
                        f"Invalid object key: {key}",
                        ErrorCodes.INPUT_INVALID_CHARS
                    )
                self._validate_json_structure(value, depth + 1)

        elif isinstance(obj, list):
            if len(obj) > self.MAX_ARRAY_LENGTH:
                raise ValidationError(
                    f"Array too long: {len(obj)} (max: {self.MAX_ARRAY_LENGTH})",
                    ErrorCodes.INPUT_OUT_OF_RANGE
                )
            for item in obj:
                self._validate_json_structure(item, depth + 1)

        elif isinstance(obj, str):
            if len(obj) > self.MAX_STRING_LENGTH:
                raise ValidationError(
                    f"String too long: {len(obj)} (max: {self.MAX_STRING_LENGTH})",
                    ErrorCodes.INPUT_STRING_TOO_LONG
                )

    def _validate_message_schema(self, message: Dict[str, Any]):
        """Validate message against schema"""
        msg_type_str = message.get('type')
        if not msg_type_str:
            raise ValidationError("Missing 'type' field", ErrorCodes.MISSING_REQUIRED_FIELD)

        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            raise ValidationError(f"Unknown message type: {msg_type_str}", ErrorCodes.UNKNOWN_MESSAGE_TYPE)

        schema = self.SCHEMAS.get(msg_type)
        if not schema:
            raise ValidationError(f"No schema defined for type: {msg_type_str}", ErrorCodes.UNKNOWN_MESSAGE_TYPE)

        # Check required fields
        for field in schema['required_fields']:
            if field not in message:
                raise ValidationError(f"Missing required field: {field}", ErrorCodes.INPUT_MISSING_FIELD)

        # Check field types
        field_types = schema.get('field_types', {})
        for field, expected_type in field_types.items():
            if field in message:
                value = message[field]
                if not isinstance(value, expected_type):
                    raise ValidationError(
                        f"Invalid type for field {field}: {type(value).__name__} "
                        f"(expected: {expected_type})",
                        ErrorCodes.INPUT_INVALID_TYPE
                    )

        # Check for unexpected fields
        allowed_fields = set(schema['required_fields'] + schema.get('optional_fields', []))
        for field in message:
            if field not in allowed_fields:
                raise ValidationError(f"Unexpected field: {field}", ErrorCodes.INPUT_INVALID_CHARS)

    def _validate_message_content(self, message: Dict[str, Any]):
        """Validate message content against constraints"""
        msg_type = MessageType(message['type'])
        schema = self.SCHEMAS[msg_type]
        constraints = schema.get('field_constraints', {})

        # Special handling for unit_actions_query: accept unit_ids in either location
        if msg_type == MessageType.UNIT_ACTIONS_QUERY:
            # If unit_ids is at top level, move it to data for handler compatibility
            if 'unit_ids' in message and 'data' not in message:
                message['data'] = {'unit_ids': message.pop('unit_ids')}
            elif 'unit_ids' in message and 'data' in message:
                # If both exist, prefer data but ensure unit_ids is there
                if 'unit_ids' not in message['data']:
                    message['data']['unit_ids'] = message['unit_ids']
                message.pop('unit_ids', None)  # Remove top-level duplicate
            
            # Verify unit_ids exists in data now
            if 'data' not in message or 'unit_ids' not in message.get('data', {}):
                raise ValidationError("Missing required field: unit_ids in data", ErrorCodes.INPUT_MISSING_FIELD)

        for field, field_constraints in constraints.items():
            if field not in message:
                continue

            value = message[field]

            # String constraints
            if isinstance(value, str):
                if 'min_length' in field_constraints:
                    if len(value) < field_constraints['min_length']:
                        raise ValidationError(
                            f"Field {field} too short: {len(value)} < {field_constraints['min_length']}",
                            ErrorCodes.INPUT_OUT_OF_RANGE
                        )

                if 'max_length' in field_constraints:
                    if len(value) > field_constraints['max_length']:
                        raise ValidationError(
                            f"Field {field} too long: {len(value)} > {field_constraints['max_length']}",
                            ErrorCodes.INPUT_STRING_TOO_LONG
                        )

                if 'pattern' in field_constraints:
                    import re
                    if not re.match(field_constraints['pattern'], value):
                        raise ValidationError(
                            f"Field {field} doesn't match pattern: {field_constraints['pattern']}",
                            ErrorCodes.INPUT_INVALID_CHARS
                        )

                if 'allowed_values' in field_constraints:
                    if value not in field_constraints['allowed_values']:
                        raise ValidationError(
                            f"Field {field} has invalid value: {value}",
                            ErrorCodes.INPUT_OUT_OF_RANGE
                        )

            # Numeric constraints
            elif isinstance(value, (int, float)):
                if 'min_value' in field_constraints:
                    if value < field_constraints['min_value']:
                        raise ValidationError(
                            f"Field {field} too small: {value} < {field_constraints['min_value']}",
                            ErrorCodes.INPUT_OUT_OF_RANGE
                        )

                if 'max_value' in field_constraints:
                    if value > field_constraints['max_value']:
                        raise ValidationError(
                            f"Field {field} too large: {value} > {field_constraints['max_value']}",
                            ErrorCodes.INPUT_OUT_OF_RANGE
                        )

            # List constraints
            elif isinstance(value, list):
                if 'max_length' in field_constraints:
                    if len(value) > field_constraints['max_length']:
                        raise ValidationError(
                            f"Field {field} list too long: {len(value)} > {field_constraints['max_length']}",
                            ErrorCodes.INPUT_OUT_OF_RANGE
                        )

            # Dict constraints
            elif isinstance(value, dict):
                if 'max_keys' in field_constraints:
                    if len(value) > field_constraints['max_keys']:
                        raise ValidationError(
                            f"Field {field} object too many keys: {len(value)} > {field_constraints['max_keys']}",
                            ErrorCodes.INPUT_OUT_OF_RANGE
                        )

    def get_validation_stats(self) -> Dict[str, Any]:
        """Get validation statistics"""
        total = self.validation_stats['total_messages']
        valid_rate = (self.validation_stats['valid_messages'] / total * 100) if total > 0 else 0

        return {
            **self.validation_stats,
            'valid_rate_percent': round(valid_rate, 2)
        }

    def reset_stats(self):
        """Reset validation statistics"""
        self.validation_stats = {
            'total_messages': 0,
            'valid_messages': 0,
            'validation_errors': 0,
            'errors_by_type': {}
        }
