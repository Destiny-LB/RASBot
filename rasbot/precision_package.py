"""Versioned execution sources, separate from the platform's trusted evaluator."""
import hashlib
from pathlib import Path, PurePosixPath
from . import execution_package as package


SCOPE = 'precision-generation-toolchain-v1'
CORE = frozenset(['openskill/'+n for n in ('00_prepare_task.md','01_generate_test_rules.md','02_run_atk_verification.md','03_analyze_precision_report.md')] +
    ['scripts/'+n for n in ('create_workspace.py','prepare_atk_submission.py','verify_schema.py','verify_trigger_coverage.py')] +
    ['prompts/prompt_template.md','prompts/generate_prompt__repo_version_DS_aclnnName.py',
     'docs/trigger_library.md','docs/simplified_atk_test_rules__json.md','docs/decorated_atk_operator_schema__yaml.md'])
AUXILIARY = {'scripts/generation':{'.py','.json'}, 'scripts/common':{'.py','.json'},
             'prompts/fragments':{'.md','.txt'}, 'docs/generation':{'.md','.json'},
             'tests/generation':{'.py','.json'}}

def editable(name):
    if not package.safe_path(name):return False
    if name in CORE:return True
    p=PurePosixPath(name)
    return any(name.startswith(folder+'/') and p.suffix in extensions and
               not any(part.startswith('.') or part=='__pycache__' for part in p.parts)
               for folder,extensions in AUXILIARY.items())

def snapshot(repo):
    return {p.relative_to(repo).as_posix(): p.read_text(encoding='utf-8')
            for folder in ('openskill', 'scripts', 'prompts', 'docs', 'tests') for p in sorted((repo / folder).rglob('*'))
            if p.is_file() and editable(p.relative_to(repo).as_posix()) and not p.is_symlink()}


def validate_files(files):
    package.validate_files(files)
    for name, content in files.items():
        if not editable(name):
            raise ValueError('Invalid Precision execution source: ' + name)
        if name.endswith('.py'):
            try:
                compile(content, name, 'exec')
            except (SyntaxError, ValueError) as error:
                raise ValueError('Invalid Python source: ' + name) from error
    return files


def apply_changes(parent, changes):
    validate_files(parent)
    if not isinstance(changes,dict):raise ValueError('Invalid source changes')
    for name,value in changes.items():
        if not editable(name):
            raise ValueError('Outside current evolution scope: '+name)
        if value is None and name in CORE:raise ValueError('Core entry cannot be deleted: '+name)
    validate_files({k:v for k,v in changes.items() if v is not None})
    result=dict(parent)
    for name,value in changes.items():
        if value is None:result.pop(name,None)
        else:result[name]=value
    return validate_files(result)


hashes = package.hashes


def materialize(root, files):
    from .task_contract import adapt
    files = {name: adapt(content) if name == 'openskill/01_generate_test_rules.md' else content
             for name, content in files.items()}
    validate_files(files)
    return package.materialize(root, files)


def materialize_references(root, repo, slug=None):
    """Runtime dependencies are fixed references, never candidate-editable sources."""
    references = {}
    if slug is not None:
        if not isinstance(slug, str) or Path(slug).name != slug or '/' in slug or '\\' in slug or slug in ('.', '..'):
            raise ValueError('Invalid reference task slug')
        folder = Path(repo) / 'tasks' / slug / '02_atk_run/atk_runnable'
        if not folder.is_dir() and (Path(root) / 'scripts/prepare_atk_submission.py').is_file():
            raise ValueError('Required runnable reference is missing')
        for file in folder.rglob('*'):
            if file.is_symlink() or (hasattr(file, 'is_junction') and file.is_junction()):
                raise ValueError('Linked reference rejected')
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                name = file.relative_to(repo).as_posix()
                references[name] = file.read_bytes()
    if slug and (Path(root)/'prompts/generate_prompt__repo_version_DS_aclnnName.py').is_file():
        config=Path(repo)/'tasks'/slug/'02_atk_run/atk_run_config.json'
        if config.is_file():references['tasks/'+slug+'/02_atk_run/atk_run_config.json']=config.read_bytes()
    source = Path(repo) / 'docs/trigger_library.md'
    if not source.is_file():
        if (Path(root) / 'scripts/verify_trigger_coverage.py').is_file():
            raise ValueError('Required trigger library reference is missing')
        return package.materialize_references(root, references)
    if not (Path(root)/'docs/trigger_library.md').exists():
        references['docs/trigger_library.md'] = source.read_bytes()
    return package.materialize_references(root, references)


def references_intact(root, expected):
    root=Path(root)
    try:
        actual={}
        for folder in ('docs','tasks'):
            if package.linked(root/folder):return False
            for p in (root/folder).rglob('*'):
                if package.linked(p):return False
                if p.is_file():
                    name=p.relative_to(root).as_posix()
                    if name in expected or not editable(name):actual[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        return actual==expected
    except OSError:return False


def intact(root, expected):
    root=Path(root)
    if not root.is_dir() or package.linked(root):return False
    try:
        actual={}
        for p in root.rglob('*'):
            if package.linked(p):return False
            if not p.is_file() or '__pycache__' in p.parts:continue
            name=p.relative_to(root).as_posix()
            if name.startswith('tasks/'):continue
            if name=='docs/trigger_library.md' and name not in expected:continue
            actual[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        return actual==expected
    except OSError:return False
