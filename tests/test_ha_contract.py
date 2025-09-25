import sys
import types

import pytest


@pytest.mark.ha_integration
def test_real_driver_payloads(load_service_area_tree, monkeypatch):
    module = load_service_area_tree(use_real_drivers=True)

    calls = []
    stub_light = types.SimpleNamespace(
        turn_on=lambda **kwargs: calls.append(("on", kwargs)),
        turn_off=lambda **kwargs: calls.append(("off", kwargs)),
    )
    monkeypatch.setitem(sys.modules, "light", stub_light)

    module.init()
    tree = module.get_area_tree()
    device = tree.get_device("light_living_room_main")
    assert device is not None

    module.create_event(
        device_name="sensor_living_room_motion",
        tags=["auto", "motion_detected"],
    )
    module.create_event(
        device_name="sensor_living_room_motion",
        tags=["auto", "motion_detected"],
    )

    assert calls, "light driver should issue Home Assistant commands"
    assert calls[0][0] == "on"
    assert calls[-1][0] in {"on", "off"}
    assert device.cached_state is not None
