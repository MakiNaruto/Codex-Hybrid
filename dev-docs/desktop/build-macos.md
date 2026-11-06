# macOS 构建

当前顶层入口仅接受 Intel macOS x86_64。Apple Silicon 的底层目标映射不能代替 arm64 原生构建与验收。Windows 使用[独立指南](build-windows.md)。

## 干净检出准备

需要完成首次启动与许可的 Xcode、Rust/Cargo 的 x86_64-apple-darwin 工具链、x86_64 Python 3.11+。在仓库根目录执行。

```sh
uname -m
xcode-select -p
rustc -vV
python3 -c 'import platform; print(platform.machine())'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

主机与 Python 架构应为 x86_64。构建入口会安装缺失的固定版本 PyInstaller，并先离线获取锁定 Cargo 依赖，缺失时联网获取。可通过 `STAGE0_PYTHON` 指定已安装项目依赖的 Intel Python，`CARGO_HOME` 指定缓存。

## 构建和产物

先正常退出正在运行的预览应用，再执行。

```sh
STAGE0_OPEN_APP=0 bash scripts/build_desktop.sh
# 构建后打开应用
bash scripts/build_desktop.sh
```

脚本依次完成冻结、隔离验证、Cargo 编译、运行库和图标组装、应用内 sidecar 检查。开发预览产物为 `apps/desktop/build/stage0/Codex Hybrid Tray Preview.app`。默认运行模式会在完成后打开应用。

需要分步调试时，可准备工具并只构建 sidecar，再执行验证与 Cargo。完整入口包括依赖准备、组装和应用内检查。

```sh
.venv/bin/python -m pip install --target apps/desktop/build/stage0/tools -r apps/desktop/tools/requirements.txt
.venv/bin/python -X utf8 apps/desktop/tools/build_sidecar.py --tools-dir apps/desktop/build/stage0/tools
CARGO_HOME="$PWD/apps/desktop/build/stage0/cargo-home" cargo fetch --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
```

独立 sidecar 位于 `apps/desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin`，必须与相邻 `_internal/` 一起使用。debug 窗口位于 `apps/desktop/build/stage0/tauri-target/debug/hybrid-stage0-shell`。冻结报告位于 `apps/desktop/build/stage0/frozen-results-macos-x86_64.json`。

## 失败定位与验收范围

Xcode 错误先检查 `xcode-select -p` 及 Xcode 中 Command Line Tools 选择。缺少 crate 时运行锁定依赖预取，缺少 PyInstaller 时执行上述工具安装。隔离验证需要本地回环监听及冻结进程所需的权限。

当前 `.app` 由脚本组装，Tauri 官方 bundle、正式 release 安装包、签名、公证及无 Python/Git/源码的干净环境验收仍待完成。历史 Intel 构建记录见[原构建文档](../archive/desktop/build-macos-intel-history.md)与[验证证据](../archive/desktop/stage0-validation.md)，2026-11-06 根构建入口已完成最终重冻与组装，Intel locked Cargo check/test/build、源码/冻结/应用内隔离检查通过，具体范围见[本轮矩阵](status.md#本轮验证矩阵)。窗口和托盘实机未在本轮运行。
