# Intent: CC Switch 第三方配置下的无缝混合路由

## 状态

已由用户确认，日期：2026-11-03。

## 问题

Codex 通过 CC Switch 选择第三方厂商后，`config.toml` 的 `model_provider` 指向该厂商，而当前管理路由入口只接受 `openai` 或 `codex-hybrid`，因此无法开启 Hybrid。即使允许接管，也不能把当前厂商排除在 Hybrid 模型目录之外，否则接管后正在使用的模型会立即失效。

## 目标

- Codex 由 CC Switch 第三方厂商启动时，可以开启 Hybrid。
- 从第三方厂商开启后不再额外要求 OpenAI 登录，第三方模型继续使用当前厂商凭据。
- 第三方模式下不请求 OpenAI 模型列表，不显示 GPT 系列官方模型。
- 第三方模型提供可选择的多种推理强度。
- 接管前 `config.toml` 实际使用的第三方配置是基线，不以 CC Switch 数据库中可能滞后的 `is_current` 为准。
- 当前厂商的全部模型自动成为 Hybrid 已有模型；其他厂商模型只进入待添加列表。
- 关闭 Hybrid 时恢复开启前完整的 Codex 配置，无论该配置指向哪个厂商。

## 模型身份与去重

- 当前厂商模型第一次被识别时自动加入，之后允许逐个移除。
- 同一 CC Switch 记录内的同一精确模型 ID 只出现一次。
- 模型身份始终使用 `app_type + provider_record_id + exact model_id`。
- 不同 CC Switch 记录即使厂商显示名、模型显示名完全一致，也保留为两个可独立路由的模型。
- 厂商显示名、模型 `displayName` 仅用于展示，不参与路由身份判断。

## 配置匹配

- `config.toml` 是当前正在使用配置的唯一权威。
- CC Switch `is_current` 只能辅助定位记录，与实际配置冲突时不得覆盖 `config.toml` 的事实。
- 当前 Codex provider 配置必须唯一匹配一个受支持的 CC Switch 记录。
- 找不到记录或匹配到多个记录时拒绝接管，并明确提示无法唯一匹配；不得通过地址、厂商名或模型名猜测。

## 运行期冲突

- Hybrid 开启期间，如果 CC Switch 再次选择厂商并改写 `config.toml`，以该外部写入结果为准。
- Hybrid 检测到管理字段被替换后转为“接入已关闭 / 配置已变化”，不得自动重写并抢回配置。
- 用户再次开启 Hybrid 时，以当时实际的 Codex 配置建立新的接入前基线。

## 关闭语义

- “关闭接入”是撤销本次接管，不是强制切换到 OpenAI 官方模型。
- 关闭后恢复本次开启前保存的完整配置，包括当时的第三方 provider、模型目录引用、模型选择及其他用户配置。

## 范围外

- 不根据厂商名称、模型名称或 API 地址猜测 CC Switch 记录。
- 不合并不同账号、记录或 Key。
- 不自动添加当前厂商以外的模型。
- 不回写 CC Switch 数据库。
- 不改变现有历史兼容、模型适配或代理规则。
- 不改变 Windows/macOS 的代理、进程识别、桌面启停、后台服务、安装或平台专用代码。

## 验收表述

当前 CC Switch 激活 DeepSeek 时，Hybrid 应能把 DeepSeek 的全部模型作为已有模型带入，并允许开启路由；GLM、千问等其他厂商显示在待添加列表。关闭 Hybrid 后，Codex 恢复到开启前的 DeepSeek 配置。若配置无法唯一对应 CC Switch 记录，则不发生接管。

开启后的 Codex 不应因 Hybrid 接管而出现 OpenAI 登录验证，也不应混入 OpenAI 官方模型；DeepSeek 等第三方模型仍通过本地网关和各自厂商 Key 工作，并可切换 `low`、`medium`、`high` 推理强度。
