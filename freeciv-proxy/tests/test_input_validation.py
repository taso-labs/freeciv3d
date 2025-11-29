#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Phase 4: Input Validation Hardening Tests

Tests input validation per LLM WebSocket Protocol v2.0.1:
- String length validation (city names, building names, etc.)
- Character allowlist validation per field type
- SQL injection pattern detection
- XSS pattern detection
- Coordinate range validation
- Null byte and control character removal
"""

import pytest
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from action_validator import ValidationResult
from input_validator import InputValidator, InputValidationError

class TestStringLengthValidation:
    """Test string length constraints per Protocol v2.0.1"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    # --- City Name Tests (max 50 chars) ---
    
    def test_city_name_valid_length(self, validator):
        """City name under 50 chars should pass"""
        result = validator.validate_string_field("New York", "city_name")
        assert result.is_valid is True
    
    def test_city_name_exactly_50_chars(self, validator):
        """City name of exactly 50 chars should pass"""
        name = "A" * 50
        result = validator.validate_string_field(name, "city_name")
        assert result.is_valid is True
    
    def test_city_name_exceeds_50_chars(self, validator):
        """City name over 50 chars should fail with E224"""
        name = "A" * 51
        result = validator.validate_string_field(name, "city_name")
        assert result.is_valid is False
        assert result.error_code == "E224"
    
    # --- Building Name Tests (max 30 chars) ---
    
    def test_building_name_valid_length(self, validator):
        """Building name under 30 chars should pass"""
        result = validator.validate_string_field("Granary", "building_name")
        assert result.is_valid is True
    
    def test_building_name_exactly_30_chars(self, validator):
        """Building name of exactly 30 chars should pass"""
        name = "A" * 30
        result = validator.validate_string_field(name, "building_name")
        assert result.is_valid is True
    
    def test_building_name_exceeds_30_chars(self, validator):
        """Building name over 30 chars should fail with E224"""
        name = "A" * 31
        result = validator.validate_string_field(name, "building_name")
        assert result.is_valid is False
        assert result.error_code == "E224"
    
    # --- Tech Name Tests (max 50 chars) ---
    
    def test_tech_name_valid_length(self, validator):
        """Tech name under 50 chars should pass"""
        result = validator.validate_string_field("The Wheel", "tech_name")
        assert result.is_valid is True
    
    def test_tech_name_exactly_50_chars(self, validator):
        """Tech name of exactly 50 chars should pass"""
        name = "T" * 50
        result = validator.validate_string_field(name, "tech_name")
        assert result.is_valid is True
    
    def test_tech_name_exceeds_50_chars(self, validator):
        """Tech name over 50 chars should fail with E224"""
        name = "T" * 51
        result = validator.validate_string_field(name, "tech_name")
        assert result.is_valid is False
        assert result.error_code == "E224"
    
    # --- Message Tests (max 256 chars) ---
    
    def test_message_valid_length(self, validator):
        """Message under 256 chars should pass"""
        result = validator.validate_string_field("Hello, would you like to trade?", "message")
        assert result.is_valid is True
    
    def test_message_exactly_256_chars(self, validator):
        """Message of exactly 256 chars should pass"""
        msg = "A" * 256
        result = validator.validate_string_field(msg, "message")
        assert result.is_valid is True
    
    def test_message_exceeds_256_chars(self, validator):
        """Message over 256 chars should fail with E224"""
        msg = "A" * 257
        result = validator.validate_string_field(msg, "message")
        assert result.is_valid is False
        assert result.error_code == "E224"
    
    # --- Agent ID Tests (max 50 chars) ---
    
    def test_agent_id_valid_length(self, validator):
        """Agent ID under 50 chars should pass"""
        result = validator.validate_string_field("my-agent-123", "agent_id")
        assert result.is_valid is True
    
    def test_agent_id_exactly_50_chars(self, validator):
        """Agent ID of exactly 50 chars should pass"""
        agent_id = "a" * 50
        result = validator.validate_string_field(agent_id, "agent_id")
        assert result.is_valid is True  # All lowercase alpha is valid for agent_id
        
    def test_agent_id_50_with_valid_chars(self, validator):
        """Agent ID of 50 chars with valid chars should pass"""
        agent_id = "agent-" + "a" * 44  # 6 + 44 = 50
        result = validator.validate_string_field(agent_id, "agent_id")
        assert result.is_valid is True
    
    def test_agent_id_exceeds_50_chars(self, validator):
        """Agent ID over 50 chars should fail with E224"""
        agent_id = "a" * 51
        result = validator.validate_string_field(agent_id, "agent_id")
        assert result.is_valid is False
        assert result.error_code == "E224"


