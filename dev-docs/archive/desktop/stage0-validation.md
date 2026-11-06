> 历史归档，保留原始决策、日期与验证范围。当前操作见[桌面开发导航](../../desktop/README.md)。原位置为 `apps/desktop/docs/stage0-validation.md`。原文历史路径与命令仅用于理解当时执行条件。

> 当前主题指南见[桌面开发文档](../../desktop/validation.md)。本文保留历史决策与按日期记录的验证范围，部分早期描述已被后续增量更新。

# 桌面版阶段 0 验证记录

验证日期：2026-10-26。当前结论：Python sidecar 路线已在本机得到实测支持；阶段 0 尚未全部通过，Tauri 原生窗口、macOS 实机和真实 Codex 重启仍待验证。

本次仅新增隔离探针、最小桌面骨架和文档，未修改生产业务代码、用户 Codex 配置或重启当前 Codex。沿用仓库当前名称 Codex Hybrid 和默认目录约定，不将旧名称重新写回代码。

## 2026-10-28 后续状态说明

下文保留 2026-10-26 探针结果，不代表当前生产实现仍有同样缺口。后续管理网页已增加字段级恢复与冲突校验、会话索引事务、空模型首次使用，以及 Windows / macOS 可选桌面操作；对应代码、自动化覆盖与未完成边界见[对齐记录](../../../apps/desktop/docs/web-desktop-alignment.md)。其中第 3 项配置恢复差距已由网页业务层补齐，但不能因此认定旧 CLI 路径、桌面实例互斥或打包验证通过；后续网页已实现管理进程监督独立网关子进程；私有桌面控制协议及打包验收仍未完成。

阶段 0 双平台窗口、打包、真实 Codex 重启仍未完成。2026-10-28 用户确认放弃任务状态探测，只保留 Codex 桌面运行检测；下文相关探测事项为历史记录，不再阻塞验收。下文“本机”指原 Windows 验证环境，不指阅读文档时的当前宿主。

## 2026-11-01 Intel 优先与脚本复验

用户已调整为 macOS Intel x86_64 优先，Apple Silicon / Windows 延后。正式 `build_probe.py` 已支持 Intel；新增 `build_macos_intel.sh` 串联冻结、隔离检查和锁定依赖的离线 Tauri 编译。实际执行成功：20 项冻结检查通过，Tauri 开发窗口编译通过；架构选择 3 项及既有桌面分发/macOS 适配 9 项测试通过。构建过程未操作真实 Codex。沙箱内首次执行受 PyInstaller 信号量权限限制，允许本机运行后通过。

这不包含正式 `.app` / `.dmg`、生产管理界面或无 Python 干净环境验收。复现见 [Intel 构建流程](../../../apps/desktop/docs/build-macos-intel.md)。以下保留历史验证记录。

## 2026-11-01 只读管理预览验收

- 新增只读快照测试 4 项通过，包含临时 HOME 下的源码命令和冻结命令复验；覆盖空状态、文件保持不变、凭据不返回、错误不泄露、固定目录不受 CLI 环境变量覆盖。既有 20 项冻结隔离检查和 Intel Tauri 编译再次通过。
- 在临时 HOME、虚构厂商和中文模型下打开真实 macOS Tauri 窗口：显示独立管理、厂商 1、模型 1、中文模型及协议。移走临时 settings 后点击刷新，列表消失并显示未配置提示；没有自动创建配置。
- UI 验证使用手工组装的本地测试 `.app`，只证明窗口及 sidecar 链路，不作为正式打包验收。真实配置、付费连接、Codex 启停、Windows 和 Apple Silicon 均未进行本轮验收。

## 2026-11-01 初始化、编辑保存与主动连接测试

