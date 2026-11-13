"""Precision-specific candidate development, assets and contracts."""
import json
import shutil
from pathlib import Path
from .precision_package import materialize, editable, validate_files, hashes, materialize_references, references_intact
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


def prepare(adapter, runtime, source, root, body):
    package = root / 'execution-package'
    materialize(package, body['execution_files'])
    references = materialize_references(package, adapter.repo, source['slug'])
    smoke = root / 'smoke'; smoke.mkdir()
    _, result = adapter.prepare(runtime, source, smoke)
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
    return {'root': str(root), 'package': str(package), 'workspace': str(workspace),
                          'training_slug': source['slug'], 'protected': protected_digest(workspace),
                          'initial_file_hashes': hashes(collect(package, list(body['execution_files']), references)),
                          'original_files': list(body['execution_files']), 'reference_files': references,
                          'reference': str(reference), 'task_facts': adapter.task_prompt(source['slug']), 'status': 'ready'}


def prompt(dev, proposal):
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
诊断与候选指令：{json.dumps(proposal, ensure_ascii=False)}
'''
    if dev.get('checkpoint'):
        prompt += '\n上次开发检查点（仅开发证据，未晋升）：' + json.dumps(dev['checkpoint'], ensure_ascii=False)
    prompt = render(dev.get('reference', dev['root']), dev['package'], dev['workspace'],
                    dev['training_slug'], (Path(dev['package']) / 'openskill/01_generate_test_rules.md').read_text(encoding='utf-8'),
                    dev.get('task_facts', ''), prompt, development=True)
    return prompt


def changes(dev):
    return asset_changes(dev['protected'], protected_digest(Path(dev['workspace'])))


def observe(dev):
    # Read only allowed candidate sources, even when artifact acceptance failed.
    current = {}
    root = Path(dev['package'])
    for folder in ('openskill', 'scripts'):
        for p in (root / folder).rglob('*'):
            if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root.resolve()) and editable(p.relative_to(root).as_posix()):
                import hashlib
                current[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    def difference(initial):
        if initial is None:
            return {'status': 'not_recorded', 'paths': [], 'components': []}
        diff = asset_changes(initial, current)
        paths = sorted(set(sum(diff.values(), [])))
        return {'status': 'observed', **diff, 'paths': paths,
                'components': sorted({'scripts' if p.startswith('scripts/') else 'skill' for p in paths})}
    full = difference(dev.get('parent_file_hashes'))
    full['development_delta'] = difference(dev.get('initial_file_hashes'))
    return full
