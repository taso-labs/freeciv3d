#!/bin/bash
# Monitor Docker build and startup progress

echo "🔍 FreeCiv3D Build & Startup Monitor"
echo "===================================="

check_docker_status() {
    if docker-compose ps 2>/dev/null | grep -q "Up"; then
        echo "✅ Container is running"
        return 0
    else
        echo "⏳ Container not yet running"
        return 1
    fi
}

check_port() {
    local port=$1
    local service=$2
    if nc -z localhost $port 2>/dev/null; then
        echo "✅ $service responding on port $port"
        return 0
    else
        echo "⏳ $service not yet responding on port $port"
        return 1
    fi
}

check_service() {
    local url=$1
    local service=$2
    if curl -f -s "$url" > /dev/null 2>&1; then
        echo "✅ $service is working"
        return 0
    else
        echo "⏳ $service not yet ready"
        return 1
    fi
}

# Monitor loop
echo "Monitoring build and startup progress..."
echo "Press Ctrl+C to stop monitoring"
echo ""

while true; do
    echo "$(date '+%H:%M:%S') - Checking status..."

    # Check container status
    check_docker_status

    # Check ports
    if docker-compose ps 2>/dev/null | grep -q "Up"; then
        check_port 8080 "Web server"
        check_port 8002 "LLM WebSocket"
        check_port 6001 "FreeCiv game server"

        # Check services
        check_service "http://localhost:8080" "Web interface"

        if check_port 8002 "LLM WebSocket" && check_port 8080 "Web server"; then
            echo ""
            echo "🎉 Services are ready for testing!"
            echo "  📱 Web Interface: http://localhost:8080"
            echo "  🤖 LLM Gateway: ws://localhost:8002/llmsocket"
            echo "  🎮 Game Server: localhost:6001"
            echo ""
            echo "Ready to test agent-clash integration!"
            break
        fi
    fi

    echo "Waiting 30 seconds..."
    echo ""
    sleep 30
done