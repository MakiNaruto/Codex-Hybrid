# Configuration

**English** · [简体中文](../zh-CN/configuration.md)

[Project home](../../README.md) · [Documentation](README.md)

The project's `config/` directory holds configuration examples while private data defaults to `~/.codex-hybrid/`:

- [models.example.yaml](../../config/models.example.yaml): model configuration template.
- [deepseek.example.env](../../config/deepseek.example.env): placeholder-only environment file.

Examples use `<name>.example.<extension>`. Generated configuration, credentials, and runtime files are excluded from version control.

## Data directory

Private data defaults to `~/.codex-hybrid/` on every OS, alongside `~/.codex/`, independently of source location. Precedence: `--data-dir` → `CODEX_HYBRID_DATA_DIR` → default directory. Custom directories are not remembered; supply the same flag or environment variable for subsequent commands. `cli-config.json` is no longer generated or loaded. Legacy installations require an explicit original data directory; no automatic migration occurs.


The wizard prints commands using the selected directory. Relative paths resolve from the working directory; absolute paths are recommended. `--models-config` can select an external YAML file; otherwise the source defaults to `models.yaml` in the selected data directory. Management-generated YAML is saved in that same directory.

Selecting a new directory does not import files from the old one. Use the same directory for subsequent operations. Older initialized instances still need their original directory specified explicitly; roll back and stop before reinitializing.

`--codex-home` independently selects the Codex user directory. Its `config.toml` references the data directory's `models.json`. `CODEX_HYBRID_HOME`, with legacy `MODEL_ROUTER_HOME` / `CONNECTED_HOME` compatibility, is used only for legacy installation detection; it no longer selects the data root.

Before migration or reinstallation, run `uninstall` in the original location with the original data directory and confirm the configuration rollback. Local data and credentials remain in place. Install dependencies in the new location and run `install` with the selected directory. Do not reuse another machine's state, backups, or virtual environment; they contain machine-specific absolute paths and process state. Automatic migration is not provided.

## Wizard configuration

In `install`, choose **1 = Manual API setup** and provide:

| Field | Example / meaning |
| --- | --- |
| API base URL | `https://api.deepseek.com`; include `/v1` only if required, not `/chat/completions` |
| Model ID | `deepseek-v4-flash`; use the exact ID available to your account |
| Display name | `DeepSeek Flash`; shown in Codex's model picker |
| Protocol | Chat Completions or Responses, as supported by the provider |
| API key | Input is hidden and saved in local private files |

The wizard generates `setup-models.yaml` and `provider.env`, then asks whether to start the service. It does not enable routing during installation; turn on **Client routing** in the management page to update Codex configuration. The page opens when the service starts and the link is available. Initial setup does not automatically call paid APIs.

## CC Switch

Each Codex model entry binds to the CC Switch provider record ID and exact model ID. Its `slug` is the original `provider-record-id/model-id`, without hashing, escaping, or splitting on slashes. The binding separately stores `provider_record_id`, `app_type`, and `model_id`. Display names are labels only. The imported catalog has no default model: calls require an explicit selection, and a model list can be imported without a configured default. CC Switch's `config.model`, when present, is included as an exact model entry.

The gateway reads CC Switch at startup, then watches the database directory for database and `-wal` changes, merging consecutive events with a debounce of about 300 milliseconds. A safety check runs every 30 seconds; if notifications are unavailable, periodic checks continue. Synchronization continues with the management page closed. Page refreshes use the background cache without reading the database. The displayed sync time changes only when a snapshot is loaded or updated, not on unchanged checks. The directory, complete bindings, and source revision are stored together in `settings.json` under `cc_snapshot`; the client directory file is generated from that snapshot. Each sync replaces the entire CC directory, removes deleted entries and bindings, and preserves official models. Read or validation failures retain the previous snapshot and retry without publishing partial results. Deleting all supported provider records clears external models.

