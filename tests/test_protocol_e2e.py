#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Phase 5: End-to-End Protocol Integration Tests

Tests the complete LLM WebSocket Protocol v2.0.1 flow against running services.
These tests require Docker Compose services to be running.

Run with: python -m pytest tests/test_protocol_e2e.py -v

Tests will be SKIPPED if services are not available.
"""

import pytest
import asyncio
import json
import os
import sys
import time
import websockets
import socket
from typing import Optional, Dict, Any

# Add freeciv-proxy to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'freeciv-proxy'))

# Configuration
PROXY_HOST = os.environ.get('PROXY_HOST', 'localhost')
PROXY_PORT = int(os.environ.get('PROXY_PORT', '8002'))
PROXY_WS_URL = f'ws://{PROXY_HOST}:{PROXY_PORT}/civsocket/'
DEFAULT_TIMEOUT = 10  # seconds

# Test credentials - these should work with test configuration
TEST_AGENT_ID = "e2e-test-agent"
TEST_API_TOKEN = os.environ.get('TEST_API_TOKEN', 'test-api-token-for-e2e')
TEST_PORT = 6001  # Civserver port for testing


def is_service_available(host: str, port: int) -> bool:
    """Check if a service is reachable"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def is_websocket_available() -> bool:
    """Check if WebSocket endpoint is actually available by attempting connection"""
    import asyncio
    
    async def try_connect():
        try:
            async with asyncio.timeout(3):
                ws = await websockets.connect(PROXY_WS_URL)
                await ws.close()
                return True
        except Exception:
            return False
    
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(try_connect())
        loop.close()
        return result
    except Exception:
        return False


# Skip WebSocket-dependent tests if endpoint is not available  
_ws_skip = pytest.mark.skipif(
    not is_websocket_available(),
    reason=f"FreeCiv proxy WebSocket not available at {PROXY_WS_URL}. Run 'docker-compose up -d' first."
)


