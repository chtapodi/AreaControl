import types
import sys
import importlib.util
import copy
import builtins
import os
from pathlib import Path

import pytest
import yaml


def _stub_decorator(*dargs, **dkwargs):
    if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
        return dargs[0]
    def wrapper(func):
        return func
    return wrapper


class DummyLog:
    def info(self, *a, **k):
        pass
    def warning(self, *a, **k):
        pass
    def fatal(self, *a, **k):
        pass


def load_area_tree(use_real_drivers: bool | None = None):
    """Load ``area_tree`` for tests.

    When ``use_real_drivers`` is True (or the environment variable
    ``AREATREE_REAL_DRIVERS`` is set to ``1``), the module is loaded
    without stubbing Home Assistant modules and ``init()`` is executed so
    the real drivers are used.  Otherwise the missing modules are stubbed
    and ``init`` is not called.
    """
    if use_real_drivers is None:
        use_real_drivers = os.getenv("AREATREE_REAL_DRIVERS") == "1"
    pyscript_mod = types.ModuleType('pyscript')
    pyscript_mod.k_to_rgb = types.ModuleType('pyscript.k_to_rgb')
    pyscript_mod.k_to_rgb.convert_K_to_RGB = lambda x: x
    pyscript_mod.service = _stub_decorator
    pyscript_mod.event_trigger = _stub_decorator
    pyscript_mod.pyscript_compile = _stub_decorator
    pyscript_mod.state_trigger = _stub_decorator
    sys.modules['pyscript'] = pyscript_mod
    sys.modules['pyscript.k_to_rgb'] = pyscript_mod.k_to_rgb

    if not use_real_drivers:
        # Use the real Home Assistant modules when available, otherwise stub them
        try:
            import homeassistant.const  # noqa: F401
        except Exception:
            sys.modules['homeassistant'] = types.ModuleType('homeassistant')
            sys.modules['homeassistant.const'] = types.ModuleType('homeassistant.const')
            sys.modules['homeassistant.const'].EVENT_CALL_SERVICE = 'call_service'
            util_mod = types.ModuleType('homeassistant.util')
            util_mod.color = types.SimpleNamespace(
                color_RGB_to_hs=lambda *a, **k: (0, 0),
                color_hs_to_RGB=lambda *a, **k: (0, 0, 0),
                color_temperature_to_rgb=lambda *a, **k: (0, 0, 0),
            )
            sys.modules['homeassistant.util'] = util_mod

    if not use_real_drivers:
        tracker_mod = types.ModuleType('tracker')
        tracker_mod.TrackManager = object
        tracker_mod.Track = object
        tracker_mod.Event = object
        sys.modules['tracker'] = tracker_mod

    with open('area_tree.py') as f:
        lines = [line for line in f.readlines()
                 if not (line.strip() in {"init()", "run_tests()"} and not line.startswith(" "))]
    code = ''.join(lines)

    spec = importlib.util.spec_from_loader('area_tree', loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.log = DummyLog()
    mod.service = _stub_decorator
    mod.event_trigger = _stub_decorator
    mod.pyscript_compile = _stub_decorator
    mod.state_trigger = _stub_decorator
    sys.modules['area_tree'] = mod
    exec(code, mod.__dict__)
    if use_real_drivers and hasattr(mod, "init"):
        mod.init()
    return mod


def load_tracker():
    pyscript_mod = types.ModuleType('pyscript')
    pyscript_mod.service = _stub_decorator
    pyscript_mod.event_trigger = _stub_decorator
    pyscript_mod.pyscript_compile = _stub_decorator
    sys.modules['pyscript'] = pyscript_mod

    class DummyState:
        def set(self, *a, **k):
            pass
        def get(self, *a, **k):
            return None
    dummy_state = DummyState()

    sys.modules['state'] = dummy_state
    sys.modules['light'] = types.ModuleType('light')
    sys.modules['light'].turn_on = lambda *a, **k: None
    sys.modules['light'].turn_off = lambda *a, **k: None

    with open('modules/tracker.py') as f:
        lines = []
        for line in f.readlines():
            if line.strip() in {'plot_graph()'} and not line.startswith(' '):
                continue
            line = line.replace('./pyscript/connections.yml', 'tests/scenarios/simple_connections.yml')
            lines.append(line)
    code = ''.join(lines)
    spec = importlib.util.spec_from_loader('modules.tracker', loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.log = DummyLog()
    mod.state = dummy_state
    mod.light = sys.modules['light']
    mod.pyscript_compile = _stub_decorator
    mod.service = _stub_decorator
    sys.modules['modules.tracker'] = mod
    exec(code, mod.__dict__)
    return mod


@pytest.fixture
def load_service_area_tree(monkeypatch):
    """Return a loader that prepares ``area_tree`` for service-level tests."""

    fixtures_root = Path(__file__).parent / "fixtures" / "pyscript"
    file_map = {
        "layout.yml": fixtures_root / "layout.yml",
        "rules.yml": fixtures_root / "rules.yml",
        "devices.yml": fixtures_root / "devices.yml",
        "connections.yml": fixtures_root / "connections.yml",
        "./pyscript/layout.yml": fixtures_root / "layout.yml",
        "./pyscript/rules.yml": fixtures_root / "rules.yml",
        "./pyscript/devices.yml": fixtures_root / "devices.yml",
        "./pyscript/connections.yml": fixtures_root / "connections.yml",
    }

    class StubEvent:
        def __init__(self, area):
            self._area = area

        def get_area(self):
            return self._area

    class StubTrack:
        def __init__(self, area):
            self._area = area
            self._events = [StubEvent(area)]

        def add_event(self, area):
            self._events.append(StubEvent(area))

        def get_area(self):
            return self._area

        def get_previous_event(self, index):
            if index < len(self._events):
                return self._events[-index - 1]
            return None

        def get_pretty_string(self):
            return f"Track(area={self._area}, events={len(self._events)})"

    class StubTrackManager:
        def __init__(self):
            self.tracks = []

        def add_event(self, area):
            for track in self.tracks:
                if track.get_area() == area:
                    track.add_event(area)
                    break
            else:
                self.tracks.append(StubTrack(area))
            return self.tracks[-1]

        def get_pretty_string(self):
            if not self.tracks:
                return "<no tracks>"
            return " | ".join(track.get_pretty_string() for track in self.tracks)

    def _load_fixture_yaml(path):
        path_str = str(path)
        target = file_map.get(path_str)
        if target is None:
            key = Path(path_str).name
            target = file_map.get(key)
        if target is None:
            candidate = Path(path_str)
            if not candidate.is_absolute():
                candidate = fixtures_root / candidate.name
            if candidate.exists():
                target = candidate
        if target is None:
            raise FileNotFoundError(f"No fixture mapped for {path_str}")
        with target.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)

    def _ensure_stub_modules():
        if "light" not in sys.modules:
            light_mod = types.ModuleType("light")
            light_mod.calls = []

            def _record(action, **kwargs):
                light_mod.calls.append((action, kwargs))

            light_mod.turn_on = lambda **kwargs: _record("on", **kwargs)
            light_mod.turn_off = lambda **kwargs: _record("off", **kwargs)
            sys.modules["light"] = light_mod
        if "state" not in sys.modules:
            state_mod = types.ModuleType("state")
            state_mod.get = lambda *a, **k: None
            state_mod.set = lambda *a, **k: None
            sys.modules["state"] = state_mod

    def _loader(*, use_real_drivers=False):
        if use_real_drivers and os.getenv("AREATREE_REAL_DRIVERS") != "1":
            pytest.skip("AREATREE_REAL_DRIVERS=1 required for real driver tests")

        if use_real_drivers:
            tracker_module = sys.modules.get("tracker")
            if tracker_module is None or not hasattr(tracker_module, "TrackManager"):
                try:
                    tracker_module = load_tracker()
                except FileNotFoundError as exc:
                    pytest.skip(f"tracker module unavailable for real drivers: {exc}")
                sys.modules["tracker"] = tracker_module

        module = load_area_tree(use_real_drivers=use_real_drivers)

        monkeypatch.setattr(module, "load_yaml", _load_fixture_yaml, raising=False)

        if not use_real_drivers:
            _ensure_stub_modules()
            module.light = sys.modules["light"]
            module.state = sys.modules["state"]
            module.light.calls = []
            original_device_set_state = module.Device.set_state

            def _patched_set_state(self, state):
                expected_status = state.get("status")
                original_device_set_state(self, state)
                if expected_status is not None:
                    if self.cached_state is None:
                        self.cached_state = {}
                    self.cached_state["status"] = expected_status

            module.Device.set_state = _patched_set_state
            module.TrackManager = StubTrackManager
            module.Track = StubTrack
            module.Event = StubEvent
            module.tracker_manager = None
        else:
            tracker_module = sys.modules.get("tracker")
            if tracker_module is not None and hasattr(tracker_module, "TrackManager"):
                module.TrackManager = tracker_module.TrackManager
                module.Track = getattr(tracker_module, "Track", module.Track)
                module.Event = getattr(tracker_module, "Event", module.Event)

        module.area_tree = None
        module.event_manager = None
        module.global_triggers = None
        module.tracker_manager = None

        return module

    return _loader
