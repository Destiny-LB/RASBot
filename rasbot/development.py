"""Editable candidate workspace; never use development results as formal scores."""
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from .core import now
from .execution_package import materialize, editable, validate_files, hashes, materialize_references, references_intact
from .agent_runtime import protected_digest, asset_changes
from .task_contract import render


def collect(root, original, references=None):
    root = Path(root)
    if not root.is_dir() or root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()):
        raise ValueError('Invalid development source root')
    files = {}
    if references is not None and not references_intact(root, references):
        raise ValueError('Development changed fixed script references')
    size = 0
    for p in root.rglob('*'):
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('Linked development source rejected')
        if not p.is_file() or '__pycache__' in p.parts:
            continue
        name = p.relative_to(root).as_posix()
        if references is not None and name in references:
            continue
        size += p.stat().st_size
        if not editable(name) or size > 2_000_000 or len(files) >= 100:
            raise ValueError('Unapproved development source: ' + name)
        files[name] = p.read_text(encoding='utf-8')
    if set(original) - set(files):
        raise ValueError('Development cannot delete inherited sources')
    return validate_files(files)


def prepare(evo, run, body):
    run.update(state='development_preparing', development_body=body)
    evo.save(run, 'preparing editable candidate and diagnosis-only smoke workspace')
    root = Path(run['root']) / 'development'
    root.mkdir()
    package = root / 'execution-package'
    materialize(package, body['execution_files'])
    adapter = evo.runtime.registry.get(run['agent_id'])
    source = evo.store.get(run['evidence'][0]['task_id'])
    references = materialize_references(package, adapter.repo, source['slug'])
    smoke = root / 'smoke'; smoke.mkdir()
    _, result = adapter.prepare(evo.runtime, source, smoke)
    workspace = Path(result['workspace'])
    reference = root / 'reference'
    reference.mkdir()
    # Expose documentation only, not the repository-wide task/holdout directories.
    docs = adapter.repo / 'docs'
    if docs.is_dir():
        for file in docs.rglob('*'):
            if file.is_file() and not file.is_symlink() and file.suffix in ('.md', '.json', '.yaml', '.yml'):
                out = reference / 'docs' / file.relative_to(docs)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(file, out)
    run['development'] = {'root': str(root), 'package': str(package), 'workspace': str(workspace),
                          'training_slug': source['slug'], 'protected': protected_digest(workspace),
                          'original_files': list(body['execution_files']), 'reference_files': references,
                          'reference': str(reference), 'task_facts': adapter.task_prompt(source['slug']), 'status': 'ready'}
    run['state'] = 'development_ready'
    return evo.save(run, 'candidate development ready; formal evaluation tasks not exposed')


