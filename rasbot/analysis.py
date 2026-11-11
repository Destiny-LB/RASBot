"""Read-only, versioned observations. Never rewrite historical evaluation scores."""
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from .quality import diversity

VERSION = 'traceability-shadow-v1'


def traceability(suite, ledger):
    """Check declared links, not the numerical effectiveness of a test."""
    issues = []
    def issue(code, subject):
        issues.append({'code': code, 'subject': str(subject)})
    if not isinstance(suite, list) or not isinstance(ledger, dict) or not isinstance(ledger.get('triggers'), list):
        return {'version': VERSION, 'status': 'invalid', 'issues': [{'code': 'invalid_schema', 'subject': 'suite/ledger'}]}
    cases, refs, triggers = {}, {}, {}
    for case in suite:
        if not isinstance(case, dict) or type(case.get('id')) is not int:
            issue('invalid_case_id', 'case'); continue
        key = case['id']
        if key in cases: issue('duplicate_case_id', key)
        cases[key] = case
        refs[key] = set()
        if not isinstance(case.get('generate_intent'), str) or not case['generate_intent'].strip():
            issue('missing_intent', key)
        values = case.get('trigger_library_ref', [])
        if not isinstance(values, list) or not values:
            issue('missing_reference', key); continue
        for ref in values:
            match = re.fullmatch(r'(TRIGGER-[\w.-]+|CODE-[\w.-]+):\s*(\S.*)', ref) if isinstance(ref, str) else None
            if not match: issue('malformed_reference', key); continue
            if match[1].startswith('TRIGGER-'): refs[key].add(match[1][8:])
            else:
                code = ledger.get('code_triggers', {})
                if not isinstance(code, dict) or not ({match[1], match[1][5:]} & code.keys()):
                    issue('undefined_code_trigger', match[1])
    for trigger in ledger['triggers']:
        if not isinstance(trigger, dict) or not isinstance(trigger.get('id'), str):
            issue('invalid_trigger', 'ledger'); continue
        key = trigger['id']
        if key in triggers: issue('duplicate_trigger', key)
        triggers[key] = trigger
        ids = trigger.get('actual_case_ids', [])
        if not isinstance(ids, list) or any(type(i) is not int for i in ids):
            issue('invalid_case_links', key); continue
        if trigger.get('status') == 'applicable' and not ids: issue('uncovered_applicable', key)
        if trigger.get('status') == 'skipped' and ids: issue('skipped_with_cases', key)
        if trigger.get('status') not in ('applicable', 'skipped', 'not_testable'): issue('unassessed_trigger', key)
        for identity in ids:
            if identity not in cases: issue('dangling_case', f'{key}:{identity}')
            elif key not in refs[identity]: issue('missing_reverse_reference', f'{key}:{identity}')
    for identity, links in refs.items():
        for key in links:
            if key not in triggers: issue('unknown_trigger', key)
            elif not isinstance(triggers[key].get('actual_case_ids', []), list) or identity not in triggers[key].get('actual_case_ids', []):
                issue('missing_ledger_link', f'{key}:{identity}')
    return {'version': VERSION, 'status': 'observed', 'consistent': not issues,
            'case_count': len(cases), 'trigger_count': len(triggers), 'issue_count': len(issues),
            'issues': issues[:100], 'scope': 'Declared traceability only; not numerical coverage or defect detection'}


def diagnose(task):
    result = task['result']
    validation = result.get('validation', {})
    events = task.get('events', [])
    durations = {}
    transitions = [e for e in events if e['kind'].startswith('state.') or e['kind'] == 'task.created']
    for left, right in zip(transitions, transitions[1:]):
        seconds = max(0, (datetime.fromisoformat(right['created']) - datetime.fromisoformat(left['created'])).total_seconds())
        state = left['kind'].removeprefix('state.')
        durations[state] = round(durations.get(state, 0) + seconds, 3)
    failures = {}
    artifact = result.get('context_artifact')
    context_status = 'unavailable'
    if artifact:
        try:
            messages = json.loads(Path(artifact).read_text(encoding='utf-8'))
            for message in messages:
                for part in message.get('content', []):
                    if part.get('type') == 'tool' and part.get('state', {}).get('status') in ('error', 'failed'):
                        name = str(part.get('name', 'unknown'))
                        failures[name] = failures.get(name, 0) + 1
            context_status = 'available'
        except (OSError, ValueError, TypeError, AttributeError): context_status = 'unreadable'
    category = ('validation_failure' if validation.get('passed') is False else
                'execution_failure' if task['state'] in ('engine_failed', 'blocked') else
                'interrupted' if task['state'] == 'cancelled' else
                'completed' if task['state'] in ('generated', 'completed') else 'in_progress')
    return {'category': category, 'validation_reason': validation.get('reason'),
            'tool_failures': failures, 'context_status': context_status, 'phase_seconds': durations,
            'bottleneck_observation': max(durations, key=durations.get) if durations else None,
            'scope': 'Observed state residence time, not causal attribution; unfinished phases excluded'}


def analyze_task(task):
    report = {'task_id': task['id'], 'agent_id': task['domain'], 'diagnosis': diagnose(task),
              'quality': {'status': 'unsupported'}}
    if task['domain'] != 'precision': return report
    workspace = task['result'].get('workspace')
    if not workspace:
        report['quality'] = {'status': 'unavailable'}; return report
    root = Path(workspace)
    paths = [root / '01_generate/submission/test_suite.json', root / '01_generate/report/trigger_coverage.json']
    try:
        raw = [p.read_bytes() for p in paths]
        report['quality'] = traceability(*[json.loads(b) for b in raw])
        report['input_diversity'] = diversity(json.loads(raw[0]))
        report['quality']['artifact_sha256'] = [hashlib.sha256(b).hexdigest() for b in raw]
    except (OSError, ValueError, TypeError):
        report['quality'] = {'version': VERSION, 'status': 'unavailable_or_invalid'}
    return report
