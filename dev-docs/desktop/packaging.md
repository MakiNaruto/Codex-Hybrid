# 桌面打包契约

当前 Tauri 2 窗口与 PyInstaller 后端共享 `src/management/web/` 资源。构建与打包必须同时更新窗口、sidecar 和运行库，旧进程需正常退出后重新启动。平台构建命令见 [macOS](build-macos.md)与 [Windows](build-windows.md)。

| 契约 | macOS Intel | Windows x64 |
| --- | --- | --- |
| PyInstaller 形式 | onedir | onefile |
| 独立后端 | 带 `x86_64-apple-darwin` 后缀及相邻 `_internal/` | 便携目录内 `hybrid-stage0-probe.exe` |
| 应用布局 | 脚本组装 `.app`，包含运行库与 Frameworks 链接 | 完整双 EXE 便携目录 |
| 窗口构建 | debug 开发预览 | release 开发预览 |
| 发布检查 | 运行包内 sidecar，临时 HOME 验证 | 临时发布目录内验证后替换，失败恢复 |

macOS 包内后端需要正确的 `Contents/Frameworks` 运行库布局，不能只复制单个可执行文件。直接运行 debug 壳也需要相邻运行库。Windows 后端与窗口必须位于同一分发目录。

动态导入的 `codex_integration.platforms.macos.client`、`codex_integration.platforms.windows.client` 及 Windows 进程/Restart Manager 依赖必须进入各自冻结清单。冻结入口调用 `multiprocessing.freeze_support()`。`report` 返回成功或源码单元测试通过后，还需验证冻结控制器的真实本地 worker 启停与退出清理。

`build/`、`dist/`、Cargo target、工具缓存和验证日志均为可再生产物。应用名、sidecar 名和标识仍含 preview/stage0，D08 已评审确认本轮保留现有身份和阶段产物目录。官方 bundle、签名、公证、安装更新及干净机器验证列入[状态清单](status.md)。

历史布局决策与性能测量保留在[macOS 原始记录](../archive/desktop/build-macos-intel-history.md)与[Windows 原始记录](../archive/desktop/build-windows-history.md)。首次与重复启动测量条件不同，不能合并推导首次打开耗时保证。

## 兼容、权限与发布验收

打包保留现有 CLI 命令、HTTP 路径和用户数据格式。新目录或包名迁移同时核查 setuptools 白名单、静态 package-data、PyInstaller hidden imports、冻结多进程 spawn 与私有命令完整性。Unicode/空格目录和最小 PATH 启动纳入冻结验证。POSIX 私有权限和 Windows 用户目录 ACL 分平台检查。

发布里程碑包括当前 Intel 测试包、后续 Windows/arm64 测试包，以及签名后公开分发。正式发布前分别确定 macOS 账号、证书、签名/公证，Windows 签名方案，以及构建凭据管理。测试包通过后继续验收首次安装、兼容旧数据、手动覆盖升级保留数据、多窗口正常重启、并发流式请求、工具与子任务、网络异常、持续运行和日志轮转。

## 本轮资源核对

本轮 wheel 已构建，包含当前 107 个 Python 模块和 16 个网页资源，覆盖嵌套 `shared/`、`features/` 脚本。HTTP 静态入口为五个嵌套脚本分别登记固定路径，PyInstaller 按完整相对路径收集资源。最终 wheel 已核对固定 IPC 错误码、两个 CLI 入口及无旧模块夹带。源码/冻结/应用内三报告均为最终 21 项、16 资源通过，冻结控制器隔离生命周期另 1 项通过。完整范围见[验证矩阵](status.md#本轮验证矩阵)。
