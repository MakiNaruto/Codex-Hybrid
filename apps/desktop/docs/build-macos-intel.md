# macOS Intel 构建流程

当前目标：macOS x86_64。采用 Tauri 2 + 冻结 Python；Xcode 用于原生编译、SDK 和链接，不编写 Swift 桌面层。Apple Silicon 和 Windows 后续分别实施。

## 准备环境

在仓库根目录执行。需要 Xcode（完成首次启动和许可）、Rust/Cargo 的 x86_64-apple-darwin 工具链、x86_64 Python 3.11+。本机已验证 Xcode 16、Python 3.14.7、Rust 1.98。静态原型前端不需要 Node。

```sh
uname -m
xcode-select -p
rustc -vV
python3 -c 'import platform; print(platform.machine())'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install --target apps/desktop/build/stage0/tools -r apps/desktop/stage0/requirements.txt
```

架构应为 x86_64，Rust host 应为 x86_64-apple-darwin。首次联网获取已锁定的 Rust 依赖：

```sh
CARGO_HOME="$PWD/apps/desktop/build/stage0/cargo-home" cargo fetch --locked --manifest-path apps/desktop/stage0/tauri/Cargo.toml
```

## 一条命令生成开发预览应用

完成上述 Python 环境准备并安装 Rust、Xcode 后，在仓库根目录执行：

```sh
bash rebuild.sh
# 仅构建，完成后不打开窗口
STAGE0_OPEN_APP=0 bash rebuild.sh
```

脚本支持从空 `build/`、`dist/`、`target/` 目录重建，缺少 PyInstaller 工具时自动安装，Cargo 本地缺少锁定依赖时联网获取。随后执行隔离原型构建，创建应用目录、`Info.plist`、图标及 Python 运行库，并用临时 HOME 检查打包的 sidecar。

产物为 `apps/desktop/build/stage0/Codex Hybrid Tray Preview.app`。更新前先正常退出正在运行的预览应用。清理后的首次构建需要重新下载依赖和完整编译。此入口目前仅支持 Intel macOS，开发预览包尚待签名、公证与干净机器验收。

## 单独重建隔离原型

```sh
bash apps/desktop/stage0/build_macos_intel.sh
```

脚本遇到错误立即停止，依次冻结 Python、运行 20 项隔离验证、使用 Cargo.lock 离线编译 Tauri 窗口。不关闭真实 Codex，不修改真实配置，不发送付费请求。验证使用临时本地端口；执行环境必须允许监听回环端口。可通过 `STAGE0_PYTHON` 指定已安装业务依赖的 Intel Python，通过 `CARGO_HOME` 指定已下载的 Rust 缓存。

输出：

- `apps/desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin`：Tauri sidecar。
- `apps/desktop/stage0/tauri/target/debug/hybrid-stage0-shell`：开发窗口可执行程序。
- `apps/desktop/build/stage0/frozen-results-macos-x86_64.json`：20 项冻结验证报告。

从仓库启动窗口：

```sh
CARGO_HOME="$PWD/apps/desktop/build/stage0/cargo-home" cargo run --offline --locked --manifest-path apps/desktop/stage0/tauri/Cargo.toml --features custom-protocol
```

点击“检查打包程序”，应返回 `frozen: true`、UTF-8 和静态资源报告。窗口已提供配置初始化、厂商与模型编辑保存及主动连接测试；已提供接入预览、确认及恢复入口，完整生命周期与发布验收仍待完成。

## 常见问题和后续打包

找不到 PyInstaller：重新执行工具目录安装命令；构建脚本不会自动联网安装。缺少 crate：执行上面的 `cargo fetch --locked`。Xcode 工具路径错误：在 Xcode 设置中确认 Command Line Tools 选中了已安装的 Xcode。端口权限错误：为本次隔离验证提供本地监听权限。

当前脚本不生成正式 `.app` 或 `.dmg`，也不使用此前手工拼装的 `.app` 作为交付包。私有控制协议、管理界面和接入预览已接入；下一阶段完成托盘及完整退出体验，再加入 Tauri 官方 bundle 工具、release 构建、应用资源、版本及校验和。最终在无 Python/Git/源码的 Intel Mac 环境验收；签名和公证另行完成。原型编译成功不等同于完整应用可发布。

## 管理预览与私有操作

窗口现通过固定 Tauri 命令 `desktop_snapshot` 调用冻结程序的 `desktop-snapshot` 模式，读取 `~/.codex-hybrid/settings.json` 指向的现有模型来源；不接受前端路径、命令或任意 shell 参数。CLI 的环境变量目录覆盖不应用于桌面默认路径。

