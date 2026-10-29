# 工作原理

[English](../en/architecture.md) · **简体中文**

[返回首页](../../README.zh-CN.md) · [文档导航](README.md)

```text
Codex：用户目录 config.toml + 所选数据目录 models.json
                         ↓
              本地网关（127.0.0.1:18891）
                 ├─ 官方模型 → OpenAI 官方订阅端点
                 └─ 第三方模型 → 所选供应商 API
                                      ↑
                             YAML / CC Switch 只读来源
```

Codex 从自身的 `config.toml` 读取网关地址及模型目录路径；本地网关读取数据目录中的
`settings.json`，再加载当前 YAML 或 CC Switch 来源。主 agent 与子 agent 共用原生模型目录，
按模型 key 路由，不经过 MCP。

网关收到 `/models` 请求时，复用 Codex 携带的订阅凭据及查询参数刷新官方目录，不额外读取登录文件。刷新成功后同步发布合并目录与路由白名单；刷新失败时返回与当前白名单一致的上次目录，保留配置并允许继续调用。没有有效缓存时返回 `OFFICIAL_MODEL_LIST_UNAVAILABLE`。该行为不修改 Codex 界面，也不自动替换用户选择的模型。

官方请求也经过本地网关。官方订阅认证仅发送给固定官方端点，第三方请求使用对应供应商 Key。
配置、凭据、令牌和备份保存在所选数据目录；含凭据文件不要提交版本控制。
生成文件使用 POSIX `0600` 权限，Windows 依赖目录 ACL。

### 协议兼容边界

第三方 Responses 默认开启 Portable 兼容模式；显式选择 `responses_compatibility: native` 时使用原生路径：保留请求字段、消息类别、工具 namespace、独立工具输出、推理与加密字段，以及返回的工具参数增量事件。仅替换地址、认证、模型 ID，并应用显式配置的参数、输出预算和禁止存储策略。不注入外部模型提示词，不转换工具结构，不自动重试生成或切换协议。端点不支持这些特性时返回错误。

Chat Completions 使用现有兼容转换。Responses 默认（或显式设置 `responses_compatibility: portable`）使用同样的兼容桥：可读历史推理或摘要变为普通历史文本，不转发不透明推理；system/developer 消息归并到系统指令区；工具定义展开并映射名称。这是语义降级，不保证与原生请求等价。

历史迁移独立于协议选择。原生 Responses 可通过 `history_migration: true` 移除有完整内容的历史项存储 ID，保留 call_id、嵌套资源 ID 和纯 ID 引用；它不解密推理、不获取缺失历史，也不能保证不同服务的加密状态可复用。Portable 路径本身已包含此 ID 重放处理。官方路由维持现有历史迁移行为。

兼容桥的系统指令归并只处理消息，不把带 developer 角色的工具元数据当成文本。没有 `call_id` 的具名独立工具输出在原生路径保留；只有兼容桥将其降级为保留来源的 user 上下文，不伪造调用关系。真正带调用 ID 的工具结果保持原有配对。

历史工具调用缺少 namespace 且没有精确注册别名时，兼容桥只在短名称与调用类型能匹配唯一注册工具时补全绑定。显式 namespace 不会被改指向其他工具；未知、同名歧义或类型不匹配在转发前报错，调用 ID、参数与结果保留。Portable Responses 与 Chat Completions 共用此规则，原生传输和平台专用行为不变。

同一工具重复声明时，若执行结构完全一致，允许说明文字更新并保留最后遇到的说明；参数结构或绑定冲突仍然拒绝。

两个协议共用 SSE 分帧，支持多行数据及仅在 `event:` 中声明的事件类型。显式上游错误转换为脱敏的失败终态；协议类型不匹配单独报错。连接关闭和 `[DONE]` 本身不代表成功，不补造完成事件，不自动换协议。原生路径不重试生成；Portable Responses 保留原有未注册工具重试机制。兼容桥的协作工具说明来自本次实际注册的映射表；有歧义的短工具名不会被猜测执行。

模型添加名单与模型级兼容覆盖保存在 Hybrid 的 `settings.json`，CC Switch 数据库保持只读。偏好按来源区分，名单同时控制目录发布与实时路由。首次升级保留先前已发布的模型；后续发现的新模型只有添加后才可使用。模型级 Hybrid 设置优先于 YAML 模型设置，后者优先于厂商设置；显式 native 保留，缺省 Responses 使用 portable。

### 代码职责与复用边界

| 模块 | 职责 |
| --- | --- |
| `gateway/server.py` | HTTP 生命周期、认证和路由选择；`external_route` 组织第三方请求，不执行工具 |
| `model_catalog/` | 配置来源、模型目录、凭据解析和模型偏好 |
| `adapters/native_responses.py` | 原生 Responses 传输，历史 ID 迁移仅按配置启用 |
| `adapters/responses.py` | Portable 工具注册、历史映射、冲突检查和返回事件转换；Chat 共用这些规则 |
| `adapters/chat.py` | 在共用 Portable 转换之上处理 Chat 消息和流事件 |
| `adapters/coordination.py` | 原生协作 namespace 映射和请求内 spawn 名称一致性，独立于 Portable 转换 |
| `adapters/request_compat.py` | 历史重放、路由上下文和脱敏错误转换 |
| `management/` | 配置发布、管理 HTTP 接口和转发进程生命周期；服务层持有锁与配置快照，`routing.py` 组织路由预览与可恢复事务 |
| `desktop/configuration.py` | CLI 与管理路由共用的纯 TOML 转换：生成、识别、恢复受管字段和保留当前模型，不读写文件或调用操作系统 |
| `desktop/` | 客户端命令与服务、会话迁移和按平台分开的桌面控制 |
| `management/web/` | `app.js` 提供公共交互与接入编排，`models.js` 处理模型页面，`diagnostics.js` 在独立作用域内管理诊断时间范围与请求状态 |

Portable 请求按固定顺序处理：先注册本次请求和历史中发现的全部工具，再转换历史，随后检查重复工具的执行结构，最后生成实际可调用的协作工具说明。不要把工具发现移到历史转换之后：历史调用可能依赖后面才出现的工具定义。
