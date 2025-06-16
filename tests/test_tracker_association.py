import unittest
import types
import sys
import importlib.util


def load_tracker():
    def stub_decorator(*dargs, **dkwargs):
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        def wrapper(func):
            return func
        return wrapper

    pyscript_mod = types.ModuleType('pyscript')
    pyscript_mod.service = stub_decorator
    pyscript_mod.event_trigger = stub_decorator
    pyscript_mod.pyscript_compile = stub_decorator
    sys.modules['pyscript'] = pyscript_mod
    sys.modules['homeassistant'] = types.ModuleType('homeassistant')
    sys.modules['homeassistant.const'] = types.ModuleType('homeassistant.const')
    sys.modules['homeassistant.const'].EVENT_CALL_SERVICE = 'call_service'

    class DummyLog:
        def info(self, *a, **k):
            pass
        def warning(self, *a, **k):
            pass
        def fatal(self, *a, **k):
            pass

    with open('modules/tracker.py') as f:
        lines = [line for line in f.readlines() if line.strip() != 'plot_graph()']
    code = ''.join(lines)

    spec = importlib.util.spec_from_loader('tracker_mod', loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.log = DummyLog()
    mod.service = stub_decorator
    mod.event_trigger = stub_decorator
    mod.pyscript_compile = stub_decorator
    mod.state = types.SimpleNamespace(set=lambda *a, **k: None)
    exec(code, mod.__dict__)
    return mod


class TestTrackAssociation(unittest.TestCase):
    def setUp(self):
        self.tracker = load_tracker()

    def _make_event(self, area, t):
        e = self.tracker.Event(area)
        e.first_presence_time = t
        e.last_rising_edge_time = t
        return e

    def _make_track(self, areas, times):
        tr = self.tracker.Track()
        events = [self._make_event(a, t) for a, t in zip(areas, times)]
        tr.event_list = list(reversed(events))
        tr.first_event_time = times[0]
        tr.last_event_time = times[-1]
        return tr

    def test_direction_speed_tie_breaker(self):
        gm = self.tracker.GraphManager('connections.yml')
        tm = self.tracker.TrackManager.__new__(self.tracker.TrackManager)
        tm.tracks = []
        tm.max_track_length = 5
        tm.oldest_track = 30 * 60
        tm.max_tracks = 10
        tm.score_threshold = 2.5
        tm.graph_manager = gm

        t1 = self._make_track(['bedroom', 'bathroom'], [0, 1])
        t2 = self._make_track(['office', 'laundry_room'], [0, 1])
        tm.tracks = [t1, t2]

        new_track = self._make_track(['hallway'], [2])

        chosen = []
        original_merge = self.tracker.Track.merge_tracks
        def fake_merge(self, other):
            chosen.append(self)
        self.tracker.Track.merge_tracks = fake_merge
        tm.try_associate_track(new_track)
        self.tracker.Track.merge_tracks = original_merge

        self.assertEqual(chosen[0], t1)


if __name__ == '__main__':
    unittest.main()
