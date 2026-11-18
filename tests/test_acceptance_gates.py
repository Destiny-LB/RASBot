import unittest
import test_quality_constraints
import test_toolchain_integrity
CODE=test_toolchain_integrity.CODE
from rasbot.meta_promotion import decide
class AcceptanceTests(unittest.TestCase):
 def data(self):
  rows=test_quality_constraints.QualityConstraintTests().data()
  for t in rows:
   if t['role']=='baseline':t['meta_evaluation']['quality']['metrics']['risk_coverage']=.5
  return rows
 def score(self,rows):return decide(rows,['a'],{'scoring_version':'meta-generation-v3'})
 def test_failed_candidate_cannot_promote_on_full_scores(self):
  d=self.data();d[-1].update(passed=False,terminal_state='validation_failed',toolchain_contract=None)
  self.assertEqual(self.score(d)['reason'],'candidate_acceptance_failed')
 def test_absent_acceptance_and_required_probe_are_inconclusive(self):
  d=self.data();d[-1].pop('passed');self.assertEqual(self.score(d)['state'],'inconclusive')
  d=self.data();d[-1].update(toolchain_required=True,toolchain_contract=None)
  self.assertEqual(self.score(d)['reason'],'required_contract_not_run')
 def test_failed_baseline_does_not_block_valid_improvement(self):
  d=self.data()
  for t in d:
   if t['role']=='baseline':t.update(passed=False,toolchain_required=True,toolchain_contract=None)
  self.assertEqual(self.score(d)['state'],'promoted')
 def test_explicit_not_required_is_valid_evidence(self):
  d=self.data()
  for t in d:t.update(toolchain_required=True,toolchain_contract={'passed':True,'status':'not_required'})
  self.assertEqual(self.score(d)['state'],'promoted')

class ProbeClassificationTests(unittest.TestCase):
 setUp=test_toolchain_integrity.ToolchainIntegrityTests.setUp
 run_probe=test_toolchain_integrity.ToolchainIntegrityTests.run_probe
 def test_candidate_missing_function_and_syntax_error_are_behavior_failures(self):
  for code in ('x=1\n','def broken(\n'):
   r=self.run_probe(code)
   self.assertEqual(r['reason'],'candidate_interface_failure');self.assertEqual(r['status'],'checked')
   self.assertEqual(r['executions'][0]['returncode'],0)
 def test_trusted_import_failure_is_not_candidate_fault(self):
  (self.repo/'scripts/verify_schema.py').write_text('x=1\n')
  r=self.run_probe(CODE)
  self.assertEqual(r['status'],'error');self.assertEqual(r['reason'],'trusted_probe_error')
  self.assertEqual(len(r['executions']),1)
 def test_unclassified_candidate_exit_is_inconclusive_evidence(self):
  r=self.run_probe('import sys\nsys.exit(7)\n')
  self.assertEqual(r['status'],'error');self.assertEqual(r['reason'],'unclassified_probe_error')
 def test_candidate_timeout_is_not_behavior_failure(self):
  import time
  from rasbot.toolchain_contracts import check
  self.run_probe(CODE)
  p=self.package/'scripts/verify_schema.py';p.write_text('import time\ntime.sleep(5)\n'+CODE)
  import hashlib
  self.manifest['execution_files']['scripts/verify_schema.py']=hashlib.sha256(p.read_bytes()).hexdigest()
  self.manifest['validation_deadline']=time.monotonic()+.5
  r=check(self.runtime,self.manifest,self.suite)
  self.assertEqual(r['reason'],'budget_exhausted');self.assertEqual(r['status'],'error')

class DeliverableTests(unittest.TestCase):
 def test_missing_trigger_library_is_required_by_both_layers(self):
  import tempfile,json
  from pathlib import Path
  from types import SimpleNamespace
  from rasbot.execution_package import GENERATION_DELIVERABLES
  from rasbot.meta_evaluation import evaluate
  from rasbot.agent_runtime import validate,protected_digest
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   for name in GENERATION_DELIVERABLES:
    if name.endswith('trigger_library.md'):continue
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('[]' if name.endswith('.json') else 'report')
   (root/GENERATION_DELIVERABLES[0]).write_text('[{"id":1,"inputs":[1]}]')
   (root/'02_atk_run/atk_run_config.json').write_text('{"max_cases":1}')
   verdict=validate(SimpleNamespace(repo=root),{'workspace':str(root),'protected':protected_digest(root),'attempt':str(root)})
   self.assertFalse(verdict['passed']);self.assertIn('01_generate/report/trigger_library.md',verdict['missing'])
   report=evaluate({'slug':'sample','state':'validation_failed','events':[],'result':{'workspace':str(root),'validation':verdict}})
   self.assertLess(report['quality']['metrics']['deliverables'],1)
