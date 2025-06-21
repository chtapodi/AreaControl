import types
import sys
import copy
import pytest

from .conftest import load_area_tree as _base_load
import os


def load_area_tree():
    """Load ``area_tree`` with optional real driver support."""
    if 'homeassistant' not in sys.modules:
        sys.modules['homeassistant'] = types.ModuleType('homeassistant')
    if 'homeassistant.util' not in sys.modules:
        util_mod = types.ModuleType('homeassistant.util')
        util_mod.color = types.SimpleNamespace(
            color_RGB_to_hs=lambda r, g, b: (0, 0),
            color_hs_to_RGB=lambda h, s: (0, 0, 0),
            color_temperature_to_rgb=lambda k: (0, 0, 0),
        )
        sys.modules['homeassistant.util'] = util_mod
    return _base_load(use_real_drivers=os.getenv('AREATREE_REAL_DRIVERS') == '1')


class DummyDriver:
    def __init__(self, name='dummy'):
        self.name = name
        self.state = {}

    def get_state(self):
        return copy.deepcopy(self.state)

    def set_state(self, state):
        if 'status' in state and not state['status']:
            self.state = {'status': 0}
        else:
            self.state.update(state)
        return copy.deepcopy(self.state)

    def filter_state(self, state):
        return state


@pytest.fixture
def area_tree():
    return load_area_tree()


def test_merge_data_empty_list(area_tree):
    with pytest.raises(ValueError):
        area_tree.merge_data([])


def test_merge_data_integers(area_tree):
    assert area_tree.merge_data([1, 2, 3, 4, 5]) == pytest.approx(3.0)


def test_merge_data_floats(area_tree):
    assert area_tree.merge_data([1.5, 2.5, 3.5]) == pytest.approx(2.5)


def test_merge_data_mixed_numbers(area_tree):
    assert area_tree.merge_data([1, 2.5, 3]) == pytest.approx(2.1666666666666665)


def test_merge_data_lists(area_tree):
    assert area_tree.merge_data([[1, 2], [3, 4], [5, 6]]) == pytest.approx([3.0, 4.0])


def test_merge_data_lists_with_different_lengths(area_tree):
    result = area_tree.merge_data([[1, 2], [3, 4, 5], [6]])
    assert result == pytest.approx([3.3333333333333335, 3.0, 5.0])


def test_merge_data_dicts(area_tree):
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5}]
    expected = {"a": 3.0, "b": 3.0}
    assert area_tree.merge_data(data) == pytest.approx(expected)


def test_merge_states(area_tree):
    states = [{"status": 0}, {"status": 1}, {"status": 1}]
    result = area_tree.merge_states(states)
    assert result["status"] == 1


def test_merge_states_no_status(area_tree):
    states = [{"other": 5}, {"other": 10}]
    result = area_tree.merge_states(states)
    assert result.get("status") == 0


def make_area_with_light(area_tree):
    Area = area_tree.Area
    Device = area_tree.Device
    area = Area('room')
    light = Device(DummyDriver('light'))
    area.add_device(light)
    return area, light


def test_set_setting_status(area_tree):
    area, _ = make_area_with_light(area_tree)
    area.set_state({"status": 1})
    assert area.get_state()["status"] == 1
    area.set_state({"status": 0})
    assert area.get_state()["status"] == 0
    area.set_state({"status": 1})
    assert area.get_state()["status"] == 1


def test_setting_cache(area_tree):
    _, light = make_area_with_light(area_tree)
    light.set_state({"status": 1, "rgb_color": [255, 255, 255]})
    light.set_state({"status": 0})
    state = light.get_state()
    assert state["status"] == 0
    assert state["rgb_color"] in ([255, 255, 255], (255, 255, 255))
    light.add_to_cache({"rgb_color": [255, 0, 255]})
    state = light.get_state()
    assert state["status"] == 0
    assert state["rgb_color"] == [255, 0, 255]


def test_set_and_get_color(area_tree):
    area, _ = make_area_with_light(area_tree)
    area.set_state({"rgb_color": [0, 0, 0], "status": 0})
    state = area.get_state()
    assert state["status"] == 0
    if "rgb_color" in state:
        assert state["rgb_color"] == [0, 0, 0]

    area.set_state({"rgb_color": [255, 255, 255]})
    state = area.get_state()
    if "rgb_color" in state:
        assert state["rgb_color"] == [255, 255, 255]
    assert state["status"] == 0

    area.set_state({"status": 1})
    state = area.get_state()
    assert state["status"] == 1
    assert state["rgb_color"] == [255, 255, 255]

    area.set_state({"rgb_color": [0, 255, 0]})
    state = area.get_state()
    assert state["status"] == 1
    assert state["rgb_color"] == [0, 255, 0]

    area.set_state({"rgb_color": [255, 195, 50]})
    area.set_state({"status": 0})
    area.set_state({"status": 1})
    state = area.get_state()
    assert state["status"] == 1
    assert state["rgb_color"] == [255, 195, 50]


def test_combine_states(area_tree):
    states = [
        {"status": 1, "brightness": 255, "rgb_color": [255, 255, 0]},
        {"status": 1, "rgb_color": [255, 0, 0]},
        {"status": 0, "brightness": 100, "rgb_color": [0, 255, 255]},
    ]
    first_expected = {"status": 1, "brightness": 255, "rgb_color": [255, 255, 0]}
    assert area_tree.combine_states(states, strategy="first") == first_expected

    last_expected = {"status": 0, "brightness": 100, "rgb_color": [0, 255, 255]}
    assert area_tree.combine_states(states, strategy="last") == last_expected

    average_expected = {"status": 1, "brightness": 177.5, "rgb_color": [170, 170, 85]}
    assert area_tree.combine_states(states, strategy="average") == pytest.approx(average_expected)


def test_motion_sensor(area_tree):
    Area = area_tree.Area
    Device = area_tree.Device
    set_motion_sensor_mode = area_tree.set_motion_sensor_mode
    motion_sensor_mode = area_tree.motion_sensor_mode

    area = Area('room')
    light = Device(DummyDriver('light'))
    motion = Device(DummyDriver('motion_sensor_room'))
    area.add_device(light)
    area.add_device(motion)

    class DummyEventManager:
        def __init__(self, area):
            self.area = area
        def create_event(self, event):
            if 'on' in event.get('tags', []) and 'motion_occupancy' in event.get('tags', []) and motion_sensor_mode():
                self.area.set_state({'status': 1, 'brightness': 255})

    area_tree.event_manager = DummyEventManager(area)
    area_tree.input_boolean = types.SimpleNamespace(motion_sensor_mode='on')

    area.set_state({'status': 1, 'brightness': 255, 'rgb_color': [255, 72, 35]})
    area.set_state({'status': 0})

    area_tree.event_manager.create_event({'device_name': motion.name, 'tags': ['on', 'motion_occupancy']})
    state = area.get_state()
    assert state['status'] == 1
    assert state['brightness'] == 255

    area.set_state({'status': 0})
    set_motion_sensor_mode('off')
    area_tree.event_manager.create_event({'device_name': motion.name, 'tags': ['on', 'motion_occupancy']})
    state = area.get_state()
    assert state['status'] == 0

