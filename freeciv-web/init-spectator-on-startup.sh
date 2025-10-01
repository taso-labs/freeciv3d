#!/bin/bash
# This script creates a cron job to run spectator deployment on container restart
# It ensures spectator files are deployed whenever the container starts

echo "Setting up automatic spectator deployment..."

# Create the deployment script in a location that persists
mkdir -p /docker/freeciv-web-shared/scripts
cp /docker/freeciv-web-shared/startup-spectator.sh /docker/freeciv-web-shared/scripts/

# Create a systemd service to run the spectator deployment on startup
sudo tee /etc/systemd/system/spectator-deploy.service > /dev/null <<EOF
[Unit]
Description=Deploy Spectator Files
After=tomcat10.service
Wants=tomcat10.service

[Service]
Type=oneshot
ExecStart=/docker/freeciv-web-shared/startup-spectator.sh
User=docker
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF

# Enable the service
sudo systemctl enable spectator-deploy.service 2>/dev/null || echo "Systemctl not available, using alternative approach"

# Alternative: Add to docker user's bashrc to run on login
echo "# Auto-deploy spectator files on container restart" >> /home/docker/.bashrc
echo "if [ ! -f /tmp/spectator-deployed ]; then" >> /home/docker/.bashrc
echo "  /docker/freeciv-web-shared/startup-spectator.sh && touch /tmp/spectator-deployed" >> /home/docker/.bashrc
echo "fi" >> /home/docker/.bashrc

echo "Spectator auto-deployment configured!"