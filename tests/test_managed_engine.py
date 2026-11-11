import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from rasbot.managed_engine import ManagedEngine


class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Reversible stand-in; real DPAPI and real startup are checked separately.
        def codec(value, decrypt=False):
            return value[::-1]
        self.engine = ManagedEngine(Path(self.temp.name), codec)

    def test_persistent_identity_and_no_plaintext_secret(self):
        first = self.engine.client()
        second = self.engine.client()
        self.assertEqual(first.url, second.url)
        self.assertEqual(first.password, second.password)
        self.assertNotIn(first.password, self.engine.path.read_text())
        self.assertTrue(first.url.startswith('http://127.0.0.1:'))

    def test_healthy_server_reused_without_launch(self):
        with patch('rasbot.managed_engine.Client.request', return_value={'version': '2.2.5'}), patch(
                'rasbot.managed_engine.subprocess.Popen') as launch:
            self.engine.start()
            launch.assert_not_called()

    def test_occupied_port_is_not_taken_over(self):
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            sock.listen()
            self.engine.path.write_text(json.dumps({
                'url': f'http://127.0.0.1:{sock.getsockname()[1]}', 'secret': 'test'}))
            with patch('rasbot.managed_engine.Client.request', side_effect=RuntimeError('auth')), patch(
                    'rasbot.managed_engine.subprocess.Popen') as launch:
                with self.assertRaises(RuntimeError):
                    self.engine.start()
                launch.assert_not_called()