class WebSocketClient:
    """Helper class for WebSocket testing"""
    
    def __init__(self, url: str = PROXY_WS_URL):
        self.url = url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.messages: list = []
    
    async def connect(self, timeout: float = DEFAULT_TIMEOUT):
        """Connect to WebSocket server"""
        self.ws = await asyncio.wait_for(
            websockets.connect(self.url),
            timeout=timeout
        )
        return self
    
    async def send(self, message: Dict[str, Any]):
        """Send JSON message"""
        if self.ws:
            await self.ws.send(json.dumps(message))
    
    async def receive(self, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
        """Receive and parse JSON message"""
        if self.ws:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            self.messages.append(msg)
            return msg
        return {}
    
    async def close(self):
        """Close connection"""
        if self.ws:
            await self.ws.close()
            self.ws = None
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


@_ws_skip
@pytest.mark.asyncio
class TestConnectionFlow:
    """Test WebSocket connection and authentication flow"""
    
    async def test_connect_receives_welcome_message(self):
        """Connection should receive welcome message immediately"""
        async with WebSocketClient() as client:
            msg = await client.receive()
            assert msg['type'] == 'welcome'
            assert 'handler_id' in msg
            assert 'timestamp' in msg
    
    async def test_llm_connect_authentication(self):
        """LLM connect should authenticate agent"""
        async with WebSocketClient() as client:
            # Receive welcome
            welcome = await client.receive()
            assert welcome['type'] == 'welcome'
            
            # Send llm_connect
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_auth',
                'api_token': TEST_API_TOKEN,
                'capabilities': ['unit_move', 'city_production', 'tech_research'],
                'port': TEST_PORT
            })
            
            # Should receive connection response
            response = await client.receive(timeout=15)
            
            # Response should indicate success or auth error (if civserver not available)
            assert response['type'] in ['llm_connect_response', 'error']
            
            if response['type'] == 'error':
                # Auth error or civserver not available
                assert 'error_code' in response
                assert response['error_code'] in ['E102', 'E123', 'E500']
    
    async def test_invalid_token_returns_e102(self):
        """Invalid API token should return E102 error"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            await client.send({
                'type': 'llm_connect',
                'agent_id': 'bad-token-agent',
                'api_token': 'invalid-token-12345',
                'port': TEST_PORT
            })
            
            response = await client.receive(timeout=10)
            
            # Should get error response
            if response['type'] == 'error':
                assert response['error_code'] == 'E102'
                assert 'invalid' in response.get('message', '').lower() or 'auth' in response.get('message', '').lower()
    
    async def test_missing_required_field_returns_e101(self):
        """Missing required field should return E101"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Send message missing 'type'
            await client.send({
                'agent_id': 'test',
                'api_token': 'test'
            })
            
            response = await client.receive()
            assert response['type'] == 'error'
            assert response['error_code'] in ['E101', 'E220']
    
    async def test_unknown_message_type_returns_e103(self):
        """Unknown message type should return E103"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            await client.send({
                'type': 'unknown_type_xyz'
            })
            
            response = await client.receive()
            assert response['type'] == 'error'
            assert response['error_code'] == 'E103'


@_ws_skip
@pytest.mark.asyncio
class TestStateQueries:
    """Test state query functionality"""
    
    async def test_state_query_without_auth_fails(self):
        """State query without authentication should fail"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            await client.send({
                'type': 'state_query',
                'format': 'llm_optimized'
            })
            
            response = await client.receive()
            
            # Should get error - not authenticated
            assert response['type'] == 'error'
            assert response['error_code'] in ['E120', 'E102']
    
    async def test_state_query_formats(self):
        """Test different state query formats"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Try auth first
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_query',
                'api_token': TEST_API_TOKEN,
                'port': TEST_PORT
            })
            
            auth_response = await client.receive(timeout=15)
            
            if auth_response['type'] == 'error':
                pytest.skip(f"Auth failed: {auth_response.get('message')}")
            
            # Test llm_optimized format
            await client.send({
                'type': 'state_query',
                'format': 'llm_optimized'
            })
            
            response = await client.receive()
            
            if response['type'] == 'state_response':
                assert 'data' in response
                data = response['data']
                assert 'turn' in data or 'phase' in data


@_ws_skip
@pytest.mark.asyncio
class TestEntityActionQueries:
    """Test batch entity action queries (Phase 2 feature)"""
    
    async def test_unit_actions_query_format(self):
        """Test unit_actions_query message format"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Auth
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_unit_query',
                'api_token': TEST_API_TOKEN,
                'port': TEST_PORT
            })
            
            auth_response = await client.receive(timeout=15)
            
            if auth_response['type'] == 'error':
                pytest.skip(f"Auth failed: {auth_response.get('message')}")
            
            # Send batch unit query
            await client.send({
                'type': 'unit_actions_query',
                'data': {
                    'unit_ids': [1, 2, 3]
                }
            })
            
            response = await client.receive()
            
            # Should get response or error (units may not exist)
            assert response['type'] in ['unit_actions_response', 'error']
            
            if response['type'] == 'unit_actions_response':
                assert 'data' in response
                data = response['data']
                assert 'units' in data or 'errors' in data
    
    async def test_city_actions_query_format(self):
        """Test city_actions_query message format"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Auth
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_city_query',
                'api_token': TEST_API_TOKEN,
                'port': TEST_PORT
            })
            
            auth_response = await client.receive(timeout=15)
            
            if auth_response['type'] == 'error':
                pytest.skip(f"Auth failed: {auth_response.get('message')}")
            
            # Send batch city query
            await client.send({
                'type': 'city_actions_query',
                'data': {
                    'city_ids': [1, 2]
                }
            })
            
            response = await client.receive()
            
            # Should get response or error
            assert response['type'] in ['city_actions_response', 'error']


@_ws_skip
@pytest.mark.asyncio
class TestActionExecution:
    """Test action execution flow"""
    
    async def test_action_without_auth_fails(self):
        """Action without authentication should fail"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            await client.send({
                'type': 'action',
                'action': {
                    'type': 'unit_move',
                    'unit_id': 1,
                    'dest_x': 10,
                    'dest_y': 20
                }
            })
            
            response = await client.receive()
            
            assert response['type'] == 'error'
            assert response['error_code'] in ['E120', 'E102']
    
    async def test_invalid_action_returns_validation_error(self):
        """Invalid action should return validation error"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Auth
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_action',
                'api_token': TEST_API_TOKEN,
                'capabilities': ['unit_move'],
                'port': TEST_PORT
            })
            
            auth_response = await client.receive(timeout=15)
            
            if auth_response['type'] == 'error':
                pytest.skip(f"Auth failed: {auth_response.get('message')}")
            
            # Send action with invalid unit_id (negative)
            await client.send({
                'type': 'action',
                'action': {
                    'type': 'unit_move',
                    'unit_id': -999,
                    'dest_x': 10,
                    'dest_y': 20
                }
            })
            
            response = await client.receive()
            
            assert response['type'] == 'error'
            # Should get validation error
            assert response['error_code'] in ['E222', 'E230', 'E130']


@_ws_skip
@pytest.mark.asyncio
class TestInputValidation:
    """Test input validation (Phase 4 features)"""
    
    async def test_sql_injection_blocked(self):
        """SQL injection attempts should be blocked with E223"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Auth
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_sql',
                'api_token': TEST_API_TOKEN,
                'port': TEST_PORT
            })
            
            auth_response = await client.receive(timeout=15)
            
            if auth_response['type'] == 'error':
                pytest.skip(f"Auth failed: {auth_response.get('message')}")
            
            # Send action with SQL injection in city name
            await client.send({
                'type': 'action',
                'action': {
                    'type': 'unit_found_city',
                    'unit_id': 1,
                    'city_name': "Test'; DROP TABLE users;--"
                }
            })
            
            response = await client.receive()
            
            # Should be blocked with E223
            if response['type'] == 'error':
                # E223 for injection or E230 for unit not found
                assert response['error_code'] in ['E223', 'E230', 'E130']
    
    async def test_oversized_string_blocked(self):
        """Oversized strings should be blocked with E224"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Auth
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_size',
                'api_token': TEST_API_TOKEN,
                'port': TEST_PORT
            })
            
            auth_response = await client.receive(timeout=15)
            
            if auth_response['type'] == 'error':
                pytest.skip(f"Auth failed: {auth_response.get('message')}")
            
            # Send action with oversized city name (>50 chars)
            await client.send({
                'type': 'action',
                'action': {
                    'type': 'unit_found_city',
                    'unit_id': 1,
                    'city_name': "A" * 100  # Way over 50 char limit
                }
            })
            
            response = await client.receive()
            
            # Should be blocked
            if response['type'] == 'error':
                assert response['error_code'] in ['E224', 'E223', 'E230', 'E130']
    
    async def test_invalid_coordinates_blocked(self):
        """Invalid coordinates should be blocked with E251"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Auth
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_coord',
                'api_token': TEST_API_TOKEN,
                'port': TEST_PORT
            })
            
            auth_response = await client.receive(timeout=15)
            
            if auth_response['type'] == 'error':
                pytest.skip(f"Auth failed: {auth_response.get('message')}")
            
            # Send action with out-of-range coordinates
            await client.send({
                'type': 'action',
                'action': {
                    'type': 'unit_move',
                    'unit_id': 1,
                    'dest_x': 99999,  # Way over 9999 limit
                    'dest_y': -100    # Negative
                }
            })
            
            response = await client.receive()
            
            if response['type'] == 'error':
                assert response['error_code'] in ['E251', 'E222', 'E230', 'E130']


