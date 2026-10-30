# 002：原生 Responses 的显式局部兼容试用

日期：2026-10-30。实现为共享网关代码；本次实际验证平台为 Windows。

## 决策

保持既有 portable 默认及严格 native 行为。新增按来源、按模型显式保存的 `responses_adaptations`，仅在 native 路由下启用。能力依据端点实测设置，不按模型名称自动推断，不在失败后自动降级或重放生成。

试用模型和当前配置：

| 模型 | 明确启用的转换 | 保留的主要原生特性 |
| --- | --- | --- |
| GLM-5.3-Flash | agent_messages、standalone_outputs、discovered_tools | namespace、function、custom、正文和工具输入增量 |
| DeepSeek V4.1 Flash（deepseek-flash） | custom_tools、agent_messages、discovered_tools | namespace、普通 function 增量、文本独立工具通知、commentary/final_answer |
| Qwen3.8 Max、Qwen3.8 2.4T A95B | custom_tools、agent_messages、standalone_outputs、discovered_tools | namespace、普通 function 增量、正文流；未观察到 phase 标记 |

不改变代理、进程识别、桌面生命周期或安装脚本。CC Switch 保持只读。模型偏好通过正式管理 API 发布；其他模型不变。

## 阶段结论：四项能力覆盖当前主要兼容问题

截至 2026-10-30，agent_messages、standalone_outputs、custom_tools、discovered_tools 这四个显式适配维度，已覆盖当前 GLM、DeepSeek 和两款 Qwen 端点实测中的主要兼容问题。真实子 agent 投递、普通工具执行、嵌套创建与结果交付已有成功样本。这里的“大部分”指本记录已观察到的问题范围，不是对所有第三方模型的覆盖率统计。

继续采用原生优先、最小兼容、实时输出；由使用者为常用模型配置必要项，Portable 保留为手动兜底。不因现有样本全局默认开启四项，不自动按厂商推断、不自动降级重放。转换的语义代价、当前模型配置和未验证范围见下文；新问题先定位请求转换、上游拒绝、返回事件转换或宿主执行，再决定是否新增能力。

## 实测依据

当前配置端点的原生 namespace 函数调用及结果回传，两个模型均完成。GLM 接受 custom 工具，但拒绝测试中的 agent_message 和无 call_id 的具名独立输出。DeepSeek 拒绝原生 custom 定义；虽接受 agent_message 并返回 completed，严格任务结果检查却未通过。将明文 agent 消息转为 user 后，两模型均正确返回测试标记。

DeepSeek 包装 custom 工具后的一次测试把 grammar 定义误当作原始输入。明确输入约束说明与实际输入的区别后，复测得到正确原始输入，并完成工具结果回传。这仍不保证供应商强制执行原始 grammar。

正式服务零活跃请求时通过 restart 入口加载实现，没有重启 Codex 桌面。经当前实际网关的 namespace/function 与 custom 工具闭环均完成，结果标记校验通过；最终 agent 消息转换配置的任务标记检查通过。以上工具结果由测试程序本地提供，不是桌面执行器实际执行，也没有实际创建子 agent。

新增加的本机 HTTP 回归在上游等待释放时读取正文，再允许上游完成，验证客户端能在完成前收到文字。正文和未转换工具事件直接转发；包装 custom 的 JSON 参数增量被抑制，完整输入校验后还原调用。局部兼容不使用 portable 的整轮缓存和未知工具生成重试。

## 验证边界与恢复

专项 Python 回归覆盖原生路由、局部转换、消息来源、事件还原、管理持久化、CC 同步、原有 portable 转换、代理和网关活动；管理页现有 Node 回归通过。没有开展全套测试、macOS 实机验证、桌面 UI 验收、实际子 agent 创建、跨供应商推理历史回放或完整工具发现验收。

试用应从新聊天开始。已有 portable 工具历史、缺 namespace 的历史调用、供应商加密状态与全部 Codex 扩展字段尚未完成实机验证。加密 agent 内容明确拒绝，不尝试解密。

