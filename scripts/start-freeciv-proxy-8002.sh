#!/bin/bash
# Start freeciv-proxy on port 8002 for LLM Gateway WebSocket connections

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
FREECIV_WEB_DIR="${SCRIPT_DIR}/.."
PROXY_DIR="${FREECIV_WEB_DIR}/freeciv-proxy"

echo "Starting freeciv-proxy on port 8002 for LLM Gateway..."

# Set environment variables
export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

# LLM Gateway configuration
export CACHE_HMAC_SECRET=${CACHE_HMAC_SECRET:-"abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"}
export API_KEY_SECRET=${API_KEY_SECRET:-"test12345678901234567890123456789012"}
export LLM_API_TOKENS=${LLM_API_TOKENS:-"test-token-fc3d-001,test-token-fc3d-002"}
export SESSION_TIMEOUT_SECONDS=${SESSION_TIMEOUT_SECONDS:-3600}
export MAX_LLM_AGENTS=${MAX_LLM_AGENTS:-10}

cd "${PROXY_DIR}" || {
    echo "ERROR: freeciv-proxy directory not found at ${PROXY_DIR}"
    exit 1
}

# Start freeciv-proxy on port 8002 with LLM gateway support
echo "  - Port: 8002 (LLM Gateway WebSocket)"
echo "  - Max agents: ${MAX_LLM_AGENTS}"
echo "  - Session timeout: ${SESSION_TIMEOUT_SECONDS}s"

# Start in background
nohup python3 -u freeciv-proxy.py 8002 > "${FREECIV_WEB_DIR}/logs/freeciv-proxy-8002.log" 2>&1 &
PROXY_PID=$!

echo $PROXY_PID > "${FREECIV_WEB_DIR}/logs/freeciv-proxy-8002.pid"

# Wait and check if it started
sleep 3
if kill -0 $PROXY_PID 2>/dev/null; then
    echo "✓ freeciv-proxy started on port 8002 (PID: $PROXY_PID)"

    # Test connection
    timeout 5 python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    result = s.connect_ex(('0.0.0.0', 8002))
    if result == 0:
        print('✓ freeciv-proxy listening on port 8002')
    else:
        print('✗ freeciv-proxy not responding on port 8002')
        exit(1)
finally:
    s.close()
" || echo "✗ Connection test failed"
else
    echo "ERROR: freeciv-proxy failed to start on port 8002"
    exit 1
fi