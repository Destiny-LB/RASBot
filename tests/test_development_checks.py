import json
import unittest
from pathlib import Path
from unittest.mock import patch
import test_development
from rasbot.development_checks import check


class GateTests(unittest.TestCase):
    setUp = test_development.DevelopmentTests.setUp
    ready = test_development.DevelopmentTests.ready
    idle = test_development.DevelopmentTests.idle

    def test_shell_success_without_artifacts_is_rejected(self):
        run = self.evo.tick(self.ready()['id']); self.idle()
        run = self.evo.tick(run['id'])
        self.assertEqual(run['state'], 'development_ready')
        self.assertNotIn('candidate', run)
        self.assertEqual(len(run['development']['checkpoints']), 1)
        result = run['development']['check']
        self.assertFalse(result['passed'])
        self.assertIn('missing', result['validation']['reason'])
        self.assertEqual(json.loads(Path(result['artifact']).read_text(encoding='utf-8'))['passed'], False)
        self.assertEqual(run['trials'], [])

    def test_checker_failure_is_not_success(self):
        run = self.ready()
        with patch.object(self.runtime.registry.get('precision'), 'validate', side_effect=TimeoutError('test timeout')):
            result = check(self.runtime, 'precision', run['development'], 10)
        self.assertFalse(result['passed'])
        self.assertIn('TimeoutError', result['error'])

    def test_reference_does_not_expose_all_task_paths(self):
        run = self.evo.tick(self.ready()['id'])
        root = Path(run['development']['reference'])
        self.assertFalse((root / 'tasks').exists())
        prompt = (Path(run['development']['root']) / 'instructions.md').read_text(encoding='utf-8')
        self.assertIn('REPO_ROOT=' + str(root), prompt)
