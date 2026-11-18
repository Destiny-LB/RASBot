"""Platform-owned development acceptance; model claims are not test evidence."""
from .evaluation_policy import QUALITY_POLICY
import json,time,subprocess
from .evaluation_budget import remaining,BudgetExhausted
from pathlib import Path
from .core import now


def check(runtime, agent_id, dev, seconds):
    deadline=time.monotonic()+max(0,seconds)
    result = {'version': 'development-artifact-gate-v1', 'started': now(),
              'scope': 'diagnosis-task generation only; not held-out evaluation'}
    manifest = {'agent_id': agent_id, 'workspace': dev['workspace'],
                'attempt': dev['root'], 'protected': dev['protected'],
                'validation_timeout': min(180,max(0,seconds)), 'validation_deadline':deadline}
    if dev.get('scoring_version')==QUALITY_POLICY:
        manifest['quality_policy']=QUALITY_POLICY
        result['version']='development-artifact-gate-v2'
    try:
        remaining(deadline,180)
        if dev.get('execution_scope')=='precision-generation-toolchain-v1':
            import uuid
            from .precision_toolchain import prepare
            from .precision_development import collect
            files=collect(dev['package'],dev['original_files'],dev.get('reference_files'))
            _,result['preparation_evidence']=prepare(runtime,dev['training_slug'],Path(dev['root'])/('prepare-check-'+uuid.uuid4().hex),files,deadline=deadline)
        remaining(deadline,180)
        verdict = runtime.registry.get(agent_id).validate(runtime, manifest)
        if verdict.get('passed') and dev.get('execution_scope')=='precision-generation-toolchain-v1':
            import hashlib
            from .toolchain_contracts import check as contract_check
            root=Path(dev['package'])
            contract_manifest={'workspace':dev['workspace'],'validation_deadline':deadline,'execution_root':str(root),'reference_files':dev.get('reference_files',{}),
                'execution_files':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files}}
            contract=contract_check(runtime,contract_manifest,Path(dev['workspace'])/'01_generate/submission/test_suite.json')
            verdict.update(toolchain_contract=contract,passed=contract['passed'])
        if verdict.get('reason')=='budget_exhausted' or (verdict.get('toolchain_contract') or {}).get('reason')=='budget_exhausted':raise BudgetExhausted('budget_exhausted')
        contract=verdict.get('toolchain_contract') or {}
        if contract.get('status')=='error':result.update(reason='toolchain_evidence_unavailable',cause=contract.get('reason','probe_error'))
        remaining(deadline,180)
        result.update(passed=verdict.get('passed') is True, validation=verdict)
    except (BudgetExhausted,subprocess.TimeoutExpired) as error:
        result.update(passed=False,reason='budget_exhausted',error=str(error))
    except Exception as error:
        result.update(passed=False, error=type(error).__name__ + ': ' + str(error))
    result['finished'] = now()
    path = Path(dev['root']) / 'development-check.json'
    result['artifact'] = str(path)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
