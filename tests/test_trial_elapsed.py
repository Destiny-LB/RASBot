import unittest
from rasbot.trial_timing import elapsed

class ElapsedTests(unittest.TestCase):
    def test_duration_comes_from_terminal_event(self):
        task = {'state': 'generated', 'events': [{'kind': 'state.generated', 'created': '2026-11-12T00:00:20+00:00'}]}
        self.assertEqual(elapsed(task, '2026-11-12T00:00:00+00:00'), 20)
        self.assertIsNone(elapsed(task, None))