import os
import unittest
import yaml
from modules.adaptive_learning import AdaptiveLearner

class TestAdaptiveLearner(unittest.TestCase):
    def setUp(self):
        self.history = 'tests/tmp_history.yml'
        if os.path.exists(self.history):
            os.remove(self.history)
        self.learner = AdaptiveLearner(history_file=self.history)

    def tearDown(self):
        if os.path.exists(self.history):
            os.remove(self.history)

    def test_event_logging_and_analysis(self):
        # record presence at hour 1
        self.learner.record_presence('living_room', timestamp=3600)
        # two brightness events at hour 1
        self.learner.collect_event({'device_name': 'light.lr', 'rule_name': 'auto',
                                   'final_state': {'brightness': 150}, 'timestamp': 3600})
        self.learner.collect_event({'device_name': 'light.lr', 'rule_name': 'auto',
                                   'final_state': {'brightness': 50}, 'timestamp': 3700})

        # file should contain three entries
        with open(self.history, 'r') as f:
            data = yaml.safe_load(f)
        self.assertEqual(len(data), 3)

        patterns = self.learner.analyze_patterns()
        self.assertEqual(patterns['presence_by_area_hour']['living_room'][1], 1)
        self.assertAlmostEqual(patterns['avg_brightness_by_hour'][1], 100)

if __name__ == '__main__':
    unittest.main()

