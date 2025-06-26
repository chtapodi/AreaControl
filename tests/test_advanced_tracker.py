import os
import unittest
import tempfile
import pytest
import yaml
import json
import random

pytest.importorskip("scipy")

from modules.advanced_tracker import (
    load_room_graph_from_yaml,
    SensorModel,
    PersonTracker,
    MultiPersonTracker,
    DEFAULT_MIN_PLOT_TIME,
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
                min_plot_time=0.0,
            )
            multi.process_event('p1', 'bedroom', timestamp=0.0)
            multi.step(timestamp=0.0)
            event_dirs = [
                root
                for root, _, files in os.walk(tmp)
                if any(f.endswith('.png') for f in files)
            ]
            self.assertEqual(len(event_dirs), 1)
            self.assertIn(os.path.join("tests", self._testMethodName), event_dirs[0])
            contents = os.listdir(event_dirs[0])
            self.assertIn('0.0.png', contents)

            legend = getattr(multi, '_last_legend_lines', [])
            self.assertTrue(any(line.strip().startswith('p1:') for line in legend))
            self.assertTrue(any('solid line: estimated path' in line for line in legend))
            self.assertTrue(any('dashed orange: true path (tests only)' in line for line in legend))

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
                min_plot_time=0.0,
            )
            multi.process_event('p1', 'bedroom', timestamp=0.0)
            multi.process_event('p1', 'kitchen', timestamp=1000.0)
            event_dirs = [
                root
                for root, _, files in os.walk(tmp)
                if any(f.endswith('.png') for f in files)
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

    def test_sensor_model_presence(self):
        sm = SensorModel()
        sm.set_presence('bedroom', True)
        self.assertEqual(sm.likelihood_still_present('bedroom', current_time=0.0), 1.0)
        sm.set_presence('bedroom', False)
        self.assertEqual(sm.likelihood_still_present('bedroom', current_time=0.0), 0.0)

    def test_sensor_model_cooldown_and_retrigger(self):
        sm = SensorModel()
        start = 0.0
        sm.record_trigger('bedroom', timestamp=start)

        # Probability stays at 1.0 during the cooldown window
        mid = start + sm.cooldown / 2
        self.assertEqual(sm.likelihood_still_present('bedroom', current_time=mid), 1.0)

        # Retrigger before cooldown expiry should not extend the window
        sm.record_trigger('bedroom', timestamp=start + 100)
        self.assertEqual(sm.likelihood_still_present('bedroom', current_time=start + sm.cooldown - 1), 1.0)

        # After the original cooldown the state resets
        end = start + sm.cooldown + 1
        self.assertEqual(sm.likelihood_still_present('bedroom', current_time=end), sm.floor_prob)
        self.assertFalse(sm.motion_state['bedroom'])

    def test_highlight_probability_formatting(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        multi = MultiPersonTracker(graph, sensor_model, debug=True)
        multi.process_event('p1', 'bedroom', timestamp=0.0)
        multi.set_highlight_room('bedroom')
        text = multi._format_highlight_probabilities()
        self.assertIn('p1', text)
        self.assertIn('bedroom', text)

    def test_particles_stay_put_without_events(self):
        graph = load_room_graph_from_yaml('connections.yml')
        sensor_model = SensorModel()
        random.seed(0)
        tracker = PersonTracker(graph, sensor_model, num_particles=10, stay_prob=1.0)
        visited = {p.room for p in tracker.particles}
        initial = set(visited)
        for i in range(5):
            tracker.update(i)
            visited.update(p.room for p in tracker.particles)
        self.assertEqual(visited, initial)

        random.seed(0)
        mover = PersonTracker(graph, sensor_model, num_particles=10, stay_prob=0.0)
        visited_move = {p.room for p in mover.particles}
        initial_move = set(visited_move)
        for i in range(5):
            mover.update(i)
            visited_move.update(p.room for p in mover.particles)
        self.assertGreater(len(visited_move), len(initial_move))

    def _run_yaml_scenario(self, path: str):
        with open(path, 'r') as f:
            scenario = yaml.safe_load(f)

        scenario_name = scenario.get('name') or os.path.splitext(os.path.basename(path))[0]

        graph = load_room_graph_from_yaml(scenario['connections'])
        sensor_model = SensorModel()
        multi = MultiPersonTracker(
            graph,
            sensor_model,
            test_name=scenario_name,
            min_plot_time=scenario.get('min_plot_time', DEFAULT_MIN_PLOT_TIME),
        )

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
        true_locations = {}
        correct = 0
        total = 0
        while current <= max_t + extra_steps:
            events = time_events.get(current, [])
            updated = set()
            for pid, room in events:
                multi.process_event(pid, room, timestamp=current)
                updated.add(pid)
                true_locations[pid] = room

            multi.step(timestamp=current, skip_ids=updated)

            if events:
                estimates = multi.estimate_locations()
                known = list(true_locations.keys())
                predicted = [estimates.get(pid) for pid in known]
                actual = [true_locations.get(pid) for pid in known]
                if sorted(predicted) == sorted(actual):
                    correct += len(known)
                else:
                    for pid in known:
                        if estimates.get(pid) == true_locations.get(pid):
                            correct += 1
                total += len(known)

            current += 1

        accuracy = correct / total if total else 1.0

        return (
            multi.estimate_locations(),
            scenario.get('expected_final', {}),
            accuracy,
        )

    def test_yaml_scenarios(self):
        scenario_dir = os.path.join('tests', 'scenarios')
        for fname in os.listdir(scenario_dir):
            if not fname.endswith('.yml') or 'connections' in fname:
                continue
            result, expected, accuracy = self._run_yaml_scenario(
                os.path.join(scenario_dir, fname)
            )
            for pid, room in expected.items():
                self.assertEqual(result.get(pid), room)
            self.assertGreaterEqual(accuracy, 0.8)

    def test_event_history_records_all_events(self):
        path = os.path.join('tests', 'scenarios', 'walk_across_house.yml')
        with open(path, 'r') as f:
            scenario = yaml.safe_load(f)

        graph = load_room_graph_from_yaml(scenario['connections'])
        sensor_model = SensorModel()
        multi = MultiPersonTracker(graph, sensor_model, test_name='walk_across_house')

        time_events = {}
        events = []
        for person in scenario.get('persons', []):
            pid = person['id']
            for ev in person.get('events', []):
                t = ev['time']
                time_events.setdefault(t, []).append((pid, ev['room']))
                events.append((t, ev['room']))

        current = 0
        max_t = max(time_events) if time_events else 0
        while current <= max_t:
            for pid, room in time_events.get(current, []):
                multi.process_event(pid, room, timestamp=current)
            multi.step(timestamp=current)
            current += 1

        history = multi._event_history
        self.assertGreaterEqual(len(history), len(events))
        for t, room in events:
            frag = f"{float(t):.1f}s: motion {room}"
            self.assertTrue(any(frag in h for h in history))


if __name__ == '__main__':
    unittest.main()
