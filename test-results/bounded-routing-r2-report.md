# 混合路由 R2 实测报告

日期：2026-10-29，北京时间。平台：本机 macOS。

## 范围与配置

本轮用户批准第三方目标 500,000 tokens，允许略超，最高 660,000。官方仅使用 gpt-6.1-sol/low 和 gpt-5.6-sol/low；第三方排除 OpenRouter。当前配置实际列出五个第三方模型，均为 openai_responses + portable：DeepSeek V4 Flash、V4 Pro、Qwen3.8 Max、Qwen3.8 2.4T A95B、GLM 5.3 Flash。没有改动模型配置、服务、产品源代码，也没有自动切换协议。

先执行五个最小 API 请求，经过当前 route() 与 adapter，直接连接配置中的上游，每个 max_output_tokens=128、low、无工具、无自动重试。该层不代表真实桌面会话。

随后通过 Codex 原生 create_thread / send_message_to_thread 建立四个独立、无继承历史的聊天，以及实际 connected_agent_bridge 子 agent。四个聊天由桌面后端处理，未操作独立窗口或模型选择器 UI。预检首次受沙箱 DNS 限制，未收到上游响应；获准联网执行后完成五个预检，没有对收到上游错误的请求重试。

## 结果

| 场景 | 结果 | 实际证据 / 边界 |
| --- | --- | --- |
| 五个模型最小 API 预检 | 5/5 通过 | 均 completed，正确返回 R2_READY_731；共 1,870 tokens |
| DeepSeek Flash 新聊天 | 通过 | R2_DS_417 |
| 千问 Max 新聊天 | 通过 | R2_QW_539 |
| GLM Flash 新聊天 | 通过 | R2_GL_284 |
| 全新官方先回复 → DeepSeek Flash | 通过 | R2_OF_862 保留；不是从第三方开始的历史 |
| DeepSeek Flash → 6.1-sol → Flash | 通过 | 两次切换均保留 R2_DS_417 |
| 千问 Max → 6.1-sol → 千问 Max | 通过 | 两次切换均保留 R2_QW_539 |
| GLM Flash → 5.6-sol | 通过 | R2_GL_284 保留 |
| 官方主 agent → DeepSeek Flash 子 agent | 通过 | 实际创建子 agent、任务可见、收到结果 |
| 官方主 agent → DeepSeek Pro、千问 A95B 两位直接子 agent | 通过（顺序执行） | 分别返回 R2_PRO_493、R2_A95B_816；按时间戳没有重叠，不能声称两个直接第三方子 agent 并发已验收 |
| DeepSeek Flash 子 agent → 6.1-sol、GLM Flash 孙 agent | 调用与结果交付通过；首次聚合不完整 | 两位实际任务执行时间重叠；返回 R2_SOL_631、R2_GLM_752 |
| 同一 DeepSeek 父 agent 接收较迟完成通知后再汇总 | 补充确认通过 | 追加一次无工具指令后，父 agent 依据真实完成通知汇总两项结果；不是首次自动汇总通过 |
| 官方 5.6 执行只读命令 | 通过 | 实际运行 python3 -c 'print(137*29)'，返回 R2_GL_284\|3973 |
| 上述工具历史 → GLM Flash | **失败** | 本地 route_request 阶段 KeyError / GATEWAY_STREAM_ADAPTATION_FAILED；未进入上游连接阶段 |
| 失败后 → 官方 6.1-sol | 通过 | R2_GL_284\|3973，证明该会话可恢复且历史仍在 |

## 问题 R2-1：工具历史切入 portable 第三方失败

最小真实路径：GLM Flash 新聊天 → 5.6-sol → 官方执行一次只读命令 → GLM Flash 读取现有随机码和工具结果。

聊天：01a18818-a07a-7681-ae9f-d9298ff527a3。
失败 turn：01a1881b-148c-7512-b54e-356ad6f76ee5。
请求 ID：6437e5f5e16044d5b117c36ffaf920d4。
北京时间：22:40:38。

网关记录：phase=route_request，status=incompatible_request_or_stream，error_type=KeyError，error_code=GATEWAY_STREAM_ADAPTATION_FAILED；位置 gateway/server.py:518、gateway/server.py:261、adapters/responses.py:247。该日志明确定位到上游连接前的请求转换，不能按厂商流错误解释。

