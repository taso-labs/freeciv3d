#!/usr/bin/env python3
# -*- coding: utf-8 -*-

'''**********************************************************************
    Freeciv-web - the web version of Freeciv. http://play.freeciv.org/
    Copyright (C) 2009-2015  The Freeciv-web project

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

***********************************************************************'''


from os import chdir
import re
import sys
import html
import threading
from tornado import web, websocket, ioloop, httpserver
from debugging import *
import logging
from civcom import *
from llm_handler import LLMWSHandler
from state_extractor import StateExtractorHandler, LegalActionsHandler, shutdown_executor, civcom_registry
from monitoring import HealthCheckHandler, MetricsHandler, StatsHandler
from admin_handlers import AdminAuthHandler
import json
import uuid
import gc
import os

PROXY_PORT = 8002
# Max WebSocket connections per proxy instance. Set to match civserver maxconnectionsperhost
# for consistent scaling. Supports 5000+ concurrent observers per game for broadcast scenarios.
# Memory impact: ~320MB per civserver with 16384 connections.
CONNECTION_LIMIT = 16384

# CORS Configuration - Default to localhost for development
# In production, set ALLOWED_ORIGINS environment variable to your domains
# Example: ALLOWED_ORIGINS="https://play.freeciv.org,https://freeciv3d.com"
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:8080,http://127.0.0.1:8080').split(',')

civcoms = {}

# ============================================================================
# Per-Port Connection Semaphore
# ============================================================================
# Limits concurrent observer handshakes per civserver to prevent overwhelming
# the server when many users connect simultaneously.
#
# Problem: Without rate limiting, 100 users watching a game = 300 simultaneous
# WebSocket connections (3 observers each). Each handshake requires ~500ms-2s
# of civserver attention for ruleset transmission, causing:
# - Connection timeouts under load
# - Retry loops that compound the problem
# - AI takeover messages as observers disconnect/reconnect
#
# Solution: Queue connections per-port with a semaphore. Only N connections
# can be in the "handshake" phase simultaneously. Others wait their turn.
# ============================================================================

# Per-port semaphores: {civserver_port: threading.Semaphore}
_port_semaphores: dict = {}
_semaphore_lock = threading.Lock()

# Max concurrent observer handshakes per civserver port.
# Each viewer creates 3 observer connections (global, player1, player2).
# Value should be >= 3 to allow one user's connections to handshake in parallel.
# - 3 = serializes even a single user's connections (slow)
# - 6 = 2 users can connect in parallel (recommended)
# - 9 = 3 users can connect in parallel
# Keep reasonable to avoid overwhelming civserver during handshake-heavy rulesets.
MAX_CONCURRENT_HANDSHAKES = 6


def get_port_semaphore(port: int) -> threading.Semaphore:
    """Get or create a semaphore for a civserver port.

    Thread-safe: uses a lock to prevent race conditions when creating
    semaphores for new ports.

    Args:
        port: The civserver port number (e.g., 6001)

    Returns:
        A threading.Semaphore limiting concurrent handshakes to MAX_CONCURRENT_HANDSHAKES
    """
    with _semaphore_lock:
        if port not in _port_semaphores:
            _port_semaphores[port] = threading.Semaphore(MAX_CONCURRENT_HANDSHAKES)
            logger.info(f"Created connection semaphore for port {port} (max {MAX_CONCURRENT_HANDSHAKES} concurrent)")
        return _port_semaphores[port]


def cleanup_port_semaphore(port: int) -> None:
    """Remove a semaphore when a civserver port is released.

    Called when a game ends and the port is returned to the pool.
    Prevents memory leak from accumulating semaphores for unused ports.

    Args:
        port: The civserver port number being released
    """
    with _semaphore_lock:
        if port in _port_semaphores:
            del _port_semaphores[port]
            logger.info(f"Cleaned up connection semaphore for port {port}")


chdir(sys.path[0])

class IndexHandler(web.RequestHandler):

    """Serves the Freeciv-proxy index page """

    def get(self):
        self.write("Freeciv-web websocket proxy, port: " + str(PROXY_PORT))


class StatusHandler(web.RequestHandler):

    """Serves the Freeciv-proxy status page, on the url:  /status """

    def get(self, params):
        self.write(get_debug_info(civcoms))


