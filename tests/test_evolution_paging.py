import json
import tempfile
import unittest
from rasbot.core import Store
from rasbot.runtime import Runtime
from rasbot.opencode_service import Service
from rasbot.evolution import Evolution


class PagingTests(unittest.TestCase):
    def test_pages_are_bounded_disjoint_and_clamped(self):
        with tempfile.TemporaryDirectory() as root:
            runtime = Runtime(Store(root))
            evolution = Evolution(runtime, Service(runtime))
            self.assertEqual(evolution.page()['total'], 0)
            with runtime.store.connect() as c:
                for i in range(12):
                    identity = f'{i:02d}'
                    c.execute('INSERT INTO evolution_runs VALUES(?,?,?)', (identity, json.dumps({'id': identity, 'state': 'cancelled'}), identity))
            first, second, last = evolution.page(), evolution.page(2), evolution.page(999)
            self.assertEqual([r['id'] for r in first['runs']], ['11','10','09','08','07'])
            self.assertEqual(len(second['runs']), 5)
            self.assertEqual(last['page'], 3)
            self.assertEqual(len(last['runs']), 2)
            self.assertEqual(len({r['id'] for p in (first,second,last) for r in p['runs']}), 12)
            self.assertEqual(len(evolution.page(1,10)['runs']), 10)
            with self.assertRaises(ValueError): evolution.page(0)
            with self.assertRaises(ValueError): evolution.page(1,1000)
