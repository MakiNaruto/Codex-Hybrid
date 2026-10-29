# Codex 桌面独立工具输出：源码与最终请求审计

> 实现更新：第三方 Responses 现默认保留原生结构；本文“当前网关”的对比记录的是审计时的旧实现。该降级现仅用于 Chat Completions 和显式选择 `responses_compatibility: portable` 的 Responses。独立的 `history_migration` 选项及配置方法见[配置说明](configuration.md#responses-原生与兼容模式)。

## 结论

Codex 正式支持一种独立工具输出（standalone function-call output）：具有 name、可选 namespace 和 output，没有 call_id。它不是损坏的调用配对。桌面发起 turn/start.toolOutput 后，app-server 主动构造这一类型；历史整理保留它；最终 HTTP /responses 仍发送这一类型，不补出 function_call，也不改成 user 消息。

现有网关将其变成 user 消息是第三方兼容降级，不是官方原行为的等价复刻。先前“只是换结构、不改含义”的表述过强：正文和来源得到保留，但模型可见的消息类别改变了。网关只改出站副本，不能据此推断 Codex 本地权限判断也随之改变。

## 核对版本与方法

- 本机桌面：/Applications/ChatGPT.app，版本 26.1023.51421。
- 桌面捆绑二进制：codex-cli 0.165.0-alpha.1.2。
- 全局 CLI：0.153.4。两者不能当作相同版本；前一阶段 CLI 成功不等于覆盖桌面路径。
- 对照官方源码 tag：rust-v0.165.0-alpha.1.2，commit 720fec862a608ae1e5878d1eecb04fb93192e93c。
- 读取桌面 app.asar 中主进程代码，核对 toolOutput 的传递；未修改应用。
- 运行真实桌面捆绑 app-server，连接仅本机假模型端点，发送人工任务。捕获真实出站 JSON；没有真实模型调用，没有修改现有网关或用户配置。

## 四层流转

### 1. 桌面 → app-server：JSON-RPC

桌面创建/恢复会话后，调用 turn/start。主进程的发送流程在存在 toolOutput 时令 input 为空，并将 toolOutput 传入 executeTurnStart。简化请求为：

```json
{
  "method": "turn/start",
  "params": {
    "threadId": "目标会话编号",
    "input": [],
    "toolOutput": {
      "name": "create_thread",
      "namespace": "codex_app",
      "output": "<codex_delegation>……任务及来源……</codex_delegation>"
    }
  }
}
```

这是客户端 RPC，不是模型 HTTP 请求。参数类型 TurnToolOutput 根本没有 call_id 字段。官方文档也公开说明 turn/start 支持独立工具输出。

### 2. app-server → 内部历史：ResponseItem

turn_processor.rs 检查 input 与 toolOutput 互斥，name 非空；随后显式创建 FunctionCallOutput，设置 call_id=None。turn_input.rs 明确允许这种输入启动或引导一个 turn。

id 是历史项身份，call_id 是工具调用配对身份，不能混用。app-server 可以为该项分配 fco_ 开头的 id，但不因此生成 call_id。

### 3. 历史 → 模型 Prompt

ContextManager::for_prompt 整理当前会话模型历史：对真实调用补齐缺失的中断结果，清理无对应调用的配对结果，并依据能力处理媒体。这里的孤立结果检查只对 call_id=Some 的结果要求配对；call_id=None 的具名独立输出被保留。

因此独立输出的结构为：

```text
目标会话既有历史
+ 独立外部工具输出（这次投递）
+ 本轮所需指令、环境与工具定义等上下文
```

不是为它构造一组不存在的“模型调用 A → A 的返回结果”。普通真实工具循环仍然保留它自己的 function_call/call_id/output 配对。

### 4. Prompt → 最终 HTTP /responses

client.rs::build_responses_request 从整理后的历史构造 ResponsesApiRequest，并根据 Responses Lite 等能力注入工具定义/指令前缀，处理内部元数据与加密字段。prepare_response_items_for_request 处理项 ID 和能力字段；这些步骤没有把独立输出转换为 user 消息。

codex-api 的 ResponsesClient::stream_request 编码该请求并 POST 到 /responses。本机捕获到：

```json
{
  "model": "gpt-6.1-sol",
  "input": [
    "……此处省略其他真实上下文项……",
    {
      "type": "function_call_output",
      "id": "fco_人工测试记录编号",
      "name": "create_thread",
      "namespace": "codex_app",
      "output": "<codex_delegation>……人工任务……</codex_delegation>"
    }
  ],
  "stream": true,
  "store": false
}
```

上例为删减展示；input 中的省略字符串不是实际协议项。真实捕获中相关通知没有 call_id，整个请求中的 function_call 数量为 0。完整的安全捕获证据位于 test-results/codex-wire-audit-2026-10-29.json。

## 与当前网关的对比

| 环节 | 原生 Codex | 当前网关外部路由 |
|---|---|---|
| 独立通知类别 | function_call_output，call_id 缺省 | 转为 message，role=user |
| 来源 | name/namespace 结构化字段 | 正文中的 Host-delivered context 说明 |
| 正文 | 原始字符串或结构化内容 | 文本；非字符串输出使用 JSON 文本化 |
| 是否虚构一次调用 | 否 | 否 |
| 是否等价保留消息身份 | 保留独立工具输出身份 | 否，属于降级 |

客户端源码能说明历史与出站请求怎样组织，不能说明官方服务端如何将此结构最终编码进模型。官方服务端推理输入编码不在这些客户端源码中，不能声称已经复刻。

## 后续设计约束

1. 内部按原生语义区分：用户消息、配对工具结果、独立外部工具输出、agent 消息；不要把“缺少 call_id”本身视为损坏。
2. 根据端点能力决定是否保留原生输出，而不是因为模型是第三方就默认重写；能力应针对协议特征，不针对模型名称。
3. 不支持独立输出的端点无法接受完全相同的结构。必须选择明确的降级策略或报不支持，不能以来源提示词冒充等价实现，也不凭空补调用关系。
4. 后续回归应直接通过桌面捆绑 app-server 的 turn/start.toolOutput，验证最终 wire JSON；全局 CLI 的普通文本 turn 不能替代它。

本轮只进行审计并记录证据，没有改动或重载生产路由逻辑。

## 来源

- [官方 app-server 文档](https://learn.chatgpt.com/docs/app-server)：turn/start 的 toolOutput、thread/inject_items，以及客户端 RPC 与模型请求的区别。
- [对应版本 turn_processor.rs](https://github.com/openai/codex/blob/720fec862a608ae1e5878d1eecb04fb93192e93c/codex-rs/app-server/src/request_processors/turn_processor.rs#L544)：参数校验与 call_id=None 的显式构造。
- [对应版本 turn_input.rs](https://github.com/openai/codex/blob/720fec862a608ae1e5878d1eecb04fb93192e93c/codex-rs/core/src/session/turn_input.rs#L344)：独立输出作为 turn 输入。
- [历史规范化](https://github.com/openai/codex/blob/720fec862a608ae1e5878d1eecb04fb93192e93c/codex-rs/core/src/context_manager/history.rs#L962)及[孤立结果检查](https://github.com/openai/codex/blob/720fec862a608ae1e5878d1eecb04fb93192e93c/codex-rs/core/src/context_manager/normalize.rs#L171)。
- [对应版本请求构造](https://github.com/openai/codex/blob/720fec862a608ae1e5878d1eecb04fb93192e93c/codex-rs/core/src/client.rs#L980)。
- [对应版本 HTTP 发送](https://github.com/openai/codex/blob/720fec862a608ae1e5878d1eecb04fb93192e93c/codex-rs/codex-api/src/endpoint/responses.rs#L73)。
- [独立输出序列化往返测试](https://github.com/openai/codex/blob/720fec862a608ae1e5878d1eecb04fb93192e93c/codex-rs/protocol/src/models.rs#L3433)。
