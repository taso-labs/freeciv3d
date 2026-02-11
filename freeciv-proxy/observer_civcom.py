"""
Observer CivCom — dedicated global-observer connection to civserver.

Provides a single source of truth for global game state (no fog-of-war)
by connecting as a FreeCiv observer via the `/observe` chat command.

The existing per-player CivCom aggregation is kept as a fallback.
"""

import json
import logging
import os

from civcom import CivCom
from packet_constants import PACKET_CHAT_MSG_REQ, PACKET_SERVER_JOIN_REQ
from state_extractor import civcom_registry

logger = logging.getLogger(__name__)

OBSERVER_AGENT_ID = "__observer__"


class _NoOpIOLoop:
    """Fake Tornado IOLoop that discards all scheduled callbacks.

    CivCom uses ``civwebserver.io_loop.add_callback()`` and ``.call_later()``
    to schedule WebSocket writes from the CivCom thread.  The observer has no
    WebSocket client, so we silently drop everything.
    """

    def add_callback(self, *args, **kwargs):
        pass

    def call_later(self, *args, **kwargs):
        pass


class ObserverStub:
    """Minimal stand-in for the ``civwebserver`` parameter CivCom expects.

    CivCom accesses ``civwebserver.loginpacket`` during ``run()`` and calls
    ``write_message()`` to forward packets to the WebSocket client.  The
    observer has no WebSocket client, so we provide a no-op stub.
    """

    def __init__(self, loginpacket: str):
        self.loginpacket = loginpacket
        # CivCom checks these via hasattr / getattr:
        self.is_llm_agent = False
        self.buffer_enabled = False
        # CivCom schedules writes via civwebserver.io_loop.add_callback();
        # provide a no-op loop so the thread doesn't crash.
        self.io_loop = _NoOpIOLoop()

    def write_message(self, *args, **kwargs):
        """No-op — observer discards forwarded packets."""
        pass


class ObserverCivCom(CivCom):
    """CivCom subclass that becomes a global observer after the handshake.

    Once the server acknowledges the join (``handshake_complete`` is set),
    we queue a ``/observe`` chat command.  The civserver then calls
    ``connection_attach(pconn, NULL, TRUE)`` which attaches the connection
    as a global observer — no fog-of-war, receives ALL packets.
    """

    def __init__(self, username, civserverport, key, civwebserver):
        super().__init__(username, civserverport, key, civwebserver)
        self._observe_sent = False

    def _release_handshake_semaphore(self):
        """Override: observer has no semaphore, but must still set handshake_complete.

        The base CivCom only calls handshake_complete.set() inside the
        semaphore release path (guarded by ``if self.port_semaphore is not None``).
        The observer is spawned directly (no WSHandler), so port_semaphore is
        never set.  We unconditionally set the event here.
        """
        self.handshake_complete.set()

    def parse_and_store_packet(self, packet_json):
        """Intercept packet processing to inject /observe after handshake."""
        super().parse_and_store_packet(packet_json)

        if self.handshake_complete.is_set() and not self._observe_sent:
            self._observe_sent = True
            observe_cmd = json.dumps({
                "pid": PACKET_CHAT_MSG_REQ,
                "message": "/observe"
            })
            self.queue_to_civserver(observe_cmd)
            logger.info(
                f"Observer {self.username}: Sent /observe command to become global observer"
            )


def _cleanup_stale_observer(game_id: str) -> None:
    """Remove a dead/stopped observer from the registry so a new one can spawn."""
    existing = civcom_registry.get_civcom(game_id, OBSERVER_AGENT_ID)
    if existing is None:
        return

    existing.stopped = True
    try:
        existing.close_connection()
    except Exception:
        pass
    try:
        civcom_registry.unregister_game(game_id, OBSERVER_AGENT_ID)
    except Exception:
        pass
    logger.info(f"Game {game_id}: Cleaned up stale observer before respawn")


def spawn_observer_civcom(game_id: str, port: int) -> ObserverCivCom:
    """Spawn an observer CivCom and register it in the global registry.

    Only one observer per game is allowed.  If a live observer already exists,
    this is a no-op.  If a stale (stopped/dead) observer is in the registry,
    it is cleaned up and replaced.

    Args:
        game_id: The game identifier.
        port: The civserver TCP port.

    Returns:
        The started ObserverCivCom instance (or existing live one).
    """
    # Single-observer-per-game guard
    existing = civcom_registry.get_civcom(game_id, OBSERVER_AGENT_ID)
    if existing is not None:
        if not existing.stopped and existing.is_alive():
            logger.info(
                f"Game {game_id}: Observer already running, skipping spawn"
            )
            return existing
        # Stale/dead observer — clean up before respawning
        _cleanup_stale_observer(game_id)

    # Build username with _view_ substring (FreeCiv observer convention)
    # and random suffix to prevent guessability
    random_suffix = os.urandom(3).hex()  # 6 hex chars
    username = f"obs_{game_id[:8]}_view_{random_suffix}"

    # FreeCiv usernames cannot start with a digit
    if username[0].isdigit():
        username = "o" + username

    login_packet = json.dumps({
        "pid": PACKET_SERVER_JOIN_REQ,
        "username": username,
        "capability": "+Freeciv.Web.Devel-3.3",
        "version_label": "-dev",
        "major_version": 3,
        "minor_version": 3,
        "patch_version": 0,
        "port": port,
    })

    stub = ObserverStub(login_packet)
    key = f"{OBSERVER_AGENT_ID}_{game_id[:8]}"
    observer = ObserverCivCom(username, port, key, stub)

    civcom_registry.register_game(game_id, OBSERVER_AGENT_ID, observer)
    observer.start()

    logger.info(
        f"Game {game_id}: Spawned observer CivCom on port {port} "
        f"(username={username})"
    )
    return observer


def stop_observer_civcom(game_id: str) -> None:
    """Stop and unregister the observer CivCom for a game."""
    observer = civcom_registry.get_civcom(game_id, OBSERVER_AGENT_ID)
    if observer is None:
        return

    observer.stopped = True
    try:
        observer.close_connection()
    except Exception as e:
        logger.debug(f"Game {game_id}: Observer close_connection error (benign): {e}")

    try:
        civcom_registry.unregister_game(game_id, OBSERVER_AGENT_ID)
    except Exception as e:
        logger.debug(f"Game {game_id}: Observer unregister error (benign): {e}")

    logger.info(f"Game {game_id}: Stopped observer CivCom")