- 源码桌面回归覆盖 16 项：固定 HOME、只读快照、读取期间版本变化、初始化不改写 Codex、管理鉴权要求、Key 不回显及留空保留、过期版本拒绝、未编辑高级字段保留、CC Switch 拒绝写入、跨进程服务互斥、stdin 初始化/保存/回读。源码回归及独立补充测试通过。
- 连接测试通过模拟上游走真实请求构造及流式适配，确认 Authorization、请求地址及完成状态；上游正文和带私密内容的异常均不返回。未执行真实付费请求。
- 最终冻结程序的 stdin 工作流通过（初始化、保存虚构 Key、两次回读，约 56 秒）；已有 20 项冻结隔离检查和 Intel Tauri 编译通过。共享 prepare 仅新增显式目录及鉴权要求参数，默认 CLI 语义保持；网页工作流 16 项、代理规则 10 项通过，不作为 Windows 实机验收。
- 真实 macOS 窗口在独立临时 HOME 中完成：点击初始化、添加厂商与中文模型、保存回读、重新打开编辑（Key 为空）、编辑中刷新被阻止、显式取消草稿。Codex 测试配置内容保持不变，管理配置权限 0600。未点击真实供应商连接测试。
- 最后单独修正前端反馈：保存/初始化成功但回读失败时分别说明，不把已完成的写入显示为未保存；语法检查和 Tauri 再编译通过。使用手工测试 app 验证界面，仍不是正式安装包。

## 2026-11-01 常驻控制与接入闭环

- 桌面改为私有 stdio 常驻控制进程，保持同一管理对象、签名密钥和服务锁；无配置时读取不创建目录，启动不自动启动网关。主开关每次先预览和明确确认，复用现有事务、可选正常 Codex 操作、双方向偏好及网关监督。
- 控制器单元测试 9 项通过；桌面相关源码回归共 26 项通过。覆盖不自动启用、取消/失效预览、启动失败不改配置、正常切换、保留网关时拒绝退出、残留状态显式恢复、无所有权窗口仍可退出。
- 源码及冻结进程集成通过：临时 HOME、随机回环端口，实际启动网关并检查健康，恢复原生路由，再启动后断开控制输入，验证子进程退出及下一次不自动恢复。冻结回归约 52 秒。入口补上 multiprocessing.freeze_support()，没有发送模型推理请求。
- 冻结预览首次暴露打包遗漏：archive_viewer 确认 desktop.client 存在但动态导入的 desktop.macos_client 缺失。仅在 macOS 构建添加 hidden-import；归档确认包含，冻结完整链路随后通过。目标/动态模块选择 4 项测试通过，Windows 打包未同步调整。
- 共享回归：接入事务 12 项、网页工作流 16 项、代理规则 10 项、运行监督 35 项均通过。初次接入事务测试受沙箱临时端口限制，允许本地监听后通过；未降低检查标准。
- 真实 macOS 窗口仅用隔离配置验证：初始原生/停止；预览未改写 Codex 测试文件；不勾选 Codex 自动操作，确认后显示已接入/网关运行；窗口关闭及接入中退出被拦截。关闭接入恢复原生后，由于检测到 Codex 进程而保留网关、拒绝退出，符合保守停服规则。仅按严格路径及临时 HOME 匹配清理该测试窗口，确认其网关端口释放；真实 Codex 未关闭或重启。
- 重新打开原生配置且网关未启动的隔离窗口，点击“退出应用”，进程正常以 0 退出。托盘隐藏、真实 Codex 自动启停、正式 app/dmg、无 Python 干净环境及其他平台仍未验收。
- Intel 一键脚本新增冻结控制进程生命周期回归，防止仅 report/静态窗口成功却不能启用后台网关的回归。最终整条脚本执行成功：20 项冻结检查、冻结控制进程集成（本次约 28 秒）及锁定依赖的 Tauri 编译通过。

## 结果

### 2026-11-01 macOS 构建预检

- 当前命令环境为 macOS 15.6、x86_64；Python 3.14.7 和 Rust 1.98.0 的宿主均为 x86_64，Xcode 16.0 可用。未发现 `/opt/homebrew` 下的 arm64 工具链，`arch -arm64` 无法执行。因此本轮不能验收计划中的 macOS Apple Silicon 产物，也未绕过构建脚本的目标架构检查。
- 使用已有 `.venv/bin/python` 执行源码隔离探针，20 项检查通过；报告为 `apps/desktop/build/stage0/source-results-macos-x86_64.json`（忽略提交）。只验证当前 x86_64 源码环境，不代表 arm64、冻结程序或无 Python 环境通过。
- 首次运行复现旧夹具缺少 `models_cache.json` 导致 `SOURCE_UNAVAILABLE`；已补齐临时官方缓存，保留原有空来源、配置不变、Origin 限制及退出检查。未修改生产业务代码。
- 尝试 `cargo check --manifest-path apps/desktop/stage0/tauri/Cargo.toml --features custom-protocol`，依赖解析因 `index.crates.io` DNS 解析失败而停止，未进入原生编译，也未生成已验证的 Cargo.lock。此次尝试使用仓库内 `CARGO_HOME=apps/desktop/build/stage0/cargo-home`。
- 未修改真实 Codex 配置、未操作真实 Codex 生命周期、未发送付费 API 请求。后续需切换 arm64 原生执行环境，完成 Python 冻结构建、同组探针、Tauri 窗口及干净设备验收。

