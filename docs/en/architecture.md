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

On `/models`, the gateway reuses Codex's subscription credentials and query parameters to refresh the official catalog, without reading login files separately. Successful refreshes publish the merged directory and routing allowlist together. Failed refreshes return the previous directory only if it matches the current allowlist, preserving configuration and allowing calls to continue. Without a valid cache, the endpoint returns `OFFICIAL_MODEL_LIST_UNAVAILABLE`. This requires no Codex UI changes and never substitutes the selected model.

Configuration, credentials, tokens, and backups live in the selected data directory. Do not commit files containing credentials. Generated files use POSIX `0600` permissions; Windows relies on directory ACLs.

### Protocol compatibility boundaries

Third-party Responses defaults to portable compatibility. Explicit `responses_compatibility: native` selects native transport: request fields, message types, tool namespaces, standalone tool outputs, reasoning and encrypted state, and streamed argument deltas are preserved. Routing replaces the address, credentials and model ID, applies explicit parameters/output budgets, and enforces no storage. It does not inject routing instructions, flatten tools, retry generations or fall back to Chat.

Chat Completions retains the portable conversion. Responses uses that bridge by default or with explicit `responses_compatibility: portable`: readable reasoning becomes historical assistant text, opaque reasoning is omitted, system/developer messages are consolidated, and tools are flattened. This changes semantics and is not equivalent to native transport.

History migration is separate. Native Responses supports `history_migration: true` to remove replayable top-level item IDs, preserving call IDs, nested resource IDs and bare references. It cannot decrypt reasoning or fetch missing history. Portable conversion already includes this ID handling. The official route keeps its existing migration behavior.

Portable instruction consolidation applies to messages, not developer-role tool metadata. Native transport preserves named standalone outputs without a `call_id`; only the compatibility bridge converts them to user context with source attribution. Real tool results retain their call identities.

When replayed tool history omits a namespace and has no exact registered alias, portable conversion resolves the short name only if exactly one registered tool of the same call kind matches. Explicit namespaces are never redirected. Unknown, ambiguous or mismatched tool kinds fail before forwarding; call IDs, arguments and results are preserved. This rule is shared by portable Responses and Chat Completions and does not change native transport or platform-specific behavior.

Repeated definitions may update a tool's description; the last encountered description is retained when the execution schema is identical. Conflicting parameter schemas or bindings are still rejected.

Both protocols share SSE framing, including multiline data and types declared only by `event:`. Explicit upstream errors become sanitized terminal failures; protocol mismatches fail explicitly. EOF and `[DONE]` alone never imply success. There is no automatic protocol switching. Native Responses does not retry generations; portable Responses retains its existing unknown-tool retry mechanism. Portable coordination guidance uses the request-scoped tool registry; ambiguous short tool names are not guessed.

Hybrid stores membership and per-model compatibility overrides in its own settings.json, scoped by source; CC Switch remains read-only. Both directory publication and live routing enforce membership. Upgrade preserves previously published models; newly discovered models require an Add action. Hybrid model overrides take precedence over YAML model options and provider defaults. Explicit native is preserved; unspecified Responses compatibility defaults to portable.

### Code responsibilities and reuse

| Module | Responsibility |
| --- | --- |
| `gateway/server.py` | HTTP lifecycle, authentication and route selection; `external_route` assembles external requests without executing tools |
| `model_catalog/` | Configuration sources, model catalogs, credentials and model preferences |
| `adapters/native_responses.py` | Native Responses transport with explicitly configured history ID migration |
| `adapters/responses.py` | Portable tool registration, history mapping, conflict checks and event conversion, shared by Chat |
| `adapters/chat.py` | Chat messages and stream conversion on top of the shared Portable rules |
| `adapters/coordination.py` | Native collaboration namespace mapping and request-scoped spawn naming, independent of Portable conversion |
| `adapters/request_compat.py` | History replay, routing context and sanitized errors |
| `management/` | Configuration publication, management HTTP, routing operations and forwarding process lifecycle |
| `desktop/` | Client configuration, session migration and platform-specific desktop control |

Portable requests register all current and discovered tools before mapping history, then validate duplicate execution schemas and generate guidance for the registered coordination aliases. Preserve this order: historical calls can depend on tool definitions that appear later in the request.
