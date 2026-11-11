import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from rasbot.core import Store
from rasbot.settings import Settings, protect


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'RASBOT_OPENCODE_MODE': 'external', 'RASBOT_OPENCODE_URL': 'http://localhost:4098'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.settings = Settings(Store(self.temp.name))
        from rasbot.opencode_service import Client
        client = Client('http://127.0.0.1:4108', '')
        for method in ('client', 'start'):
            mocked = patch('rasbot.managed_engine.ManagedEngine.' + method, return_value=client)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.engine = SimpleNamespace(client=client)

    def test_disconnect_blocks_calls_and_survives_restart(self):
        self.settings.connection(self.engine, False)
        with patch('rasbot.opencode_service.Client.request') as request:
            with self.assertRaises(RuntimeError):
                self.engine.client.request('POST', '/api/session')
            restarted = Settings(self.settings.store)
            self.assertFalse(restarted.public()['enabled'])
            with self.assertRaises(RuntimeError):
                restarted.guard(restarted.client()).request('GET', '/api/info')
            request.assert_not_called()
        with patch('rasbot.opencode_service.Client.request', return_value={'version': '2.2.5'}):
            self.settings.connection(self.engine, True)
            self.assertTrue(self.settings.public()['enabled'])
            self.assertEqual(self.engine.client.request('GET', '/api/info')['version'], '2.2.5')

    def test_failed_reconnect_keeps_disconnected(self):
        self.settings.connection(self.engine, False)
        with patch('rasbot.opencode_service.Client.request', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                self.settings.connection(self.engine, True)
        self.assertFalse(self.settings.public()['enabled'])

    def test_active_task_prevents_disconnect(self):
        version = self.settings.store.version({'name': 'test'})
        task = self.settings.store.create('demo', 'test', version)
        self.settings.store.transition(task, 'queued', 'engine_running', {})
        with self.assertRaises(ValueError):
            self.settings.connection(self.engine, False)
        self.assertTrue(self.settings.public()['enabled'])

    def test_external_config_and_environment_are_ignored(self):
        (self.settings.store.root / 'engine-settings.json').write_text('{"mode":"external","url":"https://example.com"}')
        with patch.dict(os.environ, {'RASBOT_OPENCODE_MODE': 'external', 'RASBOT_OPENCODE_URL': 'https://example.com'}):
            self.assertEqual(self.settings.public()['mode'], 'managed')
            self.assertEqual(self.settings.client().url, 'http://127.0.0.1:4108')
            self.assertFalse(hasattr(self.settings, 'update'))

    def test_disconnected_start_does_not_launch(self):
        self.settings.disconnected.touch()
        self.settings.start(self.engine)
        self.settings.managed.start.assert_not_called()

    def test_start_launches_managed_engine(self):
        self.settings.start(self.engine)
        self.settings.managed.start.assert_called_once()