Renaming a provider or model, or changing the CC Switch default model, does not change an existing entry's identity. Addresses and credentials are reread for each request. Deleted models or provider records fail instead of falling back to another model. Bindings do not store raw credential-bearing configuration.

After upgrading and restarting the gateway, the new directory is published automatically. Legacy hashed `cc_…/default` and `cc_…/model_…` selections are no longer accepted. Restart Codex and reselect models in chats using old identifiers. Subsequent directory changes synchronize automatically, but a running Codex client may cache its old directory; management still prompts for a manual restart. Synchronization does not confirm client reload.

Choose **2 = Local CC Switch**, confirm the database path (default `~/.cc-switch/cc-switch.db`), and confirm activation.

The bridge only reads third-party static API configuration in the OpenAI / Codex section. It does not write the database or change another tool's selected provider. Edit models and keys in CC Switch. A source failure does not trigger fallback to another key.

## Manual YAML

For the first initialization, copy and edit the examples. These commands use the default directory; for a custom directory, change the variable and set `CODEX_HYBRID_DATA_DIR` or save the same directory with `config`. Run commands from the project root.

```sh
# macOS / Linux shell
ROUTER_DATA_DIR="$HOME/.codex-hybrid"
mkdir -p "$ROUTER_DATA_DIR"
cp config/models.example.yaml "$ROUTER_DATA_DIR/models.yaml"
cp config/deepseek.example.env "$ROUTER_DATA_DIR/deepseek.env"
chmod 600 "$ROUTER_DATA_DIR/models.yaml" "$ROUTER_DATA_DIR/deepseek.env"
```

```powershell
# Windows PowerShell
$RouterDataDir = Join-Path $HOME ".codex-hybrid"
New-Item -ItemType Directory -Force $RouterDataDir
Copy-Item config/models.example.yaml (Join-Path $RouterDataDir "models.yaml")
Copy-Item config/deepseek.example.env (Join-Path $RouterDataDir "deepseek.env")
```

Edit the API URL, protocol, and model ID in `models.yaml`, and set `DEEPSEEK_API_KEY` in `deepseek.env`. The example's model key is `deepseek/flash`, the YAML `provider_id/alias`. It is distinct from the upstream provider's model ID.

```sh
# macOS: prepare → start → connect Codex
./scripts/codex-hybrid.sh prepare --source yaml
./scripts/codex-hybrid.sh start
./scripts/codex-hybrid.sh activate
```

```powershell
# Windows
.\scripts\codex-hybrid.cmd prepare --source yaml
.\scripts\codex-hybrid.cmd start
.\scripts\codex-hybrid.cmd activate
```

`prepare` is for first initialization only. To change YAML on an existing installation, run `refresh-models --source yaml --models-config /path/to/models.yaml` as described in [commands](cli.md), not `prepare` again.

## API keys

Copy `config/models.example.yaml` to `<data-directory>/models.yaml` and edit the provider and model details. Choose one credential method for each provider.

Store the key directly in YAML; the management page also uses this method when saving a new key:

```yaml
credentials:
  api_key: "YOUR_API_KEY"
```

Or use an environment variable / `.env` file. Copy `config/deepseek.example.env` to `<data-directory>/deepseek.env`, set `DEEPSEEK_API_KEY=YOUR_API_KEY`, and configure:

```yaml
credentials:
  api_key_env: DEEPSEEK_API_KEY
  env_file: ./deepseek.env
```

`env_file` is relative to the YAML file. Without it, only the gateway process environment is read. `.env` files are not scanned automatically; reference them explicitly. Use the same pattern with a different variable name for other providers.

| Configuration | Read behavior |
| --- | --- |
| YAML specifies only `api_key`; other `.env` files or variables exist | Use the YAML key; do not read other sources |
| The same credentials specify both `api_key` and `api_key_env` / `env_file` | Reject with `CONFIG_AMBIGUOUS_CREDENTIALS`; choose one method |
| `api_key_env` is set in both the process environment and specified `.env` | Prefer the process environment; read the specified `.env` if unset or empty |
| The selected source has no valid key | Fail the request without switching credential sources |

