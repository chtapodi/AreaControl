import copy
from .conftest import load_area_tree

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

class DummyTree:
    def __init__(self, area):
        self.area = area
    def get_area(self, name=None):
        if name is None or name == self.area.name:
            return self.area
        return None

def make_area(area_tree):
    Area = area_tree.Area
    Device = area_tree.Device
    area = Area('room')
    driver = DummyDriver('light')
    device = Device(driver)
    area.add_device(device)
    return area, device

def test_freeze_area_blocks_state():
    area_tree = load_area_tree()
    area, device = make_area(area_tree)
    area_tree.get_area_tree = lambda: DummyTree(area)

    assert area_tree.freeze_area('room')
    assert area.is_frozen()
    assert device.locked

    area.set_state({'status': 1})
    assert device.driver.state == {}


def test_unfreeze_area_allows_state():
    area_tree = load_area_tree()
    area, device = make_area(area_tree)
    area_tree.get_area_tree = lambda: DummyTree(area)

    area_tree.freeze_area('room')
    area_tree.unfreeze_area('room')

    assert not area.is_frozen()
    assert not device.locked

    area.set_state({'status': 1})
    assert device.driver.state['status'] == 1
