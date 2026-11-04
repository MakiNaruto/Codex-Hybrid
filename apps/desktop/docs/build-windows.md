# Windows x64 桌面构建

在 Windows x64 本机运行 `scripts/build_desktop.ps1`，生成桌面开发预览的便携目录。脚本依次冻结 Python 后端、执行隔离验证、编译 Tauri release 窗口，并检查分发目录中的后端。当前脚本已在 macOS 上检查平台选择与打包参数，Windows 编译、窗口运行和干净机器验收仍待实机执行。

## 准备环境

- Windows x64 和 x64 Python 3.11+。
- Rust/Cargo，安装 `x86_64-pc-windows-msvc` 工具链和目标。
- Visual Studio 2022 Build Tools 的“使用 C++ 的桌面开发”组件，包含 MSVC 和 Windows SDK。
- Microsoft Edge WebView2 Runtime，用于运行桌面窗口。

静态前端直接使用仓库资源，无需 Node。在仓库根目录的 PowerShell 中准备 Python 环境。

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

默认使用根目录 `.venv/Scripts/python.exe`。可通过 `STAGE0_PYTHON` 指向另一个已安装项目依赖的 x64 Python。缺少 PyInstaller 时，脚本会把固定版本安装到 `apps/desktop/build/stage0/tools-windows-x86_64/`。Cargo 优先读取本地锁定依赖，缺少时联网下载；可用 `CARGO_HOME` 指定缓存目录。

原生工具、依赖安装、冻结验证或 Rust 编译失败时，脚本立即报错停止。构建后不自动启动窗口。

## 产物和验证

输出目录为 `apps/desktop/dist/stage0/windows-x86_64/`，分发时保留以下两个文件在同一目录。

- `Codex Hybrid.exe` 为桌面窗口，嵌入 Windows ICO 图标和管理页。
- `hybrid-stage0-probe.exe` 为单文件 Python 后端，包含 Windows 动态加载的本机集成模块。

双击 `Codex Hybrid.exe` 启动。构建目录中的验证报告分别为 `apps/desktop/build/stage0/frozen-results-windows-x86_64.json` 和 `packaged-results-windows-x86_64.json`。隔离检查使用临时目录和模拟上游，需要允许本地回环监听；不会操作真实 Codex 配置或启停真实 Codex。

当前交付为开发预览便携目录。安装包、代码签名，以及无 Python 的 Windows 干净环境验收仍需后续完成。实机需检查窗口启动、图标、后端调用、配置操作和现有 Windows 退出行为。macOS 的 `.app` 构建入口见 [Intel Mac 构建流程](build-macos-intel.md)。
