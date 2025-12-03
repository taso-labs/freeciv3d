#!/bin/bash
# LLM Gateway startup script for FreeCiv3D integration

echo "=== Starting FreeCiv3D LLM Gateway ==="

# Change to the LLM Gateway directory
cd /docker/project-root/llm-gateway/

# Create logs directory if it doesn't exist
mkdir -p logs

# Set environment variables for the gateway
export FREECIV_PROXY_HOST=localhost
export FREECIV_PROXY_PORT=8002
export LLM_GATEWAY_HOST=0.0.0.0
export LLM_GATEWAY_PORT=8003
export LLM_API_TOKENS=${LLM_API_TOKENS:-test-token-fc3d-001,test-token-fc3d-002}
export LOG_LEVEL=INFO

# Install requirements if they don't exist
if [ ! -f "/tmp/llm-gateway-deps-installed" ]; then
    echo "Installing LLM Gateway dependencies..."
    pip3 install --break-system-packages -r requirements.txt
    touch /tmp/llm-gateway-deps-installed
fi

echo "Starting LLM Gateway on port ${LLM_GATEWAY_PORT}..."
/home/docker/.local/bin/uvicorn main:app --host ${LLM_GATEWAY_HOST} --port ${LLM_GATEWAY_PORT} --log-level ${LOG_LEVEL,,} --ws-max-size 104857600 &

# Store the PID for later cleanup
echo $! > /tmp/llm-gateway.pid

echo "✅ LLM Gateway started (PID: $(cat /tmp/llm-gateway.pid))"
