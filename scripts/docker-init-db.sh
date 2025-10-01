#!/bin/bash
# Docker database initialization script
# Fixed version with proper syntax and comprehensive error handling

set -e

echo "=== Starting Database Initialization ==="

# Configuration
DB_HOST="127.0.0.1"
DB_PORT="3306"
DB_USER="docker"
DB_PASSWORD="changeme"
DB_NAME="freeciv_web"

# Wait for MySQL to be ready
echo "Waiting for MySQL to be ready..."
for i in {1..60}; do
    if mysqladmin ping -h $DB_HOST -P $DB_PORT --silent 2>/dev/null; then
        echo "MySQL is ready!"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "ERROR: MySQL failed to start within 60 seconds"
        exit 1
    fi
    echo "  Waiting for MySQL... ($i/60)"
    sleep 1
done

# Check if database exists, create if not
echo "Ensuring database exists..."
mysql -h $DB_HOST -P $DB_PORT -u root << 'EOF'
CREATE DATABASE IF NOT EXISTS freeciv_web;
CREATE USER IF NOT EXISTS 'docker'@'localhost' IDENTIFIED BY 'changeme';
CREATE USER IF NOT EXISTS 'docker'@'%' IDENTIFIED BY 'changeme';
GRANT ALL PRIVILEGES ON freeciv_web.* TO 'docker'@'localhost';
GRANT ALL PRIVILEGES ON freeciv_web.* TO 'docker'@'%';
FLUSH PRIVILEGES;
EOF

if [ $? -ne 0 ]; then
    echo "ERROR: Could not connect to MySQL as root"
    exit 1
fi

echo "Database and user setup complete!"

# Test connection as docker user
echo "Testing database connection..."
mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASSWORD $DB_NAME -e "SELECT 1;" >/dev/null
if [ $? -ne 0 ]; then
    echo "ERROR: Cannot connect to database as $DB_USER"
    exit 1
fi

# Create tables if they don't exist
echo "Creating database tables..."
mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASSWORD $DB_NAME << 'EOF'
CREATE TABLE IF NOT EXISTS servers (
    id int(11) NOT NULL AUTO_INCREMENT,
    host varchar(100) NOT NULL,
    port int(11) NOT NULL,
    version varchar(100) NOT NULL,
    state varchar(20) NOT NULL,
    type varchar(20) NOT NULL,
    available tinyint(1) NOT NULL DEFAULT 1,
    stamp timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY unique_server (host, port)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

CREATE TABLE IF NOT EXISTS games (
    id int(11) NOT NULL AUTO_INCREMENT,
    host varchar(100) NOT NULL,
    port int(11) NOT NULL,
    type varchar(20) NOT NULL,
    state varchar(20) NOT NULL,
    turn int(11) NOT NULL DEFAULT 0,
    players text,
    created timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
EOF

if [ $? -eq 0 ]; then
    echo "Database tables created successfully!"
else
    echo "Warning: Some tables may already exist"
fi

# Run Flyway migrations if available
FLYWAY_DIR="/docker/freeciv-web/src/main/resources/db/migration"
if [ -d "$FLYWAY_DIR" ]; then
    echo "Running database migrations..."
    for migration in $(ls $FLYWAY_DIR/V*.sql 2>/dev/null | sort); do
        if [ -f "$migration" ]; then
            echo "Running migration: $(basename $migration)"
            mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASSWORD $DB_NAME < "$migration" 2>/dev/null || {
                echo "Migration $(basename $migration) already applied or failed (this is normal)"
            }
        fi
    done
else
    echo "No Flyway migrations directory found, skipping migrations"
fi

# Initialize game servers in database
echo "Registering initial game servers..."
mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASSWORD $DB_NAME << 'EOF'
-- Register game servers for ports 6000-6009
INSERT INTO servers (host, port, version, state, type, available, stamp) VALUES
('localhost', 6000, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6001, 'freeciv-web-devel', 'Pregame', 'multiplayer', 1, NOW()),
('localhost', 6002, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6003, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6004, 'freeciv-web-devel', 'Pregame', 'multiplayer', 1, NOW()),
('localhost', 6005, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6006, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6007, 'freeciv-web-devel', 'Pregame', 'multiplayer', 1, NOW()),
('localhost', 6008, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6009, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW())
ON DUPLICATE KEY UPDATE available=1, stamp=NOW();

-- Verify servers were inserted
SELECT 'Registered servers:' as status;
SELECT host, port, state, type, available FROM servers WHERE available = 1 ORDER BY port;
EOF

if [ $? -eq 0 ]; then
    echo "Game servers registered successfully!"
else
    echo "Warning: Server registration may have failed"
fi

echo "=== Database Initialization Complete ==="