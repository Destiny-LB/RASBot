import unittest
from unittest.mock import patch
from pathlib import Path
import test_development
from rasbot.campaigns import select_next
from rasbot.experience import Experience


class RelayTests(unittest.TestCase):
    setUp = test_development.DevelopmentTests.setUp
    ready = test_development.DevelopmentTests.ready
    idle = test_development.DevelopmentTests.idle

    def test_relay_keeps_budget_and_is_bounded(self):
        run = self.evo.tick(self.ready()['id']); self.idle()
        started = run['development']['started']
        with patch('rasbot.development_checks.check', return_value={'passed': False}):
            for index in range(3):
                run = self.evo.tick(run['id'])
                self.assertEqual(run['development']['started'], started)
                self.assertEqual(run['trials'], [])
                if index < 2:
                    self.assertEqual(run['state'], 'development_ready')
                    run = self.evo.tick(run['id'])
            self.assertEqual(run['state'], 'failed')
            self.assertEqual(len(run['development']['episodes']), 3)

    def test_checkpoint_tampering_blocks_new_session(self):
        run = self.evo.tick(self.ready()['id']); self.idle()
        with patch('rasbot.development_checks.check', return_value={'passed': False}):
            run = self.evo.tick(run['id'])
        (Path(run['development']['package'])/'scripts/helper.py').write_text('print(99)')
        count = len(self.client.calls)
        self.assertEqual(self.evo.tick(run['id'])['state'], 'failed')
        self.assertEqual(len(self.client.calls), count)


class SelectionTests(unittest.TestCase):
    def test_best_compatible_donor_not_most_recent(self):
        def run(i, passes, base='base', comparable=True):
            return dict(id=i, candidate=i, state='rejected', baseline=base,
                        trials=[{'comparable': comparable}], scores={
                        'candidate_passes': passes, 'baseline_passes': 0})
        result = select_next([run('best', 2), run('new', 1), run('wrong', 3, 'old'),
                              run('invalid', 9, comparable=False)], 'base')
        self.assertEqual(result['parent'], 'best')
        self.assertIsNone(select_next([run('wrong', 3, 'old')], 'base')['parent'])

    def test_recall_ranks_relevance_and_filters_evaluator(self):
        memory = object.__new__(Experience)
        rows = [dict(run_id='recent', evaluator_id='e', failure_stage='proposal'),
                dict(run_id='relevant', evaluator_id='e', failure_stage='development',
                     development_check={'secret': 'holdout'}, trial_ids=['private']),
                dict(run_id='incompatible', evaluator_id='other', failure_stage='development')]
        with patch.object(memory, 'list', return_value=rows):
            result = memory.recall('precision', {'evaluator_id':'e', 'failure_stage':'development'})
        self.assertEqual([x['run_id'] for x in result], ['relevant', 'recent'])
        self.assertNotIn('trial_ids', result[0])
        self.assertNotIn('development_check', result[0])
