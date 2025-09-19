#!/bin/bash
# Docker database initialization script

set -e

echo "=== Starting Database Initialization ==="

# Configuration (allow overrides via env)
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-docker}"
DB_PASSWORD="${DB_PASSWORD:-changeme}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-$DB_PASSWORD}}"
DB_NAME="${DB_NAME:-freeciv_web}"
EXTERNAL_FLYWAY="${EXTERNAL_FLYWAY:-1}"
# How long to wait for external Flyway to apply migrations (retries * interval)
MIGRATION_WAIT_RETRIES="${MIGRATION_WAIT_RETRIES:-60}"
MIGRATION_WAIT_INTERVAL="${MIGRATION_WAIT_INTERVAL:-5}"

# Wait for MySQL to be ready
echo "Waiting for MySQL to be ready..."
for i in {1..60}; do
	if mysqladmin ping -h "$DB_HOST" -P "$DB_PORT" -u root -p"$DB_ROOT_PASSWORD" --silent 2> /dev/null; then
		echo "MySQL is ready!"
		break
	fi
	if [ "$i" -eq 60 ]; then
		echo "ERROR: MySQL failed to start within 60 seconds"
		exit 1
	fi
	echo "  Waiting for MySQL... ($i/60)"
	sleep 1
done

# Create database and user
echo "Setting up database and user..."
mysql -h "$DB_HOST" -P "$DB_PORT" -u root -p"$DB_ROOT_PASSWORD" -e "
CREATE DATABASE IF NOT EXISTS $DB_NAME;
-- Create user for both localhost and remote access; allow host override
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
CREATE USER IF NOT EXISTS '$DB_USER'@'%' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'%';
FLUSH PRIVILEGES;
" 2> /dev/null || {
	echo "Database setup completed or already exists"
}

# Test connection
echo "Testing database connection..."
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -e "SELECT 1;" > /dev/null || {
	echo "ERROR: Cannot connect to database"
	exit 1
}

# Run migrations manually
FLYWAY_DIR="/docker/freeciv-web/src/main/resources/db/migration"
if [ "$EXTERNAL_FLYWAY" = "1" ] || [ "$EXTERNAL_FLYWAY" = "true" ]; then
	echo "External Flyway mode enabled: waiting for migrations to be applied by the flyway service"
	found=0
	for i in $(seq 1 "$MIGRATION_WAIT_RETRIES"); do
		# Check for Flyway schema history table
		cnt=$(mysql -N -s -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB_NAME' AND table_name='flyway_schema_history';" 2> /dev/null || echo 0)
		if [ "${cnt:-0}" -gt 0 ]; then
			echo "Detected Flyway schema history table; assuming migrations applied."
			found=1
			break
		fi
		echo "Waiting for external Flyway to apply migrations... ($i/$MIGRATION_WAIT_RETRIES)"
		sleep "$MIGRATION_WAIT_INTERVAL"
	done

	if [ "$found" -ne 1 ]; then
		echo "ERROR: timed out waiting for external Flyway to apply migrations."
		echo "Run the flyway service (e.g. 'docker compose run --rm flyway') and try again."
		exit 1
	fi
else
	if [ -d "$FLYWAY_DIR" ]; then
		echo "Running database migrations (local mode)..."
		while IFS= read -r -d '' migration; do
			echo "Running migration: $(basename "$migration")"
			mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" < "$migration" 2> /dev/null || {
				echo "Migration $(basename "$migration") already applied or failed"
			}
		done < <(find "$FLYWAY_DIR" -name "V*.sql" -print0 | sort -z)
	fi
fi

# Register game servers
echo "Registering game servers..."
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -e "
INSERT INTO servers (host, port, version, state, type, available, stamp) VALUES
('localhost', 6000, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6001, 'freeciv-web-devel', 'Pregame', 'multiplayer', 1, NOW()),
('localhost', 6002, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6003, 'freeciv-web-devel', 'Pregame', 'singleplayer', 1, NOW()),
('localhost', 6004, 'freeciv-web-devel', 'Pregame', 'multiplayer', 1, NOW())
ON DUPLICATE KEY UPDATE available=1, stamp=NOW();
" 2> /dev/null

echo "=== Database Initialization Complete ==="
