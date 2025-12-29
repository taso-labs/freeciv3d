#!/bin/bash

# Start Freeciv-web's dependency services.
#
# Need to start the dependency services in a different way to work with
# your set up? Create a script that starts them and put it in
# scripts/dependency-services-start.sh.


export JAVA_OPTS="-Djava.security.egd=file:/dev/urandom"
export CATALINA_HOME=/usr/share/tomcat10
export CATALINA_BASE=/var/lib/tomcat10

# Tomcat
echo "Starting up Tomcat" && \
if service --status-all 2>&1 | grep -Fq 'tomcat10' && [ -x /usr/sbin/service ]; then
   sudo service tomcat10 start || echo "unable to start tomcat10 service, trying direct startup..."
   # If service start failed, try direct startup as fallback
   if ! curl --output /dev/null --silent --head --fail "http://localhost:8080" 2>/dev/null; then
      sudo su -s /bin/bash tomcat -c "export CATALINA_HOME=$CATALINA_HOME && export CATALINA_BASE=$CATALINA_BASE && $CATALINA_HOME/bin/catalina.sh start"
   fi
else
   # Direct startup (needed in Docker containers without systemd)
   sudo su -s /bin/bash tomcat -c "export CATALINA_HOME=$CATALINA_HOME && export CATALINA_BASE=$CATALINA_BASE && $CATALINA_HOME/bin/catalina.sh start"
fi

# waiting for Tomcat to start, since it will take some time.
# ROOT.war deploys at / context, so check the root path
until `curl --output /dev/null --silent --head --fail "http://localhost:8080/"`; do
    printf ".."
    sleep 3
done
sleep 8
