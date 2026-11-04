# Spec: CC Switch 第三方配置下的无缝混合路由

来源意图：[dev-docs/intent/cc-switch-third-party-routing.md](../intent/cc-switch-third-party-routing.md)

## Status

Approved by the user on 2026-11-03.

## Objective

让已经通过 CC Switch 使用第三方厂商的 Codex 用户可以直接开启 Hybrid。接管时保留当前厂商的全部模型，只把其他 CC Switch 记录列为待添加项；关闭 Hybrid 时恢复接管前的配置，而不是强制使用 OpenAI。

核心用户故事：

- 当 Codex 使用 CC Switch 的 DeepSeek 配置时，我能开启 Hybrid，并继续使用 DeepSeek 的所有模型。
- 添加模型时，我只看到 GLM、千问等其他厂商的待添加模型；DeepSeek 已作为现有模型存在。
- 当同一厂商存在多个 CC Switch 记录时，各记录继续保持独立，不因显示名相同而合并或误用 Key。
- 当我关闭 Hybrid 时，Codex 恢复开启前的 provider、模型选择和其他接入字段。
- 当 CC Switch 在 Hybrid 开启期间覆盖 Codex 配置时，Hybrid 停止宣称接管成功，不自动与 CC Switch 争抢配置文件。

## Product Contract

### 当前配置的权威来源

- Codex `config.toml` 是当前配置的唯一权威。
- CC Switch `providers.is_current` 只作为辅助信息；即使它与 `config.toml` 冲突，也不能覆盖配置文件中的事实。
- 当前第三方 provider 配置必须唯一匹配一个受支持的 Codex CC Switch 记录。
- 匹配不到记录或匹配到多个记录时，拒绝开启 Hybrid，返回可区分、可展示的错误，不进行基于地址、厂商名或模型名的猜测。
- 当前配置含 profile、缺少 provider 表、协议不受支持或凭据不可解析时，沿用现有的明确拒绝语义。

### 模型目录与身份

- 当前厂商首次被识别时，其模型目录和 `config.model` 中可解析的全部精确模型 ID 自动加入当前 CC Switch 来源的 Hybrid 模型成员。后台同步同样执行首次识别与导入。
- 当前厂商的模型出现在“已添加模型”区域，不出现在待添加列表；其他厂商的模型仍为未添加，进入待添加列表。
- 自动加入只执行一次。对已经完成首次导入的同一来源、同一 CC Switch 记录，用户后续删除的模型不得在后台同步或重新开启 Hybrid 时被静默加回。记录后续新增的模型需要手动添加。
- 同一记录内的重复模型 ID 只保留一个目录项；厂商显示名或模型显示名变化不改变模型身份。
- 不同 CC Switch 记录即使拥有相同厂商显示名、相同模型 ID，也必须保留为不同 slug，并能分别解析到各自的实时 Key 和端点。
- 已添加模型之后可由用户逐个删除；删除不写回 CC Switch。
- 其他厂商不会因开启 Hybrid 自动加入；仍遵循现有“发现后手动添加”的规则。

### 开启 Hybrid

- 当 Codex 处于唯一可匹配的 CC Switch 第三方直连配置时，接入开关必须可用，而不是显示为 `unsupported`。
- 从第三方直连开启时，生成的本地 Hybrid provider 不要求 OpenAI 登录；Codex 不应因缺少订阅认证而弹出登录验证。本地访问仍由 `X-Connected-Token` 校验。
- 从第三方直连开启时，模型目录不得混入 OpenAI 官方模型，也不得请求 OpenAI `/models` 获取 GPT 系列模型。
- 第三方模型条目必须声明可在 Codex 中选择的多个推理强度，至少包含 `low`、`medium`、`high`。
- 开启前先发布包含当前厂商模型的 Hybrid 模型目录，再进入现有配置预览、确认、会话索引迁移和配置提交事务。
- `original-config.toml` 保存开启前的实际 Codex 配置，包括第三方 `model_provider`、模型选择和其他接入字段。
- 生成的候选配置使用现有 `codex-hybrid` provider 和模型目录，不复制 CC Switch 业务到桌面外壳或平台专用模块。

### 关闭 Hybrid

