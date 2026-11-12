"""Shared generation contract for development and frozen execution."""
import sys
from pathlib import Path


def adapt(text):
    return (text.replace('interfaces/constraints.md', 'report/constraints.md')
            .replace('$REPO_ROOT/scripts/', '$EXECUTION_ROOT/scripts/')
            .replace('${REPO_ROOT}/scripts/', '${EXECUTION_ROOT}/scripts/'))


def render(repo, package, workspace, slug, skill, facts='', overlay='', development=False):
    permission = ('You may edit allowed Skill and Python sources in EXECUTION_ROOT; fixed docs/tasks references remain read-only.'
                  if development else 'Do not edit EXECUTION_ROOT during execution.')
    return f'''# RASBot generation-only execution contract
REPO_ROOT={Path(repo).as_posix()}
EXECUTION_ROOT={Path(package).as_posix()}
WORKSPACE_DIR={Path(workspace).as_posix()}
TASK_SLUG={slug}
PYTHON={Path(sys.executable).as_posix()}

Execute Step 1: generate complete test_suite.json, design report, coverage ledger,
validate rules and materialize ATK input. Use this existing workspace; do not create another.
Do NOT execute Step 2/3, hardware jobs, SSH, Docker, atk task, or read ground truth,
.agent_read_not_allow or Step 4. Repository and workspace src/interfaces/template/
atk_runnable/config assets are read-only. Write constraints to 01_generate/report/constraints.md.
Use Python with -X utf8 on Windows. Report blocking permissions honestly.
使用简体中文撰写解释、设计报告及最终回复。
Use absolute EXECUTION_ROOT/scripts/... paths for ALL scripts, including relative examples.
REPO_ROOT is read-only documentation; it is not the executable script directory.
The existing configuration is authoritative; missing optional fields do not authorize edits.
{permission}
The platform independently validates artifacts. This contract overrides conflicting examples.

## Versioned execution overlay
{adapt(overlay)}
## Task facts (generation-only scope above overrides the full execution scope)
{adapt(facts)}
## Pinned Step 1 Skill
{adapt(skill)}
'''
