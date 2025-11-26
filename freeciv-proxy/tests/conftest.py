import os
import secrets
import pytest
from unittest.mock import Mock

@pytest.fixture(autouse=True, scope="session")
def test_env():
    """Ensure required env vars exist for tests."""
    os.environ.setdefault("CACHE_HMAC_SECRET", secrets.token_hex(32))
    os.environ.setdefault("AUTH_ENABLED", "false")
    os.environ.setdefault("API_KEY_SECRET", "test-secret")
    yield

@pytest.fixture
def civcom_factory():
    """Return a lightweight CivCom mock with realistic dict/list structures."""
    def _make():
        civcom = Mock()
        civcom.game_turn = 1
        civcom.stopped = False
        civcom.is_alive = lambda: True
        civcom.unit_types = {
            1: {"id": 1, "name": "Warriors", "transport_capacity": 0},
            2: {"id": 2, "name": "Trireme", "transport_capacity": 2},
        }
        civcom.improvements = {
            1: {"id": 1, "name": "Granary"},
            2: {"id": 2, "name": "Barracks"},
        }
        civcom.map_info = {"width": 80, "height": 50}
        civcom.visible_tiles = {}
        civcom.nations = {"Americans": 0}
        civcom.queue_to_civserver = lambda pkt: None
        civcom.send_packets_to_civserver = lambda: None
        # Optional goto helpers
        civcom.request_goto_path = lambda unit_id, dest_tile: None
        civcom.get_goto_path = lambda unit_id, dest_tile, timeout_sec=0.5: {"dir": []}
        # Full state snapshot
        def _get_full_state(player_id):
            return {
                "turn": 1,
                "phase": "movement",
                "players": {str(player_id): {"id": player_id, "name": "Player"}},
                "units": {},
                "cities": {},
                "map": {"width": 80, "height": 50, "tiles": []},
                "visible_tiles": [],
            }
        civcom.get_full_state = _get_full_state
        return civcom
    return _make
