# Model-first management implementation

Implemented the accepted list + add dialog + detail drawer layout. Main list shows added external models; connection editors and source controls are in Manage connections. Official models retain existing management. Empty/search/error/saving states, keyboard-accessible native dialogs, dark theme tokens and reduced motion are supported.

Responses defaults to portable for YAML/CC Switch when not explicitly configured. Model-level overrides select the actual routing adapter; explicit native remains available. Hybrid settings own membership and compatibility overrides. CC Switch stays read-only. On first publication, previously advertised external models are retained; subsequently discovered models require adding. A new source starts with an empty selection; switching back restores that source selection. Saving a new independent model is an explicit Add. Source-disabled models cannot be added through the API. Removed models fail live routing, including stale client requests, while in-flight snapshots remain intact.

Validation on macOS:
- Python full suite: 334 tests, 313 passed, 19 errors, 2 skipped. Untouched HEAD baseline: 323 tests, 302 passed, the same 19 errors and 2 skips. Exact error-case set comparison found no new failures. Baseline errors include legacy fixtures without source configuration, Windows SSL simulation under Python 3.14, and existing runtime tests. Full-suite logs are /tmp/hybrid-model-tests-delivery.log and /tmp/hybrid-model-baseline.log.
- 11 newly added Python cases cover defaults, overrides, actual native adapter choice, membership, invalid updates, source scoping, CC read-only/sync retention, write rollback, dormant overrides after protocol changes, and HTTP authentication.
- 31 Node frontend tests passed, including save failure recovery, source capture, and duplicate submission prevention. JS syntax checks and git diff --check passed.
- Real browser with isolated temporary YAML and dummy credentials: toggle off/save/reopen, remove, batch re-add, connection management. Console error/warning list empty. Main page no horizontal overflow at 320/768/1024/1440px; 320px drawer content also fits. No real upstream/model calls made.
- Screenshots: implemented-desktop.jpg and implemented-detail.jpg. Isolated preview at http://127.0.0.1:18973/manage/ intentionally remains available for review. Its Python process owns only a temporary fixture directory.

Shared management/catalog code applies to both platforms; Windows OS integrations were not changed or physically validated. Current real Hybrid service was not restarted. New frontend detects an old backend and requests a service restart before new model actions. No real user model configuration or CC Switch database was changed during this implementation.

Known full-suite baseline failures remain outside this change; this is not a claim of a green full suite or Windows acceptance.

Follow-up UI refinements: available-model checkboxes align to the left of each model, enabled rows offer direct removal, and the shared shell has three navigation pages (Access & runtime, Models, Runtime & diagnostics). The last page is remembered locally; URL fragments support direct links and history. Navigation updates headings and keyboard focus. Browser verification covered all three pages, reload restoration, a 320px viewport without horizontal overflow, and an empty console error/warning list. Screenshot: three-page-navigation.png.
