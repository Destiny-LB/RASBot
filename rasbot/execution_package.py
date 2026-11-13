"""Domain-neutral source manifests, safe paths, materialization and integrity."""
import hashlib
from pathlib import Path, PurePosixPath


def safe_path(name):
    if not isinstance(name, str) or name in ('', '.', '..') or chr(92) in name or ':' in name:
        return False
    p = PurePosixPath(name)
    return not p.is_absolute() and p.as_posix() == name and all(x not in ('.', '..') for x in p.parts)


def validate_files(files):
    if not isinstance(files, dict) or len(files) > 100:
        raise ValueError('Invalid execution file package')
    size = 0
    for name, content in files.items():
        if not safe_path(name) or not isinstance(content, str) or not content.strip():
            raise ValueError('Invalid execution source: ' + str(name))
        size += len(content.encode('utf-8'))
    if size > 2_000_000: raise ValueError('Execution package exceeds 2 MB')
    return files


def hashes(files):
    return {name: hashlib.sha256(value.encode('utf-8')).hexdigest() for name, value in sorted(files.items())}


def materialize(root, files):
    validate_files(files)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8', newline='')
    return hashes(files)


def linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def materialize_references(root, files):
    root = Path(root)
    if not root.is_dir() or linked(root): raise ValueError('Invalid reference root')
    for name, raw in files.items():
        if not safe_path(name) or not isinstance(raw, bytes): raise ValueError('Invalid fixed reference')
        target = root / name
        if target.exists() or linked(target): raise ValueError('Reference overlaps existing asset')
        parent = target.parent
        while parent != root:
            if linked(parent): raise ValueError('Linked reference parent')
            parent = parent.parent
    result = {}
    for name, raw in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


def intact(root, expected, folders=None, ignore_cache=False):
    root = Path(root)
    if not root.is_dir() or linked(root): return False
    if folders is not None and any(not safe_path(n) for n in folders): return False
    actual = {}
    selected = [root] if folders is None else [root / name for name in folders]
    try:
        for folder in selected:
            if linked(folder): return False
            for file in folder.rglob('*'):
                if linked(file): return False
                if file.is_file() and not (ignore_cache and '__pycache__' in file.parts):
                    actual[file.relative_to(root).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    except OSError:
        return False
    return actual == expected
