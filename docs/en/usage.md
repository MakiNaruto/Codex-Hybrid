# Usage and verification

**English** · [简体中文](../zh-CN/usage.md)

[Project home](../../README.md) · [Documentation](README.md)

## Browser Codex connection switch (minimal version)

Use the connection switch on the existing local management page. Review the change and confirm to save routing and catalog settings; cancel leaves configuration untouched. Disabling restores the fields from before this connection, including absent fields, while retaining unrelated edits. Changes after preview, conflicting edits to managed fields, or an invalid backup stop the switch.

The switch reports saved configuration, without tracking client reload acknowledgements. Enabling and disabling have separate desktop-action preferences: ask each time (default, unchecked), automatic, or no desktop action. On Windows and macOS, enabling can start or gracefully restart the identified Codex desktop app; disabling only restarts an already-running app. CLI and VS Code clients must be restarted manually. Unknown installations, custom CODEX_HOME, and failed detection fall back to manual handling.

Each confirmed operation requests cooperative Windows background shutdown once through Restart Manager. It registers only exact desktop process identities (PID and native creation time), verifies the affected application list, and never enables force shutdown. No foreground activation, taskbar click or keyboard simulation is used. Windows manages the shutdown request; after it succeeds, the gateway waits up to another 12 seconds for process exit. A refused shutdown still allows configuration changes and reports manual restart. Configuration failure stops without reopening the app. Launch waits up to 20 seconds for a visible desktop window. This OS session-ending path may differ from the app's Quit menu and does not guarantee running tasks resume. Select an official model after disabling. Management stays available on a separate listener. Forwarding stops after disabling only when there are no active requests and no detected Codex processes; otherwise it is retained.

## Test a model connection

On Windows, each upstream request reads the current user's system HTTP/HTTPS proxy and bypass rules again. Changing or disabling the system proxy takes effect without restarting the service; disabling it uses a direct connection, whose availability depends on the network. Inherited proxy environment variables and `upstream_proxy` do not override the Windows system selection. This does not control network-level forwarding such as Clash TUN or evaluate PAC scripts. macOS retains the existing explicit `upstream_proxy` override and Python environment/system proxy discovery behavior.

Open the management page, save and enable a model, then click **Test connection**. The test sends `Reply with exactly hello and nothing else.` with an output budget of at most 8192 tokens, or the model's lower configured limit.

Success means this basic request completed. Full Codex sessions and tool calls need separate verification. The 8192-token limit is an output budget, not a guarantee of total usage or cost.

## Use a third-party model in a main chat

Select a configured model in Codex's native model picker, start a new chat, and send:

```text
Reply only: Hello World
```

Expected reply: `Hello World`. A new chat helps verify the model selection. Full sessions include system instructions, tool definitions, and history, so their input is usually larger than a management-page connection test.

## Create subagents across models

Select an official or third-party model that supports tool calls in the main chat. The gateway advertises enabled child models in collaboration tools for official, third-party native Responses, portable Responses, and Chat Completions routes. A parent can select an official or another third-party child model; children can create further subagents within the client's depth and concurrency limits. Native Responses retains its tool namespaces and stream events without portable conversion.

Send the prompt below. **Replace the model key first.** The manual YAML example uses `deepseek/flash`; the setup wizard uses `custom/default`. For CC Switch, use the actual registered key. Run `status` to list model keys. To verify the reverse direction, select a third-party parent and use a client-supported official model key or another enabled third-party model key for the child.

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

