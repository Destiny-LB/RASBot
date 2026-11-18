import unittest
from rasbot.risk_profile import evaluate,consistency,diversity
from rasbot.meta_promotion import decide
from rasbot.meta_evaluation import WEIGHTS
from rasbot.evaluation_policy import EVALUATOR_ID
from rasbot.evaluation_budget import confirmation_plan
from rasbot.campaigns import select_next
from unittest.mock import patch
import test_evolution
from rasbot.campaigns import Campaigns
from datetime import datetime,timezone,timedelta
import test_agent_runtime
import json,subprocess
from pathlib import Path

class RiskTests(unittest.TestCase):
 def case(self,values,**extra):
  return dict(id=1,inputs=[dict(name='x',type='tensor',shape=[33],dtype='fp32',range_values=values)],**extra)
 def test_claims_and_wide_ranges_do_not_establish_near_zero(self):
  a=evaluate('ops-aclnnExpm1',[self.case([-100,100],generate_intent='near zero fully covered')])
  self.assertFalse(next(x for x in a['checks'] if x['id']=='near_zero')['hit'])
  b=evaluate('ops-aclnnExpm1',[self.case([-1e-7,1e-7])])
  self.assertTrue(next(x for x in b['checks'] if x['id']=='near_zero')['hit'])
 def test_special_values_are_valid_distinct_specs(self):
  a=self.case({'name':'constant','value':float('inf')});b=self.case({'name':'constant','value':float('-inf')})
  self.assertEqual(diversity([a,a,b]),2/3)
  n=self.case({'name':'constant','value':float('nan')});self.assertEqual(diversity([n,n]),.5)
 def test_constant_and_shape_probes(self):
  r=evaluate('ops-aclnnExpm1',[self.case({'name':'constant','value':1e-7})])
  self.assertTrue(next(x for x in r['checks'] if x['id']=='near_zero')['hit'])
 def test_unsupported_is_not_zero(self):
  self.assertIsNone(evaluate('other',[])['score'])
 def test_invalid_domain_and_unknown_distribution_no_credit(self):
  for v in ([-2,-1],{'name':'nd','mean':-.999,'std':.0001}):
   r=evaluate('ops-aclnnLog1p',[self.case(v)])
   self.assertFalse(next(x for x in r['checks'] if x['id']=='above_minus_one')['hit'])
 def test_consistency_partial_and_duplicate_ids(self):
  a=dict(id=1,generate_intent='test',trigger_library_ref=['CODE-x: reason'])
  b=dict(id=2,generate_intent='',trigger_library_ref=[])
  ledger={'triggers':[],'code_triggers':{'x':{}}}
  self.assertEqual(consistency([a,b],ledger),.5)
  self.assertEqual(consistency([a,a],ledger),0)
