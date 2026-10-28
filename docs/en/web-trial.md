# Web trial checklist

**English** · [简体中文](../zh-CN/web-trial.md)

[Project home](../../README.md) · [Documentation](README.md)

> This document records an early web validation round. Optional Windows desktop launch/restart controls were added on 2026-10-27, and manual restart confirmation was removed. See [usage](usage.md) for current behavior. That update passed 141 tests, JavaScript syntax checks, and diff checks. Read-only detection found the local installation; restricted process access falls back to unknown status. Actual desktop shutdown/restart remains untested. The earlier browser checks below do not verify those newer interactions.

This iteration focused on the existing management page, without desktop packaging, a tray, automatic restart, or conflict-repair workflows.

## Open the updated page

Restart the local service from the project directory, then refresh the management page in an independent browser:

```sh
./scripts/codex-hybrid.sh restart
./scripts/codex-hybrid.sh manage-url
```

On Windows, use `.\scripts\codex-hybrid.cmd`. Keep the same `--data-dir` for a custom data directory. Existing management links remain usable; obtain private links with `manage-url`. Do not use the test environment's port 18991 for a real instance.

Restarting interrupts unfinished gateway requests, so wait for current tasks to finish. The recorded development round did not stop the real service, modify real Codex configuration, or send paid requests.

## Suggested trial sequence

The manual restart steps below describe the earlier interface; consult [usage](usage.md) for the current controls.

1. Check setup readiness and local service connection status at the top. Readable credentials and successful connections are shown separately; providers are not tested automatically.
2. Search provider or model names and IDs, and switch between enabled-only and all-model filters.
3. Edit a provider without saving and check the unsaved indicator. Edit and save another provider; the first draft should remain. Drafts are not stored in browser storage, so save before closing.
4. Check validation for request timeouts, context limits, and output limits in advanced settings. Duplicate provider identifiers should be rejected.
5. Save and click **Test connection**. This sends a real request using provider quota and shows the model ID and elapsed time on success. It tests saved configuration. Refresh the client model catalog and restart Codex before selecting the corresponding model.
6. In the earlier interface, routing or catalog changes triggered a manual restart reminder whose confirmation persisted across page refreshes and service restarts. Key/base URL changes without catalog changes did not require another restart confirmation.
7. Routing changes now migrate local session routing metadata. Fully quit Codex first and confirm in an independent browser. See [session migration](session-migration.md) for scope, backups, and recovery.
8. Open the runtime and diagnostics section, expand recent errors, and download sanitized JSON. Diagnostics are not uploaded automatically and contain no configuration, keys, or conversations.

## Features implemented in that round

- A setup-wizard option to configure models later in the web page, allowing management to start without third-party models.
- Setup readiness, credential readability, search, and enabled-model filtering.
- Unsaved indicators and navigation/refresh/source-change warnings, with other provider drafts preserved after saving.
- Test duration, provider request timeout editing, input validation, and clearer errors.
- Persisted manual restart confirmation, distinct from verification that the client actually loaded changes.
- Gateway activity counters, recent-error summaries, and allowlisted diagnostics downloads.
- Runtime and error logs rotating at 2 MiB with three older files retained; unusually large metadata records summarized.

## Verification and limits

The earlier final regression passed 64 tests, JavaScript syntax checks, and Git diff checks.

Automated coverage included empty-configuration initialization, skipping credentials in the wizard, separate data across source changes, read-only CC Switch access, persistent restart confirmation and rejection of expired confirmations, key updates, log rotation, diagnostics sanitization, and release of request/stream activity counters. No paid validation used real providers.

An isolated browser environment checked preservation and saving of two provider drafts, empty search results, successful simulated-upstream tests and timing, routing preview confirmation, restart reminders after refresh, manual confirmation updates, diagnostics downloads, and desktop and 390px layouts. Examples used temporary directories and dummy credentials; screenshots do not represent real model configuration.

The final unsaved-refresh confirmation test was blocked by a browser automation dialog. Draft preservation after canceling, confirmed discard, and leave-page warnings still require manual checks. Complete real Codex conversations, tool calls, real session migration, and Windows machine acceptance also require manual validation. No gateway requests does not mean tasks are idle. In that earlier version, the web page did not quit, launch, or restart Codex automatically.

Diagnostics read the latest 20 errors within the final 128 KiB of the current log, without searching rotated files. Oversized logs from older versions may become rotated files on the first rotation. Restart the service to apply the new logging policy. Early startup errors appear in `service.startup.stderr`, recreated on each background launch.
