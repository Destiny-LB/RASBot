"""Execution integration for the bounded Precision toolchain scope."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
from .precision_package import materialize,materialize_references,intact,references_intact,CORE
from .agent_runtime import protected_digest
from .evaluation_budget import remaining

def environment(runtime):
    env=dict(os.environ,PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1')
    deps=runtime.store.root/'tool-deps'
    if deps.is_dir():env['PYTHONPATH']=str(deps)
    return env

def invoke(script,source,target,repo,env,deadline=None):
    target.mkdir(parents=True,exist_ok=True)
    result=subprocess.run([sys.executable,'-B','-X','utf8',str(script),'--source-dir',str(source),'--workspace-root',str(target)],cwd=repo,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=remaining(deadline,120),env=env)
    (target/'prepare.log').write_text(result.stdout+result.stderr,encoding='utf8')
    if result.returncode or not result.stdout.strip():raise ValueError('Workspace preparation failed; inspect prepare.log')
    workspace=Path(result.stdout.strip().splitlines()[-1]).resolve()
    if not workspace.is_relative_to(target.resolve()) or not workspace.is_dir():raise ValueError('Preparation returned an outside workspace')
    return workspace

def prepare(runtime,slug,target,files,deadline=None):
    repo=runtime.repo;source=repo/'tasks'/slug;env=environment(runtime)
    package=target/'preparation-package';expected=materialize(package,files);refs=materialize_references(package,repo,slug)
    def trusted_assets():
        paths=set((repo/'scripts').rglob('*.py'))|{repo/name for name in CORE if (repo/name).is_file()}
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    trusted=trusted_assets()
    source_before=protected_digest(source)
    fixed=invoke(repo/'scripts/create_workspace.py',source,target/'fixed-preparation',repo,env,deadline)
    fixed_digest=protected_digest(fixed)
    workspace=invoke(package/'scripts/create_workspace.py',source,target/'candidate-preparation',package,env,deadline)
    if protected_digest(workspace)!=fixed_digest:raise ValueError('Candidate preparation changed fixed task assets')
    if protected_digest(source)!=source_before:raise ValueError('Candidate preparation changed source task')
    after=trusted_assets()
    if trusted!=after:raise ValueError('Candidate preparation changed trusted evaluator')
    if not intact(package,expected) or not references_intact(package,refs):raise ValueError('Candidate preparation mutated frozen package')
    remaining(deadline,120)
    return str(workspace),{'scope':'fixed task asset equivalence; no hardware validation','passed':True,'package':str(package),'protected':fixed_digest}

def prompt(runtime,root,slug):
    result=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(root)/'prompts/generate_prompt__repo_version_DS_aclnnName.py'),'--slug',slug,'--dry-run'],cwd=root,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60,env=environment(runtime))
    if result.returncode or not result.stdout.strip() or len(result.stdout)>256000:raise ValueError('Candidate prompt generation failed: '+result.stderr[-500:])
    return result.stdout
