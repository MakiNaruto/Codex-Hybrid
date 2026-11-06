# 仓库目录与依赖边界

本页记录 2026-11-06 的当前目录。本轮已完成后端、平台模块、共享页面与桌面工程的职责归类，保留原公共符号和命令入口。现行构建命令见[桌面开发](../desktop/README.md)，目标方案见[桌面规划](../plans/desktop-and-documentation-refactoring.md)及仓库 `tasks/plan.md`。

## 当前目录

```text
src/
├── cli/                   已发布入口、bootstrap 与 commands/ 命令族
├── gateway/               HTTP 转发、路由装配、活动与传输
├── management/            Management 门面、commands、用例、同步与监督
│   └── web/               页面装配、shared/ 控件与 features/ 功能
├── codex_integration/     本机配置、服务、sessions/、platforms/ 与私有协议
├── model_catalog/         sources/ 来源包、preferences 与 publication
├── adapters/              原生传输、history/context/stream_errors 与 portable/
└── infrastructure/        共享错误、文件、锁、日志、SSE 与上游错误契约
desktop/
├── src-tauri/             Tauri 装配、ipc/lifecycle、托盘与原生弹窗
├── sidecar/main.py        冻结运行入口与兼容验证分派
├── tools/                 构建路径、sidecar、平台脚本和 macOS 组装
├── validation/            夹具、隔离检查、盘点与临时配置往返
├── tests/                 桌面契约与生命周期回归
├── stage0/                旧工具文档锚点兼容入口
├── docs/                  旧文档入口及章节兼容导航
├── build/                 可再生缓存、组装应用与报告
└── dist/                  可再生 sidecar 与便携目录
scripts/                   根构建入口和分平台安装/服务入口
docs/{zh-CN,en}/            双语用户任务指南
dev-docs/                  当前开发指南、规划、决策与历史归档
tests/                     当前 Python 与 Node 回归入口
```

桌面源码已分离为应用、构建、验证与测试目录。构建缓存和产物继续使用 `build/stage0`、`dist/stage0`，应用名、标识和 `STAGE0_*` 环境变量保持兼容。`codex_integration/platforms/` 已接管平台实现，旧模块精确导出同一函数/类。

后端网关已拆为 `server.py` 装配、`http_handler.py` HTTP 边界、`routing.py` 路由、`official_catalog.py` 官方目录及 `streaming.py` 流式处理。`infrastructure/` 已承接 errors、files、locking、runtime_log、sse 和 upstream_errors。管理 `use_cases/`、`commands.py`、同步与监督，以及本机 `sessions/` 已按实际职责提取。目标方案中尚未产生实际复用价值的子拆分保持现有模块。

## 运行与管理入口

```text
浏览器 → management/http.py → Management 与 ManagementContext
桌面共用页面 → 固定 Tauri 命令 → desktop-controller → 私有白名单 → 同一管理业务
CLI → cli.__main__ → 本机集成与管理业务
管理业务 → ForwardingRuntime → 自管网关子进程 → gateway/server.py
```

浏览器与桌面的鉴权和传输边界分别维护。桌面不通过交互式 CLI 调用业务，页面适配不能放宽浏览器 Host、Origin 与认证检查。网关保留模型 HTTP 转发接口，桌面 stdio 本身不开放管理 HTTP 监听。

