#!/bin/bash
# Deploy spectator files to Tomcat webapp
# This script runs automatically on container startup to ensure
# spectator files are always available even after restarts

echo "=== Deploying Spectator Files ==="

WEBAPP_DIR="/var/lib/tomcat10/webapps/freeciv-web"
SOURCE_DIR="/docker/freeciv-web-shared/src/main/webapp"
RETRY_COUNT=0
MAX_RETRIES=30

# Wait for webapp to be deployed (Tomcat may take time to extract WAR)
echo "Waiting for FreeCiv webapp to be deployed..."
while ! sudo test -d "$WEBAPP_DIR/webclient" && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  echo "Waiting for webapp deployment... (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"
  sleep 2
  RETRY_COUNT=$((RETRY_COUNT + 1))
done

if ! sudo test -d "$WEBAPP_DIR/webclient"; then
  echo "ERROR: FreeCiv webapp not found after $MAX_RETRIES attempts"
  echo "Expected directory: $WEBAPP_DIR/webclient"
  exit 1
fi

echo "FreeCiv webapp found, deploying spectator files..."

# Check if source files exist
if [ ! -f "$SOURCE_DIR/webclient/spectator.jsp" ]; then
  echo "ERROR: Source spectator.jsp not found at $SOURCE_DIR/webclient/spectator.jsp"
  exit 1
fi

if [ ! -f "$SOURCE_DIR/javascript/spectator_client.js" ]; then
  echo "ERROR: Source spectator_client.js not found at $SOURCE_DIR/javascript/spectator_client.js"
  exit 1
fi

# Copy spectator JSP file
echo "Copying spectator.jsp..."
sudo cp "$SOURCE_DIR/webclient/spectator.jsp" "$WEBAPP_DIR/webclient/" || {
  echo "ERROR: Failed to copy spectator.jsp"
  exit 1
}

# Copy spectator JavaScript file
echo "Copying spectator_client.js..."
sudo cp "$SOURCE_DIR/javascript/spectator_client.js" "$WEBAPP_DIR/javascript/" || {
  echo "ERROR: Failed to copy spectator_client.js"
  exit 1
}

# Fix ownership and permissions to match other webapp files
echo "Setting file permissions..."
sudo chown root:root "$WEBAPP_DIR/webclient/spectator.jsp" || echo "Warning: Failed to set ownership for spectator.jsp"
sudo chown root:root "$WEBAPP_DIR/javascript/spectator_client.js" || echo "Warning: Failed to set ownership for spectator_client.js"
sudo chmod 640 "$WEBAPP_DIR/webclient/spectator.jsp" || echo "Warning: Failed to set permissions for spectator.jsp"
sudo chmod 640 "$WEBAPP_DIR/javascript/spectator_client.js" || echo "Warning: Failed to set permissions for spectator_client.js"

# Verify deployment
if sudo test -f "$WEBAPP_DIR/webclient/spectator.jsp" && sudo test -f "$WEBAPP_DIR/javascript/spectator_client.js"; then
  echo "✅ Spectator files deployed successfully!"
  echo "   - spectator.jsp: $(sudo ls -la "$WEBAPP_DIR/webclient/spectator.jsp" | awk '{print $1, $3, $4, $5}')"
  echo "   - spectator_client.js: $(sudo ls -la "$WEBAPP_DIR/javascript/spectator_client.js" | awk '{print $1, $3, $4, $5}')"
  echo "   - Spectator URL: http://localhost:8080/webclient/spectator.jsp"
else
  echo "❌ ERROR: Spectator file deployment failed"
  exit 1
fi

echo "=== Spectator Files Deployment Complete ==="