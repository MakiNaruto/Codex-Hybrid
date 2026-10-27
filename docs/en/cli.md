# Commands and advanced setup

**English** · [简体中文](../zh-CN/cli.md)

[Project home](../../README.md) · [Documentation](README.md)

## Installation details

Clone the repository with Git into a directory you plan to keep. Run the following commands from the project root.

| System | Double-click launcher | Terminal command |
| --- | --- | --- |
| macOS | `scripts/start-macos.command` | `./scripts/codex-hybrid.sh install` |
| Windows (PowerShell) | `scripts/start-windows.cmd` | `.\scripts\codex-hybrid.cmd install` |

The launcher creates the project's `.venv`, installs dependencies, and opens a Chinese-language install wizard. On Windows, enable Python Launcher or Add Python to PATH when installing Python.

If you are not ready to enter model details, press `Ctrl+C` after dependency installation, then rerun `install` later. Initial setup still requires a valid model configuration before the service and management page can start.

Private data defaults to `~/.codex-hybrid/` on every OS, alongside `~/.codex/`, independently of source location. Precedence: `--data-dir` → `CODEX_HYBRID_DATA_DIR` → default directory. Custom directories are not remembered; supply the same flag or environment variable for subsequent commands. `cli-config.json` is no longer generated or loaded. Legacy installations require an explicit original data directory; no automatic migration occurs.

The wizard asks whether to start the local service. It does not enable routing during installation. To connect Codex, turn on **Client routing** in the management page; this updates the target Codex `config.toml`. **Fully quit and reopen Codex** afterward. The Codex user directory defaults to `~/.codex`; use `CODEX_HOME` or `--codex-home` during initialization to select the directory your client actually uses.

## Common commands

After install, use these commands to manage the service. On Windows, replace `./scripts/codex-hybrid.sh` with `.\scripts\codex-hybrid.cmd`.

```sh
./scripts/codex-hybrid.sh install         # Install dependencies and configure; reuse existing initialization
./scripts/codex-hybrid.sh start           # Start the service
./scripts/codex-hybrid.sh stop            # Stop the service
./scripts/codex-hybrid.sh manage-url      # Get the management page URL
./scripts/codex-hybrid.sh status          # Show service, source, and model keys
./scripts/codex-hybrid.sh refresh-models  # Update the client model catalog from the current source
./scripts/codex-hybrid.sh restart         # Restart after updating code
./scripts/codex-hybrid.sh activate        # Connect Codex to the local router
./scripts/codex-hybrid.sh rollback        # Restore the initialization backup
./scripts/codex-hybrid.sh uninstall       # Stop service and confirm Codex configuration rollback
```

The default management URL is [http://127.0.0.1:18892/manage/](http://127.0.0.1:18892/manage/); management defaults to the forwarding port plus one, or explicit `management_port`. Private-link authentication is off by default, even if a `management_token` already exists.

Run `./scripts/codex-hybrid.sh manage-url --management-auth on` to enable authentication and get a private token-bearing link. Both the page and management operations then require that link; the plain address shows an access-restricted message. Use `--management-auth off` to disable it.

Specifying `--management-auth` requires `on` or `off`, automatically restarts the service, and prints the corresponding link. New installations default to off, so the local page opens directly. Without the flag, the command only retrieves the current link. The setting is stored in the data directory's `settings.json` and survives ordinary restarts.

`activate` sets Codex's provider to `codex-hybrid`, pointing requests at the local service. Models are still selected in the native picker; the service routes by model key. Official requests also pass through the local service.

After install, `status` should report `service_running: true` and `config_state: activated`. Third-party models should appear after restarting Codex.

`uninstall` stops the service first, asks whether to restore the Codex configuration from its installation backup, and removes the `codex-hybrid` provider table. If later edits are detected, it asks for a second explicit confirmation before overwriting them. Runtime files and provider credentials remain in the data directory for a future reinstall.

## Instance configuration

```sh
./scripts/codex-hybrid.sh config
./scripts/codex-hybrid.sh config --data-dir /path/to/data
```

`config` inspects the selected instance; `--set` and `--reset` are removed. Port and authentication live in its `settings.json`; the Codex target uses the path recorded at initialization. Use `--port` and `--codex-home` at installation, and `manage-url --management-auth on|off` for existing authentication.

## Model configuration options

### 1. Enter details during install

Choose **1 = Manual API setup**. Enter the API base URL, exact model ID, display name, protocol, and API key. You can exit and rerun install later. After initialization, use `manage-url` to open the management page and add providers, models, or update keys.

The wizard generates `setup-models.yaml` and `provider.env`. See [wizard configuration](configuration.md#wizard-configuration) for fields.

### 2. Read CC Switch configuration

Choose **2 = Local CC Switch** and confirm the database path, defaulting to `~/.cc-switch/cc-switch.db`. Existing installations can switch to CC Switch in the management page.

Only third-party static API configuration from its OpenAI / Codex section is read. Continue maintaining models, URLs, and keys in CC Switch. See [CC Switch](configuration.md#cc-switch).

### 3. Edit YAML manually

Before the first initialization, copy `config/models.example.yaml` to `models.yaml` in your data directory and edit:

| Field | Value |
| --- | --- |
| `providers.<provider_id>.base_url` | API prefix; include `/v1` only as required by the provider, not `/chat/completions` |
| `protocol` | `openai_chat_completions` or `openai_responses` |
| `credentials` | Either `api_key`, or `api_key_env` with optional `env_file` |
| `models.<alias>.model_id` | Exact model ID supported by your provider account |
| `models.<alias>.display_name` | Name displayed in Codex's model picker |
| `enabled` | Set desired providers and models to `true`; placeholder entries in the example are disabled |
| `default_model` | A `provider_id/alias` model key, such as `deepseek/flash` |

If using the example's credential method, also copy `config/deepseek.example.env` to `deepseek.env` in the data directory and set `DEEPSEEK_API_KEY`. `env_file` resolves relative to the YAML file.

```sh
# prepare is for first initialization only; use the Windows launcher on Windows
./scripts/codex-hybrid.sh prepare --source yaml
./scripts/codex-hybrid.sh start
./scripts/codex-hybrid.sh activate
```

Fully quit and reopen Codex. For an existing installation, switch YAML with `refresh-models --source yaml --models-config /path/to/models.yaml`, then run `restart` and restart Codex. Do not repeat `prepare`.

Saving in the management page switches the active source to `managed-models.yaml`. Edit the active file afterward; `status` shows the source. See [manual YAML](configuration.md#manual-yaml) and [API keys](configuration.md#api-keys).

> [!NOTE]
> Initial setup does not automatically call paid APIs. **Test connection** sends a real request and consumes provider quota.

## Ask an agent to install

```text
Install Codex Hybrid on this machine using the repository README.
First check Python 3.11+, the actual Codex user directory and its config.toml/models_cache.json,
and the router data directory (flag, environment variable, or wizard; default config).
Check state.json there: reuse existing initialization instead of repeating prepare.
Use the same directory for subsequent commands and use the project launcher and .venv.
Configure the YAML or CC Switch source I specify. Ask if required source details are missing.
Do not read unrelated credentials or print API keys or management tokens into chat.
Before connecting, state which Codex config.toml will be modified and preserve backups and other settings.
Check service status afterward, remind me to fully quit and reopen Codex, then follow the README verification.
Real connection tests consume quota; run them only if I explicitly request testing.
Report actual results and unverified items; do not present expected output as observed output.
```
