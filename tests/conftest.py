import types
import sys
import importlib.util
import copy
import builtins
import os


def _stub_decorator(*dargs, **dkwargs):
    if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
        return dargs[0]
    def wrapper(func):
        return func
    return wrapper


def _state_trigger(*args, **kwargs):
    """Stub for pyscript state_trigger decorator."""
    def decorator(func):
        return func
    return decorator


class DummyLog:
    def debug(self, *a, **k):
        pass
    def info(self, *a, **k):
        pass
    def warning(self, *a, **k):
        pass
    def error(self, *a, **k):
        pass
    def fatal(self, *a, **k):
        pass


def load_area_tree(use_real_drivers=None):
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
    # task_unique is a pyscript decorator intercepted at parse time; in tests
    # (exec'd outside pyscript eval) it must be a plain decorator factory.
    def _task_unique_stub(name, kill_me=False):
        def decorator(func):
            return func
        return decorator
    pyscript_mod.task_unique = _task_unique_stub

    # task.sleep stub for schedule_motion_off's _delayed_off inner function
    import asyncio as _asyncio
    task_mod = types.ModuleType('task')
    task_mod.sleep = _asyncio.sleep
    pyscript_mod.task = task_mod
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
        try:
            import homeassistant.util  # noqa: F401
        except Exception:
            util_mod = types.ModuleType('homeassistant.util')
            util_mod.color = types.SimpleNamespace(
                color_RGB_to_hs=lambda *a, **k: (0, 0),
                color_hs_to_RGB=lambda *a, **k: (0, 0, 0),
                color_temperature_to_rgb=lambda *a, **k: (0, 0, 0),
            )
            sys.modules['homeassistant.util'] = util_mod

    if not use_real_drivers:
        # Only stub tracker if it hasn't been loaded as a real module yet.
        # load_tracker() exec's the real modules/tracker.py — overwriting that
        # with object stubs would break tracker tests that run afterward.
        if 'tracker' not in sys.modules:
            tracker_mod = types.ModuleType('tracker')
            tracker_mod.TrackManager = object
            tracker_mod.Track = object
            tracker_mod.Event = object
            sys.modules['tracker'] = tracker_mod

    if 'adaptive_learning' not in sys.modules:
        adaptive_learning_mod = types.ModuleType('adaptive_learning')
        adaptive_learning_mod.Learner = object
        sys.modules['adaptive_learning'] = adaptive_learning_mod

    if 'logger' not in sys.modules:
        logger_mod = types.ModuleType('logger')
        logger_mod.Logger = object
        sys.modules['logger'] = logger_mod

    # Remove specific lines that cause issues in the test environment
    lines_to_remove = {
        "init_config = init()",
        "if init_config.get(\"run_tests_on_start\", DEFAULT_RUN_TESTS_ON_START):",
        "    run_tests()",
        "    test_manager.run_tests()"
    }
    with open('area_tree.py') as f:
        lines = [line for line in f.readlines()
                 if line.rstrip('\n') not in lines_to_remove]
    code = ''.join(lines)

    spec = importlib.util.spec_from_loader('area_tree', loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.log = DummyLog()
    mod.service = _stub_decorator
    mod.event_trigger = _stub_decorator
    mod.pyscript_compile = _stub_decorator
    mod.state_trigger = _state_trigger
    # task_unique is used bare in area_tree.py (pyscript injects it as a global)
    def _task_unique_for_exec(name, kill_me=False):
        def decorator(func):
            return func
        return decorator
    mod.task_unique = _task_unique_for_exec
    # task.sleep is used in _delayed_off; stub with asyncio.sleep
    import asyncio as _asyncio
    _task_mod = types.ModuleType('task')
    _task_mod.sleep = _asyncio.sleep
    mod.task = _task_mod
    sys.modules['area_tree'] = mod
    exec(code, mod.__dict__)
    if use_real_drivers and hasattr(mod, "init"):
        mod.init()
    return mod


def load_area_tree_with_config(config_paths, use_real_drivers=False):
    """Load ``area_tree`` and point it at specific config files for tests.

    ``config_paths`` should be a mapping containing absolute or repo-relative paths
    for one or more config keys from ``DEFAULT_CONFIG``.
    """
    mod = load_area_tree(use_real_drivers=use_real_drivers)
    settings = dict(mod.DEFAULT_CONFIG)
    settings.update(config_paths)
    settings["run_tests_on_start"] = False
    mod.config_settings = settings
    return mod


def load_tracker():
    pyscript_mod = types.ModuleType('pyscript')
    pyscript_mod.service = _stub_decorator
    pyscript_mod.event_trigger = _stub_decorator
    pyscript_mod.pyscript_compile = _stub_decorator
    sys.modules['pyscript'] = pyscript_mod

    # Always install a proper Logger stub so modules/tracker.py can instantiate it
    class _DummyLogger:
        def __init__(self, *a, **k):
            pass
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass
    logger_mod = types.ModuleType('logger')
    logger_mod.Logger = _DummyLogger
    sys.modules['logger'] = logger_mod

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


def pytest_sessionfinish(session, exitstatus):
    """Generate health dashboard after test session."""
    try:
        from tests.health_dashboard import generate_dashboard
    except ImportError:
        from health_dashboard import generate_dashboard
    try:
        generate_dashboard(session, exitstatus)
    except Exception:
        # Dashboard generation must never break the test run outcome.
        pass