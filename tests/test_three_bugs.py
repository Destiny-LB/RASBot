import unittest
import sqlite3
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import test_evolution
from rasbot.execution_package import hashes
from rasbot.precision_development import observe
from rasbot.trial_timing import completion


class PromotionTests(unittest.TestCase):
    setUp = test_evolution.EvolutionTests.setUp
    proposal = test_evolution.EvolutionTests.proposal
    finish = test_evolution.EvolutionTests.finish

    def test_commit_failure_rolls_back_champion_and_can_resume(self):
        r = self.proposal(self.evo.create([self.task], ['sample','holdout'], self.model))
        with self.runtime.store.connect() as c:
            c.execute("CREATE TRIGGER fail_commit BEFORE UPDATE ON evolution_runs WHEN json_extract(NEW.body, '$.state') = 'promoted' BEGIN SELECT RAISE(ABORT, 'simulated crash'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.finish(r, 1, 2)
        self.assertEqual(self.evo.get(r['id'])['state'], 'evaluating')
        self.assertNotEqual(self.runtime.adopted('precision'), r['candidate'])
        with self.runtime.store.connect() as c: c.execute('DROP TRIGGER fail_commit')
        self.assertEqual(self.evo.tick(r['id'])['state'], 'promoted')
        self.assertEqual(self.runtime.adopted('precision'), r['candidate'])

    def test_finished_task_is_synced_before_timeout(self):
        r = self.proposal(self.evo.create([self.task], ['sample','holdout'], self.model))
        t = r['trials'][0]; start = datetime.now(timezone.utc)-timedelta(seconds=100)
        t['started'] = start.isoformat();r['policy']['trial_seconds'] = 50;self.evo.save(r)
        self.runtime.store.transition(t['task_id'], 'queued', 'engine_running', {})
        def sync(identity):
            self.runtime.store.transition(identity, 'engine_running', 'generated', {'engine_completed_ms': (start.timestamp()+40)*1000})
            return self.runtime.store.get(identity)
        with patch.object(self.evo.engine, 'sync', side_effect=sync), patch.object(self.evo.engine, 'cancel') as cancel:
            out = self.evo.tick(r['id'])
        self.assertEqual(out['state'], 'evaluating');cancel.assert_not_called()
        self.assertEqual(out['trials'][0]['completion_timing'], 'within_budget')


class EvidenceTests(unittest.TestCase):
    def test_proposal_only_edit_is_in_full_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'scripts';p.mkdir();(p/'helper.py').write_text('print(2)')
            result=observe({'package':tmp, 'parent_file_hashes':hashes({'scripts/helper.py':'print(1)'}),
                            'initial_file_hashes':hashes({'scripts/helper.py':'print(2)'})})
            self.assertEqual(result['components'], ['scripts'])
            self.assertEqual(result['development_delta']['paths'], [])

    def test_missing_and_late_completion_are_not_accepted(self):
        start=datetime.now(timezone.utc)-timedelta(seconds=100)
        self.assertEqual(completion({'state':'generated','result':{}},start,50),'unknown')
        self.assertEqual(completion({'state':'generated','result':{'engine_completed_ms':(start.timestamp()+80)*1000}},start,50),'over_budget')
