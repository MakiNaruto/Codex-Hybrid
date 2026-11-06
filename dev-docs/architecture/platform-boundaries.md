# Windows 与 macOS 平台边界

本页汇总仓库 [AGENTS.md](../../AGENTS.md) 与当前平台实现。单个平台问题在对应模块修复。共享入口变更需核对另一平台既有约定，验证时分别记录宿主、目标与实测层次。

## 上游代理

公共兼容入口为 `src/gateway/transport.py`，实际代理策略位于 `src/infrastructure/proxy/__init__.py`、`windows.py`、`macos.py`，网关转发与管理连接测试共用。每次请求重新读取代理选择。

| 项目 | Windows | macOS |
| --- | --- | --- |
| 来源 | 当前用户手动系统 HTTP/HTTPS 代理 | 显式 `upstream_proxy` 优先，否则 Python `urllib.request.getproxies()` |
| 环境 | HTTP_PROXY、HTTPS_PROXY、ALL_PROXY 不覆盖系统选择 | 保留 Python 的环境与系统发现规则 |
| 显式覆盖 | upstream_proxy 不覆盖系统选择 | 保留显式覆盖能力 |
| 绕过 | 系统绕过规则，忽略继承的 NO_PROXY | 保留 Python 原有规则 |
| 系统代理关闭 | 下次请求直连，实际可达性取决于网络 | 环境或显式代理仍可能生效 |
| 系统代理变更 | 下次请求重新读取，无需重启 | 无显式代理时下次请求重新发现 |

Windows 当前不解析 PAC。TUN 出口由操作系统与代理软件控制。测试矩阵包含开启、换地址、关闭、绕过以及环境和显式配置优先级。一个平台的策略不能推广到另一平台。

## 本机识别、退出与启动

公共入口为 `src/codex_integration/client.py`。Windows 实现分别位于 `src/codex_integration/platforms/windows/client.py`、`processes.py`、`restart_manager.py`，macOS 实现位于 `src/codex_integration/platforms/macos/client.py`。旧平台模块保留精确导出，公共入口延迟导入选定平台。

Windows 使用 Store 安装识别、PID/创建时间校验、Restart Manager 正常退出和应用激活。退出请求后等待与启动窗口确认有独立超时。macOS 从标准目录与 Spotlight 识别并验证应用，用 Apple events 请求退出，Launch Services 启动，仅确认主进程出现。权限不足、安装未识别、进程身份变化或超时时反馈手动处理。

应用检测区分桌面、CLI 与 VS Code，仅本机默认 Codex 数据目录对应且身份可确认的桌面应用可自动操作。进程数不能推导窗口数或任务状态。自动操作只尝试一次正常退出/启动，配置结果与客户端操作结果分别展示。真实操作需要专门测试会话。

## 窗口、托盘与所有权

两个平台关闭窗口均隐藏并保留草稿和服务。托盘状态由原生层轮询，状态未知时禁用路由切换。原生确认框分别使用 macOS AppKit 和 Windows TaskDialog。Windows 右键菜单与双击恢复，macOS Dock 与 Cmd+Q 逻辑各自维护。

macOS 接入中退出先引导恢复原生配置，再检查依赖与安全停服。复用已确认归属的网页服务时，桌面退出仅断开连接。Windows 在路由开启、存在活动或安全状态未知时支持原生退出确认，确认后停止桌面自己的网关并保留路由配置。此行为独立于 macOS 的恢复流程。详见[生命周期](../desktop/lifecycle.md)。

目录互斥和服务所有权以实际锁与身份核查为准，不能用 PID 文件检查替代。Windows 单实例约定与 macOS 复用服务逻辑分别保留。共享控制器的写入、预览票据、异常 EOF 清理和恢复契约需覆盖两端。

## 构建、路径与权限

| 项目 | macOS Intel | Windows x64 |
| --- | --- | --- |
| 编译环境 | Xcode、x86_64 Rust 与 Python | MSVC x64、SDK、Rust 与 Python、WebView2 |
| 后端 | PyInstaller onedir，运行库与 Frameworks 布局 | PyInstaller onefile，动态模块清单 |
| 分发 | 当前脚本组装开发预览 `.app` | release 窗口与后端双 EXE 便携目录 |
| 输出发布 | 组装后执行包内 sidecar 检查 | 临时完整目录验证后替换，失败恢复 |
| 配置权限 | POSIX 私有文件权限 | 用户目录 ACL |
| 安装/服务 | `.sh` 入口 | `.cmd` 与 PowerShell 入口 |

不要将 POSIX chmod 的测试结果解释为 Windows ACL 验收。路径处理需覆盖 Unicode、空格、默认目录与用户可写目录。macOS HOME 隔离启动需直接运行包内程序，Launch Services 不保证继承 `HOME=... open` 的覆盖。

## 验证记录规范

源码、平台模拟、原生编译、冻结 worker、窗口交互和安装实机分别列结果。Intel macOS、Windows x64、Apple Silicon arm64 独立登记。Apple Silicon 底层目标映射尚不足以证明原生可运行。最新缺口见[状态](../desktop/status.md)，命令与验收矩阵见[验证](../desktop/validation.md)。

本轮已运行 Intel Cargo 编译与冻结隔离检查，Windows、Apple Silicon 和真实 Codex 控制仍需独立原生验收。历史归档保留[页面对齐](../archive/desktop/web-desktop-alignment-history.md)与[Windows 增量](../archive/desktop/handoff-history.md#2026-11-05-windows-托盘对齐)的日期与范围。
