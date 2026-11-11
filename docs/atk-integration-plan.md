# ATK 接入前置梳理

来源：PrecisionTesting 的 Step 2、atk_queue/atk_queue/cli.py 与 queue.py，2026-11-10 静态检查。没有提交硬件任务或修改队列。

## 已确认协议

- submit 位置参数是 workspace、suite，支持 --queue-dir 与显式 --job-id；只入队，不代表已执行。
- wait 使用精确 job ID；自身无超时。中断等待不取消远端作业。
- wait 返回 0 为 completed、1 为 failed、2 还可能是取消/非法 ID/记录不存在，需读取持久化记录区分。
- cancel 为独立生命周期操作。完成退出不等于精度通过，需分析阶段日志及比较证据。
- 输出位置以 Job 记录为准，不能假设 job-0。提交前先持久化平台 Experiment/Job 关联，未知提交结果按 Job ID 查询，不能盲目重提。

## 文档与代码差异

Step 2 文档要求 workspace 在仓库 .runs 下；queue.py 的 workspace 校验主要检查目录存在，对 tasks 源目录仅发出警告而非硬拒绝，另要求 suite 位于 workspace/02_atk_run/atk_input。RASBot 应自行硬拒绝源任务目录，部署时还应对目标队列版本验证路径及映射条件。

## 当前外部依赖

当前 shell 未发现 atk-queue 命令；这不代表远端未部署。需要明确：队列调度主机、实际 Queue 目录、配置文件位置、允许使用的硬件与镜像、共享工作区/传输方式。不要把 SSH 密钥或其他凭据填写到文档。

## 下一步实现与验收

1. 配置明确的执行端，先进行只读状态/环境检查。
2. 增加 Experiment/Job/Attempt 持久化关系和提交前日志。
3. 用已通过生成门禁的一个任务验收提交、等待、结果收集及重连。
4. 分类队列失败、环境失败、无效比较与真实数值异常，保留原始证据。
5. 验证平台重启不重提；取消必须确认队列终态；大产物记录位置、摘要和保留期限。
