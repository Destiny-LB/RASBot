import tempfile
import unittest
from unittest.mock import Mock
from rasbot.core import Store
from rasbot.preferences import models, save_model, default_model


class PreferencesTests(unittest.TestCase):
    def test_catalog_redacts_settings_and_rejects_invalid_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            client = Mock()
            client.request.return_value = {'data': [
                {'id': 'a', 'providerID': 'p', 'name': 'A', 'enabled': True,
                 'settings': {'apiKey': 'must-not-leak'}},
                {'id': 'disabled', 'providerID': 'p', 'enabled': False}]}
            self.assertEqual(models(client), [{'id': 'a', 'providerID': 'p', 'name': 'A'}])
            choice = {'id': 'a', 'providerID': 'p'}
            save_model(store, client, choice)
            self.assertEqual(default_model(Store(directory)), choice)
            with self.assertRaises(ValueError):
                save_model(store, client, {'id': 'missing', 'providerID': 'p'})
            self.assertEqual(default_model(store), choice)
            save_model(store, client, None)
            self.assertIsNone(default_model(store))


class EvolutionModelTests(unittest.TestCase):
    def resolve(self, config, available=True, requested=None):
        from rasbot.preferences import evolution_model
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            client = Mock()
            client.request.side_effect = lambda method, path: config if path == '/api/config' else {'data': [{'id': 'm', 'providerID': 'p', 'enabled': available}]}
            return evolution_model(store, client, requested)

    def test_follow_opencode(self):
        self.assertEqual(self.resolve([{'type': 'document', 'info': {'model': {'providerID': 'p', 'model': 'm'}}}]), {'providerID': 'p', 'id': 'm'})

    def test_explicit_model_has_priority(self):
        self.assertEqual(self.resolve([], requested={'providerID': 'explicit', 'id': 'chosen'}), {'providerID': 'explicit', 'id': 'chosen'})

    def test_missing_or_ambiguous_model_is_not_guessed(self):
        for config in ([], [{'info': {'model': {'providerID': 'p', 'model': name}}} for name in ('a','b')]):
            with self.assertRaisesRegex(ValueError, '无法确定'):
                self.resolve(config)

    def test_unavailable_default_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '不可用'):
            self.resolve([{'info': {'model': {'providerID': 'p', 'model': 'm'}}}], available=False)

    def test_connection_failure_is_chinese(self):
        from rasbot.preferences import evolution_model
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            client=Mock(); client.request.side_effect=RuntimeError('connection failed')
            with self.assertRaisesRegex(ValueError, '无法读取'):
                evolution_model(Store(directory),client)
