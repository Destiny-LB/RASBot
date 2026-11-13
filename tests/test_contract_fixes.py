import tempfile
import unittest
from pathlib import Path
from rasbot.task_contract import render
from rasbot.precision_package import materialize, materialize_references, references_intact
from rasbot.development import collect
from rasbot.agent_runtime import asset_changes
from rasbot.evolution import trajectory


class ContractFixTests(unittest.TestCase):
    def test_both_modes_remove_conflicting_paths(self):
        old = '$GENERATE_DIR/interfaces/constraints.md $REPO_ROOT/scripts/verify_schema.py'
        for dev in (False, True):
            text = render('repo', 'package', 'workspace', 'sample', old, old, old, dev)
            self.assertNotIn('interfaces/constraints.md', text)
            self.assertNotIn('$REPO_ROOT/scripts/', text)
            self.assertIn('report/constraints.md', text)
            self.assertIn('Do NOT execute Step 2/3', text)

    def test_runnable_reference_is_fixed_and_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); repo = root/'repo'; package = root/'package'
            original = repo/'tasks/sample/02_atk_run/atk_runnable/executor.py'
            original.parent.mkdir(parents=True); original.write_text('original')
            files = {'scripts/helper.py': 'pass'}
            materialize(package, files)
            refs = materialize_references(package, repo, 'sample')
            self.assertTrue(references_intact(package, refs))
            self.assertEqual(collect(package, list(files), refs), files)
            copied = package/original.relative_to(repo)
            self.assertEqual(copied.read_bytes(), original.read_bytes())
            copied.write_text('tampered')
            self.assertFalse(references_intact(package, refs))
            with self.assertRaises(ValueError): collect(package, list(files), refs)

    def test_skill_on_disk_is_adapted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'package'
            materialize(root, {'openskill/01_generate_test_rules.md': '$GENERATE_DIR/interfaces/constraints.md'})
            self.assertEqual((root/'openskill/01_generate_test_rules.md').read_text(), '$GENERATE_DIR/report/constraints.md')

    def test_asset_diff_survives_trajectory(self):
        changes = asset_changes({'modified': 'a', 'deleted': 'b'}, {'modified': 'c', 'added': 'd'})
        self.assertEqual(changes, {'added': ['added'], 'modified': ['modified'], 'deleted': ['deleted']})
        task = {'id': 'x', 'slug': 'sample', 'state': 'validation_failed', 'events': [],
                'result': {'validation': {'passed': False, 'asset_changes': changes}}}
        self.assertEqual(trajectory(task)['validation']['asset_changes'], changes)
