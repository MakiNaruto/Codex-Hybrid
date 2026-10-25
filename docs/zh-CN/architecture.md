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

官方请求也经过本地网关。官方订阅认证仅发送给固定官方端点，第三方请求使用对应供应商 Key。
配置、凭据、令牌和备份保存在所选数据目录；含凭据文件不要提交版本控制。
生成文件使用 POSIX `0600` 权限，Windows 依赖目录 ACL。
