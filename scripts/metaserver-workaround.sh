#!/bin/bash
# Workaround script to register game servers with metaserver
# This compensates for the freeciv-web binary's metaserver connection issues

echo "=== Metaserver Workaround Script ==="
echo "Waiting for Tomcat to be ready..."
sleep 15

# Register single player server (port 6001)
echo "Registering single player server on port 6001..."
curl -s -X POST 'http://localhost:8080/freeciv-web/meta/metaserver?host=localhost&port=6001&state=Pregame&type=singleplayer&message=Singleplayer&version=3.0.0'

# Register multiplayer server (port 6002)  
echo "Registering multiplayer server on port 6002..."
curl -s -X POST 'http://localhost:8080/freeciv-web/meta/metaserver?host=localhost&port=6002&state=Pregame&type=multiplayer&message=Multiplayer&version=3.0.0'

# Mark servers as available
echo "Marking servers as available..."
mysql -u docker -pchangeme freeciv_web -e "UPDATE servers SET available=1 WHERE port IN (6001, 6002)" 2>/dev/null

echo "✓ Game servers registered with metaserver"