Exporting a variable in another terminal does not update an already-running gateway's environment; restart it. Explicit `.env` files are reread for subsequent requests.

A new key entered in the management page is saved to `<data-directory>/managed-models.yaml` as `credentials.api_key`, replacing that provider's environment reference. Leaving the field blank preserves the existing source. Saving switches the active source to this managed YAML and leaves the original manual YAML unchanged. Edit the current source afterward, or continue in the management page. Keys are not displayed back to the browser.

Do not commit files containing credentials. Set manually created key files to POSIX `0600` or use a private directory ACL on Windows. Management-generated files get private permissions automatically.

## Management page

Initialize through the wizard or manual YAML first; installation cannot start from an empty management page. The default URL is [http://127.0.0.1:18891/manage/](http://127.0.0.1:18891/manage/). Use your custom port if needed, or obtain the URL with:

```sh
./scripts/codex-hybrid.sh manage-url
```

To require a private access link:

```sh
./scripts/codex-hybrid.sh manage-url --management-auth on   # Enable and print a token-bearing link
./scripts/codex-hybrid.sh manage-url --management-auth off  # Disable authentication
```

Specifying `--management-auth` automatically restarts the service. When enabled, both the page and management operations require the returned private link; the plain URL shows an access-restricted message. The setting lives in the data directory's `settings.json` and survives ordinary `restart`. Without the flag, `manage-url` retrieves the current address without changing settings.

Commands use the fixed user directory after installation. Override temporarily with `--data-dir` or `CODEX_HYBRID_DATA_DIR`. On Windows, use `.\scripts\codex-hybrid.cmd manage-url`.

In **Independent management**, add a provider and enter its API URL, protocol, key, and models, then save. In **CC Switch**, select the read-only database source. Keys are not echoed. Do not share private links containing the local access token.

Saving independent configuration makes `managed-models.yaml` the active source without overwriting the original YAML. After adding or removing models, fully quit and reopen Codex. Key or API URL changes take effect on the next request.

## Connect Codex manually

`prepare` reads the target Codex directory's `config.toml` and `models_cache.json`, then generates these files in the selected data directory:

- `models.json`: preserves official models and appends enabled third-party models.
- `original-config.toml`: original configuration backup.
- `desktop-config.toml`: complete candidate configuration for Codex.
- `settings.json` and `state.json`: gateway settings, target path, and overwrite protection checks.

`start` launches the background gateway. After checking readiness, `activate` writes the candidate to the target `config.toml`. `install` combines these steps; it does not modify the Codex application or model weights.

To edit manually, run `prepare` and `start`, then use the generated `desktop-config.toml` as a reference for the actual Codex `config.toml`; do not also run `activate`. The core settings are below. Replace placeholders before use:

```toml
# Top-level fields must precede all [tables]. Replace existing fields; do not duplicate them.
model_provider = "codex-hybrid"
model_catalog_json = "/absolute/path/to/router-data/models.json"

[model_providers.codex-hybrid]
name = "Codex Hybrid"
base_url = "http://127.0.0.1:18891"
wire_api = "responses"
requires_openai_auth = true
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0
http_headers = { "X-Connected-Token" = "COPY_THE_LOCAL_TOKEN_FROM_THE_GENERATED_CONFIG" }
```

`model_provider` selects the gateway, `base_url` selects its listening address, and `model_catalog_json` is the generated catalog's absolute path. `X-Connected-Token` must match `local_token` in `settings.json`; it is not a provider API key. Use the generated candidate's port and TOML-escaped Windows paths.

Prefer the complete generated candidate and `activate` to retain backup and integrity checks. After manual edits, `status` may show `modified_since_prepare`, and automatic activation or rollback may refuse overwrite. Merge against the backup manually when needed. Do not overwrite the entire file after other settings have changed.
