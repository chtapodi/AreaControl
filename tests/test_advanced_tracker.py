import os
import unittest
import tempfile
import pytest
import yaml
import json
from unittest.mock import patch

VERBOSE_LEVEL = int(os.getenv("TEST_VERBOSITY", "0"))


def _vprint(*args, **kwargs):
    if VERBOSE_LEVEL >= 2:
        print(*args, **kwargs)


def _get_debug_dir(name: str):
    base = os.environ.get("TEST_DEBUG_DIR", os.path.join("tracker_debug", "plots"))
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path, lambda: None

pytest.importorskip("scipy")

from modules.advanced_tracker import (
    load_room_graph_from_yaml,
    SensorModel,
    PersonTracker,
    MultiPersonTracker,
    Phone,
    Person,
)


class TestAdvancedTracker(unittest.TestCase):
    def test_load_graph(self):
        graph = load_room_graph_from_yaml('connections.yml')
        self.assertIn('bedroom', graph.get_neighbors('bathroom'))
        self.assertIn('bathroom', graph.get_neighbors('bedroom'))

    def test_person_distribution(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        tracker = PersonTracker(graph, sensor_model, num_particles=10)
        now = 0.0
        tracker.update(now, sensor_room='bedroom')
        dist = tracker.distribution()
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=5)

    def test_debug_visualization(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        with tempfile.TemporaryDirectory() as tmp:
            multi = MultiPersonTracker(
                graph,
                sensor_model,
                debug=True,
                debug_dir=tmp,
                test_name=self._testMethodName,
            )
            multi.process_event('p1', 'bedroom')
            multi.step()
            event_dirs = [
                root
                for root, _, files in os.walk(tmp)
                if any(f.startswith('frame_') for f in files)
            ]
            self.assertEqual(len(event_dirs), 1)
            self.assertIn(os.path.join("tests", self._testMethodName), event_dirs[0])
            contents = os.listdir(event_dirs[0])
            self.assertTrue(
                any(f.startswith('frame_') and f.endswith('.png') for f in contents)
            )

            legend = getattr(multi, '_last_legend_lines', [])
            self.assertTrue(any(line.strip().startswith('p1:') for line in legend))
            self.assertTrue(any('width=confidence' in line for line in legend))
            self.assertTrue(any('node color blends with gray' in line for line in legend))
            self.assertTrue(any('dashed orange: true path (tests only)' in line for line in legend))

    def test_event_log_includes_timestamp(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        with tempfile.TemporaryDirectory() as tmp:
            multi = MultiPersonTracker(
                graph,
                sensor_model,
                debug=True,
                debug_dir=tmp,
                test_name=self._testMethodName,
            )
            multi.process_event('p1', 'bedroom', timestamp=5.0)
            self.assertTrue(multi._event_history)
            self.assertIn('5.0', multi._event_history[0])

    def test_multiple_event_directories(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        with tempfile.TemporaryDirectory() as tmp:
            multi = MultiPersonTracker(
                graph,
                sensor_model,
                debug=True,
                debug_dir=tmp,
                event_window=600,
                test_name=self._testMethodName,
            )
            multi.process_event('p1', 'bedroom', timestamp=0.0)
            multi.process_event('p1', 'kitchen', timestamp=1000.0)
            event_dirs = [
                root
                for root, _, files in os.walk(tmp)
                if any(f.startswith('frame_') for f in files)
            ]
            self.assertEqual(len(event_dirs), 1)
            self.assertIn(os.path.join("tests", self._testMethodName), event_dirs[0])

    def test_phone_association_and_state(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        multi = MultiPersonTracker(graph, sensor_model, debug=False)
        import random
        random.seed(0)
        multi.add_phone('ph1')
        multi.associate_phone('ph1', 'alice')
        multi.process_phone_data('ph1', 'bedroom', timestamp=0.0)
        multi.step()
        self.assertIn('alice', multi.people)
        self.assertEqual(multi.people['alice'].phones, ['ph1'])
        state = json.loads(multi.dump_state())
        self.assertEqual(state['phones']['ph1']['person'], 'alice')
        self.assertEqual(state['phones']['ph1']['last_room'], 'bedroom')
        self.assertIn('estimate', state['people']['alice'])

    def test_sensor_model_presence(self):
        model = SensorModel()
        model.set_presence('bedroom', True, timestamp=0.0)
        self.assertEqual(model.likelihood_still_present('bedroom', current_time=10.0), 1.0)
        model.set_presence('bedroom', False, timestamp=20.0)
        self.assertEqual(model.likelihood_still_present('bedroom', current_time=20.0), 0.0)
    def test_highlight_format(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        debug_dir, cleanup = _get_debug_dir('test_highlight_format')
        multi = MultiPersonTracker(graph, sensor_model, debug=True, debug_dir=debug_dir)
        import random
        random.seed(0)
        multi.set_highlight_room('bedroom')
        multi.process_event('p1', 'bedroom', timestamp=0.0)
        multi.process_event('p2', 'kitchen', timestamp=0.0)
        multi.step()
        text = multi._format_highlight_probabilities()
        self.assertIsNotNone(text)
        self.assertTrue(any(line.startswith('p1:') for line in text.splitlines()))
        cleanup()

    def test_debug_interval(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        with tempfile.TemporaryDirectory() as tmp, patch('time.time') as mock_time:
            mock_time.return_value = 0.0
            multi = MultiPersonTracker(
                graph,
                sensor_model,
                debug=True,
                debug_dir=tmp,
                debug_interval=5.0,
            )
            multi.process_event('p1', 'bedroom', timestamp=0.0)
            mock_time.return_value = 1.0
            multi.step()
            mock_time.return_value = 6.0
            multi.step()
            frames = [f for f in os.listdir(tmp) if f.startswith('frame_')]
            self.assertEqual(len(frames), 2)

    def _run_yaml_scenario(self, path: str, *, debug: bool = False):
        with open(path, 'r') as f:
            scenario = yaml.safe_load(f)

        graph = load_room_graph_from_yaml(scenario['connections'])
        sensor_model = SensorModel()

        random_seed = scenario.get('seed', 0)
        import random
        random.seed(random_seed)

        multi = MultiPersonTracker(graph, sensor_model, debug=debug)

        # Build mapping of time -> list of (pid, room)
        time_events = {}
        for person in scenario.get('persons', []):
            pid = person['id']
            for ev in person.get('events', []):
                t = ev['time']
                time_events.setdefault(t, []).append((pid, ev['room']))


        max_t = max(time_events) if time_events else 0
        extra_steps = scenario.get('extra_steps', 10)

        current = 0
        while current <= max_t + extra_steps:
            events = time_events.get(current, [])
            updated = set()
            for pid, room in events:
                multi.process_event(pid, room, timestamp=current)
                updated.add(pid)
                _vprint(f"New motion event: {room} {current}->{current + 1}")

            for pid, tracker in multi.trackers.items():
                if pid not in updated:
                    tracker.update(current)

            multi._updated_since_plot = True
            multi._maybe_visualize(current)

            current += 1

        return multi.estimate_locations(), scenario.get('expected_final', {})

    def test_yaml_scenarios(self):
        scenario_dir = os.path.join('tests', 'scenarios')
        for fname in os.listdir(scenario_dir):
            if not fname.endswith('.yml') or 'connections' in fname:
                continue
            result, expected = self._run_yaml_scenario(os.path.join(scenario_dir, fname))
            for pid, room in expected.items():
                self.assertEqual(result.get(pid), room)

    def _run_yaml_scenario_accuracy(self, path: str) -> float:
        with open(path, "r") as f:
            scenario = yaml.safe_load(f)

        graph = load_room_graph_from_yaml(scenario["connections"])
        sensor_model = SensorModel()

        random_seed = scenario.get("seed", 0)
        import random
        random.seed(random_seed)

        multi = MultiPersonTracker(graph, sensor_model, debug=False)

        time_events = {}
        for person in scenario.get("persons", []):
            pid = person["id"]
            for ev in person.get("events", []):
                t = ev["time"]
                time_events.setdefault(t, []).append((pid, ev["room"]))


        max_t = max(time_events) if time_events else 0
        extra_steps = scenario.get("extra_steps", 10)

        true_locations = {p["id"]: None for p in scenario.get("persons", [])}
        correct = 0
        total = 0

        current = 0
        while current <= max_t + extra_steps:
            events = time_events.get(current, [])
            updated = set()
            for pid, room in events:
                multi.process_event(pid, room, timestamp=current)
                true_locations[pid] = room
                updated.add(pid)
                _vprint(f"New motion event: {room} {current}->{current + 1}")

            for pid, tracker in multi.trackers.items():
                if pid not in updated:
                    tracker.update(current)

            estimates = multi.estimate_locations()
            if VERBOSE_LEVEL >= 2:
                _vprint("True locations:")
                for pid_t, room_t in sorted(true_locations.items()):
                    if room_t is not None:
                        _vprint(f"    {pid_t}: {room_t}")
                _vprint("Estimates:")
                for pid_e, room_e in sorted(estimates.items()):
                    _vprint(f"    {pid_e}: {room_e}")

            location_counts = {}
            for pid, room in true_locations.items():
                if room is not None:
                    location_counts.setdefault(room, set()).add(pid)
            ambiguous = set()
            for room, pids in location_counts.items():
                if len(pids) > 1:
                    ambiguous.update(pids)
            for pid in updated:
                if true_locations[pid] is None or pid in ambiguous:
                    continue
                total += 1
                if estimates.get(pid) == true_locations[pid]:
                    correct += 1

            current += 1

        if total == 0:
            return 1.0
        return correct / total

    def test_yaml_scenario_accuracy(self):
        scenario_dir = os.path.join("tests", "scenarios")
        for fname in os.listdir(scenario_dir):
            if not fname.endswith(".yml") or "connections" in fname:
                continue
            acc = self._run_yaml_scenario_accuracy(os.path.join(scenario_dir, fname))
            self.assertGreaterEqual(acc, 0.8)


if __name__ == '__main__':
    unittest.main()
