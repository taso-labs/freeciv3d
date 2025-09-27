#!/bin/bash

echo "=== Freeciv3D Docker Container Starting ==="

# Start all Freeciv-web services first (this starts tomcat)
echo "Starting Freeciv-web services..."
/docker/scripts/start-freeciv-web.sh

echo "=== Freeciv3D Container Ready ==="

exec "$@"