After upgrading, restart the service and run `manage-url`. Management defaults to the forwarding port plus one (18892); port 65535 uses 65534 instead. An explicit `management_port` must be distinct. The forwarding port no longer serves the management UI. With routing disabled, management can still save configuration and perform user-triggered connection tests. Routing activation starts forwarding before committing configuration. Forwarding bind failures leave management available. Management now supervises an isolated forwarding child process. Unexpected exits trigger at most three restarts after 1, 3, and 10 seconds; 60 seconds of continuous operation resets the retry budget for a later crash. Startup failures stop retries. User-requested stops, individual request errors, and health-check timeouts do not trigger restarts. Interrupted requests are never replayed. Starting or restarting Hybrid restores the saved routing choice: enabled routing starts forwarding automatically; disabled routing starts management only. The switch reflects the saved choice even during startup or a forwarding fault. Faults show a reason and a Retry action; turn the switch off to restore the original configuration. Refreshing the page does not restart the service. The child exits when its private connection to the management process closes.

OS-held `service.lock` prevents duplicate services for one data directory. `operation.lock` serializes management/CLI writes, `control.lock` serializes CLI lifecycle commands, and `.codex-hybrid.lock` protects migrations targeting the same Codex directory. Lock files remain after exit; do not delete them to unlock. External applications still require conflict checks.

Process detection and switch previews only inspect whether Codex desktop, CLI and VS Code clients are running. Permission or identity failures remain unknown. Task status probing has been dropped: no task sockets, internal IPC or thread history are read. Process presence and zero gateway requests do not establish task idleness. Windows behavior still requires device validation.


### Notification and startup reliability (2026-10-29)

On macOS, CC Switch directory monitoring uses kqueue to observe writes to an open SQLite WAL without treating shared-memory read activity as configuration changes. Periodic synchronization remains the fallback if notifications are unavailable. Other platforms keep their native observer.

Forwarding reports a starting state while management status queries remain available. Routing commits revalidate configuration and index revisions after startup. The worker readiness deadline is 10 seconds; CLI control calls allow 15 seconds including failed-child cleanup. Startup faults expose fixed categories (port occupied, permission denied, timeout, invalid configuration, early exit, or other startup error), never raw exception messages.


### Desktop switching and logging backpressure (2026-10-29)

Management status remains available while waiting for Codex desktop to quit or launch. The page reports preparation, graceful exit, configuration application, and launch progress. Concurrent routing switches are rejected until the current operation finishes. Desktop system calls run outside the configuration lock; commits recheck configuration and replan indexes flushed during exit. Configuration changes stop the write and prevent the subsequent desktop launch.

The forwarding child sends records through a background writer, and the management process writes records through another background writer. Desktop operation results reuse the management queue, so routing responses do not wait for disk writes. Each queue holds at most 256 pending records, with each record reduced to at most 16 KiB of metadata before enqueueing. Full queues drop new records; actual event-log write and rotation failures also count as known drops, even when Python logging handles the underlying exception. `forwarding.log_dropped_records` in status and diagnostics reports known drops on both sides for the current management-service lifetime, including across child restarts. Backpressure and disk stalls do not block supervision, crash recovery, or request threads. Each supervision pass reads at most 64 records. Shutdown allows at most 0.2 seconds per writer to drain; trailing and crash-time in-flight records may be lost.

Each database backup stops the switch after an approximately five-second deadline when the database stays exclusively locked; release the lock and preview again. Log files are closed in background threads, with a total 0.2-second wait in `RuntimeLog.close()`. Python logging shutdown also avoids waiting on blocked writer locks. Unterminated stderr fragments are retained during normal close; stalled writes can still lose trailing records.

## Manage added models

The main page lists added third-party models only. Use Add models to search and select in batches. Open model details to set compatibility, test the connection, or remove the model. New Responses configurations default to Portable; explicitly disabling it preserves native format. Chat retains its existing conversion. Removing a model preserves its source configuration and blocks subsequent routing; in-flight requests retain their own snapshot. Restart clients after adding/removing models to reload their picker.

Manage connections edits independent providers or reuses CC Switch read-only. Re-enable source-disabled models at their source first. Newly discovered models are not automatically added; upgrade preserves previously advertised models. Model overrides are stored in Hybrid, never written back to CC Switch.
