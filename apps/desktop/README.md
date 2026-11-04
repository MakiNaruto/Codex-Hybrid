# 桌面应用与构建

本目录保存 Codex Hybrid 的 Tauri 桌面外壳、构建工具、计划与验证记录。CLI、网页端和桌面端共用的 Python 逻辑位于 `src/codex_integration/` 和 `src/management/`；共用界面位于 `src/management/web/`。当前优先 macOS Intel x86_64，Windows x64 已提供构建入口并待实机验收，Apple Silicon 延后。Intel 开发预览已支持配置管理与接入控制，已接入 macOS 托盘状态、接入预览、重启确认与关闭隐藏逻辑，仍待完整托盘实机验收、正式打包和干净环境验收。

- [开发交接与待办](docs/handoff.md)：新会话/agent 先读；当前实现、验证边界、下一步、命令和安全注意事项。
- [Intel Mac 构建流程](docs/build-macos-intel.md)：环境准备、一条命令构建及产物边界。
- [Windows x64 构建流程](docs/build-windows.md)：环境准备、PowerShell 构建入口及便携目录，待 Windows 实机验收。
- [实施计划](docs/plan.md)：已确认的产品范围、生命周期、实施阶段和验收标准。
- [网页与桌面对齐](docs/web-desktop-alignment.md)：当前 demo 规则、代码证据及桌面未完成边界。
- [阶段 0 验证记录](docs/stage0-validation.md)：实测结果、已发现问题与尚未验证的能力。
- [阶段 0 工具说明](stage0/README.md)：Python 探针、Windows/macOS 复现命令与 Tauri 最小窗口。

```text
apps/desktop/
├─ docs/          方案与验证记录
├─ stage0/        隔离验证脚本、Tauri 骨架和验证页面
├─ build/         本地工具依赖、缓存和结构化验证结果（忽略提交）
└─ dist/          打包验证产物（忽略提交）
```

命令示例默认从仓库根目录执行。验证脚本仍复用根目录 `src/` 下的现有业务代码；不会复制一套业务内核到本目录。

目录已从根目录 `desktop/` 迁移至 `apps/desktop/`，Python 包已从 `desktop` 更名为 `codex_integration`。旧构建产物不代表新源码，请使用新路径重新构建；CLI 命令、用户数据目录和管理 API 地址保持原有约定。

### 共用网页管理界面

当前 Tauri 窗口直接打包 `src/management/web/`，与网页端共用模型、接入及诊断页面；不再加载单独的 stage0 预览界面。浏览器使用原有 HTTP API，桌面使用私有 IPC 白名单。首次打开需点击初始化，接入开关仍需预览并确认；macOS 托盘、正常重启和安全退出沿用平台约定。请重新运行 Intel 构建脚本，使窗口资源和 sidecar 同时更新。详情见 [页面对齐](docs/web-desktop-alignment.md)。

## 新电脑继续开发

Git 中保留 Tauri 源码、平台配置、`Cargo.lock`、图标、Python 构建与验证工具，以及 `docs/` 下的计划、协议、交接和验证记录。桌面页面源码位于仓库根目录的 `src/management/web/`，旧 `stage0/web/` 探针页面已清理。

先阅读 [开发交接](docs/handoff.md)，再按 [Intel 构建流程](docs/build-macos-intel.md) 准备 Python、Xcode 和 Rust，安装 Python 依赖并执行 `cargo fetch --locked`，最后运行构建脚本。Windows 与 Apple Silicon 的后续步骤和验收边界保留在 [工具说明](stage0/README.md) 中。

`build/`、`dist/`、`.venv-stage0/`、`stage0/tauri/target/`、`stage0/tauri/gen/` 和 Python 缓存由 Git 忽略，在新电脑按需生成。本机构建产物已清理。Intel Mac 准备好 Python 环境、Rust 和 Xcode 后，在仓库根目录运行 `bash scripts/build_desktop.sh`，会按需下载 PyInstaller 和锁定的 Cargo 依赖，编译并生成 `build/stage0/Codex Hybrid Tray Preview.app`，随后打开应用。设 `STAGE0_OPEN_APP=0` 可仅构建。历史验证结论保留在文档中，日志和测试包随构建重新生成。

Windows x64 使用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1`，输出 `apps/desktop/dist/stage0/windows-x86_64/`，窗口 EXE 与后端 EXE 需一起分发。构建前准备和当前验证边界见 Windows 构建流程。
