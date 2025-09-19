#!/bin/bash

echo "=== Freeciv3D Docker Container Starting ==="

# Set default database configuration if not provided
export DB_HOST="${DB_HOST:-127.0.0.1}"
export DB_USER="${DB_USER:-docker}"
export DB_PASSWORD="${DB_PASSWORD:-changeme}"
export DB_NAME="${DB_NAME:-freeciv_web}"

# Generate Tomcat context.xml with database configuration BEFORE starting services
echo "Configuring Tomcat database connection..."
sudo mkdir -p /var/lib/tomcat10/conf/Catalina/localhost
sudo sed -e "s|#DB_HOST#|${DB_HOST}|g" \
    -e "s|#DB_USER#|${DB_USER}|g" \
    -e "s|#DB_PASSWORD#|${DB_PASSWORD}|g" \
    -e "s|#DB_NAME#|${DB_NAME}|g" \
    /docker/config/web.context.tmpl | sudo tee /var/lib/tomcat10/conf/Catalina/localhost/freeciv-web.xml > /dev/null
sudo chown tomcat:tomcat /var/lib/tomcat10/conf/Catalina/localhost/freeciv-web.xml
echo "✓ Tomcat database configuration ready"

# Start all Freeciv-web services (this starts nginx, tomcat, publite2)
echo "Starting Freeciv-web services..."
/docker/scripts/start-freeciv-web.sh

# Start LLM Gateway components automatically
# Note: Game-specific proxies (7000-7009) are managed by publite2 via start-freeciv-web.sh
# The LLM Gateway requires a dedicated proxy on port 8002 with /llmsocket endpoint

# Start dedicated freeciv-proxy for LLM Gateway (port 8002)
echo "=== Starting FreeCiv Proxy for LLM Gateway (Port 8002) ==="
if [ -d "/docker/freeciv-proxy" ]; then
    cd /docker/freeciv-proxy
    nohup python3 -u freeciv-proxy.py 8002 > /docker/logs/freeciv-proxy-8002.log 2>&1 &
    PROXY_8002_PID=$!
    sleep 2
    if kill -0 $PROXY_8002_PID 2>/dev/null; then
        echo "✓ FreeCiv proxy started on port 8002 (PID: $PROXY_8002_PID)"
    else
        echo "✗ FreeCiv proxy failed to start on port 8002"
    fi
else
    echo "⚠️  FreeCiv proxy directory not found, skipping LLM Gateway"
fi

# Start LLM Gateway API (port 8003) - depends on proxy 8002
echo "=== Starting LLM Gateway API (Port 8003) ==="
if [ -d "/docker/llm-gateway" ]; then
    cd /docker/llm-gateway
    nohup /home/docker/.local/bin/uvicorn main:app --host 0.0.0.0 --port 8003 --log-level info > /docker/logs/llm-gateway.log 2>&1 &
    GATEWAY_PID=$!
    sleep 2
    if kill -0 $GATEWAY_PID 2>/dev/null; then
        echo "✓ LLM Gateway started on port 8003 (PID: $GATEWAY_PID)"
    else
        echo "✗ LLM Gateway failed to start on port 8003"
    fi
else
    echo "⚠️  LLM Gateway directory not found, skipping startup"
fi

echo "=== Freeciv3D Container Ready ==="

exec "$@"
