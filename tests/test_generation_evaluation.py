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

class DecisionTests(unittest.TestCase):
 def data(self):
  rows=[]
  for rep in (0,1):
   for role in ('baseline','candidate'):
    m=dict.fromkeys(WEIGHTS,1.0);m['risk_coverage']=.5 if role=='baseline' else .75
    rows.append(dict(slug='x',replicate=rep,role=role,passed=True,comparable=True,meta_evaluation={'evaluator_version':EVALUATOR_ID,'validity':{'eligible':True},'quality':{'metrics':m}}))
  return rows
 def test_new_risk_gain_requires_confirmation(self):
  d=self.data();p={'scoring_version':'meta-generation-v3'}
  self.assertEqual(decide(d[:2],['x'],p)['state'],'confirming')
  self.assertEqual(decide(d,['x'],p)['basis'],'generation_design_quality')
 def test_regression_retains_all_search_evidence(self):
  d=self.data();d[-1]['meta_evaluation']['quality']['metrics']['diversity']=.9
  result=decide(d,['x'],{'scoring_version':'meta-generation-v3'})
  self.assertEqual(result['state'],'promoted');self.assertEqual(len(result['pairs']),2)
 def test_missing_risk_blocks(self):
  d=self.data();d[-1]['meta_evaluation']['quality']['metrics']['risk_coverage']=None
  self.assertEqual(decide(d,['x'],{'scoring_version':'meta-generation-v3'})['state'],'inconclusive')
 def test_quality_selection_over_old_passes(self):
  def run(name,gain,passes):
   return dict(id=name,candidate=name,baseline='b',state='rejected',trials=[{'comparable':True}],policy={'scoring_version':'meta-generation-v3'},scores={'candidate_passes':passes},decision={'pairs':[{'gain':gain}], 'policy_version':'meta-generation-v3'})
  self.assertEqual(select_next([run('quality',5,0),run('old',1,9)],'b','meta-generation-v3')['parent'],'quality')
 def test_budget_uses_symmetric_observation_cap(self):
  r={'slugs':['a','b'],'policy':{'trial_seconds':1320,'overhead_seconds':720,'scoring_version':'meta-generation-v3'},'trials':[{'duration_seconds':300}]*4}
  p=confirmation_plan(r);self.assertEqual(p['trial_seconds'],570);self.assertEqual(p['required_seconds'],3000)
  r['trials'][0]={'duration_seconds':None};self.assertEqual(confirmation_plan(r)['trial_seconds'],1320)


class GenerationEvaluationIntegrationTests(unittest.TestCase):
 def setUp(self):
  test_evolution.EvolutionTests.setUp(self)
  support=patch('rasbot.risk_profile.supported',return_value=True);support.start();self.addCleanup(support.stop)
 def test_frozen_score_and_two_round_adoption(self):
  adapter=self.runtime.registry.get('precision');policy=dict(adapter.policy(),scoring_version='meta-generation-v3');adapter.policy=lambda:dict(policy)
  run=test_evolution.EvolutionTests.proposal(self,self.evo.create([self.task],['sample','holdout'],self.model))
  def evaluation(task,*args,**kwargs):
   m=dict.fromkeys(WEIGHTS,1.0);m['risk_coverage']=.8 if task['version']==run['candidate'] else .5
   return dict(evaluator_version=EVALUATOR_ID,validity={'eligible':True},quality={'metrics':m},artifact_sha256={'suite':'fixed'})
  with patch('rasbot.meta_evaluation.evaluate',side_effect=evaluation):
   for round in range(2):
    for t in run['trials']:
     if 'passed' not in t:self.runtime.store.transition(t['task_id'],'queued','generated',{'validation':{'passed':True}})
    for _ in range(5):run=self.evo.tick(run['id'])
    self.assertEqual(run['state'],'evaluating' if round==0 else 'promoted')
    if round==0:stamp=run['trials'][0]['meta_evaluation']['captured_at']
   self.assertEqual(run['trials'][0]['meta_evaluation']['captured_at'],stamp)
   self.assertEqual(run['decision']['basis'],'generation_design_quality')


class ProfilePreflightTests(unittest.TestCase):
 setUp=test_evolution.EvolutionTests.setUp
 def test_tasks_without_profile_can_start(self):
  adapter=self.runtime.registry.get('precision');policy=dict(adapter.policy(),scoring_version='meta-generation-v3');adapter.policy=lambda:dict(policy)
  self.risk_support.stop()
  calls=len(self.client.calls)
  run=self.evo.create([self.task],['sample','holdout'],self.model)
  self.assertEqual(run['slugs'],['sample','holdout'])
  self.assertEqual(len(self.evo.list()),1)