如需恢复旧路径，在模型详情重新开启兼容模式（portable）。局部配置保留但不生效；通过管理 API 将 `responses_adaptations` 设为 `[]` 可清除局部转换。详细设置见双语 configuration 文档。

## 用户配置与校验

模型详情最初提供三项独立适配勾选，后续子 agent 验证新增第四项“展开已发现工具”，见本文后续修复记录。由使用者依据常用端点的表现配置，不内置供应商名称判断。关闭完整兼容模式后可编辑，Portable 下禁用勾选控件但保留选择。最初三项的保存、重新打开与模式切换已在隔离假凭据的管理页验证；当时没有改变实际两个试用模型的设置。这是管理页浏览器检查，不是 Codex 桌面真实任务验收。

新增 Pydantic v2 依赖与独立 response_schemas 模块。适配选项、agent 明文、独立通知、custom 工具定义/历史调用和包装参数使用严格结构校验；原生扩展字段不静默删除。只对可选配置补默认值，执行数据缺失时明确失败。后续新增能力应增加显式选项、对应结构/转换及回归，不以通用删字段方式修复所有端点。

本次 93 项 Python 专项与 8 项前端回归通过，另检查 JS 语法和 diff 空白。依赖已安装于本仓库虚拟环境；零活跃请求时通过正式入口重启 Hybrid 加载实现。未新增付费模型调用，也未执行 macOS 实机或桌面端 agent 验收。

## 定向上游能力复核

2026-10-30 后续按用户要求新增直接上游探针，均禁用全部局部转换，不修改运行配置。GLM 原生 namespace custom + Lark grammar 返回正确随机原始输入和 custom_tool_call；回传匹配 call_id 的 custom_tool_call_output 后正确复述随机标记，闭环通过。

DeepSeek 不带 call_id 的具名 function_call_output，当 output 为文本时正确执行随机标记任务。额外尝试直接将 JSON 对象作为 output：512 token 时 incomplete；提高到 2048 后两次 completed，但均未正确返回标记。最后一次明确回复没有看到通知或标记。这说明文本通知的成功不能外推到任意 output 形态；本探针不宣称直接对象是通用 Responses 标准格式，也未覆盖其他结构化表示形式。结果分别见本地 test-results/native-features-verification.json 与 structured-notice-verification.json。没有修改模型偏好或服务。

## Qwen3.8 定向验证

同日对当前启用的 qwen3.8-max、qwen3.8-2.4t-a95b 各执行原生与局部适配对照，共 22 次小规模上游请求。未启用的 qwen3.8-27b 未测试。没有修改模型设置或重启服务。

两模型原生 namespace function 调用及结果回传均通过随机标记检查；custom 调用的原始输入正确，但返回 item 缺失 namespace，严格身份检查失败，因此未继续原生 custom 回传。该场景还观察到 custom 与 function 参数增量混用，不能据终态调用存在就宣称原生流完整兼容。独立文本工具通知均返回 response.failed / InvalidParameter；agent_message 均 completed，但未按要求返回任务随机标记。正文未返回 commentary/final_answer 标记。

在内存配置中显式启用 custom_tools、agent_messages、standalone_outputs 后，两个模型各六项检查均通过：namespace function、function 结果、custom 调用身份与原始输入、custom 结果、独立文本通知、agent 任务标记。此验证使用当前局部适配器直连上游，不是 Codex 桌面执行器或真实子 agent 验收，也不代表旧聊天历史与全部工具发现已验证。两模型保存的 portable 配置保持不变。

本地探针为 test-results/verify_qwen_native.py；语义检查分别保存为 qwen-native-verification.json 与 qwen-adapted-verification.json，事件统计保存在对应 native-trial 时间戳 JSON 中。

## DeepSeek 真实嵌套委任对照

2026-10-30 在 Windows 继续检查 DeepSeek V4.1 Flash。原配置 custom_tools、agent_messages 下，两次全新父 agent 都收到任务，但最终正文输出 DSML 工具调用标记，没有发生真实工具执行或子 agent 创建。请求 70fcb39cb23049099a2c5cad21ea9775、25aa4e00f6974dc1a0e0debe85607107 均 completed / read_upstream，没有 GATEWAY_STREAM_ADAPTATION_FAILED；spawn_agent_in_request_tools=false、spawn_agent_in_history_tools=true、spawn_agent_advertised=true。网关 completed 不代表工具执行成功，必须核对真实工具事件与代理树。

