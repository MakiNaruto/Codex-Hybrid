# Troubleshooting

When disabling routing, migration removes external storage IDs from the verified
plain-text assistant message shape and backs up the original history. Tools,
reasoning and compressed history are not covered yet. See the
[compatibility decision record (Chinese)](../decisions/001-history-compatibility.md).

**English** · [简体中文](../zh-CN/troubleshooting.md)

[Project home](../../README.md) · [Documentation](README.md)

| Problem | What to do |
| --- | --- |
| A model is missing | Publish the client model catalog in the management page, fully quit and reopen Codex, and check that the target Codex user directory is correct. |
| No models can connect | Check that the gateway is running. Official models also depend on it while routing is enabled. |
| A request returns 401 | Update the key in the active YAML, management-page configuration, or CC Switch source. There is no automatic fallback to other credential sources. |
| Switching to an official model reports `persisted-item lookup` / `rustponsesapi` | External history item IDs do not exist in official storage. Update the code, restart the service, keep Codex routing enabled, select an official model in the existing chat, and retry. The gateway replays full history content without item storage IDs while preserving tool `call_id` and file IDs. Official requests bypass this compatibility layer when routing is disabled; start a new official-model chat if routing must stay disabled. References containing only an ID cannot be reconstructed by this layer. |
| A third-party model calls an unavailable tool | The Responses API discards that generation and retries the same model with corrective feedback, up to two times. If it still fails, the gateway reports `GATEWAY_UNREGISTERED_TOOL`. Codex's official executor reports command failures to the model; network failures are not automatically replayed. |
| Installation fails | Check Python version and network access, then retry. On macOS, use `CODEX_HYBRID_PYTHON` to select an interpreter. |
| macOS reports a script permission error | Run `sh scripts/codex-hybrid.sh install` from the project root. |
| Rollback detects newer configuration changes | Enter `yes` to confirm restoring the initialization backup. The current configuration is first saved as `pre-rollback-*.toml` in the data directory. Pressing Enter or reaching noninteractive EOF cancels. Backup integrity failures still block restoration. |
| You want to uninstall | Run `./scripts/codex-hybrid.sh uninstall`. It stops the service, asks whether to restore the Codex configuration, and removes the local provider table. Runtime files and credentials remain in the data directory. |
| You want to migrate or reinstall | Run `uninstall` in the original location, then install dependencies and initialize with the selected data directory. |

Third-party Responses Portable generations are buffered and validated until a terminal event
arrives before forwarding, so the first output is delayed. This prevents tool calls from
discarded generations from reaching the executor. Official models, native Responses (including explicit feature adaptations), and Chat Completions
continue streaming immediately. Two retries mean at most three upstream requests, which
can increase latency and usage. An early upstream disconnect discards the buffer and
reports `UPSTREAM_STREAM_ENDED_EARLY` without automatic replay.

Selecting a new directory does not import old configuration. Do not reuse another machine's state, backups, or virtual environment: they contain machine-specific paths and service state. See [data directory and migration](configuration.md#data-directory).
