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




