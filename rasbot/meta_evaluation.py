"""Versioned shadow evaluation. Never changes task verdicts or adopted versions."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from .evidence import generation_integrity

from .evaluation_policy import EVALUATOR_ID
WEIGHTS = {'valid_rules': .35, 'risk_coverage': .30, 'deliverables': .15,
           'evidence_consistency': .10, 'diversity': .10}
from .execution_package import GENERATION_DELIVERABLES as DELIVERABLES
PROBE = '''import sys,json,importlib.util
from pathlib import Path
sys.path.insert(0,sys.argv[1])
spec=importlib.util.spec_from_file_location('trusted_prepare',Path(sys.argv[1])/'prepare_atk_submission.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
w=Path(sys.argv[2]);rules=json.loads((w/'01_generate/submission/test_suite.json').read_text(encoding='utf-8'))
config=m._load_task_config(w/'02_atk_run/atk_run_config.json')
if not isinstance(rules,list) or any(not isinstance(x,dict) for x in rules):raise ValueError('Invalid suite')
valid,skipped,logs,warnings=m.prepare_and_verify(rules,config)
print(json.dumps({'valid':len(valid),'skipped':len(skipped),'examples':skipped[:10]}))
'''


def weighted(metrics):
    points = sum(100 * WEIGHTS[k] * v for k, v in metrics.items() if v is not None)
    weight = sum(WEIGHTS[k] for k,v in metrics.items() if v is not None)
    return {'score': round(points, 2) if weight > .999999 else None,
            'measured_points': round(points, 2), 'measured_maximum': round(100 * weight, 2),
            'possible_range': [round(points, 2), round(points + 100 * (1-weight), 2)],
            'metrics': metrics, 'weights': dict(WEIGHTS),
            'measurement_coverage': {k: 'measured' if v is not None else 'not_measured' for k,v in metrics.items()}}


def evaluate(task, repo=None, dependencies=None):
    metrics = dict.fromkeys(WEIGHTS)
    diagnostics, artifact_hashes = [], {}
    result = task.get('result', {})
    root = Path(result['workspace']).resolve() if result.get('workspace') else None
    def read(relative):
        if root is None: return None
        p = root / relative
        try:
            if not p.resolve().is_relative_to(root):
                diagnostics.append({'code':'outside_workspace','path':relative});return None
            raw = p.read_bytes()
            artifact_hashes[relative] = hashlib.sha256(raw).hexdigest()
            return raw
        except OSError: return None
    raws = {p: read(p) for p in DELIVERABLES}
    metrics['deliverables'] = sum(bool(v and v.strip()) for v in raws.values()) / len(DELIVERABLES)
    for p, raw in raws.items():
        if not raw: diagnostics.append({'code':'missing_deliverable','path':p})
    def parsed(raw):
        try: return json.loads(raw) if raw else None
        except (ValueError, UnicodeError): return None
    suite = parsed(raws[DELIVERABLES[0]])
    config = parsed(read('02_atk_run/atk_run_config.json')) or {}
    expected = config.get('max_cases') if isinstance(config,dict) else None
    ledger = parsed(raws[DELIVERABLES[3]])
    from .risk_profile import evaluate as risk_evaluate, consistency, diversity
    risk=risk_evaluate(task.get('slug',''),suite)
    metrics.update(diversity=diversity(suite),risk_coverage=risk['score'],
                   evidence_consistency=consistency(suite,ledger))
    if not isinstance(suite,list) or not suite:metrics['valid_rules']=0.0
    if repo and isinstance(suite,list) and suite and type(expected) is int and expected>0:
        try:
            env = dict(os.environ, PYTHONUTF8='1')
            if dependencies and Path(dependencies).is_dir(): env['PYTHONPATH']=str(dependencies)
            scripts=Path(repo)/'scripts'
            evaluator_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in scripts.glob('*.py')}
            check=subprocess.run([sys.executable,'-B','-X','utf8','-c',PROBE,str(scripts),str(root)],
                                 capture_output=True,text=True,encoding='utf-8',timeout=45,env=env)
            if check.returncode: raise ValueError('Canonical materialization probe failed')
            evidence=json.loads(check.stdout)
            if evaluator_hashes!={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in scripts.glob('*.py')}:
                raise ValueError('Evaluator changed during probe')
            if any(read(p)!=raw for p,raw in raws.items()): raise ValueError('Artifacts changed during probe')
            metrics['valid_rules']=evidence['valid']/max(expected,len(suite))
            diagnostics.append({'code':'canonical_rule_check',**evidence,'expected':expected})
        except (OSError,ValueError,subprocess.TimeoutExpired) as error:
            metrics['valid_rules']=None;diagnostics.append({'code':'measurement_error','reason':str(error)[:300]})
    integrity=generation_integrity(result)
    reason=result.get('validation',{}).get('reason','')
    issues=[]
    if integrity['status']=='invalid': issues.extend(integrity['issues'])
    if any(x in reason for x in ('assets changed','sources changed','reference files changed','evaluator scripts changed')):
        issues.append('protected_asset_change')
    eligible=False if issues else None
    manifest=result.get('agent_manifest',{})
    if not issues and root and manifest.get('protected') is not None:
        from .agent_runtime import protected_digest
        from .precision_package import intact, references_intact
        try:
            if protected_digest(root)!=manifest['protected']: issues.append('protected_asset_change')
            if any(not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h for p,h in manifest.get('trusted_scripts',{}).items()): issues.append('trusted_evaluator_change')
            if manifest.get('execution_root') and (not intact(manifest['execution_root'],manifest['execution_files']) or
                not references_intact(manifest['execution_root'],manifest.get('reference_files',{}))): issues.append('execution_package_change')
            eligible=False if issues else True
        except (OSError,KeyError): eligible=None
    if task['state'] not in ('generated','validation_failed'): eligible=None
    events=task.get('events',[])
    starts=[e['created'] for e in events if e['kind']=='state.engine_running']
    ends=[e['created'] for e in events if e['kind']=='state.'+task['state']]
    seconds=max(0,(datetime.fromisoformat(ends[-1])-datetime.fromisoformat(starts[0])).total_seconds()) if starts and ends else None
    quality=weighted(metrics)
    if risk.get('status')=='partially_measured':
        quality['score']=None
        quality['possible_range'][1]=round(quality['measured_points']+100*WEIGHTS['risk_coverage']*(risk['possible_range'][1]-risk['score']),2)
        quality['measurement_coverage']['risk_coverage']='partially_measured'
        quality['score_semantics']='confirmed_points_lower_bound'
    return {'evaluator_version':EVALUATOR_ID,'risk_evidence':risk,'mode':'diagnostic','promotion_eligible':False,
            'validity':{'eligible':eligible,'issues':issues,'scope':'current local integrity; historical execution isolation not proven'},
            'quality':quality,'cost':{'duration_seconds':seconds,'model_cost':None},
            'diagnostics':diagnostics,'artifact_sha256':artifact_hashes,
            'evaluator_sha256':locals().get('evaluator_hashes',{}),
            'limits':['Risk coverage uses fixed input-design probes, not sampled hardware coverage.',
                      'Rule validity means canonical materializability, not exhaustive numerical constraints.',
                      'Deliverable presence is not document quality. No hardware effect evaluated.']}


def compare(pairs):
    details=[]
    for slug,base,candidate in pairs:
        common=[k for k in WEIGHTS if base['quality']['metrics'][k] is not None and candidate['quality']['metrics'][k] is not None]
        details.append({'slug':slug,'metric_deltas':{k:round(candidate['quality']['metrics'][k]-base['quality']['metrics'][k],4) for k in common},
                        'common_weight':sum(WEIGHTS[k] for k in common),
                        'baseline_score':base['quality']['score'],'candidate_score':candidate['quality']['score']})
    return {'mode':'shadow','decision':'not_for_promotion','pairs':details,
            'reason':'Incomplete domain-effect measurement; preserve original decision. No missing-weight renormalization.'}
