# 桌面工程、构建与文档重构规划

日期为 2026-11-06，状态为执行中。本文补齐整体目录方案中的桌面应用工程、构建工具链与文档信息架构。实施任务登记在 `tasks/todo.md` 的 D01–D09，整体方案见 `tasks/plan.md`。

## 1. 当前职责与构建链

桌面运行链为共用管理页面 → Tauri 固定命令 → Python sidecar 的 desktop-controller → 共用管理用例与本机集成。

macOS Intel 构建链为 `scripts/build_desktop.sh` → `apps/desktop/tools/build_macos.sh` → `build_sidecar.py` → 冻结验证 → Cargo 构建 → 复制运行库并组装 `.app` → 应用内冻结验证 → 注册图标并按开关打开窗口。

Windows x64 构建链为 `scripts/build_desktop.ps1` → `apps/desktop/tools/build_windows.ps1` → 初始化 MSVC → Python/Rust 预检 → `build_sidecar.py` → 冻结验证 → Cargo release 构建 → 临时双 EXE 目录 → 产物内冻结验证 → 替换输出目录并在失败时恢复。

已确认的差异包括 macOS PyInstaller onedir、Windows onefile，macOS `.app` 内 Frameworks 链接及运行库，Windows 完整双 EXE 目录发布，以及不同的原生弹窗和退出流程。Apple Silicon 的目标映射已出现在构建工具中，验收状态需独立登记。

本轮已将运行入口迁到 `sidecar/main.py`，验证夹具与命令归入 `validation/`，构建归入 `tools/`，Tauri 归入 `src-tauri/`。原 stage0 映射在下文保留为迁移来源记录。命令完整性按源码与冻结隔离检查复验。

## 2. 目标工程目录

```text
apps/desktop/
├── README.md                         # 工程入口和开发导航
├── src-tauri/
│   ├── Cargo.toml
│   ├── Cargo.lock
│   ├── build.rs
│   ├── tauri.conf.json
│   ├── tauri.macos.conf.json
│   ├── capabilities/
│   ├── icons/                        # 图标资源与生成规范
│   ├── examples/                     # 仍有复现价值的原生示例
│   └── src/
│       ├── main.rs                   # 装配、命令注册和事件接线
│       ├── ipc.rs                    # 串行会话、限额、超时、响应配对
│       ├── lifecycle.rs              # 隐藏、退出、断连及资源释放
│       ├── desktop_tray.rs
│       └── platforms/
│           ├── macos_dialog.rs
│           └── windows_dialog.rs
├── sidecar/
│   └── main.py                       # 冻结入口，分派已登记命令
├── tools/
│   ├── build_sidecar.py              # PyInstaller 构建协调
│   ├── build_paths.py                # 仓库、资源、临时输出路径
│   ├── platforms/
│   │   ├── macos.py                  # onedir、运行库与 app 组装
│   │   └── windows.py                # onefile 和发布目录相关能力
│   ├── build_macos.sh                # Xcode、Rust、构建与产物验证
│   ├── build_windows.ps1             # MSVC、Rust、构建与产物验证
│   └── requirements.txt              # 构建工具依赖
├── validation/
│   ├── fixtures.py                   # 隔离配置及虚构上游夹具
│   ├── probe.py                      # 验证专用命令与报告
│   ├── verify.py                     # 源码/冻结执行的端到端检查
│   ├── preflight.py                  # 只读环境和进程盘点
│   └── audit_config.py               # 临时配置往返验证
├── tests/
│   ├── test_responses_only.py
│   ├── test_tray_lifecycle.py
│   └── test_build_contracts.py        # 有针对性的路径、产物与命令回归
├── build/                            # 可再生中间产物和验证输出
└── dist/                             # 分平台分架构的交付产物

scripts/
├── build_desktop.sh                  # 调用桌面工程的 macOS 入口
├── build_desktop.ps1                 # 调用桌面工程的 Windows 入口
├── codex-hybrid.sh
└── codex-hybrid.cmd

src/management/web/                   # 浏览器与桌面共用页面
src/codex_integration/                # 本机集成和控制业务
```

新增模块以真实复用和可测试职责为条件。`tools/platforms/windows.py` 仅在实际有可从 PowerShell 收拢的 Python 职责时创建，MSVC 环境引导归属 PowerShell。macOS 系统工具调用同样保留在对应平台实现。

