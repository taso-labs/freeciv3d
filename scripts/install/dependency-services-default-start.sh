#!/bin/bash

# Start Freeciv-web's dependency services.
#
# Need to start the dependency services in a different way to work with
# your set up? Create a script that starts them and put it in
# scripts/dependency-services-start.sh.


export JAVA_OPTS="-Djava.security.egd=file:/dev/urandom"
export CATALINA_HOME=/var/lib/tomcat10

# Tomcat
echo "Starting up Tomcat" && \
if service --status-all | grep -Fq 'tomcat10'; then
   sudo /usr/sbin/service tomcat10 start || echo "unable to start tomcat10 service"
else
   # It's a suid script, so will run as tomcat user
   sudo $CATALINA_HOME/bin/catalina.sh start
fi

# waiting for Tomcat to start, since it will take some time.
until `curl --output /dev/null --silent --head --fail "http://localhost:8080/freeciv-web"`; do
    printf ".."
    sleep 3
done
sleep 8
