# 桌面日常开发

先读仓库 [AGENTS.md](../../AGENTS.md)，再确认目标平台。Tauri 使用共用管理页面，Python 管理业务和本机集成仍由 `src/management/` 与 `src/codex_integration/` 提供。桌面外壳只负责固定命令、会话与平台窗口行为。

## 首次准备

从干净检出开始，在仓库根目录准备 Python 3.11+ 和项目依赖。原生工具链分别按 [macOS](build-macos.md)或 [Windows](build-windows.md)安装。静态页面构建不需要 Node，JS 检查需要 Node。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Windows 改用 `py -3 -m venv .venv` 和 `.venv/Scripts/python.exe`。构建依赖由平台构建入口按需安装，构建缓存与输出目录可重新生成。

## 调试入口

- `src/management/web/` 提供共用页面，`app.js` 装配 `shared/` 与 `features/`，原 models/diagnostics/usage/desktop 接口保留。
- `desktop/src-tauri/src/main.rs` 装配和注册固定命令，`ipc.rs` 管理 sidecar 与请求，`lifecycle.rs` 处理窗口和退出。
- `desktop/sidecar/main.py` 分派冻结入口，包括 `desktop-controller`。
- `src/codex_integration/controller.py` 处理常驻控制会话。
- `src/codex_integration/client.py` 是共享本机集成入口，平台实现分别位于 `src/codex_integration/platforms/windows/` 与 `platforms/macos/`，旧模块保留显式兼容导出。

先按平台指南构建 sidecar，再运行窗口。

```sh
CARGO_HOME="$PWD/desktop/build/stage0/cargo-home" cargo run --offline --locked --target-dir desktop/build/stage0/tauri-target --manifest-path desktop/src-tauri/Cargo.toml --features custom-protocol
```

以上为 macOS 缓存示例。Windows 使用 PowerShell 构建入口准备 MSVC 环境。修改页面后也需重新构建包含页面的窗口。运行中的旧实例不会自动载入新产物。

## 隔离验证与实际操作

验证使用临时 HOME、虚构配置、随机回环端口和模拟上游。真实界面的连接测试会访问供应商且可能计费。真实 Codex 重启应使用专门测试会话，避免关闭承载开发任务的客户端。

隔离 `.app` 启动时直接执行包内程序，并为该进程设置临时 HOME。Launch Services 的 `open` 不保证接收调用者的 HOME。退出后先检查进程，再读取 UI，避免观察工具重新启动应用到真实用户目录。验证命令见[验证指南](validation.md)。

历史问题与决策保留在[开发交接](../archive/desktop/handoff-history.md)。

## 已确认的产品与开发约束

| 主题 | 当前约定与目标 |
| --- | --- |
| 交付 | 普通用户最终可通过桌面完成配置与接入，目标环境无需 Python、Git 或终端；当前开发预览仍需完成安装实机验收 |
| 技术路线 | Tauri 2 + 冻结 Python，Xcode 提供原生 SDK/编译/链接；共用管理业务与页面 |
| 平台推进 | Intel macOS 优先，Windows x64 与 Apple Silicon 分别构建和实机验收；Windows 已有后续 release 构建记录 |
| 来源 | 独立管理与 CC Switch 只读同步二选一，来源各自保留已有数据和模型偏好 |
| 默认目录 | 桌面固定用户默认目录，现有业务数据格式与 CLI 兼容，桌面偏好和运行元数据使用独立文件 |
| 首次使用 | 目标可跳过模型配置进入管理页，当前初始化仍依赖官方配置与缓存，端到端缺口单独验收 |
| 操作 | 一个 Codex 接入主开关协调转发，预览后明确确认；打开应用和初始化保持转发关闭 |
| 更新 | 手动下载安装新版并保留数据，完整产物一起替换 |
| 用户反馈 | 配置结果、索引警告、Codex 操作结果分别显示，模型列表变化提示用户重启客户端 |
| 数据冲突 | 检测并阻止冲突写入，提示检查后重新读取，保留无关字段修改 |
| 诊断 | 运行日志、明确错误和本地白名单诊断导出，用户自行决定分享 |

首版范围排除 Linux、Windows ARM64、开机自启、自动更新、数据目录选择/搬迁、CLI 图形化封装、请求历史、强杀 Codex 与任务恢复保证。任务状态探测已取消，进程识别只表达桌面客户端是否运行。冲突字段可视化修复、网页迁移备份恢复向导、手选 Codex 应用位置亦已移出目标，保留冲突拦截与 CLI 事务恢复。

早期计划排除用量统计，但后续已增加读取保留网关日志的聚合用量页面。当前以[使用指南](../../docs/zh-CN/usage.md#用量统计)和 `management/usage.py` 为准，统计覆盖范围与日志轮转限制应继续验证。

Clash Verge Rev 作为 Tauri 工程参考，引用代码须遵守许可证。完整产品决策来源见[归档计划](../archive/desktop/stage0-plan.md)，实际平台增量以[平台边界](../architecture/platform-boundaries.md)和[生命周期](lifecycle.md)为准。
