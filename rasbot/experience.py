"""Evidence-backed observations, not model-authored assertions of general laws."""
import json
from .core import now


class Experience:
    def __init__(self, store):
        self.store = store
        with store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS experiences (run_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL)')

    def record(self, run):
        item = {'run_id': run['id'], 'agent_id': run.get('agent_id', 'precision'),
                'campaign_id': run.get('campaign_context', {}).get('campaign_id'),
                'hypothesis': run.get('campaign_context', {}).get('hypothesis'),
                'baseline': run['baseline'], 'candidate': run.get('candidate'),
                'proposal_parent': run.get('proposal_parent', run['baseline']),
                'outcome': run['state'], 'evaluator_id': run['evaluator_id'],
                'scores': run.get('scores'), 'decision': run.get('decision'),
                'diagnosis': run.get('proposal', {}).get('diagnosis', '')[:3000],
                'reason': run.get('reason'),
                'trial_ids': [t['task_id'] for t in run['trials']],
                'development_check': run.get('development', {}).get('check'),
                'scope': run['policy'].get('scope'), 'created': now(),
                'interpretation': 'Observed experiment only; diagnosis is an unverified hypothesis; historical promotion may have been rolled back'}
        with self.store.connect() as c:
            c.execute('INSERT OR IGNORE INTO experiences VALUES(?,?,?,?)',
                      (run['id'], item['agent_id'], json.dumps(item, ensure_ascii=False), item['created']))
        return item

    def list(self, agent_id, limit=20):
        with self.store.connect() as c:
            return [json.loads(r[0]) for r in c.execute(
                'SELECT body FROM experiences WHERE agent_id=? ORDER BY created DESC, run_id DESC LIMIT ?',
                (agent_id, max(1, min(int(limit), 100))))]

    def recall(self, agent_id):
        # Keep task output and evaluation-task identities out of proposal memory.
        return [{k: item.get(k) for k in ('run_id', 'hypothesis', 'outcome', 'scores', 'reason',
                                         'baseline', 'candidate', 'evaluator_id', 'scope', 'interpretation', 'development_check')}
                for item in self.list(agent_id, 6)]
