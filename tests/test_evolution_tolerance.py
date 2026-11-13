import json
import unittest
from unittest.mock import patch
import test_evolution
from rasbot.precision_warnings import classify


class ToleranceTests(unittest.TestCase):
    setUp = test_evolution.EvolutionTests.setUp
    proposal = test_evolution.EvolutionTests.proposal
    finish = test_evolution.EvolutionTests.finish

    def test_first_comparison_has_priority(self):
        r = self.evo.create([self.task], ['sample', 'holdout'], self.model, 120, development=True)
        self.assertEqual(r['policy']['trial_seconds'], 1320)
        self.assertEqual(r['policy']['initial_trials'], 4)
        self.assertEqual(r['policy']['max_trials'], 8)

    def test_format_repairs_are_bounded_and_keep_original_clock(self):
        r = self.evo.tick(self.evo.create([self.task], ['sample','holdout'], self.model)['id'])
        started = r['started']
        original = self.client.request
        self.client.request = lambda method,path,body=None: {'data': [
            {'type':'assistant','content':[{'type':'text','text':'invalid JSON'}]},
            {'type':'idle','outcome':'succeeded'}]} if path.endswith('/context') else original(method,path,body)
        for i in range(3):
            r = self.evo.tick(r['id'])
            self.assertEqual(r['started'], started)
            self.assertEqual(r['state'], 'proposing' if i < 2 else 'failed')
        self.assertEqual(len(r['proposal_errors']), 3)
        self.assertEqual(r['trials'], [])

    def test_uncertain_repair_request_is_not_replayed(self):
        r = self.evo.tick(self.evo.create([self.task], ['sample','holdout'], self.model)['id'])
        original = self.client.request
        def request(method,path,body=None):
            if path.endswith('/context'):
                return {'data':[{'type':'assistant','content':[{'type':'text','text':'bad'}]}, {'type':'idle','outcome':'succeeded'}]}
            if path.endswith('/prompt'): raise RuntimeError('uncertain')
            return original(method,path,body)
        self.client.request = request
        with self.assertRaises(RuntimeError): self.evo.tick(r['id'])
        self.assertEqual(self.evo.tick(r['id'])['state'], 'proposal_unknown')

    def test_confirmation_needs_budget_and_cannot_promote(self):
        r = self.proposal(self.evo.create([self.task], ['sample','holdout'], self.model, 120))
        from datetime import datetime, timezone, timedelta
        r['deadline'] = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        self.evo.save(r)
        with patch('rasbot.evolution.decide', return_value={'state':'confirming','reason':'potential speedup'}):
            r = self.finish(r, 2, 2)
        self.assertEqual(r['state'], 'inconclusive')
        self.assertTrue(r['decision']['confirmation_required'])
        self.assertEqual(len(r['trials']), 4)

    def test_warning_classes_preserve_semantic_gates(self):
        warnings = classify("WARNING: library.source_path should be 'docs/trigger_library.md'\nWARNING: case 1 has two primary triggers\nWARNING: unknown issue")
        self.assertEqual([w['blocking'] for w in warnings], [False, True, True])
