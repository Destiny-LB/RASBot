# RASBot

**面向 AI 可靠性任务的 Agent 执行与受控自演进平台。**

RASBot 将任务执行、产物校验、候选开发和版本采用串成可追溯闭环。当前以 PrecisionTesting 为首个领域：通过 OpenCode 生成精度测试用例，独立检查生成产物，再根据执行证据改进指令、Skill 和 Python 脚本。

当前定位是 **Windows 本机单用户工作台**。已实现生成与离线校验、候选开发、配对评测及有限多轮探索；硬件精度实验、SDC 检测和弹性容错尚未接入。`generated` 表示生成产物校验通过，不表示硬件精度通过。

## 平台如何工作

```text
领域任务 → 固定 Harness 与任务契约 → OpenCode 执行 → 平台独立校验
                                                        ↓
                                                   轨迹与产物
                                                        ↓
当前采用版本 ← 晋升 / 拒绝 / 无结论 ← 配对评测 ← 候选开发与冻结
```

- **RASBot 控制面**：管理任务状态、工作区、版本、实验预算、评价政策、证据和采用决定。
- **OpenCode 执行引擎**：管理模型 Provider、凭据、会话和工具调用，承担任务执行与候选开发。
- **领域适配器**：提供任务目录、工作区准备、执行契约、源码包策略、候选开发与评价器；任务池与采用版本按 Agent 隔离。
- **SQLite 与文件产物库**：保存任务、事件、版本谱系、演进记录及运行产物。

Harness 是 Agent 的工作方法版本，包含执行指令以及可版本化的 Skill、脚本。任务创建时绑定版本，后续晋升不会改绑历史任务。

## 快速开始

### 环境要求

- Windows，Python 3.10+。
- 已安装 OpenCode v2，并在 OpenCode 中配置可用的模型 Provider。
- 单独准备 PrecisionTesting 仓库；它不随 RASBot 分发。可执行算子需同时具备任务目录和对应 prompt。

以下命令在 RASBot 仓库根目录执行。示例假设 PrecisionTesting 位于同级的 `PrecisionTesting-main` 目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m pip install -r requirements-tools.txt --target .rasbot/tool-deps
.\.venv\Scripts\python -m rasbot serve --repo ..\PrecisionTesting-main --port 8765
```

打开 <http://127.0.0.1:8765>。平台核心使用 Python 标准库，`requirements-tools.txt` 提供领域校验所需的 PyYAML。

平台默认自动托管本机 OpenCode 引擎，优先从 PATH 查找 `opencode.exe`；非标准安装可通过 `RASBOT_OPENCODE_BIN` 指定。当前 Web 工作流不支持外部 OpenCode 连接配置。

模型服务地址和 API Key 只在 **OpenCode** 中配置，RASBot 不维护第二套模型凭据，也不读取 `.env`。平台设置可以选择新会话的默认模型，或跟随 OpenCode 默认值。平台与本机引擎之间的服务认证凭据自动生成，并使用 Windows DPAPI 加密保存；它与模型 API Key 不同。

完整安装、迁移和平台限制见 [安装与迁移](docs/portability.md)、[OpenCode 服务](docs/opencode-service.md)。

### 完成一次任务

1. 在工作台选择精度测试 Agent 和算子任务。
2. 准备工作区，固定任务契约与 Skill 快照。
3. 按需通过 OpenCode 生成计划；规划使用独立会话，完成后任务回到工作区就绪状态。
4. 启动用例生成，在会话面板查看工具反馈、处理权限或请求停止。
5. 查看平台独立校验结果、轨迹和产物。执行会话与规划会话分开创建。

精度流程当前限定为生成和离线输入物化。验收按固定策略区分阻塞性警告与提示：描述性的参考来源标签问题可保留为提示；重复输入、覆盖冲突、参考资产不一致和未知警告仍阻止通过。`warnings=true` 不一定代表失败，应结合 `passed` 与 `warning_details` 判断。

规划的“只输出计划”要求属于提示约束，不是工具沙箱。

无需模型即可运行合成生命周期演示：

```powershell
.\.venv\Scripts\python -m rasbot demo
```

演示不执行可靠性实验。任务执行还提供 `agent-bundle`、`agent-run` CLI 入口，详见 [PrecisionTesting 接入](docs/precision-runtime.md)。

## 受控自演进

### 单轮：提出、开发、验证、决定

工作台“自主演进”页选择诊断任务、2～3 个不同的评测任务和 30 / 60 / 120 分钟预算。至少一个评测任务不能出现在本轮诊断证据中。

```text
轨迹诊断 → 结构化提案 → 候选工作区修改与试跑
         → 独立开发验收 → 冻结源码版本
         → 基线 / 候选配对执行 → 必要时交换顺序复测
         → 晋升、拒绝或无结论
