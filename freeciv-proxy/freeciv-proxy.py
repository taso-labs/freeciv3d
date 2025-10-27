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

# Import RULESET cache for spectator support
try:
    from ruleset_cache import ruleset_cache
    RULESET_CACHE_AVAILABLE = True
except ImportError as e:
    logging.getLogger("freeciv-proxy").warning(f"ruleset_cache not available: {e}")
    RULESET_CACHE_AVAILABLE = False
    ruleset_cache = None

PROXY_PORT = 8002
CONNECTION_LIMIT = 1000

# CORS Configuration - Default to localhost for development
# In production, set ALLOWED_ORIGINS environment variable to your domains
# Example: ALLOWED_ORIGINS="https://play.freeciv.org,https://freeciv3d.com"
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:8080,http://127.0.0.1:8080').split(',')

civcoms = {}

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
            civcom = CivCom(username, int(civserverport), key, self)
            civcom.start()
            civcoms[key] = civcom

            return civcom
        else:
            return civcoms[key]


class RulesetCacheHandler(web.RequestHandler):
    """
    HTTP API endpoint to retrieve cached RULESET packets for a game.

    This enables spectators to fetch game initialization data (unit types,
    terrain definitions, EXTRA_MINE constants, etc.) when joining a game.

    GET /api/rulesets/<game_id> - Returns all cached RULESET packets as JSON array
    """
    logger = logging.getLogger("freeciv-proxy")

    def _safe_error_response(self, status_code: int, error_message: str,
                           user_input: str = None) -> None:
        """
        Send a safe error response with HTML-escaped user input and proper headers.

        Args:
            status_code: HTTP status code
            error_message: Safe error message (no user input)
            user_input: Optional user-provided input to escape and include
        """
        self.set_status(status_code)
        self.set_header("Content-Type", "application/json")

        response = {
            'success': False,
            'error': error_message,
            'packets': [],
            'packet_count': 0
        }

        # If user input is provided, escape it before including
        if user_input:
            response['error'] = f"{error_message}: {html.escape(user_input)}"

        self.write(response)

    def set_default_headers(self):
        """Enable CORS for cross-origin requests from web clients with origin validation"""
        origin = self.request.headers.get("Origin")

        # Validate origin against ALLOWED_ORIGINS list
        if origin and origin.strip() in ALLOWED_ORIGINS:
            self.set_header("Access-Control-Allow-Origin", origin.strip())
        elif not origin:
            # Allow requests with no origin (e.g., same-origin or server-to-server)
            self.set_header("Access-Control-Allow-Origin", ALLOWED_ORIGINS[0])
        # If origin is present but not in allowed list, no CORS header is set (request will fail)

        self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")

    def options(self, game_id):
        """Handle CORS preflight"""
        self.set_status(204)
        self.finish()

    def get(self, game_id):
        """
        Get cached RULESET packets for a game

        Args:
            game_id: Game identifier from URL path

        Returns:
            JSON response with:
            - success: boolean
            - packets: array of JSON packet strings
            - packet_count: number of packets
            - cache_info: cache metadata
        """
        if not RULESET_CACHE_AVAILABLE or ruleset_cache is None:
            self._safe_error_response(503, 'RULESET cache not available')
            return

        try:
            # Get cached packets (validation happens inside get_packets)
            packets = ruleset_cache.get_packets(game_id)

            if packets is None:
                self.logger.warning(f"No cached RULESET packets found for game: {game_id}")
                # Escape game_id to prevent XSS in error response
                self._safe_error_response(404, 'No cached packets for game', user_input=game_id)
                return

            # Get cache metadata
            cache_info = ruleset_cache.get_cache_info(game_id)

            self.logger.info(f"✓ Serving {len(packets)} cached RULESET packets for game: {game_id}")

            self.set_header("Content-Type", "application/json")
            self.write({
                'success': True,
                'packets': packets,
                'packet_count': len(packets),
                'cache_info': cache_info
            })

        except ValueError as e:
            # game_id validation failed - log full details but hide from user
            self.logger.warning(f"Invalid game_id format: {game_id} - {e}")
            # Don't expose internal validation error details to prevent information leakage
            self._safe_error_response(400, 'Invalid game_id format')

        except Exception as e:
            # Log full exception details for debugging, but hide from user
            self.logger.exception(f"Error retrieving cached RULESET packets for game {game_id}: {e}")
            # Don't expose internal error details to prevent information leakage
            self._safe_error_response(500, 'Internal server error')


def validate_username(name):
    if (name is None or len(name) <= 2 or len(name) >= 32):
        return False
    
    # Clean up stopped connections for this username before validation
    keys_to_remove = []
    for civkey in list(civcoms.keys()):
        if name == civcoms[civkey].username:
            if civcoms[civkey].stopped:
                logger.info(f"Removing stopped connection for user: {name}")
                keys_to_remove.append(civkey)
            else:
                logger.warn(f"User already connected: {name}")
                return False
    
    # Remove stopped connections
    for key in keys_to_remove:
        del civcoms[key]
        logger.info(f"Deleted stopped connection key: {key}")

    name = name.lower()
    return re.fullmatch('[a-z][a-z0-9]*', name) is not None


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
            (r"/api/rulesets/([^/]+)", RulesetCacheHandler),  # RULESET cache API for spectators
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
        websocket_max_message_size=50 * 1024 * 1024  # 50MB for large game state packets
        )

        # DEBUG: Verify websocket_max_message_size is set correctly
        max_size = application.settings.get('websocket_max_message_size', 'NOT SET')
        print(f'DEBUG: websocket_max_message_size = {max_size} bytes ({max_size / (1024*1024):.1f} MB)' if isinstance(max_size, int) else f'DEBUG: websocket_max_message_size = {max_size}')
        logger.info(f"WebSocket max message size configured: {max_size} bytes")

        http_server = httpserver.HTTPServer(application)
        http_server.listen(PROXY_PORT)
        ioloop.IOLoop.current().start()

    except KeyboardInterrupt:
        print('Exiting...')
        # Gracefully shutdown thread pool
        shutdown_executor()
