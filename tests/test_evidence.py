import hashlib
import tempfile
import unittest
from pathlib import Path
from rasbot.evidence import comparison, generation_integrity
from rasbot.analysis import analyze_task
from rasbot.agents import PrecisionAgent


def cases(*results):
    return [{'id': i, 'result': r} for i, r in enumerate(results)]


class ComparisonTests(unittest.TestCase):
    def test_runtime_errors_are_not_accuracy_failures(self):
        r = comparison(cases('execution_error', 'execution_error'), 2, True)
        self.assertEqual(r['status'], 'BLOCKED')
        self.assertIsNone(r['false_rate_among_compared'])

    def test_pass_with_coverage_gaps_is_explicit(self):
        r = comparison(cases('accuracy_pass', 'execution_error'), 2, True)
        self.assertEqual(r['status'], 'PASS'); self.assertEqual(r['coverage_gaps'], 1)

    def test_false_is_not_a_confirmed_defect(self):
        r = comparison(cases('accuracy_false', 'execution_error'), 2, True)
        self.assertEqual(r['status'], 'FAULT')
        self.assertEqual(r['false_rate_among_compared'], 1)
        self.assertIsNone(r['root_cause_confirmed'])
        self.assertFalse(r['promotion_eligible'])

    def test_unknown_and_untrusted_preserve_observations(self):
        for trusted in (None, False):
            r = comparison(cases('accuracy_false'), 1, trusted)
            self.assertEqual(r['status'], 'BLOCKED')
            self.assertEqual(r['observed_status'], 'FAULT')

    def test_duplicate_ids_and_incomplete_cases_are_invalid(self):
        pair = cases('accuracy_pass', 'accuracy_false'); pair[1]['id'] = 0
        self.assertEqual(comparison(pair, 2, True)['reason'], 'duplicate_case_id')
        self.assertEqual(comparison([], 1, True)['reason'], 'case_count_mismatch')

    def test_unknown_classification_cannot_count_as_pass(self):
        self.assertEqual(comparison(cases('SUCCESS'), 1, True)['status'], 'invalid')
        self.assertEqual(comparison(cases('accuracy_unavailable'), 1, True)['status'], 'BLOCKED')


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.suite = self.root / '01_generate/submission/test_suite.json'
        self.atk = self.root / '02_atk_run/atk_input/test_suite.atk.json'
        for path in (self.suite, self.atk):
            path.parent.mkdir(parents=True); path.write_bytes(b'[]')
        digest = hashlib.sha256(b'[]').hexdigest()
        self.task = {'id': 'test', 'domain': 'precision', 'state': 'generated', 'events': [],
                     'result': {'workspace': str(self.root), 'validation': {
                         'passed': True, 'suite_sha256': digest, 'atk_input_sha256': digest}}}

    def test_hashes_verified_for_current_task_only(self):
        self.assertTrue(generation_integrity(self.task['result'])['verified'])

    def test_tampering_invalidates_comparison_even_after_generation_pass(self):
        self.suite.write_bytes(b'[1]')
        verdict = PrecisionAgent(self.root).evaluate(self.task)
        self.assertFalse(verdict['passed']); self.assertFalse(verdict['comparable'])
        self.assertEqual(verdict['artifact_integrity']['status'], 'invalid')

    def test_missing_file_is_not_zero_failures(self):
        self.atk.unlink()
        self.assertEqual(generation_integrity(self.task['result'])['status'], 'invalid')

    def test_no_digest_is_not_verified(self):
        self.assertEqual(generation_integrity({'validation': {'passed': True}})['status'], 'not_recorded')

    def test_report_claims_do_not_create_hardware_success(self):
        self.task['result']['validation']['hardware_executed'] = True
        r = analyze_task(self.task)
        self.assertEqual(r['evidence']['hardware_status'], 'not_evaluated')
        self.assertIsNone(r['evidence']['root_cause_confirmed'])
