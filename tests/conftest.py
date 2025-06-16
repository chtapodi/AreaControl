import types
import sys
import importlib.util
import copy
import builtins


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


def load_area_tree():
    pyscript_mod = types.ModuleType('pyscript')
    pyscript_mod.k_to_rgb = types.ModuleType('pyscript.k_to_rgb')
    pyscript_mod.k_to_rgb.convert_K_to_RGB = lambda x: x
    pyscript_mod.service = _stub_decorator
    pyscript_mod.event_trigger = _stub_decorator
    pyscript_mod.pyscript_compile = _stub_decorator
    sys.modules['pyscript'] = pyscript_mod
    sys.modules['pyscript.k_to_rgb'] = pyscript_mod.k_to_rgb

    sys.modules['homeassistant'] = types.ModuleType('homeassistant')
    sys.modules['homeassistant.const'] = types.ModuleType('homeassistant.const')
    sys.modules['homeassistant.const'].EVENT_CALL_SERVICE = 'call_service'

    adv_mod = types.ModuleType('modules.advanced_tracker')
    class DummyTracker:
        def __init__(self, *a, **k):
            self.debug_dir = 'debug'
            self._debug_counter = 0
        def process_event(self, *a, **k):
            self._debug_counter += 1
        def step(self):
            pass
    adv_mod.init_from_yaml = lambda *a, **k: DummyTracker()
    adv_mod.MultiPersonTracker = DummyTracker
    sys.modules['modules.advanced_tracker'] = adv_mod

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
    sys.modules['area_tree'] = mod
    exec(code, mod.__dict__)
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
