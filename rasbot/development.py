"""Editable candidate workspace; never use development results as formal scores."""
import json
from pathlib import Path
from datetime import datetime, timezone
from .core import now
from .execution_package import hashes


# Compatibility for callers of the original Precision-only helper.
def collect(root, original, references=None):
    from .precision_development import collect as precision_collect
    return precision_collect(root, original, references)


def prepare(evo, run, body):
    run.update(state='development_preparing', development_body=body)
    evo.save(run, 'preparing candidate development workspace')
    root = Path(run['root']) / 'development'
    root.mkdir()
    adapter = evo.runtime.registry.get(run['agent_id'])
    source = evo.store.get(run['evidence'][0]['task_id'])
    run['development'] = adapter.prepare_development(evo.runtime, source, root, body)
    with evo.store.connect() as c:
        parent = json.loads(c.execute('SELECT body FROM versions WHERE id=?', (run.get('proposal_parent', run['baseline']),)).fetchone()[0])
    adapter.bind_development_parent(run['development'], parent.get('execution_files', {}))
    run['state'] = 'development_ready'
    return evo.save(run, 'candidate development ready; formal evaluation tasks not exposed')


def relay(evo, run, reason):
    """Called only after confirmed idle; snapshots never count as promotion."""
    adapter = evo.runtime.registry.get(run['agent_id'])
    dev = run['development']
    if len(dev.get('episodes', [])) >= 3 or evo.round_expired(run):
        return False
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(dev['started'])).total_seconds()
    if elapsed >= run['policy']['development_seconds']:
        return False
    if any(adapter.development_asset_changes(dev).values()):
        return False
    files = adapter.collect_development(dev)
    checkpoint = {'created': now(), 'parent': run.get('proposal_parent', run['baseline']),
                  'files': files, 'file_hashes': hashes(files), 'reason': reason,
                  'check': dev.get('check'), 'session_id': run['session_id'],
                  'scope': 'source-integrity-checked development only; not accepted candidate'}
    dev['checkpoint'] = checkpoint
    dev.setdefault('checkpoints', []).append(checkpoint)
    if dev.get('episodes'):
        dev['episodes'][-1].update(finished=now(), reason=reason)
    dev['status'] = 'ready'
    run['state'] = 'development_ready'
    evo.save(run, 'development checkpoint saved; confirmed idle session handed off')
    return True


def tick(evo, run):
    if run['state'] in ('development_preparing', 'development_starting', 'development_unknown'):
        run['last_error'] = 'Development request outcome uncertain; inspect session before cancelling. Not replayed.'
        return evo.save(run)
    adapter = evo.runtime.registry.get(run['agent_id'])
    dev = run['development']
    if run['state'] == 'development_ready':
        if dev.get('checkpoint'):
            current = adapter.collect_development(dev)
            if hashes(current) != dev['checkpoint']['file_hashes']:
                run.update(state='failed', reason='Development checkpoint source changed before handoff')
                return evo.save(run, run['reason'])
        run['state'] = 'development_starting'
        evo.save(run, 'development session creation requested')
        run.setdefault('proposal_session_id', run.get('session_id'))
        run['session_id'] = evo.engine.client.request('POST', '/api/session', {
            'title': 'RASBot candidate development ' + run['id'],
            'location': {'directory': dev['root']}})['data']['id']
        dev['session_id'] = run['session_id']
        dev.setdefault('episodes', []).append({'session_id': run['session_id'], 'started': now()})
        evo.save(run)
        path = evo.engine.client.session_path(run['session_id'])
        evo.engine.client.request('POST', path + '/model', {'model': run['model']})
        prompt = adapter.development_prompt(dev, run['proposal'])
        (Path(dev['root']) / 'instructions.md').write_text(prompt, encoding='utf-8')
        dev.setdefault('started', now())
        dev.update(status='running')
        run['state'] = 'development_unknown'
        evo.save(run)
        evo.engine.client.request('POST', path + '/prompt', {'text': prompt})
        run['state'] = 'developing'
        return evo.save(run, 'editable development session submitted')
    if run['state'] != 'developing':
        return run  # Uncertain requests must never be blindly replayed.
    path = evo.engine.client.session_path(run['session_id'])
    context = evo.engine.client.request('GET', path + '/context')['data']
    (Path(dev['root']) / 'context.json').write_text(json.dumps(context, ensure_ascii=False), encoding='utf-8')
    dev['context_artifact'] = str(Path(dev['root']) / 'context.json')
    episode_path = Path(dev['root']) / ('episode-' + str(len(dev.get('episodes', []))) + '.json')
    episode_path.write_text(json.dumps(context, ensure_ascii=False), encoding='utf-8')
    if (datetime.now(timezone.utc) - datetime.fromisoformat(dev['started'])).total_seconds() > run['policy']['development_seconds']:
        return evo.budget_stop(run, 'Candidate development budget exceeded')
    if not context or context[-1].get('type') != 'idle':
        return evo.save(run)
    dev['source_changes'] = adapter.observe_development(dev)
    try:
        if context[-1].get('outcome') != 'succeeded':
            if relay(evo, run, 'Development session ended unsuccessfully'):
                return run
            raise ValueError('Candidate development did not succeed')
        changes = adapter.development_asset_changes(dev)
        if any(changes.values()):
            dev['check'] = {'passed': False, 'validation': {'passed': False, 'reason': 'Protected task assets changed', 'asset_changes': changes}}
            raise ValueError('Development changed protected smoke task assets')
        tools = [p for m in context for p in m.get('content', []) if p.get('type') == 'tool']
        if not any(p.get('name') == 'shell' and p.get('state', {}).get('status') == 'completed' for p in tools):
            raise ValueError('Development has no completed shell trial evidence')
        files = adapter.collect_development(dev)
    except (ValueError, OSError) as error:
        run.update(state='failed', reason=str(error)); dev['status'] = 'failed'
        return evo.save(run, 'development freeze rejected')
    if run['policy'].get('development_check') == 'development-artifact-gate-v1':
        remaining = run['policy']['development_seconds'] - (datetime.now(timezone.utc) - datetime.fromisoformat(dev['started'])).total_seconds()
        if remaining <= 0:
            return evo.budget_stop(run, 'Development budget exhausted before independent check')
        dev['check'] = adapter.check_development(evo.runtime, dev, remaining)
        if not dev['check']['passed']:
            if relay(evo, run, 'Independent development artifact check failed'):
                return run
            run.update(state='failed', reason='Independent development artifact check failed')
            dev['status'] = 'failed'
            return evo.save(run, run['reason'])
        if evo.round_expired(run) or (datetime.now(timezone.utc) - datetime.fromisoformat(dev['started'])).total_seconds() > run['policy']['development_seconds']:
            return evo.budget_stop(run, 'Development check exceeded budget')
    body = run.pop('development_body'); body['execution_files'] = files
    dev.update(status='frozen', frozen=now(), file_hashes=hashes(files), tool_calls=len(tools))
    return evo.register_candidate(run, body)
