#!/bin/bash
# Startup script for freeciv-proxy with LLM gateway support

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
FREECIV_WEB_DIR="${SCRIPT_DIR}/.."
PROXY_DIR="${FREECIV_WEB_DIR}/freeciv-proxy"

# Set environment variables for LLM gateway
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# Generate secure secrets if not provided
if [ -z "$CACHE_HMAC_SECRET" ]; then
    export CACHE_HMAC_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || echo "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890")
    echo "Generated CACHE_HMAC_SECRET for this session"
fi

if [ -z "$API_KEY_SECRET" ]; then
    export API_KEY_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || echo "fallback1234567890123456789012345")
    echo "Generated API_KEY_SECRET for this session"
fi

# Install missing Python packages if needed (fallback for development)
echo "Checking Python dependencies..."
python3 -c "import bcrypt, redis, yaml" 2>/dev/null || {
    echo "Installing missing Python packages..."
    pip3 install bcrypt redis PyYAML websockets --break-system-packages 2>/dev/null || \
    pip3 install bcrypt redis PyYAML websockets --user 2>/dev/null || \
    echo "Warning: Some Python packages may be missing. Please install: bcrypt, redis, PyYAML, websockets"
}

# Default LLM API tokens if not provided
if [ -z "$LLM_API_TOKENS" ]; then
    export LLM_API_TOKENS="test-token-fc3d-001,test-token-fc3d-002"
    echo "Using default LLM_API_TOKENS for testing"
fi

# Default configuration
export SESSION_TIMEOUT_SECONDS=${SESSION_TIMEOUT_SECONDS:-3600}
export MAX_LLM_AGENTS=${MAX_LLM_AGENTS:-10}
export CACHE_TTL_SECONDS=${CACHE_TTL_SECONDS:-5}

echo "Starting freeciv-proxy with LLM gateway..."
echo "  - Port: 8002"
echo "  - LLM endpoint: /llmsocket"
echo "  - Max agents: ${MAX_LLM_AGENTS}"
echo "  - Session timeout: ${SESSION_TIMEOUT_SECONDS}s"

cd "${PROXY_DIR}" || {
    echo "ERROR: freeciv-proxy directory not found at ${PROXY_DIR}"
    exit 1
}

# Check if main proxy script exists
if [ ! -f "freeciv-proxy.py" ]; then
    echo "ERROR: freeciv-proxy.py not found in ${PROXY_DIR}"
    exit 1
fi

# Start freeciv-proxy in background
nohup python3 -u freeciv-proxy.py > "${FREECIV_WEB_DIR}/logs/freeciv-proxy.log" 2>&1 &
PROXY_PID=$!

# Wait a moment and check if it started successfully
sleep 2
if kill -0 $PROXY_PID 2>/dev/null; then
    echo "freeciv-proxy started successfully (PID: $PROXY_PID)"
    echo $PROXY_PID > "${FREECIV_WEB_DIR}/logs/freeciv-proxy.pid"

    # Test if the service is responding
    echo "Testing WebSocket connection..."
    timeout 5 python3 -c "
import socket
import time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    result = s.connect_ex(('localhost', 8002))
    if result == 0:
        print('✓ freeciv-proxy listening on port 8002')
    else:
        print('✗ freeciv-proxy not responding on port 8002')
        exit(1)
finally:
    s.close()
" || echo "✗ Connection test failed"

else
    echo "ERROR: freeciv-proxy failed to start"
    exit 1
fi