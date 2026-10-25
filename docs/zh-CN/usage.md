# 使用与验证

[English](../en/usage.md) · **简体中文**

[返回首页](../../README.zh-CN.md) · [文档导航](README.md)

### 测试模型连接

打开管理页，保存并启用模型，再点击“测试连接”。测试发送 `Reply exactly OK.`，
输出预算最多 32 tokens；若模型配置上限更低，则使用更低值。
成功仅表示这次基础请求完成，完整 Codex 会话和工具调用仍需单独验证。

### 在主会话中使用第三方模型

在 Codex 原生模型列表中选择已配置的模型，新建会话并发送：

```text
只回复：Hello World
```

预期回复 `Hello World`。新会话便于确认模型选择；完整会话包含系统提示、工具说明与历史，
输入量通常比管理页连接测试大。

### 让官方主 agent 调用第三方子 agent

主会话选择支持原生子 agent 的官方模型，发送以下最小 prompt。**先替换模型 key**：手动示例是 `deepseek/flash`，向导填写模式是 `custom/default`，CC Switch 以实际注册目录为准，可用 `status` 查看模型 key 列表。

```text
请创建一个原生子 agent，model 使用 deepseek/flash，fork_turns 使用 none，
reasoning_effort 使用该模型支持的 low。
子任务：只回复 CHILD_OK，不调用工具。
请先声明将使用哪个模型创建子 agent，创建后等待完成，再转述结果。
不要用主 agent 自己作答来代替子任务，也不要通过 MCP 或命令行代调用。
```

预期：主 agent 声明模型 → 原生子 agent 活动出现 → 子 agent 回复 `CHILD_OK` → 主 agent 转述。客户端需具备并允许原生子 agent 工具；若当前环境没有该工具，提示词本身不能启用它。

以原生子 agent 活动中的模型信息和网关日志核实实际路由，不能仅凭模型自称使用了某供应商。

<details>
<summary>验证范围与截图说明</summary>

以上回复均为预期示例，请在自己的桌面会话中验证该子 agent 流程；
连接测试的 32 tokens 是输出预算，不是总用量或费用保证。

</details>

## 日常管理

服务启停与状态查询见 [常用命令](../../README.zh-CN.md#常用命令)。后续命令自动使用安装时保存的默认数据目录；
目录优先级见 [命令行默认配置](cli.md#命令行默认配置)，迁移说明见 [数据目录](configuration.md#数据目录)。
执行 `refresh-models` 后需重启服务并完全退出、重开 Codex。

新增或删除模型后，需要更新客户端模型列表并重启 Codex。仅更新 Key 或 API 地址时下一轮请求生效。
更多操作见 [配置指南](configuration.md) 和 [命令与安装进阶](cli.md)。
