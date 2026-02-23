#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Security-focused tests for FreeCiv proxy
Tests input validation, authentication security, rate limiting, and cache integrity
"""

import unittest
import secrets
import json
import time
import hmac
import hashlib
import os
from unittest.mock import Mock, patch, MagicMock

# IMPORTANT: Set environment variables BEFORE importing modules that use them
# This ensures StateCache picks up our HMAC secret during module load
os.environ['CACHE_HMAC_SECRET'] = '8dc50280f151af309d728c951584576f205688dc82d7d295174f2ef1b3e32181'
os.environ['LLM_API_TOKENS'] = 'test-token-123'

# Import the modules to test (AFTER setting env vars)
from message_validator import MessageValidator, ValidationError
from security import InputSanitizer, SecurityError, SecurityLogger
from rate_limiter import DistributedRateLimiter, InMemoryRateLimiter
from session_manager import SessionManager, SessionState
from state_cache import StateCache
from error_handler import ErrorHandler, ErrorSeverity, ErrorCategory


class TestInputSanitization(unittest.TestCase):
    """Test input sanitization and validation"""

    def setUp(self):
        self.sanitizer = InputSanitizer()

    def test_sql_injection_prevention(self):
        """Test prevention of SQL injection attempts"""
        malicious_inputs = [
            "'; DROP TABLE users; --",
            "1 OR 1=1",
            "UNION SELECT * FROM passwords",
            "/* malicious comment */",
            "admin'--",
            "1; DELETE FROM game_state WHERE 1=1"
        ]

        for malicious_input in malicious_inputs:
            with self.assertRaises(SecurityError):
                self.sanitizer.sanitize_string_field(malicious_input, 'agent_id')

    def test_xss_prevention(self):
        """Test prevention of XSS attacks"""
        xss_inputs = [
            "<script>alert('xss')</script>",
            "javascript:alert(1)",
            "<img src=x onerror=alert(1)>",
            "<%2fscript%3e"
        ]

        for xss_input in xss_inputs:
            with self.assertRaises(SecurityError):
                self.sanitizer.sanitize_string_field(xss_input, 'agent_id')

    def test_valid_input_acceptance(self):
        """Test that valid inputs are accepted"""
        valid_inputs = [
            ("test-agent-1", "agent_id"),
            ("Warriors", "unit_type"),
            ("Alphabet", "tech_name"),
            ("Capital", "production_type")
        ]

        for valid_input, field_type in valid_inputs:
            try:
                result = self.sanitizer.sanitize_string_field(valid_input, field_type)
                self.assertEqual(result, valid_input)
            except SecurityError:
                self.fail(f"Valid input '{valid_input}' was rejected for field '{field_type}'")

    def test_coordinate_validation(self):
        """Test coordinate sanitization"""
        # Valid coordinates
        x, y = self.sanitizer.sanitize_coordinates(10, 20)
        self.assertEqual((x, y), (10, 20))

        x, y = self.sanitizer.sanitize_coordinates(-5, -10)
        self.assertEqual((x, y), (-5, -10))

        # Invalid coordinates
        with self.assertRaises(SecurityError):
            self.sanitizer.sanitize_coordinates(10000, 10000)

        with self.assertRaises(SecurityError):
            self.sanitizer.sanitize_coordinates("invalid", 20)

    def test_action_data_sanitization(self):
        """Test comprehensive action data sanitization"""
        # Valid action
        valid_action = {
            'type': 'unit_move',
            'unit_id': 123,
            'dest_x': 10,
            'dest_y': 20,
            'player_id': 1
        }

        sanitized = self.sanitizer.sanitize_action_data(valid_action)
        self.assertEqual(sanitized['type'], 'unit_move')
        self.assertEqual(sanitized['unit_id'], 123)

        # Action with SQL injection attempt
        malicious_action = {
            'type': "unit_move'; DROP TABLE units; --",
            'unit_id': 123
        }

        with self.assertRaises(SecurityError):
            self.sanitizer.sanitize_action_data(malicious_action)


class TestMessageValidation(unittest.TestCase):
    """Test WebSocket message validation"""

    def setUp(self):
        self.validator = MessageValidator(max_message_size=1024)

    def test_message_size_limits(self):
        """Test message size validation"""
        # Large message
        large_message = json.dumps({'type': 'test', 'data': 'x' * 2000})

        with self.assertRaises(ValidationError) as context:
            self.validator.validate_message(large_message)

        self.assertEqual(context.exception.error_code, 'E222')  # Protocol v2.0.1: INPUT_OUT_OF_RANGE

    def test_json_depth_limits(self):
        """Test JSON depth validation"""
        # Create deeply nested JSON
        nested = {}
        current = nested
        for i in range(15):  # Exceeds MAX_JSON_DEPTH
            current['nested'] = {}
            current = current['nested']

        deep_message = json.dumps({'type': 'test', 'data': nested})

        with self.assertRaises(ValidationError) as context:
            self.validator.validate_message(deep_message)

        self.assertEqual(context.exception.error_code, 'E222')  # Protocol v2.0.1: INPUT_OUT_OF_RANGE (depth limit)

    def test_invalid_json_handling(self):
        """Test invalid JSON handling"""
        invalid_messages = [
            "not json at all",
            '{"incomplete": json',
            '{"type": "test" missing comma "data": "value"}',
            ""
        ]

        for invalid_msg in invalid_messages:
            with self.assertRaises(ValidationError) as context:
                self.validator.validate_message(invalid_msg)

            self.assertEqual(context.exception.error_code, 'E221')  # Protocol v2.0.1: INPUT_INVALID_TYPE

    def test_schema_validation(self):
        """Test message schema validation"""
        # Valid connect message
        valid_connect = json.dumps({
            'type': 'llm_connect',
            'agent_id': 'test-agent',
            'api_token': 'valid-token-123'
        })

        try:
            result = self.validator.validate_message(valid_connect)
            self.assertEqual(result['type'], 'llm_connect')
        except ValidationError:
            self.fail("Valid connect message was rejected")

        # Missing required field
        invalid_connect = json.dumps({
            'type': 'llm_connect',
            'agent_id': 'test-agent'
            # Missing api_token
        })

        with self.assertRaises(ValidationError) as context:
            self.validator.validate_message(invalid_connect)

        self.assertEqual(context.exception.error_code, 'E220')  # Protocol v2.0.1: INPUT_MISSING_FIELD

    def test_validation_statistics(self):
        """Test validation statistics tracking"""
        # Reset stats
        self.validator.reset_stats()

        # Process some messages
        valid_msg = json.dumps({'type': 'ping'})
        invalid_msg = "invalid"

        try:
            self.validator.validate_message(valid_msg)
        except ValidationError:
            pass

        try:
            self.validator.validate_message(invalid_msg)
        except ValidationError:
            pass

        stats = self.validator.get_validation_stats()
        self.assertEqual(stats['total_messages'], 2)
        self.assertEqual(stats['valid_messages'], 1)
        self.assertEqual(stats['validation_errors'], 1)


class TestRateLimiting(unittest.TestCase):
    """Test rate limiting functionality"""

    def setUp(self):
        self.rate_limiter = InMemoryRateLimiter()

    def test_token_bucket_algorithm(self):
        """Test token bucket rate limiting"""
        key = "test-agent"
        limit = 5
        window = 10

        # Should allow requests up to limit
        for i in range(limit):
            self.assertTrue(self.rate_limiter.check_limit(key, limit, window))

        # Should reject additional requests
        self.assertFalse(self.rate_limiter.check_limit(key, limit, window))

    def test_token_refill_over_time(self):
        """Test token refill over time"""
        key = "test-agent"
        limit = 2
        window = 1  # 1 second

        # Consume tokens
        self.assertTrue(self.rate_limiter.check_limit(key, limit, window))
        self.assertTrue(self.rate_limiter.check_limit(key, limit, window))
        self.assertFalse(self.rate_limiter.check_limit(key, limit, window))

        # Wait for refill (simulate time passage)
        import time
        time.sleep(1.1)

        # Should allow requests again
        self.assertTrue(self.rate_limiter.check_limit(key, limit, window))

    def test_remaining_tokens(self):
        """Test remaining token calculation"""
        key = "test-agent"
        limit = 5
        window = 10

        # Initially should have full tokens
        remaining = self.rate_limiter.get_remaining(key, limit, window)
        self.assertEqual(remaining, limit)

        # After consuming one token
        self.rate_limiter.check_limit(key, limit, window)
        remaining = self.rate_limiter.get_remaining(key, limit, window)
        self.assertEqual(remaining, limit - 1)

    def test_distributed_rate_limiter_fallback(self):
        """Test distributed rate limiter fallback to in-memory"""
        # Mock Redis failure
        with patch('redis.Redis') as mock_redis:
            mock_redis.side_effect = Exception("Redis connection failed")

            limiter = DistributedRateLimiter({'host': 'localhost', 'port': 6379})

            # Should fall back to in-memory limiter
            self.assertTrue(limiter.check_limit('test-agent', 'default'))


class TestSessionManagement(unittest.TestCase):
    """Test session management security"""

    def setUp(self):
        self.session_manager = SessionManager(session_timeout=60)

    def test_session_creation_and_validation(self):
        """Test secure session creation and validation"""
        agent_id = "test-agent"
        api_token = "test-token-123"

        # Create session
        session = self.session_manager.create_session(agent_id, api_token)
        self.assertIsNotNone(session)
        self.assertEqual(session.agent_id, agent_id)

        # Validate session
        validated_session = self.session_manager.validate_session(session.session_id, api_token)
        self.assertIsNotNone(validated_session)
        self.assertEqual(validated_session.session_id, session.session_id)

    def test_session_expiration(self):
        """Test session expiration"""
        agent_id = "test-agent"
        api_token = "test-token-123"

        # Create session with short timeout
        short_session_manager = SessionManager(session_timeout=1)
        session = short_session_manager.create_session(agent_id, api_token)
        self.assertIsNotNone(session)

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        validated_session = short_session_manager.validate_session(session.session_id, api_token)
        self.assertIsNone(validated_session)

    def test_invalid_token_rejection(self):
        """Test rejection of invalid tokens"""
        agent_id = "test-agent"
        api_token = "valid-token"
        wrong_token = "wrong-token"

        session = self.session_manager.create_session(agent_id, api_token)
        self.assertIsNotNone(session)

        # Should reject wrong token
        validated_session = self.session_manager.validate_session(session.session_id, wrong_token)
        self.assertIsNone(validated_session)

    def test_concurrent_session_limits(self):
        """Test concurrent session limits and thread safety"""
        import threading
        import concurrent.futures

        # Create session manager with low limit for testing
        limited_session_manager = SessionManager(max_concurrent_sessions=3)

        # Function to create sessions concurrently
        def create_session_worker(agent_id: str, api_token: str):
            return limited_session_manager.create_session(agent_id, api_token)

        # Create multiple sessions up to the limit
        sessions = []
        for i in range(3):
            session = limited_session_manager.create_session(f"agent-{i}", f"token-{i}")
            self.assertIsNotNone(session)
            sessions.append(session)

        # Should reject additional session
        overflow_session = limited_session_manager.create_session("agent-overflow", "token-overflow")
        self.assertIsNone(overflow_session)

        # Test concurrent session creation with threading
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            # Try to create 5 sessions concurrently when limit is 3
            futures = []
            for i in range(5, 10):
                future = executor.submit(create_session_worker, f"concurrent-agent-{i}", f"token-{i}")
                futures.append(future)

            # Collect results
            results = [future.result() for future in futures]

            # Should have no successful sessions (all slots taken)
            successful_sessions = [r for r in results if r is not None]
            self.assertEqual(len(successful_sessions), 0)

        # Clean up by terminating a session
        terminated = limited_session_manager.terminate_session(sessions[0].session_id)
        self.assertTrue(terminated)

        # Now should be able to create one more
        new_session = limited_session_manager.create_session("agent-new", "token-new")
        self.assertIsNotNone(new_session)

    def test_session_race_condition_prevention(self):
        """Test prevention of race conditions in session creation"""
        import threading
        import concurrent.futures

        # Create session manager with limit of 1 for clear testing
        race_session_manager = SessionManager(max_concurrent_sessions=1)

        results = []
        errors = []

        def concurrent_session_creator(agent_id: str):
            try:
                return race_session_manager.create_session(agent_id, f"token-{agent_id}")
            except Exception as e:
                errors.append(e)
                return None

        # Launch multiple threads trying to create sessions simultaneously
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(10):
                future = executor.submit(concurrent_session_creator, f"race-agent-{i}")
                futures.append(future)

            # Collect results
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)

        # Should have exactly one successful session and 9 None results
        successful_sessions = [r for r in results if r is not None]
        failed_sessions = [r for r in results if r is None]

        self.assertEqual(len(successful_sessions), 1)
        self.assertEqual(len(failed_sessions), 9)
        self.assertEqual(len(errors), 0)  # No exceptions should occur

    def test_session_cleanup(self):
        """Test expired session cleanup"""
        agent_id = "test-agent"
        api_token = "test-token-123"

        # Create session with short timeout
        short_session_manager = SessionManager(session_timeout=1, cleanup_interval=0)
        session = short_session_manager.create_session(agent_id, api_token)

        # Wait for expiration
        time.sleep(1.1)

        # Trigger cleanup
        cleaned_count = short_session_manager.cleanup_expired_sessions()
        self.assertGreater(cleaned_count, 0)

    def test_session_capacity_limits(self):
        """Test session capacity enforcement"""
        limited_session_manager = SessionManager(max_concurrent_sessions=2)

        # Create up to limit
        session1 = limited_session_manager.create_session("agent1", "token1")
        session2 = limited_session_manager.create_session("agent2", "token2")

        self.assertIsNotNone(session1)
        self.assertIsNotNone(session2)

        # Should reject additional sessions
        session3 = limited_session_manager.create_session("agent3", "token3")
        self.assertIsNone(session3)


class TestCacheIntegrity(unittest.TestCase):
    """Test cache integrity and security"""

    def setUp(self):
        self.cache = StateCache(ttl=60, max_size_kb=4)

    def test_cache_hmac_integrity(self):
        """Test HMAC-based cache integrity"""
        # Use game-state keys that survive optimize_state_data()
        test_data = {'turn': 1, 'phase': 'movement', 'player_id': 1}
        cache_key = 'integrity_test'
        player_id = 1

        # Set data in cache
        success = self.cache.set(cache_key, test_data, player_id)
        self.assertTrue(success)

        # Retrieve data
        retrieved_data = self.cache.get(cache_key)
        self.assertIsNotNone(retrieved_data)
        self.assertEqual(retrieved_data['turn'], 1)

    def test_cache_poisoning_detection(self):
        """Test detection of cache poisoning attempts"""
        # Use game-state keys that survive optimize_state_data()
        test_data = {'turn': 1, 'phase': 'movement', 'player_id': 1}
        cache_key = 'poisoning_test'
        player_id = 1

        # Set legitimate data
        self.cache.set(cache_key, test_data, player_id)

        # Manually tamper with cache entry
        if cache_key in self.cache.cache:
            entry = self.cache.cache[cache_key]
            entry.data['turn'] = 999  # Modify existing field to corrupt HMAC

            # Should detect tampering and reject
            retrieved_data = self.cache.get(cache_key)
            self.assertIsNone(retrieved_data)

    def test_cache_size_limits(self):
        """Test cache size enforcement"""
        # Create a new cache with compression disabled to test raw size limits
        # (default cache has compression which can shrink data below limit)
        cache_no_compression = StateCache(ttl=60, max_size_kb=4, enable_compression=False)

        # Use dict format for cities (bypasses optimize_state_data truncation)
        large_data = {
            'turn': 1,
            'phase': 'movement',
            'player_id': 1,
            'cities': {str(i): {'id': i, 'name': f'city_with_very_long_unique_name_{i}_abcdefghij',
                                'x': i * 17, 'y': i * 23, 'owner': 1, 'pop': i * 7}
                       for i in range(150)}  # Dict format produces ~16KB uncompressed
        }
        cache_key = 'size_test'
        player_id = 1

        # Should reject oversized data (16KB > 4KB limit without compression)
        success = cache_no_compression.set(cache_key, large_data, player_id)
        self.assertFalse(success)

    def test_cache_ttl_enforcement(self):
        """Test TTL enforcement"""
        # Use game-state keys that survive optimize_state_data()
        test_data = {'turn': 1, 'phase': 'movement', 'player_id': 1}
        cache_key = 'ttl_test'
        player_id = 1

        # Create cache with short TTL
        short_cache = StateCache(ttl=1)
        success = short_cache.set(cache_key, test_data, player_id)
        self.assertTrue(success)

        # Should be available immediately
        retrieved = short_cache.get(cache_key)
        self.assertIsNotNone(retrieved)

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        retrieved = short_cache.get(cache_key)
        self.assertIsNone(retrieved)


class TestErrorHandling(unittest.TestCase):
    """Test security-focused error handling"""

    def setUp(self):
        self.error_handler = ErrorHandler()

    def test_authentication_error_handling(self):
        """Test authentication error responses"""
        agent_id = "test-agent"
        error_response = self.error_handler.handle_authentication_error(
            agent_id, "Invalid API token"
        )

        self.assertEqual(error_response.category, ErrorCategory.AUTHENTICATION)
        self.assertEqual(error_response.severity, ErrorSeverity.HIGH)
        self.assertIn("authentication", error_response.message.lower())

    def test_security_violation_handling(self):
        """Test security violation responses"""
        agent_id = "malicious-agent"
        error_response = self.error_handler.handle_security_violation(
            agent_id, "SQL injection attempt", "Detected malicious SQL in input"
        )

        self.assertEqual(error_response.category, ErrorCategory.SECURITY)
        self.assertEqual(error_response.severity, ErrorSeverity.CRITICAL)

    def test_rate_limit_error_handling(self):
        """Test rate limit error responses"""
        agent_id = "spamming-agent"
        error_response = self.error_handler.handle_rate_limit_error(
            agent_id, "message", 60
        )

        self.assertEqual(error_response.category, ErrorCategory.RATE_LIMIT)
        self.assertEqual(error_response.retry_after, 60)

    def test_error_frequency_tracking(self):
        """Test error frequency tracking for circuit breaker"""
        operation = "test_operation"
        # _track_error stores errors with composite key: f"{operation}:{error_type}"
        # so circuit breaker checks need to use the same key format
        error_key = f"{operation}:Exception"

        # Simulate multiple errors - use keyword args since handle_system_error
        # signature is (agent_id=, error_code=, ..., operation=, error=, ...)
        for i in range(5):
            try:
                raise Exception(f"Test error {i}")
            except Exception as e:
                self.error_handler.handle_system_error(operation=operation, error=e)

        # Should not trigger circuit breaker yet (threshold is 10)
        self.assertFalse(self.error_handler.should_circuit_break(error_key, 10))

        # Simulate more errors
        for i in range(6):
            try:
                raise Exception(f"Test error {i + 5}")
            except Exception as e:
                self.error_handler.handle_system_error(operation=operation, error=e)

        # Should trigger circuit breaker (11 errors >= threshold of 10)
        self.assertTrue(self.error_handler.should_circuit_break(error_key, 10))


class TestSecurityLogging(unittest.TestCase):
    """Test security event logging"""

    def setUp(self):
        # Mock the module-level logger in security.py (SecurityLogger uses security.logger)
        self.log_messages = []

        def mock_log(level, message):
            self.log_messages.append((level, message))

        # Patch the module-level logger in security module
        self.log_patcher = patch('security.logger')
        self.mock_logger = self.log_patcher.start()

        # Configure mock methods to capture messages
        self.mock_logger.info = lambda msg: mock_log('INFO', msg)
        self.mock_logger.warning = lambda msg: mock_log('WARNING', msg)
        self.mock_logger.error = lambda msg: mock_log('ERROR', msg)

    def tearDown(self):
        # Stop patching
        self.log_patcher.stop()

    def test_authentication_logging(self):
        """Test authentication event logging"""
        SecurityLogger.log_authentication_attempt(
            "test-agent", True, "192.168.1.100", "session-123"
        )

        # Check if log message was created
        self.assertTrue(len(self.log_messages) > 0)
        level, message = self.log_messages[-1]
        self.assertEqual(level, 'INFO')
        self.assertIn('AUTH_SUCCESS', message)
        self.assertIn('test-agent', message)

    def test_security_violation_logging(self):
        """Test security violation logging"""
        SecurityLogger.log_security_violation(
            "malicious-agent", "injection_attempt", "SQL injection detected", "high"
        )

        level, message = self.log_messages[-1]
        self.assertEqual(level, 'ERROR')
        self.assertIn('SECURITY_VIOLATION', message)
        self.assertIn('malicious-agent', message)

    def test_rate_limit_logging(self):
        """Test rate limit violation logging"""
        SecurityLogger.log_rate_limit_exceeded(
            "spamming-agent", "192.168.1.200", "message", 50
        )

        level, message = self.log_messages[-1]
        self.assertEqual(level, 'WARNING')
        self.assertIn('RATE_LIMIT_EXCEEDED', message)
        self.assertIn('spamming-agent', message)


class TestAuthenticationBypassPrevention(unittest.TestCase):
    """Test prevention of authentication bypass attempts"""

    def test_header_manipulation_bypass_attempt(self):
        """Test that manipulating auth headers doesn't bypass authentication"""
        # Simulate malicious headers that might bypass authentication
        malicious_headers = [
            {'X-Forwarded-User': 'admin'},
            {'X-Auth-User': 'admin'},
            {'X-Real-IP': '127.0.0.1'},
            {'X-Forwarded-For': '127.0.0.1'},
            {'Authorization': 'Bearer fake-token'},
            {'Cookie': 'session=admin; authenticated=true'},
        ]

        # Mock request handler
        mock_handler = Mock()
        mock_handler.request = Mock()

        for headers in malicious_headers:
            mock_handler.request.headers = headers

            # Import here to avoid circular import
            from state_extractor import authenticate_request

            with patch.dict('os.environ', {'AUTH_ENABLED': 'true', 'ENVIRONMENT': 'production'}):
                authenticated, player_id, game_id, error = authenticate_request(mock_handler)
                self.assertFalse(authenticated, f"Authentication bypassed with headers: {headers}")

    def test_environment_based_bypass_protection(self):
        """Test that auth bypass only works in development environment"""
        mock_handler = Mock()

        from state_extractor import authenticate_request

        # Test production environment - should not allow bypass
        with patch.dict('os.environ', {'AUTH_ENABLED': 'false', 'ENVIRONMENT': 'production'}):
            authenticated, _, _, error = authenticate_request(mock_handler)
            self.assertFalse(authenticated)
            self.assertIn("Authentication required", error)

        # Test development environment - should allow bypass
        with patch.dict('os.environ', {'AUTH_ENABLED': 'false', 'ENVIRONMENT': 'development'}):
            authenticated, _, _, error = authenticate_request(mock_handler)
            self.assertTrue(authenticated)

    def test_hmac_signature_tampering(self):
        """Test that tampered HMAC signatures are rejected"""
        from admin_handlers import validate_admin_token

        # Create a valid token structure but with wrong signature
        import time
        timestamp = int(time.time())
        valid_timestamp = str(timestamp)
        tampered_signature = "tampered_signature_12345"

        tampered_token = f"{valid_timestamp}_{tampered_signature}"

        with patch.dict('os.environ', {'ADMIN_KEY_SECRET': 'test-secret-key-for-testing'}):
            result = validate_admin_token(tampered_token)
            self.assertFalse(result, "Tampered HMAC signature should be rejected")


