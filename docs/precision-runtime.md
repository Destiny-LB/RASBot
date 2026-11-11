# PrecisionTesting Runtime 接入（2026-11-09）

## 调查结论

已检查 README、Step 1、Expm1 prompt、工作区/物化校验脚本及本机 CLI 帮助。项目是领域指令、任务资产与工具集合，不是独立服务；openskill 文档由编码 Agent 显式读取，不代表已安装成各 Runtime 原生 Skill。

分层：RASBot → Agent Runtime 适配 → OpenCode → PrecisionTesting → ATK。此次仅开放 Step 1 的生成、校验、物化；Step 2 硬件和 Step 3 报告尚未接入。

发现约束冲突：Skill 要求写 interfaces/constraints.md，任务 prompt 禁止修改 interfaces。执行契约将该产物改放 report/constraints.md。

## 使用

先在工作台创建精度任务并准备工作区，取得任务 ID。在项目目录执行：

```powershell
python -m rasbot agent-bundle --task TASK_ID --engine opencode
python -m rasbot agent-run --task TASK_ID --engine opencode --model provider/model --timeout 1800
```

bundle 仅生成可审查指令与清单，不调用模型。agent-run 实际调用 Runtime，可能产生费用。继承 Runtime 的模型认证和工具权限，不添加自动批准或跳过权限参数。权限不足将阻塞，需通过 Runtime 正常配置权限。

OpenAI 兼容 API 请配置为 OpenCode Provider；RASBot 不再提供独立的模型 API 配置。当前官方 Provider 文档使用 providers/package/settings.baseURL，不能照搬旧配置字段。文档：https://opencode.ai/docs/providers/ 。

Windows 自动寻找原生 OpenCode exe；可用 RASBOT_OPENCODE_BIN 指定绝对路径。拒绝脚本包装器，不使用 shell=True。

## 证据与验收

prepared → agent_running → generated / blocked。每次尝试保存 task.md、manifest.json、events.jsonl、stderr.log、validation.log。退出后导入结构化事件及会话 ID，目前不实时推送。

generated 要求进程无错误、受保护资产摘要不变、suite 存在、独立运行原 prepare_atk_submission.py 成功、无 WARNING、ATK 输入已生成。不把 Agent 宣称成功当作依据，不表示硬件精度通过。

task.md 使用完整任务 prompt 与准备时的 Step 1 快照；模型没有收到截断后的简略计划请求。旧规划 instructions 不作为执行指令；版本可提供 agent_instructions 叠加策略。规划也通过 OpenCode 服务会话执行，独立模型 API 适配器已移除。

## 边界

资产摘要检查和提示词约定不是操作系统沙箱。当前未固定全部工具和仓库文档版本，未实现实时流、会话自动恢复、自动权限配置、硬件实验或独立元评价。Windows 超时尝试终止进程树，中断后仍需核查 Runtime 会话。不自动重试，避免重放有副作用的行动。

CLI 依据：https://opencode.ai/docs/cli/ 、本机 opencode run --help。
