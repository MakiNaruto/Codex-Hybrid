# Usage and verification

**English** · [简体中文](../zh-CN/usage.md)

[Project home](../../README.md) · [Documentation](README.md)

## Browser Codex connection switch (minimal version)

Use the connection switch on the existing local management page. Review the change and confirm to save routing and catalog settings; cancel leaves configuration untouched. Disabling restores the fields from before this connection, including absent fields, while retaining unrelated edits. Changes after preview, conflicting edits to managed fields, or an invalid backup stop the switch.

The switch reports saved configuration, without tracking client reload acknowledgements. Enabling and disabling have separate desktop-action preferences: ask each time (default, unchecked), automatic, or no desktop action. On Windows and macOS, enabling can start or gracefully restart the identified Codex desktop app; disabling only restarts an already-running app. CLI and VS Code clients must be restarted manually. Unknown installations, custom CODEX_HOME, and failed detection fall back to manual handling.

Each confirmed operation requests cooperative Windows background shutdown once through Restart Manager. It registers only exact desktop process identities (PID and native creation time), verifies the affected application list, and never enables force shutdown. No foreground activation, taskbar click or keyboard simulation is used. Windows manages the shutdown request; after it succeeds, the gateway waits up to another 12 seconds for process exit. A refused shutdown still allows configuration changes and reports manual restart. Configuration failure stops without reopening the app. Launch waits up to 20 seconds for a visible desktop window. This OS session-ending path may differ from the app's Quit menu and does not guarantee running tasks resume. Select an official model after disabling. Management stays available on a separate listener. Forwarding stops after disabling only when there are no active requests and no detected Codex processes; otherwise it is retained.

## Test a model connection

Open the management page, save and enable a model, then click **Test connection**. The test sends `Reply with exactly hello and nothing else.` with an output budget of at most 8192 tokens, or the model's lower configured limit.

Success means this basic request completed. Full Codex sessions and tool calls need separate verification. The 8192-token limit is an output budget, not a guarantee of total usage or cost.

## Use a third-party model in a main chat

Select a configured model in Codex's native model picker, start a new chat, and send:

```text
Reply only: Hello World
```

Expected reply: `Hello World`. A new chat helps verify the model selection. Full sessions include system instructions, tool definitions, and history, so their input is usually larger than a management-page connection test.

## Have an official-model agent create a third-party subagent

Select an official model that supports native subagents in the main chat, then send the prompt below. **Replace the model key first.** The manual YAML example uses `deepseek/flash`; the setup wizard uses `custom/default`. For CC Switch, use the actual registered key. Run `status` to list model keys.

```text
Create a native subagent with model deepseek/flash, fork_turns none,
and reasoning_effort low, if supported by that model.
Subtask: reply only CHILD_OK and do not call tools.
First state which model you will use, then create the subagent, wait for it,
and relay its result. Do not answer the subtask yourself or substitute an
MCP or command-line call for the native subagent.
```

Expected sequence: the main agent names the model → native subagent activity appears → the subagent replies `CHILD_OK` → the main agent relays the result. The client must expose and allow native subagent tools; a prompt cannot enable unavailable tools.

Verify routing using the model information in native subagent activity and gateway logs. A model's own identity claim is insufficient.

<details>
<summary>Verification scope</summary>

The replies above are expected examples. Verify the subagent workflow in your own desktop session; the connection test described earlier only covers a basic request.

</details>

## Daily management

See [common commands](../../README.md#common-commands) for starting, stopping, and checking the service. Commands use the fixed user directory; custom directories must be supplied explicitly. See [CLI defaults](cli.md#instance-configuration) for precedence and [data directory](configuration.md#data-directory) for migration.

After running `refresh-models`, restart the service and fully quit and reopen Codex. After adding or removing models, update the client catalog and restart Codex. API key or base URL updates take effect on the next request.

See [configuration](configuration.md) and [commands](cli.md) for more detail.


The Windows-only `desktop.probe_windows_restart_manager` (run with `PYTHONPATH=src python -m desktop.probe_windows_restart_manager`) creates isolated GUI fixtures, verifying background cooperative exit and respected shutdown refusal. It never operates on Codex. The real Codex background restart still needs separate validation.

On macOS, installation discovery validates the Codex bundle identifier and executable. Quitting uses Apple events and may require Automation permission; denied or timed-out quits fall back to manual handling without force termination. Launch confirmation checks for the desktop main process.

### Independent management and process locks

After upgrading, restart the service and run `manage-url`. Management defaults to the forwarding port plus one (18892); port 65535 uses 65534 instead. An explicit `management_port` must be distinct. The forwarding port no longer serves the management UI. With routing disabled, management can still save configuration and perform user-triggered connection tests. Routing activation starts forwarding before committing configuration. Forwarding bind failures leave management available, with recovery when routing is already enabled. Both listeners still share one Python process; crash isolation and supervision remain future work.

OS-held `service.lock` prevents duplicate services for one data directory. `operation.lock` serializes management/CLI writes, `control.lock` serializes CLI lifecycle commands, and `.codex-hybrid.lock` protects migrations targeting the same Codex directory. Lock files remain after exit; do not delete them to unlock. External applications still require conflict checks.

Process detection and switch previews only inspect whether Codex desktop, CLI and VS Code clients are running. Permission or identity failures remain unknown. Task status probing has been dropped: no task sockets, internal IPC or thread history are read. Process presence and zero gateway requests do not establish task idleness. Windows behavior still requires device validation.
