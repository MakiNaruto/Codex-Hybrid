# 桌面版阶段 0 验证记录

验证日期：2026-10-26。当前结论：Python sidecar 路线已在本机得到实测支持；阶段 0 尚未全部通过，Tauri 原生窗口、macOS 实机和真实 Codex 重启仍待验证。

本次仅新增隔离探针、最小桌面骨架和文档，未修改生产业务代码、用户 Codex 配置或重启当前 Codex。沿用仓库当前名称 Codex Hybrid 和默认目录约定，不将旧名称重新写回代码。

## 2026-10-28 后续状态说明

下文保留 2026-10-26 探针结果，不代表当前生产实现仍有同样缺口。后续管理网页已增加字段级恢复与冲突校验、会话索引事务、空模型首次使用，以及 Windows / macOS 可选桌面操作；对应代码、自动化覆盖与未完成边界见[对齐记录](web-desktop-alignment.md)。其中第 3 项配置恢复差距已由网页业务层补齐，但不能因此认定旧 CLI 路径、桌面实例互斥或打包验证通过；后续网页已实现管理进程监督独立网关子进程；私有桌面控制协议及打包验收仍未完成。

阶段 0 双平台窗口、打包、真实 Codex 重启仍未完成。2026-10-28 用户确认放弃任务状态探测，只保留 Codex 桌面运行检测；下文相关探测事项为历史记录，不再阻塞验收。下文“本机”指原 Windows 验证环境，不指阅读文档时的当前宿主。

## 结果

| 验证项 | 状态 | 证据及边界 |
| --- | --- | --- |
| 既有协议测试 | 通过 | unittest 的 5 项测试通过；动态协议测试出现既有 HTTPError ResourceWarning |
| 源码探针 | 通过 | 20 项检查；使用 Python 3.14.7、PyYAML 6.0.3、psutil 7.2.2 |
| Windows 独立可执行文件 | 通过当前宿主检查 | PyInstaller 6.22.3 单文件产物，约 13.8 MB；同一组 20 项检查通过 |
| 无监听的配置管理 | 通过 | 占住指定端口时仍能读取空来源、保存厂商、发布目录和执行模拟连接测试 |
| Unicode 路径及模型名 | 明确 UTF-8 后通过 | 临时目录含中文和空格，模型显示名含中文；需固定运行时编码 |
| 生产网关类的子进程运行 | 通过隔离检查 | 使用临时配置和端口，健康检查、加载保存配置及管理 Origin 限制正常 |
| 协作退出 | 通过 | shutdown 控制输入后正常退出，端口释放；控制输入 EOF 后也退出 |
| Windows 应用识别 | 只读检查通过 | 可区分桌面安装与 VS Code backend；桌面窗口程序实际名为 ChatGPT.exe |
| Codex 活动状态 | 未验证，按未知处理 | 可用 CLI 有 app-server/proxy 命令，但尚未连接桌面实际实例获取状态 |
| 正常关闭并重启 Codex | 待专门会话实测 | 没有关闭承载当前工作的真实应用 |
| Tauri 窗口与 sidecar 调用 | 尚未编译 | 最小骨架已准备；当前未发现 Rust/Cargo 和现代 MSVC 构建工具，WebView2 目录可见 |
| macOS arm64 | 待实机 | 已准备原生构建和同一组验证命令；未在本 Windows 会话运行 Mac 产物 |
| 无 Python 的干净机器 | 待验收 | 本次仅清除 Python 搜索路径、缩小 PATH，并复制到仓库外工作目录；宿主仍有 Python |
| 配置恢复事务、实例互斥 | 待实现和验证 | 不能将现有 CLI 的 PID 检查视为完整互斥，也不能直接复用现有恢复开关 |

## 已发现的问题及处理

### 1. 文件默认编码不能依赖 Windows 本机区域设置

当前 Python 的默认编码为 cp936，UTF-8 模式为关闭状态。现有 management.private_write 使用未指定 encoding 的文本写入；含中文路径的 settings.json 会按区域编码写出。隔离进程按 UTF-8 重新读取时触发 UnicodeDecodeError。

探针采用源码入口 `-X utf8`，冻结入口采用 PyInstaller `--python-option "X utf8"`，并固定 stdio 编码假设后通过中文路径及名称检查。生产代码中仍需明确文件编码，并评估历史非 UTF-8 数据，不应仅依靠打包开关掩盖 CLI 的兼容性问题。本次没有改变业务数据格式或自动迁移旧数据。

