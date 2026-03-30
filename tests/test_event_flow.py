"""Tests for EventManager event flow, device_type_filter, and MotionSensorDriver chain.

These tests exercise the core automation path:
    sensor signal
      -> MotionSensorDriver.trigger_state()
      -> Device.input_trigger()
      -> EventManager.check_event() / execute_rule()
      -> Area.set_state() (with optional device_type_filter)
"""
import copy
import pytest
from .conftest import load_area_tree


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_dummy_driver(name, device_type="light"):
    """Return a minimal driver stub with a controllable state dict."""

    class DummyDriver:
        def __init__(self, n, dt):
            self.name = n
            self.device_type = dt
            self._state = {}

        def get_state(self):
            return copy.deepcopy(self._state)

        def set_state(self, state):
            self._state.update(state)
            return copy.deepcopy(self._state)

        def filter_state(self, state):
            return state

    return DummyDriver(name, device_type)


# ---------------------------------------------------------------------------
# Helpers for building minimal AreaTree stubs
# ---------------------------------------------------------------------------

def make_area_tree_stub(area_tree_mod, devices_by_name):
    """Return a minimal AreaTree-like object wrapping the given devices dict.

    EventManager.execute_rule() calls self.get_area_tree().get_device(name),
    so the object needs a get_device() method backed by a flat lookup.
    """
    class _AreaTreeStub:
        def __init__(self, lookup):
            self.area_tree_lookup = lookup

        def get_device(self, device_name):
            return self.area_tree_lookup.get(device_name)

    return _AreaTreeStub(devices_by_name)


# ---------------------------------------------------------------------------
# Phase 3a — EventManager.check_event() -> execute_rule() end-to-end
# ---------------------------------------------------------------------------

class TestEventManagerFlow:
    """End-to-end tests for EventManager rule matching and execution."""

    def _build_event_manager(self, area_tree_mod, rules_dict):
        """Build an EventManager whose rules come from an in-memory dict."""
        EventManager = area_tree_mod.EventManager
        Area = area_tree_mod.Area
        Device = area_tree_mod.Device

        # Minimal area with one light device
        light_driver = make_dummy_driver("motion_sensor_kitchen", "motion")
        # The trigger device must be in the AreaTree lookup; the area contains the light
        light_output_driver = make_dummy_driver("light_kitchen", "light")
        light_device = Device(light_output_driver)
        trigger_device = Device(light_driver)

        area = Area("kitchen")
        area.add_child(light_device)
        area.add_child(trigger_device)
        light_device.set_area(area)
        trigger_device.set_area(area)

        # AreaTree stub: maps device name -> Device object
        at_stub = make_area_tree_stub(area_tree_mod, {
            "motion_sensor_kitchen": trigger_device,
            "light_kitchen": light_device,
        })

        em = EventManager.__new__(EventManager)
        em.rules = rules_dict
        em.area_tree = at_stub

        # Wire the global event_manager so Device.input_trigger can call it
        area_tree_mod.event_manager = em

        return em, light_device, area, trigger_device

    def test_matching_rule_applies_state(self):
        """A matching event should result in set_state being called on the area."""
        at = load_area_tree()
        rules = {
            "test_on": {
                "trigger_prefix": "motion_sensor_kitchen",
                "required_tags": ["on"],
                "state": {"status": 1},
                "combination_strategy": "last",
            }
        }
        em, light_device, area, _ = self._build_event_manager(at, rules)

        event = {"device_name": "motion_sensor_kitchen", "tags": ["on"]}
        results = em.check_event(event)

        assert results is not False, "Expected at least one rule to match"
        assert True in results or results == [True], f"execute_rule should return True, got {results}"
        # The light in the area should now have status=1
        assert light_device.driver._state.get("status") == 1, (
            f"Expected status=1 after motion_on rule, got {light_device.driver._state}"
        )

    def test_wrong_prefix_does_not_match(self):
        """An event whose device_name does not match trigger_prefix fires no rule."""
        at = load_area_tree()
        rules = {
            "test_on": {
                "trigger_prefix": "motion_sensor_office",
                "required_tags": ["on"],
                "state": {"status": 1},
                "combination_strategy": "last",
            }
        }
        em, light_device, _, __ = self._build_event_manager(at, rules)

        event = {"device_name": "motion_sensor_kitchen", "tags": ["on"]}
        results = em.check_event(event)

        assert light_device.driver._state.get("status") is None, (
            "State should not change when no rule prefix matches"
        )

    def test_missing_required_tag_does_not_match(self):
        """An event missing a required tag should not execute the rule."""
        at = load_area_tree()
        rules = {
            "test_on": {
                "trigger_prefix": "motion_sensor_kitchen",
                "required_tags": ["on"],
                "state": {"status": 1},
                "combination_strategy": "last",
            }
        }
        em, light_device, _, __ = self._build_event_manager(at, rules)

        event = {"device_name": "motion_sensor_kitchen", "tags": ["off"]}
        em.check_event(event)

        assert light_device.driver._state.get("status") is None, (
            "State should not change when required tag 'on' is absent"
        )

    def test_prohibited_tag_blocks_rule(self):
        """An event containing a prohibited tag should not execute the rule."""
        at = load_area_tree()
        rules = {
            "test_on": {
                "trigger_prefix": "motion_sensor_kitchen",
                "required_tags": ["on"],
                "prohibited_tags": ["manual_override"],
                "state": {"status": 1},
                "combination_strategy": "last",
            }
        }
        em, light_device, _, __ = self._build_event_manager(at, rules)

        event = {"device_name": "motion_sensor_kitchen", "tags": ["on", "manual_override"]}
        em.check_event(event)

        assert light_device.driver._state.get("status") is None, (
            "State should not change when prohibited tag 'manual_override' is present"
        )

    def test_missing_device_name_drops_event(self):
        """An event without device_name should be silently dropped."""
        at = load_area_tree()
        rules = {}
        em, _, __, ___ = self._build_event_manager(at, rules)

        result = em.check_event({"tags": ["on"]})
        assert result is False

    def test_rule_state_merged_with_event_state(self):
        """State from event_data and from rule.state are both merged into the final state."""
        at = load_area_tree()
        rules = {
            "test_merge": {
                "trigger_prefix": "motion_sensor_kitchen",
                "required_tags": ["on"],
                "state": {"brightness": 200},
                "combination_strategy": "last",
            }
        }
        em, light_device, _, __ = self._build_event_manager(at, rules)

        # Event carries its own "status" key, rule carries "brightness"
        event = {
            "device_name": "motion_sensor_kitchen",
            "tags": ["on"],
            "state": {"status": 1},
        }
        em.check_event(event)

        state = light_device.driver._state
        assert state.get("status") == 1, f"status from event_data not applied: {state}"
        assert state.get("brightness") == 200, f"brightness from rule not applied: {state}"


