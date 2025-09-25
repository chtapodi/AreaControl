import types
from tests.conftest import load_area_tree


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


def test_hue_light_calibration():
    area_tree = load_area_tree()
    # adjust profile so test has predictable output
    area_tree.COLOR_PROFILES["hue"] = {"scale": [0.5, 1.0, 1.0], "offset": [0, 0, 0]}
    calls = []
    area_tree.light = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(kw),
        turn_off=lambda **kw: None,
    )
    HueLight = area_tree.HueLight
    light = HueLight("library_lamp")
    light.apply_values(rgb_color=[100, 100, 100])
    assert calls and calls[0]["rgb_color"] == [50, 100, 100]


def test_light_calibration_offset():
    area_tree = load_area_tree()
    area_tree.COLOR_PROFILES["kauf"] = {"scale": [1.0, 1.0, 1.0], "offset": [10, -20, 5]}
    calls = []
    area_tree.light = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(kw),
        turn_off=lambda **kw: None,
    )
    KaufLight = area_tree.KaufLight
    light = KaufLight("desk_lamp")
    light.apply_values(rgb_color=[100, 100, 100])
    assert calls and calls[0]["rgb_color"] == [110, 80, 105]