离线读取本地 rollout，仅在内存中重放工具历史，得到 KeyError('exec')。历史工具调用是 custom_tool_call(name='exec', namespace 缺失)，工具注册表却位于 functions 命名空间，因此注册别名为 functions__exec。ResponsesAdapter.request 直接索引 self.bindings[alias] 时失败。

独立合成结构（functions 命名空间下的 custom exec 定义 + 无 namespace 的历史 exec 调用）也在本地复现同一 KeyError。没有发送新的第三方请求。原始网络请求没有另行抓包，因此本地重放不是原请求逐字节取证；但实际网关堆栈与离线重现相符。

建议后续修复：明确历史调用缺失 namespace 时的绑定规则，只在候选唯一时恢复命名空间；同名歧义明确报错。补充 custom/function 历史、工具输出关联、多命名空间冲突和官方历史保留的离线回归。不要以绕过错误、删除工具历史或静默修改全部 native 路由解决。本轮仅测试和诊断，未实施修复。

影响边界：问题位于共享 portable Responses 转换器，可能影响其他经过该转换器的模型；本轮只对 GLM 实际失败取证，未对其他供应商重复付费验证，也未实测 Windows。

## 问题 R2-2：短等待导致父 agent 过早判断失败

DeepSeek 父 agent 被测试指令限制为最多一次 10 秒等待。官方孙 agent 在约 5.7 秒完成，GLM 孙 agent 在约 19.7 秒完成，执行时间有重叠。父 agent 在 GLM 完成前结束，报告“失败，仍 running”。这不能算作 GLM 请求失败。

收到较迟完成通知后，额外发了一次禁止调用工具的核对指令；父 agent 确认实际收到两个通知并正确汇总。首次未自动收齐和补充提示后成功应分别记录。

后续方案应使用宿主侧 30–60 秒有界等待，区分 pending、timeout、failed 和 completed；不要让第三方父 agent 为轮询反复重发全部上下文。此次延迟样本不建立稳定的供应商延迟结论。

## 消耗核对

- 五个最小 API 请求：1,870 reported tokens。
- 真实聊天与子 agent：480,941 reported tokens；按明确的九个 rollout ID、逐次模型选择和 usage 记录统计。
- 合计第三方：**482,811 reported tokens（约 48.28 万）**，含缓存输入和推理输出。
- 真实网关成功第三方请求 14 个；其 usage 合计与 rollout 的 480,941 完全一致。另有一个本地转换失败请求，在 route_request 阶段停止，无上游请求用量。
- 先前进度更新将预检加总误写为 1,886，导致合计多记 16；最终文件以两份独立来源复核后的 482,811 为准。
- 官方主对话、官方子 agent、5.6 和自动审批用量不计入用户此次“第三方 tokens”预算；这是测试归属的已报告 token 数，不是人民币账单或整个账户的总用量。
- 第三方首次真实新聊天约 2.7–2.9 万 tokens；切换至带官方历史的第三方轮次约 5.2–5.4 万。嵌套 DeepSeek 父 agent（含补充汇总）153,728，GLM 孙 agent 28,078。短回复无法消除宿主上下文成本。
- 发现工具历史失败后停止全部新增第三方调用，仅做本地诊断和官方恢复。所有测试子 agent 已完成，无留在运行中的测试节点。

## 未覆盖

独立窗口和选择器的 UI 操作；Windows 实机；官方 → 另一第三方 → 官方 → 不同供应商的完整连续链；5.6 其他型号；DeepSeek Pro 和 A95B 的双向历史切换；直接两个第三方子 agent 的实际并发；主动取消、重连、长上下文、供应商故障注入和压力测试。

本轮五个核心方向均有实际样本，但不能据此宣称所有组合通过。值得优先修复的是已离线复现的工具历史绑定问题，而不是继续扩大付费测试矩阵。

## 文件

- bounded-routing-r2.py：仅显式运行才会产生五个付费预检请求。
- bounded-routing-r2-preflight.json：预检状态、返回模型与 usage，无凭据或上游地址。
- bounded-routing-r2-ledger.json：明确会话 ID、模型、短任务结果、调用名与逐次 usage；不导出原始提示和完整工具参数。
- bounded-routing-r2-gateway.json：时间范围内网关安全字段；包含官方协调请求，不用整个文件的总量冒充第三方用量。
- bounded-routing-r2-offline-diagnosis.json：离线复现状态及工具名，不含凭据或原始会话内容。
