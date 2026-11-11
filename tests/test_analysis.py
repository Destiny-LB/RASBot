import copy
import unittest
from rasbot.analysis import traceability, diagnose, analyze_task


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.suite = [{'id': 0, 'inputs': [{'shape': [17]}], 'generate_intent': 'tail boundary',
                       'trigger_library_ref': ['TRIGGER-1.2: tail']}]
        self.ledger = {'triggers': [{'id': '1.2', 'status': 'applicable', 'actual_case_ids': [0]}]}

    def test_valid_fixture(self):
        self.assertTrue(traceability(self.suite, self.ledger)['consistent'])

    def test_code_trigger_short_key(self):
        self.suite[0]['trigger_library_ref'].append('CODE-tail: source branch')
        self.ledger['code_triggers'] = {'tail': {'reason': 'tail branch'}}
        self.assertTrue(traceability(self.suite, self.ledger)['consistent'])

    def test_not_testable_is_valid(self):
        self.ledger['triggers'].append({'id': '2', 'status': 'not_testable', 'actual_case_ids': []})
        self.assertTrue(traceability(self.suite, self.ledger)['consistent'])

    def test_corruption_calibration(self):
        mutations = [
            ('dangling_case', lambda s, l: l['triggers'][0]['actual_case_ids'].append(99)),
            ('missing_reverse_reference', lambda s, l: s[0].update(trigger_library_ref=['TRIGGER-2: other'])),
            ('missing_ledger_link', lambda s, l: l['triggers'][0].update(actual_case_ids=[])),
            ('duplicate_case_id', lambda s, l: s.append(copy.deepcopy(s[0]))),
            ('missing_intent', lambda s, l: s[0].update(generate_intent='')),
            ('skipped_with_cases', lambda s, l: l['triggers'][0].update(status='skipped')),
            ('unassessed_trigger', lambda s, l: l['triggers'][0].update(status='unassessed')),
            ('malformed_reference', lambda s, l: s[0].update(trigger_library_ref=['1.2'])),
        ]
        for expected, mutate in mutations:
            with self.subTest(expected=expected):
                suite, ledger = copy.deepcopy(self.suite), copy.deepcopy(self.ledger)
                mutate(suite, ledger)
                result = traceability(suite, ledger)
                self.assertFalse(result['consistent'])
                self.assertIn(expected, [i['code'] for i in result['issues']])

    def test_semantic_limitation_is_explicit(self):
        self.suite[0]['inputs'] = [{'shape': [16]}]
        # A truthful boundary claim requires a domain oracle, not string matching.
        self.assertTrue(traceability(self.suite, self.ledger)['consistent'])
        self.assertIn('not numerical', traceability(self.suite, self.ledger)['scope'])

    def test_malformed_artifacts(self):
        self.assertEqual(traceability({}, [])['status'], 'invalid')
        self.ledger['triggers'][0]['actual_case_ids'] = {}
        self.assertFalse(traceability(self.suite, self.ledger)['consistent'])

    def test_durations_and_missing_evidence(self):
        task = {'id': 'x', 'domain': 'demo', 'state': 'engine_failed', 'result': {}, 'events': [
            {'kind': 'state.engine_running', 'created': '2026-01-01T00:00:00+00:00'},
            {'kind': 'state.engine_failed', 'created': '2026-01-01T00:00:12+00:00'}]}
        result = diagnose(task)
        self.assertEqual(result['phase_seconds']['engine_running'], 12)
        self.assertEqual(result['context_status'], 'unavailable')
        self.assertEqual(result['category'], 'execution_failure')
        self.assertEqual(analyze_task(task)['quality']['status'], 'unsupported')
