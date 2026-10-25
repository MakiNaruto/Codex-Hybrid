<div align="center">

# Codex Model Bridge

**Use your OpenAI subscription and third-party APIs from Codex's native model picker.**

Switch models in your main chat, or let an official-model agent delegate to a third-party native subagent.<br>
Manage providers, models, and API keys locally, with optional CC Switch integration.

**English** · [简体中文](README.zh-CN.md)

[Quick start](#quick-start) · [See it in action](#see-it-in-action) · [Common commands](#common-commands) · [Documentation](docs/en/README.md)

</div>

## See it in action

<table>
  <tr>
    <td align="center" valign="middle">
      <img src="docs/images/codex-model-picker.png" width="520" alt="Select a third-party model in Codex's native model picker and receive a Hello World reply">
    </td>
    <td align="center" valign="middle">
      <img src="docs/images/management.png" width="290" alt="Codex Model Bridge local management page: routing, configuration sources, providers, and models">
    </td>
  </tr>
  <tr>
    <td align="center"><sub>Select a third-party model in the native picker and receive a reply</sub></td>
    <td align="center"><sub>Manage routing, sources, providers, and models in one page</sub></td>
  </tr>
</table>

| What you want to do | How it works |
| --- | --- |
| Use a third-party model in Codex | Add a model → restart Codex → select it in the native model picker |
| Combine official and third-party models | Have an official-model agent create a native subagent with a specified model |
| Reuse existing configuration | Select CC Switch as a read-only source and continue editing in CC Switch |

## Quick start

### 1. Prerequisites

- **macOS or Windows** with **Python 3.11+** installed.
- The **Codex desktop app**, signed in, with at least one completed chat.
- A third-party provider's **API base URL, model ID, and API key**, or an existing **CC Switch** configuration.

### 2. Clone and launch

Clone the repository into a directory you plan to keep:

```sh
git clone https://github.com/MakiNaruto/CodexModelBridge.git codex-model-bridge
cd codex-model-bridge
```

Run the command for your system from the project root, or double-click the launcher:

| System | Terminal command | Double-click launcher |
| --- | --- | --- |
| macOS | `sh scripts/codex-model-bridge.sh install` | `scripts/start-macos.command` |
| Windows (PowerShell) | `.\scripts\codex-model-bridge.cmd install` | `scripts/start-windows.cmd` |

The launcher creates `.venv`, installs dependencies, and opens the install wizard. **The wizard and management UI are currently in Chinese.** The first installation needs internet access to download dependencies.

### 3. Configure and restart Codex

1. Choose **Manual API setup** or **Local CC Switch** and follow the prompts.
2. Choose whether to start the local service now. Installation does not enable client routing automatically.
3. After the service starts, enable **Client routing** in the management page, then **fully quit and reopen Codex**.

Turning the switch on backs up and updates Codex's `config.toml`: it sets `model_provider` to `codex-model-bridge` and writes the local model catalog and gateway connection settings. Turning it off switches `model_provider` back to `openai` and removes the local model catalog setting while keeping the `codex-model-bridge` provider table for a later switch back. The local service keeps running.

Private data is stored in the project's `config/` directory by default. Use the [local management page](http://127.0.0.1:18891/manage/) to add providers and models or update API keys. For a custom port or private access link, run `manage-url` to get the address.

> While routing is enabled, both official and third-party models depend on the local service. Run `start` after restarting your computer. See [advanced setup](docs/en/cli.md) for custom data directories, Codex paths, and YAML configuration.

### 4. Send your first message

Select a third-party model, start a new chat, and send:

```text
Reply only: Hello World
```

Expected reply: `Hello World`. This is a basic model check; see the [usage guide](docs/en/usage.md) for tool-call and native-subagent verification.

You can also click **Test connection** in the management page to send a basic request. Chats and connection tests use the selected provider's quota. Initial setup does not automatically call paid APIs.

## Common commands

The examples below use macOS. On Windows, replace `./scripts/codex-model-bridge.sh` with `.\scripts\codex-model-bridge.cmd`.

```sh
./scripts/codex-model-bridge.sh start           # Start the service
./scripts/codex-model-bridge.sh stop            # Stop the service
./scripts/codex-model-bridge.sh status          # Show service status and model keys
./scripts/codex-model-bridge.sh manage-url      # Get the management page URL
./scripts/codex-model-bridge.sh refresh-models  # Update the model catalog, then restart Codex
./scripts/codex-model-bridge.sh restart         # Restart the service after updating code
./scripts/codex-model-bridge.sh rollback        # Restore the backup
./scripts/codex-model-bridge.sh uninstall       # Stop service and confirm Codex configuration rollback
```

After adding or removing models, update the client model catalog and restart Codex. API key or base URL changes take effect on the next request.

## Learn more

| Guide | Topics |
| --- | --- |
| [Configuration](docs/en/configuration.md) | API keys, YAML, CC Switch, data directories, and migration |
| [Commands and advanced setup](docs/en/cli.md) | Commands, defaults, private access links, and custom paths |
| [Usage and verification](docs/en/usage.md) | Connection tests, main chats, native subagents, and verification limits |
| [Troubleshooting](docs/en/troubleshooting.md) | Missing models, 401 errors, installation, and rollback |
| [Architecture](docs/en/architecture.md) | Routing and credential boundaries |
