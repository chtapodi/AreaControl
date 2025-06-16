import types
import time
from .conftest import load_area_tree


def test_time_based_state_morning(monkeypatch):
    area_tree = load_area_tree()
    get_time_based_state = area_tree.get_time_based_state
    Area = area_tree.Area

    class DummyDevice:
        def __init__(self, name):
            self.name = name
            self.state = {'status': 0}
        def set_state(self, s):
            self.state.update(s)
        def get_state(self):
            return dict(self.state, name=self.name)
        def get_last_state(self):
            return self.get_state()
        def get_pretty_string(self, *a, **k):
            return self.name

    area = Area('room')
    dev = DummyDevice('light')
    area.add_device(dev)

    def fake_localtime():
        class T(tuple):
            tm_hour = 9
        return T()
    monkeypatch.setattr(time, 'localtime', fake_localtime)

    state = get_time_based_state(dev, [area])
    assert state['status'] == 1
    assert state['brightness'] == 255
    assert state['color_temp'] == 350
