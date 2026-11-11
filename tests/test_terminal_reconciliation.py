import unittest
from unittest.mock import patch
import test_evolution


class ReconciliationTests(unittest.TestCase):
    setUp = test_evolution.EvolutionTests.setUp
    create = test_evolution.EvolutionTests.create
    proposal = test_evolution.EvolutionTests.proposal

    def test_closed_round_collects_success_stops_active_and_cancels_queued(self):
        run = self.proposal(self.create())
        ids = [t['task_id'] for t in run['trials']]
        for identity in ids[:2]:
            self.runtime.store.transition(identity, 'queued', 'engine_running', {})
        run['state'] = 'inconclusive'
        self.evo.save(run)
        def sync(identity):
            if identity == ids[0]:
                self.runtime.store.transition(identity, 'engine_running', 'generated', {'validation': {'passed': True}})
            return self.runtime.store.get(identity)
        def cancel(identity):
            task = self.runtime.store.get(identity)
            self.runtime.store.transition(identity, task['state'], 'cancelled', {})
            return self.runtime.store.get(identity)
        with patch.object(self.evo.engine, 'sync', side_effect=sync), patch.object(self.evo.engine, 'cancel', side_effect=cancel) as stop:
            result = self.evo.tick(run['id'])
            stop.assert_called_once_with(ids[1])
        self.assertEqual(result['state'], 'inconclusive')
        self.assertEqual([self.runtime.store.get(i)['state'] for i in ids], ['generated', 'cancelled', 'cancelled', 'cancelled'])
