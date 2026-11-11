import unittest
from test_service import FakeClient
import test_agent_runtime
from rasbot.opencode_service import Service


class PanelTests(unittest.TestCase):
    def setUp(self):
        test_agent_runtime.AgentTests.setUp(self)
        self.client = FakeClient()
        self.service = Service(self.runtime, self.client)

    def test_open_does_not_start_model_and_reuses_session(self):
        first = self.service.panel_open(self.task)
        second = self.service.panel_open(self.task)
        self.assertEqual(first['session']['id'], second['session']['id'])
        self.assertEqual(first['state'], 'panel_ready')
        self.assertEqual(sum(m == 'POST' and p == '/api/session' for m,p,_ in self.client.calls), 1)
        self.assertFalse(any(p.endswith('/prompt') for _,p,_ in self.client.calls))

    def test_first_message_includes_contract_and_is_audited(self):
        self.service.panel_open(self.task)
        self.service.panel_send(self.task, 'Generate cases')
        sent = [b for _,p,b in self.client.calls if p.endswith('/prompt')][0]['text']
        self.assertIn('Original task facts', sent)
        self.assertIn('Generate cases', sent)
        self.assertTrue(any(e['kind']=='panel.user_message' for e in self.runtime.store.get(self.task)['events']))
        with self.assertRaises(ValueError): self.service.panel_send(self.task,'duplicate')

    def test_permission_must_belong_to_task_and_not_allow_always(self):
        self.service.panel_open(self.task)
        with self.assertRaises(ValueError): self.service.panel_permission(self.task,'foreign','once')
        with self.assertRaises(ValueError): self.service.panel_permission(self.task,'permission','always')
        self.client.permissions = [{'id': 'permission'}]
        self.service.panel_permission(self.task,'permission','reject')
        self.assertEqual(self.client.calls[-1][2], {'reply': 'reject'})
