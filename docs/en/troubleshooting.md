# Troubleshooting

**English** · [简体中文](../zh-CN/troubleshooting.md)

[Project home](../../README.md) · [Documentation](README.md)

| Problem | What to do |
| --- | --- |
| A model is missing | Publish the client model catalog in the management page, fully quit and reopen Codex, and check that the target Codex user directory is correct. |
| No models can connect | Check that the gateway is running. Official models also depend on it while routing is enabled. |
| A request returns 401 | Update the key in the active YAML, management-page configuration, or CC Switch source. There is no automatic fallback to other credential sources. |
| Installation fails | Check Python version and network access, then retry. On macOS, use `CODEX_MODEL_BRIDGE_PYTHON` to select an interpreter. |
| macOS blocks the double-click launcher | Review the source, then run `sh scripts/codex-model-bridge.sh install` in a terminal. |
| Rollback detects newer configuration changes | Enter `yes` to confirm restoring the initialization backup. The current configuration is first saved as `pre-rollback-*.toml` in the data directory. Pressing Enter or reaching noninteractive EOF cancels. Backup integrity failures still block restoration. |
| You want to uninstall | Run `./scripts/codex-model-bridge.sh uninstall`. It stops the service, asks whether to restore the Codex configuration, and removes the local provider table. Runtime files and credentials remain in the data directory. |
| You want to migrate or reinstall | Run `uninstall` in the original location, then install dependencies and initialize with the selected data directory. |

Selecting a new directory does not import old configuration. Do not reuse another machine's state, backups, or virtual environment: they contain machine-specific paths and service state. See [data directory and migration](configuration.md#data-directory).
