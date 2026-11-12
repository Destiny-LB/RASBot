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

    def test_frozen_snapshot_is_not_a_source_edit(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            original = store.version({'name': 'baseline'})
            files = {'openskill/01_generate_test_rules.md': 'Original Skill'}
            frozen = store.version({'name': 'frozen-execution-baseline', 'execution_files': files}, original)
            overlay = store.version({'name': 'evolved-execution-package', 'execution_files': files,
                                     'agent_instructions': 'New instructions'}, frozen)
            changed = store.version({'name': 'evolved-execution-package', 'execution_files': {
                'openskill/01_generate_test_rules.md': 'Improved Skill', 'scripts/helper.py': 'print(1)'}}, frozen)
            rows = {v['id']: v for v in audit_versions(store, original, [])}
            self.assertTrue(rows[frozen]['source_snapshot'])
            item = rows[frozen]['file_diffs'][0]
            self.assertEqual(item['status'], 'snapshot')
            self.assertEqual(item['diff'], '')
            self.assertEqual(item['content'], 'Original Skill')
            self.assertFalse(rows[overlay]['source_snapshot'])
            self.assertEqual(rows[overlay]['file_diffs'], [])
            changes = {f['path']: f for f in rows[changed]['file_diffs']}
            self.assertEqual(changes['openskill/01_generate_test_rules.md']['status'], 'modified')
            self.assertIn('+Improved Skill', changes['openskill/01_generate_test_rules.md']['diff'])
            self.assertEqual(changes['scripts/helper.py']['status'], 'added')
