#!/bin/bash

# Start Freeciv-web's dependency services in Docker (no sudo required)
#
# This script is used in Docker containers where:
# - docker user is in the tomcat group
# - Tomcat directories are group-writable
# - No privilege escalation is needed

export JAVA_OPTS="-Djava.security.egd=file:/dev/urandom"
export CATALINA_HOME=/usr/share/tomcat10
export CATALINA_BASE=/var/lib/tomcat10

# Start Tomcat directly as docker user (docker is in tomcat group)
echo "Starting up Tomcat (Docker mode, no sudo)"
$CATALINA_HOME/bin/catalina.sh start

# Wait for Tomcat to start
echo "Waiting for Tomcat to start..."
until curl --output /dev/null --silent --head --fail "http://localhost:8080/freeciv-web" 2>/dev/null; do
    printf ".."
    sleep 3
done
echo ""
echo "Tomcat started successfully"
sleep 8
