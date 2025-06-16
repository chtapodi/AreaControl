from .conftest import load_tracker


def test_track_manager_basic_merge():
    tracker = load_tracker()
    TrackManager = tracker.TrackManager
    GraphManager = tracker.GraphManager

    # disable visualization to avoid file writes
    tracker.GraphManager.visualize_graph = lambda *a, **k: None

    tm = TrackManager()
    tm.graph_manager = GraphManager('tests/scenarios/simple_connections.yml')

    tm.add_event('bedroom')
    tm.add_event('hallway')
    tm.add_event('kitchen')

    tracks = tm.get_tracks()
    assert len(tracks) == 1
    assert len(tracks[0]) == 3
    assert [e.get_area() for e in tracks[0]] == ['kitchen', 'hallway', 'bedroom']
