# Unified protocol compatibility fix

## Changes

Responses and Chat Completions now share portable history normalization. Readable reasoning or summaries become historical assistant text; opaque state is not forwarded to a foreign endpoint. Official native encrypted history remains unchanged. Tool call/result pairing and identifiers survive normalization.

External system/developer messages are collected in order into one instruction section: Responses uses top-level instructions, Chat uses one first system message. Synthetic requests established that Qwen rejects a system message inserted mid-history with `InvalidParameter`: system messages must be unique and first. The routing context was previously inserted near the latest user turn then converted to system, violating that constraint. No provider-name branch was added.

Both protocols use a single JSON SSE framing parser, retaining event-only types and multiline data. Explicit typed/untyped upstream errors become sanitized response.failed terminals instead of falling through to generic early-EOF errors. Protocol mismatch and unsupported history receive fixed error codes; EOF and [DONE] do not manufacture success. Connection tests now distinguish explicit failure from absent completion.

Native coordination instructions list actual aliases derived from the same bindings used to encode tools and decode calls. Ambiguous unqualified names remain rejected. No automatic protocol switching, new generation retry, or model-name compatibility rule was added.

## Verification

- 18 focused regression tests: reproduced failures before implementation, now pass.
- Full Python suite after the final source change: 277 tests, OK, 2 existing platform skips (local test sockets required execution outside the restricted sandbox).
- Web checks: 23 tests passed.
- Python compileall and git diff --check passed.
- Synthetic portable-history live verification: DeepSeek V4 Flash, DeepSeek V4 Pro, Qwen3.8 Max, Qwen3.8 2.4T A95B, Qwen3.8 27B, GLM 5.3, GLM 5.3 Flash all returned response.completed. Final seven calls reported 2,852 total tokens; this excludes earlier diagnostic probes and coordination. Per-call output budget 512.
- Qwen synthetic history produced InvalidParameter before instruction consolidation, and completed after it. Initial assistant-first probes were unsuitable as proof of the real scenario and were replaced with user→assistant→user history.

## Authorized follow-up and desktop root cause

The user explicitly authorized transmitting registered tool definitions to the existing DeepSeek/Qwen endpoints. Five full-tool-definition probes completed, returning CODE_71. Native CLI verification through an isolated gateway then passed all 23 cases: seven third-party models each fresh → official → third-party, plus a fresh official → DeepSeek case. Four cooperation cases passed: parallel DeepSeek/Qwen children; tool-history switching official → GLM → official; and GLM spawning official and DeepSeek grandchildren.

The original five desktop conversations initially still failed after these CLI checks. Marked-request diagnostics recorded field names/types and fixed error vocabulary only. They showed that desktop task notifications arrive in function_call_output envelopes containing name/namespace/output but no call_id. They are host-delivered context, not completed executable calls. Foreign endpoints require real tool-call identity; replaying the envelopes directly caused the remaining DeepSeek 400 and Qwen upstream failure.

Shared portable normalization now retains the notification source and text as ordinary user context when a named output has no call_id. Real call/result pairs retain their existing identities. No call IDs or execution results are invented. The same rule handles function and custom-tool output envelopes across both protocols.

Native testing also caught two gaps in the preceding implementation: developer-role additional_tools metadata was incorrectly treated as system text, and the cell/process wait tool was included in agent coordination guidance. Both have failing-first regressions and structural fixes. A TypeError in the temporary diagnostic script when reading content:null was corrected separately; it was not a product defect.

## Final live result

The existing gateway was reloaded only after observing zero active requests; forwarding is running and Codex config.toml remained byte-for-byte unchanged. No Codex application restart or model configuration change was needed. The temporary structural diagnostic hook was removed on the final reload.

The five original failed desktop sessions now all complete and retain their original random codes:

| Model | Result |
|---|---|
| DeepSeek V4 Flash | FLASH_7K29 |
| DeepSeek V4 Pro | ROUTE_2_K37 |
| Qwen3.8 Max | ROUTE_3_K38 |
| Qwen3.8 2.4T A95B | ROUTE_4_K39 |
| Qwen3.8 27B | ROUTE_5_K40 |

Gateway model/returned_model/status records confirm the intended external routes and completed responses. Known recorded test subtotal for the authorized follow-up artifacts is 1,042,607 tokens (tool-definition probes, native matrix, cooperation, final original desktop cases). This is not an account-wide billing figure: coordination, automatic review, earlier smoke/diagnostic probes and requests lacking usage are excluded. Short replies, low reasoning, bounded cases and zero runner retries controlled test scope.

No provider-name compatibility branch, automatic protocol switch, fabricated completion or new generation retry was added. Model tool-choice behavior, limits and future protocol variants remain possible sources of error; these passing samples are not a guarantee for every conversation. No commit was made, and unrelated concurrent edits were preserved.

## Evidence

- protocol-fix-live-2026-10-29.json: initial seven synthetic cases.
- protocol-fix-authorized-tools-2026-10-29.json: registered-tool probes.
- protocol-fix-native-matrix-2026-10-29.json: 23 successful native cases.
- protocol-fix-native-cooperation-2026-10-29.json: four successful cooperation cases and tool-schema identities.
- protocol-fix-desktop-original-cases-2026-10-29.json: before/after original desktop results.
- protocol-fix-desktop-gateway-2026-10-29.json: final live routing evidence.
- protocol-fix-reload-2026-10-29.json: final safe reload and unchanged config check.

New tests: tests/test_protocol_compat.py. Architecture rationale: docs/en/architecture.md and docs/zh-CN/architecture.md.
