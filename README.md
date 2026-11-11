# RASBot

本项目采用 [MIT License](LICENSE)。

迁移与安装说明见 [源码提交与跨机器运行](docs/portability.md)。当前完整托管工作流支持 Windows；Linux/macOS 凭据后端尚未实现。运行数据和模型凭据不随源码分发。

AI 可靠性 Agent 自演进平台的 V0 工作台。RASBot 管理任务、Harness 版本、证据与校验；OpenCode 统一管理模型 Provider、凭据、会话和工具执行。

## 启动与模型配置

模型服务地址、API Key 和默认模型只在 **OpenCode** 中配置。RASBot 的“生成计划”、用例生成和对话面板都使用同一个 OpenCode 服务，不需要另一套模型 API 环境变量，也不会读取 `.env`。

Windows 上已安装 OpenCode 后，直接启动平台（首次默认自动托管本机引擎）：

```powershell
cd RASBot
python -m rasbot serve --repo ..\PrecisionTesting-main --port 8765
```

浏览器访问 http://127.0.0.1:8765 。这里的 OpenCode 服务认证不等同于模型 Provider 的 API Key；平台不复制模型凭据。平台设置可为新会话选择默认模型，也可跟随 OpenCode 默认值；已有会话不受影响。

本机服务凭据由平台自动生成并以 Windows DPAPI 加密保存，无需手动填写。平台仅使用本机托管引擎，已移除外部连接配置；旧连接配置和环境变量不再生效。退出平台或断开连接不会强制停止引擎。详见 [引擎管理说明](docs/opencode-service.md)。

## 工作流程

选择 Agent → 配置领域任务 → 准备工作区 → 可选“通过 OpenCode 生成计划” → 执行任务与验证。精度 Agent 的算子配置只在其任务区域出现。

也可进入 OpenCode 面板连接任务并对话。首次执行消息携带任务契约和固定的 Skill 快照。规划使用独立会话，完成后保存计划、实际模型和用量记录，任务回到工作区就绪状态。规划只要求输出文本，不执行硬件实验；这是提示约束，不是独立工具沙箱。生成用例时创建新的执行会话。

`POST /api/plan` 保留兼容入口，但现在异步提交 OpenCode 会话；通过 `/api/engine/sync` 观察结果，通过 `/api/engine/cancel` 请求停止。不再同步返回旧模型 API 的结果。不确定的请求不会自动重发。

## 当前能力与边界

- SQLite 任务、不可变 Harness 版本、父子关系、事件轨迹及评价计划登记。
- OpenCode 原生对话面板、工具反馈、一次性权限处理与停止请求。
- PrecisionTesting 工作区准备、执行契约、生成产物独立校验；校验器依赖可用 `python -m pip install -r requirements-tools.txt --target .rasbot/tool-deps` 隔离安装。
- `generated` 仅代表生成产物校验通过，不是硬件精度通过。
- 有界自主演进：模型诊断轨迹并提出执行提示词候选，平台登记谱系、运行成对任务、执行固定生成门禁、严格晋升及回滚。入口在“自主演进”页。
- 元评价建议单独记录，不自动改变本轮评价规则；评价器自身的校准与演进、长期经验提炼、SDC 与容错插件尚未实现。
- M1 正式生成与离线校验已经验收，硬件端到端尚未接入；部分目录任务缺少 prompt，暂不能执行。

当前为仅监听本机的单用户工作台。没有独立资源调度或执行沙箱；进程故障后的准备阶段恢复仍有限。

## 测试与说明

```powershell
python -m unittest discover -s tests -v
```

详细说明：[OpenCode 服务接入](docs/opencode-service.md)、[PrecisionTesting 接入](docs/precision-runtime.md)、[M1 验收](docs/m1-acceptance.md)、[M2 自主演进](docs/m2-evolution.md)、[M2 实测验收](docs/m2-acceptance.md)。

## 源码与本机数据隔离

上传 GitHub 的内容为 `rasbot/`、`tests/`、通用 `docs/`、README、依赖声明与 `.gitignore`。
默认数据目录 `.rasbot/` 保存任务数据库、任务工作区、模型对话/工具轨迹、生成产物、运行报告及加密服务凭据，已被 Git 忽略。模型 Provider 凭据和 OpenCode 全局配置由 OpenCode 管理，不应复制进源码。

可通过 `--data` 指定仓库外的数据目录（请使用本机绝对路径）；更换该参数会选择另一套状态，不会自动迁移已有任务。若把自定义数据目录放在仓库内，必须另外加入 `.gitignore`。本机辅助文件可放入已忽略的 `.local/`。

首次提交前运行 `git status --short --untracked-files=all`，暂存后运行 `git diff --cached --name-only` 和 `git diff --cached`，确认没有配置、日志、数据库、任务产物或真实凭据。`.gitignore` 只影响未跟踪文件，不会移除已提交文件或清理历史；也不会过滤手工上传的文件或整个目录压缩包。

## Agent 分层

平台通过 AgentRegistry 分发目录、准备、执行契约和评价器；任务池及采用版本按 Agent 隔离。当前实际接入精度测试 Agent 与流程演示，SDC 和弹性容错明确标记为未接入。扩展接口、历史兼容和边界见 [Agent 架构说明](docs/agent-architecture.md)。
