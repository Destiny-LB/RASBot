import json
import tempfile
import unittest
from pathlib import Path
from rasbot.core import Store
from rasbot.runtime import Runtime


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.runtime = Runtime(self.store, Path(self.temp.name) / 'missing')

    def test_demo_persists_and_replay_does_not_duplicate(self):
        identity = self.runtime.create('demo', 'test')
        first = self.runtime.advance(identity)
        second = Runtime(Store(self.temp.name)).advance(identity)
        self.assertEqual(first, second)
        self.assertEqual(first['state'], 'completed')
        self.assertTrue(first['result']['synthetic'])
        self.assertEqual(len(first['events']), 3)

    def test_claim_is_exclusive(self):
        identity = self.runtime.create('demo', 'test')
        self.assertTrue(self.store.transition(identity, 'queued', 'preparing', {}))
        self.assertFalse(self.store.transition(identity, 'queued', 'preparing', {}))

    def test_version_lineage_does_not_mutate_baseline(self):
        parent = self.runtime.baseline
        child = self.store.version({'instructions': 'new'}, parent)
        identity = self.runtime.create('demo', 'test')
        self.assertEqual(self.store.get(identity)['version'], parent)
        self.assertNotEqual(child, parent)
        with self.assertRaises(ValueError):
            self.store.version({}, 'missing')

    def test_unknown_task_and_path_traversal_rejected(self):
        for slug in ('../secret', 'missing'):
            with self.assertRaises(ValueError):
                self.runtime.create('precision', slug)

    def test_evaluation_requires_known_distinct_versions(self):
        with self.assertRaises(ValueError):
            self.store.evaluation(self.runtime.baseline, self.runtime.baseline, 'fixed budget')
        child = self.store.version({'instructions': 'new'}, self.runtime.baseline)
        self.store.evaluation(child, self.runtime.baseline, 'held-out tasks, fixed budget')
        self.assertEqual(self.store.snapshot()['evaluations'][0]['state'], 'planned')


if __name__ == '__main__':
    unittest.main()