```

精度 Agent 的 Web/API 新轮次默认开启候选开发。允许演进执行指令、`openskill/01_generate_test_rules.md` 和允许范围内的顶层 `scripts/*.py`；工作区创建脚本、任务输入和正式评价器不在候选修改范围。开发结果先经独立验收，再进入正式评测，开发试跑不计入正式分数。

执行过程允许有界修复：

- 提案 JSON、字段或源码格式不合格时，最多请求模型修复两次，保留错误输出；不重置提案时间预算，也不放行工具越界。
- 开发产物未通过验收时，在预算和完整性允许的条件下保存检查点并接续会话，最多三个开发会话；接续不重置开发预算。检查点不等于已接受的候选。
- 新轮次优先为首次基线／候选对照分配预算，不提前为可能发生的效率复测平均分配时间。120 分钟、两个任务且启用开发时，每次正式执行上限为 **1320 秒**，基线与候选一致，整轮时限不延长。
- 初次效率比较达标后，只有剩余预算足够完成整组反序复测才继续；否则保存候选与初次证据，以 `inconclusive` 和 `confirmation_required=true` 结束，不晋升。尚未自动创建独立确认轮次，也未实现基于历史耗时的预算校准。

以上预算和修复政策在创建轮次时固定，已有实验不会自动改用新政策。

当前采用规则评价的是**生成合规性与生成流程效率**：

- 候选必须通过全部合规性门槛；若通过数严格优于基线，可按合规性晋升。
- 双方全部通过时，要求每个任务候选耗时不超过基线的 80%，并交换执行顺序复测；每个配对再次达标后才按效率晋升。
- 不可比较的执行、人工干预或证据不完整不能作为正常晋升依据。
- 支持回退已晋升轮次，但要求当前采用版本仍为该候选。

耗时包含模型、工具和校验的墙钟时间。两次配对复测不构成统计显著性证明，也不能证明数值覆盖或缺陷发现能力提高。

### 多轮：有预算的长期目标

“长期演进目标”支持 1～12 轮串行探索，每轮沿用独立开发与评价流程。系统依据上一轮失败阶段选择下一步假设，并可从本目标中与当前基线兼容、证据可比较的被拒绝候选中选择父版本继续开发；正式对照仍使用创建该轮时的当前采用版本。

目标支持暂停、继续和停止。预算耗尽或连续三轮无晋升会停止；失败、取消或无结论通常需要检查后继续。每轮实验观察按 Agent 留存，后续提案按评价器及失败特征检索，最多读取六项摘要。修改组件来自开发前后的实际源码哈希差异，而非提案声明；缺少历史基线时标记为未知。摘要可包含经过筛选的开发验收失败项、相对文件路径和源码变化，不返回正式评测内容或原始日志。这些记录保留证据与结果，不等于已验证的通用经验。

评测任务跨轮复用，因此不能宣称具有永久未见的保留集。当前为有限、串行、多候选探索，尚未实现并行种群搜索或评价器自动演进。

具体政策、恢复语义与历史实测见 [自主演进](docs/evolution.md)、[候选开发工作区](docs/candidate-development.md)。

## 能力与边界

| 范围 | 当前实现 |
| --- | --- |
| 领域执行 | 精度用例生成与离线校验；另有合成流程演示 |
| 会话交互 | OpenCode 对话、工具反馈、一次性权限处理、停止与状态同步 |
| 版本管理 | 内容寻址 Harness 快照、父子关系、按 Agent 采用与回退 |
| 候选开发 | 领域适配器管理可修改范围、试跑、检查点接续、独立验收和源码冻结 |
| 演进评价 | 固定政策、配对任务、效率复测、拒绝与无结论记录 |
| 长期探索 | 有界串行轮次、历史候选续作、实验观察复用 |
| 观测审计 | 任务轨迹、版本差异、评价证据及只读审计 |
| 尚未接入 | ATK 硬件闭环、SDC 与容错插件、硬件资源池 |

当前使用文件副本、提示约束和完整性检查，**没有操作系统级执行沙箱**。OpenCode 仍继承本机执行权限，平台不会自动批准全部权限请求。开发参考目录缩小了可见材料范围，但不能阻止同机已知路径访问。

服务仅监听回环地址，采用 Host / Origin 检查和变更请求令牌，适用于本机单用户使用。不要让多个服务进程同时调度同一数据库。

已有会话与演进状态可在服务重启后继续观察；准备、创建会话等阶段中途故障的恢复仍有限。提交结果不明时不自动重发；取消需等待引擎终态确认。关闭页面不停止后台轮次，退出平台或断开连接也不会强制停止托管引擎。

已用真实模型验证生成与离线校验。最近一轮重构后演进完成了开发检查点接续、独立验收、候选冻结和正式评测启动，但基线超过当时的 660 秒预算，最终为 `inconclusive`，未完成整组 A/B 比较，也未晋升。

随后调整的预算、有限提案修复及警告分级已通过 159 项回归测试，尚未重跑真实模型演进。测试通过不代表已证明演进收益或硬件可靠性提升。

## 代码结构

| 文件 / 模块 | 职责 |
| --- | --- |
| `rasbot/__main__.py`、`web.html` | CLI、本机 HTTP API、调度入口与工作台 |
| `core.py`、`runtime.py`、`agents.py` | 存储、任务生命周期、Agent 注册与领域适配 |
| `managed_engine.py`、`settings.py`、`opencode_service.py` | 托管引擎、连接设置与会话交互 |
| `execution_package.py` | 通用安全路径、文件清单、落盘、哈希及完整性检查，不包含领域目录规则 |
| `precision_package.py`、`precision_development.py` | Precision 源码白名单、Skill 适配、固定依赖及领域开发实现 |
| `agent_runtime.py`、`task_contract.py`、`precision_warnings.py` | Precision 执行契约、生成校验和固定警告分级 |
| `evolution.py`、`development.py`、`development_checks.py` | 单轮演进、候选开发与独立开发验收 |
| `evolution_selection.py`、`evolution_scoring.py` | 任务选择与配对评分 |
| `campaigns.py`、`experience.py` | 长期目标调度与实验观察记录 |
| `analysis.py`、`evidence.py`、`quality.py`、`*_audit.py` | 轨迹、产物证据、质量分析及审计 |
| `tests/`、`docs/` | 回归测试与功能文档 |

## 开发与测试

在仓库根目录运行：

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

测试使用临时目录与合成样本，不依赖历史本机任务。真实模型调用、生成质量与硬件接入需要另外验收。扩展领域时通过 AgentRegistry 提供任务、执行与评价适配，并实现源码快照／校验／变更合并和开发工作区／契约／验收接口。通用文件路径检查不代替领域可修改范围授权。接口与边界见 [Agent 架构](docs/agent-architecture.md)。

## 数据与迁移

默认 `.rasbot/` 保存数据库、工作区、会话和工具轨迹、产物、演进报告及加密服务凭据，已由 Git 忽略；`.local/` 用于本机辅助文件。模型 Provider 凭据由 OpenCode 管理。

可通过 `--data` 指定本机绝对路径。更换目录会选择另一套状态，不会自动迁移任务；若自定义目录位于仓库内，应额外加入 `.gitignore`。不要复制 DPAPI 服务凭据到其他用户或机器，应让平台重新生成。

源码分发不包含 PrecisionTesting、模型、运行产物和本机配置。提交前检查暂存差异；忽略规则不能移除已跟踪的数据，也不能保护手工上传的压缩包。

## 文档

- [文档目录](docs/README.md)
- [安装与迁移](docs/portability.md) · [OpenCode 服务](docs/opencode-service.md)
- [Agent 架构](docs/agent-architecture.md) · [PrecisionTesting 接入](docs/precision-runtime.md)
- [自主演进](docs/evolution.md) · [候选开发工作区](docs/candidate-development.md)
- [评价与轨迹分析](docs/evaluation.md) · [ATK 接入计划](docs/atk-integration-plan.md)

## 许可证

[MIT License](LICENSE)。
