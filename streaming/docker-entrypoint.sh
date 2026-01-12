#!/bin/bash
# FreeCiv Streaming Container Entrypoint
#
# This script:
# 1. Starts Xvfb (virtual framebuffer) for headless display
# 2. Runs the Node.js streaming script
# 3. Handles graceful shutdown via SIGTERM
#
# The virtual display is required because:
# - Puppeteer needs a display for x11grab to capture
# - SwiftShader (software WebGL) renders to this display
# - FFmpeg captures the display via x11grab

set -e

# Parse resolution for Xvfb
WIDTH=${RESOLUTION%x*}
HEIGHT=${RESOLUTION#*x}
DEPTH=24

# Extract display number from DISPLAY (e.g., :99 -> 99)
DISPLAY_NUM=${DISPLAY#:}

# Aggressive cleanup of stale X11 resources from previous runs
echo "[Entrypoint] Cleaning up any stale X11 resources..."

# Kill any existing Xvfb processes
pkill -9 Xvfb 2>/dev/null || true

# Remove lock file
rm -f "/tmp/.X${DISPLAY_NUM}-lock" 2>/dev/null || true

# Remove socket file
rm -f "/tmp/.X11-unix/X${DISPLAY_NUM}" 2>/dev/null || true

# Small delay to ensure cleanup completes
sleep 1

echo "[Entrypoint] Starting Xvfb on display ${DISPLAY} (${WIDTH}x${HEIGHT}x${DEPTH})..."

# Start Xvfb in background
# -ac: Disable access control (allow any client)
# -screen 0: Configure screen 0
# +extension GLX: Enable GLX extension for OpenGL
Xvfb ${DISPLAY} -ac -screen 0 ${WIDTH}x${HEIGHT}x${DEPTH} +extension GLX &
XVFB_PID=$!

# Wait for Xvfb to be ready
sleep 2

# Verify Xvfb is running
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "[Entrypoint] ERROR: Xvfb failed to start"
    exit 1
fi

echo "[Entrypoint] Xvfb started (PID: $XVFB_PID)"

# Trap SIGTERM and SIGINT for graceful shutdown
cleanup() {
    echo "[Entrypoint] Received shutdown signal..."

    # Send SIGTERM to Node.js process (it will stop FFmpeg and browser)
    if [ -n "$NODE_PID" ]; then
        echo "[Entrypoint] Stopping Node.js process..."
        kill -TERM $NODE_PID 2>/dev/null || true
        wait $NODE_PID 2>/dev/null || true
    fi

    # Stop Xvfb
    echo "[Entrypoint] Stopping Xvfb..."
    kill -TERM $XVFB_PID 2>/dev/null || true
    wait $XVFB_PID 2>/dev/null || true

    echo "[Entrypoint] Shutdown complete"
    exit 0
}

trap cleanup SIGTERM SIGINT

# Validate required environment variables
if [ -z "$OBSERVER_URL" ]; then
    echo "[Entrypoint] ERROR: OBSERVER_URL environment variable is required"
    exit 1
fi

# STREAM_KEY is only required for production mode (YouTube streaming)
# DEV_MODE=local uses local RTMP, DEV_MODE=file is file-only mode
if [ -z "$DEV_MODE" ] && [ -z "$STREAM_KEY" ]; then
    echo "[Entrypoint] ERROR: STREAM_KEY is required for production mode (YouTube streaming)"
    echo "[Entrypoint] TIP: Set DEV_MODE=local for local RTMP, or DEV_MODE=file for file-only mode"
    exit 1
fi

echo "[Entrypoint] Configuration:"
if [ -n "$DEV_MODE" ]; then
    echo "  Mode: DEVELOPMENT ($DEV_MODE)"
else
    echo "  Mode: PRODUCTION (YouTube)"
fi
echo "  Observer URL: ${OBSERVER_URL}"
echo "  Resolution: ${RESOLUTION}"
echo "  FPS: ${FPS}"
echo "  Bitrate: ${BITRATE}"
echo "  Backup Path: ${BACKUP_PATH}"

# Start the streaming script
echo "[Entrypoint] Starting streaming script..."
node stream.js &
NODE_PID=$!

# Wait for Node.js process
wait $NODE_PID
NODE_EXIT_CODE=$?

echo "[Entrypoint] Node.js exited with code: $NODE_EXIT_CODE"

# Cleanup Xvfb
kill -TERM $XVFB_PID 2>/dev/null || true

exit $NODE_EXIT_CODE