class WSHandler(websocket.WebSocketHandler):
    logger = logging.getLogger("freeciv-proxy")
    io_loop = ioloop.IOLoop.current()
    civcoms = civcoms  # Expose global civcoms dict so civcom.py can clean it up

    def open(self):
        self.id = str(uuid.uuid4())
        self.is_ready = False
        self.set_nodelay(True)
        logger.info(f"[{self.id}] WebSocket opened")

    def on_message(self, message):
        if (not self.is_ready and len(civcoms) <= CONNECTION_LIMIT):
            # called the first time the user connects.
            logger.info(f"[{self.id}] Received first message (login): {message[:200]}")
            login_message = json.loads(message)
            self.username = login_message['username']
            if (not validate_username(self.username)):
              logger.warn("invalid username: " + str(message))
              self.write_message("[{\"pid\":5,\"message\":\"Error: Could not authenticate user.\",\"you_can_join\":false,\"conn_id\":-1}]")
              return
            self.civserverport = login_message['port']
            logger.info(f"[{self.id}] Login for user '{self.username}' on port {self.civserverport}")

            self.loginpacket = message
            self.is_ready = True
            self.civcom = self.get_civcom(
                self.username,
                self.civserverport,
                self)
            return

        # get the civcom instance which corresponds to this user.
        if (self.is_ready): 
            self.civcom = self.get_civcom(self.username, self.civserverport, self)

        if (self.civcom is None):
            self.write_message("[{\"pid\":5,\"message\":\"Error: Could not authenticate user.\",\"you_can_join\":false,\"conn_id\":-1}]")
            return

        # send JSON request to civserver.
        self.civcom.queue_to_civserver(message)

    def on_close(self):
        logger.info(f"[{self.id}] WebSocket closing")
        if hasattr(self, 'civcom') and self.civcom is not None:
            logger.info(f"[{self.id}] Cleaning up civcom for user '{self.civcom.username}'")
            self.civcom.stopped = True
            self.civcom.close_connection()
            if self.civcom.key in list(civcoms.keys()):
                del civcoms[self.civcom.key]
                logger.info(f"[{self.id}] Removed civcom entry for '{self.civcom.username}' from civcoms")
            del(self.civcom)
            gc.collect()

    # enables support for allowing alternate origins. See check_origin in websocket.py
    def check_origin(self, origin):
      return True;

    # this enables WebSocket compression with default options.
    def get_compression_options(self):
        return {'compression_level' : 9, 'mem_level' : 9}

    # get the civcom instance which corresponds to the requested user.
    def get_civcom(self, username, civserverport, ws_connection):
        key = username + str(civserverport) + ws_connection.id
        if key not in list(civcoms.keys()):
            if (int(civserverport) < 5000):
                return None

            # Acquire semaphore BEFORE starting CivCom thread to limit
            # concurrent handshakes per civserver port. This prevents
            # overwhelming the civserver when many observers connect.
            #
            # The semaphore is passed to CivCom and released after
            # PACKET_SERVER_JOIN_REPLY (handshake complete) or on error.
            port = int(civserverport)
            semaphore = get_port_semaphore(port)

            # Non-blocking acquire check - if semaphore is full, log queue status
            if not semaphore.acquire(blocking=False):
                logger.info(
                    f"[{username}] Connection queued for port {port} "
                    f"(max {MAX_CONCURRENT_HANDSHAKES} concurrent handshakes)"
                )
                # Now do blocking acquire
                semaphore.acquire(blocking=True)
                logger.info(f"[{username}] Connection dequeued for port {port}, starting handshake")
            else:
                logger.debug(f"[{username}] Semaphore acquired immediately for port {port}")

            # Issue #4 Fix: Wrap CivCom creation in try/except to ensure semaphore
            # is released if thread creation fails. Without this, a failure here
            # leaks the semaphore slot, eventually blocking ALL observer connections.
            try:
                civcom = CivCom(username, port, key, self)
                civcom.port_semaphore = semaphore  # Pass semaphore for release after handshake
                civcom.start()
                civcoms[key] = civcom
            except Exception as e:
                # Release semaphore immediately on failure to prevent slot leak
                logger.error(
                    f"[{username}] Failed to create CivCom for port {port}: {e}, "
                    f"releasing semaphore to prevent connection blocking"
                )
                try:
                    semaphore.release()
                except ValueError as ve:
                    # Issue #2 (PR Review): Log instead of silent pass - this indicates a logic error
                    logger.error(
                        f"[{username}] Semaphore already released for port {port}: {ve} "
                        f"(indicates double-release bug in error handling)"
                    )
                return None

            return civcom
        else:
            return civcoms[key]


