"""Shadow metrics: structural input diversity, never claimed numerical coverage."""
import hashlib
import json

VERSION = 'input-diversity-shadow-v1'


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def diversity(suite):
    if not isinstance(suite, list) or not suite:
        return {'version': VERSION, 'status': 'invalid', 'reason': 'nonempty suite required'}
    groups, shapes, dtypes = {}, set(), set()
    for index, case in enumerate(suite):
        if not isinstance(case, dict) or not isinstance(case.get('inputs'), list) or not case['inputs']:
            return {'version': VERSION, 'status': 'invalid', 'reason': 'missing inputs', 'index': index}
        if any(not isinstance(i, dict) for i in case['inputs']):
            return {'version': VERSION, 'status': 'invalid', 'reason': 'invalid input', 'index': index}
        try:
            # Ignore narrative and case IDs only; preserve output constraints and other semantics.
            payload = {k:v for k,v in case.items() if k not in ('id', 'generate_intent', 'trigger_library_ref')}
            key = signature(payload)
            shapes.add(signature([i.get('shape') for i in case['inputs']]))
            dtypes.add(signature([i.get('dtype') for i in case['inputs']]))
        except (ValueError, TypeError):
            return {'version': VERSION, 'status': 'invalid', 'reason': 'noncanonical input', 'index': index}
        groups.setdefault(key, []).append(index)
    duplicates = [indices for indices in groups.values() if len(indices) > 1]
    return {'version': VERSION, 'status': 'observed', 'case_count': len(suite),
            'unique_specifications': len(groups), 'duplicate_excess': len(suite)-len(groups),
            'unique_fraction': len(groups)/len(suite), 'shape_signatures': len(shapes),
            'dtype_signatures': len(dtypes), 'duplicate_groups': duplicates[:100],
            'duplicate_group_count': len(duplicates),
            'scope': 'Exact declarative specification diversity, not sampled tensor diversity, numerical coverage or bug detection',
            'promotion_eligible': False}
