#!/usr/bin/env python3
"""
Test script for FreeCiv LLM WebSocket Gateway
Tests the full LLM integration including authentication, state queries, and actions
"""

import asyncio
import json
import logging
import time
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FreeCivLLMTester:
    """Test client for FreeCiv LLM WebSocket gateway"""

    def __init__(self, host="localhost", port=8002):
        self.host = host
        self.port = port
        self.websocket = None
        self.agent_id = "test-agent-001"
        self.session_id = None
        self.player_id = None

    async def connect(self):
        """Connect to the WebSocket server"""
        uri = f"ws://{self.host}:{self.port}/llmsocket/{self.port}"
        logger.info(f"Connecting to {uri}")

        try:
            self.websocket = await websockets.connect(uri)
            logger.info("✓ Connected to WebSocket")
            return True
        except Exception as e:
            logger.error(f"✗ Connection failed: {e}")
            return False

    async def send_message(self, message):
        """Send a message and wait for response"""
        if not self.websocket:
            raise Exception("Not connected")

        logger.info(f"Sending: {json.dumps(message, indent=2)}")
        await self.websocket.send(json.dumps(message))

        # Wait for response
        response = await self.websocket.recv()
        parsed_response = json.loads(response)
        logger.info(f"Received: {json.dumps(parsed_response, indent=2)}")

        return parsed_response

    async def test_authentication(self):
        """Test LLM authentication flow"""
        logger.info("=== Testing Authentication ===")

        auth_message = {
            "type": "llm_connect",
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "data": {
                "api_token": "test-token-fc3d-001",
                "model": "gpt-4",
                "game_id": "test-game-001",
                "capabilities": ["move", "build", "research"]
            }
        }

        try:
            response = await self.send_message(auth_message)

            if response.get("type") == "auth_success":
                self.session_id = response.get("session_id")
                self.player_id = response.get("player_id")
                logger.info(f"✓ Authentication successful - Session: {self.session_id}, Player: {self.player_id}")
                return True
            else:
                logger.error(f"✗ Authentication failed: {response}")
                return False

        except Exception as e:
            logger.error(f"✗ Authentication error: {e}")
            return False

    async def test_state_query(self):
        """Test state query functionality"""
        logger.info("=== Testing State Query ===")

        state_query = {
            "type": "state_query",
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "data": {
                "format": "llm_optimized",
                "include_legal_actions": True,
                "player_perspective": self.player_id
            }
        }

        try:
            response = await self.send_message(state_query)

            if response.get("type") == "state_response":
                logger.info("✓ State query successful")
                state_data = response.get("data", {})
                logger.info(f"  - Turn: {state_data.get('turn', 'unknown')}")
                logger.info(f"  - Phase: {state_data.get('phase', 'unknown')}")
                logger.info(f"  - Cached: {response.get('cached', False)}")
                return True
            else:
                logger.error(f"✗ State query failed: {response}")
                return False

        except Exception as e:
            logger.error(f"✗ State query error: {e}")
            return False

    async def test_action(self):
        """Test action submission"""
        logger.info("=== Testing Action Submission ===")

        action_message = {
            "type": "action",
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "data": {
                "action_type": "end_turn",
                "actor_id": self.player_id,
                "parameters": {}
            }
        }

        try:
            response = await self.send_message(action_message)

            if response.get("type") in ["action_accepted", "action_rejected"]:
                if response.get("type") == "action_accepted":
                    logger.info("✓ Action accepted")
                else:
                    logger.info(f"○ Action rejected (expected): {response.get('error_message', 'No reason given')}")
                return True
            else:
                logger.error(f"✗ Action submission failed: {response}")
                return False

        except Exception as e:
            logger.error(f"✗ Action submission error: {e}")
            return False

    async def test_ping(self):
        """Test ping functionality"""
        logger.info("=== Testing Ping ===")

        ping_message = {
            "type": "ping",
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "data": {}
        }

        try:
            response = await self.send_message(ping_message)

            if response.get("type") == "pong":
                logger.info("✓ Ping successful")
                return True
            else:
                logger.error(f"✗ Ping failed: {response}")
                return False

        except Exception as e:
            logger.error(f"✗ Ping error: {e}")
            return False

    async def test_invalid_message(self):
        """Test invalid message handling"""
        logger.info("=== Testing Invalid Message Handling ===")

        invalid_message = {
            "type": "invalid_type",
            "agent_id": self.agent_id,
            "timestamp": time.time(),
            "data": {}
        }

        try:
            response = await self.send_message(invalid_message)

            if response.get("type") == "error":
                logger.info("✓ Invalid message properly rejected")
                return True
            else:
                logger.error(f"✗ Invalid message not rejected: {response}")
                return False

        except Exception as e:
            logger.error(f"✗ Invalid message test error: {e}")
            return False

    async def disconnect(self):
        """Disconnect from the server"""
        if self.websocket:
            await self.websocket.close()
            logger.info("✓ Disconnected")

    async def run_full_test(self):
        """Run the complete test suite"""
        logger.info("Starting FreeCiv LLM WebSocket Test Suite")
        logger.info("=" * 50)

        results = {
            "connection": False,
            "authentication": False,
            "state_query": False,
            "action": False,
            "ping": False,
            "invalid_message": False
        }

        try:
            # Test connection
            results["connection"] = await self.connect()
            if not results["connection"]:
                return results

            # Test authentication
            results["authentication"] = await self.test_authentication()
            if not results["authentication"]:
                return results

            # Test other functionality
            results["state_query"] = await self.test_state_query()
            results["action"] = await self.test_action()
            results["ping"] = await self.test_ping()
            results["invalid_message"] = await self.test_invalid_message()

        except Exception as e:
            logger.error(f"Test suite error: {e}")
        finally:
            await self.disconnect()

        return results

async def main():
    """Main test function"""
    import sys

    # Allow host and port override
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8002

    tester = FreeCivLLMTester(host, port)
    results = await tester.run_full_test()

    # Print summary
    print("\n" + "=" * 50)
    print("TEST RESULTS SUMMARY")
    print("=" * 50)

    passed = 0
    total = len(results)

    for test_name, result in results.items():
        status = "PASS" if result else "FAIL"
        icon = "✓" if result else "✗"
        print(f"{icon} {test_name.replace('_', ' ').title()}: {status}")
        if result:
            passed += 1

    print(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! LLM Gateway is working correctly.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Check the logs above.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())