"""Coding-agent process adapter. Does not bypass runtime tool permissions."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
from .task_contract import render
from .execution_package import snapshot as source_snapshot, materialize, intact, materialize_references, references_intact


def executable(engine):
    if engine != 'opencode':
        raise ValueError('Only OpenCode is supported')
    override = os.environ.get('RASBOT_' + engine.upper() + '_BIN')
    if override:
        path = Path(override)
    elif os.name == 'nt' and engine == 'opencode':
        native = shutil.which('opencode.exe')
        path = (Path(native) if native else
                Path(os.environ.get('APPDATA', '')) / 'npm/node_modules/@opencode/cli/bin/opencode.exe')
    else:
        found = shutil.which(engine)
        if not found:
            raise ValueError(f'{engine} executable not found')
        path = Path(found)
    if not path.is_file():
        raise ValueError(f'{engine} not found; set RASBOT_{engine.upper()}_BIN')
    if path.suffix.lower() in ('.cmd', '.ps1', '.bat', '.js'):
        raise ValueError('Configure the native OpenCode executable, not a script wrapper')
    return [str(path)]


def command(engine, prompt_file, model=None):
    instruction = f'Read {prompt_file.as_posix()} completely and execute its generation-only task.'
    if engine == 'opencode':
        args = ['run', '--standalone', '--format', 'json']
    else:
        raise ValueError('Unknown engine')
    if model:
        args += ['--model', model]
    return executable(engine) + args + [instruction]


def protected_digest(workspace):
    result = {}
    for relative in ('01_generate/src', '01_generate/interfaces',
                     '01_generate/submission/test_suite.template.json',
                     '02_atk_run/atk_runnable', '02_atk_run/atk_run_config.json'):
        path = workspace / relative
        files = path.rglob('*') if path.is_dir() else [path]
        for file in files:
            if file.is_file():
                result[file.relative_to(workspace).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return result


def asset_changes(expected, actual):
    return {'added': sorted(actual.keys() - expected.keys()),
            'deleted': sorted(expected.keys() - actual.keys()),
            'modified': sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k])}


def bundle(runtime, task_id, engine, model=None, transport='cli'):
    task = runtime.store.get(task_id)
    if task['domain'] != 'precision' or task['state'] != 'prepared':
        raise ValueError('A prepared precision task is required')
    workspace = Path(task['result']['workspace']).resolve()
    root = runtime.store.root / 'runs' / task_id
    if not workspace.is_relative_to(root) or not workspace.is_dir():
        raise ValueError('Workspace is outside the task run directory')
    prompt = runtime.repo / 'prompts' / (task['slug'] + '.md')
    if not prompt.is_file():
        raise ValueError('Task prompt is missing')
    attempt = root / 'agent' / uuid.uuid4().hex
    attempt.mkdir(parents=True)
    snapshot = json.loads(Path(task['result']['skills_snapshot']).read_text(encoding='utf-8'))
    skill = snapshot['01_generate_test_rules.md']['content']
    with runtime.store.connect() as c:
        harness = json.loads(c.execute('SELECT body FROM versions WHERE id=?', (task['version'],)).fetchone()[0])
    overlay = harness.get('agent_instructions', '')
    files = harness.get('execution_files')
    if files is None:
        files = source_snapshot(runtime.repo)
    execution_root = attempt / 'execution-package'
    package_hashes = materialize(execution_root, files)
    reference_hashes = materialize_references(execution_root, runtime.repo, task['slug'])
    skill = files.get('openskill/01_generate_test_rules.md', skill)
    # Resolve existing Skill commands to the versioned execution scripts.
    skill = skill.replace('$REPO_ROOT/scripts/', '$EXECUTION_ROOT/scripts/')
    skill = skill.replace('${REPO_ROOT}/scripts/', '${EXECUTION_ROOT}/scripts/')
    trusted_scripts = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (runtime.repo / 'scripts').rglob('*.py')}
    text = render(runtime.repo, execution_root, workspace, task['slug'], skill,
                  prompt.read_text(encoding='utf-8'), overlay)
    instruction = attempt / 'task.md'
    instruction.write_text(text, encoding='utf-8')
    args = command(engine, instruction, model) if transport == 'cli' else None
    manifest = {'engine': engine, 'model': model, 'harness': task['version'],
                'cwd': str(workspace), 'command': args, 'transport': transport, 'instruction': str(instruction),
                'instruction_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'workspace': str(workspace), 'attempt': str(attempt),
                'execution_root': str(execution_root), 'execution_files': package_hashes,
                'reference_files': reference_hashes,
                'trusted_scripts': trusted_scripts,
                'protected': protected_digest(workspace), 'scope': 'generate-only'}
    (attempt / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def validate(runtime, manifest):
    workspace = Path(manifest['workspace'])
    if manifest.get('execution_root') and 'reference_files' in manifest and not references_intact(manifest['execution_root'], manifest['reference_files']):
        return {'passed': False, 'reason': 'Fixed execution reference files changed'}
    if manifest.get('execution_root') and not intact(manifest['execution_root'], manifest['execution_files']):
        return {'passed': False, 'reason': 'Versioned execution sources changed during trial'}
    if 'trusted_scripts' in manifest:
        current = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (runtime.repo / 'scripts').rglob('*.py')}
        if current != manifest['trusted_scripts']:
            return {'passed': False, 'reason': 'Independent evaluator scripts changed'}
    changes = asset_changes(manifest['protected'], protected_digest(workspace))
    if any(changes.values()):
        return {'passed': False, 'reason': 'Protected task assets changed', 'asset_changes': changes}
    suite = workspace / '01_generate/submission/test_suite.json'
    if not suite.is_file():
        return {'passed': False, 'reason': 'test_suite.json missing; agent text is not evidence'}
    rules = json.loads(suite.read_text(encoding='utf-8'))
    config = json.loads((workspace / '02_atk_run/atk_run_config.json').read_text(encoding='utf-8'))
    expected = config['max_cases']
    if not isinstance(rules, list) or len(rules) != expected:
        return {'passed': False, 'reason': 'Rule count does not match max_cases',
                'expected': expected, 'actual': len(rules) if isinstance(rules, list) else None}
    seen = set()
    duplicates = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or not isinstance(rule.get('inputs'), (dict, list)):
            return {'passed': False, 'reason': 'Malformed case inputs', 'case_index': index}
        signature = json.dumps(rule['inputs'], sort_keys=True, ensure_ascii=False)
        if signature in seen:
            duplicates.append(rule.get('id', index))
        seen.add(signature)
    if duplicates:
        return {'passed': False, 'reason': 'Duplicate input specifications',
                'duplicate_count': len(duplicates), 'example_ids': duplicates[:20]}
    required = ['01_generate/report/test_rule_design.md',
                '01_generate/report/trigger_coverage.json', '01_generate/report/trigger_library.md']
    missing = [name for name in required if not (workspace / name).is_file()
               or not (workspace / name).stat().st_size]
    if missing:
        return {'passed': False, 'reason': 'Required Step 1 deliverables missing', 'missing': missing}
    output = workspace / '02_atk_run/atk_input/test_suite.atk.json'
    # Generate into a fresh directory so an older output cannot satisfy this gate.
    # Keep the old artifact untouched unless this invocation succeeds without warnings.
    output.parent.mkdir(parents=True, exist_ok=True)
    tool_env = dict(os.environ)
    deps = runtime.store.root / 'tool-deps'
    if deps.is_dir():
        tool_env['PYTHONPATH'] = str(deps)
    tool_env['PYTHONUTF8'] = '1'
    with tempfile.TemporaryDirectory(prefix='.rasbot-validation-', dir=output.parent) as temp:
        fresh_output = Path(temp) / output.name
        args = [sys.executable, '-X', 'utf8', str(runtime.repo / 'scripts/prepare_atk_submission.py'),
                'prepare', '--task-dir', str(workspace), '--submission', str(suite), '-o', str(fresh_output)]
        result = subprocess.run(args, cwd=runtime.repo, capture_output=True, timeout=manifest.get('validation_timeout', 180),
                                encoding='utf-8', errors='replace', env=tool_env)
        log = result.stdout + result.stderr
        (Path(manifest['attempt']) / 'validation.log').write_text(log, encoding='utf-8')
        clean = result.returncode == 0 and 'WARNING:' not in log and fresh_output.is_file()
        if clean:
            os.replace(fresh_output, output)
    return {'passed': clean, 'returncode': result.returncode, 'warnings': 'WARNING:' in log,
            'expected_count': expected, 'actual_count': len(rules),
            'suite_sha256': hashlib.sha256(suite.read_bytes()).hexdigest(),
            'atk_input_sha256': hashlib.sha256(output.read_bytes()).hexdigest() if clean else None,
            'suite': str(suite), 'atk_input': str(output), 'hardware_executed': False}


def execute(runtime, task_id, engine, model=None, timeout=1800):
    if not 1 <= timeout <= 7200:
        raise ValueError('Timeout must be between 1 and 7200 seconds')
    manifest = bundle(runtime, task_id, engine, model)
    previous = runtime.store.get(task_id)['result']
    result = {**previous, 'agent_manifest': manifest}
    if not runtime.store.transition(task_id, 'prepared', 'agent_running', result):
        raise ValueError('Task already claimed')
    attempt = Path(manifest['attempt'])
    try:
        with (attempt / 'events.jsonl').open('w', encoding='utf-8') as out, (attempt / 'stderr.log').open('w', encoding='utf-8') as err:
            process = subprocess.Popen(manifest['command'], cwd=manifest['cwd'],
                stdout=out, stderr=err, stdin=subprocess.DEVNULL, env={**os.environ, 'PYTHONUTF8': '1'})
            with runtime.store.connect() as c:
                runtime.store.event(c, task_id, 'agent.started', {'pid': process.pid, 'engine': engine, 'manifest': str(attempt / 'manifest.json')})
            timed_out = False
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                else:
                    process.kill()
                code = process.wait(timeout=15)
                timed_out = True
        sessions = set()
        errors = []
        with (attempt / 'events.jsonl').open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                sid = event.get('sessionID') or event.get('session_id')
                if isinstance(sid, str):
                    sessions.add(sid)
                if event.get('type') == 'error' or event.get('is_error'):
                    errors.append(event.get('type', 'error'))
                with runtime.store.connect() as c:
                    runtime.store.event(c, task_id, 'agent.event', event)
        result.update(returncode=code, session_ids=sorted(sessions), runtime_errors=errors)
        if timed_out:
            raise RuntimeError('Agent timed out; inspect session and logs before retrying')
        if code or errors:
            raise RuntimeError('Agent returned an error; inspect events.jsonl and stderr.log')
        result['validation'] = validate(runtime, manifest)
        state = 'generated' if result['validation']['passed'] else 'blocked'
        result['next'] = 'Generation gate only; no numerical correctness or hardware verdict'
        runtime.store.transition(task_id, 'agent_running', state, result)
    except Exception as error:
        result['error'] = str(error)
        runtime.store.transition(task_id, 'agent_running', 'blocked', result)
    return runtime.store.get(task_id)
