"""Transactional state and immutable version registry; standard-library only."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'rasbot.db'
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, parent TEXT,
                body TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, domain TEXT NOT NULL,
                slug TEXT NOT NULL, version TEXT NOT NULL REFERENCES versions(id),
                state TEXT NOT NULL, result TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL REFERENCES tasks(id), kind TEXT NOT NULL,
                payload TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY, candidate TEXT,
                baseline TEXT, state TEXT, protocol TEXT, created TEXT);
            ''')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def version(self, body, parent=None):
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True)
        identity = hashlib.sha256((str(parent) + raw).encode()).hexdigest()[:20]
        with self.connect() as c:
            if parent and not c.execute('SELECT 1 FROM versions WHERE id=?', (parent,)).fetchone():
                raise ValueError('Unknown parent version')
            c.execute('INSERT OR IGNORE INTO versions VALUES(?,?,?,?)', (identity, parent, raw, now()))
        return identity

    def create(self, domain, slug, version):
        if not isinstance(domain, str) or not domain:
            raise ValueError('Agent identifier is required')
        identity = uuid.uuid4().hex
        with self.connect() as c:
            c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)',
                      (identity, domain, slug, version, 'queued', '{}', now()))
            self.event(c, identity, 'task.created', {'version': version})
        return identity

    def event(self, c, task, kind, payload):
        c.execute('INSERT INTO events(task_id,kind,payload,created) VALUES(?,?,?,?)',
                  (task, kind, json.dumps(payload, ensure_ascii=False), now()))

    def transition(self, task, expected, state, result):
        with self.connect() as c:
            cur = c.execute('UPDATE tasks SET state=?,result=? WHERE id=? AND state=?',
                            (state, json.dumps(result, ensure_ascii=False), task, expected))
            if cur.rowcount != 1:
                return False
            self.event(c, task, 'state.' + state, result)
        return True

    def get(self, task):
        with self.connect() as c:
            row = c.execute('SELECT * FROM tasks WHERE id=?', (task,)).fetchone()
            if not row:
                raise ValueError('Unknown task')
            result = dict(row)
            result['result'] = json.loads(result['result'])
            result['events'] = [dict(r) for r in c.execute('SELECT * FROM events WHERE task_id=? ORDER BY seq', (task,))]
            for event in result['events']:
                event['payload'] = json.loads(event['payload'])
            return result

    def snapshot(self):
        with self.connect() as c:
            return {name: [dict(r) for r in c.execute('SELECT * FROM ' + name + ' ORDER BY created DESC')]
                    for name in ('tasks', 'versions', 'evaluations')}

    def evaluation(self, candidate, baseline, protocol):
        if candidate == baseline or not protocol.strip():
            raise ValueError('Specify distinct versions and an evaluation protocol')
        identity = uuid.uuid4().hex
        with self.connect() as c:
            for version in (candidate, baseline):
                if not c.execute('SELECT 1 FROM versions WHERE id=?', (version,)).fetchone():
                    raise ValueError('Unknown version')
            c.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?)',
                      (identity, candidate, baseline, 'planned', protocol, now()))
        return identity
