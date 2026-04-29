import os
import sys
import types

try:
    from .conftest import load_area_tree_with_config
except ImportError:
    from conftest import load_area_tree_with_config


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


def _ensure_test_stubs():
    if "adaptive_learning" not in sys.modules:
        adaptive = types.ModuleType("adaptive_learning")
        adaptive.get_learner = lambda: types.SimpleNamespace(
            record_presence=lambda *args, **kwargs: None,
            record_rule_event=lambda *args, **kwargs: None,
        )
        sys.modules["adaptive_learning"] = adaptive

    if "logger" not in sys.modules:
        logger_mod = types.ModuleType("logger")

        class _Logger:
            def __init__(self, *args, **kwargs):
                pass

            def debug(self, *args, **kwargs):
                pass

            def info(self, *args, **kwargs):
                pass

            def warning(self, *args, **kwargs):
                pass

            def error(self, *args, **kwargs):
                pass

            def fatal(self, *args, **kwargs):
                pass

        logger_mod.Logger = _Logger
        sys.modules["logger"] = logger_mod

    # Don't stub 'modules' — we need the real package for area_graph etc.
    # Only set stubs for submodules that are already stubbed at the bare level.
    if "modules" not in sys.modules:
        # Import the real modules package to make submodules importable
        import importlib
        real_modules = importlib.import_module("modules")
        sys.modules["modules"] = real_modules
    if "modules.adaptive_learning" not in sys.modules:
        # Use the stub from the bare module
        bare = sys.modules.get("adaptive_learning")
        if bare:
            sys.modules["modules.adaptive_learning"] = bare
    if "modules.logger" not in sys.modules:
        sys.modules["modules.logger"] = sys.modules["logger"]


def build_module():
    _ensure_test_stubs()
    previous_cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        area_tree = load_area_tree_with_config(CONFIG_PATHS)
    finally:
        os.chdir(previous_cwd)
    calls = []

    def _mock_state_get(entity_id, *args, **kwargs):
        if entity_id is None:
            return None
        if entity_id.endswith(".rgb_color"):
            return [255, 200, 140]
        if entity_id.endswith(".brightness"):
            return 255
        if entity_id.endswith(".color_temp"):
            return 350
        if entity_id.startswith("light."):
            return "off"
        if entity_id.startswith("switch."):
            return "off"
        if entity_id.startswith("fan."):
            return "off"
        if entity_id.startswith("media_player."):
            return "off"
        return None

    area_tree.light = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(("light.on", kw)),
        turn_off=lambda **kw: calls.append(("light.off", kw)),
    )
    area_tree.switch = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(("switch.on", kw)),
        turn_off=lambda **kw: calls.append(("switch.off", kw)),
    )
    area_tree.fan = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(("fan.on", kw)),
        turn_off=lambda **kw: calls.append(("fan.off", kw)),
    )
    area_tree.media_player = types.SimpleNamespace(
        turn_on=lambda **kw: calls.append(("media_player.on", kw)),
        turn_off=lambda **kw: calls.append(("media_player.off", kw)),
        volume_set=lambda **kw: calls.append(("media_player.volume", kw)),
    )
    area_tree.cover = types.SimpleNamespace(set_cover_position=lambda **kw: calls.append(("cover.set", kw)))
    area_tree.state = types.SimpleNamespace(get=_mock_state_get)
    area_tree.input_boolean = types.SimpleNamespace(motion_sensor_mode="on")
    area_tree.tracker_manager = DummyTrackerManager()
    area_tree.global_triggers = []
    area_tree.config_settings = dict(area_tree.DEFAULT_CONFIG)
    area_tree.config_settings.update(CONFIG_PATHS)

    tree = area_tree.AreaTree(
        area_tree.config_settings["layout"],
        devices_file=area_tree.config_settings["devices"],
    )
    event_manager = area_tree.EventManager(area_tree.config_settings["rules"], tree)
    area_tree.area_tree = tree
    area_tree.event_manager = event_manager
    return area_tree, calls


def test_button_uses_local_area():
    area_tree, calls = build_module()
    area_tree.event_manager.create_event({"device_name": "service_input_button_single_kitchen"})

    on_entities = {
        call[1].get("entity_id")
        for call in calls
        if call[0] == "light.on"
    }
    assert "light.kauf_kitchen_corner" in on_entities
    assert "light.kauf_hanging_5" in on_entities


def test_button_walks_up_to_nearest_outputs():
    area_tree, calls = build_module()
    area_tree.event_manager.create_event({"device_name": "service_input_button_single_hallway_nook"})

    on_entities = {
        call[1].get("entity_id")
        for call in calls
        if call[0] == "light.on"
    }
    assert "light.kauf_hallway" in on_entities


def test_button_target_outputs_override():
    area_tree, calls = build_module()
    area_tree.event_manager.create_event({"device_name": "service_input_button_single_kitchen_corner"})

    on_entities = [
        call[1].get("entity_id")
        for call in calls
        if call[0] == "light.on"
    ]
    assert on_entities == ["light.kauf_kitchen_corner"]


def test_button_does_not_affect_plugs_or_fans():
    area_tree, calls = build_module()
    area_tree.event_manager.create_event({"device_name": "service_input_button_single_office"})

    targeted = {call[1].get("entity_id") for call in calls}
    assert "switch.office_fan" not in targeted
    assert "fan.office_fan" not in targeted


def test_tracker_records_button_area():
    area_tree, _calls = build_module()
    area_tree.event_manager.create_event({"device_name": "service_input_button_single_bathroom"})

    engine = area_tree.occupancy_engine
    assert engine.room_occupancy_confidence("bathroom") > 0.01
    assert engine.room_recent_activity("bathroom")


def test_unknown_button_name_is_ignored_safely():
    area_tree, calls = build_module()
    result = area_tree.event_manager.check_event({"device_name": "service_input_button_single_unknown_room"})

    assert result == [False]
    assert calls == []
