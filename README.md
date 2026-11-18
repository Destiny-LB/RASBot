# RASBot

**面向 AI 可靠性任务的 Agent 执行与受控自演进平台。**

RASBot 采用“独立平台 + OpenCode 执行引擎”架构：平台管理任务、版本、预算和评价，OpenCode 执行领域任务并开发候选版本。演进结果经过独立验收与配对比较后，才可能成为后续任务使用的版本。

首个领域是 PrecisionTesting。目前支持精度测试用例生成、离线校验及生成阶段的自演进。ATK 硬件闭环、静默数据损坏（SDC）检测和弹性容错是后续扩展方向，尚未接入。

## 工作流程

```text
领域任务 → 固定任务契约 → OpenCode 执行 → 独立校验 → 轨迹与产物
                                                        ↓
当前采用版本 ← 晋升 / 拒绝 / 无结论 ← 配对评测 ← 候选开发与冻结
```

| 组成 | 职责 |
| --- | --- |
| RASBot 控制面 | 任务生命周期、版本谱系、预算、评价政策和采用决定 |
| OpenCode 引擎 | 模型 Provider、凭据、会话、工具调用和候选开发 |
| 领域适配器 | 任务目录、工作区准备、执行契约、可修改范围和独立评价 |
| SQLite 与产物目录 | 任务事件、源码快照、运行产物和演进证据 |

任务创建时绑定版本，后续晋升不会改绑历史任务。当前工作台面向 Windows 本机单用户使用。

## 快速开始

需要 Python 3.10+、OpenCode v2，以及单独准备的 PrecisionTesting 仓库。在 OpenCode 中配置可用的模型 Provider；模型服务地址和 API Key 不由 RASBot 重复管理。

