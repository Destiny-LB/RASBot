"""Platform-owned development acceptance; model claims are not test evidence."""
import json
from pathlib import Path
from .core import now


def check(runtime, agent_id, dev, seconds):
    result = {'version': 'development-artifact-gate-v1', 'started': now(),
              'scope': 'diagnosis-task generation only; not held-out evaluation'}
    manifest = {'agent_id': agent_id, 'workspace': dev['workspace'],
                'attempt': dev['root'], 'protected': dev['protected'],
                'validation_timeout': max(1, min(180, int(seconds)))}
    try:
        verdict = runtime.registry.get(agent_id).validate(runtime, manifest)
        result.update(passed=verdict.get('passed') is True, validation=verdict)
    except Exception as error:
        result.update(passed=False, error=type(error).__name__ + ': ' + str(error))
    result['finished'] = now()
    path = Path(dev['root']) / 'development-check.json'
    result['artifact'] = str(path)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
