# Session index migration when switching routing

**English** · [简体中文](../zh-CN/session-migration.md)

[Project home](../../README.md) · [Documentation](README.md)

Enabling or disabling Codex Hybrid routing, and the CLI commands `activate`, `rollback`, and `uninstall`, migrate only the local session index in the selected Codex data directory. Archived sessions, subagent sessions, and paginated sessions are included. Cloud sessions and sessions in other data directories are excluded.

| Operation | Provider in the session index | Model in the session index |
| --- | --- | --- |
| Enable routing | Set to `codex-hybrid` | Keep the original model |
| Disable routing with an official model | Set to `openai` | Keep the original model |
| Disable routing with a third-party model | Set to `openai` | Use the first available model in the official list |

Official models are identified by the instance's `official_models` list, rather than name prefixes or the current provider. Fallback selection follows catalog order, filtered by the official list and hidden entries. An existing official model is preserved even if temporarily unavailable; Codex handles that situation. An unset model remains unset so Codex can apply its own recovery rules. Switching stops if the official list is unavailable, or if a required fallback cannot be found.

Enabling routing preserves the original model even if it is no longer in the hybrid catalog. Third-party models replaced when disabling routing are not automatically restored when routing is enabled again.

Migration does not modify `.jsonl` or `.jsonl.zst` history files, headers, historical turn models, reference offsets, or pagination caches. Routing configuration is updated without selecting, inserting, or overwriting its `model` field. CLI switching from an older configuration snapshot also preserves the current root-level model setting or its absence. `--default-model` is no longer supported, and old `session_default_models` presets are no longer used for migration; similarly named defaults in model connection configuration are unaffected.

## Switching routing

1. Open the management page in an independent browser. Finish tasks and quit Codex first if possible; the web page permits proceeding after confirmation, and process detection is advisory.
2. Toggle client routing. The preview shows existing session indexes, missing indexes to populate, and existing indexes whose history files are missing. Canceling the preview writes no data.
3. Confirm the index migration, then reopen Codex clients that need the new routing.

The web confirmation includes restart guidance. Impact details omit default models and repeated routing descriptions. **Check status** refreshes desktop, VS Code, CLI, and gateway status; gateway activity counts only gateway requests. The management service stays running after switching. Forwarding stops only when there are no active requests and no related processes are detected. Local desktop controls are optional; restart other clients yourself. CLI migration and interrupted-migration recovery still require Codex to be closed first.

### Codex populates missing indexes

The preview scans local filenames, necessary session headers, and existing indexes. It does not start Codex or rebuild indexes. Multiple history fragments count as one logical session.

After confirmation, an independent Codex app-server starts only if indexes are missing. It uses `thread/read` to populate metadata, without calling `thread/resume` or `turn/start` or generating model output. The helper uses temporary authentication storage, blocks outbound HTTP, and does not modify user configuration. The index migration transaction starts after the helper exits.

Executable discovery checks PATH, common desktop installation locations, and running Codex executables. For a custom installation, add `codex_executable` with the full executable path to the instance's `settings.json`, then restart the gateway. Switching stops if the executable is missing, its protocol is incompatible, or index population is incomplete. Complete existing indexes require no helper process.

Codex may create or update its metadata database while populating indexes. The tool then revalidates existing indexes, the file inventory, and preview state before creating a migration backup. If population fails, routing changes are not applied, but indexes already created by Codex remain.

Sessions with existing indexes but missing history files receive index updates without fabricated history. Missing history sources, reference cycles, and old offsets do not block index migration because this tool does not rewrite history files. Codex determines whether the history itself can be recovered.

### Windows

Windows and macOS share the same logic. The default Codex data directory in PowerShell is `$env:USERPROFILE\.codex`; `CODEX_HOME` or a custom instance can select another directory. Paths support Unicode and spaces, and configuration is read as UTF-8.

Run from the project root:

```powershell
.\scripts\codex-hybrid.cmd rollback
```

Do not modify configuration or indexes concurrently with tools such as CC Switch. Open Windows file handles, SQLite write locks, changes after preview, and backup or write failures can block switching.

### Web migration warnings

For incompatible database schemas, unsafe paths, conflicting session IDs, or unrecognized metadata in sessions without indexes, the web page warns and skips all index migration while continuing to save routing configuration. The CLI remains strict.

Warnings appear in the confirmation and result. Confirmation writes them to `session-migration-warnings.jsonl` in the instance directory, rotating at 2 MiB and keeping up to three older files without recording message content. Canceling the preview writes no log. Configuration validation, official-model validation, failed index population, stale previews, backup failures, and actual write failures cannot be skipped this way.

## Backups and interrupted-migration recovery

Before the first actual modification, including missing-index population, a fixed baseline is stored under `session-baselines/<codex-home-id>/` in the instance directory. It contains the index database, configuration to be changed, and history files affected by that operation's compatibility repairs, rather than all chat history. Each Codex home has a separate baseline and checksum marker; subsequent switches neither replace nor delete it. A missing or corrupt baseline blocks switching.

To explicitly replace a baseline with the current state, stop the relevant Codex clients and run `codex-hybrid reset-session-baseline --codex-home /codex/home --data-dir /instance/directory`. The next actual modification captures a new baseline. This is diagnostic material, not an automatic historical database restore.

Each migration temporarily saves the existing full recovery format under `session-migrations/<backup-id>/`. Success or a fully completed rollback deletes the temporary record. Cleanup failures are retried on startup and the next switch without failing a successful switch. Interrupted or incomplete rollbacks retain their records and block switching. Backups contain private configuration, indexes, and any history affected by repairs.

An ordinary write failure restores routing configuration and rolls back index updates. If interruption leaves the manifest in `applying`, subsequent switches stop. Keep Codex closed and run:

```powershell
.\scripts\codex-hybrid.cmd recover-sessions --backup "D:\Codex Data\session-migrations\backup-id" --data-dir "D:\Codex Data"
```

On macOS or with the installed CLI, use `codex-hybrid recover-sessions --backup /absolute/path/to/backup`; supply `--data-dir` for a custom instance.

Recovery supports interrupted migrations only and does not overwrite new data created after a completed migration. Older interrupted backups containing history files can still be recovered. New backups restore only the index provider/model fields and routing configuration owned by the migration, leaving unrelated metadata such as titles unchanged.

Switching back to OpenAI does not guarantee that its backend accepts all history created by third-party models. Correct model selection, recoverable history, and a successful real-backend reply require separate verification.
