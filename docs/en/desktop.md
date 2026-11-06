# Desktop development preview

[简体中文](../zh-CN/desktop.md) · [Documentation](README.md)

The desktop app shares the browser management interface and provides configuration, models, Codex routing previews, and tray controls. It remains a development preview. Release installers, signing, and clean-machine acceptance are pending.

## Obtain and launch

The current top-level macOS build entry supports Intel x86_64 and produces `apps/desktop/build/stage0/Codex Hybrid Tray Preview.app`. Windows x64 produces the portable directory `apps/desktop/dist/stage0/windows-x86_64/`. Keep `Codex Hybrid.exe` and `hybrid-stage0-probe.exe` together, then launch the window executable. Apple Silicon still requires native acceptance testing.

Source-build prerequisites and commands are in the [macOS build guide](../../dev-docs/desktop/build-macos.md) and [Windows build guide](../../dev-docs/desktop/build-windows.md). Developer guides are currently maintained in Chinese.

## Initialize and configure sources

Desktop uses the fixed user directories `~/.codex-hybrid` and `~/.codex`. CLI directory environment overrides do not apply. On first launch, click initialize. Initialization currently requires official Codex configuration and its model cache. It prepares management configuration and a recovery baseline. Launching or initializing the app does not automatically enable routing.

Configure providers, models, and keys in the management interface. See [Configuration](configuration.md). CC Switch sources remain read-only. A blank key during editing preserves the existing key. Failed operations preserve unsaved drafts. Connection tests require an explicit click, contact the provider, and may incur charges.

## Preview, enable, and recover

Preview enabling or disabling routing, review active requests and model/index effects, then explicitly confirm. Optional Codex actions require confirmation. Configuration changes and client configuration loading have separate results.

After an abnormal exit, a routed configuration requires an explicit choice to recover the service or preview and confirm disabling routing. Check routing configuration, gateway health, and remote model availability separately. See [Usage and verification](usage.md).

## Tray and exit

Both platforms provide management, hybrid routing, restart Codex, and exit menu entries. A checkmark indicates routing configuration. Tooltips and the management page show gateway details. Closing the window hides it while retaining drafts and services. Use the exit action to finish the app. Canceling a confirmation does not submit the operation.

### macOS

Reopen through the tray management action or Dock. Cmd+Q and tray exit run safety checks. Active routing may first require a preview restoring native configuration, followed by another safe-stop check. When desktop reuses an existing browser service, exiting desktop disconnects while that service continues running.

### Windows

Right-click the notification-area icon for the menu and double-click to restore the management window. Active routing, in-flight requests, or unknown safety state trigger native exit confirmation. Confirmation exits desktop and its owned gateway while preserving saved routing configuration. Follow recovery prompts on the next launch.

Real Codex restarts, complete tray interaction, and some native behavior still need acceptance testing on each platform. See [Development status](../../dev-docs/desktop/status.md).

## Update and recover

Exit the old preview normally, rebuild, and replace the complete artifact. Update both Windows executables together or the complete macOS `.app`. An automatic update workflow has not completed acceptance testing. User data remains in the fixed user directories above.

See [Troubleshooting](troubleshooting.md) for startup, configuration, and rollback issues. Abnormal disconnection retains configuration and the recovery baseline. Follow recovery prompts after reopening. Confirm the effects before testing live connections or restarting Codex.
