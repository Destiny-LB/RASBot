import tempfile
import unittest
from pathlib import Path
from rasbot.core import Store
from rasbot.runtime import Runtime
from rasbot.evolution_selection import Selection


class SelectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.runtime = Runtime(Store(root / 'state'), root / 'repo')
        for slug in ('a', 'b'):
            (self.runtime.repo / 'tasks' / slug).mkdir(parents=True)
        (self.runtime.repo / 'prompts').mkdir()
        for slug in ('a', 'b'):
            (self.runtime.repo / 'prompts' / (slug + '.md')).write_text('task')
        self.selection = Selection(self.runtime)

    def task(self, slug, state):
        identity = self.runtime.create('precision', slug)
        self.runtime.store.transition(identity, 'queued', state, {'session_id': 'real-session'})
        return identity

    def test_failure_and_success_control_leave_holdout(self):
        success = self.task('a', 'generated')
        failure = self.task('a', 'validation_failed')
        self.task('b', 'generated')
        r = self.selection.recommend()
        self.assertEqual(r['source_ids'], [failure, success])
        self.assertEqual(r['slugs'], ['a', 'b'])
        self.assertTrue(r['ready'])

    def test_no_evidence_does_not_invent_diagnosis(self):
        r = self.selection.recommend()
        self.assertFalse(r['ready'])
        self.assertEqual(r['source_ids'], [])

    def test_fixed_pool_does_not_silently_expand(self):
        self.selection.pool()
        (self.runtime.repo / 'tasks/new').mkdir()
        (self.runtime.repo / 'prompts/new.md').write_text('new')
        self.assertNotIn('new', self.selection.recommend()['pool'])

    def test_success_only_selects_latest_and_excludes_unstarted_cancel(self):
        self.task('a', 'generated')
        newest = self.task('b', 'generated')
        self.task('a', 'cancelled')
        r = self.selection.recommend()
        self.assertEqual(r['source_ids'], [newest])
        self.assertEqual(r['slugs'], ['b', 'a'])