- 关闭动作恢复本次开启前保存的 provider 和模型基线，不强制切换到 `openai`。
- 会话索引迁移目标使用恢复后配置中的实际 provider；当前模型名不能在关闭时被无条件替换成官方模型。
- 只恢复本工具管理的接入字段，并保留开启期间用户对无关配置的修改；这不是整个 `config.toml` 的字节级回滚。
- 配置基线缺失、损坏，或 `model_provider`、`model_catalog_json` 与接入时不一致时，停止关闭操作并返回现有恢复错误，不执行部分恢复。
- 2026-11-05 用户确认：关闭时允许清理已修改的 `[model_providers.codex-hybrid]` 表及其子表；预览后发生任何配置变化仍须重新确认。正常关闭后重新开启会生成新的 provider 表。

### 运行期外部覆盖

- Hybrid 开启期间，如果 CC Switch 将 `config.toml` 的 `model_provider` 改为其他 provider，下次状态读取必须识别为“配置已变化/接入已关闭”，不能继续显示为 `project`。
- 2026-11-05 用户明确范围：页面按 provider 选择显示接入状态，表内字段的生效与有效性由 Codex 处理。
- 检测到覆盖后继续以外部写入的 Codex 配置为准。
- 2026-11-05 用户确认：后台自动读取 CC Switch 更新，按实际 Codex 配置唯一匹配当前记录。新记录首次被识别时自动导入其全部模型并保存首次导入标记，可以在用户重新开启 Hybrid 前完成。
- 用户再次开启 Hybrid 时，以当时实际的 Codex 配置重新执行唯一匹配并建立新的接入前基线。此前来源的已添加成员和首次导入标记保持来源内持久化。

## Tech Stack

- Python 3.11+
- SQLite 只读访问 CC Switch 3.20.x 数据库
- Python `tomllib`
- 原生 HTML/CSS/JavaScript 管理页

## Commands

```sh
# JavaScript syntax checks
node --check src/management/web/app.js
node --check src/management/web/models.js

# Python static checks provided by the repository configuration
.venv/bin/python -m ruff check src
```

If `ruff` is not installed in the existing environment, record that limitation instead of replacing the check with a different linter.

## Project Structure

- `src/model_catalog/cc_switch.py`: CC Switch 只读读取、记录解析、当前记录匹配候选和安全边界。
- `src/model_catalog/sources.py`: 来源偏好、已添加成员和模型目录合并。
- `src/management/service.py`: 管理状态、首次导入、模型偏好持久化和网页 API 数据。
- `src/management/routing.py`: Codex 配置预览、基线恢复和路由事务。
- `src/codex_integration/session_migration.py`: 会话索引的 provider 迁移。
- `src/management/web/`: 接入状态、已添加模型和待添加模型界面。
- `dev-docs/specs/`, `dev-docs/intent/`: 本功能的规格和已确认意图。

平台专用目录 `src/codex_integration/windows_*`、`src/codex_integration/macos_client.py`、桌面外壳和安装脚本不属于本功能修改范围。

## Code Style

沿用仓库现有风格：共享业务使用小函数，公开状态不包含凭据，预期错误使用稳定的 `ConfigError` code，前端错误通过 `errorMessage` 映射。示例：

```python
if not matches:
    raise ConfigError('CC_ROUTING_PROVIDER_UNMATCHED')
if len(matches) > 1:
    raise ConfigError('CC_ROUTING_PROVIDER_AMBIGUOUS')
```

核心约束：

- 不把 API Key、认证头或含 Query 的 URL写入日志、状态响应或模型目录。
- 模型路由身份使用 `app_type + provider_record_id + exact model_id`。
- 匹配、首次导入和路由恢复均应是可重复规划、可测试的纯逻辑；文件写入继续经过现有锁和事务。
- 平台分支保持显式；共享层不得调用平台 API。

## Testing Strategy

Python 单元与集成测试覆盖：

