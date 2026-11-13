import tempfile
import unittest
from pathlib import Path
from rasbot.precision_package import materialize, materialize_references, references_intact
from rasbot.development import collect


class ReferenceTests(unittest.TestCase):
    def test_script_relative_reference_exists_and_is_not_candidate_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); repo = root / 'repo'; (repo / 'docs').mkdir(parents=True)
            (repo / 'docs/trigger_library.md').write_text('fixed library', encoding='utf-8')
            package = root / 'package'
            sources = {'scripts/verify_trigger_coverage.py': 'from pathlib import Path\nREFERENCE=Path(__file__).resolve().parents[1]/"docs/trigger_library.md"\n'}
            materialize(package, sources)
            refs = materialize_references(package, repo)
            self.assertTrue(references_intact(package, refs))
            self.assertEqual(collect(package, list(sources), refs), sources)
            (package / 'docs/trigger_library.md').write_text('changed', encoding='utf-8')
            self.assertFalse(references_intact(package, refs))
            with self.assertRaises(ValueError): collect(package, list(sources), refs)

    def test_dependency_missing_is_preparation_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); package = root / 'package'
            materialize(package, {'scripts/verify_trigger_coverage.py': 'pass'})
            with self.assertRaises(ValueError): materialize_references(package, root / 'missing-repo')