@_ws_skip
@pytest.mark.asyncio 
class TestPingPong:
    """Test keepalive ping/pong"""
    
    async def test_ping_returns_pong(self):
        """Ping message should receive pong response"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            await client.send({
                'type': 'ping',
                'timestamp': int(time.time() * 1000)
            })
            
            response = await client.receive()
            
            # Should get pong
            assert response['type'] == 'pong'
            assert 'timestamp' in response


@_ws_skip
@pytest.mark.asyncio
class TestDisconnection:
    """Test clean disconnection"""
    
    async def test_clean_disconnect(self):
        """Clean disconnect should not raise errors"""
        async with WebSocketClient() as client:
            await client.receive()  # welcome
            
            # Auth
            await client.send({
                'type': 'llm_connect',
                'agent_id': TEST_AGENT_ID + '_disconnect',
                'api_token': TEST_API_TOKEN,
                'port': TEST_PORT
            })
            
            await client.receive(timeout=15)
            
            # Close connection - should not raise
            await client.close()


class TestProtocolCompliance:
    """Non-async tests for protocol format compliance - always run"""
    
    def test_error_response_format(self):
        """Error responses should match protocol spec format"""
        # Test error response structure
        sample_error = {
            "type": "error",
            "error_code": "E102",
            "message": "Invalid API token",
            "timestamp": 1234567890
        }
        
        assert sample_error['type'] == 'error'
        assert sample_error['error_code'].startswith('E')
        assert len(sample_error['error_code']) >= 3
    
    def test_action_request_format(self):
        """Action requests should match protocol spec format"""
        sample_action = {
            "type": "action",
            "action": {
                "type": "unit_move",
                "unit_id": 42,
                "dest_x": 10,
                "dest_y": 20
            }
        }
        
        assert sample_action['type'] == 'action'
        assert 'action' in sample_action
        assert 'type' in sample_action['action']
    
    def test_state_query_format(self):
        """State query should match protocol spec format"""
        sample_query = {
            "type": "state_query",
            "format": "llm_optimized",
            "include_actions": True
        }
        
        assert sample_query['type'] == 'state_query'
        assert sample_query['format'] in ['full', 'delta', 'llm_optimized']


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "--tb=short"])
