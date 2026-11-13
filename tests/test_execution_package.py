import json
from pathlib import Path
import unittest
from unittest.mock import patch

from rasbot.precision_package import apply_changes, materialize, intact
from rasbot.agent_runtime import bundle, validate
import test_evolution
import test_agent_runtime


class PackageTests(unittest.TestCase):
    def test_invalid_paths_and_python_rejected(self):
        for name, code in [('scripts/../escape.py', 'x=1'), ('scripts\\escape.py', 'x=1'),
                           ('C:/escape.py', 'x=1'), ('scripts/create_workspace.py', 'x=1'),
                           ('tasks/a.py', 'x=1'), ('scripts/a.py', 'def broken('),
                           ('openskill/02_atk_run.md', 'changed')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                apply_changes({}, {name: code})

    def test_materialization_and_tamper_detection(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / 'package'
            expected = materialize(target, {'scripts/helper.py': 'print(1)\n'})
            self.assertTrue(intact(target, expected))
            (target / 'scripts/helper.py').write_text('print(2)')
            self.assertFalse(intact(target, expected))


class ExecutionSourceTests(unittest.TestCase):
    setUp = test_agent_runtime.AgentTests.setUp

    def candidate_bundle(self):
        with self.runtime.store.connect() as c:
            parent = json.loads(c.execute('SELECT body FROM versions WHERE id=?', (self.runtime.baseline,)).fetchone()[0])
        parent['execution_files'] = {'openskill/01_generate_test_rules.md': 'Candidate Skill',
                                     'scripts/helper.py': 'print("candidate")\n'}
        version = self.runtime.store.version(parent, self.runtime.baseline)
        with self.runtime.store.connect() as c:
            c.execute('UPDATE tasks SET version=? WHERE id=?', (version, self.task))
        return bundle(self.runtime, self.task, 'opencode', transport='http')

    def test_candidate_skill_and_script_are_used_without_modifying_repo(self):
        m = self.candidate_bundle()
        text = Path(m['instruction']).read_text(encoding='utf-8')
        self.assertIn('Candidate Skill', text)
        self.assertIn('EXECUTION_ROOT=', text)
        self.assertEqual((Path(m['execution_root']) / 'scripts/helper.py').read_text(), 'print("candidate")\n')
        self.assertFalse((self.repo / 'scripts/helper.py').exists())

    def test_runtime_source_edits_rejected(self):
        m = self.candidate_bundle()
        (Path(m['execution_root']) / 'scripts/helper.py').write_text('print("edited")')
        self.assertEqual(validate(self.runtime, m)['reason'], 'Versioned execution sources changed during trial')

    def test_candidate_script_cannot_replace_independent_gate(self):
        m = self.candidate_bundle()
        (self.ws / '02_atk_run').mkdir()
        (self.ws / '02_atk_run/atk_run_config.json').write_text('{"max_cases": 1}')
        sub = self.ws / '01_generate/submission'; sub.mkdir()
        (sub / 'test_suite.json').write_text('[{"inputs": {"x": 1}}]')
        report = self.ws / '01_generate/report'; report.mkdir()
        for name in ('test_rule_design.md', 'trigger_coverage.json', 'trigger_library.md'):
            (report / name).write_text('evidence')
        # Configuration was created after bundle; refresh only task protection for this fixture.
        from rasbot.agent_runtime import protected_digest
        m['protected'] = protected_digest(self.ws)
        with patch('rasbot.agent_runtime.subprocess.run') as process:
            process.return_value.returncode = 1
            process.return_value.stdout = 'invalid'
            process.return_value.stderr = ''
            self.assertFalse(validate(self.runtime, m)['passed'])
            self.assertEqual(Path(process.call_args.args[0][3]).resolve(), (self.repo / 'scripts/prepare_atk_submission.py').resolve())


class FileEvolutionTests(unittest.TestCase):
    setUp = test_evolution.EvolutionTests.setUp

    def test_file_proposal_is_inherited_evaluated_and_auditable(self):
        (self.repo / 'scripts').mkdir()
        (self.repo / 'scripts/helper.py').write_text('print("base")\n')
        run = self.evo.create([self.task], ['sample', 'holdout'], self.model)
        self.evo.tick(run['id'])
        proposal = {'diagnosis': '修复脚本', 'agent_instructions': '执行版本化脚本',
                    'meta_evaluation': '保留固定验收', 'file_changes': {'scripts/helper.py': 'print("candidate")\n'}}
        original = self.client.request
        self.client.request = lambda method, path, body=None: ({'data': [
            {'type': 'assistant', 'content': [{'type': 'text', 'text': json.dumps(proposal)}]},
            {'type': 'idle', 'outcome': 'succeeded'}]} if path.endswith('/context') else original(method, path, body))
        run = self.evo.tick(run['id'])
        self.assertEqual(run['state'], 'evaluating')
        with self.runtime.store.connect() as c:
            read = lambda v: json.loads(c.execute('SELECT body FROM versions WHERE id=?', (v,)).fetchone()[0])
            self.assertEqual(read(run['baseline'])['execution_files']['scripts/helper.py'], 'print("base")\n')
            self.assertEqual(read(run['candidate'])['execution_files']['scripts/helper.py'], 'print("candidate")\n')
        from rasbot.version_audit import audit_versions
        rows = {v['id']: v for v in audit_versions(self.runtime.store, run['baseline'], [run])}
        self.assertIn('+print("candidate")', rows[run['candidate']]['file_diffs'][0]['diff'])
        self.assertEqual((self.repo / 'scripts/helper.py').read_text(), 'print("base")\n')
        run = test_evolution.EvolutionTests.finish(self, run, 1, 2)
        self.assertEqual(run['state'], 'promoted')
        self.assertEqual(self.runtime.store.get(self.runtime.create('precision', 'sample'))['version'], run['candidate'])
        self.evo.rollback(run['id'])
        self.assertEqual(self.runtime.store.get(self.runtime.create('precision', 'sample'))['version'], run['baseline'])
