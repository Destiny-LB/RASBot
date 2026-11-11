# M1：精度生成闭环验收

范围：OpenCode 读取 PrecisionTesting 任务与 Step 1 Skill，在独立 workspace 中生成并校验正式用例。禁止执行 Step 2/3、ATK 作业、SSH 和硬件实验。源任务资产与配置保持不变。

## 分层门禁

1. 连接：已配置模型代理可达，OpenCode 返回有效响应。
2. 工具：真实 read 调用读取指定本地文件，得到预期内容。
3. 生成：正式 suite 的规则数等于原配置 max_cases，不降配为 smoke。
4. 交付：设计报告、覆盖账本、Trigger Library 副本存在且非空。
5. 校验：RASBot 独立运行原 prepare_atk_submission.py，无失败、无 WARNING，生成 ATK 输入。
6. 追溯：保存任务/会话 ID、指令快照、过程记录、规则及物化文件摘要。

generated 仅表示上述生成门禁通过，不代表精度故障已检出，也不证明覆盖设计最优。设计报告内容和去重情况仍需审阅。

模型工具错误应由 Agent 读取反馈修正。独立校验失败时将具体日志交回原会话，限定只修复生成产物，不修改验证工具、max_cases 或受保护资产。不因一次失败就重建任务或降低门槛。

运行记录在 .rasbot/m1-run.json；实验产物位于该任务的 runs 目录。未达到所有门禁前，不宣布 M1 完成。

实际运行的任务 ID、会话 ID、文件摘要和验收记录保存在本机数据目录的 reports/ 下，不随源码发布。
