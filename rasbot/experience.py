"""Evidence-backed observations, not model-authored assertions of general laws."""
import json
from .core import now


def features(run):
    dev = run.get('development', {})
    check = dev.get('check') or {}
    stage = ('evaluation' if run.get('scores') or run.get('trials') else
             'development' if dev else 'proposal')
    observed = dev.get('source_changes', {})
    components = observed.get('components', [])
    component = '+'.join(sorted(components)) if components else ('none' if observed.get('status') == 'observed' else 'unknown')
    return {'failure_stage': stage, 'failure_code':
            'artifact_gate' if check.get('passed') is False else run.get('state', 'unknown'),
            'changed_component': component}


def diagnostic(run):
    """Only diagnosis-workspace structural evidence; no formal task output."""
    from pathlib import PurePosixPath
    dev = run.get('development', {})
    verdict = (dev.get('check') or {}).get('validation') or {}
    def paths(values):
        return [p for p in values[:50] if isinstance(p, str) and '\\' not in p
                and ':' not in p and not PurePosixPath(p).is_absolute()
                and '..' not in PurePosixPath(p).parts]
    result = {'stage': features(run)['failure_stage']}
    # Platform-defined messages only; never forward arbitrary evaluator text.
    reasons = {'Protected task assets changed', 'Required Step 1 deliverables missing',
               'Duplicate input specifications', 'Malformed case inputs',
               'Rule count does not match max_cases', 'test_suite.json missing; agent text is not evidence'}
    if verdict.get('reason') in reasons:
        result['reason'] = verdict['reason']
    if isinstance(verdict.get('asset_changes'), dict):
        result['asset_changes'] = {k: paths(verdict['asset_changes'].get(k, [])) for k in ('added', 'modified', 'deleted')}
    if isinstance(verdict.get('missing'), list): result['missing'] = paths(verdict['missing'])
    observed = dev.get('source_changes', {})
    result['source_changes'] = {'status': observed.get('status', 'not_recorded'),
                                'paths': paths(observed.get('paths', [])),
                                'components': observed.get('components', [])}
    for key in ('expected_count', 'actual_count', 'duplicate_count', 'warnings'):
        if type(verdict.get(key)) in (int, bool): result[key] = verdict[key]
    return result



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
        item.update(features(run))
        item['diagnostic'] = diagnostic(run)
        item['evidence_refs'] = {'run_id': run['id']}
        item['applicability'] = {'agent_id': item['agent_id'], 'evaluator_id': item['evaluator_id'], 'scope': item['scope']}
        with self.store.connect() as c:
            c.execute('INSERT OR IGNORE INTO experiences VALUES(?,?,?,?)',
                      (run['id'], item['agent_id'], json.dumps(item, ensure_ascii=False), item['created']))
        return item

    def list(self, agent_id, limit=20):
        with self.store.connect() as c:
            return [json.loads(r[0]) for r in c.execute(
                'SELECT body FROM experiences WHERE agent_id=? ORDER BY created DESC, run_id DESC LIMIT ?',
                (agent_id, max(1, min(int(limit), 100))))]

    def recall(self, agent_id, query=None):
        # Never expose raw task output, evaluation identities or development logs.
        query = query or {}
        items = self.list(agent_id, 100)
        if query.get('evaluator_id'):
            items = [x for x in items if x['evaluator_id'] == query['evaluator_id']]
        keys = ('failure_stage', 'failure_code', 'changed_component')
        items.sort(key=lambda x: sum(bool(query.get(k)) and x.get(k) == query[k]
                                    for k in keys), reverse=True)
        safe = ('run_id', 'hypothesis', 'outcome', 'scores', 'baseline', 'candidate',
                'evaluator_id', 'scope', 'interpretation', 'failure_stage',
                'failure_code', 'changed_component', 'applicability', 'evidence_refs', 'diagnostic')
        return [{k: item.get(k) for k in safe} for item in items[:6]]
