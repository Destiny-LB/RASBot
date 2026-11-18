"""Platform-owned structural probes; candidate tests never authorize promotion."""
import hashlib,json,subprocess,sys,tempfile
from .evaluation_budget import remaining,BudgetExhausted
from pathlib import Path
from .precision_toolchain import environment
from .precision_package import intact,references_intact
PROBE="""import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
try:
    from verify_schema import validate_atk_structure
    suite=json.loads(Path(sys.argv[2]).read_text(encoding='utf8'))
    cases=[suite,{},[],[None],[{}],[dict(suite[0],inputs=[])]]
    print(json.dumps([not bool(validate_atk_structure(case)[0]) for case in cases]))
except (ImportError,SyntaxError,AttributeError,TypeError,ValueError,KeyError,IndexError,NameError) as error:
    print(type(error).__name__+': '+str(error),file=sys.stderr)
    sys.exit(20)
"""

class CandidateContractViolation(ValueError):
    pass

def check(runtime,manifest,suite):
    root=Path(manifest['execution_root'])
    changed=[name for name,digest in manifest['execution_files'].items()
             if not (runtime.repo/name).is_file() or hashlib.sha256((runtime.repo/name).read_text(encoding='utf8').encode('utf8')).hexdigest()!=digest]
    plan=contract_plan(changed)
    evidence={'contract_plan':plan,'version':'toolchain-structural-contract-v1','changed_files':changed,
              'scope':'schema acceptance/rejection and frozen package integrity; not full behavioral equivalence',
              'passed':True,'status':'not_required'}
    # All script helpers and schema knowledge can affect the public validator contract.
    required=bool(plan['local_probes'])
    if not required:return evidence
    def snapshot():
        paths={Path(suite)}
        for folder in [Path(manifest.get('workspace',Path(suite).parent)),runtime.repo/'scripts',Path(__file__).parent]:
            paths.update(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before=None
    try:
        remaining(manifest.get('validation_deadline'),30)
        before=snapshot()
        source=Path(suite).read_bytes()
        outcomes=[]
        evidence['executions']=[]
        with tempfile.TemporaryDirectory(prefix='rasbot-contract-') as temp:
            for index,scripts in enumerate((runtime.repo/'scripts',root/'scripts')):
                probe=Path(temp)/f'suite-{index}.json'
                probe.write_bytes(source)
                r=subprocess.run([sys.executable,'-B','-X','utf8','-c',PROBE,str(scripts),str(probe)],
                    cwd=root,capture_output=True,encoding='utf8',errors='replace',
                    timeout=remaining(manifest.get('validation_deadline'),30),env=environment(runtime))
                if not probe.is_file() or probe.read_bytes()!=source:
                    raise ValueError('Contract probe mutated isolated input')
                side='trusted' if index==0 else 'candidate'
                evidence['executions'].append({'side':side,'returncode':r.returncode})
                if r.returncode:
                    if index==1 and r.returncode==20:
                        raise CandidateContractViolation('Candidate interface failure: '+r.stderr[-500:])
                    evidence['reason']='trusted_probe_error' if index==0 else 'unclassified_probe_error'
                    raise ValueError('Structural probe failed: '+r.stderr[-500:])
                try: outcome=json.loads(r.stdout)
                except ValueError:
                    if index==1:raise CandidateContractViolation('Candidate probe output is not JSON')
                    raise ValueError('Trusted probe output is not JSON')
                outcomes.append(outcome)
                if index==0 and outcome!=[True,False,False,False,False,False]:
                    evidence['reason']='trusted_contract_failed'
                    raise ValueError('Trusted contract does not accept fixed fixtures')
        remaining(manifest.get('validation_deadline'),30)
        expected=[True,False,False,False,False,False]
        evidence.update(status='checked',probe_names=['formal_valid_suite','object_suite','empty_suite','non_object_rule','missing_fields','empty_inputs'],trusted=outcomes[0],candidate=outcomes[1])
        evidence['passed']=outcomes[0]==expected and outcomes[1]==expected
        if outcomes[0]!=expected:evidence.update(status='error',reason='trusted_contract_failed')
        elif outcomes[1]!=expected:evidence.update(reason='behavior_mismatch')
        if not intact(root,manifest['execution_files']) or not references_intact(root,manifest.get('reference_files',{})):
            evidence['reason']='integrity_violation'
            raise ValueError('Contract probe mutated frozen execution package')
    except CandidateContractViolation as error:
        evidence.update(passed=False,status='checked',reason='candidate_interface_failure',error=str(error))
    except (BudgetExhausted,subprocess.TimeoutExpired) as error:
        evidence.update(passed=False,status='error',reason='budget_exhausted',error=str(error))
    except Exception as error:
        evidence.update(passed=False,status='error',error=str(error))
    if before is not None:
        try:
            if not intact(root,manifest['execution_files']) or not references_intact(root,manifest.get('reference_files',{})):
                raise ValueError('Contract probe mutated frozen execution package')
            if snapshot()!=before:raise ValueError('Contract probe changed formal artifacts or trusted assets')
        except Exception as error:
            evidence.update(passed=False,status='error',reason='integrity_violation',error=str(error))
    return evidence


def contract_plan(changed):
    """Describe checks without claiming that unimplemented semantic tests ran."""
    names=set(changed);scripts=any(n.startswith('scripts/') for n in names)
    schema=scripts or any(n.startswith('docs/') for n in names)
    checks=[];pending=[]
    if 'scripts/create_workspace.py' in names:checks.append('preparation_asset_equivalence')
    if any(n.startswith('prompts/') for n in names):
        checks.append('prompt_generation_and_package_integrity');pending.append('prompt_fact_semantics')
    if scripts:pending.extend(['conversion_semantics','trigger_coverage_semantics'])
    if any(n.startswith('openskill/02_') or n.startswith('openskill/03_') for n in names):pending.append('hardware_workflow_effect')
    return {'local_probes':['schema_positive_negative'] if schema else [],
            'execution_checks':checks,'not_validated':pending,
            'scope':'offline generation only; no hardware replay'}
