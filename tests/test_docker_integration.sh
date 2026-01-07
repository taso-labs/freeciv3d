#!/bin/bash
# Integration test script for FreeCiv3D Docker with LLM Gateway

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
FREECIV_DIR="${SCRIPT_DIR}/.."

echo "🚀 FreeCiv3D Docker Integration Test"
echo "====================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    local status=$1
    local message=$2
    if [ "$status" = "ok" ]; then
        echo -e "${GREEN}✓${NC} $message"
    elif [ "$status" = "warn" ]; then
        echo -e "${YELLOW}⚠${NC} $message"
    else
        echo -e "${RED}✗${NC} $message"
    fi
}

# Function to check if a port is listening
check_port() {
    local port=$1
    local service=$2
    local timeout=${3:-10}

    echo "Checking if $service is listening on port $port..."

    for i in $(seq 1 $timeout); do
        if nc -z localhost $port 2>/dev/null; then
            print_status "ok" "$service responding on port $port"
            return 0
        fi
        sleep 1
    done

    print_status "fail" "$service not responding on port $port after ${timeout}s"
    return 1
}

# Function to test HTTP endpoint
test_http() {
    local url=$1
    local description=$2

    echo "Testing $description..."
    if curl -f -s "$url" > /dev/null; then
        print_status "ok" "$description is working"
        return 0
    else
        print_status "fail" "$description is not working"
        return 1
    fi
}

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    print_status "fail" "Docker not found"
    exit 1
fi
print_status "ok" "Docker found"

if ! command -v python3 &> /dev/null; then
    print_status "fail" "Python3 not found"
    exit 1
fi
print_status "ok" "Python3 found"

# Check if websockets module is available
if ! python3 -c "import websockets" 2>/dev/null; then
    print_status "warn" "websockets module not found, installing..."
    pip3 install websockets || {
        print_status "fail" "Failed to install websockets module"
        exit 1
    }
fi
print_status "ok" "WebSockets module available"

# Navigate to FreeCiv directory
cd "$FREECIV_DIR"

echo ""
echo "Building and starting Docker container..."

# Build the Docker image
echo "Building Docker image..."
if docker-compose build; then
    print_status "ok" "Docker image built successfully"
else
    print_status "fail" "Docker build failed"
    exit 1
fi

# Start the container
echo "Starting Docker container..."
if docker-compose up -d; then
    print_status "ok" "Docker container started"
else
    print_status "fail" "Failed to start Docker container"
    exit 1
fi

# Wait for container to be ready
echo "Waiting for container to initialize..."
sleep 30

# Get container status
if docker-compose ps | grep -q "Up"; then
    print_status "ok" "Container is running"
else
    print_status "fail" "Container is not running properly"
    docker-compose logs
    exit 1
fi

echo ""
echo "Testing service endpoints..."

# Test HTTP endpoints
test_http "http://localhost:8080" "Main web interface"
test_http "http://localhost:8080/civclientlauncher" "Game launcher"

# Test specific ports
echo ""
echo "Testing network connectivity..."

check_port 8080 "Web server" 20
check_port 8002 "LLM WebSocket Gateway" 20
check_port 6001 "FreeCiv game server" 10

echo ""
echo "Testing LLM WebSocket Gateway..."

# Run the WebSocket test
if python3 tests/test_llm_websocket.py localhost 8002; then
    print_status "ok" "LLM WebSocket Gateway test passed"
else
    print_status "fail" "LLM WebSocket Gateway test failed"
    echo "Container logs:"
    docker-compose logs --tail=50
fi

echo ""
echo "Testing agent-clash compatibility..."

# Check if agent-clash directory exists
if [ -d "../agent-clash" ]; then
    echo "Testing connection from agent-clash client..."

    # Try to run a simple connection test from agent-clash
    cd ../agent-clash
    if python3 -c "
import asyncio
import sys
import os
sys.path.append('.')
from agent_clash.harness.freeciv_proxy_client import FreeCivLLMTester

async def test_connection():
    tester = FreeCivLLMTester('localhost', 8002)
    try:
        connected = await tester.connect()
        if connected:
            print('✓ agent-clash can connect to FreeCiv3D LLM Gateway')
            await tester.disconnect()
            return True
        else:
            print('✗ agent-clash cannot connect to FreeCiv3D LLM Gateway')
            return False
    except Exception as e:
        print(f'✗ Connection test failed: {e}')
        return False

result = asyncio.run(test_connection())
exit(0 if result else 1)
" 2>/dev/null; then
        print_status "ok" "agent-clash integration test passed"
    else
        print_status "warn" "agent-clash integration test failed (may need agent-clash setup)"
    fi

    cd "$FREECIV_DIR"
else
    print_status "warn" "agent-clash directory not found, skipping integration test"
fi

echo ""
echo "Container resource usage:"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"

echo ""
echo "🎉 Integration test complete!"
echo ""
echo "Services accessible at:"
echo "  🌐 Web Interface: http://localhost:8080"
echo "  🎮 Game Launcher: http://localhost:8080/civclientlauncher"
echo "  🤖 LLM Gateway: ws://localhost:8002/llmsocket"
echo ""
echo "To stop the container: docker-compose down"
echo "To view logs: docker-compose logs -f"