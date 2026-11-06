# 桌面工程

Codex Hybrid 的 Tauri 外壳、冻结 Python 后端、构建与验证工具位于本目录。浏览器与桌面共用 `src/management/web/`，管理和本机业务复用 `src/management/` 与 `src/codex_integration/`。

- [开发导航](../../dev-docs/desktop/README.md)覆盖当前环境、双平台构建、资源、协议、生命周期和验证。
- [当前架构](../../dev-docs/architecture/repository-layout.md)说明当前目录与剩余迁移目标。
- [平台边界](../../dev-docs/architecture/platform-boundaries.md)说明代理、进程和退出差异。
- [当前状态](../../dev-docs/desktop/status.md)区分实现、历史测试和本轮待验收项。
- [中文桌面指南](../../docs/zh-CN/desktop.md)与[英文桌面指南](../../docs/en/desktop.md)面向用户。
- [历史归档](../../dev-docs/archive/desktop/README.md)保留原始计划、交接及验证范围，`docs/` 旧路径保留章节导航。

## 当前构建入口

命令从仓库根目录执行，先按平台开发指南准备依赖。源码按 `src-tauri/`、`sidecar/`、`tools/`、`validation/` 和 `tests/` 归类，根脚本转发至平台工具。

```sh
STAGE0_OPEN_APP=0 bash scripts/build_desktop.sh
```

Intel macOS 输出 `apps/desktop/build/stage0/Codex Hybrid Tray Preview.app`。Windows x64 使用 PowerShell。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

Windows 输出 `apps/desktop/dist/stage0/windows-x86_64/`，窗口与后端两个 EXE 一起分发。Apple Silicon 仍待原生构建与验收。当前为开发预览，正式安装包、签名、公证和干净环境验收仍待完成。本轮 Intel Cargo 与冻结检查已通过，窗口操作、Windows 和 Apple Silicon 的本轮原生验收仍待执行，具体范围见状态页。
