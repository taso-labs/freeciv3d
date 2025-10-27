-- Grant remote access privileges to docker user
-- This allows connections from other Docker containers (not just localhost)
-- The MYSQL_USER environment variable creates 'docker'@'localhost' by default
-- This script adds 'docker'@'%' to allow connections from any host

-- In MySQL 8.0, CREATE USER and GRANT must be separate statements
CREATE USER IF NOT EXISTS 'docker'@'%' IDENTIFIED BY 'changeme';
GRANT ALL PRIVILEGES ON freeciv_web.* TO 'docker'@'%';
FLUSH PRIVILEGES;
