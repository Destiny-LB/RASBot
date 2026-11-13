# PrecisionTesting 接入与生成验收

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

task.md 使用完整任务 prompt 与所选版本的 Step 1 Skill；模型没有收到截断后的简略计划请求。旧规划 instructions 不作为执行指令；版本可提供 agent_instructions 及 Skill、执行脚本文件包，详见 [自主演进](evolution.md)。规划也通过 OpenCode 服务会话执行，独立模型 API 适配器已移除。

## 边界

资产摘要检查和提示词约定不是操作系统沙箱。CLI 备用执行入口不提供实时流或服务会话恢复；HTTP 会话恢复见 [OpenCode 服务](opencode-service.md)。自动权限配置、硬件实验和评价器自动演进尚未实现。Windows 超时尝试终止进程树，中断后仍需核查 Runtime 会话。不自动重试，避免重放有副作用的行动。

CLI 依据：https://opencode.ai/docs/cli/ 、本机 opencode run --help。


## 生成验收门槛

1. 连接：已配置模型代理可达，OpenCode 返回有效响应。
2. 工具：真实 read 调用读取指定本地文件，得到预期内容。
3. 生成：正式 suite 的规则数等于原配置 max_cases，不降配为 smoke。
4. 交付：设计报告、覆盖账本、Trigger Library 副本存在且非空。
5. 校验：RASBot 独立运行原 prepare_atk_submission.py，无失败、无 WARNING，生成 ATK 输入。
6. 追溯：保存任务/会话 ID、指令快照、过程记录、规则及物化文件摘要。

generated 仅表示上述生成门禁通过，不代表精度故障已检出，也不证明覆盖设计最优。设计报告内容和去重情况仍需审阅。

普通任务中的模型工具错误应由 Agent 读取反馈修正。独立校验失败时将具体日志交回原会话，限定只修复生成产物，不修改验证工具、max_cases 或受保护资产。不因一次失败就重建任务或降低门槛。正式演进评测不自动修复或重试，以保留对照条件。

运行记录在 .rasbot/m1-run.json；实验产物位于该任务的 runs 目录。这是历史生成验收记录路径，不作为程序输入。

实际运行的任务 ID、会话 ID、文件摘要和验收记录保存在本机数据目录的 reports/ 下，不随源码发布。


### 验收警告分级

固定策略precision-warning-severity-v1保存warning_details。仅library.source_path的描述性标签警告为非阻塞；其canonical内容和SHA校验仍须通过。重复输入、覆盖账本冲突、参考资产一致性问题及未知警告均阻塞；返回码非零或缺少新物化产物仍失败。passed可以为true且warnings为true，调用方应以passed及warning_details判断，不应将所有提示等同失败。
