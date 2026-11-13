import json
import unittest
from unittest.mock import patch
import test_evolution
from rasbot.campaigns import Campaigns


class CampaignTests(unittest.TestCase):
    def setUp(self):
        test_evolution.EvolutionTests.setUp(self)
        self.campaigns = Campaigns(self.evo)

    def create(self, rounds=3):
        return self.campaigns.create('改进生成流程，保持固定验收', max_rounds=rounds,
            source_ids=[self.task], slugs=['sample', 'holdout'], model=self.model)

    def close(self, run_id, state='rejected', candidate=False):
        run = self.evo.get(run_id)
        if candidate:
            body = {'agent_id': 'precision', 'agent_instructions': 'archived donor', 'execution_files': {}}
            run['candidate'] = self.runtime.store.version(body, run['baseline'])
            run['trials'] = [{'task_id': self.task, 'comparable': True}]
        run['state'] = state
        self.evo.save(run)
        return run

    def test_restart_recovers_owned_round_without_duplicate(self):
        item = self.create()
        original = self.campaigns.save
        with patch.object(self.campaigns, 'save', side_effect=RuntimeError('crash after run creation')):
            with self.assertRaises(RuntimeError): self.campaigns.tick(item['id'])
        restarted = Campaigns(self.evo)
        recovered = restarted.tick(item['id'])
        self.assertEqual(len(self.evo.list()), 1)
        self.assertEqual(len(recovered['runs']), 1)

    def test_historical_parent_competes_against_current_baseline(self):
        item = self.campaigns.tick(self.create()['id'])
        first = self.close(item['current_run'], candidate=True)
        item = self.campaigns.tick(item['id'])
        second = self.evo.get(item['current_run'])
        self.assertEqual(second['proposal_parent'], first['candidate'])
        self.assertNotEqual(second['baseline'], first['candidate'])
        self.assertEqual(len(second['campaign_context']['experiences']), 1)
        second = self.evo.tick(second['id'])
        text = next(b['text'] for _,p,b in self.client.calls if p.endswith('/prompt'))
        self.assertIn('archived donor', text)
        self.assertIn('Long-term objective', text)
        # Repeated campaign sync cannot duplicate observation rows.
        self.campaigns.tick(item['id'])
        self.assertEqual(len(self.campaigns.experience.list('precision')), 1)

    def test_round_budget_is_not_success_claim(self):
        item = self.campaigns.tick(self.create(rounds=1)['id'])
        self.close(item['current_run'])
        item = self.campaigns.tick(item['id'])
        self.assertEqual(item['state'], 'budget_exhausted')
        self.assertEqual(len(self.evo.list()), 1)

    def test_failure_requires_attention_not_automatic_retry(self):
        item = self.campaigns.tick(self.create()['id'])
        self.close(item['current_run'], state='failed')
        item = self.campaigns.tick(item['id'])
        self.assertEqual(item['state'], 'needs_attention')
        self.campaigns.tick(item['id'])
        self.assertEqual(len(self.evo.list()), 1)
        self.campaigns.control(item['id'], 'resume')
        self.campaigns.tick(item['id'])
        self.assertEqual(len(self.evo.list()), 2)

    def test_pause_stops_owned_round_and_resume_does_not_replay_it(self):
        item = self.campaigns.tick(self.create()['id'])
        first = item['current_run']
        self.campaigns.control(item['id'], 'pause')
        item = self.campaigns.tick(item['id'])
        self.assertEqual(item['state'], 'paused')
        self.assertEqual(self.evo.get(first)['state'], 'cancelled')
        self.campaigns.control(item['id'], 'resume')
        item = self.campaigns.tick(item['id'])
        self.assertNotEqual(item['current_run'], first)

    def test_deadline_stops_before_new_round(self):
        item = self.create(); item['deadline'] = '2000-01-01T00:00:00+00:00'
        self.campaigns.save(item)
        self.assertEqual(self.campaigns.tick(item['id'])['state'], 'budget_exhausted')
        self.assertEqual(self.evo.list(), [])

    def test_duplicate_agent_objective_rejected(self):
        self.create()
        with self.assertRaises(ValueError): self.create()

    def test_manual_round_reserves_agent_slot(self):
        item = self.create()
        self.evo.create([self.task], ['sample', 'holdout'], self.model)
        self.campaigns.tick(item['id'])
        self.assertEqual(len(self.evo.list()), 1)

    def test_memory_is_agent_scoped(self):
        item = self.campaigns.tick(self.create()['id'])
        self.close(item['current_run'])
        self.campaigns.tick(item['id'])
        self.assertEqual(self.campaigns.experience.list('other'), [])
        self.assertNotIn('trial_ids', self.campaigns.experience.recall('precision')[0])

    def test_three_nonimproving_candidates_stop_search(self):
        item = self.create(rounds=6)
        for _ in range(3):
            item = self.campaigns.tick(item['id'])
            self.close(item['current_run'])
        item = self.campaigns.tick(item['id'])
        self.assertEqual(item['state'], 'stopped_no_gain')
        self.assertEqual(len(self.evo.list()), 3)

    def test_changed_champion_cannot_be_overwritten(self):
        run = self.evo.create([self.task], ['sample', 'holdout'], self.model)
        run = test_evolution.EvolutionTests.proposal(self, run)
        newer = self.runtime.store.version({'agent_id': 'precision', 'agent_instructions': 'new adopted version'})
        with self.runtime.store.connect() as c:
            c.execute('INSERT INTO champions VALUES(?,?)', ('precision', newer))
        run = test_evolution.EvolutionTests.finish(self, run, 1, 2)
        self.assertEqual(run['state'], 'inconclusive')
        self.assertEqual(self.runtime.adopted(), newer)
