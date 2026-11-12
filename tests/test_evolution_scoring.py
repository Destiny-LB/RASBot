import unittest
from rasbot.evolution_scoring import decide, elapsed
import test_evolution

POLICY = {'efficiency_max_ratio': .8, 'efficiency_repetitions': 2}


def trials(repeats=1):
    return [{'slug': slug, 'replicate': rep, 'role': role, 'passed': True,
             'comparable': True, 'duration_seconds': 100 if role == 'baseline' else 70}
            for rep in range(repeats) for slug in ('a', 'b') for role in ('baseline', 'candidate')]


class ScoringTests(unittest.TestCase):
    def test_one_fast_run_needs_confirmation(self):
        self.assertEqual(decide(trials(), ['a', 'b'], POLICY)['state'], 'confirming')

    def test_repeated_gain_promotes_efficiency_only(self):
        self.assertEqual(decide(trials(2), ['a', 'b'], POLICY)['basis'], 'generation_efficiency')

    def test_single_task_regression_prevents_promotion(self):
        data = trials(2); data[-1]['duration_seconds'] = 99
        self.assertEqual(decide(data, ['a', 'b'], POLICY)['state'], 'rejected')

    def test_missing_nan_zero_time_cannot_promote(self):
        for value in (None, float('nan'), 0, -1, True):
            data = trials(2); data[-1]['duration_seconds'] = value
            self.assertEqual(decide(data, ['a', 'b'], POLICY)['state'], 'rejected')

    def test_incomplete_pairs_cannot_promote(self):
        self.assertEqual(decide(trials(2)[:-1], ['a', 'b'], POLICY)['state'], 'inconclusive')

    def test_integrity_and_compliance_take_priority(self):
        data = trials(2); data[-1]['manual_intervention'] = True
        self.assertEqual(decide(data, ['a', 'b'], POLICY)['state'], 'inconclusive')
        data = trials(2); data[-1]['passed'] = False
        self.assertEqual(decide(data, ['a', 'b'], POLICY)['state'], 'rejected')

    def test_duration_comes_from_terminal_event(self):
        task = {'state': 'generated', 'events': [{'kind': 'state.generated', 'created': '2026-11-12T00:00:20+00:00'}]}
        self.assertEqual(elapsed(task, '2026-11-12T00:00:00+00:00'), 20)
        self.assertIsNone(elapsed(task, None))


class ConfirmationTests(unittest.TestCase):
    setUp = test_evolution.EvolutionTests.setUp

    def test_confirmation_is_persisted_reversed_and_bounded(self):
        run = test_evolution.EvolutionTests.proposal(self, self.evo.create([self.task], ['sample', 'holdout'], self.model))
        for trial in run['trials']:
            trial.update(passed=True, comparable=True, terminal_state='generated', duration_seconds=100 if trial['role']=='baseline' else 70)
        self.evo.save(run)
        run = self.evo.tick(run['id'])
        self.assertEqual(run['state'], 'evaluating')
        self.assertEqual(len(run['trials']), 8)
        self.assertEqual([t['role'] for t in run['trials'][4:]], ['candidate', 'baseline']*2)
        for trial in run['trials'][4:]:
            trial.update(passed=True, comparable=True, terminal_state='generated', duration_seconds=100 if trial['role']=='baseline' else 70)
        self.evo.save(run)
        from rasbot.evolution import Evolution
        restarted = Evolution(self.runtime, self.evo.engine)
        run = restarted.tick(run['id'])
        self.assertEqual(run['state'], 'promoted')
        self.assertEqual(run['decision']['basis'], 'generation_efficiency')
        self.assertEqual(run['scores']['tasks_per_arm'], 4)
        self.assertEqual(len(run['trials']), 8)
        self.evo.rollback(run['id'])
        self.assertEqual(self.runtime.adopted(), run['baseline'])
