import builtins
import logging
import os
import time

# Provide dummy implementations required by modules.tracker
builtins.pyscript_compile = lambda f: f
builtins.service = lambda f: f

class DummyState:
    def set(self, *args, **kwargs):
        pass

builtins.state = DummyState()
logging.basicConfig(level=logging.INFO)
builtins.log = logging.getLogger("test")

os.environ["MPLBACKEND"] = "Agg"

# Create minimal config files expected by GraphManager when tracker is imported
os.makedirs("pyscript", exist_ok=True)
with open("pyscript/connections.yml", "w") as f:
    f.write("connections: []")

import importlib.util
import pathlib

tracker_path = pathlib.Path(__file__).resolve().parents[1] / "modules" / "tracker.py"
spec = importlib.util.spec_from_file_location("tracker", tracker_path)
tracker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracker)


def test_merge_tracks_no_error_recent_first(tmp_path):
    t1 = tracker.Track()
    t1.add_event("a")
    time.sleep(0.01)
    t1.add_event("b")

    t2 = tracker.Track()
    t2.add_event("c")
    time.sleep(0.01)
    t2.add_event("d")

    # Should not raise
    t1.merge_tracks(t2)
    assert len(t1.get_track_list()) >= 2


def test_merge_tracks_no_error_old_first(tmp_path):
    t2 = tracker.Track()
    t2.add_event("c")
    time.sleep(0.01)
    t2.add_event("d")

    t1 = tracker.Track()
    t1.add_event("a")
    time.sleep(0.01)
    t1.add_event("b")

    t1.merge_tracks(t2)
    assert len(t1.get_track_list()) >= 2