运行时 sidecar 调用 `src/` 下的业务。验证命令的兼容期可通过延迟分派访问验证模块，冻结清单需明确包含这些模块。最终是否独立验证可执行文件，以现有工具调用和冻结回归结果为依据单独决定。

## 3. 原始目录到迁移目录的映射

| 原始位置 | 迁移位置 | 迁移要点 |
| --- | --- | --- |
| `apps/desktop/stage0/tauri/` | `apps/desktop/src-tauri/` | 同时修正 Cargo manifest 路径、externalBin、frontendDist、图标与 capabilities 引用 |
| `stage0/build_probe.py` | `tools/build_sidecar.py` | 分离路径、平台产物规则与通用 PyInstaller 调用 |
| `stage0/build_macos_intel.sh` | `tools/build_macos.sh` | 明确 Intel 支持条件，匹配 Python 与 Rust 架构 |
| `scripts/build_desktop.sh` 中应用组装片段 | `tools/platforms/macos.py` 或平台脚本的对应函数 | 内联 Python 提取后可单独验证 Frameworks、plist 与图标路径 |
| `scripts/build_desktop.ps1` 中构建实现 | `tools/build_windows.ps1` | 根入口显式透传参数、退出码和工作目录，保留平台引导与发布回滚流程 |
| `stage0/probe.py` | `sidecar/main.py` 与 `validation/probe.py` | 先核对现有命令，再区分运行入口和夹具；阶段内维持原命令可调用 |
| `stage0/verify.py` | `validation/verify.py` | fixture 抽成显式模块，分别验证源码模式和冻结模式 |
| `stage0/preflight.py`、`audit_config.py` | `validation/` | 标注只读盘点与临时数据写入边界，修正相互导入 |
| `stage0/test_*.py` | `apps/desktop/tests/` | 修正读取源码的路径断言，保持行为断言 |
| `stage0/requirements.txt` | `tools/requirements.txt` | 区分项目运行依赖、构建工具依赖与测试依赖 |
| `stage0/README.md` | 开发工具指南与历史记录 | 逐节分类，当前复现命令进入开发指南，历史事实进入归档 |

旧脚本入口可先用精确转发维持迁移窗口。每次移动先迁工具和调用方，再执行完整构建链验证，最后清理已无调用方的兼容入口。

## 4. 构建配置与产物契约

### 4.1 路径和资源

使用集中路径模块表达仓库根、共用网页、Tauri 工程、工具缓存与输出根。避免迁移后继续依赖固定 `parents[3]`。构建脚本从自身位置定位仓库，并验证根目录标识文件。

新 Tauri 工程内的 frontendDist 预期为 `../../../src/management/web`，externalBin 按新的配置位置计算，并通过实际 Tauri 构建确认。静态页面由同一源码目录提供，新增嵌套 JS 目录须同时纳入 Python 包和 sidecar 资源清单。

### 4.2 可复用构建阶段

明确预检、构建 sidecar、验证 sidecar、构建 Rust、组装产物、验证产物、发布输出和可选打开应用八个阶段。阶段输入输出清晰，网络依赖获取与离线编译分别记录，命令保留 `--locked` 和原有离线优先规则。

复用构建路径、目标架构映射、资源清单和验证程序。平台脚本调用平台封装，macOS 和 Windows 分别管理各自产物布局。

### 4.3 输出与兼容

目标布局为 `build/<target>/` 存放隔离中间产物，`dist/<target>/` 存放完成验证的应用目录。Cargo 缓存等可跨构建复用的资源放在 `build/cache/`，验证报告按目标与执行批次区分，避免彼此覆盖。

在路径迁移阶段通过显式映射支持现有 `build/stage0`、`dist/stage0` 消费者。环境变量 `STAGE0_PYTHON`、`STAGE0_OPEN_APP` 如引入更准确名称，需规定新旧变量优先级并覆盖设置冲突测试。

当前 Rust package、sidecar 文件名、Tauri productName/identifier 和手工 plist 标识含 stage0 或 preview。文件目录迁移与应用身份调整分阶段处理。应用身份调整需先核对 Launch Services、能力范围、用户偏好、进程识别及已有产物的并存方式，再确定名称映射。

Windows 组装继续在临时目录验证完整双 EXE 后替换，并在替换失败时恢复旧产物。macOS 的运行库与 Frameworks 链接、权限和 app 内执行须有独立验证。

