import tempfile
import unittest
from pathlib import Path
from rasbot.agents import AgentRegistry, DemoAgent
from rasbot.core import Store
from rasbot.runtime import Runtime
from rasbot.evolution import Evolution
from rasbot.evolution_selection import Selection
from rasbot.opencode_service import Service


class FixtureAgent(DemoAgent):
    id = 'fixture'
    name = 'Test-only reliability adapter'
    execution = True
    evolution = True
    harness_id = 'fixture-harness'
    evaluator_id = 'fixture-evaluator'
    evolution_goal = 'Test registry isolation'
    proposal_constraints = 'Execute fixture tasks only.'
    def catalog(self): return ['recovery-a', 'recovery-b']
    def eligible(self, key): return key in self.catalog()
    def holdout_key(self, anchor, key): return key
    def assets(self, keys): return []
    def policy(self):
        return {'version': self.evaluator_id, 'max_session_seconds': 1800, 'max_repairs': 0}
    def evaluate(self, task):
        return {'passed': task['result'].get('fixture_pass', False), 'comparable': task['state'] == 'completed'}


class AgentTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.store = Store(root.name)
        self.runtime = Runtime(self.store, Path(root.name) / 'no-precision-repo')
        self.runtime.registry.register(FixtureAgent())

    def test_non_precision_preparation_without_repo_layout(self):
        self.assertEqual(self.runtime.catalog('fixture'), ['recovery-a', 'recovery-b'])
        task = self.runtime.create('fixture', 'recovery-a')
        result = self.runtime.advance(task)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(self.runtime.describe(result)['agent_name'], FixtureAgent.name)

    def test_unconnected_agents_rejected_and_cross_agent_version_blocked(self):
        for identity in ('sdc', 'resilience', 'unknown'):
            with self.assertRaises(ValueError): self.runtime.create(identity, 'task')
        with self.assertRaises(ValueError):
            self.runtime.create('fixture', 'recovery-a', self.runtime.baseline)
        self.assertNotEqual(self.runtime.adopted('fixture'), self.runtime.adopted('precision'))

    def test_selection_and_evolution_use_adapter_contract(self):
        source = self.runtime.create('fixture', 'recovery-a')
        self.store.transition(source, 'queued', 'generated', {'session_id': 'fixture-session'})
        selection = Selection(self.runtime, 'fixture').recommend()
        self.assertEqual(selection['source_ids'], [source])
        self.assertEqual(selection['slugs'], ['recovery-a', 'recovery-b'])
        self.assertEqual(selection['agent_id'], 'fixture')
        self.assertEqual(Selection(self.runtime, 'precision').recommend()['source_ids'], [])
        evolution = Evolution(self.runtime, Service(self.runtime))
        run = evolution.create([source], selection['slugs'], {'id': 'test', 'providerID': 'test'}, agent_id='fixture')
        self.assertEqual(run['agent_id'], 'fixture')
        self.assertEqual(run['harness_id'], 'fixture-harness')
        self.assertEqual(run['policy']['version'], 'fixture-evaluator')
        self.assertFalse(any('no-precision-repo' in p for p in run['assets']))

    def test_custom_evaluator_and_adoption_are_not_precision_scoped(self):
        source = self.runtime.create('fixture', 'recovery-a')
        self.store.transition(source, 'queued', 'generated', {'session_id': 'fixture'})
        evolution = Evolution(self.runtime, Service(self.runtime))
        run = evolution.create([source], ['recovery-a', 'recovery-b'], {'id': 'test', 'providerID': 'test'}, agent_id='fixture')
        candidate = self.store.version({'agent_id': 'fixture', 'agent_instructions': 'test'}, run['baseline'])
        run.update(candidate=candidate, state='evaluating')
        for slug in run['slugs']:
            for role in ('baseline', 'candidate'):
                identity = self.runtime.create('fixture', slug, run[role])
                self.store.transition(identity, 'queued', 'completed', {'fixture_pass': role == 'candidate'})
                run['trials'].append({'task_id': identity, 'role': role, 'slug': slug})
        evolution.save(run)
        for _ in range(5): run = evolution.tick(run['id'])
        self.assertEqual(run['state'], 'promoted')
        self.assertEqual(self.runtime.adopted('fixture'), candidate)
        self.assertEqual(self.runtime.adopted('precision'), self.runtime.baseline)
        evolution.rollback(run['id'])
        self.assertEqual(self.runtime.adopted('fixture'), run['baseline'])

    def test_invalid_registry_identity_rejected(self):
        agent = FixtureAgent()
        agent.id = '../bad'
        with self.assertRaises(ValueError): AgentRegistry([agent])
