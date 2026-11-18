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

class CampaignConfirmationTests(unittest.TestCase):
 setUp=test_evolution.EvolutionTests.setUp
 def test_confirm_within_campaign_budget_no_new_candidate(self):
  campaign=Campaigns(self.evo)
  item=campaign.create('confirm',max_rounds=2,source_ids=[self.task],slugs=['sample','holdout'],model=self.model)
  item=campaign.tick(item['id']);run=self.evo.get(item['current_run']);run['development_enabled']=False;self.evo.save(run)
  run=test_evolution.EvolutionTests.proposal(self,run)
  for t in run['trials']:t.update(passed=True,comparable=True,terminal_state='generated',duration_seconds=100 if t['role']=='baseline' else 70)
  run['deadline']=(datetime.now(timezone.utc)+timedelta(seconds=20)).isoformat();self.evo.save(run)
  with patch('rasbot.evolution.decide',return_value={'state':'confirming','reason':'quality_confirmation_required'}):
   run=self.evo.tick(run['id'])
  self.assertTrue(run['decision']['confirmation_required'])
  item=campaign.tick(item['id']);resumed=self.evo.get(run['id'])
  self.assertEqual(item['current_run'],run['id']);self.assertEqual(len(self.evo.list()),1)
  self.assertEqual(resumed['state'],'evaluating');self.assertEqual(len(resumed['trials']),8)
  self.assertLessEqual(resumed['deadline'],item['deadline'])
  campaign.tick(item['id']);self.assertEqual(len(self.evo.get(run['id'])['budget_extensions']),1)
