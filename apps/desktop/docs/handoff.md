> 2026-11-01 更新：当前 Tauri 窗口已切换为直接加载 `src/management/web/`。`transport.js` 将桌面请求交给私有 `web_api` 白名单，`desktop.js` 负责初始化和生命周期；旧 `apps/desktop/stage0/web/` 不再是窗口入口。详见 [页面对齐](web-desktop-alignment.md#共用管理页面2026-11-01) 和 [私有协议](private-management.md#共用网页适配)。以下较早的预览页面描述按历史进度阅读。

> 2026-11-01 目录整理：Tauri 外壳、构建和验证工具统一位于 `apps/desktop/`；原 Python `desktop` 包更名为 `codex_integration`，位于 `src/codex_integration/`。网页 HTTP 入口与共用页面仍位于 `src/management/`。下面命令已更新路径；旧构建产物需重新生成。
>
> 本次验证：Python 420 项（2 项跳过），JavaScript 74 项；Python wheel 构建与脱离源码目录的导入检查通过；Intel macOS 完整构建脚本通过 20 项冻结隔离检查、冻结控制进程检查及离线 Tauri 编译。平台控制与代理行为未调整，Windows 与 Apple Silicon 未做本次实机验收。

# 桌面应用开发交接

更新日期：2026-11-01。供新会话和其他 agent 接手；这是当前状态快照，接手时先检查代码与 git diff，不能把历史测试结果当成本轮验证。

## 目标与已确认决策

- 当前只做 macOS Intel x86_64，先走通日用桌面版、打包和可复现脚本。
- Apple Silicon 后续由用户在对应设备本机构建；Windows 另行推进。本机编译通过不代表这些平台验收通过。
- 技术路线是 Tauri 2 + PyInstaller 冻结 Python。Xcode 提供 macOS SDK、编译和链接工具，不改为 SwiftUI。
- 复用现有 Python 管理、配置事务、会话索引迁移和网关监督业务，不复制第二套业务内核。
- 主操作统一为“Codex 接入”；切换先预览再明确确认，不提供独立网关开关。启动应用不自动开启接入或启动网关。
- 固定使用用户的 `~/.codex-hybrid`；桌面不接受前端传入任意路径或 shell 命令。

先读仓库根目录 `AGENTS.md`，再读本文、[计划](plan.md)、[协议](private-management.md)、[验证记录](stage0-validation.md)和[构建流程](build-macos-intel.md)。历史计划存在早期阶段描述，以本文和计划顶部“当前推进”为当前顺序。

## 已实现及验证边界

| 内容 | 当前实现 | 验证范围 |
| --- | --- | --- |
| Intel 工具链与冻结 | 架构预检、PyInstaller sidecar、锁定 Cargo 依赖、离线 Tauri 编译、一条命令构建 | Intel 完整脚本曾通过；最新托盘/重启增量已重新跑完整 Intel 脚本并通过 |
| 配置快照 | 公共目录及选定编辑字段，不返回 Key、管理令牌、整份原始配置 | 源码及冻结隔离测试 |
| 初始化 | 读取官方配置和模型缓存，创建管理文件及恢复基线，不改写 Codex | 临时 HOME 测试；仍要求官方配置/缓存存在 |
| 厂商与模型管理 | 保存、版本校验、Key 留空保留、高级字段保留；CC Switch 只读 | 单元测试及先前隔离原生窗口验证 |
| 草稿与连接测试 | 编辑时阻止刷新及其他编辑，失败保留草稿；连接测试显式触发 | 隔离模拟上游，不发付费请求 |
| 常驻控制进程 | 私有 stdio，串行请求，64 KiB 请求上限，实例锁，同会话预览签名；无管理 HTTP 监听 | 控制器及真实本地 worker 生命周期测试 |
| 接入切换 | 预览活动、索引影响；明确确认；先确保网关健康再改配置；可选正常操作 Codex及方向偏好 | 临时配置实际启停网关；真实 Codex 自动操作未验收 |
| 恢复与退出 | 残留接入显式恢复；macOS 退出时预览恢复原生配置，确认后另查活动及进程，不能确认时保留服务 | 源码/冻结生命周期；Intel 隔离窗口验证取消、Cmd+Q 引导和恢复后保留网关；真实客户端完整验收仍待进行 |
| macOS 托盘 | CH 菜单：接入/网关状态、打开、开启/关闭接入预览、重启 Codex 确认、退出；原生层轮询状态；关闭隐藏、Dock 重开 | 已通过 Intel 编译、Rust/界面测试及隔离窗口草稿/网关跨关闭保留；完整托盘点选、持续隐藏及真正 Dock 点击未验收 |
| 应用包 | 存在手工组装的 Tray/Routing/Editor/Readonly Preview.app | 仅本地测试产物，正式 Tauri release app/dmg 尚未实现 |

最新托盘增量保留 Windows 原有关闭拦截分支，tray-icon feature 仅在 macOS 开启。没有调整任何平台的上游代理规则。

## 代码入口

| 文件 | 用途 |
| --- | --- |
| `src/codex_integration/snapshot.py` | 脱敏快照、配置版本及读取竞争检测 |
| `src/codex_integration/management.py` | 初始化、保存、主动连接测试 |
| `src/codex_integration/restart.py` | macOS 独立重启的单次预览票据、过期与进程身份复核 |
| `apps/desktop/stage0/tauri/src/macos_tray.rs` | macOS 专用托盘菜单、状态显示及原生轮询 |
| `apps/desktop/stage0/web/restart.js` | 窗口/托盘共用的重启确认区 |
| `src/codex_integration/controller.py` | 常驻私有协议、实例所有权、预览/确认、网关与安全退出 |
| `src/codex_integration/service.py` | 共享准备逻辑；新增可选参数默认保留原 CLI 行为 |
| `apps/desktop/stage0/probe.py` | 冻结入口及 freeze_support；snapshot/manage/controller 模式 |
| `apps/desktop/stage0/build_probe.py` | 架构映射、冻结及 macOS 动态模块 hidden import |
| `apps/desktop/stage0/build_macos_intel.sh` | Intel 预检、冻结、隔离验证、Cargo 构建 |
| `apps/desktop/stage0/tauri/src/main.rs` | sidecar 会话、固定命令白名单、macOS 托盘及退出保护 |
| `apps/desktop/stage0/web/` | 静态管理界面与接入预览 |
| `apps/desktop/stage0/test_web_lifecycle.cjs` | 托盘事件、安全退出及草稿保护测试 |
| `tests/test_desktop_*.py` | 快照、管理、私有命令、控制器及真实 worker 测试 |
| `tests/test_stage0_build.py` | 架构及 hidden import 回归 |

## 接手后按此顺序推进

1. 完成 Intel 托盘专门实机验证：菜单打开窗口、接入入口、退出、关闭隐藏、Dock 重开；隐藏时草稿（包括未保存 Key）和网关保留；窗口及托盘走同一预览确认流程。当前 AX 观察会重新激活应用，不能凭观察到窗口就判断 hide 失效。
2. 继续退出边界实测：macOS 已实现接入中退出引导预览恢复、确认后检查安全停服，允许取消。已验证窗口退出入口、Cmd+Q、取消及恢复后保留网关；尚需托盘点选与无依赖时恢复后正常退出的原生窗口验收。
3. 检查生命周期边界：控制进程断连、实例锁失败、原生配置+网关 fault 且无活 worker 的退出；不能为了退出而削弱活动/进程未知时的保护。检查隐藏期间事件失败、长请求、无响应和超时处理。
4. 验收托盘状态与独立重启 Codex：计划菜单入口已实现，切换与重启均先显示预览确认；原生状态轮询不依赖隐藏页面的计时器。真实 Codex 启停需专门测试会话，勿操作当前承载开发任务的 Codex；完整托盘不能仅凭自动化事件测试标记完成。
5. 引入官方 Tauri bundle 工具与 release 构建，输出 Intel `.app` / `.dmg`，完善名称、图标（现为占位）、版本、sidecar 布局和校验和。当前无 cargo-tauri CLI 的已验证安装；先确认环境再选工具版本。
6. 把正式打包纳入可复现脚本，记录依赖及错误诊断；现有脚本只产 debug 可执行程序和冻结 sidecar，不生成正式安装包，也不重建手工 Preview.app。
7. 在无 Python/Git/源码的 Intel 干净环境验收安装、启动、更新保留数据、退出、恢复。签名、公证及公开分发随后处理。
8. 继续产品功能缺口：真正可跳过官方缓存/模型配置的首次使用、来源切换、独立目录成员管理、日志/设置/脱敏诊断、单实例用户体验等；以计划逐项核对，不把原型界面视为完整产品。
9. 后续在 Apple Silicon 设备原生构建与实际验收，分别输出 arm64 安装包；Windows 按专用模块实施和验收，不因代码去重改变其代理、进程或安装行为。

## 构建与回归命令

从仓库根目录执行。本机已验证 macOS 15.6 x86_64、Xcode 16、Python 3.14.7、Rust 1.98；当前不能执行 arm64 程序。工具/cache/build/dist 为本机产物，Git 忽略，换机器须按构建流程安装依赖。

```sh
bash apps/desktop/stage0/build_macos_intel.sh

CARGO_HOME="$PWD/apps/desktop/build/stage0/cargo-home" cargo build --offline --locked \
  --manifest-path apps/desktop/stage0/tauri/Cargo.toml --features custom-protocol

PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_desktop_*.py'
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p test_stage0_build.py
node --test apps/desktop/stage0/test_web_lifecycle.cjs
node --check apps/desktop/stage0/web/app.js
git diff --check
```

冻结实际 worker 回归：

```sh
PYTHONPATH=src \
STAGE0_SNAPSHOT_EXECUTABLE="$PWD/apps/desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin" \
.venv/bin/python -m unittest discover -s tests -p test_desktop_controller_process.py
```

Python 集成测试需允许回环监听；PyInstaller 需本地进程/信号量权限。沙箱内受限失败先区分权限与代码故障，不以删测试或弱化断言解决。Node 用于新增界面事件测试，当前静态前端构建本身不要求 Node。

历史通过结果：desktop Python 26 项、构建 4 项、共享 routing 12 项、web workflow 16 项、gateway transport 10 项、runtime control 35 项、冻结隔离 20 项及冻结 controller 生命周期；托盘增量后单独通过 controller 9 项和界面事件 3 项。日志位于 `apps/desktop/build/stage0/`；这些是历史证据，后续改动需重跑相应检查。

## 本机产物与启动

- sidecar：`apps/desktop/dist/stage0/hybrid-stage0-probe-x86_64-apple-darwin`
- 窗口程序：`apps/desktop/stage0/tauri/target/debug/hybrid-stage0-shell`
- 手工测试包：`apps/desktop/build/stage0/Codex Hybrid Tray Preview.app`
- 托盘测试 HOME：`apps/desktop/build/stage0/tray-fixture-home`
- 退出恢复测试 HOME：`apps/desktop/build/stage0/exit-fixture-home`（本轮已恢复原生配置，测试进程已清理）
- 早期路由测试 HOME：`apps/desktop/build/stage0/routing-fixture-home`

隔离启动手工测试包（存在时）：

```sh
HOME="$PWD/apps/desktop/build/stage0/tray-fixture-home" \
"./apps/desktop/build/stage0/Codex Hybrid Tray Preview.app/Contents/MacOS/hybrid-stage0-shell"
```

使用真实用户配置打开：

```sh
open "./apps/desktop/build/stage0/Codex Hybrid Tray Preview.app"
```

`.app` 是目录，不能直接 `./…app` 执行。隔离启动应直接运行内部 executable；不要假设 `HOME=… open …app` 会把环境传给 Launch Services 启动的应用。启动前检查同一测试包是否已运行，避免绑定到旧实例；不要对已退出应用直接调用会自动启动应用的 UI API，否则可能使用真实 HOME。手工包会过时，修改后不能假设其已同步最新编译结果。

## 安全边界和已踩过的坑

- 不关闭/重启承载当前任务的真实 Codex，不修改其真实配置，不发付费请求。测试使用临时 HOME、虚构模型、模拟上游和随机回环端口；Codex 自动操作保持不勾选。
- 关闭接入成功不等于可以停服。活动、相关进程或检测未知时保留网关；不能将进程模拟测试当成另一系统实机验收。
- 控制进程 stdin EOF 的 worker 清理属于异常收尾，可能中断请求；磁盘恢复基线保留，不能称为安全退出。
- PyInstaller 曾遗漏动态导入的 `codex_integration.macos_client`：源码测试通过但冻结预览失败。已加 macOS-only hidden import，冻结多进程加 freeze_support；必须保留冻结真实 worker 回归。
- Rust 断连不自动重试写操作，避免重复提交；不得将 stderr、上游错误文本、Key 或原始配置直接回传界面。
- 窗口仅有配置互斥保护，不要据此宣称产品级单实例或无响应恢复全部完成。
- 工作树已有大量未提交修改，包含前序桌面工作；本轮没有提交、推送或合并。先 `git status --short` / `git diff`，不要 reset、覆盖或把全部改动混为新任务提交。

## 新会话启动提示

可以直接告诉接手者：

> 阅读 AGENTS.md、apps/desktop/docs/handoff.md 和 apps/desktop/docs/plan.md，检查工作树后继续 macOS x86_64。先完成托盘与安全退出实机验收，再做官方 app/dmg 打包和可复现脚本。Apple Silicon 留待对应设备构建；不要操作承载任务的真实 Codex，不要改动 Windows 约定。每项进度区分已实现、已测试和待验收，并更新交接文档。

## 2026-11-01 退出恢复增量

- macOS 退出失败时由 Rust 返回恢复预览提示，前端重新读取状态并复用已有关闭接入预览；确认前不写 Codex 配置，取消不残留自动退出意图。确认成功后单独调用安全退出；事务失败不重试写入、不继续退出。Windows 不返回该提示，保留原有退出行为。
- 实机发现默认菜单 Quit 的底层 muda 直接调用 `NSApplication terminate:`，原有 ExitRequested 拦截不能覆盖 Cmd+Q。已替换 macOS 默认应用菜单末尾 Quit 为自定义 guarded-quit（Cmd+Q），保留默认其他菜单。依据为锁定的 Tauri 2.12.5 / muda 0.20.0 本地源码；升级依赖时须复核默认菜单结构。此前“Cmd+Q 正常退出”只验证了无接入场景，不能当作保护验收。
- 本轮通过：8 项 Node 生命周期事件、9 项控制器单元测试、1 项冻结真实 worker 生命周期（约 47 秒）、Intel offline locked Cargo 编译、JS 语法、Rust 格式及 diff 检查。未重跑整条 PyInstaller 构建脚本；Python sidecar 未修改。
- 原生测试使用 exit-fixture-home、随机回环端口、虚构官方模型，不勾选 Codex 自动操作、不发送推理请求。验证接入、退出预览、取消、异常退出后显式恢复、修复后 Cmd+Q 保持同一 PID、确认恢复原生后因检测到 Codex 保留网关并阻止退出。最后严格按 PID、路径和隔离 HOME 清理测试所有者；这是测试异常收尾，不是安全退出验收。
- 调试旧 Cmd+Q 时，UI 观察自动重开测试包到了真实 HOME；该窗口配置读取失败，未执行初始化、保存或接入切换，已关闭。今后退出后先用进程检查确认存活，禁止再直接读取可能自动重开的应用 UI。
- 仍待：托盘菜单点选、隐藏持续状态及草稿/网关跨隐藏保留、恢复后无依赖时原生安全退出、断连/超时/实例锁/故障边界、正式 app/dmg。

## 2026-11-01 完整托盘入口增量

- CH 托盘增加接入/网关状态、动态开启/关闭接入菜单、重启 Codex；开启/关闭会先读取状态并直接打开已有预览，点击菜单不会直接提交切换。状态原生线程每五秒尝试读取同一串行控制会话，忙时跳过、不积压；不自动重建断开的会话，断连显示不可用。安全退出期间禁止轮询及其他请求创建新会话。
- 独立重启限 macOS；托盘与窗口共用确认区，显示活动和全应用影响。预览两分钟有效、单次使用；执行前复核已识别安装与 PID/创建时间。未运行不启动、检测未知不操作、正常退出失败不启动、不强杀、不重试。网关故障且配置仍接入时拒绝重启。
- 重启预览与接入预览互相作废，配置编辑/切换使旧重启票据失效。服务端要求显式确认与票据，不接受前端路径；Windows 在接触管理目录前拒绝新增重启命令，既有平台实现与代理规则不变。
- 源码桌面 37 项、Node 事件 11 项、Rust 状态映射 2 项通过。最终完整 Intel 脚本通过：20 项冻结探针、含重启取消票据的冻结 worker 生命周期（约 32 秒）、offline locked Cargo 编译。日志 `apps/desktop/build/stage0/tray-build-final.log`（忽略提交）。新增冻结回归只执行重启预览、取消及提交失效票据，绝不确认有效的真实 Codex 重启。
- 托盘自动化受菜单栏 AX 读取超时限制；完整点选与持续隐藏仍不得标记完成；草稿/网关跨关闭重开保留见最终原生窗口补充。控制通道长请求或无响应的超时恢复仍待单独处理。
- 原生 API 依据：[Tauri 托盘文档](https://v2.tauri.app/learn/system-tray/)及本地锁定 Tauri 2.12.5 的 MenuItem / TrayIcon 源码。

### 最终原生窗口补充

- 最新手工 Tray Preview.app 已同步最终 Rust 程序及冻结 sidecar；仅为本地测试包。隔离 exit-fixture-home 验证首次加载原生/网关停止、独立重启预览显示运行及活动 0、取消后未操作 Codex。
- 创建未保存厂商与虚构 Key 草稿，关闭窗口后核对同一隔离 PID 仍存活；重开后厂商文字及密码掩码保留，随后明确取消草稿。此项证明草稿跨关闭重开保留，不证明窗口持续隐藏或真正 Dock 点击已验收。
- 隔离窗口明确开启接入（不勾选 Codex 操作），关闭窗口后未调用 UI 观察，直接检查同一 PID 与本地 `/healthz`：网关仍健康。随后重开仍显示已接入/运行中。此项证明服务跨关闭保留，窗口持续隐藏与托盘菜单点选仍待验收。
- 最终由退出引导恢复隔离原生配置，检测到真实 Codex 后保留网关、阻止退出；未选择自动操作 Codex。随后严格核对 PID、可执行路径及隔离 HOME 清理测试所有者并确认端口释放。这是测试收尾，不作为无依赖安全退出验收。


## 2026-11-01 托盘精简与系统确认

- macOS 菜单改为管理 / 混合路由（勾选）/ 重启 Codex… / 退出…；删除常驻状态行，状态 tooltip 保留。未知状态禁用切换。
- 托盘切换和独立重启改用 AppKit 系统弹窗；继续使用已有控制器预览与提交接口、单次票据及安全检查。网页与非 macOS 原确认入口保留。重启检测中、被草稿阻挡及失败均给出反馈。
- 验证记录见 `stage0-validation.md` 的“托盘原生确认”节；Windows / Apple Silicon 与实际 Codex 重启未验收。原托盘“点击无反应”在自动化下尚无法复现其完整菜单点选；本轮验证事件到弹窗及取消链路，不能把这一项写为完整托盘点选验收。

- 本轮成功构建已原子替换手工 `Codex Hybrid Tray Preview.app` 的窗口程序，并校验 SHA-256 一致。仍运行的旧实例不自动退出；下次重新打开该测试包加载新菜单。未修改 sidecar 业务代码。