继续验证：提升执行权限后 `cargo fetch` 下载成功，生成 `apps/desktop/stage0/tauri/Cargo.lock`；`cargo metadata --offline --locked --no-deps` 通过。此前 DNS 失败不再阻塞依赖获取。锁文件仅记录本轮解析结果，不代表双平台构建验证通过。

- 正式配置的 `cargo check --offline --locked` 已进入应用构建脚本，因不存在 `hybrid-stage0-probe-x86_64-apple-darwin` 停止；未制作或伪造该非目标平台 sidecar。
- 为单独检查 Rust 窗口代码，使用临时环境覆盖 `TAURI_CONFIG='{"bundle":{"externalBin":[]}}'`，不修改正式配置。首次复现缺少 `icons/icon.png` 的编译宏错误；补齐 32×32 RGBA 几何占位图标后检查通过。依据为本轮下载的 `tauri-codegen 2.7.4` 的默认图标路径处理。
- 通过命令：`TAURI_CONFIG='{"bundle":{"externalBin":[]}}' CARGO_HOME="$PWD/apps/desktop/build/stage0/cargo-home" cargo check --offline --locked --manifest-path apps/desktop/stage0/tauri/Cargo.toml --features custom-protocol`。日志为 `apps/desktop/build/stage0/cargo-check-shell-only-macos-x86_64.log`。此覆盖仅用于编译检查，不用于正常窗口运行、sidecar 验收或产物交付。
- 本轮没有链接运行窗口或验证按钮，也没有生成安装包。完整构建仍须在两种目标平台配合真实 sidecar 验证；阶段 0 保持未完成。

### 本地 Xcode 验证补充

用户要求尝试本地 Xcode 后，确认 Xcode 16.0、Apple clang 16.0.0 和 macOS SDK 可用。使用 `xcrun clang -arch arm64` 编译并链接最小 C 程序成功，`file` 确认为 arm64 Mach-O；这仅证明 SDK/链接器支持交叉编译，不代表 Rust arm64 标准库、Python arm64 运行环境或应用实机验收已具备。测试文件均在忽略提交的 `apps/desktop/build/stage0/`。

- 使用同样临时排除 sidecar 的 `TAURI_CONFIG`，执行 `cargo build --offline --locked --manifest-path apps/desktop/stage0/tauri/Cargo.toml --features custom-protocol` 成功，耗时约 2 分钟。日志为 `apps/desktop/build/stage0/cargo-build-shell-only-macos-x86_64.log`，产物经 `file` 确认为 x86_64 Mach-O。
- 将桌面壳复制到本地临时 `.app`（`apps/desktop/build/stage0/Codex Hybrid Stage0 Shell.app`，仅包含可执行文件和最小 Info.plist），通过桌面 UI 成功打开 `Codex Hybrid Stage0 Probe` 窗口。真实页面显示中文标题、说明、检查按钮及等待状态，静态资源可加载。
- 点击“检查打包程序”后，页面显示 `检查失败：No such file or directory (os error 2)`，符合本次未包含 sidecar 的条件；证明前端到 Rust 命令的调用和错误返回路径可用，不代表 Python 通信成功。
- 这是 x86_64 桌面壳的编译、链接及窗口运行验证，不是正式 Tauri bundle、安装包或目标 arm64 验收。没有更改正式 `externalBin` 配置，没有修改真实 Codex 配置或操作 Codex 启停。

### x86_64 sidecar 补充隔离验证

