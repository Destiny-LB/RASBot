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

class DevelopmentPolicyTests(unittest.TestCase):
 def test_only_measured_quality_warnings_are_nonblocking(self):
  from rasbot.precision_warnings import classify,apply_quality_policy
  warnings=classify("WARNING: duplicate case signature 1\nWARNING: coverage mismatch\nWARNING: canonical sha256 changed\nWARNING: unknown condition")
  self.assertEqual([w['blocking'] for w in warnings],[True]*4)
  changed=apply_quality_policy(warnings,'meta-generation-v3')
  self.assertEqual([w['blocking'] for w in changed],[False,False,True,True])
  self.assertEqual([w['blocking'] for w in warnings],[True]*4)
  self.assertTrue(apply_quality_policy(classify('WARNING: TRIGGER-x canonical sha256 changed'),'meta-generation-v3')[0]['blocking'])


class DevelopmentMaterializationTests(unittest.TestCase):
 setUp=test_agent_runtime.AgentTests.setUp
 def test_duplicates_continue_to_independent_materialization(self):
  from rasbot.agent_runtime import validate,protected_digest
  atk=self.ws/'02_atk_run';atk.mkdir();(atk/'atk_run_config.json').write_text('{"max_cases":2}')
  folder=self.ws/'01_generate/submission';folder.mkdir()
  (folder/'test_suite.json').write_text(json.dumps([{'id':i,'inputs':[{'shape':[1]}]} for i in range(2)]))
  report=self.ws/'01_generate/report';report.mkdir()
  for name in ('constraints.md','test_rule_design.md','trigger_coverage.json','trigger_library.md'):(report/name).write_text('present')
  manifest={'workspace':str(self.ws),'attempt':str(self.ws),'protected':protected_digest(self.ws),'quality_policy':'meta-generation-v3'}
  for count,warning,expected in [(2,'WARNING: duplicate case signature',True),(1,'',False),(2,'WARNING: unknown',False)]:
   def materialize(args,**kwargs):
    Path(args[args.index('-o')+1]).write_text(json.dumps([{}]*count))
    return subprocess.CompletedProcess(args,0,stdout=warning,stderr='')
   with patch('rasbot.agent_runtime.subprocess.run',side_effect=materialize) as process:
    result=validate(self.runtime,manifest)
   self.assertTrue(process.called);self.assertEqual(result['passed'],expected)


class FormalGatePolicyTests(unittest.TestCase):
 setUp=test_evolution.EvolutionTests.setUp
 def test_fixed_meta_policy_is_applied_before_trial_dispatch(self):
  run=test_evolution.EvolutionTests.proposal(self,self.evo.create([self.task],['sample','holdout'],self.model))
  run['policy']['scoring_version']='meta-generation-v3';self.evo.save(run)
  trial=run['trials'][0];attempt=Path(run['root'])/'formal-attempt';attempt.mkdir()
  result={'agent_manifest':{'attempt':str(attempt)},'session_id':'s','engine_url':self.client.url}
  self.runtime.store.transition(trial['task_id'],'queued','panel_ready',result)
  with patch.object(self.evo.engine,'panel_send'):
   self.evo.tick(run['id'])
  task=self.runtime.store.get(trial['task_id'])
  self.assertEqual(task['result']['agent_manifest']['quality_policy'],'meta-generation-v3')
  self.assertEqual(json.loads((attempt/'manifest.json').read_text(encoding='utf8'))['quality_policy'],'meta-generation-v3')
