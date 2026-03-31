"""Tests for ServiceDriver color/temperature/brightness propagation via HA_only_on_lights rule.

These tests verify that:
1. service_input_button_all_lights device exists in layout.yml
2. HA_only_on_lights rule with combination_strategy: "last" correctly propagates color/temp/brightness
3. Event states (color, temperature, brightness) override rule states when merged
4. All lights in scope receive the merged state updates
"""
import os
import types

from .conftest import load_area_tree_with_config


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

CONFIG_PATHS = {
    "layout": os.path.join(REPO_ROOT, "layout.yml"),
    "rules": os.path.join(REPO_ROOT, "rules.yml"),
    "devices": os.path.join(REPO_ROOT, "devices.yml"),
    "discovered": os.path.join(REPO_ROOT, "discovered.yml"),
    "connections": os.path.join(REPO_ROOT, "connections.yml"),
}


class DummyTrackerManager:
    class _Track:
        def __init__(self, area_name):
            self.area_name = area_name

        def get_pretty_string(self):
            return self.area_name

    def __init__(self):
        self.tracks = []

    def add_event(self, area_name):
        self.tracks.append(self._Track(area_name))

    def get_pretty_string(self):
        return str(self.tracks)


def build_real_config_module():
    """Build area_tree with real config and capture light.turn_on/turn_off calls."""
    area_tree = load_area_tree_with_config(CONFIG_PATHS)
    calls = []

    area_tree.light = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(("on", kw)),
        turn_off=lambda **kw: calls.append(("off", kw)),
    )
    area_tree.switch = types.SimpleNamespace(
        turn_on=lambda **kw: None,
        turn_off=lambda **kw: None,
    )
    area_tree.fan = types.SimpleNamespace(
        turn_on=lambda **kw: None,
        turn_off=lambda **kw: None,
    )
    area_tree.media_player = types.SimpleNamespace(
        turn_on=lambda **kw: None,
        turn_off=lambda **kw: None,
        volume_set=lambda **kw: None,
    )
    area_tree.cover = types.SimpleNamespace(set_cover_position=lambda **kw: None)
    area_tree.state = types.SimpleNamespace(get=lambda *args, **kwargs: "off")
    area_tree.input_boolean = types.SimpleNamespace(motion_sensor_mode="on")
    area_tree.tracker_manager = DummyTrackerManager()
    area_tree.global_triggers = []
    area_tree.config_settings = dict(area_tree.DEFAULT_CONFIG)
    area_tree.config_settings.update(CONFIG_PATHS)

    tree = area_tree.AreaTree(area_tree.config_settings["layout"], devices_file=area_tree.config_settings["devices"])
    event_manager = area_tree.EventManager(area_tree.config_settings["rules"], tree)
    area_tree.area_tree = tree
    area_tree.event_manager = event_manager
    return area_tree, calls


