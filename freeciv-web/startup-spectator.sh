#!/bin/bash
# Immediate spectator deployment script
# This runs from volume mount to deploy spectator files without Docker rebuild

echo "=== Immediate Spectator Deployment ==="

WEBAPP_DIR="/var/lib/tomcat10/webapps/freeciv-web"
SOURCE_DIR="/docker/freeciv-web-shared"
RETRY_COUNT=0
MAX_RETRIES=60

# Wait for webapp to be deployed (longer timeout for immediate deployment)
echo "Waiting for FreeCiv webapp to be available..."
while ! sudo test -d "$WEBAPP_DIR/webclient" && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  echo "Waiting for webapp deployment... (attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"
  sleep 2
  RETRY_COUNT=$((RETRY_COUNT + 1))
done

if ! sudo test -d "$WEBAPP_DIR/webclient"; then
  echo "ERROR: FreeCiv webapp not found after $MAX_RETRIES attempts"
  echo "Expected directory: $WEBAPP_DIR/webclient"
  echo "Available directories:"
  sudo ls -la /var/lib/tomcat10/webapps/ || echo "Cannot list webapps directory"
  exit 1
fi

echo "FreeCiv webapp found at $WEBAPP_DIR"

# Check if source files exist in volume mount
if [ ! -f "$SOURCE_DIR/src/main/webapp/webclient/spectator.jsp" ]; then
  echo "ERROR: Source spectator.jsp not found at $SOURCE_DIR/src/main/webapp/webclient/spectator.jsp"
  echo "Available files in source webclient:"
  ls -la "$SOURCE_DIR/src/main/webapp/webclient/" || echo "Cannot list source webclient directory"
  exit 1
fi

if [ ! -f "$SOURCE_DIR/src/main/webapp/javascript/spectator_client.js" ]; then
  echo "ERROR: Source spectator_client.js not found at $SOURCE_DIR/src/main/webapp/javascript/spectator_client.js"
  echo "Available files in source javascript:"
  ls -la "$SOURCE_DIR/src/main/webapp/javascript/" | grep spectator || echo "No spectator files found"
  exit 1
fi

# Create javascript directory if it doesn't exist
sudo mkdir -p "$WEBAPP_DIR/javascript"

# Deploy spectator.jsp
echo "Deploying spectator.jsp..."
sudo cp "$SOURCE_DIR/src/main/webapp/webclient/spectator.jsp" "$WEBAPP_DIR/webclient/" || {
  echo "ERROR: Failed to copy spectator.jsp"
  exit 1
}

# Deploy spectator_client.js
echo "Deploying spectator_client.js..."
sudo cp "$SOURCE_DIR/src/main/webapp/javascript/spectator_client.js" "$WEBAPP_DIR/javascript/" || {
  echo "ERROR: Failed to copy spectator_client.js"
  exit 1
}

# Set proper permissions
echo "Setting file permissions..."
sudo chown root:root "$WEBAPP_DIR/webclient/spectator.jsp" 2>/dev/null || echo "Warning: Could not set ownership for spectator.jsp"
sudo chown root:root "$WEBAPP_DIR/javascript/spectator_client.js" 2>/dev/null || echo "Warning: Could not set ownership for spectator_client.js"
sudo chmod 640 "$WEBAPP_DIR/webclient/spectator.jsp" 2>/dev/null || echo "Warning: Could not set permissions for spectator.jsp"
sudo chmod 640 "$WEBAPP_DIR/javascript/spectator_client.js" 2>/dev/null || echo "Warning: Could not set permissions for spectator_client.js"

# Verify deployment
if sudo test -f "$WEBAPP_DIR/webclient/spectator.jsp" && sudo test -f "$WEBAPP_DIR/javascript/spectator_client.js"; then
  echo "✅ Spectator files deployed successfully!"
  echo "   - spectator.jsp: $(sudo ls -la "$WEBAPP_DIR/webclient/spectator.jsp" 2>/dev/null | awk '{print $1, $3, $4, $5}' || echo 'deployed')"
  echo "   - spectator_client.js: $(sudo ls -la "$WEBAPP_DIR/javascript/spectator_client.js" 2>/dev/null | awk '{print $1, $3, $4, $5}' || echo 'deployed')"
  echo "   - Spectator URL: http://localhost:8080/webclient/spectator.jsp"
else
  echo "❌ ERROR: Spectator file deployment failed"
  exit 1
fi

echo "=== Immediate Spectator Deployment Complete ==="