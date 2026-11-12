import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_evolution
from rasbot.development import collect
from rasbot.evolution import Evolution


class DevelopmentTests(unittest.TestCase):
    setUp = test_evolution.EvolutionTests.setUp

    def ready(self):
        (self.repo / 'openskill').mkdir(exist_ok=True)
        (self.repo / 'openskill/01_generate_test_rules.md').write_text('Write report/constraints.md')
        (self.repo / 'scripts').mkdir()
        (self.repo / 'scripts/helper.py').write_text('print(1)\n')
        run = self.evo.create([self.task], ['sample', 'holdout'], self.model, development=True)
        def prepare(runtime, task, target):
            workspace = target / 'workspace'; (workspace / '01_generate/src').mkdir(parents=True)
            (workspace / '01_generate/src/kernel.cpp').write_text('protected')
            return 'prepared', {'workspace': str(workspace)}
        with patch.object(self.runtime.registry.get('precision'), 'prepare', side_effect=prepare):
            return test_evolution.EvolutionTests.proposal(self, run)

    def idle(self, tools=True):
        original = self.client.request
        context = [{'type':'assistant','content': ([{'type':'tool','name':'shell','state':{'status':'completed'}}] if tools else [])},
                   {'type':'idle','outcome':'succeeded'}]
        self.client.request = lambda method,path,body=None: {'data':context} if path.endswith('/context') else original(method,path,body)

    def test_edit_trial_freeze_and_separate_formal_workspaces(self):
        run = self.ready()
        self.assertEqual(run['state'], 'development_ready')
        self.assertEqual(run['trials'], [])
        self.assertNotIn('candidate', run)
        run = self.evo.tick(run['id'])
        (Path(run['development']['package'])/'scripts/helper.py').write_text('print(2)\n')
        self.idle()
        restarted = Evolution(self.runtime, self.evo.engine)
        with patch('rasbot.development_checks.check', return_value={'passed': True}):
            run = restarted.tick(run['id'])
        self.assertEqual(run['state'], 'evaluating')
        self.assertEqual(run['development']['status'], 'frozen')
        self.assertEqual(len(run['trials']), 4)
        with self.runtime.store.connect() as c:
            body = json.loads(c.execute('SELECT body FROM versions WHERE id=?',(run['candidate'],)).fetchone()[0])
        self.assertEqual(body['execution_files']['scripts/helper.py'], 'print(2)\n')
        self.assertEqual((self.repo/'scripts/helper.py').read_text(), 'print(1)\n')
        self.assertTrue(all(self.runtime.store.get(t['task_id'])['result']=={} for t in run['trials']))

    def test_protected_task_change_rejects_freeze(self):
        run=self.evo.tick(self.ready()['id']); self.idle()
        (Path(run['development']['workspace'])/'01_generate/src/kernel.cpp').write_text('changed')
        run=self.evo.tick(run['id'])
        self.assertEqual(run['state'],'failed'); self.assertEqual(run['trials'],[])
        self.assertEqual(run['development']['check']['validation']['asset_changes']['modified'], ['01_generate/src/kernel.cpp'])

    def test_no_tool_trial_cannot_freeze(self):
        run=self.evo.tick(self.ready()['id']); self.idle(False)
        self.assertEqual(self.evo.tick(run['id'])['state'],'failed')

    def test_timeout_stops_development(self):
        run=self.evo.tick(self.ready()['id']); self.idle()
        run['development']['started']='2000-01-01T00:00:00+00:00';self.evo.save(run)
        result=self.evo.tick(run['id'])
        self.assertEqual(result['state'],'inconclusive')
        self.assertTrue(any(p.endswith('/interrupt') for _,p,_ in self.client.calls))

    def test_unknown_request_not_replayed(self):
        run=self.ready();self.client.fail_prompt=True
        with self.assertRaises(RuntimeError):self.evo.tick(run['id'])
        count=len(self.client.calls)
        self.assertEqual(self.evo.tick(run['id'])['state'],'development_unknown')
        self.assertEqual(len(self.client.calls),count)

    def test_deleted_disallowed_and_invalid_sources_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'scripts').mkdir()
            with self.assertRaises(ValueError):collect(root,['scripts/base.py'])
            (root/'scripts/base.py').write_text('def broken(')
            with self.assertRaises(ValueError):collect(root,[])
            (root/'scripts/base.py').write_text('print(1)')
            (root/'scripts/create_workspace.py').write_text('print(1)')
            with self.assertRaises(ValueError):collect(root,[])

    def test_budget_reserves_development_without_extending_round(self):
        run=self.ready();p=run['policy']
        self.assertEqual(p['development_seconds'],720)
        self.assertEqual(p['round_seconds'],p['proposal_seconds']+p['development_seconds']+p['max_trials']*p['trial_seconds']+p['overhead_seconds'])
