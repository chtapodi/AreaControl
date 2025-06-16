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

