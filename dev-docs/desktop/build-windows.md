# Windows x64 构建

在 Windows x64 本机从干净检出构建。准备 x64 Python 3.11+、Rust/Cargo 的 `x86_64-pc-windows-msvc` 工具链、Visual Studio 2022 Build Tools 和 Microsoft Edge WebView2 Runtime。

## 环境准备

从 [Build Tools 安装器](https://aka.ms/vs/17/release/vs_BuildTools.exe)安装“使用 C++ 的桌面开发”，包含 MSVC x64/x86 生成工具与 Windows 10/11 SDK。Rust 安装完成后重新打开 PowerShell。仓库根目录执行。

```powershell
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
rustup target add x86_64-pc-windows-msvc
```

## 构建和产物

正常退出运行中的预览应用，在仓库根目录执行。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

根入口转发至 `desktop/tools/build_windows.ps1`，平台入口会加载 MSVC x64 环境，检查编译工具，安装缺失的 PyInstaller，冻结后端并执行隔离验证，再编译 release 窗口。Cargo 使用锁定依赖，离线获取失败时联网获取。`STAGE0_PYTHON` 可指定另一个已安装项目依赖的 x64 Python，`CARGO_HOME` 可指定缓存。

发布前在临时目录验证完整产物，再替换输出目录，失败时恢复原目录。输出为 `desktop/dist/stage0/windows-x86_64/`，必须一起分发 `Codex Hybrid.exe` 与 `hybrid-stage0-probe.exe`。构建完成后不会自动启动窗口。

报告为 `desktop/build/stage0/frozen-results-windows-x86_64.json` 与 `packaged-results-windows-x86_64.json`。隔离验证需要允许本地回环监听。

## 失败定位与验收范围

`link.exe not found` 时检查 Build Tools 的 C++ 工作负载与 SDK。仅安装 Rust 或仅向 PATH 加入 linker 无法提供完整编译环境。入口通过 `vswhere.exe` 和 `VsDevCmd.bat` 加载环境，自动定位失败时可使用 x64 Developer PowerShell。

2026-11-05 的记录包含 Windows x64 release 编译、源码与冻结隔离检查，用户另确认安装 Build Tools 后解决 linker 错误。托盘点选、双击与最小化恢复、弹窗焦点、隐藏保留状态、真实 Codex 重启以及无 Python 的干净机器验收仍需 Windows 实机执行。安装包与签名亦待完成。[原构建记录](../archive/desktop/build-windows-history.md)与[Windows 托盘增量](../archive/desktop/handoff-history.md#2026-11-05-windows-托盘对齐)保留证据范围。

本轮目录迁移未在 Windows 原生执行构建，以上路径与参数已对照当前脚本，原生结果仍需复验。