- 将阶段 0 固定版本的 PyInstaller 6.22.3 和 hooks 2026.9 安装到仓库内 `apps/desktop/build/stage0/tools`。直接调用 PyInstaller，参数沿用 `build_probe.py` 并明确 `--target-arch x86_64`，产物单独保存为 `apps/desktop/dist/stage0/macos-x86_64/hybrid-stage0-probe`（约 15 MiB）。未放宽正式构建脚本的 Windows x64 / macOS arm64 架构检查，未将 Intel Mac 加入交付范围。
- `.venv/bin/python -X utf8 apps/desktop/stage0/verify.py --executable apps/desktop/dist/stage0/macos-x86_64/hybrid-stage0-probe --output apps/desktop/build/stage0/frozen-results-macos-x86_64.json` 的 20 项检查全部通过，耗时约 51 秒。冻结程序复制到中文及空格临时路径，去除 Python 搜索变量并缩小 PATH，覆盖配置管理、模拟连接、真实临时网关、Origin 限制、协作退出、端口释放及控制通道 EOF 退出。宿主仍安装有 Python，不能视为干净机器验收。
- 将该产物复制为 Tauri 所需的 `hybrid-stage0-probe-x86_64-apple-darwin` 后，正式配置下的 `cargo build --offline --locked --manifest-path apps/desktop/stage0/tauri/Cargo.toml --features custom-protocol` 成功，不再覆盖 `externalBin`。日志为 `apps/desktop/build/stage0/cargo-build-with-sidecar-macos-x86_64.log`。
- 本地临时 `.app` 为 `apps/desktop/build/stage0/Codex Hybrid Stage0 Sidecar.app`，包含 Rust 可执行文件、无目标后缀的 sidecar 和最小 Info.plist；不属于正式 Tauri 安装包。
- 通过真实桌面 UI 启动该 `.app` 并点击“检查打包程序”，按钮显示进行中，随后恢复可点击并返回 JSON：`frozen: true`、`utf8_mode: 1`，Python 3.14.7、psutil 7.2.2、PyYAML 6.0.3，五项静态资源均为 `true`。前端 → Tauri Rust 命令 → 打包 Python → JSON 展示链路通过。没有使用模拟 sidecar 或修改 Rust 命令实现。
- 结论仅适用于当前 macOS x86_64 环境；Windows Tauri、macOS arm64、无 Python 干净环境、正式 bundle、真实 Codex 正常退出/启动及安全停服仍待验收，阶段 0 不标记完成。

| 验证项 | 状态 | 证据及边界 |
| --- | --- | --- |
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

以下为早期阶段 0 顺序的历史记录；当前优先 Intel，后续接手顺序以[开发交接](../../../apps/desktop/docs/handoff.md)为准：

1. 补齐 Windows Rust/MSVC 构建条件，实际编译并运行最小窗口，锁定 Cargo 依赖。
2. 在用户的 macOS arm64 设备执行同一套构建与验证，记录真实结果。
3. 在专门测试会话验证 Codex 状态读取与正常重启，并验证失败恢复。
4. 完成配置事务和实例互斥的原型设计与验证，再进入正式业务控制实现。

## 复现与产物

工具说明见 [Stage0 README](../../../apps/desktop/stage0/README.md)。本机产物位于 apps/desktop/dist/stage0，结构化结果位于 apps/desktop/build/stage0/source-results.json、frozen-results.json 和 config-audit.json；这些目录被 Git 忽略，报告可按说明重建。二进制为验证探针，不是可日用客户端或安装包。

