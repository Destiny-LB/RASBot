"""Versioned execution sources, separate from the platform's trusted evaluator."""
import hashlib
from pathlib import Path, PurePosixPath


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
    if not isinstance(files, dict) or len(files) > 100:
        raise ValueError('Invalid execution file package')
    size = 0
    for name, content in files.items():
        if not editable(name) or not isinstance(content, str) or not content.strip():
            raise ValueError('Invalid execution source: ' + str(name))
        size += len(content.encode('utf-8'))
        if size > 2_000_000:
            raise ValueError('Execution package exceeds 2 MB')
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


def hashes(files):
    return {name: hashlib.sha256(content.encode('utf-8')).hexdigest()
            for name, content in sorted(files.items())}


def materialize(root, files):
    from .task_contract import adapt
    files = {name: adapt(content) if name == 'openskill/01_generate_test_rules.md' else content
             for name, content in files.items()}
    validate_files(files)
    root.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8', newline='')
    return hashes(files)


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
                target = Path(root) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = file.read_bytes(); target.write_bytes(raw)
                references[name] = hashlib.sha256(raw).hexdigest()
    source = Path(repo) / 'docs/trigger_library.md'
    if not source.is_file():
        if (Path(root) / 'scripts/verify_trigger_coverage.py').is_file():
            raise ValueError('Required trigger library reference is missing')
        return references
    target = Path(root) / 'docs/trigger_library.md'
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = source.read_bytes()
    target.write_bytes(raw)
    references['docs/trigger_library.md'] = hashlib.sha256(raw).hexdigest()
    return references


def references_intact(root, expected):
    actual = {}
    for directory in ('docs', 'tasks'):
        folder = Path(root) / directory
        if folder.is_symlink() or (hasattr(folder, 'is_junction') and folder.is_junction()):
            return False
        for file in folder.rglob('*'):
            if file.is_symlink() or (hasattr(file, 'is_junction') and file.is_junction()):
                return False
            if file.is_file():
                actual[file.relative_to(root).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return actual == expected


def intact(root, expected):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        return False
    actual = {}
    for folder in ('scripts', 'openskill'):
        if (root / folder).is_symlink():
            return False
        for file in (root / folder).rglob('*'):
            if file.is_symlink():
                return False
            if file.is_file() and '__pycache__' not in file.parts:
                actual[file.relative_to(root).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return actual == expected
