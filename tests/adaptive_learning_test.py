import types
import sys
import importlib.util


def load_adaptive_learning():
    def stub_decorator(*dargs, **dkwargs):
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        def wrapper(func):
            return func
        return wrapper

    pyscript_mod = types.ModuleType('pyscript')
    pyscript_mod.service = stub_decorator
    sys.modules['pyscript'] = pyscript_mod

    with open('modules/adaptive_learning.py') as f:
        code = f.read()
    spec = importlib.util.spec_from_loader('modules.adaptive_learning', loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.service = stub_decorator
    sys.modules['modules.adaptive_learning'] = mod
    exec(code, mod.__dict__)
    return mod


def test_event_logging_and_pattern():
    mod = load_adaptive_learning()
    learner = mod.get_learner()

    seq = ['kitchen', 'hallway', 'bedroom', 'kitchen', 'hallway', 'bedroom']
    for ts, area in enumerate(seq):
        learner.record_presence(area, timestamp=float(ts))

    learner.record_rule_event('lights_on', timestamp=10.0)

    assert learner.get_rule_log()[-1][1] == 'lights_on'
    suggestions = learner.suggest_rules()
    assert {'sequence': ['kitchen', 'hallway'], 'count': 2} in suggestions