# ---------------------------------------------------------------------------
# Phase 3b — device_type_filter
# ---------------------------------------------------------------------------

class TestDeviceTypeFilter:
    """Tests that Area.set_state respects device_type_filter."""

    def _make_area_with_two_devices(self, area_tree_mod):
        """Build an Area containing one 'light' and one 'plug' device."""
        Area = area_tree_mod.Area
        Device = area_tree_mod.Device

        light_drv = make_dummy_driver("kitchen_light", "light")
        plug_drv = make_dummy_driver("kitchen_plug", "plug")

        light_dev = Device(light_drv)
        plug_dev = Device(plug_drv)

        area = Area("kitchen")
        area.add_child(light_dev)
        area.add_child(plug_dev)
        light_dev.set_area(area)
        plug_dev.set_area(area)

        return area, light_dev, plug_dev

    def test_filter_light_skips_plug(self):
        """device_type_filter=['light'] should update lights but skip plugs."""
        at = load_area_tree()
        area, light_dev, plug_dev = self._make_area_with_two_devices(at)

        area.set_state({"status": 1}, device_type_filter=["light"])

        assert light_dev.driver._state.get("status") == 1, (
            "Light device should have been updated"
        )
        assert plug_dev.driver._state.get("status") is None, (
            "Plug device should have been skipped by device_type_filter=['light']"
        )

    def test_filter_plug_skips_light(self):
        """device_type_filter=['plug'] should update plugs but skip lights."""
        at = load_area_tree()
        area, light_dev, plug_dev = self._make_area_with_two_devices(at)

        area.set_state({"status": 1}, device_type_filter=["plug"])

        assert plug_dev.driver._state.get("status") == 1, (
            "Plug device should have been updated"
        )
        assert light_dev.driver._state.get("status") is None, (
            "Light device should have been skipped by device_type_filter=['plug']"
        )

    def test_no_filter_updates_all(self):
        """device_type_filter=None should update both device types."""
        at = load_area_tree()
        area, light_dev, plug_dev = self._make_area_with_two_devices(at)

        area.set_state({"status": 1}, device_type_filter=None)

        assert light_dev.driver._state.get("status") == 1, "Light should be updated without filter"
        assert plug_dev.driver._state.get("status") == 1, "Plug should be updated without filter"

    def test_filter_propagates_to_sub_areas(self):
        """device_type_filter must propagate through nested sub-areas."""
        at = load_area_tree()
        Area = at.Area
        Device = at.Device

        # Build: home -> kitchen -> light AND plug
        light_drv = make_dummy_driver("kitchen_light", "light")
        plug_drv = make_dummy_driver("kitchen_plug", "plug")
        light_dev = Device(light_drv)
        plug_dev = Device(plug_drv)

        kitchen = Area("kitchen")
        kitchen.add_child(light_dev)
        kitchen.add_child(plug_dev)
        light_dev.set_area(kitchen)
        plug_dev.set_area(kitchen)

        home = Area("home")
        home.add_child(kitchen)

        home.set_state({"status": 1}, device_type_filter=["light"])

        assert light_dev.driver._state.get("status") == 1, (
            "Nested light should be updated"
        )
        assert plug_dev.driver._state.get("status") is None, (
            "Nested plug should be skipped by filter propagated to sub-area"
        )

    def test_multi_type_filter(self):
        """device_type_filter=['light', 'plug'] should update both device types."""
        at = load_area_tree()
        area, light_dev, plug_dev = self._make_area_with_two_devices(at)

        area.set_state({"status": 1}, device_type_filter=["light", "plug"])

        assert light_dev.driver._state.get("status") == 1, "Light should be updated"
        assert plug_dev.driver._state.get("status") == 1, "Plug should be updated"

    def test_execute_rule_device_type_filter_applied(self):
        """execute_rule with device_type_filter in rule YAML skips non-matching types."""
        at = load_area_tree()
        EventManager = at.EventManager
        Area = at.Area
        Device = at.Device

        light_drv = make_dummy_driver("kitchen_light", "light")
        plug_drv = make_dummy_driver("kitchen_plug", "plug")
        motion_drv = make_dummy_driver("motion_sensor_kitchen", "motion")

        light_dev = Device(light_drv)
        plug_dev = Device(plug_drv)
        motion_dev = Device(motion_drv)

        kitchen = Area("kitchen")
        for dev in [light_dev, plug_dev, motion_dev]:
            kitchen.add_child(dev)
            dev.set_area(kitchen)

        at_stub = make_area_tree_stub(at, {
            "motion_sensor_kitchen": motion_dev,
            "kitchen_light": light_dev,
            "kitchen_plug": plug_dev,
        })

        rules = {
            "motion_on": {
                "trigger_prefix": "motion_sensor_kitchen",
                "required_tags": ["on"],
                "state": {"status": 1},
                "combination_strategy": "last",
                "device_type_filter": ["light"],
            }
        }

        em = EventManager.__new__(EventManager)
        em.rules = rules
        em.area_tree = at_stub
        at.event_manager = em

        event = {"device_name": "motion_sensor_kitchen", "tags": ["on"]}
        em.check_event(event)

        assert light_dev.driver._state.get("status") == 1, (
            "Light should be ON after motion_on rule with device_type_filter=['light']"
        )
        assert plug_dev.driver._state.get("status") is None, (
            "Plug should NOT be updated by motion_on rule with device_type_filter=['light']"
        )


