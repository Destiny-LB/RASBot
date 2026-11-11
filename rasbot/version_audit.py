"""Read-only view of version lineage and its actual evaluation evidence."""
import difflib
import json


def audit_versions(store, adopted, runs, adopted_by_agent=None):
    versions = store.snapshot()['versions']
    bodies = {v['id']: json.loads(v['body']) for v in versions}
    result = []
    for version in versions:
        identity = version['id']
        body = bodies[identity]
        parent = bodies.get(version['parent'], {})
        before = parent.get('agent_instructions', '')
        after = body.get('agent_instructions', '')
        old_files, new_files = parent.get('execution_files', {}), body.get('execution_files', {})
        file_diffs = [{'path': name, 'status': 'modified' if name in old_files else 'added',
                       'diff': '\n'.join(difflib.unified_diff(
                           old_files.get(name, '').splitlines(), new_files.get(name, '').splitlines(),
                           fromfile='parent/' + name, tofile='current/' + name, lineterm=''))}
                      for name in sorted(set(old_files) | set(new_files))
                      if old_files.get(name) != new_files.get(name)]
        evaluations = []
        for run in runs:
            roles = [role for role in ('baseline', 'candidate') if run.get(role) == identity]
            if roles:
                evaluations.append({'id': run['id'], 'roles': roles, 'state': run['state'],
                                    'scores': run.get('scores'), 'evaluator_id': run['evaluator_id'],
                                    'created': run['created'],
                                    'trials': [t for t in run['trials'] if t['role'] in roles]})
        result.append({'id': identity, 'parent': version['parent'], 'created': version['created'],
                       'agent_id': body.get('agent_id', 'precision'),
                       'adopted': identity == (adopted_by_agent or {}).get(body.get('agent_id', 'precision'), adopted), 'body': body, 'evaluations': evaluations,
                       'file_diffs': file_diffs,
                       'instruction_diff': '\n'.join(difflib.unified_diff(
                           before.splitlines(), after.splitlines(), fromfile='parent overlay',
                           tofile='current overlay', lineterm=''))})
    return result
