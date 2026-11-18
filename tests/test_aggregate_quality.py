import copy,unittest
from rasbot.meta_promotion import decide
from rasbot.meta_evaluation import WEIGHTS
from rasbot.evaluation_policy import EVALUATOR_ID
from rasbot.risk_profile import evaluate
class AggregateTests(unittest.TestCase):
 def data(self):
  return [dict(slug=s,replicate=r,role=role,passed=True,comparable=True,meta_evaluation={'evaluator_version':EVALUATOR_ID,'validity':{'eligible':True},'quality':{'metrics':dict(valid_rules=1,deliverables=1,risk_coverage=None,evidence_consistency=1,diversity=.5 if role=='baseline' else .8)}}) for r in (0,1) for s in ('general-a','general-b') for role in ('baseline','candidate')]
 def test_general_tasks_promote_without_fabricated_risk(self):
  d=decide(self.data(),['general-a','general-b'],{})
  self.assertEqual(d['state'],'promoted');self.assertEqual(d['measured_maximum'],70)
  self.assertEqual(len(d['unmeasured_risk_tasks']),2)
 def test_one_task_soft_regression_allowed_when_round_gain_positive(self):
  rows=self.data()
  for t in rows:
   if t['slug']=='general-a' and t['role']=='candidate':t['meta_evaluation']['quality']['metrics']['diversity']=.4
  d=decide(rows,['general-a','general-b'],{})
  self.assertEqual(d['state'],'promoted');self.assertEqual(len(d['regressions']),2)
 def test_hard_gate_cannot_be_compensated(self):
  rows=self.data();rows[-1]['passed']=False
  self.assertEqual(decide(rows,['general-a','general-b'],{})['reason'],'candidate_acceptance_failed')
 def test_missing_measurement_cannot_shrink_comparison_scope(self):
  rows=self.data();rows[-1]['meta_evaluation']['quality']['metrics']['risk_coverage']=.5
  self.assertEqual(decide(rows,['general-a','general-b'],{})['state'],'inconclusive')
 def test_known_profile_missing_is_not_excluded(self):
  rows=self.data()
  for t in rows:t['slug']='ops-aclnnExpm1' if t['slug']=='general-a' else 'general-b'
  self.assertEqual(decide(rows,['ops-aclnnExpm1','general-b'],{})['state'],'inconclusive')
 def test_unknown_distribution_has_explicit_uncertainty(self):
  case={'inputs':[{'type':'tensor','shape':[33],'dtype':'float32','range_values':{'name':'nd','mean':0,'std':1}}]}
  risk=evaluate('ops-aclnnExpm1',[case])
  self.assertEqual(risk['status'],'partially_measured')
  self.assertTrue(next(c for c in risk['checks'] if c['id']=='fp32')['hit'])
  self.assertEqual(next(c for c in risk['checks'] if c['id']=='near_zero')['status'],'not_measured')
  self.assertGreater(risk['possible_range'][1],risk['score'])
 def test_constant_list_is_equivalent(self):
  a={'inputs':[{'type':'tensor','shape':[33],'dtype':'float16','range_values':[{'name':'constant','value':1e-7}]}]}
  r=evaluate('ops-aclnnExpm1',[a]);self.assertTrue(next(c for c in r['checks'] if c['id']=='near_zero')['hit'])
