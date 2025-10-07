#!/bin/bash

echo "=== Freeciv3D Docker Container Starting ==="

# Generate Tomcat context.xml with database configuration
echo "=== Generating Tomcat Database Configuration ==="
echo "Creating context.xml from template..."
sudo mkdir -p /var/lib/tomcat10/conf/Catalina/localhost
sudo sed -e "s|#DB_HOST#|${DB_HOST}|g" \
    -e "s|#DB_USER#|${DB_USER}|g" \
    -e "s|#DB_PASSWORD#|${DB_PASSWORD}|g" \
    -e "s|#DB_NAME#|${DB_NAME}|g" \
    /docker/config/web.context.tmpl | sudo tee /var/lib/tomcat10/conf/Catalina/localhost/freeciv-web.xml > /dev/null
sudo chown tomcat:tomcat /var/lib/tomcat10/conf/Catalina/localhost/freeciv-web.xml
echo "✓ Generated freeciv-web.xml:"
sudo cat /var/lib/tomcat10/conf/Catalina/localhost/freeciv-web.xml

# Start all Freeciv-web services first (this starts MySQL, nginx, tomcat)
echo "Starting Freeciv-web services..."
/docker/scripts/start-freeciv-web.sh

# Database initialization using Flyway migrations
echo "=== Initializing Database with Flyway Migrations ==="

# Note: MySQL is running as a separate container.
# docker-compose depends_on with service_healthy ensures MySQL is ready before this starts.

# Generate Flyway configuration from template
echo "Generating Flyway configuration from template..."
sed -e "s|#DB_HOST#|${DB_HOST}|g" \
    -e "s|#DB_USER#|${DB_USER}|g" \
    -e "s|#DB_PASSWORD#|${DB_PASSWORD}|g" \
    -e "s|#DB_NAME#|${DB_NAME}|g" \
    /docker/config/flyway.tmpl > /docker/freeciv-web/flyway.properties

echo "✓ Generated flyway.properties:"
cat /docker/freeciv-web/flyway.properties

# Run Flyway migrations to initialize database schema
echo "Running Flyway migrations..."
cd /docker/freeciv-web
if mvn -B -Dflyway.configFiles=./flyway.properties flyway:migrate 2>&1 | tee /tmp/flyway-migration.log; then
    echo "✓ Flyway migrations completed successfully!"
else
    echo "✗ Flyway migration failed!"
    echo "Last 30 lines of migration log:"
    tail -30 /tmp/flyway-migration.log
    exit 1
fi

echo "=== Database Initialization Complete ==="

# Deploy spectator files to webapp
echo "Deploying spectator files..."
/docker/scripts/deploy-spectator-files.sh || {
    echo "Spectator file deployment failed, but continuing..."
    echo "You may need to deploy spectator files manually"
}

echo "=== Starting FreeCiv Proxy for LLM Gateway (Port 8002) ==="
# Start dedicated proxy for LLM Gateway on port 8002
# This is separate from game-specific proxies (7000-7009) managed by publite2
cd /docker/freeciv-proxy && \
bash -c "cd /docker/freeciv-proxy && python3 -u freeciv-proxy.py 8002 2>&1 | tee /docker/logs/freeciv-proxy-PORT6000.log" &
PROXY_8002_PID=$!

# Wait for proxy to start
sleep 2
if kill -0 $PROXY_8002_PID 2>/dev/null; then
    echo "✓ FreeCiv proxy started on port 8002 (PID: $PROXY_8002_PID)"
else
    echo "✗ FreeCiv proxy failed to start on port 8002"
fi

echo "=== Starting LLM Gateway (Port 8003) ==="
cd /docker/llm-gateway && \
nohup /home/docker/.local/bin/uvicorn main:app --host 0.0.0.0 --port 8003 --log-level info > /docker/logs/llm-gateway.log 2>&1 &
GATEWAY_PID=$!

# Wait for gateway to start
sleep 2
if kill -0 $GATEWAY_PID 2>/dev/null; then
    echo "✓ LLM Gateway started on port 8003 (PID: $GATEWAY_PID)"
else
    echo "✗ LLM Gateway failed to start on port 8003"
fi

echo "=== Freeciv3D Container Ready ==="

exec "$@"
