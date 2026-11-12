"""Internal result semantics and live-task integrity; no external artifact importer."""
import hashlib
from pathlib import Path

VERSION = 'reliability-evidence-v1'
RESULTS = ('accuracy_pass', 'accuracy_false', 'execution_error', 'accuracy_unavailable')


def generation_integrity(result):
    """Recheck only fixed artifacts inside this platform task's own workspace."""
    validation = result.get('validation', {})
    fields = {'suite_sha256': '01_generate/submission/test_suite.json',
              'atk_input_sha256': '02_atk_run/atk_input/test_suite.atk.json'}
    if not any(validation.get(k) for k in fields):
        return {'status': 'not_recorded', 'verified': False, 'issues': []}
    if not result.get('workspace'):
        return {'status': 'invalid', 'verified': False, 'issues': ['missing_workspace']}
    root = Path(result['workspace']).resolve()
    issues = []
    for key, relative in fields.items():
        expected = validation.get(key)
        if not isinstance(expected, str) or len(expected) != 64:
            issues.append('missing_digest:' + key)
            continue
        file = root / relative
        try:
            if not file.resolve().is_relative_to(root):
                issues.append('outside_workspace:' + relative)
                continue
            digest = hashlib.sha256()
            with file.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                issues.append('digest_mismatch:' + relative)
        except OSError:
            issues.append('missing_or_unreadable:' + relative)
    return {'status': 'verified' if not issues else 'invalid', 'verified': not issues, 'issues': issues}


def comparison(cases, expected_count, trustworthy=None):
    """Pure internal contract for future execution adapters; never reads report files.

    Trustworthiness must come from the execution adapter, not from an LLM report.
    Case IDs count inputs, not output tensors or repeated job attempts.
    """
    result = {'version': VERSION, 'status': 'invalid', 'observed_status': None,
              'comparison_trustworthy': trustworthy, 'root_cause_confirmed': None,
              'promotion_eligible': False}
    if type(expected_count) is not int or expected_count < 0 or not isinstance(cases, list):
        return {**result, 'reason': 'invalid_case_contract'}
    if trustworthy is not None and type(trustworthy) is not bool:
        return {**result, 'reason': 'invalid_trust_state'}
    counts = dict.fromkeys(RESULTS, 0)
    seen = set()
    for case in cases:
        if (not isinstance(case, dict) or type(case.get('id')) is not int or case['id'] < 0
                or case.get('result') not in RESULTS):
            return {**result, 'reason': 'invalid_case_record'}
        if case['id'] in seen:
            return {**result, 'reason': 'duplicate_case_id'}
        seen.add(case['id']); counts[case['result']] += 1
    if len(cases) != expected_count:
        return {**result, 'reason': 'case_count_mismatch', 'observed_count': len(cases)}
    compared = counts['accuracy_pass'] + counts['accuracy_false']
    observed = 'FAULT' if counts['accuracy_false'] else 'PASS' if compared else 'BLOCKED'
    status = observed if trustworthy is True else 'BLOCKED'
    return {**result, 'status': status, 'observed_status': observed, 'counts': counts,
            'comparison_count': compared, 'execution_success': compared + counts['accuracy_unavailable'],
            'coverage_gaps': counts['execution_error'] + counts['accuracy_unavailable'],
            'false_rate_among_compared': counts['accuracy_false'] / compared if compared else None,
            'reason': ('comparison_trust_unknown' if trustworthy is None else
                       'comparison_untrustworthy' if not trustworthy else
                       'no_valid_comparison' if not compared else 'comparison_observed'),
            'scope': 'Comparison outcomes only; accuracy_false is not a confirmed defect count'}


def task_evidence(task):
    validation = task['result'].get('validation', {})
    # No hardware adapter exists today. Even arbitrary files or task fields claiming
    # hardware success cannot upgrade a generation-only task to a hardware verdict.
    return {'version': VERSION, 'generation_passed': validation.get('passed'),
            'generation_integrity': generation_integrity(task['result']),
            'hardware_status': 'not_evaluated', 'root_cause_confirmed': None,
            'scope': 'Current precision harness validates generation, not hardware accuracy'}