def validate_username(name):
    if (name is None or len(name) <= 2 or len(name) >= 32):
        return False

    # Normalize to lowercase early for consistent comparison
    name_lower = name.lower()

    # Observer usernames have unique random suffixes (e.g., global_view_abc12345)
    # and should never conflict with each other. Skip connection cleanup for observers
    # to prevent race conditions when multiple observer frames connect simultaneously.
    # Patterns: global_xxx, playerN_xxx, observer_xxx, anything_view_xxx
    is_observer = (
        name_lower.startswith('global_') or
        name_lower.startswith('player') or
        name_lower.startswith('observer') or
        '_view_' in name_lower or
        '_observer_' in name_lower
    )

    if not is_observer:
        # Clean up existing connections for this username before validation
        # This allows reconnection (e.g., page refresh, multiple tabs) by closing old connection
        keys_to_remove = []
        for civkey in list(civcoms.keys()):
            if civkey in civcoms and name_lower == civcoms[civkey].username.lower():
                if civcoms[civkey].stopped:
                    logger.info(f"Removing stopped connection for user: {name}")
                else:
                    # Close active connection to allow reconnection
                    logger.info(f"Closing active connection for reconnecting user: {name}")
                    civcoms[civkey].stopped = True
                    try:
                        civcoms[civkey].close_connection()
                    except Exception as e:
                        logger.warn(f"Error closing connection: {e}")
                keys_to_remove.append(civkey)

        # Remove old connections (check if key still exists)
        for key in keys_to_remove:
            if key in civcoms:
                del civcoms[key]
                logger.info(f"Deleted connection key: {key}")

    # Allow letters, numbers, and underscores (for observer names like global_view_abc123)
    return re.fullmatch('[a-z][a-z0-9_]*', name_lower) is not None


if __name__ == "__main__":
    try:
        print('Started Freeciv-proxy. Use Control-C to exit')

        if len(sys.argv) == 2:
            PROXY_PORT = int(sys.argv[1])
        print(('port: ' + str(PROXY_PORT)))

        LOG_FILENAME = '../logs/freeciv-proxy-logging-' + str(PROXY_PORT) + '.log'
        logging.basicConfig(filename=LOG_FILENAME,level=logging.INFO)
        logger = logging.getLogger("freeciv-proxy")

        application = web.Application([
            (r'/civsocket/' + str(PROXY_PORT), WSHandler),
            (r'/llmsocket/' + str(PROXY_PORT), LLMWSHandler),  # New endpoint for LLM agents
            (r"/api/game/([^/]+)/state", StateExtractorHandler),  # REST API for state extraction
            (r"/api/game/([^/]+)/legal_actions", LegalActionsHandler),  # REST API for legal actions
            (r"/health", HealthCheckHandler),  # Health check endpoint
            (r"/metrics", MetricsHandler),  # Prometheus metrics endpoint
            (r"/stats", StatsHandler),  # JSON stats endpoint
            (r"/admin/auth", AdminAuthHandler),  # Admin authentication management
            (r"/", IndexHandler),
            (r"(.*)status", StatusHandler),
        ],
        # Increase WebSocket frame size limit for large FreeCiv packets
        # FreeCiv sends large game state packets (map data, player data, city data)
        # that can exceed Tornado's default 10MB limit, causing "frame exceeds limit" errors
        # See: https://www.tornadoweb.org/en/stable/websocket.html#tornado.websocket.WebSocketHandler.max_message_size
        websocket_max_message_size=50 * 1024 * 1024,  # 50MB for large game state packets

        # WebSocket keepalive to prevent idle connection timeouts
        # GKE load balancer has 600s default idle timeout, nginx has 90s proxy_read_timeout
        # Sending pings every 30s ensures connections stay alive through all proxies
        # Agent-clash client also sends pings (5s interval), but server-side pings provide
        # redundancy and ensure bidirectional keepalive
        # Increased to 180s (3 min) for LLM agent connections that may have slow response times
        # Must match llm-gateway's uvicorn ws-ping-timeout (docker-entrypoint.sh, start-llm-gateway.sh)
        websocket_ping_interval=30,  # Send ping every 30 seconds
        websocket_ping_timeout=180,  # Close connection if no pong received within 180 seconds (3 min)
        )

        # Log WebSocket settings at startup
        max_size = application.settings.get('websocket_max_message_size', 'NOT SET')
        ping_interval = application.settings.get('websocket_ping_interval', 'NOT SET')
        ping_timeout = application.settings.get('websocket_ping_timeout', 'NOT SET')
        if isinstance(max_size, int):
            logger.info(f"WebSocket max_message_size: {max_size} bytes ({max_size / (1024*1024):.1f} MB)")
        else:
            logger.info(f"WebSocket max_message_size: {max_size}")
        logger.info(f"WebSocket keepalive: ping_interval={ping_interval}s, ping_timeout={ping_timeout}s")

        http_server = httpserver.HTTPServer(application)
        http_server.listen(PROXY_PORT)
        ioloop.IOLoop.current().start()

    except KeyboardInterrupt:
        print('Exiting...')
        # Gracefully shutdown thread pool
        shutdown_executor()
