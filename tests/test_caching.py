import copy

from .conftest import load_area_tree

area_tree = load_area_tree()
Device = area_tree.Device
get_cached_last_set_state = area_tree.get_cached_last_set_state
set_cached_last_set_state = area_tree.set_cached_last_set_state

class DummyDriver:
    def __init__(self, name='dummy'):
        self.name = name
        self.state = {}
    def get_state(self):
        return copy.deepcopy(self.state)
    def set_state(self, state):
        self.state.update(state)
        return copy.deepcopy(self.state)
    def filter_state(self, state):
        return state


def test_get_last_state_empty():
    d = Device(DummyDriver('test'))
    state = d.get_last_state()
    assert state == {'name': 'test'}


def test_get_missing_cache_entry():
    d = Device(DummyDriver('test'))
    assert d.get('status') is None


def test_global_cache_copy():
    d = Device(DummyDriver('dev'))
    sample = {'status': 1}
    set_cached_last_set_state(d, sample)
    ret = get_cached_last_set_state()
    ret['status'] = 0
    assert get_cached_last_set_state() == sample
