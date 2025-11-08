#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Metaserver Client for FreeCiv3D
Queries the metaserver game list to find available multiplayer pregame servers.
"""

import logging
import time
from typing import Optional, List, Dict, Any
from urllib.request import Request, urlopen
import urllib.error
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs
import sys

# Note: metaserver host/port are passed in by callers; no direct config import here.

logger = logging.getLogger("freeciv-proxy")


def _port_sort_key(g: Dict[str, Any]) -> int:
    """Return an integer port suitable for sorting (fallback to maxsize)."""
    port = g.get("port")
    return port if isinstance(port, int) else sys.maxsize


class GameListParser(HTMLParser):
    """Parse game list HTML to extract multiplayer server information."""

    def __init__(self):
        super().__init__()
        self.games: List[Dict[str, Any]] = []
        self.current_game: Dict[str, Any] = {}
        self.in_multiplayer_table = False
        self.in_row = False
        self.current_tag = None
        self.cell_index = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        # Detect multiplayer table
        if tag == "table" and attrs_dict.get("id") == "multiplayer-table":
            self.in_multiplayer_table = True

        # Start of table row (skip header row)
        if tag == "tr" and self.in_multiplayer_table:
            self.in_row = True
            self.current_game = {
                "players": None,
                "message": None,
                "state": None,
                "turn": None,
                "port": None,
            }
            self.cell_index = 0

        # Table cells
        if tag == "td" and self.in_row:
            self.current_tag = "td"

        # Extract port and type from play/observe links
        if tag == "a" and self.in_row:
            href = attrs_dict.get("href")
            if href:
                # Parse query parameters from the link reliably
                try:
                    parsed = urlparse(href)
                    qs = parse_qs(parsed.query)
                    # Only consider multiplayer actions
                    action = (qs.get("action", [""])[0] or "").lower()
                    multi_flag = (qs.get("multi", [""])[0] or "").lower()
                    if action not in ("multi", "observe") and multi_flag != "true":
                        return
                    if "civserverport" in qs and qs["civserverport"]:
                        try:
                            self.current_game["port"] = int(qs["civserverport"][0])
                        except (ValueError, TypeError):
                            pass
                    if "type" in qs and qs["type"]:
                        self.current_game["type"] = str(qs["type"][0])
                except Exception:
                    # Ignore malformed hrefs; row may still yield useful cells
                    pass

    def handle_endtag(self, tag):
        if tag == "table" and self.in_multiplayer_table:
            self.in_multiplayer_table = False

        if tag == "tr" and self.in_row:
            # Default type if within multiplayer table and no explicit type param found
            if self.in_multiplayer_table and "type" not in self.current_game:
                self.current_game["type"] = "multiplayer"
            # End of row - save if we extracted a port
            if self.current_game.get("port"):
                self.games.append(self.current_game.copy())
            self.in_row = False
            self.cell_index = 0

        if tag == "td":
            self.current_tag = None
            self.cell_index += 1

    def handle_data(self, data):
        if not self.in_row or self.current_tag != "td":
            return

        data = data.strip()
        if not data:
            return

        # Map cell index to field (based on JSP structure)
        # 0: Players, 1: Message, 2: State, 3: Turn, 4: Action (links)
        if self.cell_index == 0:  # Players column
            # Parse "X player(s)" or "None"
            if "None" in data:
                self.current_game["players"] = 0
            else:
                # Extract the first integer-like token without regex
                num = None
                token = []
                for ch in data:
                    if ch.isdigit():
                        token.append(ch)
                    elif token:
                        break
                if token:
                    try:
                        num = int("".join(token))
                    except (ValueError, TypeError):
                        num = None
                if num is not None:
                    self.current_game["players"] = num
        elif self.cell_index == 1:  # Message
            self.current_game["message"] = data
        elif self.cell_index == 2:  # State
            self.current_game["state"] = data
        elif self.cell_index == 3:  # Turn
            try:
                self.current_game["turn"] = int(data)
            except (ValueError, TypeError):
                self.current_game["turn"] = 0


class MetaserverClient:
    """Client for querying FreeCiv metaserver game list.

    Light-weight HTTP client with small in-memory cache and retry logic.
    """

    # Ordered candidate paths to probe on the metaserver for the game list.
    CANDIDATE_PATHS: List[str] = [
        "/freeciv-web/game/list?v=multiplayer",
        "/game/list?v=multiplayer",
        "/freeciv-web/game/list?v=singleplayer",
        "/game/list?v=singleplayer",
    ]

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8080,
        timeout: int = 5,
        cache_ttl: float = 10.0,
        max_retries: int = 2,
        backoff_factor: float = 0.5,
        user_agent: str = "FreeCiv3D-MetaserverClient/1.0",
    ):
        """Initialize metaserver client.

        Args:
            host: Metaserver hostname.
            port: Metaserver HTTP port.
            timeout: Single request timeout in seconds.
            cache_ttl: Seconds to keep successful result cached.
            max_retries: Number of retry attempts per path on transient errors.
            backoff_factor: Base factor for exponential backoff (sleep = factor * 2^attempt).
            user_agent: HTTP User-Agent header value.
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0
        self._cache_ttl: float = cache_ttl
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.user_agent = user_agent

    def _request_html(self, url: str) -> Optional[str]:
        """Perform an HTTP GET with retry & simple backoff.

        Returns decoded HTML string or None on failure.
        """
        attempt = 0
        while True:
            try:
                req = Request(url, method="GET", headers={"User-Agent": self.user_agent, "Accept": "text/html"})
                with urlopen(req, timeout=self.timeout) as resp:
                    status = getattr(resp, "status", None) or resp.getcode()
                    if status != 200:
                        raise RuntimeError(f"HTTP {status} for {url}")
                    html_bytes = resp.read()
                return html_bytes.decode("utf-8", errors="replace")
            except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as e:
                # Transient error handling
                if attempt >= self.max_retries:
                    logger.debug(f"Request failed permanently for {url}: {e}")
                    return None
                sleep_time = self.backoff_factor * (2 ** attempt)
                logger.debug(
                    f"Request attempt {attempt+1} failed for {url}: {e}; retrying in {sleep_time:.2f}s"
                )
                time.sleep(sleep_time)
                attempt += 1
            except Exception as e:  # Unexpected error -> do not retry
                logger.debug(f"Unexpected error for {url}: {e}")
                return None

    def _fetch_game_list(self) -> str:
        """Fetch raw HTML from game list endpoint, trying known path variants.

        Raises:
            RuntimeError: If all HTTP requests fail or no multiplayer table found.
        """
        last_error: Optional[Exception] = None
        for path in self.CANDIDATE_PATHS:
            url = f"http://{self.host}:{self.port}{path}"
            html = self._request_html(url)
            if html is None:
                last_error = last_error or RuntimeError(f"Failed to fetch {path}")
                continue
            if 'id="multiplayer-table"' in html:
                logger.debug(f"Metaserver fetch succeeded using path {path}")
                return html
            logger.debug(
                f"Metaserver fetch for {path} returned 200 but multiplayer table not found"
            )
        raise RuntimeError(
            f"Metaserver connection failed after trying {len(self.CANDIDATE_PATHS)} paths: {last_error}"
        )

    def _parse_games(self, html: str) -> List[Dict[str, Any]]:
        """Parse HTML to extract game information.

        Args:
            html: HTML content from game list

        Returns:
            List of game dictionaries with keys: port, players, state, message, turn
        """
        parser = GameListParser()
        try:
            parser.feed(html)
        except Exception as e:
            logger.error(f"Failed to parse game list HTML: {e}")
            return []

        return parser.games

    def get_multiplayer_games(self, use_cache: bool = True) -> List[Dict[str, Any]]:
        """Get list of multiplayer games from metaserver.

        Args:
            use_cache: Use cached results if available and fresh

        Returns:
            List of game dictionaries sorted by port (lowest first)
        """
        now = time.time()

        # Return cached data if valid
        if use_cache and self._cache and (now - self._cache_time) < self._cache_ttl:
            logger.debug(f"Using cached game list (age: {now - self._cache_time:.1f}s)")
            return self._cache["games"]

        try:
            html = self._fetch_game_list()
            games = self._parse_games(html)

            # Sort by port (lowest first)
            games.sort(key=_port_sort_key)

            # Update cache
            self._cache = {"games": games}
            self._cache_time = now

            logger.info(f"Fetched {len(games)} multiplayer games from metaserver")
            return games

        except Exception as e:
            logger.error(f"Failed to get multiplayer games: {e}")
            # Return stale cache if available
            if self._cache:
                logger.warning("Returning stale cached data due to metaserver error")
                return self._cache["games"]
            return []

    def find_pregame_server(
        self, min_players: int = 0, max_players: int = 0
    ) -> Optional[int]:
        """Find the lowest port number for a suitable multiplayer pregame server.

        Args:
            min_players: Minimum number of current players (default: 0)
            max_players: Maximum number of current players (default: 0 for empty servers)

        Returns:
            Port number of suitable server, or None if no servers available
        """
        games = self.get_multiplayer_games()

        # Filter for pregame servers with desired player count
        suitable = [
            g
            for g in games
            if isinstance(g.get("port"), int)
            and g.get("type") in ("multiplayer", "longturn")
            and g.get("state") == "Pregame"
            and isinstance((players := g.get("players")), int)
            and min_players <= players <= max_players
        ]

        if not suitable:
            logger.warning(
                f"No suitable multiplayer pregame servers found "
                f"(players: {min_players}-{max_players}, total games: {len(games)})"
            )
            return None

        # Return lowest port (games are already sorted by port once fetched)
        best = suitable[0]
        logger.info(
            f"Selected multiplayer server: port={best['port']}, "
            f"players={best['players']}, state={best['state']}, "
            f"message={best.get('message', 'N/A')}"
        )
        return best["port"]

    def invalidate_cache(self):
        """Force cache invalidation on next query."""
        self._cache = None
        self._cache_time = 0


# Simple cache of clients by (host, port)
_client_cache: Dict[tuple, MetaserverClient] = {}


def get_metaserver_client(
    host: str = "localhost", port: int = 8080
) -> MetaserverClient:
    """Get metaserver client for the given host/port (cached per key)."""
    key = (host, port)
    client = _client_cache.get(key)
    if client is None:
        client = MetaserverClient(host, port)
        _client_cache[key] = client
    return client