通过正式管理 API 仅为 DeepSeek 增加 discovered_tools，保留 custom_tools、agent_messages，不开启 standalone_outputs，不改变 GLM 或 Qwen。全新 fork_turns=none 父 agent 实际创建 /deepseek_expanded_check_72109_run_f8df1bfc470647aa9dfcdcfed3305328_run_30af84acc8964b0caec16a765fc279c6/ds_leaf_72109，宿主代理树确认孙 agent completed，返回 DS_LEAF_OK_72109。worker 使用宿主实际暴露的 collaboration.spawn_agent；内部工具名与对外桥接工具名不必相同。继续要求该父 agent 执行只读 Get-Location，实际 exec_command 返回退出码 0 和仓库路径。

该对照支持 DeepSeek 也需要展开历史发现工具；未证明 DSML 正文输出的所有成因都由工具发现引起。保留三项作为当前试用配置，不解析正文 DSML、不自动重放或切换 portable。仅覆盖当前 Windows 宿主、端点和短任务，不代表长任务、并发、全部旧历史或 macOS 已通过。本轮没有修改共享实现，仅修改模型配置和本文记录。

## Qwen 真实工具与嵌套委任验证

2026-10-30 Windows：当前启用的 qwen3.8-max、qwen3.8-2.4t-a95b 原先均为 portable，适配列表为空。先做基线：Max 实际 Get-Location 与同模型嵌套委任均成功，孙 agent 返回 QW_MAX_OK_83041；A95B 实际 Get-Location 成功，本轮 portable 基线未测试其嵌套委任。禁用的 qwen3.8-27b 未测试、未改配置。

结合前述原生能力矩阵，通过正式管理 API 将两款启用模型显式设为 native，并启用 custom_tools、agent_messages、standalone_outputs、discovered_tools。原配置保存于本地 test-results/qwen-real-agent-profile-before.json。未改共享实现、GLM、DeepSeek 或代理行为。

分别使用全新 fork_turns=none 父 agent，两款均实际执行 Get-Location 并返回仓库路径，实际创建同模型孙 agent 并等待得到精确标记。Max 孙 agent 路径后缀为 /qw_max_native_leaf_79216，结果 QW_MAX_NATIVE_OK_79216；A95B 后缀为 /qw_a95b_native_leaf_42817，结果 QW_A95B_NATIVE_OK_42817。宿主代理树确认两者均存在且 completed，未依赖模型文字自述作为唯一依据。

样本请求：Max 的 77c3cae1380745449284864058dc5d54、6c12cd9c73d643c4a4eb652ffcddc9ec、ced3812e1d2241dbae35e4c4baa8cea1；A95B 的 35fe705d558545d19a3d5c3165780df2、b0479067d32e404096a457faf2aae28e、133059a665034342a31a01d5fac8a8a1 均 completed。未复现 GATEWAY_STREAM_ADAPTATION_FAILED 或 DeepSeek 本轮出现的正文 DSML 假调用。另观察到 A95B 请求 fb06117a6801447a9c033ced8af07fb2 为 write_client / client_disconnected / ConnectionAbortedError；整体任务仍完成，断连原因未单独定位，不等同于适配失败。

保留两款 native 加四项适配作为当前试用配置，portable 仍可手动恢复。本轮证明该组合在当前 Windows、端点和短任务可用；未做去除 discovered_tools 的对照，不能断言该项对 Qwen 必需。没有测量桌面实时显示时延，没有重跑完整测试套件，也不代表长任务、并发、旧历史或 macOS 验收通过。

## 三项全开的代价与排查原则

局部适配是无条件执行的显式转换，不是先尝试原生、失败才介入。没有对应输入时不触发该项；出现对应结构时，即便端点原本支持，也会转换。

