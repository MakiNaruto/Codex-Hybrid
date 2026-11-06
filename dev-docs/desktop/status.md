# 桌面状态与未完成事项

整理日期为 2026-11-06。实现、历史自动化通过和实机验收分别登记，后续源码变更需重跑相关检查。

| 平台 | 已有记录 | 仍需验收 |
| --- | --- | --- |
| macOS Intel | 完整构建历史、冻结控制器与本地 worker、原生窗口草稿及网关跨关闭保留 | 完整托盘点选、持续隐藏、真实 Dock 重开、真实 Codex 重启、无依赖安全退出和干净机器 |
| Windows x64 | 2026-11-05 release 编译、源码与冻结隔离检查、linker 安装反馈 | 菜单点选、双击与最小化恢复、弹窗焦点、隐藏保留、真实 Codex 重启和干净机器 |
| Apple Silicon | 底层工具包含目标映射 | arm64 原生构建、冻结运行、交互与安装全链路 |

上述表格汇总历史记录，本轮新结果另列如下。证据分别见[验证记录](../archive/desktop/stage0-validation.md)、[交接增量](../archive/desktop/handoff-history.md)和[Windows 构建记录](../archive/desktop/build-windows-history.md)。

## 本轮源码基线与迁移

2026-11-06 从 HEAD 发现的六个截断入口/模块已恢复。原始语法与完整性问题作为迁移起点记录，现行入口已迁入新目录。平台实现归入 `codex_integration/platforms/`，旧模块保留精确兼容导出，公共入口仍按平台延迟导入。

桌面 D02–D05 已分离 sidecar、工具、验证和 Tauri 目录，根构建脚本为短转发。`build/stage0`、`dist/stage0`、应用身份和环境变量保留兼容。网关、管理用例、同步/监督、CLI、本机事务/会话、模型来源/偏好/发布、协议转换、代理、网页与 Rust 外壳已按实际职责分层，实际路径见[当前架构](../architecture/repository-layout.md)。

## 本轮验证矩阵

本轮结果对应 2026-11-06 工作树，尚未提交固定版本。原生构建、隔离运行与窗口实机分别登记。

| 验证 | 本轮结果 | 范围与缺口 |
| --- | --- | --- |
| 全量 Python | 518 项执行，2 项平台相关跳过，其余通过 | 当前宿主回归，跨平台模拟与真实系统分别登记 |
| 桌面 Python | 24 项通过 | 工程入口、资源、协议和生命周期回归 |
| 本机平台专项 | 44 项通过 | Windows/macOS 模拟分支、旧导出身份及延迟导入，真实应用控制另验 |
| Node 网页/桌面事件 | 94 项通过 | 原 89 项与新增 5 项模块回归，浏览器与 Tauri 窗口另验 |
| HTTP 页面入口 | 12 个脚本、5 个只读 API 通过 | 本地 HTTP 响应与精确静态路径，未覆盖浏览器渲染 |
| wheel | 最终构建成功，精确 107 个 Python 模块与 16 个网页资源 | 临时目录验证两个 CLI 入口，旧 build/lib 拷贝已清理 |
| Intel Cargo | offline locked check/test/build 通过，Rust 4 项 | 含原 3 项和固定命令注册回归，未运行窗口和托盘 |
| 源码隔离 verify | 最终 21 项、16 个资源通过 | 临时配置、模拟上游、本地 worker |
| PyInstaller 冻结 verify | 最终 21 项、16 个资源通过 | Intel onedir 资源、控制命令及子进程 |
| `.app` 内 verify | 最终 21 项、16 个资源通过 | 包内 sidecar 与运行库布局，未验原生窗口 |
| 冻结控制器生命周期 | 最终 1 项通过，约 17 秒 | 隔离配置与真实本地 worker，未操作真实 Codex |
| 根构建入口 | `STAGE0_OPEN_APP=0 bash scripts/build_desktop.sh` 最终通过 | 每次构建均执行包内 verify，构建后未启动窗口 |
| Windows 新目录链路 | 未在本轮原生执行 | 编译、便携目录、冻结运行及交互需 Windows 复验 |
| Apple Silicon | 未在本轮原生执行 | arm64 构建、冻结、交互和安装独立验收 |
| 真实浏览器与原生交互 | 本轮未验 | CUA 尝试受 Work 设置 disabled 限制，页面/托盘实机待验 |
| 干净机器与签名 | 待验收 | 无 Python/Git/源码、安装升级、签名/公证 |

