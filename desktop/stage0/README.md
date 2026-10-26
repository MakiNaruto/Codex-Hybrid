# Stage 0：隔离验证工具

这些文件验证打包、管理接口拆分和网关生命周期，不是生产桌面客户端。不读取真实对话，不修改用户 Codex 配置，不重启真实 Codex，不发送付费 API 请求。配置测试只使用自动创建并清理的临时目录；`probe.py` 非 report 模式要求显式 settings 路径及 fixture 标记。

## Python 验证

在仓库根目录，使用目标架构的 Python 3.11+ 创建环境并安装项目依赖和构建依赖。例如 Windows PowerShell：

```powershell
python -m venv desktop/.venv-stage0
desktop/.venv-stage0/Scripts/python.exe -m pip install -r requirements.txt -r desktop/stage0/requirements.txt
desktop/.venv-stage0/Scripts/python.exe -X utf8 desktop/stage0/preflight.py
desktop/.venv-stage0/Scripts/python.exe -X utf8 desktop/stage0/build_probe.py
desktop/.venv-stage0/Scripts/python.exe -X utf8 desktop/stage0/verify.py --output desktop/build/stage0/source-results.json
desktop/.venv-stage0/Scripts/python.exe -X utf8 desktop/stage0/verify.py --executable desktop/dist/stage0/hybrid-stage0-probe.exe --output desktop/build/stage0/frozen-results.json
desktop/.venv-stage0/Scripts/python.exe -X utf8 desktop/stage0/audit_config.py
```

macOS Apple Silicon：先确认终端与 Python 均为 arm64，而非 Rosetta x86_64。

```sh
python3 -m venv desktop/.venv-stage0
desktop/.venv-stage0/bin/python -m pip install -r requirements.txt -r desktop/stage0/requirements.txt
desktop/.venv-stage0/bin/python -X utf8 desktop/stage0/preflight.py
desktop/.venv-stage0/bin/python -X utf8 desktop/stage0/build_probe.py
desktop/.venv-stage0/bin/python -X utf8 desktop/stage0/verify.py --output desktop/build/stage0/source-results-macos.json
desktop/.venv-stage0/bin/python -X utf8 desktop/stage0/verify.py --executable desktop/dist/stage0/hybrid-stage0-probe --output desktop/build/stage0/frozen-results-macos.json
desktop/.venv-stage0/bin/python -X utf8 desktop/stage0/audit_config.py
```

`verify.py` 在指定输出路径时自动创建报告父目录。依赖安装和打包需要联网；验证过程的上游响应由内存模拟，网关健康检查仅访问临时本地端口。

当前 Windows 会话将 PyInstaller 安装在 `desktop/build/stage0/tools`，没有安装到全局 Python；可使用现有 `.venv/Scripts/python.exe` 和 `build_probe.py --tools-dir desktop/build/stage0/tools` 重现。该临时工具目录不随仓库提交。

`verify.py` 使用中文和空格路径；冻结模式把单文件可执行程序复制到临时目录、去除 Python 搜索变量并缩小 PATH，验证脱离源码启动。宿主机仍安装有 Python，因此这不能替代无 Python 的干净机器验收。

冻结程序通过 PyInstaller 显式启用 UTF-8 和无缓冲 stdio，避免 Windows 默认编码及控制响应缓冲问题。生产阶段仍应将持久化文件 I/O 明确为 UTF-8；不能据此声称旧 CLI 在非 UTF-8 模式下的问题已经修复。

## Tauri 最小窗口

先完成 Python 打包，生成带目标平台后缀的 sidecar，再准备 Tauri 2 对应的 Rust、系统编译工具和 WebView 运行环境。此原型使用静态前端，不需要 Node/npm。

```sh
cargo run --manifest-path desktop/stage0/tauri/Cargo.toml --features custom-protocol
```

窗口中的“检查打包程序”只经固定 Tauri 命令执行 sidecar 的 `report` 模式；前端没有通用 shell 或文件权限。此窗口不包含真实 Codex 的启停操作。

本次 Windows 会话未找到 Rust/Cargo、现代 MSVC 工具链及 vswhere，尚未编译或运行此骨架。首轮实际编译后应提交生成的 Cargo.lock，冻结依赖解析结果；目前依赖声明不是已验证的版本组合。

## 后续实机步骤

1. Windows 补齐构建工具后运行最小窗口，确认按钮能返回 frozen、UTF-8 和静态资源报告。
2. 在 macOS arm64 本机依次执行 Python 构建、20 项验证、Tauri 窗口检查，并记录输出。
3. 在无 Python 的干净目标环境测试产物；校验系统安全提示、运行时依赖、签名和临时目录策略。
4. 在专门的测试会话中验证真实 Codex 的正常关闭、重新打开、多窗口与任务状态读取；不要在承载验证操作的活动会话里关闭 Codex。
5. 配置事务、目录互斥、并发活动观测尚未实现到生产代码；后续按实施计划验证，不能将这里的 stdio 探针视为完整控制协议。

输出在 desktop/build/stage0 和 desktop/dist/stage0，属于可再生验证产物。Tauri target、gen 和专用虚拟环境均应忽略，不提交二进制或凭据。