## 5. 文档信息架构

用户资料按语言组织，开发资料按工程主题组织，验收记录按执行时间和平台归档。

```text
docs/
├── zh-CN/
│   ├── README.md                    # 用户任务导航
│   ├── desktop.md                   # 桌面安装、初始化、托盘、升级与退出
│   ├── usage.md
│   ├── configuration.md
│   ├── troubleshooting.md
│   ├── architecture.md              # 用户可理解的原理与边界
│   └── ...
├── en/                              # 与中文用户主题对应
└── images/

dev-docs/
├── README.md                        # 开发者导航
├── architecture/
│   ├── repository-layout.md         # 代码目录和依赖边界的权威说明
│   └── platform-boundaries.md       # Windows/macOS 实现与验收边界
├── desktop/
│   ├── README.md
│   ├── development.md               # 首次开发、日常调试与命令
│   ├── build-macos.md               # 按 Intel/Apple Silicon 标注支持范围
│   ├── build-windows.md
│   ├── packaging.md                 # sidecar、资源、运行库与产物契约
│   ├── private-protocol.md          # 当前协议、白名单、限额及错误契约
│   ├── lifecycle.md                 # 托盘、窗口、退出与重启的状态规则
│   ├── validation.md                # 验证方法、命令与验收矩阵
│   └── status.md                    # 当前进度、缺口与证据链接
├── plans/
│   └── desktop-and-documentation-refactoring.md
├── decisions/                       # 延续已有 ADR 编号与引用
└── archive/desktop/
    ├── stage0-plan.md
    ├── stage0-tools.md
    ├── stage0-validation.md
    └── handoff-history.md

apps/desktop/README.md               # 工程定位和开发导航链接
README.md / README.zh-CN.md          # 产品入口及用户/开发文档链接
```

### 5.1 现有文档迁移

| 当前文档 | 目标及拆分方式 |
| --- | --- |
| `apps/desktop/docs/build-macos-intel.md` | 当前环境与命令进入 `dev-docs/desktop/build-macos.md`，运行库布局进入 packaging，历史增量进入归档 |
| `apps/desktop/docs/build-windows.md` | 当前构建指南进入 build-windows，托盘用户操作进入双语 desktop 用户指南 |
| `apps/desktop/docs/private-management.md` | 协议规范进入 private-protocol，退出/托盘进入 lifecycle，带日期的验收事实进入归档 |
| `apps/desktop/docs/web-desktop-alignment.md` | 当前职责进入 repository-layout，平台差异进入 platform-boundaries/lifecycle，验证历史进入归档 |
| `apps/desktop/docs/handoff.md` | 当前状态与下一步进入 status，环境和命令进入 development，历史增量进入 handoff-history |
| `apps/desktop/docs/plan.md` | 已确认产品范围与约束提取到对应当前主题，原文归档为 stage0-plan，未完成任务逐项映射到现行清单 |
| `apps/desktop/docs/stage0-validation.md` | 原始证据保存在 archive，当前 validation 仅链接证据并列明可复现方法 |
| `apps/desktop/stage0/README.md` | 工具操作进入 development/validation，历史探针范围进入 stage0-tools |
| 中英文 `architecture.md` | 精简为用户原理并链接开发架构，详细目录树维护在 repository-layout |
| 根 README、双语文档索引、桌面 README | 同步导航、平台状态和新路径 |

文档按章节提取并建立来源映射。已确认产品决策和未完成事项逐项核对，历史实测保留日期、平台、架构、源码版本和原始范围。`status.md` 只汇总当前状态并引用证据。

### 5.2 文档验收

- 每个构建指南从干净检出开始列出前置环境、执行位置、命令、预期产物与失败定位。
- 桌面用户指南包含安装、首次初始化、来源设置、接入预览、托盘、关闭与退出、更新和恢复入口，Windows/macOS 差异显式分节。
- 每项验收区分源码测试、模拟、原生构建、冻结运行、窗口操作和安装实机，Apple Silicon 单独列状态。
- 相对链接、标题锚点、源码路径和命令参数逐项检查，导航页能到达所有现行指南。
- 中英文用户文档的行为说明对应，开发指南语言状态在导航中标注。
- 旧文档路径先保留新位置说明及历史定位，外部引用可据此迁移。

## 6. 实施顺序和依赖

