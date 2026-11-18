import unittest
from rasbot.meta_promotion import decide
from rasbot.evaluation_policy import EVALUATOR_ID as VERSION
class MetaPromotionTests(unittest.TestCase):
 def data(self, rounds=2):
  return [dict(slug='a',replicate=r,role=role,passed=True,comparable=True,meta_evaluation=dict(evaluator_version=VERSION,validity={'eligible':True},quality={'metrics':dict(valid_rules=1,risk_coverage=1,deliverables=1,evidence_consistency=1,diversity=.5 if role=='baseline' else .8)})) for r in range(rounds) for role in ('baseline','candidate')]
 def test_confirmation(self):
  self.assertEqual(decide(self.data(1),['a'],{})['state'],'confirming')
  self.assertEqual(decide(self.data(),['a'],{})['state'],'promoted')
 def test_missing_and_regression(self):
  for v,state in [(None,'inconclusive'),(.4,'rejected'),(.5,'rejected')]:
   d=self.data();d[-1]['meta_evaluation']['quality']['metrics']['diversity']=v
   self.assertEqual(decide(d,['a'],{})['state'],state)
 def test_integrity(self):
  d=self.data();d[-1]['meta_evaluation']['validity']['eligible']=False
  self.assertEqual(decide(d,['a'],{})['state'],'inconclusive')
 def test_missing_pair(self):
  self.assertEqual(decide(self.data()[:-1],['a'],{})['state'],'inconclusive')

from unittest.mock import patch
import test_evolution
class MetaIntegrationTests(unittest.TestCase):
 setUp=test_evolution.EvolutionTests.setUp
 def test_new_policy_confirmation_and_adoption(self):
  adapter=self.runtime.registry.get('precision')
  policy=dict(adapter.policy(),scoring_version='meta-generation-v3')
  adapter.policy=lambda:dict(policy)
  support=patch('rasbot.risk_profile.supported',return_value=True);support.start();self.addCleanup(support.stop)
  run=test_evolution.EvolutionTests.proposal(self,self.evo.create([self.task],['sample','holdout'],self.model))
  def evaluation(task,*args,**kwargs):
   candidate=task['version']==run['candidate']
   return dict(evaluator_version=VERSION,validity={'eligible':True},quality={'metrics':dict(valid_rules=1,risk_coverage=1,deliverables=1,evidence_consistency=1,diversity=.9 if candidate else .5)})
  with patch('rasbot.meta_evaluation.evaluate',side_effect=evaluation):
   for round in range(2):
    for t in run['trials']:
     if 'passed' not in t:
      self.runtime.store.transition(t['task_id'],'queued','generated',{'validation':{'passed':True}})
    for _ in range(5):run=self.evo.tick(run['id'])
    self.assertEqual(run['state'],'evaluating' if round==0 else 'promoted')
  self.assertEqual(run['decision']['basis'],'generation_design_quality')
  self.assertTrue(all('meta_evaluation' in t for t in run['trials']))
  task=self.runtime.create('precision','sample')
  self.assertEqual(self.runtime.store.get(task)['version'],run['candidate'])
