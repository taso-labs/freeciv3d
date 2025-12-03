#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Safe Access Utilities for LLM API Gateway
Provides defensive programming utilities to prevent KeyError crashes
"""

import logging
from typing import Any, Dict, List, Optional, Union, Callable

logger = logging.getLogger("llm-gateway")


def safe_get_nested(
    data: Dict[str, Any],
    keys: Union[List[str], str],
    *additional_keys: str,
    default: Any = None,
    required: bool = False
) -> Any:
    """
    Safely navigate nested dictionaries without raising KeyError

    Args:
        data: The dictionary to navigate
        keys: Either a list of keys or the first key (for backward compatibility)
        *additional_keys: Additional keys if first arg was a string
        default: Default value if key path doesn't exist
        required: If True, raises ValueError instead of returning default

    Returns:
        The value at the nested key path, or default if not found

    Raises:
        ValueError: If required=True and key path not found
        TypeError: If intermediate value is not a dictionary

    Examples:
        >>> data = {"agents": {"agent1": {"config": {"game_id": "game123"}}}}
        >>> safe_get_nested(data, ["agents", "agent1", "config", "game_id"])
        "game123"
        >>> safe_get_nested(data, "agents", "agent1", "config", "game_id")  # Also works
        "game123"
        >>> safe_get_nested(data, ["agents", "missing", "config"], default="not_found")
        "not_found"
    """
    # Handle both list and varargs forms
    if isinstance(keys, list):
        key_list = keys
    else:
        key_list = [keys] + list(additional_keys)

    current = data
    key_path = []

    for key in key_list:
        key_path.append(str(key))

        if not isinstance(current, dict):
            if required:
                raise ValueError(
                    f"Expected dict at key path {' -> '.join(key_path[:-1])}, "
                    f"got {type(current).__name__}"
                )
            logger.debug(f"Non-dict value at {' -> '.join(key_path[:-1])}")
            return default

        if key not in current:
            if required:
                raise ValueError(f"Required key path not found: {' -> '.join(key_path)}")
            logger.debug(f"Key path not found: {' -> '.join(key_path)}")
            return default

        current = current[key]

    return current


def safe_get_list_item(
    data: List[Any],
    index: int,
    default: Any = None,
    required: bool = False
) -> Any:
    """
    Safely get an item from a list by index

    Args:
        data: The list to access
        index: Index to retrieve
        default: Default value if index is out of range
        required: If True, raises ValueError instead of returning default

    Returns:
        The item at the index, or default if out of range

    Raises:
        ValueError: If required=True and index is out of range
        TypeError: If data is not a list
    """
    if not isinstance(data, list):
        if required:
            raise TypeError(f"Expected list, got {type(data).__name__}")
        return default

    if index < 0 or index >= len(data):
        if required:
            raise ValueError(f"Index {index} out of range for list of length {len(data)}")
        return default

    return data[index]


def safe_get_attribute(
    obj: Any,
    attr_name: str,
    default: Any = None,
    required: bool = False
) -> Any:
    """
    Safely get an attribute from an object

    Args:
        obj: The object to access
        attr_name: Name of the attribute
        default: Default value if attribute doesn't exist
        required: If True, raises ValueError instead of returning default

    Returns:
        The attribute value, or default if not found
    """
    if not hasattr(obj, attr_name):
        if required:
            raise ValueError(f"Required attribute '{attr_name}' not found on {type(obj).__name__}")
        return default

    return getattr(obj, attr_name)


def validate_dict_structure(
    data: Dict[str, Any],
    schema: Dict[str, Any],
    strict: bool = False
) -> Dict[str, List[str]]:
    """
    Validate dictionary structure against a schema

    Args:
        data: Dictionary to validate
        schema: Schema dictionary defining required structure
        strict: If True, extra keys in data are considered errors

    Returns:
        Dict with 'errors' and 'warnings' lists

    Schema format:
        {
            "required_key": {
                "type": str,  # Expected type
                "required": True,  # Whether key is required
                "nested": {...}  # For nested validation
            }
        }
    """
    errors = []
    warnings = []

    def validate_nested(current_data, current_schema, path=""):
        for key, schema_info in current_schema.items():
            current_path = f"{path}.{key}" if path else key

            # Check if required key exists
            if schema_info.get("required", False) and key not in current_data:
                errors.append(f"Required key missing: {current_path}")
                continue

            if key not in current_data:
                continue

            value = current_data[key]
            expected_type = schema_info.get("type")

            # Type validation
            if expected_type and not isinstance(value, expected_type):
                errors.append(
                    f"Type mismatch at {current_path}: "
                    f"expected {expected_type.__name__}, got {type(value).__name__}"
                )
                continue

            # Nested validation
            if "nested" in schema_info and isinstance(value, dict):
                validate_nested(value, schema_info["nested"], current_path)

        # Check for extra keys in strict mode
        if strict:
            for key in current_data:
                if key not in current_schema:
                    warnings.append(f"Extra key found: {path}.{key}" if path else key)

    validate_nested(data, schema)

    return {
        "errors": errors,
        "warnings": warnings
    }


def safe_update_nested(
    data: Dict[str, Any],
    value: Any,
    *keys: str,
    create_missing: bool = True
) -> bool:
    """
    Safely update a value in a nested dictionary

    Args:
        data: Dictionary to update
        value: Value to set
        *keys: Key path to the value
        create_missing: Whether to create missing intermediate dictionaries

    Returns:
        True if update was successful, False otherwise
    """
    if not keys:
        return False

    current = data

    # Navigate to the parent of the target key
    for key in keys[:-1]:
        if key not in current:
            if create_missing:
                current[key] = {}
            else:
                return False

        if not isinstance(current[key], dict):
            if create_missing:
                current[key] = {}
            else:
                return False

        current = current[key]

    # Set the final value
    current[keys[-1]] = value
    return True


class SafeDict:
    """
    A wrapper around dict that provides safe access methods
    """

    def __init__(self, data: Dict[str, Any] = None):
        self._data = data or {}

    def get_nested(self, *keys: str, default: Any = None, required: bool = False) -> Any:
        """Safe nested access"""
        return safe_get_nested(self._data, *keys, default=default, required=required)

    def set_nested(self, value: Any, *keys: str, create_missing: bool = True) -> bool:
        """Safe nested update"""
        return safe_update_nested(self._data, value, *keys, create_missing=create_missing)

    def has_path(self, *keys: str) -> bool:
        """Check if a key path exists"""
        try:
            safe_get_nested(self._data, *keys, required=True)
            return True
        except ValueError:
            return False

    def to_dict(self) -> Dict[str, Any]:
        """Get the underlying dictionary"""
        return self._data

    def __getitem__(self, key: str) -> Any:
        """Direct access (use with caution)"""
        return self._data[key]

    def __setitem__(self, key: str, value: Any):
        """Direct assignment"""
        self._data[key] = value

    def __contains__(self, key: str) -> bool:
        """Check if key exists"""
        return key in self._data


def create_agent_accessor(active_agents: Dict[str, Any]) -> Callable[[str], SafeDict]:
    """
    Create a safe accessor function for agent data

    Args:
        active_agents: The active agents dictionary

    Returns:
        Function that safely accesses agent data
    """
    def get_agent_data(agent_id: str) -> SafeDict:
        agent_data = active_agents.get(agent_id, {})
        return SafeDict(agent_data)

    return get_agent_data


# Specific utility functions for common LLM Gateway patterns

def get_agent_game_id(active_agents: Dict[str, Any], agent_id: str) -> Optional[str]:
    """
    Safely get game_id for an agent (addresses the specific issue from line 538)

    Args:
        active_agents: The active agents dictionary
        agent_id: Agent identifier

    Returns:
        Game ID if found, None otherwise
    """
    return safe_get_nested(active_agents, agent_id, "config", "game_id")


def get_agent_config(active_agents: Dict[str, Any], agent_id: str) -> Optional[Dict[str, Any]]:
    """
    Safely get agent configuration

    Args:
        active_agents: The active agents dictionary
        agent_id: Agent identifier

    Returns:
        Agent config dictionary if found, None if agent doesn't exist or has no config
    """
    # First check if agent exists
    if agent_id not in active_agents:
        return None

    # Direct access since we already verified existence
    agent_data = active_agents[agent_id]
    if "config" not in agent_data:
        return None

    return agent_data.get("config")


def validate_agent_registration(agent_data: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Validate agent registration data

    Args:
        agent_data: Agent registration data

    Returns:
        Validation results with errors and warnings
    """
    schema = {
        "api_token": {"type": str, "required": True},
        "model": {"type": str, "required": True},
        "game_id": {"type": str, "required": True},
        "timeout": {"type": (int, float), "required": False}
    }

    return validate_dict_structure(agent_data, schema)


def validate_game_session(session_data: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Validate game session data

    Args:
        session_data: Game session data

    Returns:
        Validation results with errors and warnings
    """
    schema = {
        "config": {
            "type": dict,
            "required": True,
            "nested": {
                "game_type": {"type": str, "required": True},
                "max_players": {"type": int, "required": False}
            }
        },
        "created_at": {"type": (int, float), "required": True},
        "status": {"type": str, "required": True},
        "players": {"type": dict, "required": True}
    }

    return validate_dict_structure(session_data, schema)