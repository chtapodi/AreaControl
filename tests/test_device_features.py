import copy
import time
from .conftest import load_area_tree


def test_brightness_caching():
    area_tree = load_area_tree()
    Device = area_tree.Device

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

    d = Device(DummyDriver('light1'))
    d.set_state({'brightness': 100})
    assert d.get_state()['brightness'] == 100
    d.set_state({'brightness': 200})
    assert d.get_state()['brightness'] == 200


def test_button_trigger_event_creation():
    area_tree = load_area_tree()
    Device = area_tree.Device

    events = []
    class DummyEventManager:
        def create_event(self, event):
            events.append(event)

    area_tree.event_manager = DummyEventManager()

    class DummyDriver:
        def __init__(self, name='dummy'):
            self.name = name
        def get_state(self):
            return {'name': self.name}
        def filter_state(self, state):
            return state

    Area = area_tree.Area
    d = Device(DummyDriver('button1'))
    d.set_area(Area('area'))
    d.input_trigger(['press'])
    assert events == [{'device_name': 'button1', 'tags': ['press']}]
