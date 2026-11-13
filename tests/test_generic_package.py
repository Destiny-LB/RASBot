import tempfile
import unittest
from pathlib import Path
from rasbot import execution_package as generic
from rasbot import precision_package as precision


class GenericPackageTests(unittest.TestCase):
    def test_non_precision_sources_and_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'package'
            files = {'policies/recovery.yaml': 'retry: 2', 'agents/controller.txt': 'execute recovery'}
            source_hashes = generic.materialize(root, files)
            refs = generic.materialize_references(root, {'fixtures/fault.bin': b'fixed'})
            self.assertTrue(generic.intact(root, {**source_hashes, **refs}))
            (root/'fixtures/fault.bin').write_bytes(b'changed')
            self.assertFalse(generic.intact(root, {**source_hashes, **refs}))
            with self.assertRaises(ValueError): precision.validate_files(files)

    def test_generic_layer_does_not_rewrite_domain_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'package'
            content = '$REPO_ROOT/scripts/tool interfaces/constraints.md'
            generic.materialize(root, {'instruction.txt': content})
            self.assertEqual((root/'instruction.txt').read_text(), content)

    def test_path_escape_and_reference_overwrite_rejected(self):
        for name in ('.', '../outside', '/absolute', 'C:/absolute', 'a/../b'):
            with self.assertRaises(ValueError): generic.validate_files({name: 'data'})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'package'
            generic.materialize(root, {'source.txt': 'original'})
            with self.assertRaises(ValueError): generic.materialize_references(root, {'source.txt': b'changed'})
            self.assertEqual((root/'source.txt').read_text(), 'original')
