# Stage 0：隔离验证工具

这些文件用于打包、管理接口拆分及生命周期验证，当前窗口为开发预览，不是正式发布客户端。自动化隔离验证仅使用临时配置和模拟上游，不读取真实对话、不改写真实 Codex 配置、不重启真实 Codex、不发送付费请求。`control` / `gateway` 探针模式要求显式 settings 路径及 fixture 标记。

`desktop-snapshot` 和 `desktop-manage` 是独立的桌面管理入口，默认读取固定用户目录；后者仅在用户主动操作时初始化、保存配置或测试连接。实际使用连接测试会访问供应商并可能计费，不能把隔离测试的无网络边界套用到产品操作。

Intel Mac 的准备和脚本入口见 [Intel 构建流程](../docs/build-macos-intel.md)。Windows x64 已增加 `scripts/build_desktop.ps1`，环境准备和便携目录见 [Windows 构建流程](../docs/build-windows.md)，仍待 Windows 实机编译验收。以下 Windows / Apple Silicon 分步命令不代表已验收。

当前 Tauri 窗口直接打包 `src/management/web/` 的共用管理页，通过私有 `web_api` 白名单连接常驻控制进程。旧 `web/` 历史探针页面已清理，前端开发入口为 `src/management/web/`。首次打开需显式初始化，初始化不会开启接入。

## Python 验证

在仓库根目录，使用目标架构的 Python 3.11+ 创建环境并安装项目依赖和构建依赖。例如 Windows PowerShell：

```powershell
python -m venv apps/desktop/.venv-stage0
apps/desktop/.venv-stage0/Scripts/python.exe -m pip install -r requirements.txt -r apps/desktop/stage0/requirements.txt
apps/desktop/.venv-stage0/Scripts/python.exe -X utf8 apps/desktop/stage0/preflight.py
apps/desktop/.venv-stage0/Scripts/python.exe -X utf8 apps/desktop/stage0/build_probe.py
apps/desktop/.venv-stage0/Scripts/python.exe -X utf8 apps/desktop/stage0/verify.py --output apps/desktop/build/stage0/source-results.json
apps/desktop/.venv-stage0/Scripts/python.exe -X utf8 apps/desktop/stage0/verify.py --executable apps/desktop/dist/stage0/hybrid-stage0-probe.exe --output apps/desktop/build/stage0/frozen-results.json
apps/desktop/.venv-stage0/Scripts/python.exe -X utf8 apps/desktop/stage0/audit_config.py
```

macOS Apple Silicon：先确认终端与 Python 均为 arm64，而非 Rosetta x86_64。

```sh
python3 -m venv apps/desktop/.venv-stage0
apps/desktop/.venv-stage0/bin/python -m pip install -r requirements.txt -r apps/desktop/stage0/requirements.txt
apps/desktop/.venv-stage0/bin/python -X utf8 apps/desktop/stage0/preflight.py
apps/desktop/.venv-stage0/bin/python -X utf8 apps/desktop/stage0/build_probe.py
apps/desktop/.venv-stage0/bin/python -X utf8 apps/desktop/stage0/verify.py --output apps/desktop/build/stage0/source-results-macos.json
apps/desktop/.venv-stage0/bin/python -X utf8 apps/desktop/stage0/verify.py --executable apps/desktop/dist/stage0/hybrid-stage0-probe --output apps/desktop/build/stage0/frozen-results-macos.json
apps/desktop/.venv-stage0/bin/python -X utf8 apps/desktop/stage0/audit_config.py
```

`verify.py` 在指定输出路径时自动创建报告父目录。依赖安装和打包需要联网；验证过程的上游响应由内存模拟，网关健康检查仅访问临时本地端口。

当前 Windows 会话将 PyInstaller 安装在 `apps/desktop/build/stage0/tools`，没有安装到全局 Python；可使用现有 `.venv/Scripts/python.exe` 和 `build_probe.py --tools-dir apps/desktop/build/stage0/tools` 重现。该临时工具目录不随仓库提交。

