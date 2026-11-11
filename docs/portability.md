# 源码提交与迁移边界

仓库提交源代码、通用文档、合成测试和依赖声明；不提交运行数据。`.rasbot/`、`.local/`、`.env*`（示例除外）、OpenCode 本机配置、数据库、日志、凭据及构建缓存由 .gitignore 排除。

## 另一台机器的部署

当前完整托管工作流仅支持 Windows，要求 Python 3.10+ 与 OpenCode v2。DPAPI 是通用 Windows 系统能力，不是开发者个人配置；不要复制 managed-engine.json 到另一用户或机器，让平台重新生成。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install .
.\.venv\Scripts\python -m pip install -r requirements-tools.txt --target .rasbot/tool-deps
# 单独准备 PrecisionTesting，并在 OpenCode 中配置模型。
.\.venv\Scripts\rasbot --repo <PrecisionTesting绝对路径> --data <本机数据目录绝对路径>
```

源码也可直接用 `python -m rasbot serve` 启动。优先从 PATH 查找原生 opencode.exe，Windows npm 安装目录是后备候选；非标准安装用 RASBOT_OPENCODE_BIN 指定。不要把实际安装路径写进源码。

`--repo` 或 RASBOT_PRECISION_REPO 显式指定领域项目；省略时的 ../PrecisionTesting-main 是相对当前工作目录的便利默认值，不是内置依赖。PrecisionTesting、模型、工具链和硬件都不随 RASBot 包分发。

## 尚未支持

Linux/macOS 的平台核心模块可以测试，但托管凭据保护当前主动拒绝非 Windows。真正跨操作系统运行需要提供系统凭据存储适配并验收，不应通过明文保存密钥掩盖此限制。Python/OpenCode 版本升级也需做 API 兼容检查。

## 提交前检查

`git diff --cached --name-only` 查看实际提交文件；`git diff --cached` 审查内容。忽略规则不会保护已经跟踪的文件。把运行目录改到仓库内其他位置时，应补充对应忽略规则。不要提交整个本机工作目录压缩包。

测试在临时目录生成数据库、会话和合成样本，不依赖历史本机任务。验收文档中的历史统计描述验证范围，不作为程序运行输入。
