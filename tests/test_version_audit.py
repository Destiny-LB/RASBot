import tempfile
import unittest
from rasbot.core import Store
from rasbot.version_audit import audit_versions


class VersionAuditTests(unittest.TestCase):
    def test_lineage_diff_and_adoption_are_independent_of_historical_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            baseline = store.version({'agent_instructions': 'Read docs\nGenerate'})
            candidate = store.version({'agent_instructions': 'Read docs\nValidate'}, baseline)
            runs = [{'id': 'run', 'baseline': baseline, 'candidate': candidate,
                     'state': 'promoted', 'evaluator_id': 'fixed', 'created': 'today',
                     'scores': {'baseline_passes': 1, 'candidate_passes': 2, 'tasks_per_arm': 2},
                     'trials': [{'role': 'candidate', 'task_id': 'test'}]}]
            rows = {v['id']: v for v in audit_versions(store, baseline, runs)}
            self.assertTrue(rows[baseline]['adopted'])
            self.assertFalse(rows[candidate]['adopted'])
            self.assertEqual(rows[candidate]['parent'], baseline)
            self.assertIn('-Generate', rows[candidate]['instruction_diff'])
            self.assertIn('+Validate', rows[candidate]['instruction_diff'])
            self.assertEqual(rows[candidate]['evaluations'][0]['state'], 'promoted')
            self.assertEqual(rows[baseline]['evaluations'][0]['roles'], ['baseline'])
            self.assertEqual(rows[baseline]['evaluations'][0]['trials'], [])
