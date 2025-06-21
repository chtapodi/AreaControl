import types
from tests.test_caching import load_area_tree


def test_plug_driver_on_off():
    area_tree = load_area_tree()
    calls = []
    area_tree.switch = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(("on", kw)),
        turn_off=lambda **kw: calls.append(("off", kw)),
    )
    PlugDriver = area_tree.PlugDriver
    d = PlugDriver("desk")
    d.set_state({"status": 1})
    d.set_state({"status": 0})
    assert calls[0][0] == "on" and calls[1][0] == "off"


def test_contact_sensor_get_state():
    area_tree = load_area_tree()
    area_tree.state = types.SimpleNamespace(get=lambda eid: "on")
    ContactSensorDriver = area_tree.ContactSensorDriver
    d = ContactSensorDriver("door")
    state = d.get_state()
    assert state["contact"] == 1


def test_fan_driver_on_off():
    area_tree = load_area_tree()
    calls = []
    area_tree.fan = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(("on", kw)),
        turn_off=lambda **kw: calls.append(("off", kw)),
    )
    FanDriver = area_tree.FanDriver
    d = FanDriver("ceiling")
    d.set_state({"status": 1})
    d.set_state({"status": 0})
    assert calls[0][0] == "on" and calls[1][0] == "off"


def test_television_driver_on_off():
    area_tree = load_area_tree()
    calls = []
    area_tree.media_player = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(("on", kw)),
        turn_off=lambda **kw: calls.append(("off", kw)),
    )
    TelevisionDriver = area_tree.TelevisionDriver
    d = TelevisionDriver("tv")
    d.set_state({"status": 1})
    d.set_state({"status": 0})
    assert calls[0][0] == "on" and calls[1][0] == "off"
