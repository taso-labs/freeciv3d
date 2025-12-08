#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Centralized error handling for FreeCiv proxy
Provides consistent error responses, recovery strategies, and security event logging
"""

import json
import logging
import traceback
import time
from typing import Dict, Any, Optional, Callable
from enum import Enum
from security import SecurityLogger

logger = logging.getLogger("freeciv-proxy")

class ErrorSeverity(Enum):
    """Error severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ErrorCategory(Enum):
    """Error categories for classification"""
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    SYSTEM = "system"
    SECURITY = "security"
    CONFIGURATION = "configuration"

class ErrorCode:
    """
    Standardized error codes per LLM WebSocket Protocol v2.0.1
    
    Code ranges:
    - E1xx: System & Connection errors
    - E22x: Input validation errors
    - E23x: Unit validation errors
    - E24x: City validation errors
    - E25x: Target validation errors
    - E26x: Diplomacy errors
    - E4xx: Client errors (rate limiting)
    - E5xx: Server errors
    """
    
    # System & Connection Errors (E1xx)
    MISSING_REQUIRED_FIELD = "E101"      # Missing required field in message
    INVALID_API_TOKEN = "E102"           # Invalid or expired API token
    UNKNOWN_MESSAGE_TYPE = "E103"        # Unrecognized message type
    NOT_AUTHENTICATED = "E120"           # Session expired or not authenticated
    STATE_QUERY_FAILED = "E121"          # Failed to retrieve game state
    CONNECTION_LOST = "E123"             # Connection to game server lost
    ACTION_VALIDATION_FAILED = "E130"    # Action failed game rule validation
    ACTION_EXECUTION_FAILED = "E131"     # Action was valid but execution failed
    
    # Input Validation Errors (E22x)
    INPUT_MISSING_FIELD = "E220"         # Action-specific required field missing
    INPUT_INVALID_TYPE = "E221"          # Wrong data type (e.g., string instead of int)
    INPUT_OUT_OF_RANGE = "E222"          # Numeric value outside valid range
    INPUT_INVALID_CHARS = "E223"         # Dangerous characters (SQL injection, XSS)
    INPUT_STRING_TOO_LONG = "E224"       # String exceeds maximum length
    
    # Unit Validation Errors (E23x)
    UNIT_NOT_FOUND = "E230"              # Specified unit does not exist
    UNIT_NOT_OWNED = "E231"              # Unit exists but not owned by player
    UNIT_BUSY = "E232"                   # Unit is busy or has no moves remaining
    UNIT_NO_MOVES = "E233"               # Insufficient movement points
    UNIT_MISSING_CAPABILITY = "E234"     # Unit lacks capability for action
    
    # City Validation Errors (E24x)
    CITY_NOT_FOUND = "E240"              # Specified city does not exist
    CITY_NOT_OWNED = "E241"              # City exists but not owned by player
    CITY_AT_CAPACITY = "E242"            # City at maximum capacity
    
    # Target Validation Errors (E25x)
    INSUFFICIENT_RESOURCES = "E250"      # Not enough gold or resources
    INVALID_COORDINATES = "E251"         # Coordinates malformed or out of range
    TARGET_OUT_OF_RANGE = "E252"         # Target too far from actor
    TARGET_NOT_VISIBLE = "E253"          # Target in fog of war
    TERRAIN_INCOMPATIBLE = "E254"        # Terrain doesn't support action
    
    # Diplomacy Errors (E26x)
    PLAYER_NOT_FOUND = "E260"            # Target player does not exist
    DIPLOMATIC_ACTION_INVALID = "E261"   # Action not allowed (e.g., already at war)
    TREATY_EXISTS = "E262"               # Treaty already exists
    NO_PENDING_TREATY = "E263"           # No treaty proposal to accept/reject
    INVALID_DIPLOMATIC_STATE = "E264"    # Current state doesn't allow action
    
    # Server Errors (E4xx, E5xx)
    RATE_LIMIT_EXCEEDED = "E429"         # Too many requests
    INTERNAL_ERROR = "E500"              # Unexpected server error
    QUERY_TIMEOUT = "E503"               # Server didn't respond in time
    UNKNOWN_ERROR = "E999"               # Unclassified error
    
    # Retryable error codes
    _RETRYABLE = {
        "E120", "E121", "E123", "E429", "E500", "E503"
    }
    
    @classmethod
    def is_retryable(cls, code: str) -> bool:
        """Check if an error code indicates a retryable condition"""
        return code in cls._RETRYABLE

class ErrorResponse:
    """Standardized error response structure"""

    def __init__(self, code: str, message: str, category: ErrorCategory = None,
                 severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                 retry_after: int = None, details: Dict[str, Any] = None):
        self.code = code
        self.message = message
        self.category = category
        self.severity = severity
        self.retry_after = retry_after
        self.details = details or {}
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        response = {
            'type': 'error',
            'code': self.code,
            'message': self.message,
            'timestamp': self.timestamp
        }

        if self.retry_after:
            response['retry_after'] = self.retry_after

        if self.details:
            response['details'] = self.details

        return response

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict())

