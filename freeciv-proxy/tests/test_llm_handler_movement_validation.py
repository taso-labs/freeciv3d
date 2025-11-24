import types
from llm_handler import LLMWSHandler


class DummyCivCom:
    def __init__(self):
        self.unit_types = {}


def make_handler_with_civcom():
    # Create a handler-like object and attach a stub civcom
    h = LLMWSHandler.__new__(LLMWSHandler)
    h.civcom = DummyCivCom()
    return h


def test_settler_cannot_move_into_ocean():
    h = make_handler_with_civcom()
    unit = {'id': 1, 'type': 'settlers', 'x': 10, 'y': 10, 'owner': 0, 'moves_left': 3}
    visible_tiles = [
        {'x': 11, 'y': 10, 'terrain': 'ocean'},
        {'x': 9, 'y': 10, 'terrain': 'grassland'}
    ]
    assert not h._is_unit_move_valid(unit, 11, 10, visible_tiles)
    assert h._is_unit_move_valid(unit, 9, 10, visible_tiles)


def test_trireme_can_move_into_ocean():
    h = make_handler_with_civcom()
    # Add a unit_type entry - id is int in this case
    h.civcom.unit_types[33] = {'name': 'Trireme', 'transport_capacity': 0}
    unit = {'id': 2, 'type': 33, 'x': 10, 'y': 10, 'owner': 0, 'moves_left': 3}
    visible_tiles = [
        {'x': 11, 'y': 10, 'terrain': 'ocean'},
        {'x': 9, 'y': 10, 'terrain': 'grassland'}
    ]
    assert h._is_unit_move_valid(unit, 11, 10, visible_tiles)
    assert h._is_unit_move_valid(unit, 9, 10, visible_tiles)


def test_llm_legal_actions_filters_ocean_for_land_units():
    h = make_handler_with_civcom()
    h.player_id = 0
    # Provide a simple game state for optimization
    game_state = {
        'units': {1: {'id': 1, 'owner': 0, 'type': 'settlers', 'x': 10, 'y': 10, 'moves_left': 3}},
        'cities': {},
        'visible_tiles': [
            {'x': 11, 'y': 10, 'terrain': 'ocean'},
            {'x': 9, 'y': 10, 'terrain': 'grassland'}
        ],
        'techs': []
    }
    actions = h._get_legal_actions_optimized(game_state)
    # There should be moves but none to the ocean tile (11,10) for the land unit
    assert any(a['type'] == 'unit_move' for a in actions)
    ocean_moves = [a for a in actions if a['type'] == 'unit_move' and a['dest_x'] == 11 and a['dest_y'] == 10]
    assert len(ocean_moves) == 0

    # coast should be allowed for land units
    game_state['visible_tiles'][0]['terrain'] = 'coast'
    actions2 = h._get_legal_actions_optimized(game_state)
    coast_moves = [a for a in actions2 if a['type'] == 'unit_move' and a['dest_x'] == 11 and a['dest_y'] == 10]
    assert len(coast_moves) >= 1


def test_llm_legal_actions_allows_ocean_for_navies():
    h = make_handler_with_civcom()
    h.player_id = 0
    # Add a naval unit type and a naval unit
    h.civcom.unit_types[33] = {'name': 'Trireme', 'transport_capacity': 0}
    game_state = {
        'units': {2: {'id': 2, 'owner': 0, 'type': 33, 'x': 10, 'y': 10, 'moves_left': 3}},
        'cities': {},
        'visible_tiles': [
            {'x': 11, 'y': 10, 'terrain': 'ocean'},
            {'x': 9, 'y': 10, 'terrain': 'grassland'}
        ],
        'techs': []
    }
    actions = h._get_legal_actions_optimized(game_state)
    ocean_moves = [a for a in actions if a['type'] == 'unit_move' and a['dest_x'] == 11 and a['dest_y'] == 10]
    assert len(ocean_moves) >= 1
