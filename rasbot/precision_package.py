"""Versioned execution sources, separate from the platform's trusted evaluator."""
import hashlib
from pathlib import Path, PurePosixPath
from . import execution_package as package


def editable(name):
    if not isinstance(name, str) or '\\' in name or ':' in name:
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(p in ('', '.', '..') for p in path.parts):
        return False
    # Provisioning and hardware operations are outside generation evolution.
    return name == 'openskill/01_generate_test_rules.md' or (
        len(path.parts) == 2 and path.parts[0] == 'scripts'
        and path.suffix == '.py' and path.stem.isidentifier()
        and path.name not in ('create_workspace.py', 'verify_precision_report.py'))


def snapshot(repo):
    return {p.relative_to(repo).as_posix(): p.read_text(encoding='utf-8')
            for folder in ('openskill', 'scripts') for p in sorted((repo / folder).rglob('*'))
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
    validate_files(changes)
    return validate_files({**parent, **changes})


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
    source = Path(repo) / 'docs/trigger_library.md'
    if not source.is_file():
        if (Path(root) / 'scripts/verify_trigger_coverage.py').is_file():
            raise ValueError('Required trigger library reference is missing')
        return package.materialize_references(root, references)
    references['docs/trigger_library.md'] = source.read_bytes()
    return package.materialize_references(root, references)


def references_intact(root, expected):
    return package.intact(root, expected, ('docs', 'tasks'))


def intact(root, expected):
    return package.intact(root, expected, ('scripts', 'openskill'), ignore_cache=True)
