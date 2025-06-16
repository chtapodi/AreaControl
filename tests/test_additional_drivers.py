import types
from tests.test_caching import load_area_tree


def test_plug_driver_switch():
    area_tree = load_area_tree()
    calls = []
    area_tree.switch = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append('on'),
        turn_off=lambda **kw: calls.append('off')
    )
    PlugDriver = area_tree.PlugDriver
    driver = PlugDriver('desk_plug')
    driver.set_state({'status': 1})
    driver.set_state({'status': 0})
    assert calls == ['on', 'off']


def test_fan_driver_wraps_plug():
    area_tree = load_area_tree()
    calls = []
    area_tree.switch = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append('on'),
        turn_off=lambda **kw: calls.append('off')
    )
    FanDriver = area_tree.FanDriver
    fan = FanDriver('ceiling_fan', window='window1')
    fan.set_state({'status': 1})
    fan.set_state({'status': 0})
    assert calls == ['on', 'off']
    assert fan.get_state()['window'] == 'window1'


def test_television_driver_on_off():
    area_tree = load_area_tree()
    calls = []
    area_tree.media_player = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append('on'),
        turn_off=lambda **kw: calls.append('off')
    )
    TelevisionDriver = area_tree.TelevisionDriver
    tv = TelevisionDriver('living_room_tv')
    tv.set_state({'status': 1})
    tv.set_state({'status': 0})
    assert calls == ['on', 'off']


def test_hue_light_calibration():
    area_tree = load_area_tree()
    # adjust profile so test has predictable output
    area_tree.COLOR_PROFILES['hue'] = [0.5, 1.0, 1.0]
    calls = []
    area_tree.light = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(kw),
        turn_off=lambda **kw: None
    )
    HueLight = area_tree.HueLight
    light = HueLight('library_lamp')
    light.apply_values(rgb_color=[100, 100, 100])
    assert calls and calls[0]['rgb_color'] == [50, 100, 100]


def test_register_input_driver_unwrap():
    area_tree = load_area_tree()

    called = []

    def factory(t, d):
        called.append((t, d))
        return types.SimpleNamespace(name=d)

    class Wrapper:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    area_tree.register_input_driver('wrapped', Wrapper(factory))

    assert area_tree.INPUT_DRIVERS['wrapped'] is factory
    area_tree.INPUT_DRIVERS['wrapped']('type', 'id')
    assert called == [('type', 'id')]


def test_input_driver_unwrap_on_use(tmp_path):
    area_tree = load_area_tree()

    called = []

    def factory(t, d):
        called.append((t, d))
        return types.SimpleNamespace(name=d)

    class Wrapper:
        def __init__(self, value):
            self.value = value

        def get(self):
            return self.value

    area_tree.INPUT_DRIVERS['wrapped2'] = Wrapper(factory)

    test_yaml = {
        'root': {
            'inputs': {
                'wrapped2': ['wrapped2_sensor']
            }
        }
    }
    yaml_path = tmp_path / 'test.yml'
    import yaml
    yaml.safe_dump(test_yaml, yaml_path.open('w'))

    tree_obj = area_tree.AreaTree(str(yaml_path))
    assert ('wrapped2', 'wrapped2_sensor') in called


def test_unwrap_callable_nameerror():
    from area_tree import _unwrap_callable

    class BrokenWrapper:
        def get(self):
            raise NameError("undefined")

    obj = BrokenWrapper()
    assert _unwrap_callable(obj) is obj


def test_unwrap_callable_nested_func():
    from area_tree import _unwrap_callable

    called = []

    def inner(t, d):
        called.append((t, d))
        return types.SimpleNamespace(name=d)

    class FuncWrapper:
        def __init__(self, value):
            self.value = types.SimpleNamespace(func=value)

    unwrapped = _unwrap_callable(FuncWrapper(inner))
    unwrapped('x', 'y')
    assert called == [('x', 'y')]


