# Architecture

**English** · [简体中文](../zh-CN/architecture.md)

[Project home](../../README.md) · [Documentation](README.md)

```text
Codex: config.toml in its user directory + models.json in the selected data directory
                                      ↓
                         Local gateway (127.0.0.1:18891)
                             ├─ Official models → OpenAI subscription endpoint
                             └─ Third-party models → Selected provider API
                                                          ↑
                                              YAML / read-only CC Switch source
```

Codex reads the gateway URL and model catalog path from its own `config.toml`. The gateway reads `settings.json` in the data directory, then loads the selected YAML or CC Switch source. Main agents and subagents share the native catalog and route by model key, without MCP.

Official requests also pass through the local gateway. OpenAI subscription credentials are sent only to a fixed official endpoint; third-party requests use the corresponding provider's key.

Configuration, credentials, tokens, and backups live in the selected data directory. Do not commit files containing credentials. Generated files use POSIX `0600` permissions; Windows relies on directory ACLs.

### Protocol compatibility boundaries

Third-party Responses and Chat Completions share history normalization. Conversation text and tool call/result identities survive; readable historical reasoning or summaries become ordinary historical text, while opaque reasoning is not transferred across endpoints. External system/developer messages are collected in order into Responses `instructions` or one initial Chat system message. The official route retains its native encrypted history.

Instruction consolidation applies to messages, not developer-role tool metadata. Desktop task notifications may use named tool-output envelopes without a `call_id`; these become ordinary context with source attribution, without inventing a tool call. Real tool results keep their original call identities.

Both protocols share SSE framing, including multiline data and types declared only by `event:`. Explicit upstream errors become sanitized terminal failures; protocol mismatches fail explicitly. EOF and `[DONE]` alone never imply success. The gateway does not invent completion events, switch protocols automatically, or replay failed requests. Native coordination guidance is generated from the actual request-scoped tool registry; ambiguous short tool names are not guessed.