DeepSeek 在当前两项基础上增加 standalone_outputs，会将原生独立通知降级为 user 消息，name/namespace 只保留为正文来源说明，失去结构化通知身份。它会把对象 output JSON 文本化，可能绕开原生对象通知不可见的问题，但该收益尚未专门验收。

GLM 在当前两项基础上增加 custom_tools，会把已通过验证的原生 custom 包装为 function。原 grammar 只作为约束文字，不再是原生工具格式；JSON 包装参数增量被抑制，完整输入验证后才还原。增加包装解析、历史工具绑定和模型误填包装内容的失败点；DeepSeek 曾实际误把 grammar 定义填入工具输入，不能假设包装无代价。

全勾仍然实时转发正文，不引入 portable 整轮缓存。优先只开启已证明必要的项，诊断时记录模型 key、端点、模式、适配列表、request_id、错误 phase、error_type、error_locations 及最后事件。区分本地 route_request 转换失败、上游请求拒绝、adapt_event 返回转换失败、宿主实际执行失败。API 探针通过不代表真实 agent 投递、工具发现、加密消息或跨模型历史通过。

## GLM 真实子 agent 投递失败与修复

用户报告的模型经日志核实为 glm-5.3-flash，而不是未启用的 glm-5.3。原请求 a8759e80320e48ef9ce44afe4c4c8619、0d61ea25c1bd42c589d916d56492d0aa 均在 route_request / MinimalResponsesAdapter.request 失败，没有进入上游连接。真实 fork_turns=none 子 agent 可复现 GATEWAY_STREAM_ADAPTATION_FAILED。

根因：实际宿主 agent_message 混合 input_text 与 encrypted_content。后者在本例包含测试任务可读明文，不是真正密文。原 Pydantic 结构只接受 input_text，而先前人工探针未覆盖该真实形态。仅记录字段类型和固定分类、不记录正文的诊断确认了这一点。

修复仅作用于明确启用 agent_messages 的路径：识别可读宿主文本 span 后转换为 input_text，保持顺序和正文；gAAAA 密文、UUID 历史占位和未知不透明 token 仍拒绝，不执行解密。基于文本形态的识别不是通用密文检测或来源认证，不得推广到任意加密字段。错误改为明确的 UNSUPPORTED_AGENT_MESSAGE_CONTENT，并在诊断导出中仅保留 allowlist 结构分类。

修复后，实际 GLM 子 agent 返回 GLM_DELIVERY_OK_83017；DeepSeek 对照子 agent 返回 DEEPSEEK_DELIVERY_OK_42719。两者均为真实宿主投递，无脚本替代，未调用执行工具。再次要求 GLM worker 创建孙 agent 时，它先仅输出计划而未调用工具；明确要求直接调用后回复 NO_SPAWN_TOOL，因此未实际创建孙 agent。该结果只建立投递修复通过，不宣称 GLM 父 agent 的嵌套委任通过，也不能单凭模型自述断言宿主工具配置缺失。后续应核对该请求是否实际注册 spawn_agent，以及嵌套深度限制。

后续核对已完成：请求 fc32cd104afb48e0910499251d53e31c 的 spawn_agent_in_request_tools=false、spawn_agent_in_history_tools=true。工具确实存在于发现历史，并非宿主未提供。新增独立选项 discovered_tools，将已发现定义合并到顶层 tools，保留 namespace 和搜索结果关联并拒绝冲突；不采用全工具扁平化。模型详情有对应勾选项。只为 GLM-5.3-Flash 试用增加该项，其当前配置为 agent_messages、standalone_outputs、discovered_tools，继续保留原生 custom。

同一旧 worker 在修改后仍重复先前无法调用的回答，不能据此判定修改有效。改用 fork_turns=none 的全新 GLM 父 agent 后，真实创建路径以 /glm_nested_ok_94271 结尾的孙 agent，原生等待后收到 GLM_NESTED_OK_94271；宿主代理树确认该孙 agent 存在且 completed。由此建立官方→GLM 任务投递、GLM→GLM 嵌套创建和结果交付的实机样本。只覆盖这次任务、当前 Windows 宿主与端点，不外推到所有工具、并发、长任务或 macOS。
