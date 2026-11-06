# 桌面私有协议

Tauri 固定命令通过 stdin/stdout JSON 连接 `desktop-controller` 常驻 Python 进程。Rust 互斥锁串行配对响应。共享页面的桌面适配将请求表示为 `{action: "web_api", path, method, body}`，控制器检查路径、方法及字段白名单后调用共用管理业务。

## 边界

- 请求上限 64 KiB，Rust 接收响应上限 1 MiB。
- API Key 通过 stdin 传递。前端不接受任意 shell、程序或用户目录，错误不回传 stderr、异常原文或上游正文。
- 桌面默认读取 `~/.codex-hybrid` 与 `~/.codex`，不套用 CLI 的目录环境变量覆盖。
- 未初始化读取状态不创建数据目录。发现已有配置或显式初始化后可建立管理对象、锁及清理完成事务记录。
- 接入提交要求同一会话的有效预览，保存配置会使旧预览失效。断连和超时均不自动重放写操作。

## 操作约定

状态和快照返回脱敏字段。初始化读取官方配置与缓存，保存恢复基线且不自动开启接入。保存厂商与模型要求版本匹配，Key 留空保留，高级字段保留，CC Switch 只读。连接测试由用户主动触发，使用已保存配置，可能计费。

接入先预览再确认，提交前重新校验版本、活动和网关健康。残留接入恢复由用户明确触发。独立重启使用同会话单次票据，有效期两分钟，确认时复核进程身份。Windows 和 macOS 通过公共本机集成入口分别调用平台实现。旧协议文档的“仅 macOS 重启”已由 2026-11-05 Windows 增量扩展。

macOS 和 Windows 的 Rust 响应超时当前为状态、读取及退出 20 秒，`web_api` 连接测试 POST 75 秒，其余 POST 与管理操作 120 秒。超时断开会话并提示检查恢复状态。退出及外部服务所有权规则见[生命周期](lifecycle.md)。

固定命令注册入口为 `desktop/src-tauri/src/main.rs`，请求与会话位于 `ipc.rs`，退出位于 `lifecycle.rs`，Python 协议入口为 `src/codex_integration/controller.py`。完整历史操作表与后续增量保留在[私有协议历史](../archive/desktop/private-management-history.md)与[开发交接](../archive/desktop/handoff-history.md)。白名单变更需同时核查两端实现和冻结回归。

## 固定操作与错误契约

| 操作族 | 校验和结果 |
| --- | --- |
| `snapshot`、`status` | 脱敏配置、路由、网关和活动，已有配置可持有锁并清理完成事务 |
| `initialize` | 用户触发，官方配置与缓存存在，已有 settings/state 拒绝覆盖，准备恢复基线与管理鉴权 |
| `save_provider` | revision 匹配、独立管理来源、保留高级字段与留空 Key，保存发布目录并作废旧预览 |
| `test_connection` | 测试已保存配置，共用路由/传输与平台代理，60 秒上游超时，仅返回安全结果和耗时 |
| `preview_routing`、`cancel_preview` | project/openai 预检、刷新目录、签名与影响摘要，取消销毁待确认版本 |
| `save_desktop_preferences` | 开启/关闭分别保存 ask/auto/never，写偏好本身保持客户端状态 |
| `set_routing` | 同控制会话有效预览、明确活动确认、HMAC/版本复核与可选客户端操作 |
| `recover_forwarding` | 用户明确恢复，限定配置仍为 project，启动后复查外部配置变更 |
| `preview_restart`、`cancel_restart`、`restart_codex` | 两分钟、单次、同会话票据，确认复核安装与 PID/创建时间，互斥路由预览 |
| `shutdown` | 检查本窗口所有权、路由及停服条件，受阻返回 `EXIT_BLOCKED` |
| `shutdown_confirmed` | Windows 原生退出确认后使用，停止自管网关并保留路由配置 |
| `web_api` | 校验允许的路径、GET/POST 和字段后委托共用管理，排除通用 URL/任意后台函数与 `forwarding/ensure` |

上述为协议约束摘要。具体页面路径及字段逐项以 `src/codex_integration/web_api.py` 的当前白名单为准，新增端点同时检查 HTTP 入口鉴权与 IPC 入口权限。写入冲突、已有服务、无效预览和断连分别处理，界面只接收稳定业务错误与脱敏网络分类。

桌面页面使用私有会话，无需网页访问 token。未初始化时 `configured: false`，显式初始化前不读取诊断。独立 `desktop-snapshot`、`desktop-manage` 入口继续用于回归，窗口常驻会话使用同一预览签名和所有权。macOS 外部服务复用对写入、活动读取、重启票据作废和退出断连分别校验。

### 当前 web_api 白名单

GET 请求体必须为 null，允许 `state`、`activity`、`processes`，`diagnostics?days=1|7|30|all`，`diagnostics/errors/<64位小写十六进制ID>`，`usage?period=today|yesterday|7|30` 和旧式 `usage?days=1|7|30`。竖线在这里表示固定允许值，实际路径使用单个值。

POST 请求体必须为对象，字段精确满足以下规则。更深层业务约束由现有管理方法验证。

| 路径 | 必填字段 | 可选字段 |
| --- | --- | --- |
| `source` | `mode` | `cc_db_path` |
| `models` | `source_id`、`updates` | 无 |
| `provider` | `id` | `spec`、`api_key`、`delete` |
| `publish` | 无 | 无 |
| `test` | `key` | 无 |
| `routing/preview` | `mode` | 无 |
| `routing` | `mode`、`revision`、`confirm_activity`、`desktop_action`、`desktop_was_running`、`desktop_ticket` | 无 |
| `desktop/preferences` | `mode`、`value` | 无 |
| `runtime/recover` | 无 | 无 |

外层请求精确包含 `action`、`path`、`method`、`body`，非法形状返回 `INVALID_REQUEST`。路由和桌面偏好复用控制器校验。未配置且读取 `state` 返回 `configured: false`，其他操作返回 `NOT_CONFIGURED`。诊断记录缺失返回 `DIAGNOSTIC_RECORD_NOT_FOUND`。业务异常只有 `web_api.ERRORS` 明确列出的码可透传，其余按控制器安全错误处理。完整错误码集合保留在源码，修改时核对两端展示与冻结回归，避免复制列表与实现漂移。
