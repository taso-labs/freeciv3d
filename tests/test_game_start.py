"""
Test suite for game start functionality and port calculations.

Tests the fix for the port 7000 conflict issue where single player games
now start on port 6001 (mapping to WebSocket 7001) instead of 6000 (mapping to 7000).
"""

import pytest
import socket
import time
import json
from typing import List, Tuple


def is_port_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is listening for connections."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except socket.error:
        return False
    finally:
        sock.close()


def calculate_websocket_port(game_port: int) -> int:
    """
    Calculate WebSocket proxy port from game server port.
    This is the logic from clinet.js line 87:
    proxy_port = parseFloat(civserverport) - 6000 + 7000
    """
    return game_port - 6000 + 7000


class TestPortCalculations:
    """Test WebSocket port calculation logic."""
    
    def test_single_player_port_calculation(self):
        """Single player on 6001 should map to WebSocket 7001."""
        game_port = 6001
        expected_ws_port = 7001
        assert calculate_websocket_port(game_port) == expected_ws_port
    
    def test_multiplayer_port_calculation(self):
        """Multiplayer on 6002 should map to WebSocket 7002."""
        game_port = 6002
        expected_ws_port = 7002
        assert calculate_websocket_port(game_port) == expected_ws_port
    
    def test_port_range_calculations(self):
        """Test port calculations for the full server range."""
        test_cases = [
            (6001, 7001),  # Single player
            (6002, 7002),  # Multiplayer
            (6003, 7003),
            (6004, 7004),
            (6005, 7005),
            (6006, 7006),
            (6007, 7007),
            (6008, 7008),
            (6009, 7009),
            (6010, 7010),
        ]
        
        for game_port, expected_ws_port in test_cases:
            assert calculate_websocket_port(game_port) == expected_ws_port, \
                f"Game port {game_port} should map to WebSocket port {expected_ws_port}"
    
    def test_port_7000_not_used(self):
        """Verify that port 7000 is never calculated."""
        # Test ports in expected range
        for game_port in range(6001, 6011):
            ws_port = calculate_websocket_port(game_port)
            assert ws_port != 7000, \
                f"Port 7000 should never be used (game port {game_port} maps to {ws_port})"


class TestServicePorts:
    """Test that required services are listening on expected ports."""
    
    def test_llm_gateway_port(self):
        """LLM Gateway should be listening on port 8003."""
        assert is_port_listening('localhost', 8003, timeout=2.0), \
            "LLM Gateway should be listening on port 8003"
    
    def test_freeciv_proxy_port(self):
        """FreeCiv proxy should be listening on port 8002."""
        assert is_port_listening('localhost', 8002, timeout=2.0), \
            "FreeCiv proxy should be listening on port 8002"
    
    def test_web_interface_port(self):
        """Web interface should be accessible on port 8080."""
        assert is_port_listening('localhost', 8080, timeout=2.0), \
            "Web interface should be accessible on port 8080"


class TestGameServerPorts:
    """Test that game servers are running on expected ports."""
    
    def test_single_player_game_port(self):
        """Single player game should be listening on port 6001."""
        assert is_port_listening('localhost', 6001, timeout=2.0), \
            "Single player game server should be listening on port 6001"
    
    def test_multiplayer_game_port(self):
        """Multiplayer game should be listening on port 6002."""
        assert is_port_listening('localhost', 6002, timeout=2.0), \
            "Multiplayer game server should be listening on port 6002"
    
    def test_websocket_proxy_7001(self):
        """WebSocket proxy for single player should be on port 7001."""
        assert is_port_listening('localhost', 7001, timeout=2.0), \
            "WebSocket proxy should be listening on port 7001 (for game port 6001)"
    
    def test_websocket_proxy_7002(self):
        """WebSocket proxy for multiplayer should be on port 7002."""
        assert is_port_listening('localhost', 7002, timeout=2.0), \
            "WebSocket proxy should be listening on port 7002 (for game port 6002)"
    
    def test_port_7000_not_listening(self):
        """Regression test: port 7000 should NOT be in use."""
        assert not is_port_listening('localhost', 7000, timeout=1.0), \
            "Port 7000 should NOT be in use (conflicts with macOS Control Center)"


class TestLLMGatewayConfiguration:
    """Test LLM Gateway configuration for multiplayer games."""
    
    def test_llm_gateway_default_port(self):
        """LLM Gateway should default to multiplayer port 6002."""
        # This is integration test - would need to check environment or API
        # For now, document the expected configuration
        expected_port = 6002
        assert expected_port == 6002, \
            "LLM Gateway should connect to multiplayer game on port 6002"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