快照返回来源类型、选定的可编辑厂商/模型字段及公共模型目录，复用既有 YAML / CC Switch 解析逻辑；不返回凭据、管理令牌或整份原始配置。缺少配置显示空状态，配置不可读显示错误，不自动初始化。独立 desktop-snapshot 回归入口仍是单次只读进程；桌面窗口改由常驻会话读取，已配置时允许建立锁及清理完成的事务记录，详见文末。

只读快照不启动网关或管理 HTTP 监听、不发送连接测试、不切换接入，也不修改 Codex。模型表中的“已加入目录”只是现有配置状态，不代表远端连接或客户端加载成功。目前支持初始化独立管理配置、编辑厂商和模型及主动连接测试；接入操作随后已接入，macOS 托盘基础入口已加入，详见文末常驻控制说明。


编辑与测试使用固定 `desktop_manage` 命令：请求经 stdin 传入，不把 Key 放入命令行。单次管理入口限定初始化、保存、测试；常驻入口另提供下文接入与退出操作。请求上限 64 KiB，不接受路径。初始化要求官方 Codex 已生成配置与模型缓存；缺少时给出提示。首次初始化保留恢复基线，启用管理鉴权要求，Codex 配置保持不变。

保存复用现有业务方法和私有文件写入，Key 留空保留，未编辑的高级参数保留；配置版本不一致或已有服务实例时拒绝。CC Switch 保持只读。模型来源启用状态与是否加入目录分别展示；目前尚未提供独立调整目录成员的控件。连接测试使用已保存的配置，用户点击才发送，可能消耗额度；验证测试使用模拟上游，不发送付费请求。草稿打开时刷新及其他厂商编辑会被阻止，失败保留草稿，显式取消才丢弃。macOS 关闭窗口已调用隐藏以保留草稿，跨隐藏的实机验收仍待完成。


协议与边界见 [私有管理接口](private-management.md)。当前仍为开发预览，尚未生成正式安装包。


## 常驻控制、接入与退出预览

窗口现在复用一次启动的 `desktop-controller` 私有进程，初始化、保存、预览、确认和状态读取共用会话。旧单次命令保留作独立回归入口。启动时不自动启用接入；“预览开启/关闭接入”先展示活动和索引影响，勾选确认后才应用事务。Codex 操作默认询问且不勾选；开启、关闭方向可分别记住偏好。残留 project 配置需显式恢复服务或关闭接入。

当前退出方式：先关闭接入，再点击“退出应用”。如仍有活动、相关 Codex 进程或状态未知，网关会保留且退出被拒绝。macOS 关闭窗口隐藏到 CH 托盘，保留草稿和服务；Cmd+Q 与托盘退出走同一安全检查。异常断连会清理网关进程并保留配置，下一次要求恢复选择；异常清理不保证请求不中断。


运行环境需允许临时回环监听，冻结程序还需 PyInstaller 本地进程/信号量权限。打包入口包含 `multiprocessing.freeze_support()`，冻结多进程需要实机验收网关启停与退出清理，不能只凭编译成功判断可用。


当前完成项与后续顺序见[开发交接](handoff.md)；手工测试包的终端启动方式也记录于该文档。

## 首次配置加载与运行库（2026-11-01）

macOS 后台程序改用 PyInstaller `--onedir`，避免每次打开应用时解压单文件运行库。Windows 仍使用 `--onefile`。Intel 构建仍输出带 target 后缀的 sidecar，但它必须与 `apps/desktop/dist/stage0/_internal/` 一起使用；不能单独分发该可执行文件。

`build_macos_intel.sh` 在编译后把运行库复制到 `tauri/target/debug/_internal/`，支持直接运行未打包的壳。根目录 `rebuild.sh` 同时更新手工预览应用的 `Contents/MacOS/_internal/`。隔离验证脚本也会复制相邻运行库。当前仍使用手工预览 `.app`，`bundle.active=false`，这不是已完成的 Tauri 安装包打包流程。

桌面控制器创建管理对象时会调用与网页服务相同的 `start_sync()`：首次状态读取前填充 CC Switch 模型缓存并发布目录，随后持续同步来源变化。它只更新管理配置与模型目录，不会开启接入、启动网关或操作 Codex。未初始化时仍需显式初始化。

本机 Intel 隔离验证：桌面源码 43 项、CC 同步 20 项、打包选择 5 项、JS 60 项通过；新冻结程序的 20 项独立打包验证通过。旧 onefile 在空临时 HOME 中启动至退出约 14.1 秒；新 onedir 首次运行约 24.0 秒，后续两次到首次状态响应分别约 0.70 / 0.50 秒。首次运行与后续重复运行不可直接当作同一条件比较，不能据此保证新构建首次打开也在一秒内。未对实际用户配置或真实 Codex 启停进行验收。
