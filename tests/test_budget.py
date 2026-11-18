import unittest
from datetime import datetime,timezone,timedelta
import test_evolution
class BudgetTests(unittest.TestCase):
 setUp=test_evolution.EvolutionTests.setUp
 def pending(self):
  r=test_evolution.EvolutionTests.proposal(self,self.evo.create([self.task],['sample','holdout'],self.model))
  for t in r['trials']:
   t.update(passed=True,comparable=True,terminal_state='generated',duration_seconds=100 if t['role']=='baseline' else 70)
  r['deadline']=(datetime.now(timezone.utc)+timedelta(seconds=20)).isoformat()
  self.evo.save(r)
  # Budget scheduling test: quality scorer requests confirmation.
  with unittest.mock.patch('rasbot.evolution.decide',return_value={'state':'confirming','reason':'quality_confirmation_required'}):
   return self.evo.tick(r['id'])
 def test_first_pair_has_full_budget(self):
  r=self.evo.create([self.task],['sample','holdout'],self.model,development=True)
  self.assertEqual(r['policy']['trial_seconds'],1320)
 def test_resume_without_redevelopment(self):
  r=self.pending();self.assertTrue(r['decision']['confirmation_required'])
  with self.assertRaises(ValueError):self.evo.confirm(r['id'],30)
  resumed=self.evo.confirm(r['id'],120)
  self.assertEqual(resumed['candidate'],r['candidate'])
  self.assertEqual(resumed['state'],'evaluating')
  self.assertEqual([t['role'] for t in resumed['trials'][4:]],['candidate','baseline']*2)
  self.assertEqual(len(resumed['budget_extensions']),1)
  with self.assertRaises(ValueError):self.evo.confirm(r['id'],120)
 def test_asset_change_blocks_resume(self):
  r=self.pending()
  with unittest.mock.patch.object(self.evo,'unchanged',return_value=False):
   with self.assertRaises(ValueError):self.evo.confirm(r['id'],120)