参考：[Tauri 系统前置条件](https://v2.tauri.app/start/prerequisites/)、[Tauri 外部程序打包](https://v2.tauri.app/develop/sidecar/)、[PyInstaller 工作方式](https://pyinstaller.org/en/stable/operating-mode.html)、[PyInstaller 构建选项](https://pyinstaller.org/en/stable/usage.html)、[官方 App Server 文档](https://learn.chatgpt.com/docs/app-server)。这些文档支持工具机制，不能代替上述待完成实测。


### Intel 托盘基础增量（2026-11-01）

- 本次仅 x86_64；Apple Silicon 留到对应设备本机构建与验收。
- macOS 专用 tray-icon feature；CH 菜单提供打开、接入设置、退出，关闭窗口调用隐藏，Dock 重开显示；Windows 生命周期分支保留。
- 离线 locked Intel 编译通过；控制器 9 项测试、界面生命周期事件 3 项测试通过。事件测试覆盖安全退出被拒绝、草稿保护及接入菜单不发出配置写入。
- 临时 HOME 原生窗口成功显示未配置/网关停止，Cmd+Q 后测试进程退出，未创建管理目录；真实 Codex 未操作。
- 当前自动化 AX 观察会重新激活应用，无法凭该观察确认隐藏持续状态；CH 菜单点选、运行中网关跨隐藏保留和草稿跨隐藏恢复仍待专门实机验证。不能据此标记完整托盘验收或正式发布完成。
- 手工 Tray Preview.app 仅测试使用，不是正式交付安装包。

### Intel 退出恢复及 Cmd+Q 修复（2026-11-01）

- 接入中退出进入已有恢复预览，明确确认后恢复原生配置，再另行检查安全停服；取消不切换配置。仅 macOS 启用该引导。
- 实机发现默认 Quit 直接调用系统 terminate，绕过原有保护；已用自定义 Cmd+Q 命令替换。修复后隔离 HOME 的接入中 Cmd+Q 保持同一进程并显示恢复预览。确认后原生配置恢复，检测到 Codex 进程时网关及应用保留。未操作真实 Codex。
- 8 项 Node 事件测试、9 项控制器测试、1 项冻结真实 worker 回归、Intel locked offline 编译、语法和格式检查通过。测试包已同步最新增量；未进行正式 bundle 或其他平台实测。完整边界与测试收尾记录见交接文档“退出恢复增量”。

### Intel 动态托盘及独立重启入口（2026-11-01）

- macOS 专用托盘模块提供接入/网关状态、打开、开启/关闭接入预览、重启 Codex 确认及退出；原生轮询不依赖隐藏网页计时器，忙时不积压，不自动重建断连会话。
- 重启仅 macOS，预览票据单次使用、两分钟过期，复核安装及 PID/创建时间；不运行不启动，未知不操作，退出失败不启动，不强杀、不重试。配置或预览变化使旧票据失效。
- 最终源码桌面测试 37 项、Node 事件测试 11 项、Rust 状态映射测试 2 项通过；完整 Intel 构建脚本通过 20 项冻结探针、含重启取消票据的真实 worker 生命周期及 locked offline 编译。最新手工测试包已同步。
- 最新隔离原生窗口验证重启预览与取消；未保存厂商及虚构 Key 跨关闭重开保留；关闭窗口后未调用 UI 观察即检查同一 PID 与本地 healthz，网关保持健康。恢复原生后检测到真实 Codex，服务及窗口保留；测试所有者最终按严格身份清理，端口释放。
- 未确认有效重启票据、未操作真实 Codex、未发推理请求。托盘菜单点选受 AX 自动化限制，持续隐藏、真正 Dock 点击、真实 Codex 启停、正式 bundle 与其他平台仍待验收。详见交接文档。
# 2026-11-01 首次加载与 Cmd+Q 修复验证

- macOS Intel 完整 `scripts/build_desktop.sh`（`STAGE0_OPEN_APP=0`）通过，包含冻结隔离校验、真实 worker 生命周期及包内 `desktop-snapshot` 运行校验。
- Python 全量 416 项通过（2 项跳过）；Node 63 项通过；Rust 3 项通过；`git diff --check` 通过。
- 本机原生预览复用已运行网页服务后，接入与运行页面显示已连接、实际接入状态和自动进程/活动检测；模型页面显示现有启用模型；诊断页面显示运行时长与现有日志摘要。未修改真实接入配置、未执行厂商推理测试、未重启或退出 Codex。
- Cmd+Q 成功退出正常预览窗口及其控制进程，原网页服务继续运行。
- 另建缺少 Python 运行库的隔离 `.app` 复现启动失败：页面显示明确“配置读取失败”提示；Cmd+Q 成功退出且无控制进程残留。
- 上述为 macOS Intel 验证，不代表 Windows 或 Apple Silicon 实机验收；启动中尚未结束的有效后台读取受 20 秒响应截止时间约束。


### macOS 托盘原生确认（2026-11-01）

- 菜单精简为“管理”、勾选式“混合路由”、“重启 Codex…”和“退出…”，移除状态行；详细状态保留 tooltip，状态未知时禁用切换。
- macOS 托盘切换及独立重启使用 AppKit NSAlert，取消不提交；继续复用已有预览、票据、进程身份和安全检查。网页与非 macOS 的原确认流程保留。
- Node：70 项通过，覆盖原生确认的取消、仅切换、切换并重启、单次重启票据、不可用及服务失败提示、草稿阻挡和从不自动操作偏好；包括原有共享网页与历史原型回归。
- Python 桌面：47 项通过；首次沙箱运行仅回环监听被拒，允许本机回环监听后全项通过。测试不操作真实 Codex。
- Rust：3 项通过，offline locked macOS Intel 构建通过；新增 AppKit 直接依赖均来自已锁定本地缓存。
- 本机实际显示 NSAlert 并点击取消，返回 `Ok(0)`。另以临时构建的隔离窗口发出与托盘相同的事件，经过真实共享页面、Tauri IPC 和 AppKit 显示“重启 Codex？”；取消后确实收到 `cancel_restart`。诊断确认页面相关状态与桌面适配器均已加载。临时 fixture 禁止 `restart_codex` 与 `set_routing` 的真实操作；验证源码移至忽略目录 `apps/desktop/build/stage0/native-dialog-check-sources/`。
- 状态栏菜单本身的 AX 读取仍超时，未证明真实托盘菜单点选、真实 Codex 重启、Windows 或 Apple Silicon 验收。此前“无反应”的完整菜单点击条件未复现；本轮已验证事件到原生确认及取消的链路，并增加检测中与异常反馈。

### macOS 托盘复用已有网页服务修复（2026-11-01）

- 复现：网页服务已占用数据目录时，托盘原生路由确认调用直接控制接口返回 `SERVICE_ALREADY_RUNNING`，但窗口的 `web_api` 接口正常。托盘预览和提交现复用共享管理接口。
- macOS 独立重启支持复用已有网页服务：由本地控制器保管单次票据，预览和确认重新读取服务状态，断连或 project 网关故障时拒绝重启；取消只清理本地票据。Windows 仍拒绝独立重启。
- Python 全量 418 项通过（2 项平台跳过）；补充断连与本地取消用例后，已有服务专项 7 项通过。Node 全量 60 项通过，覆盖已有网页服务时托盘切换，以及原有非原生确认流程。首次沙箱测试因禁止本机回环监听失败，允许回环监听后通过。
- Intel 冻结探针、冻结 worker 生命周期和原生编译通过。已更新仓库内 Tray Preview.app；包内程序首次原地复制后被系统 SIGKILL，原子替换为新文件后临时 HOME 的 `desktop-snapshot` 校验通过。未操作真实 Codex、未修改真实路由配置，未验收真实托盘点击或 Windows/Apple Silicon。

### macOS 托盘提示精简与前台显示（2026-11-01）

- 托盘路由与重启弹窗删去常规索引统计和重复说明，保留操作含义、重启影响及按钮；仅在活动请求、未知状态或历史缺失时追加提醒。结果提示保留手动处理说明与实际迁移警告。
- 显示前布局并将原生弹窗设为 key window，请求 AppKit 激活并调用 `orderFrontRegardless`；不显示或聚焦管理窗口。macOS 14 以下保留兼容激活入口。
- Node 全量 63 项、Rust 3 项通过。Intel 隔离应用实际显示精简确认框，AX 聚焦元素为确认框；取消返回 `Ok(0)`，结束后管理窗口仍为 `main_visible=false`。未操作真实 Codex 或路由配置。后台属性在模态循环中的刷新存在限制，未以该属性断言跨应用抢焦点已完成全部实机验收。


## 桌面构建入口迁移（2026-11-05）

原根目录脚本迁至 `scripts/build_desktop.sh`。本机 Intel macOS 通过新入口完成 Python 冻结、20 项隔离验证、Tauri 编译、预览 `.app` 组装和包内 `desktop-snapshot` 检查，设置 `STAGE0_OPEN_APP=0`。初次运行在沙箱回环端口绑定处受限，使用本机执行权限重跑后完整通过。

新增 `scripts/build_desktop.ps1` 输出 Windows x64 双 EXE 便携目录。4 项临时打包回归检查覆盖 Windows hidden import、两平台打包模式和架构映射，并模拟两平台 PyInstaller 参数及产物整理。当前环境没有 PowerShell 和 Windows 工具链，尚未执行 PowerShell 脚本或 Windows 编译与运行，不能作为 Windows 实机验收依据。
