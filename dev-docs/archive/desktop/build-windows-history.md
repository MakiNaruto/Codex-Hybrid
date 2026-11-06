> 历史归档，保留原始决策、日期与验证范围。当前操作见[桌面开发导航](../../desktop/README.md)。原位置为 `desktop/docs/build-windows.md`。原文历史路径与命令仅用于理解当时执行条件。

> 当前主题指南见[桌面开发文档](../../desktop/build-windows.md)。本文保留历史决策与按日期记录的验证范围，部分早期描述已被后续增量更新。

# Windows x64 桌面构建

在 Windows x64 本机运行 `scripts/build_desktop.ps1`，生成桌面开发预览的便携目录。脚本依次冻结 Python 后端、执行隔离验证、编译 Tauri release 窗口，并检查分发目录中的后端。2026-11-05 用户在 Windows 本机确认，安装下述 Build Tools 组件后解决了 `link.exe not found` 问题；此反馈不代表窗口运行和干净机器验收已完成。

## 准备环境

- Windows x64 和 x64 Python 3.11+。
- Rust/Cargo，安装 `x86_64-pc-windows-msvc` 工具链和目标。
- Visual Studio 2022 Build Tools 的“使用 C++ 的桌面开发”组件，包含 MSVC 和 Windows SDK。
- Microsoft Edge WebView2 Runtime，用于运行桌面窗口。

先安装 Windows 原生编译工具：

1. 下载并运行 [Visual Studio 2022 Build Tools 安装器](https://aka.ms/vs/17/release/vs_BuildTools.exe)。
2. 在安装器中勾选 **使用 C++ 的桌面开发**，确认包含 **MSVC x64/x86 生成工具** 和 **Windows 10/11 SDK**，然后完成安装。这些组件提供 Rust 编译需要的 `link.exe` 和系统库。
3. 在 PowerShell 中通过 winget 安装 Rustup，按安装提示完成 Rust 工具链安装：

   ```powershell
   winget install Rustlang.Rustup
   ```

安装完成后重新打开 PowerShell，使 Rust/Cargo 的 PATH 设置生效。

静态前端直接使用仓库资源，无需 Node。在仓库根目录的 PowerShell 中准备 Python 环境，并确认 Rust 的 MSVC 目标已安装。

```powershell
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
rustup target add x86_64-pc-windows-msvc
```

## 构建

先正常退出正在运行的开发预览，然后执行以下命令。脚本也支持从其他工作目录启动。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

默认使用根目录 `.venv/Scripts/python.exe`。可通过 `STAGE0_PYTHON` 指向另一个已安装项目依赖的 x64 Python。缺少 PyInstaller 时，脚本会把固定版本安装到 `desktop/build/stage0/tools-windows-x86_64/`。Cargo 优先读取本地锁定依赖，缺少时联网下载；可用 `CARGO_HOME` 指定缓存目录。

原生工具、依赖安装、冻结验证或 Rust 编译失败时，脚本立即报错停止。构建后不自动启动窗口。

### `link.exe not found` 排查

Rust 的 MSVC 目标需要 Visual Studio 提供的链接器。安装 Rust、VS Code 或仅执行 `rustup target add` 都不会安装 `link.exe`。多个 crate 同时报 build script 编译失败，通常是缺少同一个链接器造成的连带错误。

按上方“准备环境”中的下载链接安装 Build Tools；如果已经安装，则打开 Visual Studio Installer 修改组件，选中 **使用 C++ 的桌面开发**，确认包含 **MSVC x64/x86 生成工具** 和 **Windows 10/11 SDK**。安装完成后重新打开 PowerShell，再运行上述构建命令。此方法已由用户在 Windows 本机确认解决该报错。

脚本会先通过 `vswhere.exe` 查找已安装的 C++ 工具，加载 `VsDevCmd.bat` 的 x64 环境，再检查 `cl.exe`、`link.exe`、SDK 的 `rc.exe` 和库路径。缺少组件会在下载依赖和冻结后端之前报错。如果自动定位不可用，可从 Visual Studio 的 **Developer PowerShell** 中选择 x64 目标后执行脚本。仅把 `link.exe` 加入 PATH 不足以替代完整的编译环境。

## 产物和验证

输出目录为 `desktop/dist/stage0/windows-x86_64/`，分发时保留以下两个文件在同一目录。

- `Codex Hybrid.exe` 为桌面窗口，嵌入 Windows ICO 图标和管理页。
- `hybrid-stage0-probe.exe` 为单文件 Python 后端，包含 Windows 动态加载的本机集成模块。

双击 `Codex Hybrid.exe` 启动。构建目录中的验证报告分别为 `desktop/build/stage0/frozen-results-windows-x86_64.json` 和 `packaged-results-windows-x86_64.json`。隔离检查使用临时目录和模拟上游，需要允许本地回环监听；不会操作真实 Codex 配置或启停真实 Codex。

当前交付为开发预览便携目录。安装包、代码签名，以及无 Python 的 Windows 干净环境验收仍需后续完成。实机需检查窗口启动、图标、后端调用、配置操作和下述托盘生命周期。macOS 的 `.app` 构建入口见 [Intel Mac 构建流程](../../../desktop/docs/build-macos-intel.md)。


## Windows 托盘

Windows 桌面预览提供与 macOS 相同的“管理、混合路由、重启 Codex…、退出…”菜单。右键点击通知区域图标打开菜单，双击图标恢复管理窗口（包括最小化窗口）。关闭窗口会隐藏到托盘，保留未保存草稿、控制会话与网关；需要结束应用时使用托盘“退出…”或窗口退出入口。

混合路由的勾选表示配置已接入，详细接入/网关状态见图标提示。原生层每五秒尝试刷新状态，隐藏窗口后仍有效；控制会话忙时跳过，断连后禁用切换，不自动重建会话。托盘切换、重启和退出所需的原生提示框独立显示，管理窗口保持原有的显示、最小化或隐藏状态。取消、Escape、关闭确认框均不提交。未保存草稿或已有弹窗会阻止操作。

切换仍复用管理预览与提交；独立重启复用 Windows 的安装识别、进程身份校验、Restart Manager 正常退出和 Store 激活。重启票据两分钟内有效且仅能使用一次，不运行时不会通过独立重启入口启动。路由已关闭且网关没有在途请求时可直接退出。接入仍开启、网关有在途请求，或网关尚未停止且无法确认路由或请求状态时，退出会显示原生确认框。确认后关闭 Codex Hybrid 和它自己的网关，保留已保存的路由配置。退出确认框等待期间管理服务继续响应页面刷新；取消则继续运行。Windows 的单实例约定与系统代理选择不变。

回归命令：`python desktop/stage0/test_tray_lifecycle.py`，以及在 MSVC x64 环境运行 `cargo test --offline --locked --manifest-path desktop/stage0/tauri/Cargo.toml --bin hybrid-stage0-shell`。Python 检查模拟 Windows/macOS 分支，不操作真实 Codex。完整菜单点选、隐藏后的草稿/网关保留、原生确认框焦点及真实 Codex 重启仍需实机验收；macOS 本轮未进行实机验证。
