# Bailian / Zhipu Responses 实测（2026-10-29，北京时间）

结论：当前配置的两个厂商不能作为完整的原生 Codex Responses 通道直接使用。
qwen-plus 支持简单多轮文本，但工具结果回传和当前 Codex reasoning 请求存在阻断；
qwen-coder-plus-1106 最小文本请求失败；三个 GLM 模型的当前 Responses 端点返回 404。

## 范围与方法

- 读取当前 CC Switch 配置，调用工作区 `gateway.server.route` 生成原生请求，直接访问其选定上游。
- 未改变 CC Switch、生产 settings、运行进程或业务代码。凭据只在内存中使用，不写入测试结果。
- 原始 Responses 探针 18 次；另外通过 Codex 实际启动了 3 个指定外部模型的子 agent。
- Chat 对照直接使用同一厂商、同一凭据、同一模型，端点最后一段换为 `/chat/completions`。
  这些对照验证上游 Chat 能力，不等同于完整验证本地 ChatAdapter 与 Codex 的集成。
- 以 `response.completed` 和实际输出判断成功；HTTP 200 本身不算成功。

## 原生 Responses 结果

| 模型 | 普通文本与多轮 | 工具闭环 | 实际子 agent |
| --- | --- | --- | --- |
| Bailian qwen-plus | 两轮成功，均返回 PROBE-729 | 普通 function、namespace function、custom 均能发起；三种结果回传均失败 | 启动后上游 response.failed，宿主显示 UPSTREAM_STREAM_ERROR |
| Bailian qwen-coder-plus-1106 | 最小单轮失败 | 未进入 | 启动后 UPSTREAM_STREAM_ERROR |
| Zhipu glm-5.3 | 最小请求 HTTP 404 | 未进入 | 启动后 UPSTREAM_HTTP_404 |
| Zhipu glm-5.3-flash | 最小请求 HTTP 404 | 未进入 | 未单独启动 |
| Zhipu glm-5.3-flashx | 最小请求 HTTP 404 | 未进入 | 未单独启动 |

### Bailian

配置中的地址：`https://dashscope.aliyuncs.com/compatible-mode/v1/responses`。

1. qwen-plus 文本历史按标准 output item 回放，两轮均正确复述 nonce。
2. 普通函数返回 `multiply(a=137,b=29)`。本地计算 3973，再以匹配的 call_id、
   原始 function_call 和 `function_call_output` 回放，得到 `response.failed`：
   `tool must be one of user,assistant,system,function`，上游内部校验拒绝 `role='tool'`。
3. namespace 调用正确返回 `namespace=math`、`name=multiply`；custom 调用正确返回
   `custom_tool_call` 和 `input=PROBE-729`。两者回传结果时出现同一错误。
4. `include=['reasoning.encrypted_content']` 单独存在时请求可完成，但没有验证加密 reasoning 回放。
   `reasoning={'effort':'low'}` 单独存在即失败：
   `The result_format parameter must be "message" when enable_thinking is true`。
5. 携带 `tool_search` 定义的简单文本请求可完成；没有实际验证工具搜索行为，不将其记为功能通过。
6. qwen-coder-plus-1106 最小文本请求 HTTP 200 后仅返回 error SSE：
   `1 validation error for Event / object / Field required`。

### Zhipu

配置中的地址：`https://open.bigmodel.cn/api/coding/paas/v4/responses`。

三个配置模型均返回空 body 的 HTTP 404。GLM 真实子 agent 的网关元数据也显示：
上游 host 为 `open.bigmodel.cn`，阶段 `connect_upstream`，HTTP 404。
这建立了当前配置端点不可用的证据；不能据此断言智谱所有其他产品端点都不支持 Responses。

## 实际子 agent 交互

通过宿主 `spawn_agent` 分别指定 qwen-coder-plus-1106、glm-5.3、qwen-plus，任务为
两轮只读工具调用并复述 nonce。三个任务均创建成功，但模型首轮失败，无工具执行结果。
因此，已实测的启动路径不可用；不能声称已验证子 agent 内部工具多轮或嵌套 delegation。

当前网关日志中的三个请求都包含 custom、function、namespace、tool_search，协议是
openai_responses。qwen-plus 的实际首轮记录到 response.failed；其最小探针已经单独复现
reasoning 字段失败，但没有保存子 agent 原始请求，因此不将实际失败精确归因于单一字段。

## Chat 对照

五个模型都通过以下四步：单轮返回 CONTROL-863、第二轮记忆复述、生成 multiply 调用、
接收本地工具结果后回答 3973。这说明当前模型和凭据在 Chat 端点可用。

首次测试脚本对 qwen-coder 的工具增量中 null 字段处理不当，产生一个本地 TypeError。
脚本改为忽略 null 增量后，该模型完整四步重测成功。这是测试脚本问题，不计为上游失败。
保留原始记录及成功重测，避免隐藏诊断过程。

## 建议

当前这些模型使用 Chat Completions 兼容转换路径更有依据。不要因为原生 Responses
路由单元测试通过或上游返回 HTTP 200，就认定原生 Codex tools/sub-agent 可用。
本次没有切换生产配置；Chat 兼容路径仍需独立执行真实 Codex 子 agent 回归后才能确认完整可用。

## 可复现与证据

在仓库根目录执行（会产生真实上游调用和相应费用）：

```powershell
.\.venv\Scripts\python.exe test-results\live_responses_probe.py
.\.venv\Scripts\python.exe test-results\live_responses_diagnostics.py
```

- `live-responses-2026-10-29.json`：12 个 Responses 原始探针。
- `live-responses-diagnostics-2026-10-29.json`：4 个 Responses 字段/工具探针和 19 个 Chat 对照记录。
- `live-responses-extra-2026-10-29.json`：2 个工具结果回传探针及 qwen-coder 四步成功重测。
- 后续已把额外工具回传测试合入 diagnostics 脚本；重跑时该脚本会包含 6 个 Responses 探针，
  且修正后的 Chat 对照应为 20 步。本次保存的是实际原始运行记录。

标准工具调用闭环参考：
https://developers.openai.com/api/docs/guides/function-calling
