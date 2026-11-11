import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from rasbot.core import Store
from rasbot.runtime import Runtime
from rasbot.agent_runtime import bundle, command, execute, validate


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.repo = root / 'repo'
        (self.repo / 'tasks/sample').mkdir(parents=True)
        (self.repo / 'prompts').mkdir()
        (self.repo / 'prompts/sample.md').write_text('Original task facts', encoding='utf-8')
        self.runtime = Runtime(Store(root / 'state'), self.repo)
        self.task = self.runtime.create('precision', 'sample')
        run = self.runtime.store.root / 'runs' / self.task
        self.ws = run / 'workspace'
        self.ws.mkdir(parents=True)
        (self.ws / '01_generate/src').mkdir(parents=True)
        (self.ws / '01_generate/src/kernel.cpp').write_text('original')
        snapshot = run / 'skills.json'
        snapshot.write_text(json.dumps({'01_generate_test_rules.md': {'content': 'Pinned skill'}}))
        self.runtime.store.transition(self.task, 'queued', 'prepared', {'workspace': str(self.ws), 'skills_snapshot': str(snapshot)})

    @patch('rasbot.agent_runtime.executable', return_value=['fake-agent'])
    def test_bundle_preserves_full_prompt_and_pins_skill(self, _):
        m = bundle(self.runtime, self.task, 'opencode')
        text = Path(m['instruction']).read_text(encoding='utf-8')
        self.assertIn('Original task facts', text)
        self.assertIn('Pinned skill', text)
        self.assertIn('Do NOT execute Step 2/3', text)
        self.assertEqual(self.runtime.store.get(self.task)['state'], 'prepared')
        self.assertNotIn('--auto', m['command'])

    @patch('rasbot.agent_runtime.executable', return_value=['fake-agent'])
    def test_false_success_cannot_pass_gate(self, _):
        m = bundle(self.runtime, self.task, 'opencode')
        self.assertFalse(validate(self.runtime, m)['passed'])

    @patch('rasbot.agent_runtime.executable', return_value=['fake-agent'])
    def test_protected_asset_change_fails(self, _):
        m = bundle(self.runtime, self.task, 'opencode')
        (self.ws / '01_generate/src/kernel.cpp').write_text('modified')
        self.assertEqual(validate(self.runtime, m)['reason'], 'Protected task assets changed')

    @patch('rasbot.agent_runtime.executable', return_value=['fake-agent'])
    def test_formal_gate_rejects_smoke_suite(self, _):
        (self.ws / '02_atk_run').mkdir()
        (self.ws / '02_atk_run/atk_run_config.json').write_text('{"max_cases": 1000}')
        submission = self.ws / '01_generate/submission'
        submission.mkdir()
        (submission / 'test_suite.json').write_text('[{"id": 0}]')
        m = bundle(self.runtime, self.task, 'opencode')
        result = validate(self.runtime, m)
        self.assertFalse(result['passed'])
        self.assertEqual(result['actual'], 1)
        self.assertEqual(result['expected'], 1000)

    @patch('rasbot.agent_runtime.executable', return_value=['fake-agent'])
    def test_opencode_json_without_permission_bypass(self, _):
        args = command('opencode', Path('task.md'), 'provider/model')
        self.assertIn('json', args)
        self.assertIn('--standalone', args)
        self.assertNotIn('--auto', args)
        with self.assertRaises(ValueError):
            command('unsupported', Path('task.md'))

    @patch('rasbot.agent_runtime.executable', return_value=['fake-agent'])
    def test_different_ids_do_not_hide_duplicate_inputs(self, _):
        (self.ws / '02_atk_run').mkdir()
        (self.ws / '02_atk_run/atk_run_config.json').write_text('{"max_cases": 2}')
        folder = self.ws / '01_generate/submission'; folder.mkdir()
        (folder / 'test_suite.json').write_text(json.dumps([
            {'id': 0, 'inputs': [{'shape': [16]}]}, {'id': 1, 'inputs': [{'shape': [16]}]}]))
        result = validate(self.runtime, bundle(self.runtime, self.task, 'opencode'))
        self.assertEqual(result['reason'], 'Duplicate input specifications')
        self.assertEqual(result['duplicate_count'], 1)

    @patch('rasbot.agent_runtime.subprocess.Popen', side_effect=OSError('launch failure'))
    @patch('rasbot.agent_runtime.executable', return_value=['fake-agent'])
    def test_launch_failure_preserves_workspace_and_blocks(self, *_):
        task = execute(self.runtime, self.task, 'opencode')
        self.assertEqual(task['state'], 'blocked')
        self.assertEqual(task['result']['workspace'], str(self.ws))
