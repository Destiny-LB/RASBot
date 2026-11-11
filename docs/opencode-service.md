# 独立平台 + OpenCode 执行引擎

## 原生 OpenCode 面板

工作台已移除整页 iframe，改为 RASBot 自己的任务对话界面。浏览器仅访问 8765，由后端持有服务认证；无需在页面再次登录 OpenCode。

选择已准备的任务 → 连接任务会话 → 输入消息。首次消息自动附加完整任务契约和 Skill；连接本身不调用模型。会话 ID 持久化，重复打开复用同一会话。消息标记为人工干预；若用于正式元评价，必须另行隔离这种人工参与。

面板支持对话文本、可展开工具记录、模型错误/重试信息、停止请求，以及一次性允许/拒绝权限。权限归属在后端按当前会话校验，不提供永久批准按钮。当前每 4 秒轮询，非逐 token 流式；仅显示当前上下文，不包含压缩前全部历史。模型内部 reasoning 不显示。

目前是基于 OpenCode API 的原生交互面板，不是复用官方 VS Code 扩展源码。默认模型已接入平台设置；文件差异编辑、表单问答和完整历史分页尚未接入。模型 Provider 仍需在 OpenCode 配好，面板改造不修复 Provider 网络故障。

RASBot 管理任务、Harness 版本、工作区、证据和独立校验。OpenCode 管理模型、上下文、工具循环与权限。无需将 RASBot 做成插件，也不复制 OpenCode 源码。

## 启动与本机托管

在 Windows 上直接运行 `python -m rasbot serve --repo ..\PrecisionTesting-main`，首次使用默认由 RASBot 启动本机 OpenCode。需已安装原生 OpenCode 可执行文件；找不到时可设置 RASBOT_OPENCODE_BIN。无需手动启动服务或填写服务密码。

托管引擎只监听 127.0.0.1，首次分配端口并保持地址稳定。随机服务凭据使用当前 Windows 用户 DPAPI 加密保存到数据目录 managed-engine.json，仅由后端解密并通过子进程环境传给 OpenCode；不传给浏览器，不写入启动命令或 RASBot 日志。模型 API、默认模型与工具权限继续沿用 OpenCode 配置。当前托管凭据持久化仅支持 Windows。

引擎启动后通过 /api/info 检查就绪。平台重启优先重新连接原服务，不重复创建会话或重放 Prompt。端口占用或认证不匹配会报错，不接管、不关闭其他服务。RASBot 退出和“断开连接”不会终止引擎，避免中断任务；断开状态跨平台重启保留，点击“连接”才恢复。引擎异常退出后可点击“连接”重新启动，但不会自动重跑任务。

平台只使用本机托管引擎，设置提供连接管理、默认模型、主题、界面语言与任务通知。旧 engine-settings.json 和 RASBOT_OPENCODE_MODE/URL/PASSWORD/PASSWORD_FILE 不再用于平台连接；旧文件不会自动删除，但不会读取。历史任务仍绑定原服务地址，不会自动迁移或重放；原地址不同的历史会话无法直接继续操作。

仅启动引擎不调用模型，也不会启动精度实验。当前适配 OpenCode v2 /api/info、/api/session、/prompt、/context、/permission、/interrupt，不兼容旧版 /session API。

## 工作台流程

创建精度任务 → 准备工作区 → 通过 OpenCode 执行生成与校验 → 同步引擎状态与轨迹。

提交完整执行契约，立即保存会话 ID；平台重启后可以用同步按钮继续观察同一会话，不再启动另一个进程重放任务。当前采用手动 HTTP 同步，不是 SSE 实时订阅。

状态：engine_starting / engine_running / waiting_permission / engine_unknown / validating / generated / validation_failed / engine_failed / cancelled。网络不确定不代表执行已停止；不会自动重发 Prompt。会话创建响应丢失时可能产生孤立会话，需要核查引擎。

权限在 OpenCode 中处理，平台只展示待批准请求，不自动批准。停止按钮请求引擎 interrupt，并查询权威状态，不以 HTTP 成功等同于所有外部作业已结束。

引擎成功后仍须通过原项目 prepare_atk_submission.py 和受保护资产检查，才能进入 generated。generated 只代表用例生成校验，不是硬件精度通过。自动元评价和自演进尚未实现。

## 证据

SQLite 持久化任务与 session_id、引擎地址/版本、提交回执、状态与权限。每次上下文变化保存带摘要的 context 文件，可查看工具输出及错误。当前 context 只覆盖最近压缩后的会话；完整无损事件归档、SSE 重连、消息脱敏与容量策略仍待实现。

旧 agent-run CLI 保留为诊断备用入口；工作台默认走 HTTP 服务。RASBot 后端仍是标准库 Python，无须引入 JS SDK。

官方接口依据：https://opencode.ai/docs/api/ 。本机已核验创建会话、查询上下文与权限的实际响应结构。实验性 API 需随安装版本做兼容检查。

## 统一规划入口

规划与执行统一使用本服务的 Provider 和默认模型，不再读取 RASBOT_API_BASE、RASBOT_API_KEY 或 RASBOT_MODEL。旧的独立 executor 适配器已移除。

工作区准备后可选择“通过 OpenCode 生成计划”。`/api/plan` 异步提交独立的 plan-only 会话，复用同步、权限与停止机制；完成后保存计划文本、实际模型、用量与会话 ID，返回 prepared 状态。下一次生成使用新的执行会话，不把规划完成当作用例校验成功。规划的“不调用工具”是提示约束，不是沙箱权限保障。历史计划和旧状态不做自动重放。

## 平台偏好设置

设置顺序：连接管理、默认模型、外观主题、界面语言、任务通知。各项保持单行布局。

默认模型从本机 OpenCode 的 /api/model 获取已启用的聊天模型，只向页面返回模型标识和名称，不返回 Provider settings 或密钥。选择保存在数据目录 preferences.json，仅在新建规划、生成或面板会话时调用 /model 设置；已有会话不变。选择“跟随 OpenCode”取消平台覆盖，不修改 OpenCode 全局配置。模型设置失败时保留 session ID，不提交 Prompt。

主题支持浅色、深色、跟随系统；语言与主题偏好保存在当前浏览器。系统主题改变时自动更新。

任务通知支持关闭通知、页面内、桌面。默认关闭，桌面模式需用户授权浏览器通知。页面打开时每 8 秒检查任务状态，对活动引擎任务进行状态同步；完成、生成校验通过、失败、等待权限等状态变化产生提醒。同一状态不重复提醒，首次开启不补发历史结果。通知不提交或重放任务，不自动批准权限。关闭页面后不提供后台通知服务；浏览器节流可能延迟通知。桌面通知被拒绝时保留原选项，可改用页面内通知。