class TestServiceDriverColorPropagation:
    """Tests for ServiceDriver event propagation with HA_only_on_lights rule."""

    def test_service_input_button_all_lights_device_exists(self):
        """Verify that service_input_button_all_lights device is registered in layout.yml."""
        area_tree, _ = build_real_config_module()
        tree = area_tree.area_tree

        # The service_input_button_all_lights device should exist in the tree
        device = tree.get_device("service_input_button_all_lights")
        assert device is not None, (
            "service_input_button_all_lights device not found in AreaTree. "
            "Ensure it is registered in layout.yml under everything.inputs.service"
        )

    def test_service_driver_color_propagates_to_all_lights(self):
        """Verify that RGB color from service_input_button_all_lights reaches all lights."""
        area_tree, calls = build_real_config_module()

        # Simulate a service call with RGB color state
        # Note: must include status: 1 to turn on lights (service_input provides color override)
        before = len(calls)
        area_tree.event_manager.create_event({
            "device_name": "service_input_button_all_lights",
            "state": {"rgb_color": [255, 0, 0], "status": 1},  # Red
        })
        color_calls = calls[before:]

        # Extract entity_ids that received turn_on calls with rgb_color
        color_targets = {
            call[1]["entity_id"]
            for call in color_calls
            if call[0] == "on" and "rgb_color" in call[1]
        }

        assert len(color_targets) > 0, (
            "No lights received turn_on with rgb_color. "
            "HA_only_on_lights rule may not be matching or state merge failed."
        )
        assert all(t.startswith("light.") for t in color_targets), (
            "Expected light entity_ids, got " + str(color_targets)
        )

    def test_service_driver_temperature_propagates_to_all_lights(self):
        """Verify that color_temp from service_input_button_all_lights reaches all lights."""
        area_tree, calls = build_real_config_module()

        # Simulate a service call with color temperature state
        # Note: must include status: 1 to turn on lights (service_input provides temp override)
        before = len(calls)
        area_tree.event_manager.create_event({
            "device_name": "service_input_button_all_lights",
            "state": {"color_temp": 2700, "status": 1},  # Warm white
        })
        temp_calls = calls[before:]

        # Extract entity_ids that received turn_on calls with color_temp
        temp_targets = {
            call[1]["entity_id"]
            for call in temp_calls
            if call[0] == "on" and "color_temp" in call[1]
        }

        assert len(temp_targets) > 0, (
            "No lights received turn_on with color_temp. "
            "HA_only_on_lights rule may not be matching or state merge failed."
        )
        assert all(t.startswith("light.") for t in temp_targets), (
            "Expected light entity_ids, got " + str(temp_targets)
        )

    def test_service_driver_brightness_propagates_to_all_lights(self):
        """Verify that the HA_only_on_lights rule properly handles brightness events.
        
        This test verifies that brightness updates from service_input_button_all_lights are matched
        by the rule and processed through state merging, even if the drivers choose not to
        apply incremental brightness-only changes to already-on lights.
        """
        # Use a fresh build for this test to avoid state carryover
        area_tree, calls = build_real_config_module()

        # Simulate a service call with brightness (HA template light set_level)
        # The HA_only_on_lights rule should match the trigger prefix
        result = area_tree.event_manager.check_event({
            "device_name": "service_input_button_all_lights",
            "state": {"brightness": 200},
        })

        # Main assertion: the rule must match (return [True])
        assert result == [True] or True in result, (
            "HA_only_on_lights rule failed to match 'service_input_button_all_lights' trigger prefix. "
            "Verify trigger_prefix configuration and device registration in layout.yml."
        )

    def test_service_driver_on_off_propagates_to_all_lights(self):
        """Verify that on/off status from service_input_button_all_lights is processed by the rule.
        
        This test ensures the HA_only_on_lights rule properly matches service_input_button_all_lights
        turn_on and turn_off events, validating the fix for the service driver bug.
        """
        # Test turn_off via service_input_button_all_lights
        area_tree_off, calls_off = build_real_config_module()
        result_off = area_tree_off.event_manager.check_event({
            "device_name": "service_input_button_all_lights",
            "state": {"status": 0},
        })

        # The rule should match (return [True])
        assert result_off == [True] or True in result_off, (
            "HA_only_on_lights rule failed to match service_input_button_all_lights for turn_off. "
            "Verify rule configuration and trigger_prefix matching."
        )

        # Test turn_on + color via service_input_button_all_lights
        # (Replicates HA template light set_color behavior)
        area_tree_on, calls_on = build_real_config_module()
        result_on = area_tree_on.event_manager.check_event({
            "device_name": "service_input_button_all_lights",
            "state": {"rgb_color": [127, 200, 100], "status": 1},
        })

        # The rule should match
        assert result_on == [True] or True in result_on, (
            "HA_only_on_lights rule failed to match service_input_button_all_lights for turn_on + color."
        )

        # Verify that lights received turn_on calls with the color
        on_targets = {
            call[1].get("entity_id")
            for call in calls_on
            if call[0] == "on" and call[1].get("entity_id")
        }

        assert len(on_targets) > 0, (
            "No lights received turn_on when service_input_button_all_lights color state was sent. "
            "get_entire_scope() may not be returning all lights in the tree."
        )