class TestCharacterAllowlistValidation:
    """Test character allowlist validation per Protocol v2.0.1"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    # --- City Name Pattern: [a-zA-Z0-9 _-] ---
    
    def test_city_name_alphanumeric(self, validator):
        """City name with alphanumeric chars should pass"""
        result = validator.validate_string_field("Rome123", "city_name")
        assert result.is_valid is True
    
    def test_city_name_with_spaces(self, validator):
        """City name with spaces should pass"""
        result = validator.validate_string_field("New York", "city_name")
        assert result.is_valid is True
    
    def test_city_name_with_underscore(self, validator):
        """City name with underscore should pass"""
        result = validator.validate_string_field("New_York", "city_name")
        assert result.is_valid is True
    
    def test_city_name_with_hyphen(self, validator):
        """City name with hyphen should pass"""
        result = validator.validate_string_field("City-State", "city_name")
        assert result.is_valid is True
    
    def test_city_name_with_special_chars_fails(self, validator):
        """City name with special chars should fail with E223"""
        result = validator.validate_string_field("City@#$%", "city_name")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_city_name_with_unicode_fails(self, validator):
        """City name with unicode should fail with E223"""
        result = validator.validate_string_field("北京", "city_name")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    # --- Building Name Pattern: [a-zA-Z0-9_ ] ---
    
    def test_building_name_valid_chars(self, validator):
        """Building name with valid chars should pass"""
        result = validator.validate_string_field("City Walls", "building_name")
        assert result.is_valid is True
    
    def test_building_name_with_hyphen_fails(self, validator):
        """Building name with hyphen should fail (not in pattern)"""
        result = validator.validate_string_field("City-Walls", "building_name")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    # --- Agent ID Pattern: [a-zA-Z0-9_-] ---
    
    def test_agent_id_valid_chars(self, validator):
        """Agent ID with valid chars should pass"""
        result = validator.validate_string_field("agent_123-v2", "agent_id")
        assert result.is_valid is True
    
    def test_agent_id_with_space_fails(self, validator):
        """Agent ID with space should fail (not in pattern)"""
        result = validator.validate_string_field("agent 123", "agent_id")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_agent_id_with_dot_fails(self, validator):
        """Agent ID with dot should fail (not in pattern)"""
        result = validator.validate_string_field("agent.123", "agent_id")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    # --- Message Pattern: [a-zA-Z0-9 .,!?'"()-] ---
    
    def test_message_with_punctuation(self, validator):
        """Message with allowed punctuation should pass"""
        result = validator.validate_string_field("Hello! How are you?", "message")
        assert result.is_valid is True
    
    def test_message_with_quotes(self, validator):
        """Message with quotes should pass"""
        result = validator.validate_string_field("He said 'Hello'", "message")
        assert result.is_valid is True
    
    def test_message_with_parens(self, validator):
        """Message with parentheses should pass"""
        result = validator.validate_string_field("Trade (gold for maps)", "message")
        assert result.is_valid is True
    
    def test_message_empty_string(self, validator):
        """Empty message should pass (0 length is <= 256)"""
        result = validator.validate_string_field("", "message")
        assert result.is_valid is True


class TestSQLInjectionDetection:
    """Test SQL injection pattern detection"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    def test_select_injection(self, validator):
        """SELECT statement should be detected"""
        result = validator.detect_sql_injection("name'; SELECT * FROM users--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_drop_injection(self, validator):
        """DROP statement should be detected"""
        result = validator.detect_sql_injection("city'; DROP TABLE users;--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_union_injection(self, validator):
        """UNION statement should be detected"""
        result = validator.detect_sql_injection("1 UNION SELECT password FROM users")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_insert_injection(self, validator):
        """INSERT statement should be detected"""
        result = validator.detect_sql_injection("name'; INSERT INTO admins VALUES('hacker')--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_update_injection(self, validator):
        """UPDATE statement should be detected"""
        result = validator.detect_sql_injection("name'; UPDATE users SET admin=1--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_delete_injection(self, validator):
        """DELETE statement should be detected"""
        result = validator.detect_sql_injection("name'; DELETE FROM users--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_comment_injection(self, validator):
        """SQL comment markers should be detected"""
        result = validator.detect_sql_injection("admin'--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_block_comment_injection(self, validator):
        """Block comment markers should be detected"""
        result = validator.detect_sql_injection("admin/* comment */")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_or_1_equals_1(self, validator):
        """OR 1=1 pattern should be detected"""
        result = validator.detect_sql_injection("admin' OR 1=1--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_and_1_equals_1(self, validator):
        """AND 1=1 pattern should be detected"""
        result = validator.detect_sql_injection("admin' AND 1=1--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_exec_injection(self, validator):
        """EXEC statement should be detected"""
        result = validator.detect_sql_injection("'; EXEC xp_cmdshell('cmd')--")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_valid_input_passes(self, validator):
        """Normal input should pass SQL injection check"""
        result = validator.detect_sql_injection("New York City")
        assert result.is_valid is True
    
    def test_case_insensitive(self, validator):
        """SQL injection detection should be case-insensitive"""
        result = validator.detect_sql_injection("select * from users")
        assert result.is_valid is False


class TestXSSDetection:
    """Test XSS pattern detection"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    def test_script_tag(self, validator):
        """Script tag should be detected"""
        result = validator.detect_xss("<script>alert('xss')</script>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_script_tag_with_src(self, validator):
        """Script tag with src should be detected"""
        result = validator.detect_xss("<script src='evil.js'></script>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_javascript_url(self, validator):
        """javascript: URL should be detected"""
        result = validator.detect_xss("javascript:alert('xss')")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_onclick_handler(self, validator):
        """onclick handler should be detected"""
        result = validator.detect_xss("<div onclick='alert(1)'>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_onerror_handler(self, validator):
        """onerror handler should be detected"""
        result = validator.detect_xss("<img onerror='alert(1)'>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_iframe_tag(self, validator):
        """iframe tag should be detected"""
        result = validator.detect_xss("<iframe src='evil.html'>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_object_tag(self, validator):
        """object tag should be detected"""
        result = validator.detect_xss("<object data='evil.swf'>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_embed_tag(self, validator):
        """embed tag should be detected"""
        result = validator.detect_xss("<embed src='evil.swf'>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_svg_onload(self, validator):
        """SVG with onload should be detected"""
        result = validator.detect_xss("<svg onload='alert(1)'>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_img_onerror(self, validator):
        """img with onerror should be detected"""
        result = validator.detect_xss("<img src=x onerror='alert(1)'>")
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_valid_input_passes(self, validator):
        """Normal input should pass XSS check"""
        result = validator.detect_xss("Hello, would you like to trade?")
        assert result.is_valid is True
    
    def test_html_entities_allowed(self, validator):
        """HTML entities like &amp; should pass (they're safe)"""
        result = validator.detect_xss("Tom &amp; Jerry")
        assert result.is_valid is True


class TestCoordinateValidation:
    """Test coordinate range validation (0-9999)"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    def test_valid_coordinate_zero(self, validator):
        """Coordinate 0 should pass"""
        result = validator.validate_coordinate(0, "x")
        assert result.is_valid is True
    
    def test_valid_coordinate_max(self, validator):
        """Coordinate 9999 should pass"""
        result = validator.validate_coordinate(9999, "y")
        assert result.is_valid is True
    
    def test_valid_coordinate_middle(self, validator):
        """Coordinate in middle of range should pass"""
        result = validator.validate_coordinate(500, "tile")
        assert result.is_valid is True
    
    def test_negative_coordinate_fails(self, validator):
        """Negative coordinate should fail with E251"""
        result = validator.validate_coordinate(-1, "x")
        assert result.is_valid is False
        assert result.error_code == "E251"
    
    def test_coordinate_exceeds_max_fails(self, validator):
        """Coordinate > 9999 should fail with E251"""
        result = validator.validate_coordinate(10000, "y")
        assert result.is_valid is False
        assert result.error_code == "E251"
    
    def test_coordinate_float_fails(self, validator):
        """Float coordinate should fail with E221"""
        result = validator.validate_coordinate(5.5, "x")
        assert result.is_valid is False
        assert result.error_code == "E221"
    
    def test_coordinate_string_fails(self, validator):
        """String coordinate should fail with E221"""
        result = validator.validate_coordinate("100", "x")
        assert result.is_valid is False
        assert result.error_code == "E221"
    
    def test_coordinate_none_fails(self, validator):
        """None coordinate should fail with E220"""
        result = validator.validate_coordinate(None, "x")
        assert result.is_valid is False
        assert result.error_code == "E220"
    
    def test_coordinate_bool_fails(self, validator):
        """Boolean should fail as coordinate (not true integer)"""
        result = validator.validate_coordinate(True, "x")
        assert result.is_valid is False
        assert result.error_code == "E221"


class TestSanitization:
    """Test input sanitization functions"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    def test_remove_null_bytes(self, validator):
        """Null bytes should be removed"""
        result = validator.sanitize_string("Hello\x00World")
        assert result == "HelloWorld"
    
    def test_remove_control_chars(self, validator):
        """Control characters should be removed"""
        result = validator.sanitize_string("Hello\x01\x02\x03World")
        assert result == "HelloWorld"
    
    def test_preserve_newline(self, validator):
        """Newlines should be preserved"""
        result = validator.sanitize_string("Hello\nWorld")
        assert result == "Hello\nWorld"
    
    def test_preserve_tab(self, validator):
        """Tabs should be preserved"""
        result = validator.sanitize_string("Hello\tWorld")
        assert result == "Hello\tWorld"
    
    def test_strip_whitespace(self, validator):
        """Leading/trailing whitespace should be stripped"""
        result = validator.sanitize_string("  Hello World  ")
        assert result == "Hello World"
    
    def test_strip_xss_script(self, validator):
        """Script tags should be stripped"""
        result = validator.strip_xss("Hello<script>alert(1)</script>World")
        assert "<script>" not in result
        assert "</script>" not in result
    
    def test_strip_xss_javascript(self, validator):
        """javascript: URLs should be stripped"""
        result = validator.strip_xss("Click javascript:alert(1)")
        assert "javascript:" not in result
    
    def test_strip_xss_event_handler(self, validator):
        """Event handlers should be stripped"""
        result = validator.strip_xss("<div onclick='alert(1)'>text</div>")
        assert "onclick" not in result


class TestEntityIdValidation:
    """Test entity ID validation (unit_id, city_id, etc.)"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    def test_valid_entity_id(self, validator):
        """Valid entity ID should pass"""
        result = validator.validate_entity_id(123, "unit_id")
        assert result.is_valid is True
    
    def test_zero_entity_id(self, validator):
        """Zero entity ID should pass (0 is valid)"""
        result = validator.validate_entity_id(0, "city_id")
        assert result.is_valid is True
    
    def test_max_entity_id(self, validator):
        """Max entity ID should pass"""
        result = validator.validate_entity_id(999999, "player_id")
        assert result.is_valid is True
    
    def test_negative_entity_id_fails(self, validator):
        """Negative entity ID should fail with E222"""
        result = validator.validate_entity_id(-1, "unit_id")
        assert result.is_valid is False
        assert result.error_code == "E222"
    
    def test_entity_id_exceeds_max_fails(self, validator):
        """Entity ID > 999999 should fail with E222"""
        result = validator.validate_entity_id(1000000, "unit_id")
        assert result.is_valid is False
        assert result.error_code == "E222"
    
    def test_entity_id_string_fails(self, validator):
        """String entity ID should fail with E221"""
        result = validator.validate_entity_id("123", "unit_id")
        assert result.is_valid is False
        assert result.error_code == "E221"
    
    def test_entity_id_none_fails(self, validator):
        """None entity ID should fail with E220"""
        result = validator.validate_entity_id(None, "unit_id")
        assert result.is_valid is False
        assert result.error_code == "E220"
    
    def test_entity_id_bool_fails(self, validator):
        """Boolean should fail as entity ID"""
        result = validator.validate_entity_id(True, "unit_id")
        assert result.is_valid is False
        assert result.error_code == "E221"


class TestActionParamsValidation:
    """Test validation of action parameters"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    def test_valid_unit_move_params(self, validator):
        """Valid unit_move params should pass"""
        params = {'unit_id': 123, 'x': 10, 'y': 20}
        result = validator.validate_action_params('unit_move', params)
        assert result.is_valid is True
    
    def test_unit_move_invalid_coordinate(self, validator):
        """unit_move with invalid coordinate should fail"""
        params = {'unit_id': 123, 'x': -1, 'y': 20}
        result = validator.validate_action_params('unit_move', params)
        assert result.is_valid is False
        assert result.error_code == "E251"
    
    def test_unit_move_invalid_unit_id(self, validator):
        """unit_move with invalid unit_id should fail"""
        params = {'unit_id': "abc", 'x': 10, 'y': 20}
        result = validator.validate_action_params('unit_move', params)
        assert result.is_valid is False
        assert result.error_code == "E221"
    
    def test_unit_found_city_valid(self, validator):
        """unit_found_city with valid city name should pass"""
        params = {'unit_id': 123, 'city_name': 'New York'}
        result = validator.validate_action_params('unit_found_city', params)
        assert result.is_valid is True
    
    def test_unit_found_city_sql_injection(self, validator):
        """unit_found_city with SQL injection should fail"""
        params = {'unit_id': 123, 'city_name': "New York'; DROP TABLE--"}
        result = validator.validate_action_params('unit_found_city', params)
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_unit_found_city_xss(self, validator):
        """unit_found_city with XSS should fail"""
        params = {'unit_id': 123, 'city_name': "<script>alert(1)</script>"}
        result = validator.validate_action_params('unit_found_city', params)
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_diplomacy_message_valid(self, validator):
        """diplomacy_message with valid message should pass"""
        params = {'player_id': 2, 'message': 'Would you like to trade?'}
        result = validator.validate_action_params('diplomacy_message', params)
        assert result.is_valid is True
    
    def test_diplomacy_message_sql_injection(self, validator):
        """diplomacy_message with SQL injection should fail"""
        params = {'player_id': 2, 'message': "Hello'; SELECT * FROM users--"}
        result = validator.validate_action_params('diplomacy_message', params)
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_diplomacy_message_xss(self, validator):
        """diplomacy_message with XSS should fail"""
        params = {'player_id': 2, 'message': "<script>stealCookies()</script>"}
        result = validator.validate_action_params('diplomacy_message', params)
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_city_production_valid(self, validator):
        """city_production with valid building should pass"""
        params = {'city_id': 456, 'building': 'Granary'}
        result = validator.validate_action_params('city_production', params)
        assert result.is_valid is True
    
    def test_city_production_invalid_building_name(self, validator):
        """city_production with invalid building name should fail"""
        params = {'city_id': 456, 'building': 'Granary@#$%'}
        result = validator.validate_action_params('city_production', params)
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_tech_research_valid(self, validator):
        """tech_research with valid tech should pass"""
        params = {'tech': 'The Wheel'}
        result = validator.validate_action_params('tech_research', params)
        assert result.is_valid is True
    
    def test_tech_research_invalid_tech_name(self, validator):
        """tech_research with invalid tech name should fail"""
        params = {'tech': 'The@Wheel'}
        result = validator.validate_action_params('tech_research', params)
        assert result.is_valid is False
        assert result.error_code == "E223"
    
    def test_params_not_dict_fails(self, validator):
        """Non-dict params should fail with E221"""
        result = validator.validate_action_params('unit_move', "not a dict")
        assert result.is_valid is False
        assert result.error_code == "E221"


class TestNullAndTypeValidation:
    """Test null and type validation edge cases"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    def test_string_field_none(self, validator):
        """None value for string field should fail with E220"""
        result = validator.validate_string_field(None, "city_name")
        assert result.is_valid is False
        assert result.error_code == "E220"
    
    def test_string_field_wrong_type(self, validator):
        """Non-string value for string field should fail with E221"""
        result = validator.validate_string_field(123, "city_name")
        assert result.is_valid is False
        assert result.error_code == "E221"
    
    def test_string_field_list_fails(self, validator):
        """List value for string field should fail with E221"""
        result = validator.validate_string_field(["city"], "city_name")
        assert result.is_valid is False
        assert result.error_code == "E221"
    
    def test_string_field_dict_fails(self, validator):
        """Dict value for string field should fail with E221"""
        result = validator.validate_string_field({"name": "city"}, "city_name")
        assert result.is_valid is False
        assert result.error_code == "E221"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
