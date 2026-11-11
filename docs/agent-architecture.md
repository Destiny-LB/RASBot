# Agent 分层与扩展边界

平台界面以 Agent、任务、执行 Harness、证据、评价器和版本为通用对象。PrecisionTesting 是第一个领域适配器，算子、Step 1、ATK 输入、正式用例数量等知识由该适配器提供。

## 已分离的职责

- `agents.py / AgentRegistry`：注册能力、展示名称、可用状态、领域适配器。未注册的 Agent 无法通过 API 执行。
- `PrecisionAgent`：任务目录与名称、任务提示词、准备工作区、固定资产、执行契约打包、产物校验、评价结果和演进约束。
- `runtime.py`：任务状态推进、根据 Agent 分发准备过程、采用版本查询及跨 Agent 版本校验。
- `opencode_service.py`：OpenCode 会话与工具权限生命周期，契约打包和校验通过适配器调用。
- `evolution_selection.py`：通用样本选择流程；任务可用性与保留任务排序由适配器定义。评测池按 Agent 保存。
- `evolution.py`：提案、版本登记、成对执行和晋升/回滚编排；使用所选 Agent 的固定政策、评价结果与资产列表。
- 界面：新建任务先选 Agent；领域任务选择位于其配置区。任务列表显示名称和所属 Agent；演进页绑定 Agent；版本审计显示版本所属 Agent 与各自采用状态。

## 扩展接口

适配器提供元数据 `id/name/available/execution/evolution/task_label/description/harness_id/evaluator_id/evolution_goal`，以及 `catalog/title/eligible/prepare`。

使用 OpenCode 的适配器还需提供 `task_prompt/bundle/validate`。参与自主演进时提供 `assets/policy/proposal_constraints/holdout_key/evaluate`。`evaluate(task)` 返回 `passed` 与 `comparable`，平台不再将精度测试终态作为所有 Agent 的评分语义。

可通过 `runtime.registry.register(adapter)` 或构建 Runtime 时注入 registry 注册适配器。当前为代码级扩展接口，不是动态安装插件系统。可信适配器必须固定自身验证实现与任务资产；权限和操作系统隔离仍需另行部署。

首版任务参数仍以领域任务模板 key 为主，任意参数表单、远程资源调度与通用执行后端尚未实现。当前执行器仍是 OpenCode；SDC、弹性容错仅展示“未接入”，不包含实际检测或容错能力。

## 兼容与隔离

历史 SQLite `domain` 列继续作为 Agent 标识使用，`slug` 继续作为内部任务 key；不重写既有任务与验收证据。旧精度演进记录未带 `agent_id` 时按 precision 解释。新记录保存 Agent 与执行 Harness 类型，候选版本携带所属 Agent。

原精度评测池沿用 `.rasbot/evaluation-pool.json`，其他 Agent 使用独立池文件。`champions` 按 Agent 键管理采用版本，晋升或回滚只影响对应 Agent。既有精度版本与模型默认配置保持不变。

测试使用独立的非精度 fixture 验证目录/准备/样本/版本隔离，以及自定义评价器的晋升与回滚。这是扩展接口测试，不代表真实 SDC 或容错实验已验收。
