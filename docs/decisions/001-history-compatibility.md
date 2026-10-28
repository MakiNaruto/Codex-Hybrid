# 001：关闭路由时的历史兼容

日期：2026-10-28。状态：初始规则已实现，复杂历史待验证。

## 证据与决策

“回应问候”首轮通过 GLM Chat Completions 回复，ChatAdapter 生成 msg_ 加 32 位十六进制字符的消息 ID。关闭路由后，官方接口报 Supplied input item IDs require persisted-item lookup that is not supported by rustponsesapi。只删除该助手回复 payload.id 并重新加载会话后，用户确认官方可以回复。

此前迁移只改索引、逐字节保留历史；此决策增加一个明确例外，而非宣称所有历史均已兼容。OpenAI 字段合法不代表 ID 在官方持久化存储中有效。

## greeting-message-id-v1

仅在迁移到 openai 时，读取有本地索引的未压缩历史。仅对 response_item 中 type=message、role=assistant、ID 匹配 msg_[0-9a-f]{32}、非空且全部为 output_text 文本的内容移除 payload.id。保留正文、工具 call_id、嵌套资源 ID、其他记录和原换行。启用路由不转换。此 ID 形状来自本项目 ChatAdapter，但不是绝对的来源证明；未来若来源标记完善，应优先使用显式来源。

历史写入必须在 Codex 停止后完成，即使调用方允许在线索引迁移。使用现有迁移事务先备份再写入；失败回滚；中断沿用 recover 恢复。manifest.history_compatibility 记录规则、会话、数量和前后哈希，不记录正文。没有匹配项则保持原字节。重复执行不会重复转换。

## 边界及后续核对

压缩历史、无索引历史、工具调用、第三方 reasoning、压缩上下文及纯 ID 引用尚未转换；不删除或伪造其内容。迁移完成不等于官方续聊验证通过。网关内 inline_history 是另一层防护，关闭路由后不能依赖它。不要将本规则扩展为递归过滤 ID 或 API 白名单过滤整个原生历史文件。

后续问题先检查 manifest 中规则及哈希、历史类型、是否真正关闭路由和重载会话，再新增独立版本规则和回归测试。不得覆盖已有备份或悄悄扩大本规则。磁盘历史格式与发送 API 的输入格式应分别处理。