在 RASBot 仓库根目录执行，示例假设 PrecisionTesting 位于同级目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m pip install -r requirements-tools.txt --target .rasbot/tool-deps
.\.venv\Scripts\python -m rasbot serve --repo ..\PrecisionTesting-main --port 8765
```

打开 <http://127.0.0.1:8765>。平台核心使用 Python 标准库，领域工具依赖由 `requirements-tools.txt` 提供。

平台自动托管本机 OpenCode，优先从 PATH 查找 `opencode.exe`；非标准安装可设置 `RASBOT_OPENCODE_BIN`。工作台设置可选择新会话的默认模型。平台与引擎间的认证凭据使用 Windows DPAPI 保存，与模型 API Key 分开管理。

详细环境要求见 [安装与迁移](docs/portability.md) 和 [OpenCode 服务](docs/opencode-service.md)。

## 运行任务

1. 选择精度测试 Agent 和算子任务，准备工作区。
2. 按需生成计划，再启动用例生成；规划和执行使用独立会话。
3. 在 OpenCode 面板查看工具反馈、处理权限或请求停止。
4. 查看独立校验结果、任务轨迹、产物和评价证据。

`generated` 表示生成产物通过当前校验，**不表示硬件精度通过**。警告是否阻断取决于固定评价政策，应结合 `passed`、`warning_details` 和正式评价记录判断。

无需模型即可运行合成生命周期演示：

```powershell
.\.venv\Scripts\python -m rasbot demo
```

演示不执行可靠性实验。`agent-bundle`、`agent-run` 等命令见 [PrecisionTesting 接入](docs/precision-runtime.md)。

## 受控自演进

单轮流程为：诊断证据 → 结构化提案 → 候选开发与试跑 → 独立开发验收 → 冻结版本 → 基线/候选配对 → 反序确认 → 决定是否采用。

工作台选择 2～3 个不同评测任务与 60、120 或 180 分钟预算，默认 120 分钟。至少一个评测任务不在本轮诊断证据中；任务可能跨轮复用，不能视为永久未见的保留集。开发试跑不计入正式评分。

### 可修改范围

Precision 当前范围为 `precision-generation-toolchain-v1`：

| 类别 | 核心文件 |
| --- | --- |
| Skill（4 个） | `openskill/00_prepare_task.md`、`01_generate_test_rules.md`、`02_run_atk_verification.md`、`03_analyze_precision_report.md` |
| 脚本（4 个） | `scripts/create_workspace.py`、`prepare_atk_submission.py`、`verify_schema.py`、`verify_trigger_coverage.py` |
| 提示词（2 个） | `prompts/prompt_template.md`、`generate_prompt__repo_version_DS_aclnnName.py` |
| 文档（3 个） | `docs/trigger_library.md`、`simplified_atk_test_rules__json.md`、`decorated_atk_operator_schema__yaml.md` |

核心入口可修改、不可删除。辅助模块可在 `scripts/generation/`、`scripts/common/`、`prompts/fragments/`、`docs/generation/`、`tests/generation/` 中按规定文件类型新增、修改和删除；执行指令也可演进。旧版本已有的顶层 Python 辅助脚本保留兼容。

候选工作区创建脚本和提示词生成器实际参与执行，四个 Skill 一起版本化。`atk_queue`、固定任务、逐算子提示词、ground truth 及平台评价器不开放修改；采用候选不会覆盖原始 PrecisionTesting 仓库。

### 评价与晋升

当前正式评价使用 `meta-generation-v3`，测量生成设计质量：

| 指标 | 权重 | 含义 |
| --- | ---: | --- |
| 规则有效性 | 35% | 固定工具可物化的规则满足任务数量要求 |
| 风险覆盖 | 30% | 固定输入规格探针的命中情况 |
| 交付完整性 | 15% | 必要产物存在且非空 |
| 证据一致性 | 10% | 规则与覆盖账本的关联一致性 |
| 多样性 | 10% | 输入规格的差异程度 |

专项风险探针目前支持 Expm1、Log1p、Hardtanh；所有具备任务输入和提示词的算子均可参加演进，不受专项探针限制。规格覆盖不是实际采样覆盖，也不是缺陷发现率；未知分布不能自动算作命中。

晋升先要求可信完整的配对证据、候选有效规则与交付达标，再比较整轮综合质量收益；辅助指标的逐任务退步只作诊断，不单独否决晋升：

- **质量路径**：两轮各自的平均加权收益均至少为 1 分。
- **耗时只用于预算和诊断**：质量持平时，任何速度收益都不能触发晋升。

首轮达标只触发确认，仅对当前可重放的离线生成任务交换执行顺序复测后才可晋升；此规则不能直接用于不可重放的硬件实验。耗时包含工具、校验和平台观测开销，不等于纯模型速度。质量与成本不混成一个可相互抵消的总分。

脚本或文档变化时，平台还会追加正常与异常规则的结构契约探针；契约失败不能由高分抵消。准备阶段保留固定资产等价检查，执行阶段检查版本完整性。这些检查尚不构成完整的工具链语义验证。

晋升记录明确标注：**生成阶段已评价，硬件执行与报告分析效果未验证**。四个 Skill 均可修改不等于四个阶段均已验证，两轮确认也不构成统计显著性证明。

### 预算与多轮探索

提案和开发支持预算内的有限修复。首次配对优先获得执行预算；确认预算可依据首轮观测耗时估算，但不超过固定上限。预算不足时保存候选和证据，以无结论结束，可显式追加预算继续确认，恢复前重新核对版本、引擎与固定资产。

长期目标支持 1～12 轮串行探索、暂停、继续和停止，并可选择兼容的历史被拒绝候选继续开发。确认轮可使用目标已授权的剩余预算；不足时需要处理。系统不自动扩大授权预算，也不进行无限或并行种群搜索。

详见 [自主演进](docs/evolution.md)、[候选开发工作区](docs/candidate-development.md) 和 [评价与轨迹分析](docs/evaluation.md)。

## 当前边界

- 已实现任务轨迹、产物证据、源码差异、版本关系及评价记录；完整谱系可视化、跨版本趋势和自动因果归因仍需完善。
- 文件副本、提示约束和完整性检查不是操作系统级沙箱，OpenCode 继承本机执行权限。
- 服务仅监听回环地址，带 Host / Origin 检查和变更请求令牌；不要让多个服务进程同时调度同一数据库。
- 关闭页面不会停止后台轮次。已有会话可继续观察，但部分中间阶段的故障恢复仍有限。
- 自动化测试和离线探针验证实现行为，不证明真实模型演进收益或硬件可靠性提升。

## 代码与测试

| 模块 | 职责 |
| --- | --- |
| `core.py`、`runtime.py`、`agents.py` | 存储、任务生命周期与领域注册 |
| `__main__.py`、`web.html` | CLI、HTTP API、后台调度与工作台 |
| `managed_engine.py`、`settings.py`、`opencode_service.py` | OpenCode 托管与会话交互 |
| `precision_package.py`、`precision_toolchain.py`、`agent_runtime.py` | 源码范围、版本化工具链与任务执行 |
| `evolution.py`、`development.py`、`development_checks.py` | 单轮演进、候选开发与验收 |
| `meta_evaluation.py`、`risk_profile.py`、`meta_promotion.py`、`toolchain_contracts.py` | 独立评价、风险探针、晋升与契约检查 |
| `evaluation_budget.py`、`campaigns.py`、`experience.py` | 确认预算、多轮探索与实验摘要 |
| `analysis.py`、`evidence.py`、`*_audit.py` | 轨迹分析、完整性证据与审计 |

在仓库根目录运行回归测试：

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

测试使用临时目录、合成样本和模拟会话；真实模型与硬件需要另行验收。扩展领域通过 AgentRegistry 接入任务、执行、开发和评价适配，参见 [Agent 架构](docs/agent-architecture.md)。

## 数据与迁移

默认 `.rasbot/` 保存数据库、工作区、轨迹、产物、演进记录及加密服务凭据，已由 Git 忽略。可用 `--data` 指定其他本机数据目录；更换目录不会自动迁移任务。不要跨用户或机器复制 DPAPI 凭据，应由平台重新生成。

PrecisionTesting、模型、运行产物和本机配置不随源码分发。更多说明见 [文档目录](docs/README.md)、[安装与迁移](docs/portability.md) 和 [ATK 接入计划](docs/atk-integration-plan.md)。

## 许可证

[MIT License](LICENSE)。