class ErrorHandler:
    """
    Centralized error handling with security logging and recovery strategies
    """

    def __init__(self):
        self.error_counts = {}  # Track error frequencies
        self.last_cleanup = time.time()

    def handle_authentication_error(self, agent_id: str, reason: str,
                                  session_id: str = None) -> ErrorResponse:
        """Handle authentication-related errors"""
        SecurityLogger.log_authentication_attempt(
            agent_id, False, session_id=session_id, details=reason
        )

        # Determine specific error code based on reason
        reason_lower = reason.lower()
        if "token" in reason_lower or "invalid" in reason_lower:
            code = ErrorCode.INVALID_API_TOKEN
        elif "session" in reason_lower or "expired" in reason_lower:
            code = ErrorCode.NOT_AUTHENTICATED
        else:
            code = ErrorCode.INVALID_API_TOKEN

        return ErrorResponse(
            code=code,
            message=f"Authentication failed: {reason}",
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.HIGH
        )

    def handle_rate_limit_error(self, agent_id: str, limit_type: str = "default",
                              retry_after: int = 60) -> ErrorResponse:
        """Handle rate limiting errors"""
        SecurityLogger.log_rate_limit_exceeded(agent_id, limit_type=limit_type)

        return ErrorResponse(
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message=f"Rate limit exceeded for {limit_type}",
            category=ErrorCategory.RATE_LIMIT,
            severity=ErrorSeverity.MEDIUM,
            retry_after=retry_after
        )

    def handle_validation_error(self, agent_id: str, error_code: str,
                              message: str, session_id: str = None,
                              input_data: str = None, details: Dict[str, Any] = None) -> ErrorResponse:
        """Handle input validation errors"""
        SecurityLogger.log_validation_error(
            agent_id, error_code, message,
            session_id=session_id, input_data=input_data
        )

        # High severity for security-related validation errors
        severity = ErrorSeverity.HIGH if error_code == ErrorCode.INPUT_INVALID_CHARS else ErrorSeverity.MEDIUM

        return ErrorResponse(
            code=error_code,
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=severity,
            details=details
        )

    def handle_entity_error(self, agent_id: str, error_code: str,
                          message: str, details: Dict[str, Any] = None) -> ErrorResponse:
        """Handle unit/city entity validation errors (E23x, E24x)"""
        return ErrorResponse(
            code=error_code,
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            details=details
        )

    def handle_target_error(self, agent_id: str, error_code: str,
                          message: str, details: Dict[str, Any] = None) -> ErrorResponse:
        """Handle target validation errors (E25x)"""
        return ErrorResponse(
            code=error_code,
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            details=details
        )

    def handle_diplomacy_error(self, agent_id: str, error_code: str,
                             message: str, details: Dict[str, Any] = None) -> ErrorResponse:
        """Handle diplomacy errors (E26x)"""
        return ErrorResponse(
            code=error_code,
            message=message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.MEDIUM,
            details=details
        )

    def handle_security_violation(self, agent_id: str, violation_type: str,
                                details: str, session_id: str = None) -> ErrorResponse:
        """Handle security violations (SQL injection, XSS, etc.)"""
        SecurityLogger.log_security_violation(
            agent_id, violation_type, details,
            severity='high', session_id=session_id
        )

        return ErrorResponse(
            code=ErrorCode.INPUT_INVALID_CHARS,
            message="Invalid characters in input",
            category=ErrorCategory.SECURITY,
            severity=ErrorSeverity.CRITICAL,
            details={'violation_type': violation_type}
        )

    def handle_system_error(self, agent_id: str = None, error_code: str = None,
                          message: str = None, details: Dict[str, Any] = None,
                          operation: str = None, error: Exception = None,
                          session_id: str = None) -> ErrorResponse:
        """
        Handle system-level errors with appropriate logging.
        
        Can be called in two ways:
        1. With error_code, message, details for known errors
        2. With operation, error for exception handling
        """
        if error is not None:
            # Exception handling mode
            error_msg = str(error)
            error_type = type(error).__name__

            # Log detailed error for debugging
            logger.error(f"System error in {operation}: {error_type}: {error_msg}")
            logger.debug(f"Stack trace: {traceback.format_exc()}")

            # Track error frequency
            self._track_error(operation or "unknown", error_type)

            # Determine appropriate response based on error type
            if "connection" in error_msg.lower() or "socket" in error_msg.lower():
                code = ErrorCode.CONNECTION_LOST
                msg = "Game server connection error"
                severity = ErrorSeverity.HIGH
            elif "timeout" in error_msg.lower():
                code = ErrorCode.QUERY_TIMEOUT
                msg = "Query timeout - server did not respond in time"
                severity = ErrorSeverity.MEDIUM
            else:
                code = ErrorCode.INTERNAL_ERROR
                msg = "Internal server error"
                severity = ErrorSeverity.CRITICAL

            return ErrorResponse(
                code=code,
                message=msg,
                category=ErrorCategory.SYSTEM,
                severity=severity,
                details={'operation': operation} if operation else None
            )
        else:
            # Direct error code mode
            return ErrorResponse(
                code=error_code or ErrorCode.INTERNAL_ERROR,
                message=message or "Internal server error",
                category=ErrorCategory.SYSTEM,
                severity=ErrorSeverity.HIGH,
                details=details
            )

    def handle_capacity_error(self, resource_type: str, current: int,
                            maximum: int) -> ErrorResponse:
        """Handle capacity/resource limit errors"""
        return ErrorResponse(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Server capacity exceeded: {current}/{maximum} {resource_type}",
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.HIGH,
            retry_after=300,  # 5 minutes
            details={
                'resource_type': resource_type,
                'current': current,
                'maximum': maximum
            }
        )

    def should_circuit_break(self, operation: str, error_threshold: int = 10,
                           time_window: int = 300) -> bool:
        """Determine if circuit breaker should activate"""
        now = time.time()

        # Clean old entries periodically
        if now - self.last_cleanup > 60:  # Cleanup every minute
            self._cleanup_error_counts()
            self.last_cleanup = now

        # Check error count in time window
        if operation in self.error_counts:
            recent_errors = [
                timestamp for timestamp in self.error_counts[operation]
                if now - timestamp < time_window
            ]

            if len(recent_errors) >= error_threshold:
                logger.warning(f"Circuit breaker activated for {operation}: "
                             f"{len(recent_errors)} errors in {time_window}s")
                return True

        return False

    def _track_error(self, operation: str, error_type: str):
        """Track error occurrences for circuit breaker logic"""
        key = f"{operation}:{error_type}"
        now = time.time()

        if key not in self.error_counts:
            self.error_counts[key] = []

        self.error_counts[key].append(now)

        # Keep only recent errors (last hour)
        cutoff = now - 3600
        self.error_counts[key] = [
            timestamp for timestamp in self.error_counts[key]
            if timestamp > cutoff
        ]

    def _cleanup_error_counts(self):
        """Clean up old error tracking data"""
        now = time.time()
        cutoff = now - 3600  # Keep last hour

        for operation in list(self.error_counts.keys()):
            self.error_counts[operation] = [
                timestamp for timestamp in self.error_counts[operation]
                if timestamp > cutoff
            ]

            # Remove empty entries
            if not self.error_counts[operation]:
                del self.error_counts[operation]

    def get_error_stats(self) -> Dict[str, Any]:
        """Get error handling statistics"""
        now = time.time()
        total_errors = sum(len(errors) for errors in self.error_counts.values())

        # Recent errors (last 5 minutes)
        recent_cutoff = now - 300
        recent_errors = sum(
            len([e for e in errors if e > recent_cutoff])
            for errors in self.error_counts.values()
        )

        return {
            'total_tracked_errors': total_errors,
            'recent_errors_5min': recent_errors,
            'tracked_operations': len(self.error_counts),
            'error_types': list(self.error_counts.keys())
        }

    def handle_state_extraction_error(self, game_id: str, player_id: int, error: str) -> ErrorResponse:
        """Handle state extraction errors"""
        logger.error(f"State extraction failed for game {game_id}, player {player_id}: {error}")
        return ErrorResponse(
            code=ErrorCode.STATE_QUERY_FAILED,
            message=f"Failed to extract game state: {error}",
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.HIGH,
            details={
                'game_id': game_id,
                'player_id': player_id,
                'operation': 'state_extraction'
            }
        )

    def handle_action_extraction_error(self, game_id: str, player_id: int, error: str) -> ErrorResponse:
        """Handle legal action extraction errors"""
        logger.error(f"Action extraction failed for game {game_id}, player {player_id}: {error}")
        return ErrorResponse(
            code=ErrorCode.STATE_QUERY_FAILED,
            message=f"Failed to extract legal actions: {error}",
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.HIGH,
            details={
                'game_id': game_id,
                'player_id': player_id,
                'operation': 'action_extraction'
            }
        )

# Global error handler instance
error_handler = ErrorHandler()

def with_error_handling(operation: str, agent_id: str = None,
                       session_id: str = None):
    """Decorator for automatic error handling"""
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_response = error_handler.handle_system_error(
                    operation, e, agent_id, session_id
                )
                logger.exception(f"Error in {operation}: {e}")
                return error_response
        return wrapper
    return decorator