class TestLLMTokenAuthFallback(unittest.TestCase):
    """Test LLM API token fallback in SimpleAuthenticator.authenticate_request()"""

    def test_valid_llm_token_authenticates(self):
        """Valid LLM_API_TOKEN should authenticate with player_id=None, game_id=None"""
        from auth import SimpleAuthenticator
        auth = SimpleAuthenticator()

        # 'test-token-123' is set in LLM_API_TOKENS env var at module level
        authenticated, player_id, game_id = auth.authenticate_request(api_key='test-token-123')

        self.assertTrue(authenticated, "Valid LLM token should authenticate")
        self.assertIsNone(player_id, "LLM token should return player_id=None (admin access)")
        self.assertIsNone(game_id, "LLM token should return game_id=None (admin access)")

    def test_invalid_llm_token_rejected(self):
        """Invalid token should not authenticate via LLM fallback"""
        from auth import SimpleAuthenticator
        auth = SimpleAuthenticator()

        authenticated, player_id, game_id = auth.authenticate_request(api_key='not-a-valid-token')

        self.assertFalse(authenticated, "Invalid token should be rejected")
        self.assertIsNone(player_id)
        self.assertIsNone(game_id)

    def test_llm_fallback_only_after_hmac_fails(self):
        """LLM token fallback should only be tried when HMAC key validation fails"""
        from auth import SimpleAuthenticator
        auth = SimpleAuthenticator()

        # A non-fcv_ prefixed token should skip HMAC, fall through to LLM check
        with patch.object(auth, '_validate_llm_token', return_value=True) as mock_llm:
            authenticated, _, _ = auth.authenticate_request(api_key='some-bearer-token')
            self.assertTrue(authenticated)
            mock_llm.assert_called_once_with('some-bearer-token')

    def test_llm_config_unavailable_returns_false(self):
        """When config_loader is unavailable, LLM token validation returns False"""
        from auth import SimpleAuthenticator
        auth = SimpleAuthenticator()

        import auth as auth_module
        original = auth_module._llm_config

        try:
            auth_module._llm_config = None
            result = auth._validate_llm_token('test-token-123')
            self.assertFalse(result, "Should return False when _llm_config is None")
        finally:
            auth_module._llm_config = original