# ---------------------------------------------------------------------------
# Phase 3c — MotionSensorDriver -> Device.input_trigger -> EventManager
# ---------------------------------------------------------------------------

class TestMotionTriggerChain:
    """Tests the signal chain from MotionSensorDriver through to EventManager."""

    def test_trigger_state_calls_callback(self):
        """trigger_state() should invoke the registered callback with the tags."""
        at = load_area_tree()
        MotionSensorDriver = at.MotionSensorDriver

        driver = MotionSensorDriver.__new__(MotionSensorDriver)
        driver.name = "motion_sensor_kitchen"
        driver.last_state = {}
        driver.callback = None

        received = []
        driver.add_callback(lambda tags: received.append(tags))
        driver.trigger_state(tags=["on", "motion_occupancy"])

        assert received == [["on", "motion_occupancy"]], (
            f"Callback should have received ['on', 'motion_occupancy'], got {received}"
        )

    def test_trigger_state_no_callback_does_not_raise(self):
        """trigger_state() with no callback registered should not raise."""
        at = load_area_tree()
        MotionSensorDriver = at.MotionSensorDriver

        driver = MotionSensorDriver.__new__(MotionSensorDriver)
        driver.name = "motion_sensor_kitchen"
        driver.last_state = {}
        driver.callback = None

        # Should not raise even without a callback
        driver.trigger_state(tags=["on"])

    def test_trigger_state_no_tags_kwarg_does_not_raise(self):
        """trigger_state() without 'tags' kwarg should not raise."""
        at = load_area_tree()
        MotionSensorDriver = at.MotionSensorDriver

        called = []
        driver = MotionSensorDriver.__new__(MotionSensorDriver)
        driver.name = "motion_sensor_kitchen"
        driver.last_state = {}
        driver.callback = lambda tags: called.append(tags)

        driver.trigger_state()  # no tags kwarg
        assert called == [], "Callback should not be called when no tags kwarg is provided"

    def test_input_trigger_creates_event(self):
        """Device.input_trigger() should call EventManager.create_event with correct payload."""
        at = load_area_tree()
        Device = at.Device
        Area = at.Area

        events = []

        class CapturingEventManager:
            def create_event(self, event):
                events.append(copy.deepcopy(event))

        at.event_manager = CapturingEventManager()

        drv = make_dummy_driver("motion_sensor_kitchen", "motion")
        dev = Device(drv)
        area = Area("kitchen")
        area.add_child(dev)
        dev.set_area(area)

        dev.input_trigger(["on", "motion_occupancy"])

        assert len(events) == 1, f"Expected 1 event, got {events}"
        assert events[0]["device_name"] == "motion_sensor_kitchen"
        assert events[0]["tags"] == ["on", "motion_occupancy"]

    def test_full_motion_chain(self):
        """Full chain: MotionSensorDriver.trigger_state -> Device.input_trigger
        -> EventManager.check_event -> Area.set_state."""
        at = load_area_tree()
        Device = at.Device
        Area = at.Area
        EventManager = at.EventManager
        MotionSensorDriver = at.MotionSensorDriver

        # Build minimal area tree: kitchen with a light and a motion sensor device
        light_drv = make_dummy_driver("kitchen_light", "light")
        motion_drv = make_dummy_driver("motion_sensor_kitchen", "motion")

        light_dev = Device(light_drv)
        motion_dev = Device(motion_drv)

        kitchen = Area("kitchen")
        kitchen.add_child(light_dev)
        kitchen.add_child(motion_dev)
        light_dev.set_area(kitchen)
        motion_dev.set_area(kitchen)

        at_stub = make_area_tree_stub(at, {
            "motion_sensor_kitchen": motion_dev,
            "kitchen_light": light_dev,
        })

        rules = {
            "motion_on": {
                "trigger_prefix": "motion_sensor_kitchen",
                "required_tags": ["on"],
                "state": {"status": 1},
                "combination_strategy": "last",
                "device_type_filter": ["light"],
            }
        }

        em = EventManager.__new__(EventManager)
        em.rules = rules
        em.area_tree = at_stub
        at.event_manager = em

        # Create the driver, wire up the callback manually (as area_tree.py does at line 1886)
        ms_driver = MotionSensorDriver.__new__(MotionSensorDriver)
        ms_driver.name = "motion_sensor_kitchen"
        ms_driver.last_state = {}
        ms_driver.callback = None
        ms_driver.add_callback(motion_dev.input_trigger)

        # Fire the trigger as pyscript would when binary_sensor.motion_sensor_kitchen_occupancy == 'on'
        ms_driver.trigger_state(tags=["on", "motion_occupancy"])

        assert light_dev.driver._state.get("status") == 1, (
            "Light should be ON after full motion chain fires with 'on' tag"
        )

    def test_full_motion_off_chain(self):
        """Motion 'off' event should set status=0 on lights only (device_type_filter)."""
        at = load_area_tree()
        Device = at.Device
        Area = at.Area
        EventManager = at.EventManager
        MotionSensorDriver = at.MotionSensorDriver

        light_drv = make_dummy_driver("kitchen_light", "light")
        plug_drv = make_dummy_driver("kitchen_plug", "plug")
        motion_drv = make_dummy_driver("motion_sensor_kitchen", "motion")

        light_dev = Device(light_drv)
        plug_dev = Device(plug_drv)
        motion_dev = Device(motion_drv)

        # Pre-set both to ON
        light_drv._state = {"status": 1}
        plug_drv._state = {"status": 1}

        kitchen = Area("kitchen")
        for dev in [light_dev, plug_dev, motion_dev]:
            kitchen.add_child(dev)
            dev.set_area(kitchen)

        at_stub = make_area_tree_stub(at, {
            "motion_sensor_kitchen": motion_dev,
            "kitchen_light": light_dev,
            "kitchen_plug": plug_dev,
        })

        rules = {
            "motion_off": {
                "trigger_prefix": "motion_sensor_kitchen",
                "required_tags": ["off", "motion_occupancy"],
                "state": {"status": 0},
                "combination_strategy": "last",
                "device_type_filter": ["light"],
            }
        }

        em = EventManager.__new__(EventManager)
        em.rules = rules
        em.area_tree = at_stub
        at.event_manager = em

        ms_driver = MotionSensorDriver.__new__(MotionSensorDriver)
        ms_driver.name = "motion_sensor_kitchen"
        ms_driver.last_state = {}
        ms_driver.callback = None
        ms_driver.add_callback(motion_dev.input_trigger)

        ms_driver.trigger_state(tags=["off", "motion_occupancy"])

        assert light_dev.driver._state.get("status") == 0, (
            "Light should be OFF after motion_off rule"
        )
        assert plug_dev.driver._state.get("status") == 1, (
            "Plug should remain ON — motion_off rule has device_type_filter=['light']"
        )
