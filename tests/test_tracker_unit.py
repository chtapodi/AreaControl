"""Tests for Track, Event, and TrackManager functionality."""
import time
from .conftest import load_tracker


def _setup():
    """Load tracker and configure for testing."""
    tracker = load_tracker()
    tracker.GraphManager.visualize_graph = lambda *a, **k: None
    return tracker


class TestEvent:
    def test_event_area(self):
        tracker = _setup()
        ev = tracker.Event("kitchen")
        assert ev.get_area() == "kitchen"

    def test_impulse_duration_is_zero(self):
        tracker = _setup()
        ev = tracker.Event("kitchen", inpulse=True)
        assert ev.get_duration() == 0

    def test_presence_updates_rising_edge(self):
        tracker = _setup()
        ev = tracker.Event("kitchen")
        t1 = ev.last_rising_edge_time
        time.sleep(0.01)
        ev.presence()
        assert ev.last_rising_edge_time > t1
        assert ev.last_falling_edge_time is None

    def test_absence_sets_falling_edge(self):
        tracker = _setup()
        ev = tracker.Event("kitchen")
        assert ev.last_falling_edge_time is None
        ev.absence()
        assert ev.last_falling_edge_time is not None

    def test_end_sets_falling_edge(self):
        tracker = _setup()
        ev = tracker.Event("kitchen")
        ev.end()
        assert ev.last_falling_edge_time is not None

    def test_get_copy_independence(self):
        tracker = _setup()
        ev = tracker.Event("kitchen")
        ev.presence()
        cp = ev.get_copy()
        assert cp.get_area() == ev.get_area()
        assert cp.first_presence_time == ev.first_presence_time
        # Mutating copy should not affect original
        cp.absence()
        assert ev.last_falling_edge_time is None


class TestTrack:
    def test_single_event(self):
        tracker = _setup()
        track = tracker.Track()
        track.add_event("kitchen")
        assert track.get_area() == "kitchen"
        assert len(track.get_track_list()) == 1

    def test_same_area_updates_existing(self):
        tracker = _setup()
        track = tracker.Track()
        track.add_event("kitchen")
        track.add_event("kitchen")
        assert len(track.get_track_list()) == 1

    def test_different_area_creates_new_event(self):
        tracker = _setup()
        track = tracker.Track()
        track.add_event("kitchen")
        time.sleep(0.01)
        track.add_event("hallway")
        assert len(track.get_track_list()) == 2
        assert track.get_head().get_area() == "hallway"

    def test_get_duration_returns_number(self):
        tracker = _setup()
        track = tracker.Track()
        track.add_event("kitchen")
        time.sleep(0.01)
        track.add_event("hallway")
        duration = track.get_duration()
        assert isinstance(duration, (int, float))

    def test_trim_enforces_max_length(self):
        tracker = _setup()
        track = tracker.Track(max_length=2)
        track.add_event("kitchen")
        time.sleep(0.01)
        track.add_event("hallway")
        time.sleep(0.01)
        track.add_event("bedroom")
        track._trim()
        assert len(track.get_track_list()) == 2

    def test_get_previous_event(self):
        tracker = _setup()
        track = tracker.Track()
        track.add_event("kitchen")
        time.sleep(0.01)
        track.add_event("hallway")
        prev = track.get_previous_event()
        assert prev.get_area() == "kitchen"

    def test_get_previous_event_none_when_single(self):
        tracker = _setup()
        track = tracker.Track()
        track.add_event("kitchen")
        assert track.get_previous_event() is None

    def test_get_pretty_string(self):
        tracker = _setup()
        track = tracker.Track()
        track.add_event("kitchen")
        s = track.get_pretty_string()
        assert "kitchen" in s


class TestTrackManager:
    def test_single_event_creates_track(self):
        tracker = _setup()
        tm = tracker.TrackManager()
        tm.graph_manager = tracker.GraphManager('tests/scenarios/simple_connections.yml')
        tm.add_event("kitchen")
        assert len(tm.tracks) == 1

    def test_adjacent_events_merge(self):
        tracker = _setup()
        tm = tracker.TrackManager()
        tm.graph_manager = tracker.GraphManager('tests/scenarios/simple_connections.yml')
        tm.add_event("bedroom")
        tm.add_event("hallway")
        assert len(tm.tracks) == 1

    def test_distant_events_split(self):
        tracker = _setup()
        tm = tracker.TrackManager(score_threshold=1.5)
        tm.graph_manager = tracker.GraphManager('tests/scenarios/simple_connections.yml')
        tm.add_event("bedroom")
        tm.add_event("kitchen")  # 2 hops away, above threshold
        assert len(tm.tracks) == 2

    def test_event_not_in_graph_ignored(self):
        tracker = _setup()
        tm = tracker.TrackManager()
        tm.graph_manager = tracker.GraphManager('tests/scenarios/simple_connections.yml')
        tm.add_event("nonexistent_room")
        assert len(tm.tracks) == 0

    def test_cleanup_removes_old_tracks(self):
        tracker = _setup()
        tm = tracker.TrackManager(oldest_track=0)
        tm.graph_manager = tracker.GraphManager('tests/scenarios/simple_connections.yml')
        tm.add_event("kitchen")
        time.sleep(0.01)
        tm.cleanup_tracks()
        assert len(tm.tracks) == 0

    def test_merge_tracks_preserves_order(self):
        tracker = _setup()
        tm = tracker.TrackManager()
        tm.graph_manager = tracker.GraphManager('tests/scenarios/simple_connections.yml')
        tm.add_event("bedroom")
        time.sleep(0.01)
        tm.add_event("hallway")
        time.sleep(0.01)
        tm.add_event("kitchen")
        tracks = tm.get_tracks()
        assert len(tracks) == 1
        areas = [e.get_area() for e in tracks[0]]
        assert areas == ["kitchen", "hallway", "bedroom"]
