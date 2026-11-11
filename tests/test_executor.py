"""Planning shares OpenCode sessions, model configuration, and uncertainty handling."""
import unittest
from unittest.mock import patch
import test_agent_runtime
from test_service import FakeClient
from rasbot.opencode_service import Service

class PlanningTests(unittest.TestCase):
    def setUp(self):
        test_agent_runtime.AgentTests.setUp(self)
        self.client = FakeClient()
        self.service = Service(self.runtime, self.client)

    @patch('rasbot.opencode_service.validate')
    def test_plan_uses_engine_and_keeps_task_executable(self, validate):
        started = self.service.start(self.task, planning=True)
        self.assertEqual(started['state'], 'engine_running')
        sent = [b for _, p, b in self.client.calls if p.endswith('/prompt')][0]
        self.assertIn('Planning only.', sent['text'])
        self.assertNotIn('model', sent)  # inherit OpenCode model
        self.assertEqual(started['result']['agent_manifest']['scope'], 'plan-only')
        request = self.client.request
        def completed(method, path, body=None):
            if path.endswith('/context'):
                return {'data': [{'type': 'assistant', 'model': {'id': 'configured-model'},
                    'content': [{'type': 'text', 'text': 'Experiment plan'}]}, {'type': 'idle', 'outcome': 'succeeded'}]}
            return request(method, path, body)
        self.client.request = completed
        self.client.outcome = 'succeeded'
        done = self.service.sync(self.task)
        self.assertEqual(done['state'], 'prepared')
        self.assertEqual(done['result']['plan']['text'], 'Experiment plan')
        self.assertEqual(done['result']['plan']['models'], [{'id': 'configured-model'}])
        self.assertNotIn('session_id', done['result'])
        validate.assert_not_called()
        self.assertEqual(self.service.start(self.task)['result']['agent_manifest']['scope'], 'generate-only')

    def test_uncertain_plan_is_not_replayed(self):
        self.client.fail_prompt = True
        result = self.service.start(self.task, planning=True)
        self.assertEqual(result['state'], 'engine_unknown')
        self.assertIn('session_id', result['result'])
        with self.assertRaises(ValueError): self.service.start(self.task, planning=True)
        self.assertEqual(sum(p.endswith('/prompt') for _, p, _ in self.client.calls), 1)
