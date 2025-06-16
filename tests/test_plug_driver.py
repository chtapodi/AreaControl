from .test_caching import load_area_tree


def test_plug_driver_basic():
    mod = load_area_tree()

    class DummySwitch:
        def __init__(self):
            self.last = None
        def turn_on(self, entity_id=None, **kwargs):
            self.last = ("on", entity_id)
        def turn_off(self, entity_id=None, **kwargs):
            self.last = ("off", entity_id)

    class DummyState:
        def __init__(self):
            self.data = {}
        def get(self, key):
            return self.data.get(key)

    mod.switch = DummySwitch()
    mod.state = DummyState()
    mod.state.data["switch.test_plug"] = "off"
    mod.state.data["sensor.test_plug_power"] = 15
    mod.state.data["sensor.test_plug_current"] = 0.5

    plug = mod.PlugDriver(
        "test_plug",
        power_sensor="sensor.test_plug_power",
        current_sensor="sensor.test_plug_current",
    )

    state = plug.get_state()
    assert state == {"status": 0, "power": 15, "current": 0.5}

    plug.set_state({"status": 1})
    assert mod.switch.last == ("on", "switch.test_plug")
    assert plug.last_state["status"] == 1
