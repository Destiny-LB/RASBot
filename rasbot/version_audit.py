"""Read-only view of version lineage and its actual evaluation evidence."""
import difflib
import json


def audit_versions(store, adopted, runs, adopted_by_agent=None):
    snapshot = store.snapshot()
    versions = snapshot['versions']
    referenced = {t['version'] for t in snapshot['tasks']}
    referenced.update(v['parent'] for v in versions if v['parent'])
    for run in runs:
        referenced.update(run.get(k) for k in ('baseline','baseline_source','candidate','proposal_parent'))
    for evaluation in snapshot['evaluations']:
        referenced.update(evaluation.get(k) for k in ('baseline','candidate'))
    bodies = {v['id']: json.loads(v['body']) for v in versions}
    result = []
    for version in versions:
        identity = version['id']
        body = bodies[identity]
        # Runtime recreates this shared fallback on every startup. It is not
        # Precision evolution history when unused and a dedicated version is adopted.
        if (body.get('name')=='baseline' and not body.get('agent_id') and
                not body.get('execution_files') and identity!=adopted and identity not in referenced):
            continue
        parent = bodies.get(version['parent'], {})
        before = parent.get('agent_instructions', '')
        after = body.get('agent_instructions', '')
        old_files, new_files = parent.get('execution_files', {}), body.get('execution_files', {})
        is_snapshot = 'execution_files' in body and (version['parent'] is None or
            (body.get('name') == 'frozen-execution-baseline' and 'execution_files' not in parent))
        file_diffs = [{'path': name, 'status': 'snapshot' if is_snapshot else ('removed' if name not in new_files else 'modified' if name in old_files else 'added'),
                       'content': new_files.get(name, '') if is_snapshot else None,
                       'diff': '' if is_snapshot else '\n'.join(difflib.unified_diff(
                           old_files.get(name, '').splitlines(), new_files.get(name, '').splitlines(),
                           fromfile='parent/' + name, tofile='current/' + name, lineterm=''))}
                      for name in sorted(set(old_files) | set(new_files))
                      if old_files.get(name) != new_files.get(name)]
        evaluations = []
        for run in runs:
            roles = [role for role in ('baseline', 'candidate') if run.get(role) == identity]
            if roles:
                evaluations.append({'id': run['id'], 'roles': roles, 'state': run['state'],
                                    'scores': run.get('scores'), 'decision': run.get('decision'), 'evaluator_id': run['evaluator_id'],
                                    'created': run['created'],
                                    'trials': [t for t in run['trials'] if t['role'] in roles]})
        result.append({'id': identity, 'parent': version['parent'], 'created': version['created'],
                       'agent_id': body.get('agent_id', 'precision'),
                       'adopted': identity == (adopted_by_agent or {}).get(body.get('agent_id', 'precision'), adopted), 'body': body, 'evaluations': evaluations,
                       'file_diffs': file_diffs, 'source_snapshot': is_snapshot,
                       'instruction_diff': '\n'.join(difflib.unified_diff(
                           before.splitlines(), after.splitlines(), fromfile='parent overlay',
                           tofile='current overlay', lineterm=''))})
    return result
