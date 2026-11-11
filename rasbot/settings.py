"""Local engine configuration; Windows secrets are protected with user DPAPI."""
import base64
import ctypes
import os
import threading
from .opencode_service import ACTIVE


def protect(value, decrypt=False):
    if not value:
        return ''
    if os.name != 'nt':
        raise ValueError('本机引擎凭据管理目前仅支持 Windows。')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_char))]
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    output = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError('本机凭据加密/解密失败，请重新配置。')
    try:
        result = ctypes.string_at(output.data, output.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class Settings:
    def __init__(self, store):
        self.store = store
        self.disconnected = store.root / 'engine-disconnected'
        self.lock = threading.RLock()
        from .managed_engine import ManagedEngine
        self.managed = ManagedEngine(store.root, protect)

    def start(self, engine):
        with self.lock:
            client = self.client() if self.disconnected.exists() else self.managed.start()
            engine.client = self.guard(client)

    def guard(self, client):
        settings = self
        class Connection:
            def __getattr__(self, name):
                return getattr(client, name)

            def request(self, *args, **kwargs):
                with settings.lock:
                    if settings.disconnected.exists():
                        raise RuntimeError('OpenCode 已手动断开，请在平台设置中点击连接。')
                    return client.request(*args, **kwargs)
        return Connection()

    def ensure_idle(self):
        with self.store.connect() as conn:
            states = [r[0] for r in conn.execute('SELECT state FROM tasks')]
        if any(s in (*ACTIVE, 'validating', 'agent_running') for s in states):
            raise ValueError('有任务正在执行，请先停止或同步任务，再修改连接。')

    def connection(self, engine, enabled):
        with self.lock:
            if enabled:
                client = self.managed.start()
                info = client.request('GET', '/api/info')
                if not isinstance(info, dict) or not info.get('version'):
                    raise ValueError('服务未返回 OpenCode 版本信息')
                self.disconnected.unlink(missing_ok=True)
                engine.client = self.guard(client)
            else:
                self.ensure_idle()
                self.disconnected.touch()
                engine.client = self.guard(self.client())
            return {'enabled': enabled, 'connected': enabled}

    def client(self):
        return self.managed.client()

    def public(self):
        from .preferences import default_model
        return {'configured': True, 'enabled': not self.disconnected.exists(),
                'mode': 'managed', 'model': default_model(self.store)}
