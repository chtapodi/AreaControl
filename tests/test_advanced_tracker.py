import os
import unittest
import tempfile

import yaml

from modules.advanced_tracker import (
    load_room_graph_from_yaml,
    SensorModel,
    PersonTracker,
    MultiPersonTracker,
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
            multi = MultiPersonTracker(graph, sensor_model, debug=True, debug_dir=tmp)
            multi.process_event('p1', 'bedroom', timestamp=0.0)
            multi.step()
            files = sorted(os.listdir(tmp))
        self.assertTrue(any(f.startswith('frame_') and f.endswith('.png') for f in files))
        self.assertTrue(any(f.startswith('state_') and f.endswith('.json') for f in files))

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

        current = 0
        while current <= max_t:
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

    def test_generic_person_created(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        multi = MultiPersonTracker(graph, sensor_model)
        multi.process_event(None, 'bedroom', timestamp=0.0)
        self.assertIn('unknown_0', multi.estimate_locations())

    def test_phone_association(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        multi = MultiPersonTracker(graph, sensor_model)
        multi.associate_phone('alice', 'phone1')
        multi.process_phone_data('phone1', location='kitchen', timestamp=0.0)
        self.assertIn('alice', multi.people)
        self.assertIsNotNone(multi.people['alice'].phone)
        self.assertEqual(multi.people['alice'].phone.location, 'kitchen')


if __name__ == '__main__':
    unittest.main()
