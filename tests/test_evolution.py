import json
import unittest
from unittest.mock import patch
import test_agent_runtime
from test_service import FakeClient
from rasbot.evolution import Evolution
from rasbot.opencode_service import Service


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        test_agent_runtime.AgentTests.setUp(self)
        (self.repo / 'tasks/holdout').mkdir()
        (self.repo / 'prompts/holdout.md').write_text('Held-out task')
        self.runtime.store.transition(self.task, 'prepared', 'generated', {'validation': {'passed': True}})
        self.client = FakeClient()
        self.evo = Evolution(self.runtime, Service(self.runtime, self.client))
        self.model = {'id': 'fixed', 'providerID': 'test'}

    def create(self):
        return self.evo.create([self.task], ['sample', 'holdout'], self.model)

    def proposal(self, run):
        self.evo.tick(run['id'])
        original = self.client.request
        proposal = {'diagnosis': 'tool failures', 'agent_instructions': 'Use native file tools.', 'meta_evaluation': 'Coverage is not validated by counts.'}
        def request(method, path, body=None):
            if path.endswith('/context'):
                return {'data': [{'type': 'assistant', 'content': [{'type': 'text', 'text': json.dumps(proposal)}]}, {'type': 'idle', 'outcome': 'succeeded'}]}
            return original(method, path, body)
        self.client.request = request
        return self.evo.tick(run['id'])

    def finish(self, run, baseline_passes, candidate_passes, infrastructure=False):
        counts = {'baseline': baseline_passes, 'candidate': candidate_passes}
        for t in run['trials']:
            passed = counts[t['role']] > 0
            counts[t['role']] -= 1
            state = 'generated' if passed else ('engine_failed' if infrastructure else 'validation_failed')
            self.runtime.store.transition(t['task_id'], 'queued', state, {'validation': {'passed': passed}})
        for _ in range(5):
            run = self.evo.tick(run['id'])
        return run

    def test_candidate_is_immutable_child_and_meta_advisory(self):
        r = self.proposal(self.create())
        self.assertEqual(len(r['trials']), 4)
        with self.runtime.store.connect() as c:
            child = c.execute('SELECT parent,body FROM versions WHERE id=?', (r['candidate'],)).fetchone()
        self.assertEqual(child[0], r['baseline'])
        self.assertNotIn('meta_evaluation', json.loads(child[1]))
        self.assertEqual(r['policy']['max_repairs'], 0)
        prompt = next(b['text'] for _, p, b in self.client.calls if p.endswith('/prompt'))
        self.assertIn('parent_execution_overlay', prompt)
        self.assertNotIn('You plan AI reliability experiments.', prompt)

    def test_strict_improvement_promotes_and_changes_future_default(self):
        r = self.finish(self.proposal(self.create()), 1, 2)
        self.assertEqual(r['state'], 'promoted')
        task = self.runtime.create('precision', 'sample')
        self.assertEqual(self.runtime.store.get(task)['version'], r['candidate'])
        self.evo.rollback(r['id'])
        self.assertEqual(self.runtime.store.get(self.runtime.create('precision', 'sample'))['version'], r['baseline'])
        self.assertEqual(self.runtime.store.get(task)['version'], r['candidate'])

    def test_tie_retains_baseline(self):
        r = self.finish(self.proposal(self.create()), 2, 2)
        self.assertEqual(r['state'], 'rejected')
        self.assertEqual(self.runtime.store.get(self.runtime.create('precision', 'sample'))['version'], r['baseline_source'])

    def test_infrastructure_failure_cannot_promote(self):
        r = self.finish(self.proposal(self.create()), 0, 2, True)
        self.assertEqual(r['state'], 'inconclusive')

    def test_changed_inputs_invalidate_experiment(self):
        (self.repo / 'tasks/sample/config').write_text('old')
        r = self.create()
        (self.repo / 'tasks/sample/config').write_text('new')
        self.assertEqual(self.evo.tick(r['id'])['state'], 'inconclusive')

    def test_missing_prompt_fails_before_model_submission(self):
        (self.repo / 'prompts/holdout.md').unlink()
        with self.assertRaises(ValueError): self.create()
        self.assertEqual(self.client.calls, [])

    def test_evaluator_source_is_preserved(self):
        from pathlib import Path
        r = self.create()
        self.assertTrue((Path(r['root']) / 'evaluator-snapshot/evolution.py').is_file())

    def test_integrity_failure_stops_active_trial(self):
        r = self.proposal(self.create())
        t = r['trials'][0]['task_id']
        self.runtime.store.transition(t, 'queued', 'engine_running', {})
        (self.repo / 'prompts/sample.md').write_text('changed')
        def cancel(identity):
            self.runtime.store.transition(identity, 'engine_running', 'cancelled', {})
            return self.runtime.store.get(identity)
        with patch.object(self.evo.engine, 'cancel', side_effect=cancel) as stop:
            self.assertEqual(self.evo.tick(r['id'])['state'], 'inconclusive')
            stop.assert_called_once_with(t)

    def test_uncertain_prompt_is_not_replayed(self):
        r = self.create(); self.client.fail_prompt = True
        with self.assertRaises(RuntimeError): self.evo.tick(r['id'])
        self.assertEqual(self.evo.tick(r['id'])['state'], 'proposal_unknown')
        self.assertEqual(sum(p.endswith('/prompt') for _, p, _ in self.client.calls), 1)

    def test_requires_holdout_and_explicit_model(self):
        with self.assertRaises(ValueError): self.evo.create([self.task], ['sample', 'holdout'])
        with self.assertRaises(ValueError): self.evo.create([self.task], ['sample', 'sample'], self.model)

    def test_selected_budget_is_pinned(self):
        from pathlib import Path
        r = self.evo.create([self.task], ['sample', 'holdout'], self.model, round_minutes=60)
        self.assertEqual(r['policy']['round_seconds'], 3600)
        self.assertEqual(r['policy']['proposal_seconds'], 300)
        self.assertEqual(r['policy']['trial_seconds'], 735)
        self.assertEqual(json.loads((Path(r['root']) / 'evaluator-snapshot/policy.json').read_text()), r['policy'])

    def test_round_timeout_prevents_new_work_and_collects_evidence(self):
        r = self.proposal(self.create())
        r['deadline'] = '2000-01-01T00:00:00+00:00'
        self.evo.save(r)
        with patch.object(self.runtime, 'advance') as advance:
            r = self.evo.tick(r['id'])
            advance.assert_not_called()
        self.assertEqual(r['state'], 'inconclusive')
        self.assertTrue(all(t['terminal_state'] == 'cancelled' and 'trajectory' in t for t in r['trials']))

    def test_budget_stop_waits_for_confirmation_across_restart(self):
        r = self.proposal(self.create())
        identity = r['trials'][0]['task_id']
        self.runtime.store.transition(identity, 'queued', 'engine_running', {})
        r['deadline'] = '2000-01-01T00:00:00+00:00'
        self.evo.save(r)
        with patch.object(self.evo.engine, 'cancel', return_value={'state': 'engine_running'}):
            self.assertEqual(self.evo.tick(r['id'])['state'], 'cancelling')
        self.runtime.store.transition(identity, 'engine_running', 'cancelled', {})
        restarted = Evolution(self.runtime, self.evo.engine)
        self.assertEqual(restarted.tick(r['id'])['state'], 'inconclusive')

    def test_preparation_consumes_round_budget(self):
        r = self.proposal(self.create())
        def prepare(identity):
            r['deadline'] = '2000-01-01T00:00:00+00:00'
            # Expire the clock read by the controller after the blocking phase.
            clock.return_value = True
        with patch.object(self.evo, 'round_expired', return_value=False) as clock:
            with patch.object(self.runtime, 'advance', side_effect=prepare):
                self.assertEqual(self.evo.tick(r['id'])['state'], 'inconclusive')

    def test_proposer_tool_call_rejected(self):
        r = self.create(); self.evo.tick(r['id'])
        original = self.client.request
        self.client.request = lambda method, path, body=None: ({'data': [{'type': 'assistant', 'content': [{'type': 'tool', 'name': 'shell'}]}]} if path.endswith('/context') else original(method,path,body))
        self.assertEqual(self.evo.tick(r['id'])['state'], 'failed')

    def test_proposal_budget_waits_for_idle(self):
        r = self.evo.tick(self.create()['id'])
        r['started'] = '2000-01-01T00:00:00+00:00'
        self.evo.save(r)
        original = self.client.request
        self.client.request = lambda method, path, body=None: ({'data': []} if path.endswith('/context') else original(method, path, body))
        self.assertEqual(self.evo.tick(r['id'])['state'], 'cancelling')
        self.client.request = lambda method, path, body=None: ({'data': [{'type': 'idle', 'outcome': 'cancelled'}]} if path.endswith('/context') else original(method, path, body))
        self.assertEqual(self.evo.tick(r['id'])['state'], 'inconclusive')

    def test_restart_reads_persisted_state(self):
        r = self.create()
        restarted = Evolution(self.runtime, self.evo.engine)
        self.assertEqual(restarted.get(r['id'])['evaluator_id'], r['evaluator_id'])

    def test_cancel_waits_for_engine_terminal_state(self):
        r = self.proposal(self.create())
        identity = r['trials'][0]['task_id']
        self.runtime.store.transition(identity, 'queued', 'engine_running', {})
        with patch.object(self.evo.engine, 'cancel', return_value={'state': 'engine_running'}):
            self.assertEqual(self.evo.cancel(r['id'])['state'], 'cancelling')
        self.runtime.store.transition(identity, 'engine_running', 'cancelled', {})
        self.assertEqual(self.evo.tick(r['id'])['state'], 'cancelled')


class AgentConcurrencyTests(unittest.TestCase):
    setUp = EvolutionTests.setUp
    create = EvolutionTests.create
    def test_other_agent_run_does_not_block_current_agent(self):
        r=self.create()
        r['agent_id']='other'
        self.evo.save(r)
        current=self.create()
        with self.assertRaisesRegex(ValueError, '当前 Agent'):
            self.create()
        self.assertEqual(self.evo.page()['active_agents'], ['other','precision'])
        current['state']='cancelling'; self.evo.save(current)
        self.assertIn('precision',self.evo.page()['active_agents'])
        current['state']='cancelled'; self.evo.save(current)
        self.assertEqual(self.evo.page()['active_agents'], ['other'])
        self.create()

    def test_activity_is_not_limited_to_current_history_page(self):
        active=self.create()
        with self.runtime.store.connect() as c:
            for i in range(6):
                c.execute('INSERT INTO evolution_runs VALUES(?,?,?)',('terminal'+str(i),json.dumps({'id':str(i),'agent_id':'other','state':'rejected'}),'9999'+str(i)))
        page=self.evo.page()
        self.assertNotIn(active['id'],[r['id'] for r in page['runs']])
        self.assertEqual(page['active_agents'],['precision'])