def tick(evo, run):
    if run['state'] in ('development_preparing', 'development_starting', 'development_unknown'):
        run['last_error'] = 'Development request outcome uncertain; inspect session before cancelling. Not replayed.'
        return evo.save(run)
    dev = run['development']
    if run['state'] == 'development_ready':
        run['state'] = 'development_starting'
        evo.save(run, 'development session creation requested')
        run['proposal_session_id'] = run.get('session_id')
        run['session_id'] = evo.engine.client.request('POST', '/api/session', {
            'title': 'RASBot candidate development ' + run['id'],
            'location': {'directory': dev['root']}})['data']['id']
        dev['session_id'] = run['session_id']
        evo.save(run)
        path = evo.engine.client.session_path(run['session_id'])
        evo.engine.client.request('POST', path + '/model', {'model': run['model']})
        prompt = f'''开发候选版本并试跑修复。允许使用工具。只允许修改 EXECUTION_ROOT 中已有 Skill、顶层 Python 脚本及新增允许的辅助脚本；不能删除继承文件。
EXECUTION_ROOT={dev['package']}
WORKSPACE_DIR={dev['workspace']}
REPO_ROOT={dev.get('reference', dev['root'])}
只使用该诊断任务进行开发测试，不读取其他任务或正式评测目录。仓库、平台、评价规则和 workspace 的 src/interfaces/template/atk_runnable/config 均只读。
开发阶段可修改版本副本，正式评测时不允许修改。临时测试和日志放在 development 根目录的 scratch 子目录，不放在 execution-package 中。
请读取 Skill，检查并修复问题，实际运行 Python 脚本或回归测试，依据输出继续修复。报告命令、结果及未解决问题，最终用简体中文总结。
禁止硬件任务、网络服务操作、SSH、Docker和读取 ground truth。不要申请自动放开所有权限。预算到期停止。
结束前必须在诊断工作区生成完整 test_suite.json、设计报告和覆盖账本，并使用版本化脚本物化 ATK 输入。平台将调用固定原始验收器重新验证这些产物；仅成功执行 shell 命令不能通过开发验收。
开发测试是试验依据，不是正式评测分数；平台将在会话完成后检查并冻结源码。无需在最终回复重发源码 JSON。
诊断与候选指令：{json.dumps(run['proposal'], ensure_ascii=False)}
'''
        prompt = render(dev.get('reference', dev['root']), dev['package'], dev['workspace'],
                        dev['training_slug'], (Path(dev['package']) / 'openskill/01_generate_test_rules.md').read_text(encoding='utf-8'),
                        dev.get('task_facts', ''), prompt, development=True)
        (Path(dev['root']) / 'instructions.md').write_text(prompt, encoding='utf-8')
        dev.update(started=now(), status='running')
        run['state'] = 'development_unknown'
        evo.save(run)
        evo.engine.client.request('POST', path + '/prompt', {'text': prompt})
        run['state'] = 'developing'
        return evo.save(run, 'editable development session submitted')
    if run['state'] != 'developing':
        return run  # Uncertain requests must never be blindly replayed.
    path = evo.engine.client.session_path(run['session_id'])
    context = evo.engine.client.request('GET', path + '/context')['data']
    (Path(dev['root']) / 'context.json').write_text(json.dumps(context, ensure_ascii=False), encoding='utf-8')
    dev['context_artifact'] = str(Path(dev['root']) / 'context.json')
    if (datetime.now(timezone.utc) - datetime.fromisoformat(dev['started'])).total_seconds() > run['policy']['development_seconds']:
        return evo.budget_stop(run, 'Candidate development budget exceeded')
    if not context or context[-1].get('type') != 'idle':
        return evo.save(run)
    try:
        if context[-1].get('outcome') != 'succeeded':
            raise ValueError('Candidate development did not succeed')
        changes = asset_changes(dev['protected'], protected_digest(Path(dev['workspace'])))
        if any(changes.values()):
            dev['check'] = {'passed': False, 'validation': {'passed': False, 'reason': 'Protected task assets changed', 'asset_changes': changes}}
            raise ValueError('Development changed protected smoke task assets')
        tools = [p for m in context for p in m.get('content', []) if p.get('type') == 'tool']
        if not any(p.get('name') == 'shell' and p.get('state', {}).get('status') == 'completed' for p in tools):
            raise ValueError('Development has no completed shell trial evidence')
        files = collect(dev['package'], dev['original_files'], dev.get('reference_files'))
    except (ValueError, OSError) as error:
        run.update(state='failed', reason=str(error)); dev['status'] = 'failed'
        return evo.save(run, 'development freeze rejected')
    if run['policy'].get('development_check') == 'development-artifact-gate-v1':
        from .development_checks import check
        remaining = run['policy']['development_seconds'] - (datetime.now(timezone.utc) - datetime.fromisoformat(dev['started'])).total_seconds()
        if remaining <= 0:
            return evo.budget_stop(run, 'Development budget exhausted before independent check')
        dev['check'] = check(evo.runtime, run['agent_id'], dev, remaining)
        if not dev['check']['passed']:
            run.update(state='failed', reason='Independent development artifact check failed')
            dev['status'] = 'failed'
            return evo.save(run, run['reason'])
        if evo.round_expired(run) or (datetime.now(timezone.utc) - datetime.fromisoformat(dev['started'])).total_seconds() > run['policy']['development_seconds']:
            return evo.budget_stop(run, 'Development check exceeded budget')
    body = run.pop('development_body'); body['execution_files'] = files
    dev.update(status='frozen', frozen=now(), file_hashes=hashes(files), tool_calls=len(tools))
    return evo.register_candidate(run, body)