| 当前模块 | 责任与约束 |
| --- | --- |
| `gateway/server.py`、`routing.py`、`official_catalog.py`、`streaming.py` | 分别承担 HTTP 装配、路由、官方目录与流式终态，HTTP 边界位于 `http_handler.py`，原 `external_route` 等兼容导出保持可调用 |
| `gateway/transport.py` | 网关与管理连接测试共用的上游传输入口，每次请求发现平台代理 |
| `management/service.py` | Management 门面与锁/配置快照，委托具体用例 |
| `management/commands.py` | HTTP 与私有 IPC 共用业务分派，入口各自先执行认证和白名单 |
| `management/use_cases/` | `catalog.py` 来源/目录、`providers.py` 厂商、`models.py` 偏好与成员、`connection_test.py` 连接测试 |
| `management/routing.py`、`codex_integration/routing.py` | 原管理路由入口兼容导出，本机集成负责字段恢复、预览与可恢复配置/索引事务 |
| `management/runtime.py`、`supervisor.py`、`forwarding_worker.py` | 管理上下文与服务装配、转发子进程监督、本地 worker |
| `management/synchronization.py`、`cc_watch.py` | 来源同步调度与平台文件通知，保留监听失败后的定期校准 |
| `management/http.py` | 浏览器 HTTP 边界与认证，静态资源使用精确路径白名单 |
| `cli/__main__.py`、`bootstrap.py`、`commands/` | 已发布命令、运行选择及 service/management/routing/models/sessions/parser 命令族 |
| `codex_integration/service.py`、`service_lifecycle.py`、`installation.py` | 公共服务兼容入口、服务生命周期、本机配置准备 |
| `codex_integration/controller.py`、`web_api.py` | 常驻桌面控制器、私有请求白名单与共享管理分派适配 |
| `codex_integration/configuration.py` | 纯 TOML 转换，生成、识别、恢复受管字段及保留当前模型 |
| `codex_integration/sessions/` | inventory 盘点、planning 计划、transaction 事务、recovery 恢复及 index 补齐 |
| `codex_integration/session_migration.py`、`codex_index.py` | 原公开会话 API 兼容入口，委托 sessions 实现 |
| `codex_integration/client.py`、`platforms/` | 本机公共入口按平台延迟导入 Windows/macOS 实现，旧模块精确导出 |
| `model_catalog/catalog.py`、`sources/__init__.py`、`cc_switch.py` | 配置领域校验、来源选择与兼容公共符号、只读 CC 数据解析 |
| `model_catalog/preferences.py`、`publication.py` | 来源隔离、成员与兼容偏好、目录合并/快照和路由名单 |
| `adapters/native_responses.py` | 原生 Responses 传输、按配置启用的历史迁移与局部适配 |
| `adapters/portable/responses.py` | 显式 portable 的工具注册、历史绑定、冲突校验与事件转换，原 responses 模块兼容导出 |
| `adapters/history.py`、`context.py`、`stream_errors.py` | 纯历史转换、请求上下文和协作说明、安全失败事件，request_compat 保留原公开符号 |
| `adapters/coordination.py` | 请求内协作别名与工具调用命名约束 |
| `management/web/app.js` | 状态和传输装配，组装共享控件与功能模块，保留既有页面接口 |
| `management/web/shared/` | DOM/原生选择控件与提示、错误映射、草稿保护 |
| `management/web/features/` | providers 厂商/模型编辑与 routing 接入/活动/进程控制，显式小接口初始化 |
| `management/web/models.js`、`diagnostics.js`、`usage.js` | 模型成员设置、诊断和用量页面，继续使用共用接口 |
| `management/web/transport.js`、`desktop.js` | 浏览器/桌面传输选择及桌面初始化/托盘操作 |
| `desktop/sidecar/main.py` | 冻结运行分派入口与多进程 freeze_support，验证模式延迟委托 `validation/probe.py` |
| `desktop/src-tauri/src/main.rs` | Tauri 装配、固定命令注册与事件接线 |
| `desktop/src-tauri/src/ipc.rs` | 串行 sidecar 会话、限额、超时、响应配对与状态轮询 |
| `desktop/src-tauri/src/lifecycle.rs` | 关闭隐藏、安全退出、原生菜单及所有权释放 |
| `infrastructure/proxy/` | 共用代理入口和 Windows/macOS 专用选择，gateway/transport 保留公共传输入口 |

## 数据与协议契约

模型目录发布与实时路由同时执行按来源隔离的成员名单。Hybrid 模型偏好高于 YAML 模型和厂商默认，CC Switch 数据库只读。当前第三方上游为 Responses-only，缺省兼容模式为 native，portable 与局部适配由用户显式选择。历史方案中的 Chat 支持与 portable 默认按当时记录阅读。

Portable 先注册本次与历史发现的全部工具，再转换历史、验证执行结构及生成协作说明。历史短名只在调用类型和唯一注册工具匹配时补全，显式 namespace 保持绑定，歧义与结构冲突在转发前失败。`ResponsesAdapter` 与其工具注册表在当前请求内保持同一实例，tools/history 没有为目录整齐而进一步拆分。SSE 终态必须来自明确事件，EOF 和 `[DONE]` 本身不能生成成功。

恢复事务保持备份、首次基线、锁、版本复核及中断恢复语义。公共文件工具提取时，原子替换、持久化写入与配置事务是不同契约，不能合并后丢失调用方依赖。源目录搬迁同时核查静态资源、动态导入与冻结 spawn 入口。

## 构建和资源边界

`pyproject.toml` 当前显式列出六个业务包与新增 `infrastructure`，静态清单包含 `management/web/` 根资源及 `shared/*.js`、`features/*.js`。HTTP 对五个嵌套脚本逐项列白名单，冻结资源检查使用相对路径。PyInstaller 还需包含动态加载的各平台本机模块，源码导入成功后继续执行冻结运行验证。

macOS 与 Windows 的根构建脚本转发到 `desktop/tools/`，各平台工具分别维护环境引导和产物契约，详情见[打包](../desktop/packaging.md)。平台 API、代理、退出和安装脚本边界见[平台约定](platform-boundaries.md)。

## 目标迁移与证据

本轮已整理网关、管理用例/同步/监督、CLI 命令、本机接入与会话事务、来源/偏好/发布、协议历史/上下文、代理、共享网页和 Rust 外壳。保留既有 public 符号、命令、数据格式及阶段产物名称。后续以实际调用方与平台验收为依据收敛兼容层。

本页是当前结构核对。历史验证归入[桌面档案](../archive/desktop/README.md)，当前缺口与基线修复状态见[桌面状态](../desktop/status.md)。