最终三个报告均位于 `desktop/build/stage0/`，分别为 `source-results-macos-x86_64.json`、`frozen-results-macos-x86_64.json` 和 `packaged-results-macos-x86_64.json`。本轮编译和隔离结果不能覆盖历史未完成的托盘点选、持续隐藏、真实 Dock 重开或真实 Codex 重启。完整构建命令复现见[验证指南](validation.md)。

## 继续推进

1. 按平台补齐托盘、正常退出、恢复、断连、超时、实例锁、外部服务及真实客户端生命周期检查。模拟测试只能证明被模拟分支。
2. 在新目录补齐 Windows/Apple Silicon 原生构建及双平台交互，并继续检查冻结命令、资源与当前指南路径。迁移方案见[工程重构规划](../plans/desktop-and-documentation-refactoring.md)。
3. 完善正式 bundle、release 产物、版本与校验和。D08 已评审确认本轮保留 preview/stage0 应用身份和阶段产物目录，后续更名需独立实施。macOS 签名与公证、Windows 签名与安装包分别处理。
4. 在无 Python/Git/源码的目标环境检查安装、启动、更新保留数据、退出与恢复。
5. 对照[原产品计划](../archive/desktop/stage0-plan.md)核对首次使用对官方缓存的依赖、来源切换、独立目录成员管理及产品级单实例体验。日志和白名单诊断在页面对齐记录中已有实现说明，源码已恢复，仍需验证桌面入口与原生体验，再确定具体缺口。

原计划和交接全文继续保留，未完成项目在进一步逐项审查前保持开放。历史日志和测试包已部分清理，存在过的本机产物不能作为当前可用下载包。


## D07 章节归属与待迁移清单

本轮保留原文，新增当前指南。以下映射按原文章节归类，历史全文已归入 `dev-docs/archive/desktop/`，旧路径保留原标题及章节跳转。当前命令已更新到新目录，Intel 编译及三层 verify 已复验。D07 链接/路径验收已完成，跨平台构建与用户操作的最终验收仍保持开放。

| 原文及章节 | 当前主题 | 保留及待补内容 |
| --- | --- | --- |
| `build-macos-intel.md` 环境、一条命令、隔离原型、失败定位 | [macOS 构建](build-macos.md)、[开发](development.md) | Intel 限制与真实产物已提取，旧早期“无法组装 app”描述留作历史 |
| 同文管理操作、常驻退出、首次加载与运行库 | [协议](private-protocol.md)、[生命周期](lifecycle.md)、[打包](packaging.md) | 2026-11-01 性能样本及执行条件保留原文，已历史归档 |
| `build-windows.md` 环境、构建、linker、产物验证 | [Windows 构建](build-windows.md)、[打包](packaging.md) | Build Tools 用户反馈与编译记录分别保留，已历史归档 |
| 同文 Windows 托盘 | [生命周期](lifecycle.md)、双语用户 desktop 指南 | 当前平台退出差异已提取，交互实机待验收 |
| `private-management.md` 入口、网页适配、固定操作 | [协议](private-protocol.md) | 已提取当前边界，固定操作与 web_api 路径/字段已逐项核对，完整错误集合以源码白名单为准，历史“仅 macOS 重启”按 Windows 增量修正 |
| 同文生命周期及三个 macOS 增量 | [生命周期](lifecycle.md)、[验证](validation.md) | 外部网页服务所有权已提取，原生弹窗焦点实现依据和实测保留原文 |
| `web-desktop-alignment.md` 共用页面、只读预览、已实现规则 | [开发](development.md)、[协议](private-protocol.md) | 详细职责与平台边界已进入 `dev-docs/architecture/`，目标目录与当前入口分别说明 |
| 同文会话索引、目标边界、网关恢复、可靠性/桌面/日志修复 | [生命周期](lifecycle.md)、本页状态 | 索引事务细则继续以原文及用户会话迁移指南为依据，目录架构与平台边界已独立整理 |
| 同文 macOS 状态栏、首次加载退出、弹窗焦点、接入页密度 | [生命周期](lifecycle.md)、[验证](validation.md) | 日期、平台、执行条件与测试数量留存原文，已历史归档 |
| `handoff.md` 目标、状态、代码入口、推进顺序 | [开发](development.md)、本页状态 | 当前概述已提取，旧状态与最新平台增量按时间区分 |
| 同文命令、产物启动、安全边界、会话提示 | [开发](development.md)、[验证](validation.md)、[打包](packaging.md) | 旧产物清理、隔离 HOME、UI 重启风险已保留，交接历史已归档 |
| 同文全部带日期增量及最终原生窗口补充 | [生命周期](lifecycle.md)、本页状态 | 原始验证范围保留，未把取消链路或跨关闭重开当成完整托盘验收 |
| `plan.md` 当前推进、范围、架构 | [开发](development.md)、本页状态 | 产品决策逐项仍以原文为完整清单，当前架构指南已提取，未来目标仍标注规划 |
| 同文生命周期、进程检测、配置数据诊断 | [生命周期](lifecycle.md)、[协议](private-protocol.md)、双语用户指南 | 固定目录和显式确认已提取，数据兼容、锁、诊断隐私已分别提取到开发约束、协议、生命周期和验证指南 |
| 同文分阶段实施、验证限制、待验证事项、推进顺序 | [验证](validation.md)、本页状态 | 所有未完成事项继续开放，取消的任务状态探测不重新列为缺口 |
| `stage0-validation.md` 全部日期和问题章节 | [验证](validation.md)、本页状态 | 当前方法与证据入口已提取，全文日期/平台/限制已整体归档，历史日志缺失不补写当前通过 |
| `stage0/README.md` Python/Tauri 命令、后续步骤、常驻接入 | [开发](development.md)、[验证](validation.md)、[打包](packaging.md) | 现行命令已更新，Intel 已复验；Windows/Apple Silicon 原生执行另验，工具历史已归档 |

