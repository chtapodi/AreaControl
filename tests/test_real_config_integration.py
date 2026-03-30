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

EXPECTED_ROOM_LIGHTS = {
    "kitchen": {
        "motion_sensor": "motion_sensor_kitchen",
        "lights": [
            "light.hue_kitchen_ball",
            "light.kauf_kitchen_corner",
            "light.kauf_hanging_5",
        ],
    },
    "bathroom": {
        "motion_sensor": "motion_sensor_bathroom",
        "lights": [
            "light.hue_bathroom_center",
            "light.kauf_bathroom_0",
            "light.kauf_bathroom_1",
        ],
    },
    "hallway": {
        "motion_sensor": "motion_sensor_hallway",
        "lights": ["light.kauf_hallway"],
    },
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


def test_real_config_area_tree_builds_expected_rooms_and_devices():
    area_tree, _calls = build_real_config_module()
    tree = area_tree.area_tree

    for room_name, room_cfg in EXPECTED_ROOM_LIGHTS.items():
        room = tree.get_area(room_name)
        assert room is not None, f"Expected area {room_name} to exist"

        device_names = sorted(device.name for device in room.get_devices())
        expected_names = sorted(light.removeprefix("light.") for light in room_cfg["lights"])
        for expected in expected_names:
            assert expected in device_names, (
                f"Expected {expected} in area {room_name}, found {device_names}"
            )


def test_real_motion_rules_turn_expected_room_lights_on_and_off():
    area_tree, calls = build_real_config_module()

    for room_name, room_cfg in EXPECTED_ROOM_LIGHTS.items():
        motion_sensor = room_cfg["motion_sensor"]
        expected_lights = set(room_cfg["lights"])

        before = len(calls)
        area_tree.event_manager.create_event({
            "device_name": motion_sensor,
            "tags": ["on", "motion_detected"],
        })
        on_calls = calls[before:]
        on_targets = {
            call[1]["entity_id"]
            for call in on_calls
            if call[0] == "on" and call[1].get("entity_id") in expected_lights
        }
        assert expected_lights.issubset(on_targets), (
            f"Expected turn_on calls for {room_name}: {sorted(expected_lights)}, got {sorted(on_targets)}"
        )

        before = len(calls)
        area_tree.event_manager.create_event({
            "device_name": motion_sensor,
            "tags": ["off", "motion_detected"],
        })
        off_calls = calls[before:]
        off_targets = {
            call[1]["entity_id"]
            for call in off_calls
            if call[0] == "off" and call[1].get("entity_id") in expected_lights
        }
        assert expected_lights.issubset(off_targets), (
            f"Expected turn_off calls for {room_name}: {sorted(expected_lights)}, got {sorted(off_targets)}"
        )
