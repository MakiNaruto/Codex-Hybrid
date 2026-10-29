# Native Responses routing boundary

Responses now defaults to native transport for YAML, CC Switch and the legacy
single-provider route. It preserves standalone outputs, namespaces, native tools,
history/encrypted reasoning, request fields and streamed tool argument deltas.
It does not inject portable routing context, rename spawned tasks, retry unknown
tools or switch to Chat Completions. Address, credentials, model mapping,
explicit parameters/output budgets and no-storage policy remain routing concerns.

Chat retains the existing conversion. `responses_compatibility: portable`
explicitly restores the old Responses bridge. `history_migration: true` is an
independent native-route option for replayable item IDs; it does not decrypt or
resolve service-local state. Management exposes both options. CC Switch reads
the same fields from the selected provider's TOML without writing its database.

## Validation

- 78 focused Python tests passed: native routing, explicit portable routing,
  unchanged Chat conversion, legacy routing, CC Switch live configuration,
  history IDs, protocol errors, SSE transport and tool catalogs.
- 11 of these are new native-path regressions, including preservation of native
  fields/events and a real temporary CC database native/portable switch.
- 24 frontend tests passed; JavaScript syntax, Python compilation and
  `git diff --check` passed.
- A full-suite snapshot ran 293 tests (before four additional native regressions
  were added): 7 failures and 76 errors. The additional four tests passed in the
  final focused run. Full results are in `responses-native-tests.json`.
- 73 full-suite errors report `os.fsync` on a read-only backup file raising
  Windows `OSError: [Errno 9] Bad file descriptor`; two subsequent migration
  errors report missing recovery paths. An unchanged HEAD copy of
  `desktop/session_migration.py` reproduces the direct fsync failure.
- The other six non-fsync cases (five assertion failures and one HTTP 400)
  were run against a temporary archive of HEAD and all reproduced; see
  `responses-native-baseline.json`. The other two assertion failures include
  the same fsync exception in their reported result.

No live model calls, configuration migration, production reload or application
restart was performed. These tests establish routing behavior, not compatibility
of a particular third-party endpoint with all native Codex features.
