"""Agent registry and domain adapters. Core storage uses domain as a legacy agent key."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

class PrecisionAgent:
    id = 'precision'
    name = '精度测试 Agent'
    available = True
    execution = True
    evolution = True
    file_evolution = True
    task_label = '算子任务'
    description = '生成精度测试用例并离线校验；硬件执行尚未接入。'
    harness_id = 'precision-generation'
    evaluator_id = 'generation-gate-v1'
    evolution_goal = '提高正式用例生成合规性'
    def __init__(self, repo): self.repo = repo
    def catalog(self):
        directory = self.repo / 'tasks'
        return sorted(p.name for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []
    def title(self, key):
        if '-aclnn' in key:
            prefix, name = key.split('-aclnn', 1)
            parts = prefix.split('-')
            version = next((i for i, p in enumerate(parts) if re.fullmatch(r'v\d+', p)), len(parts)-1)
            return name + ' · ' + '-'.join(parts[version:])
        return key
    def eligible(self, key): return key in self.catalog() and (self.repo / 'prompts' / (key + '.md')).is_file()
    def holdout_key(self, anchor, key):
        family = anchor.split('-aclnn')[0]
        return (not key.startswith(family + '-aclnn'), key)
    def task_prompt(self, key): return (self.repo / 'prompts' / (key + '.md')).read_text(encoding='utf-8')
    def assets(self, keys):
        for folder in ['scripts', 'openskill', 'prompts', 'docs'] + ['tasks/' + s for s in keys]:
            for file in sorted((self.repo / folder).rglob('*')):
                if file.is_file() and '__pycache__' not in file.parts: yield file
        yield Path(__file__).with_name('agent_runtime.py')
    def evaluate(self, task):
        return {'passed': task['state'] == 'generated' and task['result'].get('validation', {}).get('passed') is True,
                'comparable': task['state'] in ('generated', 'validation_failed')}
    def policy(self):
        return {'version': self.evaluator_id, 'minimum_tasks': 2,
                'promotion': 'all candidate tasks pass; strictly more passes than baseline',
                'scope': 'generation compliance only; no precision or coverage-quality claim',
                'max_session_seconds': 1800, 'max_repairs': 0}
    proposal_constraints = ('Preserve immutable assets, original max_cases, existing validators, generation-only scope. '
        'The candidate overlay is for an EXECUTING coding agent, not a planner. '
        'Read task docs, design and write formal test rules and reports, run existing validators and materialize ATK inputs. '
        'Keep native file/tool argument schemas correct. Do not instruct plan-only behavior. '
        'Baseline planning metadata is not an execution budget. There is no 2048-token or one-model-call execution limit; '
        'only the supplied session time budget applies. The immutable surrounding contract supplies task facts and Step 1 Skill, '
        'prohibits hardware/SSH/Docker/ground-truth access and protects source/configuration/validators. '
        'Never claim hardware or precision success. ')
    def prepare(self, runtime, task, target):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(self.repo / 'scripts/create_workspace.py'),
            '--source-dir', str(self.repo / 'tasks' / task['slug']), '--workspace-root', str(target)],
            capture_output=True, timeout=120, encoding='utf-8', errors='replace')
        (target / 'prepare.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode: raise RuntimeError('Workspace preparation failed; inspect prepare.log')
        skills = {}
        with runtime.store.connect() as c:
            version = json.loads(c.execute('SELECT body FROM versions WHERE id=?', (task['version'],)).fetchone()[0])
        for file in sorted((self.repo / 'openskill').glob('*.md')):
            content = version.get('execution_files', {}).get('openskill/' + file.name, file.read_text(encoding='utf-8'))
            skills[file.name] = {'sha256': hashlib.sha256(content.encode()).hexdigest(), 'content': content}
        (target / 'skills-snapshot.json').write_text(json.dumps(skills, ensure_ascii=False), encoding='utf-8')
        return 'prepared', {'workspace': result.stdout.strip().splitlines()[-1],
            'skills_snapshot': str(target / 'skills-snapshot.json'),
            'next': 'Use OpenCode to plan or generate; hardware execution is not connected'}
    def bundle(self, runtime, identity, engine, model=None, transport='cli'):
        from .agent_runtime import bundle
        result = bundle(runtime, identity, engine, model, transport)
        result['agent_id'] = self.id
        result['execution_harness'] = self.harness_id
        (Path(result['attempt']) / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result
    def validate(self, runtime, manifest):
        from .agent_runtime import validate
        return validate(runtime, manifest)

class DemoAgent:
    id = 'demo'
    name = '平台流程演示'
    available = True
    execution = False
    evolution = False
    task_label = '演示任务'
    description = '仅验证任务生命周期，不产生可靠性结论。'
    harness_id = 'demo'
    evaluator_id = None
    evolution_goal = None
    def catalog(self): return []
    def title(self, key): return '流程演示 · ' + key
    def prepare(self, runtime, task, target):
        evidence = {'synthetic': True, 'note': 'Platform lifecycle demonstration; no reliability verdict'}
        (target / 'evidence.json').write_text(json.dumps(evidence), encoding='utf-8')
        return 'completed', evidence

class AgentRegistry:
    def __init__(self, agents):
        self.adapters = {}
        for agent in agents: self.register(agent)
    def register(self, agent):
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', agent.id): raise ValueError('Invalid Agent identifier')
        if agent.id in self.adapters: raise ValueError('Agent already registered')
        self.adapters[agent.id] = agent
    def get(self, identity):
        agent = self.adapters.get(identity)
        if not agent or not agent.available: raise ValueError('Agent is not connected: ' + str(identity))
        return agent
    def public(self):
        result = [{k: getattr(a, k) for k in ('id','name','available','execution','evolution','task_label','description','harness_id','evaluator_id','evolution_goal')}
                  for a in self.adapters.values()]
        result += [{'id': 'sdc', 'name': 'SDC 检测 Agent', 'available': False, 'execution': False, 'evolution': False,
                    'description': '静默故障检测 · 未接入'},
                   {'id': 'resilience', 'name': '弹性容错 Agent', 'available': False, 'execution': False, 'evolution': False,
                    'description': '恢复与容错验证 · 未接入'}]
        return [a for a in result if a['available'] or a['id'] not in self.adapters]

def bundle(runtime, task_id, engine, model=None, transport='cli'):
    return runtime.registry.get(runtime.store.get(task_id)['domain']).bundle(runtime, task_id, engine, model, transport)

def validate(runtime, manifest):
    return runtime.registry.get(manifest.get('agent_id', 'precision')).validate(runtime, manifest)