### 归档与剩余路径检查

当前开发指南直接链接归档，`desktop/docs/` 和 `stage0/README.md` 保留原标题顺序、旧锚点与历史章节跳转。根导航、桌面工程导航和双语用户原理页已连接当前架构。归档目录另设索引，便于按来源找回原始证据。

当前指南、双语用户页、图标说明和 AGENTS.md 已同步新源码路径。历史归档保留当时路径，旧文档入口保留原标题锚点。`build/stage0`、`dist/stage0` 和 preview/stage0 应用身份属于保留的兼容契约，D08 已评审确认本轮保留。

D07 内容分类、有效决策提取、历史归档、双语行为对照、相对链接/锚点和命令路径核查已完成。D09 本轮源码清理包括新目录调用方、精确资源路径、平台导入与公共兼容导出核查，旧文档入口和应用身份继续保留。Intel 新目录链路已复验。Windows、Apple Silicon、原生交互与干净环境命令仍有待验证，专项最终验收保持开放。

## 本轮网页测试对齐

2026-11-06 独立复现 `tests/test_web_models.cjs` 的旧 Chat 模型断言失败。依据 HEAD `c0dc29a` 的 Responses-only 与 native 默认，将其替换为省略协议字段的默认模型返回 native 及空 adaptations 的断言，保留原有 native 局部适配和 portable 回退覆盖。聚焦测试 7 项、历史对齐批次的完整 `node --test tests/*.cjs` 89 项通过。随后 R24 拆出 shared 与 features，保留这 89 项行为并新增 5 项初始化/接口回归，最终 94 项通过。该结果仅为本次 Node 回归，未执行浏览器或 Tauri 原生交互。临时日志位于 `/tmp/codex-hybrid-web-models-aligned.log` 与 `/tmp/codex-hybrid-web-aligned.log`，后续可按命令重建。

## 本轮独立修正与最终清理

- 会话恢复在取得运行目录锁及 Codex 目录锁后重新读取 journal，复核仍为 applying 后才执行恢复，避免等待锁期间另一进程已恢复而重复使用旧状态。并发、保留 journal 与重试回归已纳入全量结果。
- IPC 安全白名单恢复 `CC_ROUTING_PROVIDER_UNMATCHED`、`CC_ROUTING_PROVIDER_AMBIGUOUS`、`CLIENT_CONFIG_REWRITE_UNSAFE` 三个固定码，与浏览器业务反馈对应；异常原文和上游正文继续经过既有安全边界。固定码与脱敏回归通过，最终 wheel/冻结产物已包含修正。
- `service.migrate_routing` 的公共 runtime 适配已补回，原公开入口保持兼容。嵌套资源测试改为完整相对路径，最终全量通过。清理两份历史 setuptools `build/lib` 模块副本后，wheel 精确包含当前 107 个 Python 模块与 16 个网页资源。
- 最终 Ruff 与 `git diff --check` 通过。上述结果均对应本轮未提交工作树，真实 Windows、Apple Silicon、页面/托盘、真实 Codex 启停以及无 Python/Git/源码的干净机器验收继续开放。
