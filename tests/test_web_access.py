import http.client
import re
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from rasbot.__main__ import serve
from rasbot.core import Store
from rasbot.runtime import Runtime


class WebAccessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        runtime = Runtime(Store(temp.name))
        ready = threading.Event()
        servers = []

        def make_server(address, handler):
            server = ThreadingHTTPServer(address, handler)
            servers.append(server)
            ready.set()
            return server

        server_patch = patch('rasbot.__main__.ThreadingHTTPServer', side_effect=make_server)
        engine_patch = patch('rasbot.settings.Settings.start')
        server_patch.start()
        engine_patch.start()
        self.addCleanup(server_patch.stop)
        self.addCleanup(engine_patch.stop)
        thread = threading.Thread(target=serve, args=(runtime, 0), daemon=True)
        thread.start()
        self.assertTrue(ready.wait(10), 'server did not start')
        self.server = servers[0]
        self.port = self.server.server_port
        self.addCleanup(thread.join, 10)
        self.addCleanup(self.server.shutdown)

    def request(self, method='GET', path='/', headers=(), body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        self.addCleanup(conn.close)
        conn.putrequest(method, path, skip_host=True)
        for name, value in headers:
            conn.putheader(name, value)
        if body is not None:
            conn.putheader('Content-Length', str(len(body)))
        conn.endheaders(body)
        response = conn.getresponse()
        return response.status, response.read()

    def test_local_browser_and_token_post(self):
        for name in ('127.0.0.1', 'localhost', 'LOCALHOST'):
            host = f'{name}:{self.port}'
            with self.subTest(host=host):
                status, page = self.request(headers=[('Host', host)])
                self.assertEqual(status, 200)
                token = re.search(rb"'X-RASBot-Token':'([^']+)'", page).group(1).decode()
                status, _ = self.request('POST', '/not-found', [('Host', host),
                    ('Origin', f'http://{host}'), ('X-RASBot-Token', token)], b'{}')
                self.assertEqual(status, 404)
                status, _ = self.request('POST', '/not-found', [('Host', host)], b'{}')
                self.assertEqual(status, 403)
                status, _ = self.request('GET', '/api/state', [('Host', host)])
                self.assertEqual(status, 200)

    def test_rejects_untrusted_hosts_on_all_routes(self):
        invalid = [[], [('Host', 'evil.example:' + str(self.port))],
                   [('Host', '127.0.0.1')], [('Host', 'localhost:1')],
                   [('Host', f'localhost:{self.port}@evil.example')],
                   [('Host', f'localhost:{self.port}'), ('Host', f'localhost:{self.port}')],
                   [('Host', f'localhost:{self.port}, evil.example')]]
        for headers in invalid:
            for method, path in [('GET', '/'), ('GET', '/api/state'), ('POST', '/api/tasks'), ('OPTIONS', '/')]:
                with self.subTest(headers=headers, method=method, path=path):
                    status, data = self.request(method, path, headers, b'{}' if method == 'POST' else None)
                    self.assertEqual(status, 403)
                    self.assertNotIn(b'X-RASBot-Token', data)

    def test_rejects_cross_origin_and_malformed_origins(self):
        host = f'127.0.0.1:{self.port}'
        origins = ['null', 'http://evil.example', f'http://localhost:{self.port}',
                   'https://' + host, 'http://' + host + '/path',
                   'http://' + host + '.evil.example', 'http://' + host + ' http://evil.example', '']
        for origin in origins:
            for method, path in [('GET', '/'), ('GET', '/api/state'), ('POST', '/api/tasks')]:
                with self.subTest(origin=origin, method=method):
                    status, _ = self.request(method, path, [('Host', host), ('Origin', origin)],
                                             b'{}' if method == 'POST' else None)
                    self.assertEqual(status, 403)
        status, _ = self.request(headers=[('Host', host), ('Origin', 'http://' + host),
                                          ('Origin', 'http://' + host)])
        self.assertEqual(status, 403)
        _, page = self.request(headers=[('Host', host)])
        token = re.search(rb"'X-RASBot-Token':'([^']+)'", page).group(1).decode()
        status, _ = self.request('POST', '/not-found', [('Host', host),
            ('Origin', 'http://evil.example'), ('X-RASBot-Token', token)], b'{}')
        self.assertEqual(status, 403)
