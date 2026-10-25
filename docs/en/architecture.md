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
