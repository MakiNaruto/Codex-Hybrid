# R2 工具历史绑定修复与定向回归

日期：2026-10-29，北京时间。适用修改：共享 portable Responses / Chat Completions 转换器。实际运行验收：本机 macOS；Windows 未实机验收。

## 修复

1. 历史 function/custom 调用缺少 namespace、且无精确注册别名时，只在同名同调用类型的注册工具唯一时恢复别名。显式 namespace 不回退；未知、歧义、调用类型不符明确报 UnregisteredToolError。保留调用 ID、参数、结果，不执行或伪造工具。
2. 原聊天在第一项修复后触发第二个本地错误。离线核对确认，后续官方模型切换使 functions__exec 的顶层 description 更新，其他执行字段相同。现允许仅顶层说明不同的重复声明，保留最后遇到的说明；结构和参数冲突仍拒绝。

修改仅在 src/adapters/responses.py，另补 tests/test_protocol_compat.py 回归及双语 architecture 文档。官方/native 路径、代理、平台入口、模型配置均未修改。没有按模型或供应商添加特例。

## 测试驱动与审查

- 先补四项历史绑定测试，原实现失败：缺 namespace 复现 KeyError、显式错误 namespace 未获清晰错误、错误调用类型未被拒绝。实现后通过。
- 再补两项重复声明测试，先复现 description 更新失败，再实现只允许说明差异的去重。
- 协议专项共 24 项通过；覆盖 Responses / Chat、function / custom、call_id/结果/参数、原请求不可变、native 不改写、同名歧义、显式 namespace、未知工具、类型不符、说明更新与结构冲突。
- 两项内存变异检查：把唯一候选改为任意非空候选，歧义测试失败；移除 schema 冲突检查，两个协议的结构冲突测试均失败。实际产品源文件未被变异修改。
- 原聊天完整 rollout 中的工具声明、调用与结果已离线转换通过；该重放不等同于原网络请求逐字节抓包。
- 编译与 git diff --check 通过。
- gpt-5.6-sol 只读审查未发现高置信度正确性或安全阻塞项；审查不构成独立运行验收。

## 全套测试的真实状态

最终全套 340 项：319 通过，19 错误，2 项既有平台跳过。没有删除、禁用或新增跳过测试。

用 git HEAD 中修改前的适配器在内存中运行基线，旧测试 334 项也有相同的 19 个错误，错误测试 ID 集合完全相同。主要为旧测试配置缺 source，以及 macOS/Python 环境中模拟 Windows TLS 的 enum_certificates 不存在。它们不属于本次工具历史修改，未扩展修复。

最初受限沙箱测试另有本机临时端口权限错误；上面的最终结果来自获准本地端口访问后的完整运行。临时基线脚本第一次缺少多进程主入口保护，导致测试子进程重入；已停止该脚本进程树并修正，最终基线为带入口保护后正常完成的那次，不能使用最初中止结果作基线。

全套没有全绿，不能把“没有新增同类错误”表述为整个仓库测试通过。

## 实际回归

使用仓库现有 restart 入口，在零活跃请求时两次加载修复。均核对 Codex config.toml 和网关 settings.json 字节不变，没有重启桌面。第一次加载名称绑定修复；第二次加载最终说明去重修复。

原聊天：01a18818-a07a-7681-ae9f-d9298ff527a3。

| 用例 | 结果 | 证据 |
| --- | --- | --- |
| 第一次名称修复后切回 GLM | 本地失败 | ValueError / Conflicting tool definitions；route_request；请求 f0c83f4f0f2f4dcba7c7bc355f94340d；未发到上游 |
| 最终修复后同一聊天切回 GLM | 通过 | turn 01a1882d-1248-70e3-a44a-cf05197cff83；R2_GL_284\|3973；请求 9a04a675bef1482f8ab12e03c410ad43，返回 glm-5.3-flash，completed |
| DeepSeek Flash 合成工具历史 | 通过 | 缺 namespace + 两版说明，R2_FIX_918\|3973；completed；741 tokens |
| 千问 Max 相同合成历史 | 路由/内容通过，严格格式不符 | completed，返回 R2_FIX_918 空格\|空格 3973；随机码和结果均对，原 strict passed=false 保留；776 tokens；未重试 |

合成历史请求每个 max_output_tokens=128、low，使用 route/adapter 直接连接上游，无工具实际执行，无生成重试。它们验证共享转换与厂商接受该结构，不冒充完整桌面会话或 Chat Completions 实际 API 验收。

## 用量

- 前轮第三方：482,811 reported tokens。
- 原 GLM 聊天成功回归：56,886。
- DeepSeek/千问两个短回归：1,517。
- 本轮新增：58,403。
- **累计：541,214（约 54.12 万），低于最高 660,000；停止新增付费请求。**

包含第三方缓存输入和推理输出。官方协调与官方审查不计入第三方预算。两个本地转换失败发生于连接上游之前，不计作未知的第三方 API 请求。已报告 token 数不等于人民币账单。

## 证据

- bounded-routing-r2-fix-baseline.json：修改前基线错误测试 ID。
- bounded-routing-r2-fix-validation.json：最终专项、全套及基线对照。
- bounded-routing-r2-fix-offline.json：原聊天工具历史离线重放。
- bounded-routing-r2-fix-reload-first.json / bounded-routing-r2-fix-reload.json：两次加载前后零活跃请求和配置字节检查。
- bounded-routing-r2-fix-gateway.json：实际模型、请求 ID、失败位置及成功 usage。
- bounded-routing-r2-fix-probes.py：显式 --live 才会发起两个付费请求。
- bounded-routing-r2-fix-probes.json：两个小请求原始严格匹配与语义匹配分开保留。
- bounded-routing-r2-fix-ledger.json：累计用量。

本轮已修复并验收原工具历史失败。原报告中的短等待问题属于测试父 agent 的等待/判定方式；没有因此修改产品的路由或超时默认值。未开展新的嵌套矩阵、Windows 实机或窗口 UI 验收。

本地提交：b0eba09（分支 codex/portable-tool-history-binding）。只提交四个修复/回归/双语架构文件，测试证据保留在工作区，未推送或合并。
