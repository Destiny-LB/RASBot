import unittest
from rasbot.meta_promotion import decide
from rasbot.meta_evaluation import WEIGHTS
from rasbot.evaluation_policy import EVALUATOR_ID
class QualityConstraintTests(unittest.TestCase):
 def data(self,rounds=2):
  return [dict(slug='a',replicate=r,role=role,passed=True,comparable=True,duration_seconds=100 if role=='baseline' else 70,meta_evaluation=dict(evaluator_version=EVALUATOR_ID,validity={'eligible':True},quality={'metrics':dict.fromkeys(WEIGHTS,1)})) for r in range(rounds) for role in ('baseline','candidate')]
 def decision(self,d):return decide(d,['a'],{'scoring_version':'meta-generation-v3','promotion_version':'quality-or-efficiency-v1','efficiency_max_ratio':.8})
 def test_speed_never_promotes(self):
  for rounds in (1,2):
   self.assertEqual(self.decision(self.data(rounds))['reason'],'insufficient_quality_gain')
 def test_quality_gain_is_independent_of_duration(self):
  d=self.data()
  for t in d:
   if t['role']=='baseline':t['meta_evaluation']['quality']['metrics']['risk_coverage']=.5
   t['duration_seconds']=None
  self.assertEqual(self.decision(d)['basis'],'generation_design_quality')
 def test_contract_errors_are_inconclusive(self):
  for reason in ('budget_exhausted','integrity_violation','infrastructure_error','trusted_contract_failed'):
   for role in ('baseline','candidate'):
    d=self.data();next(t for t in d if t['role']==role)['toolchain_contract']={'passed':False,'reason':reason,'status':'error'}
    self.assertEqual(self.decision(d)['state'],'inconclusive')
 def test_regression_never_bought_by_speed(self):
  d=self.data();d[-1]['meta_evaluation']['quality']['metrics']['diversity']=.99
  self.assertEqual(self.decision(d)['reason'],'insufficient_quality_gain')
 def test_every_pair_and_trustworthy_time_required(self):
  for duration in (90,None,True,float('nan'),0):
   d=self.data();d[-1]['duration_seconds']=duration
   self.assertEqual(self.decision(d)['state'],'rejected')
 def test_current_policy_does_not_require_legacy_marker(self):
  self.assertEqual(decide(self.data(),['a'],{'scoring_version':'meta-generation-v3'})['reason'],'insufficient_quality_gain')

 def test_contract_failure_cannot_be_offset_by_score(self):
  d=self.data();d[-1]['toolchain_contract']={'passed':False}
  self.assertEqual(self.decision(d)['reason'],'toolchain_contract_failed')

class ContractTests(unittest.TestCase):
 def test_bad_candidate_is_rejected_and_good_one_passes(self):
  import tempfile,json
  from pathlib import Path
  from types import SimpleNamespace
  from unittest.mock import patch
  from rasbot.toolchain_contracts import check
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);runtime=SimpleNamespace(repo=root/'repo',store=SimpleNamespace(root=root))
   manifest={'execution_root':str(root),'execution_files':{'scripts/verify_schema.py':'changed'}}
   (root/'suite.json').write_text('[{"inputs":[1]}]')
   good=[True,False,False,False,False,False]
   for candidate,expected in [(good,True),([True]*6,False)]:
    results=[SimpleNamespace(returncode=0,stdout=json.dumps(v)) for v in [good,candidate]]
    with patch('rasbot.toolchain_contracts.subprocess.run',side_effect=results),patch('rasbot.toolchain_contracts.intact',return_value=True),patch('rasbot.toolchain_contracts.references_intact',return_value=True):
     self.assertEqual(check(runtime,manifest,root/'suite.json')['passed'],expected)

class ContractPlanTests(unittest.TestCase):
 def test_mapping_does_not_claim_semantic_validation(self):
  from rasbot.toolchain_contracts import contract_plan
  plan=contract_plan(['scripts/create_workspace.py','prompts/prompt_template.md','openskill/02_run_atk_verification.md'])
  self.assertIn('preparation_asset_equivalence',plan['execution_checks'])
  self.assertIn('schema_positive_negative',plan['local_probes'])
  self.assertIn('hardware_workflow_effect',plan['not_validated'])
  self.assertIn('conversion_semantics',plan['not_validated'])
 def test_untrusted_evidence_precedes_other_candidate_failure(self):
  t=QualityConstraintTests();d=t.data()
  d[1]['toolchain_contract']={'passed':False,'status':'checked'}
  d[-1]['toolchain_contract']={'passed':False,'status':'error','reason':'budget_exhausted'}
  self.assertEqual(t.decision(d)['state'],'inconclusive')
