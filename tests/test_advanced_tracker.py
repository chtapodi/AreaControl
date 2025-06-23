import os
import unittest
import tempfile
import pytest
import yaml
import json

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

    def test_event_log_includes_timestamp(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        multi = MultiPersonTracker(graph, sensor_model, debug=True)
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
        multi = MultiPersonTracker(graph, sensor_model)
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

    def _run_yaml_scenario(self, path: str):
        with open(path, 'r') as f:
            scenario = yaml.safe_load(f)

        graph = load_room_graph_from_yaml(scenario['connections'])
        sensor_model = SensorModel()
        multi = MultiPersonTracker(graph, sensor_model)

        # Build mapping of time -> list of (pid, room)
        time_events = {}
        for person in scenario.get('persons', []):
            pid = person['id']
            for ev in person.get('events', []):
                t = ev['time']
                time_events.setdefault(t, []).append((pid, ev['room']))

        random_seed = scenario.get('seed', 0)
        import random
        random.seed(random_seed)

        max_t = max(time_events) if time_events else 0
        extra_steps = scenario.get('extra_steps', 10)

        current = 0
        while current <= max_t + extra_steps:
            events = time_events.get(current, [])
            updated = set()
            for pid, room in events:
                multi.process_event(pid, room, timestamp=current)
                updated.add(pid)

            for pid, tracker in multi.trackers.items():
                if pid not in updated:
                    tracker.update(current)

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


if __name__ == '__main__':
    unittest.main()