### 2. 单文件打包的启动器不是实际网关进程

初次冻结验证中，对 Popen 返回的启动器执行 terminate 后，解释器子进程仍持有监听和管道，导致退出等待超时及临时 exe 无法清理。已定位并清理该次隔离探针进程，没有按名称停止其他程序。

探针增加私有 stdin 的 shutdown 与 EOF 退出行为后，通过正常退出、端口释放和控制器断开检查。因此桌面层必须区分协作关闭与强制回收，不能只记录一个 PID 并直接 terminate。未来需结合父进程消失保护和可靠进程树归属验证；单文件与目录式打包的最终选择仍需 Mac、崩溃及冷启动数据。

### 3. 当前路由开关不等于恢复接入前配置

audit_config.py 在临时配置中执行现有开启/关闭循环。原配置没有 model_provider 字段，关闭后新增 model_provider=openai，同时留下本工具的 provider 表，语义并非完全还原。

这与已确定的“恢复接入前原生配置”要求不同。桌面版需单独实现不可被重复开启覆盖的字段基线、冲突检查与恢复事务；保留原先不存在字段的状态，并避免覆盖无关外部变更。该审计是已知差距记录，不代表该功能已修复。

### 4. Codex backend 与桌面主程序必须区分

本机同时存在 VS Code 扩展的 codex.exe、桌面安装下的 codex.exe，以及 WindowsApps 包中的 ChatGPT.exe。读取 AppxManifest 确认桌面 Application Id=App，Executable=app/ChatGPT.exe。

因此不能使用 Stop-Process -Name codex 之类的操作实现重启，也不能只把 backend 重启当成应用重启。后续需要通过安装身份、进程树和窗口归属定位，采用正常应用退出。当前仅验证识别依据，没有发送关闭窗口消息。

### 5. 任务状态读取仍是未证实能力

官方 App Server 文档存在 thread/status/changed 等状态接口；当前本机 CLI 帮助也列出控制 socket proxy。运行 daemon version 的只读检查在本工具执行环境因无法解析用户目录而失败，这不证明桌面应用没有接口。

尚未验证连接桌面正在使用的实例、状态新鲜度或全窗口覆盖。首版继续执行既定降级：状态不可读时展示未知，由用户确认正常重启；不得通过另起 App Server 或读取旧对话推断全部任务空闲。

## 架构方向与未完成项

已有 Python Gateway 可以实例化并复用 Management，而不构造 HTTP Server；测试证明拆分配置管理与网关监听在技术上可行。但这不意味着配置管理已彻底从 gateway.settings、并发槽、opener 和模型目录中解耦。阶段 1 仍须抽离接口，支持真正无官方目录、无模型和损坏来源的首次使用。

stdio 可作为 Rust 与 Python 的私有控制通道。探针只验证逐行 JSON、请求 ID、方法白名单及协作退出；生产协议还需处理消息大小、超时、并发、取消、事件和 stdout 日志隔离。网关日志当前写 stdout，不能未经隔离直接复用控制流。

本次不冻结 UI 框架。最小 Tauri 窗口使用原生静态页面，目的是先验证系统工具链与 sidecar 调用，避免业务界面掩盖运行时问题。

继续完成阶段 0 的顺序：

1. 补齐 Windows Rust/MSVC 构建条件，实际编译并运行最小窗口，锁定 Cargo 依赖。
2. 在用户的 macOS arm64 设备执行同一套构建与验证，记录真实结果。
3. 在专门测试会话验证 Codex 状态读取与正常重启，并验证失败恢复。
4. 完成配置事务和实例互斥的原型设计与验证，再进入正式业务控制实现。

## 复现与产物

工具说明见 [Stage0 README](../stage0/README.md)。本机产物位于 desktop/dist/stage0，结构化结果位于 desktop/build/stage0/source-results.json、frozen-results.json 和 config-audit.json；这些目录被 Git 忽略，报告可按说明重建。二进制为验证探针，不是可日用客户端或安装包。

参考：[Tauri 系统前置条件](https://v2.tauri.app/start/prerequisites/)、[Tauri 外部程序打包](https://v2.tauri.app/develop/sidecar/)、[PyInstaller 工作方式](https://pyinstaller.org/en/stable/operating-mode.html)、[PyInstaller 构建选项](https://pyinstaller.org/en/stable/usage.html)、[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)。这些文档支持工具机制，不能代替上述待完成实测。