class TestMalformedRequestHandling(unittest.TestCase):
    """Test handling of malformed and edge case requests"""

    @unittest.skip("Cache compression is too effective - need different test approach for size limits")
    def test_extremely_large_state_handling(self):
        """Test handling of extremely large game states

        NOTE: This test is skipped because gzip compression is very effective
        at compressing even high-entropy data. The cache size limit tests
        are covered in test_cache_size_limits which uses uncompressable data.
        """
        pass

    def test_malformed_json_in_requests(self):
        """Test handling of malformed JSON in requests"""
        validator = MessageValidator()

        malformed_json_strings = [
            '{"incomplete": json',  # Incomplete JSON
            '{"duplicate": "key", "duplicate": "value"}',  # Duplicate keys (valid JSON, may parse)
            '{"nesting": ' + '{"level": ' * 15 + '"deep"' + '}' * 15,  # Deep nesting (exceeds MAX_JSON_DEPTH=10)
            '\x00\x01\x02invalid',  # Binary data
        ]

        for malformed_json in malformed_json_strings:
            with self.assertRaises(ValidationError):
                # Use public validate_message() API instead of private _validate_message_content()
                validator.validate_message(malformed_json)

    def test_concurrent_cache_modifications(self):
        """Test cache behavior under concurrent modifications"""
        import concurrent.futures
        import threading

        cache = StateCache()

        def cache_operation(operation_id):
            """Perform cache operations concurrently"""
            try:
                # Set data using game-state format (dict format to bypass optimization)
                state = {'turn': operation_id, 'phase': 'movement', 'player_id': operation_id % 8 + 1,
                         'cities': {str(operation_id): {'id': operation_id, 'name': f'city_{operation_id}'}}}
                cache.set(f'key_{operation_id}', state, operation_id % 8 + 1)

                # Get data
                result = cache.get(f'key_{operation_id}')

                # Invalidate some data
                if operation_id % 3 == 0:
                    cache.invalidate(player_id=operation_id % 8 + 1)

                return operation_id
            except Exception as e:
                return f"Error: {e}"

        # Run concurrent operations
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(cache_operation, i) for i in range(100)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        # Should complete without deadlocks or corruption
        error_count = sum(1 for r in results if isinstance(r, str) and r.startswith("Error"))
        self.assertLess(error_count, 5, "Too many errors in concurrent operations")

    def test_memory_exhaustion_protection(self):
        """Test protection against memory exhaustion attacks"""
        # Use small max_entries to trigger eviction (default is 1000)
        cache = StateCache(max_cache_size_mb=1, max_entries=50)  # Very small cache with low entry limit

        # Try to exhaust memory with many small entries using dict format to bypass optimization
        for i in range(200):
            # Dict format cities bypass optimize_state_data
            state = {'turn': i, 'phase': 'movement', 'player_id': 1,
                     'cities': {str(j): {'id': j, 'name': f'city{j}'} for j in range(10)}}
            cache.set(f'key_{i}', state, i % 8 + 1)

        # Cache should have limited entries due to eviction (max_entries=50)
        cache_stats = cache.get_cache_stats()
        self.assertLessEqual(cache_stats['cache_entries'], 50, "Cache should evict entries to prevent memory exhaustion")

    def test_invalid_authentication_tokens(self):
        """Test handling of various invalid authentication tokens"""
        from admin_handlers import validate_admin_token

        invalid_tokens = [
            None,
            "",
            "short",
            "no_underscore_separator",
            "multiple_underscores_in_token_structure",
            "12345_validtimestamp_butmultiple_separators",
            "notanumber_signature",
            "12345_",  # Missing signature
            "_signature_only",  # Missing timestamp
            "\x00\x01invalid_chars_signature",
            "a" * 10000,  # Extremely long token
        ]

        with patch.dict('os.environ', {'ADMIN_KEY_SECRET': 'test-secret-key-for-testing'}):
            for token in invalid_tokens:
                result = validate_admin_token(token)
                self.assertFalse(result, f"Invalid token should be rejected: {token}")


if __name__ == '__main__':
    unittest.main()