D01 建立工具与文档映射 → D02 分离 sidecar/验证职责 → D03 整理构建工具 → D04 迁移 Tauri 工程 → D05 更新资源及冻结契约 → D06 双平台完整构建验证 → D07 迁移文档与导航 → D08 复核产品身份命名 → D09 最终审查与旧路径收敛。

D07 可在 D01 后先完成内容分类与草案，在 D06 产出实际路径和命令后验收。D08 完成身份影响审查后才能决定是否调整具体名称。各任务按一类职责或单个平台细分提交，约 3–5 个文件为一个可验证批次。

总体后端重构的 R03 基线应包含桌面工具可调用性，R25 对应桌面 Rust 内部拆分，R26 的构建与资源验证纳入 D05/D06，R27 的文档验收纳入 D07/D09。

## 7. 当前规划判断与验证范围

本次将桌面工程从 stage0 提升为明确的应用、构建、验证目录，将开发者文档集中到 dev-docs，并新增双语桌面用户指南。目录方案已批准并执行。当前路径见开发架构，运行入口、构建、验证、Tauri 和文档已完成本轮目录迁移。

本轮已完成截断源码恢复、平台模块与桌面目录迁移。Intel 本地 locked Cargo check/build、PyInstaller 源码/冻结/应用内 verify 各 21 项通过。未在本轮运行原生窗口、Windows 或 Apple Silicon 构建，真实 Codex 操作与干净机器验收仍待执行。D07 当前指南、双语用户入口、归档、链接与命令路径已同步，完整验证范围见[当前状态](../desktop/status.md)。


## 8. 本轮执行记录

2026-11-06 已完成以下范围，最终提交前以实际工作树和验证日志核对。

- 后端已拆分网关 HTTP/路由/目录/流、管理 commands/use_cases/同步/监督、CLI 命令族、本机 routing 与 sessions、模型来源包/偏好/发布、协议 history/context/stream_errors 和代理基础设施。原公共调用符号与数据契约保留。
- Portable 的 ResponsesAdapter 保持每请求独立且同一注册表实例，tools/history 未继续过度拆分。网页 app 负责装配 shared 与 features，现有模型/诊断/用量/桌面接口保留。
- Rust main 负责装配，ipc 负责私有会话和响应配对，lifecycle 负责关闭隐藏和安全退出，平台弹窗各自维护。Intel offline locked check/test/build 与四项 Rust 回归通过。
- D02–D05 的源码、构建、验证、Tauri 资源迁移已实施，D06 已完成 Intel 执行范围，Windows 和 Apple Silicon 原生构建/交互保持待验。
- D07 当前主题指南、双语入口、历史归档、旧标题导航及链接/命令路径检查已整理。D08 经评审确认保留现有应用 identity、sidecar 名、build/stage0、dist/stage0 和环境变量，名称调整留待独立需求。
- D09 本轮清理覆盖旧源码调用方、新包资源白名单、平台动态导入和兼容导出。原公共 Python 入口及旧文档章节导航保留，跨平台实机与干净机器验收继续开放。
- Node 94 项、HTTP 12 个脚本和 5 个只读 API 通过，wheel 包含 107 个 Python 模块及 16 个网页资源。真实浏览器尝试受 Work 设置 disabled 限制，窗口与托盘尚未进行本轮实机验收。

最后一轮完整 Python 与 Intel 重冻/组装结果汇总到[当前验证矩阵](../desktop/status.md#本轮验证矩阵)。本记录不把模拟、HTTP 响应或冻结通过扩展为另一平台原生及真实客户端控制验收。


最终执行补充。全量 Python 518 项（2 项平台相关跳过）、桌面 Python 24 项、Node 94 项、Intel Rust 4 项通过。根入口 `STAGE0_OPEN_APP=0 bash scripts/build_desktop.sh` 完成最终重冻与应用组装，源码/冻结/应用内三报告各 21 项且 16 个资源全部通过，冻结控制器隔离生命周期另 1 项通过。wheel 精确包含 107 个 Python 模块和 16 个网页资源，临时目录两个 CLI 入口通过，Ruff 与 diff 检查通过。

本轮还独立修正并发恢复取得双锁后重读 journal、恢复三个固定 IPC 错误码白名单，并补回 service.migrate_routing 的公共 runtime 适配。原生 Windows/Apple Silicon、真实页面/托盘及干净机器仍按平台继续验收，完整清单见状态页。
