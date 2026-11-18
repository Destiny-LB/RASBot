import hashlib,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from rasbot.toolchain_contracts import check

CODE='def validate_atk_structure(x):\n return ([] if isinstance(x,list) and x and isinstance(x[0],dict) and x[0].get("inputs") else ["invalid"],[])\n'
class ToolchainIntegrityTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
  self.repo=self.root/'repo';self.package=self.root/'package';self.ws=self.root/'workspace';self.ws.mkdir()
  for p in (self.repo/'scripts',self.package/'scripts'):p.mkdir(parents=True)
  (self.repo/'scripts/verify_schema.py').write_text(CODE)
  self.suite=self.ws/'suite.json';self.suite.write_text('[{"id":1,"inputs":[1]}]')
  self.runtime=SimpleNamespace(repo=self.repo,store=SimpleNamespace(root=self.root))
 def run_probe(self,code):
  p=self.package/'scripts/verify_schema.py';p.write_text(code)
  self.manifest={'execution_root':str(self.package),'workspace':str(self.ws),'execution_files':{'scripts/verify_schema.py':hashlib.sha256(p.read_bytes()).hexdigest()}}
  return check(self.runtime,self.manifest,self.suite)
 def test_isolated_input_mutation_rejected(self):
  r=self.run_probe('from pathlib import Path\nimport sys\nPath(sys.argv[2]).write_text(\'[ {"id":999,"inputs":[1]} ]\')\n'+CODE)
  self.assertFalse(r['passed']);self.assertIn('isolated input',r['error'])
  self.assertEqual(json.loads(self.suite.read_text())[0]['id'],1)
 def test_formal_artifact_mutation_rejected(self):
  r=self.run_probe('from pathlib import Path\nPath('+repr(str(self.suite))+').write_text(\'[ {"id":999,"inputs":[1]} ]\')\n'+CODE)
  self.assertFalse(r['passed']);self.assertEqual(r['reason'],'integrity_violation')
 def test_trusted_script_mutation_rejected(self):
  r=self.run_probe('from pathlib import Path\nPath('+repr(str(self.repo/'scripts/verify_schema.py'))+').write_text("changed")\n'+CODE)
  self.assertEqual(r['reason'],'integrity_violation')
 def test_good_probe_passes(self):self.assertTrue(self.run_probe(CODE)['passed'])
 def test_shared_probe_deadline(self):
  self.run_probe(CODE)
  clock=[100.];self.manifest['validation_deadline']=105.
  timeouts=[]
  def run(*args,**kwargs):
   timeouts.append(kwargs['timeout']);clock[0]+=3
   return SimpleNamespace(returncode=0,stdout='[true,false,false,false,false,false]')
  with patch('time.monotonic',side_effect=lambda:clock[0]),patch('rasbot.toolchain_contracts.subprocess.run',side_effect=run):
   r=check(self.runtime,self.manifest,self.suite)
  self.assertEqual(timeouts,[5,2]);self.assertEqual(r['reason'],'budget_exhausted')
 def test_expired_development_does_not_dispatch(self):
  from rasbot.development_checks import check as development_check
  runtime=SimpleNamespace(registry=SimpleNamespace(get=lambda _:self.fail('dispatched expired validation')))
  r=development_check(runtime,'precision',{'workspace':str(self.ws),'root':str(self.root),'protected':{}},0)
  self.assertFalse(r['passed']);self.assertEqual(r['reason'],'budget_exhausted')

import test_evolution
class PipelineTimingTests(unittest.TestCase):
 setUp=test_evolution.EvolutionTests.setUp
 def test_start_is_saved_before_prepare_and_used_for_elapsed(self):
  r=test_evolution.EvolutionTests.proposal(self,self.evo.create([self.task],['sample','holdout'],self.model))
  identity=r['trials'][0]['task_id']
  original=self.runtime.advance
  def advance(task):
   persisted=self.evo.get(r['id'])['trials'][0]
   self.assertIn('pipeline_started',persisted)
   return original(task)
  with patch.object(self.runtime,'advance',side_effect=advance):self.evo.tick(r['id'])
  r=self.evo.get(r['id']);trial=r['trials'][0]
  from datetime import datetime,timedelta
  trial['pipeline_started']=(datetime.fromisoformat(trial['pipeline_started'])-timedelta(seconds=90)).isoformat()
  trial['started']=(datetime.fromisoformat(trial['pipeline_started'])+timedelta(seconds=80)).isoformat();self.evo.save(r)
  self.runtime.store.transition(identity,'prepared','generated',{'validation':{'passed':True}})
  r=self.evo.tick(r['id']);trial=r['trials'][0]
  self.assertGreater(trial['duration_seconds']-trial['execution_seconds'],79)
