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

### Native Responses and explicit compatibility

The management page labels the choice as the provider API protocol and persistently explains the forwarding mode for both manual and CC Switch provider cards. Chat Completions retains Responses-to-Chat conversion through this gateway. Some tool types, standalone notifications and reasoning history may be downgraded or unsupported; a passing connection test does not establish full desktop compatibility. This configuration requires the gateway rather than a direct Codex connection to Chat Completions.

Responses defaults to portable compatibility for both YAML and CC Switch sources. Explicit native settings remain supported. Failures do not trigger Chat Completions fallback. Chat retains its existing conversion. Provider-level YAML options (also available under Advanced settings in management) are:

```yaml
protocol: openai_responses
responses_compatibility: portable  # default; native preserves protocol structure
history_migration: false        # true removes only replayable top-level history item IDs
```

Portable mode consolidates instructions, flattens tools, converts standalone tool outputs to user context, converts readable reasoning to historical text, and omits opaque reasoning. It already includes item-ID replay. History migration alone cannot decrypt reasoning or resolve bare item references. Responses support does not make encrypted state or file resources portable between services.

For CC Switch, these fields are read from the selected `model_providers.<provider>` TOML table; the database remains read-only. Defaults are `portable` and `false`. CC Switch `meta.apiFormat` still overrides `wire_api`. Chat configurations reject `portable` or enabled history migration, which are Responses-specific. Legacy single-provider `.env` routing also defaults to native Responses; use YAML or CC Switch for portable compatibility.

### Catalog and synchronization

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

Initialize through the wizard or manual YAML first; installation cannot start from an empty management page. The default URL is [http://127.0.0.1:18892/manage/](http://127.0.0.1:18892/manage/). Management defaults to the forwarding port plus one (or explicit `management_port`). Obtain the current URL with:

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
request_max_retries = 4
stream_max_retries = 5
stream_idle_timeout_ms = 300000
http_headers = { "X-Connected-Token" = "COPY_THE_LOCAL_TOKEN_FROM_THE_GENERATED_CONFIG" }
```

These retry and SSE idle values match the documented Codex defaults. Codex handles HTTP retries and stream recovery; the gateway does not replay failed upstream POSTs. The official upstream socket timeout is 300 seconds, rather than a total turn deadline. Third-party providers retain their configured `timeout_seconds`.


`model_provider` selects the gateway, `base_url` selects its listening address, and `model_catalog_json` is the generated catalog's absolute path. `X-Connected-Token` must match `local_token` in `settings.json`; it is not a provider API key. Use the generated candidate's port and TOML-escaped Windows paths.

Prefer the complete generated candidate and `activate` to retain backup and integrity checks. After manual edits, `status` may show `modified_since_prepare`, and automatic activation or rollback may refuse overwrite. Merge against the backup manually when needed. Do not overwrite the entire file after other settings have changed.

### Model membership and overrides

Configure frequent Responses models in Models → View details: turn off full compatibility, then select only the agent-message, standalone-output, or custom-tool conversions required by that endpoint. Save to apply on the next request. No selections means strict native. Enable full compatibility for the Portable fallback when needed; no automatic switching or retries occur. Portable retains the selected adaptations without activating them. Existing defaults and saved modes are not migrated in bulk.

Pydantic validates adapted structures with strict types. Only optional adaptation lists default to empty; task content, tool input, and call relationships are never invented. Invalid known structures fail explicitly. Unadapted native content and extension fields pass through. Tool JSON is validated once that tool input completes, without waiting for the entire response.

An additional option, “Expand discovered tools” (`discovered_tools`), merges definitions from `additional_tools` / `tool_search_output` into current `tools`, retaining namespaces and tool-search result call IDs. Expanded `additional_tools` metadata is removed; conflicting definitions fail. Enable this if the model repeatedly cannot find an advertised tool. It increases the explicit tool list and context usage. The GLM-5.3-Flash trial currently uses it.

Agent-message adaptation also recognizes readable task text placed by the host in `encrypted_content`. No decryption occurs; gAAAA ciphertext, UUID history markers and opaque tokens are rejected with `UNSUPPORTED_AGENT_MESSAGE_CONTENT`. Diagnostics record only fixed structural categories, never message text. Retest in a fresh chat or parent agent after changing adaptations, to avoid earlier failure history influencing the model.

The four adaptations (`agent_messages`, `standalone_outputs`, `custom_tools`, and `discovered_tools`) cover the main compatibility problems observed so far with GLM-5.3-Flash, DeepSeek V4.1 Flash, Qwen3.8 Max, and Qwen3.8 2.4T A95B: task delivery, notifications, tool formats, and discovery during nested delegation. Enable only the adaptations needed by the endpoint; this is not a universal compatibility guarantee. Prefer native mode with explicit adaptations and use Portable as a manual fallback.

| Current trial model | Adaptations enabled in native mode |
| --- | --- |
| GLM-5.3-Flash | agent_messages, standalone_outputs, discovered_tools |
| DeepSeek V4.1 Flash | agent_messages, custom_tools, discovered_tools |
| Qwen3.8 Max, Qwen3.8 2.4T A95B | All four |

These profiles reflect current endpoints and short real nested-agent tests on Windows on 2026-10-30. The necessity of discovered_tools for Qwen was not isolated. Long tasks, concurrency, old histories, and macOS remain unverified. See the [decision and troubleshooting record](../decisions/002-native-feature-adaptations.md) for evidence, request IDs, and conversion tradeoffs.

Experimental native feature adaptations: keep the model in `native` mode and set `responses_adaptations` in a model update to `POST /manage/api/models`. Supported flags are `custom_tools` (wrap only custom tools as functions within their original namespaces, restoring returned calls), `agent_messages` (plaintext agent tasks to user messages), `standalone_outputs` (named outputs without call_id to user context retaining provenance), and `discovered_tools` (expand definitions from tool discovery history). These are source-scoped Hybrid preferences; CC Switch remains read-only. An empty array restores strict native transport. Flags are dormant outside native mode. Model details displays active adaptations.

This path streams immediately, without whole-generation buffering or generation retries. Text, phases and unaffected tool argument deltas are preserved. Wrapped custom inputs are restored only after complete JSON/string validation, so their wrapper argument deltas are suppressed. Original grammar is conveyed as guidance rather than guaranteed upstream enforcement. Encrypted agent messages are rejected rather than decrypted or treated as plaintext. Connection probes do not establish full history-switching or nested-agent acceptance.

Model details offers a per-model compatibility switch. Hybrid stores this override and the added-model list in its private settings.json (`model_preferences`), without writing to CC Switch. YAML models may also specify responses_compatibility. Precedence: Hybrid model override → YAML model setting → provider setting → portable default for Responses. Chat does not expose this switch.

Membership controls both publication and live routing. The first upgrade publication retains previously advertised models; later discoveries require adding explicitly. CC Switch database selections are scoped separately and restored when switching back. Saving a new model in independent management counts as an explicit Add; external source-file additions do not.
