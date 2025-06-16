import types
import sys
import importlib.util
import copy

# Helper to load area_tree module without executing init() / run_tests() and stub missing libs

def load_area_tree():
    def stub_decorator(*dargs, **dkwargs):
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        def wrapper(func):
            return func
        return wrapper

    pyscript_mod = types.ModuleType('pyscript')
    pyscript_mod.k_to_rgb = types.ModuleType('pyscript.k_to_rgb')
    pyscript_mod.k_to_rgb.convert_K_to_RGB = lambda x: x
    pyscript_mod.service = stub_decorator
    pyscript_mod.event_trigger = stub_decorator
    pyscript_mod.pyscript_compile = stub_decorator
    sys.modules['pyscript'] = pyscript_mod
    sys.modules['pyscript.k_to_rgb'] = pyscript_mod.k_to_rgb

    sys.modules['homeassistant'] = types.ModuleType('homeassistant')
    sys.modules['homeassistant.const'] = types.ModuleType('homeassistant.const')
    sys.modules['homeassistant.const'].EVENT_CALL_SERVICE = 'call_service'
    ha_util = types.ModuleType('homeassistant.util')
    ha_color = types.ModuleType('homeassistant.util.color')
    ha_color.color_hs_to_RGB = lambda h, s: (h, s, 0)
    ha_color.color_temperature_to_rgb = lambda k: (k, k, k)
    ha_util.color = ha_color
    sys.modules['homeassistant.util'] = ha_util
    sys.modules['homeassistant.util.color'] = ha_color

    tracker_mod = types.ModuleType('tracker')
    tracker_mod.TrackManager = object
    tracker_mod.Track = object
    tracker_mod.Event = object
    sys.modules['tracker'] = tracker_mod

    class DummyLog:
        def info(self, *a, **k):
            pass
        def warning(self, *a, **k):
            pass
        def fatal(self, *a, **k):
            pass

    with open('area_tree.py') as f:
        lines = f.readlines()
    # Remove top-level calls to init() and run_tests()
    lines = [
        line for line in lines
        if not (line.strip() in {"init()", "run_tests()"} and not line.startswith(" "))
    ]
    code = ''.join(lines)

    spec = importlib.util.spec_from_loader('area_tree', loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.log = DummyLog()
    mod.service = stub_decorator
    mod.event_trigger = stub_decorator
    mod.pyscript_compile = stub_decorator
    sys.modules['area_tree'] = mod
    exec(code, mod.__dict__)
    return mod

area_tree = load_area_tree()
Device = area_tree.Device
get_cached_last_set_state = area_tree.get_cached_last_set_state
set_cached_last_set_state = area_tree.set_cached_last_set_state

class DummyDriver:
    def __init__(self, name='dummy'):
        self.name = name
        self.state = {}
    def get_state(self):
        return copy.deepcopy(self.state)
    def set_state(self, state):
        self.state.update(state)
        return copy.deepcopy(self.state)
    def filter_state(self, state):
        return state


def test_get_last_state_empty():
    d = Device(DummyDriver('test'))
    state = d.get_last_state()
    assert state == {'name': 'test'}


def test_get_missing_cache_entry():
    d = Device(DummyDriver('test'))
    assert d.get('status') is None


def test_global_cache_copy():
    d = Device(DummyDriver('dev'))
    sample = {'status': 1}
    set_cached_last_set_state(d, sample)
    ret = get_cached_last_set_state()
    ret['status'] = 0
    assert get_cached_last_set_state() == sample
