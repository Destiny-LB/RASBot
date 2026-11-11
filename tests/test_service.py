from unittest.mock import patch
import unittest
import test_agent_runtime
from rasbot.opencode_service import Service


class FakeClient:
    url = 'http://127.0.0.1:4098'
    def __init__(self):
        self.calls = []
        self.outcome = None
        self.permissions = []
        self.fail_prompt = False
    def session_path(self, sid):
        return '/api/session/' + sid
    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == '/api/info': return {'version': 'test-v2'}
        if path.endswith('/prompt'):
            if self.fail_prompt: raise RuntimeError('response lost')
            return {'data': {'id': 'message'}}
        if path.endswith('/context'): return {'data': [{'type': 'idle', 'outcome': self.outcome}] if self.outcome else []}
        if path.endswith('/permission'): return {'data': self.permissions}
        return {'data': {'id': 'session-test', **({'outcome': self.outcome} if self.outcome else {})}}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        test_agent_runtime.AgentTests.setUp(self)
        self.client = FakeClient()
        self.service = Service(self.runtime, self.client)

    def test_start_persists_session_and_prevents_duplicate(self):
        task = self.service.start(self.task)
        self.assertEqual(task['state'], 'engine_running')
        self.assertEqual(task['result']['session_id'], 'session-test')
        with self.assertRaises(ValueError): self.service.start(self.task)
        self.assertEqual(sum(p.endswith('/prompt') for _,p,_ in self.client.calls), 1)

    def test_permission_is_distinct_from_failure(self):
        self.service.start(self.task)
        self.client.permissions = [{'id': 'permission-test'}]
        self.assertEqual(self.service.sync(self.task)['state'], 'waiting_permission')

    def test_model_selected_before_prompt_and_not_changed_on_sync(self):
        import json
        model = {'providerID': 'test', 'id': 'model-a'}
        (self.runtime.store.root / 'preferences.json').write_text(json.dumps({'model': model}))
        task = self.service.start(self.task)
        paths = [p for _, p, _ in self.client.calls]
        self.assertLess(paths.index('/api/session/session-test/model'), paths.index('/api/session/session-test/prompt'))
        self.assertEqual(task['result']['selected_model'], model)
        (self.runtime.store.root / 'preferences.json').write_text('{"model":null}')
        self.service.sync(self.task)
        self.assertEqual(sum(p.endswith('/model') for _,p,_ in self.client.calls), 1)

    def test_model_failure_does_not_submit_prompt(self):
        (self.runtime.store.root / 'preferences.json').write_text('{"model":{"providerID":"test","id":"missing"}}')
        original = self.client.request
        def request(method, path, body=None):
            if path.endswith('/model'): raise RuntimeError('Model unavailable')
            return original(method, path, body)
        self.client.request = request
        task = self.service.start(self.task)
        self.assertEqual(task['state'], 'engine_unknown')
        self.assertEqual(task['result']['session_id'], 'session-test')
        self.assertFalse(any(p.endswith('/prompt') for _,p,_ in self.client.calls))

    def test_stale_session_outcome_does_not_end_active_turn(self):
        self.service.start(self.task)
        original = self.client.request
        def request(method, path, body=None):
            if path.endswith('/context'):
                return {'data': [{'type': 'idle', 'outcome': 'interrupted'}, {'type': 'assistant', 'content': []}]}
            return original(method, path, body)
        self.client.request = request
        self.client.outcome = 'interrupted'
        self.assertEqual(self.service.sync(self.task)['state'], 'engine_running')

    def test_repair_uses_existing_session_and_is_bounded(self):
        task = self.service.start(self.task)
        result = task['result']
        result['validation'] = {'passed': False, 'reason': 'Rule count does not match max_cases'}
        self.runtime.store.transition(self.task, 'engine_running', 'validation_failed', result)
        self.service.repair_generation(self.task)
        repaired = self.runtime.store.get(self.task)
        self.assertEqual(repaired['result']['session_id'], 'session-test')
        self.assertEqual(repaired['result']['repair_attempts'], 1)
        self.assertIn('max_cases', self.client.calls[-1][2]['text'])
        result = repaired['result']; result['repair_attempts'] = 3
        self.runtime.store.transition(self.task, 'engine_running', 'validation_failed', result)
        with self.assertRaises(ValueError): self.service.repair_generation(self.task)

    def test_uncertain_submission_preserves_session(self):
        self.client.fail_prompt = True
        task = self.service.start(self.task)
        self.assertEqual(task['state'], 'engine_unknown')
        self.assertEqual(task['result']['session_id'], 'session-test')
        self.service.sync(self.task)
        self.assertEqual(sum(p.endswith('/prompt') for _,p,_ in self.client.calls), 1)

    @patch('rasbot.opencode_service.validate', return_value={'passed': False})
    def test_successful_agent_still_needs_artifact_validation(self, _):
        self.service.start(self.task)
        self.client.outcome = 'succeeded'
        self.assertEqual(self.service.sync(self.task)['state'], 'validation_failed')
