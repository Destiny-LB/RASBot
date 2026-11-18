import json,tempfile,unittest
from pathlib import Path
from rasbot.core import Store
from rasbot.runtime import Runtime
from rasbot.precision_package import CORE,SCOPE,snapshot,editable,apply_changes,materialize,materialize_references,intact,references_intact
from rasbot.precision_development import collect
from rasbot.agent_runtime import bundle

PREP='''import argparse,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-dir');p.add_argument('--workspace-root');a=p.parse_args()
w=Path(a.workspace_root)/'workspace';shutil.copytree(a.source_dir,w);print(w.resolve())
'''
class ScopeTests(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name);self.repo=self.root/'repo'
  for name in CORE:
   p=self.repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('pass\n' if name.endswith('.py') else 'original '+name,encoding='utf8')
  (self.repo/'scripts/create_workspace.py').write_text(PREP)
  (self.repo/'prompts/generate_prompt__repo_version_DS_aclnnName.py').write_text("from pathlib import Path\nprint('VERSIONED GUIDANCE '+(Path(__file__).parent/'prompt_template.md').read_text())\n")
  task=self.repo/'tasks/sample'
  for name,value in {'01_generate/src/kernel.cpp':'source','01_generate/interfaces/schema.md':'fixed schema','01_generate/submission/test_suite.template.json':'[]','02_atk_run/atk_runnable/run.py':'pass','02_atk_run/atk_run_config.json':'{"max_cases":1000}'}.items():
   p=task/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
  (self.repo/'prompts/sample.md').write_text('FIXED TASK FACTS')
  self.runtime=Runtime(Store(self.root/'state'),self.repo)
 def version(self,changes=None):
  files=apply_changes(snapshot(self.repo),changes or {})
  return self.runtime.store.version({'agent_id':'precision','execution_scope':SCOPE,'execution_files':files})
 def test_scope_is_13_and_excludes_infrastructure(self):
  self.assertEqual(len(CORE),13);self.assertEqual(set(snapshot(self.repo)),CORE)
  for name in ('atk_queue/core.py','tasks/a/config.json','ops/run.sh','offline/image.tar','scripts/verify_precision_report.py','openskill/04_validate_ground_truth.md','scripts/new_root.py'):
   self.assertFalse(editable(name))
   with self.assertRaises(ValueError):apply_changes({}, {name:'pass'})
 def test_auxiliary_delete_and_core_protection(self):
  files=snapshot(self.repo);files=apply_changes(files,{'scripts/common/__init__.py':'','scripts/common/helper.py':'x=1','prompts/fragments/notes.md':'notes'})
  package=self.root/'package';materialize(package,files)
  (package/'scripts/common/helper.py').unlink()
  self.assertNotIn('scripts/common/helper.py',collect(package,list(files),{}))
  with self.assertRaises(ValueError):apply_changes(files,{'openskill/02_run_atk_verification.md':None})
 def test_candidate_docs_are_not_fixed_references(self):
  files=apply_changes(snapshot(self.repo),{'docs/trigger_library.md':'candidate risk knowledge'})
  package=self.root/'package';expected=materialize(package,files);refs=materialize_references(package,self.repo,'sample')
  self.assertNotIn('docs/trigger_library.md',refs);self.assertTrue(intact(package,expected));self.assertTrue(references_intact(package,refs))
  (package/'docs/trigger_library.md').write_text('edited')
  self.assertFalse(intact(package,expected));self.assertEqual((self.repo/'docs/trigger_library.md').read_text(),'original docs/trigger_library.md')
 def test_candidate_preparation_prompt_and_all_skills_loaded(self):
  code=PREP+"(w/'candidate-proof.txt').write_text('candidate prepared')\n"
  version=self.version({'scripts/create_workspace.py':code,'prompts/prompt_template.md':'NEW TEMPLATE','openskill/02_run_atk_verification.md':'NEW STEP TWO'})
  identity=self.runtime.create('precision','sample',version);task=self.runtime.advance(identity)
  self.assertEqual(task['state'],'prepared',task['result']);self.assertTrue(task['result']['preparation_evidence']['passed'])
  self.assertTrue((Path(task['result']['workspace'])/'candidate-proof.txt').exists())
  manifest=bundle(self.runtime,identity,'opencode',transport='http')
  text=Path(manifest['instruction']).read_text(encoding='utf8')
  self.assertIn('NEW TEMPLATE',text);self.assertIn('NEW STEP TWO',text);self.assertIn('FIXED TASK FACTS',text)
  self.assertEqual(manifest['validated_workflow_stages'],['01_generate'])
  self.assertEqual(len([p for p in manifest['execution_files'] if p.startswith('openskill/')]),4)
 def test_preparation_cannot_reduce_fixed_case_requirement(self):
  code=PREP+"(w/'02_atk_run/atk_run_config.json').write_text('{\"max_cases\":1}')\n"
  task=self.runtime.advance(self.runtime.create('precision','sample',self.version({'scripts/create_workspace.py':code})))
  self.assertEqual(task['state'],'failed');self.assertIn('fixed task assets',task['result']['error'])
 def test_prompt_cannot_mutate_frozen_package(self):
  code="from pathlib import Path\n(Path(__file__).parent/'prompt_template.md').write_text('mutated')\nprint('guidance')\n"
  identity=self.runtime.create('precision','sample',self.version({'prompts/generate_prompt__repo_version_DS_aclnnName.py':code}))
  self.assertEqual(self.runtime.advance(identity)['state'],'prepared')
  with self.assertRaisesRegex(ValueError,'mutated frozen'):bundle(self.runtime,identity,'opencode',transport='http')

 def test_old_baseline_migrates_without_changing_adoption(self):
  from rasbot.evolution import Evolution
  from rasbot.opencode_service import Service
  from test_service import FakeClient
  (self.repo/'tasks/holdout').mkdir()
  (self.repo/'prompts/holdout.md').write_text('holdout')
  adapter=self.runtime.registry.get('precision')
  policy=dict(adapter.policy(),scoring_version='meta-generation-v3')
  adapter.policy=lambda:dict(policy)
  original=self.runtime.adopted('precision')
  identity=self.runtime.create('precision','sample')
  self.runtime.store.transition(identity,'queued','generated',{'validation':{'passed':True}})
  from unittest.mock import patch
  support=patch('rasbot.risk_profile.supported',return_value=True);support.start();self.addCleanup(support.stop)
  run=Evolution(self.runtime,Service(self.runtime,FakeClient())).create([identity],['sample','holdout'],{'id':'fixed','providerID':'test'})
  self.assertEqual(run['baseline_source'],original)
  self.assertEqual(self.runtime.adopted('precision'),original)
  self.assertNotEqual(run['baseline'],original)
  with self.runtime.store.connect() as c:
   row=c.execute('SELECT parent,body FROM versions WHERE id=?',(run['baseline'],)).fetchone()
  body=json.loads(row[1]);self.assertEqual(row[0],original)
  self.assertEqual(body['execution_scope'],SCOPE)
  self.assertEqual(set(body['execution_files']),CORE)