`verify.py` 使用中文和空格路径；冻结模式把单文件可执行程序复制到临时目录、去除 Python 搜索变量并缩小 PATH，验证脱离源码启动。宿主机仍安装有 Python，因此这不能替代无 Python 的干净机器验收。

冻结程序通过 PyInstaller 显式启用 UTF-8 和无缓冲 stdio，避免 Windows 默认编码及控制响应缓冲问题。生产阶段仍应将持久化文件 I/O 明确为 UTF-8；不能据此声称旧 CLI 在非 UTF-8 模式下的问题已经修复。

## Tauri 最小窗口

先完成 Python 打包，生成带目标平台后缀的 sidecar，再准备 Tauri 2 对应的 Rust、系统编译工具和 WebView 运行环境。此原型使用静态前端，不需要 Node/npm。

```sh
cargo run --locked --manifest-path apps/desktop/stage0/tauri/Cargo.toml --features custom-protocol
```

窗口中的“检查打包程序”只经固定 Tauri 命令执行 sidecar 的 `report` 模式；前端没有通用 shell 或文件权限。窗口另通过固定 `desktop_snapshot` 命令展示本机来源及模型脱敏快照，并通过 stdin 私有操作支持用户主动初始化、保存及测试连接，macOS 已接入可选正常 Codex 操作与独立重启预览，真实启停仍待专门会话实测。隔离验证均使用临时配置与模拟上游；实际使用连接测试可能计费。

最初的 Windows 会话未找到 Rust/Cargo、现代 MSVC 工具链及 vswhere，尚未编译或运行此骨架。2026-11-01 在 macOS x86_64 环境获取依赖并生成 Cargo.lock，后续构建使用 `--locked` 保留解析结果；这不代表目标双平台已验证。当前构建结果与边界见[验证记录](../docs/stage0-validation.md)。

## 后续实机步骤

1. Windows 补齐构建工具后运行最小窗口，确认按钮能返回 frozen、UTF-8 和静态资源报告。
2. 在 macOS arm64 本机依次执行 Python 构建、20 项验证、Tauri 窗口检查，并记录输出。
3. 在无 Python 的干净目标环境测试产物；校验系统安全提示、运行时依赖、签名和临时目录策略。
4. 在专门的测试会话中验证真实 Codex 的运行检测、正常关闭、重新打开及多窗口；任务状态探测已取消。不要在承载验证操作的活动会话里关闭 Codex。
5. 网页业务层已实现配置事务、目录互斥、并发活动观测和网关监督，具体边界见[对齐记录](../docs/web-desktop-alignment.md)。桌面私有控制协议及生命周期仍待验证，不能将这里的 stdio 探针视为完整控制协议。

输出在 apps/desktop/build/stage0 和 apps/desktop/dist/stage0，属于可再生验证产物。Tauri target、gen 和专用虚拟环境均应忽略，不提交二进制或凭据。


## 常驻接入预览

桌面窗口现使用 `desktop-controller` 模式：私有 stdio 会话复用配置管理和网关监督，不开放管理 HTTP 端口。它支持预览/确认接入、明确恢复残留状态及退出检查，详见 [私有控制协议](../docs/private-management.md)。初次加载允许建立管理对象和稳定锁文件，但不启动网关；未配置时不创建数据目录。macOS 已接入 CH 托盘：接入/网关状态、打开窗口、开启/关闭接入预览、重启 Codex 确认、退出；状态由原生层轮询，窗口隐藏不依赖页面计时器。关闭窗口隐藏并保留草稿及服务，Cmd+Q 和托盘退出共用安全检查。Windows 关闭行为保持原状。独立重启票据单次使用、两分钟过期，取消不操作应用；未运行或状态未知时不能重启，退出失败不启动。托盘完整点选和跨隐藏状态保留仍待实机验收。

macOS 打包显式包含动态加载的 `codex_integration.macos_client`；打包入口调用 `multiprocessing.freeze_support()`。仅编译或 report 通过不足以证明后台网关能启动，需要分别在源码和冻结模式下验收后台网关启停及退出清理。Windows 打包清单未在本轮同步改动。