- CC Switch 当前记录辅助字段读取、旧数据库结构兼容，以及不泄露凭据。
- `config.toml` 唯一匹配、无匹配、多重匹配、`is_current` 与实际配置冲突。
- 当前厂商全部模型首次加入、跨记录同名模型不合并、同一记录重复 ID 去重。
- 用户删除后后台同步或重新开启不自动恢复。后台同步中实际配置切换到新记录时首次导入该记录，其他厂商保持待添加。不同 CC Switch 数据库偏好隔离。
- 从第三方直连开启 Hybrid 的配置候选、基线、预览 revision、提交及失败回滚。
- 第三方基线生成的 provider 不要求 OpenAI 登录，第三方模型可在没有订阅 Bearer 时通过本地鉴权路由；官方模型仍要求订阅认证。
- 第三方模式发布的目录只包含第三方模型，`/models` 返回本地目录且不访问 OpenAI；官方模式仍保留原有官方目录刷新行为。
- 第三方模型目录包含 `low`、`medium`、`high` 推理强度。
- 从 Hybrid 关闭到第三方 provider 的会话迁移和配置恢复。
- Hybrid 开启期间配置被外部覆盖后的状态变化、后台首次导入新记录及已有导入标记的持久化。

前端 `node:test` 覆盖：

- 第三方直连状态可显示开启入口，不再一律显示“无法切换”。
- 当前厂商模型进入已添加列表，其他厂商进入待添加列表。
- 同名记录仍显示为两个独立可操作模型。
- 外部覆盖后显示接入已关闭/配置已变化，不显示成功的运行状态。

验证范围是本机 macOS 开发环境的自动化与隔离临时目录测试。模拟测试不能宣称 Windows 实机或 macOS 桌面端完整验收；平台专用行为不应发生变化，但仍须由完整 Python/前端回归确认现有断言。

## Boundaries

### Always

- 先验证 `config.toml` 的唯一记录匹配，再进行目录发布或配置写入。
- 在目录和 `settings.json` 快照中保持模型身份、成员和首次导入状态的原子性。
- 保留已有功能：官方模型、独立 YAML 来源、历史迁移、模型兼容适配和请求路由。
- 运行相关 Python 与前端回归，并在说明中写清平台和验证范围。
- 在模型、配置或状态行为变化时同步更新中英文用户文档。

### Ask First

- 修改现有 `openai` 路由 API 模式的外部含义，或以不兼容方式新增状态枚举。
- 改变“保留无关配置修改”的现有恢复语义。
- 修改 CC Switch 数据库结构或任何写数据库能力。
- 需要调整 Windows/macOS 平台专用进程、桌面或启动行为。

### Never

- 根据厂商名、模型名或地址猜测 CC Switch 记录。
- 合并不同 CC Switch 记录或跨记录复用凭据。
- 自动启用实际配置对应记录以外的其他厂商模型。
- 在 Hybrid 开启期间自动重写被 CC Switch 覆盖的配置。
- 在日志、管理 API、模型目录或测试失败信息中暴露 Key、认证头或其他敏感配置。
- 修改 CC Switch 数据库或桌面外壳中的共享业务副本。
- 删除、跳过或弱化现有测试来使新行为通过。

## Success Criteria

1. 当前 `config.toml` 唯一对应 DeepSeek CC Switch 记录时，接入开关可用。
2. 从 DeepSeek 开启 Hybrid 后，Codex 不要求 OpenAI 登录，第三方模型请求可以通过本地鉴权正常路由。
3. 第三方模式下模型列表不包含 GPT 系列官方模型，也不会请求 OpenAI `/models`。
4. 第三方模型可选择 `low`、`medium`、`high` 推理强度。
5. 首次接管后，`deepseek-v4-flash`、`deepseek-v4-pro` 均为已添加 Hybrid 模型，其他厂商模型仅在待添加列表。
6. 用户删除其中一个 DeepSeek 模型后，关闭并重新开启同一配置不会把它静默加回。
7. 两个同名 DeepSeek CC Switch 记录保持两个独立模型 slug，分别使用各自凭据。
8. 从 DeepSeek 开启 Hybrid 后再关闭，Codex 恢复第三方 provider 和原模型，不改用官方模型。
9. 无法唯一匹配 CC Switch 记录时不发生配置或目录写入，并显示明确错误。
10. Hybrid 开启期间 CC Switch 覆盖配置后，页面不再显示 Hybrid 仍处于接管状态，且配置不会被自动抢回。
11. 相关 Python、Python 全量、前端回归和 JavaScript 语法检查通过；平台专用代码未被修改。

## Open Questions

None. Resolved before approval:

1. Restore only Hybrid-managed fields and retain unrelated edits made while routing was active.
2. After a record's one-time import, models added to that record later require manual selection in Hybrid.
