"""Start a loopback OpenCode service without exposing credentials to the UI."""
import json
import os
import secrets
import socket
import subprocess
import time
from .agent_runtime import executable
from .opencode_service import Client


class ManagedEngine:
    def __init__(self, root, protect):
        self.root = root.resolve()
        self.path = self.root / 'managed-engine.json'
        self.protect = protect
        self.process = None

    def client(self):
        if not self.path.exists():
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            data = {'url': f'http://127.0.0.1:{port}',
                    'secret': self.protect(secrets.token_urlsafe(32))}
            # Exclusive creation avoids overwriting another platform's credentials.
            try:
                with self.path.open('x', encoding='utf-8') as out:
                    json.dump(data, out)
            except FileExistsError:
                pass
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not data['url'].startswith('http://127.0.0.1:'):
            raise ValueError('托管引擎必须监听本机回环地址')
        return Client(data['url'], self.protect(data['secret'], decrypt=True))

    def start(self):
        client = self.client()
        try:
            info = client.request('GET', '/api/info')
            if info.get('version'):
                return client
        except RuntimeError:
            pass
        port = int(client.url.rsplit(':', 1)[1])
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                raise RuntimeError('托管引擎端口被占用或认证不匹配；未接管或关闭其他服务。') from None
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        env = {**os.environ, 'OPENCODE_SERVER_PASSWORD': client.password,
               'OPENCODE_SERVER_USERNAME': 'opencode'}
        self.process = subprocess.Popen(
            executable('opencode') + ['serve', '--hostname', '127.0.0.1', '--port', str(port)],
            cwd=self.root.parent, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags, start_new_session=os.name != 'nt')
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('本机 OpenCode 启动失败，请检查安装和模型配置。')
            try:
                if client.request('GET', '/api/info').get('version'):
                    return client
            except RuntimeError:
                pass
            time.sleep(.25)
        # Do not kill a server on an uncertain readiness timeout.
        raise RuntimeError('OpenCode 尚未就绪，请点击连接重试；不会重复提交任务。')
