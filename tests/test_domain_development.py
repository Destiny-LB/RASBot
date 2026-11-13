import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
from rasbot.development import prepare
from rasbot.precision_development import observe
from rasbot.experience import features, diagnostic
from rasbot.execution_package import hashes


class DomainDevelopmentTests(unittest.TestCase):
    def test_other_domain_prepares_without_precision_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = SimpleNamespace(prepare_development=Mock(return_value={'root': tmp, 'status': 'ready'}), bind_development_parent=Mock())
            evo = SimpleNamespace(runtime=SimpleNamespace(registry=SimpleNamespace(get=lambda _: adapter)),
                                  store=SimpleNamespace(get=lambda _: {'id': 'diagnosis'}, connect=MagicMock()),
                                  save=lambda run, *args: run)
            evo.store.connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = ['{"execution_files": {}}']
            run = {'baseline': 'base', 'root': tmp, 'agent_id': 'other', 'evidence': [{'task_id': 'diagnosis'}]}
            self.assertEqual(prepare(evo, run, {})['state'], 'development_ready')
            adapter.prepare_development.assert_called_once()
            self.assertFalse((Path(tmp)/'development/execution-package').exists())

    def test_actual_changes_override_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'scripts').mkdir()
            (root/'scripts/helper.py').write_text('pass')
            dev = {'package': tmp, 'parent_file_hashes': hashes({'scripts/helper.py': 'pass'}), 'initial_file_hashes': hashes({'scripts/helper.py': 'pass'})}
            (root/'scripts/helper.py').write_text('print(1)')
            dev['source_changes'] = observe(dev)
            run = {'development': dev, 'proposal': {'file_changes': {}}, 'state': 'failed'}
            self.assertEqual(features(run)['changed_component'], 'scripts')
            self.assertEqual(diagnostic(run)['source_changes']['paths'], ['scripts/helper.py'])

    def test_diagnostic_filters_absolute_paths_and_logs(self):
        run = {'development': {'check': {'passed': False, 'validation': {
            'reason': 'Protected task assets changed', 'asset_changes': {
                'modified': ['02_atk_run/atk_run_config.json', 'C:/secret', '../private']},
            'log': 'private output'}}}}
        result = diagnostic(run)
        self.assertEqual(result['asset_changes']['modified'], ['02_atk_run/atk_run_config.json'])
        self.assertNotIn('log', result)
        self.assertEqual(features({'development': {}, 'state': 'failed'})['changed_component'], 'unknown')
