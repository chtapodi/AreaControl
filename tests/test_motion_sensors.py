import types
from .conftest import load_area_tree, _stub_decorator


def setup_motion_env():
    mod = load_area_tree()
    # stub pyscript decorators
    mod.state_trigger = _stub_decorator
    mod.service = _stub_decorator
    mod.event_trigger = _stub_decorator
    mod.pyscript_compile = _stub_decorator
    # required globals
    mod.global_triggers = []
    mod.input_boolean = types.SimpleNamespace(motion_sensor_mode='on')
    mod.light = types.SimpleNamespace(turn_on=lambda **kw: None,
                                      turn_off=lambda **kw: None)
    mod.tracker_manager = types.SimpleNamespace(process_event=lambda *a, **k: None)
    area_tree = mod.AreaTree('layout.yml')
    mod.area_tree = area_tree
    mod.event_manager = mod.EventManager('rules.yml', area_tree)
    return mod


def get_kitchen_lights(area_tree):
    area = area_tree.get_area('kitchen')
    return [c for c in area.get_children() if c.name.startswith('kauf')]


def test_motion_sensor_turns_on_lights():
    mod = setup_motion_env()
    area_tree = mod.get_area_tree()
    lights = get_kitchen_lights(area_tree)
    # ensure cache empty
    for l in lights:
        assert l.cached_state is None
    mod.event_manager.create_event({'device_name': 'motion_sensor_kitchen',
                                    'tags': ['on', 'motion_occupancy']})
    for l in lights:
        assert l.cached_state is not None


def test_motion_sensor_respects_freeze():
    mod = setup_motion_env()
    area_tree = mod.get_area_tree()
    lights = get_kitchen_lights(area_tree)
    mod.freeze_area('kitchen')
    mod.event_manager.create_event({'device_name': 'motion_sensor_kitchen',
                                    'tags': ['on', 'motion_occupancy']})
    for l in lights:
        assert not l.cached_state
    mod.unfreeze_area('kitchen')
    mod.event_manager.create_event({'device_name': 'motion_sensor_kitchen',
                                    'tags': ['on', 'motion_occupancy']})
    for l in lights:
        assert l.cached_state is not None


def test_motion_sensor_mode_off_disables():
    mod = setup_motion_env()
    area_tree = mod.get_area_tree()
    lights = get_kitchen_lights(area_tree)
    mod.input_boolean.motion_sensor_mode = 'off'
    mod.event_manager.create_event({'device_name': 'motion_sensor_kitchen',
                                    'tags': ['on', 'motion_occupancy']})
    for l in lights:
        assert not l.cached_state
    mod.input_boolean.motion_sensor_mode = 'on'
    mod.event_manager.create_event({'device_name': 'motion_sensor_kitchen',
                                    'tags': ['on', 'motion_occupancy']})
    for l in lights:
        assert l.cached_state is not None
