# Return reminders simplification (prompt 126)

Source-only review. Release is held for Ruggie's preview approval. No production API requests, reminder sends, backend runtime edits, scheduling rules, recipients or destination settings changed.

## Behavior

Running FWA rows have **Change frequency**, using the existing Frequency selector and existing `resume` read/write endpoints. Paused FWA rows retain Resume; Main, future-scheduled, idle and expired rows do not offer frequency change. Running rows keep their saved frequency visible. Selection uses the existing server revision and durable request identity; double submission remains blocked.

Confirmations name Send now, Start reminders, Resume, Change frequency and Pause. Frequency review names the new interval and states that the stop time stays unchanged. Send review shows each known last-send timestamp without preventing another deliberate send. Signup reminder Save passes the Save confirmation label; its other confirmations retain their existing labels.

Start, post-capture guidance, away-check guidance and selection-limit wording are shorter. Clear member list opens the same existing maintenance review/confirmation: the backend `clear` operation calls `finish`, archives the saved list and stops its job. It does not delete history or bypass confirmation. A failed overview refresh keeps clearly labeled old rows usable; 401/403 clears protected rows and selection.

The top label is explicitly **CWL month for new member lists**. Existing capture policy uses UTC and the list expiry month: captures from the 16th belong to the next month, including December → January. Both pools use this policy. The API does not expose each saved list's persisted `cwl_season`, so this label never claims to describe older saved lists. Their existing start/stop dates remain visible.

## Prerequisite proof, before UI changes

`tests/test_return_frequency_resume.py` calls the real existing service and store against the established in-memory collection/scheduler fixtures for 30, 60 and 120 minutes on an already-running FWA list. All three pass: only frequency changes, last-send/count/start/stop remain exact, one scheduler job is replaced, next run equals last successful send plus the selected interval and is in the future, and no send callback runs. No backend change was needed. An immediate-next-run mutation is killed by these assertions.

## Checks

- Full frontend: **1497 tests / 262 files**; TypeScript and complete main/preview Vite build pass.
- Return frontend focused: **15 tests**, including existing model regressions; real service/store prerequisite: **3 passed**.
- Two genuine mutants killed: force immediate scheduling; incorrectly map frequency to start instead of resume. Originals restored, no backend runtime diff.
- Required `tools/check_war_reminders.py`: 213 backend passed / 1 skipped; 35 frontend tests, TypeScript and isolated build pass. Existing aiohttp configuration warnings and the normal 500kB Vite chunk advisory are retained in the log.
- Checked-in browser harness: overview, frequency confirmation, failed refresh and denied refresh at **320 / 360 / 390 / 1440** (16 states), no horizontal overflow or browser exceptions. Actual keyboard Enter confirms exactly one local resume POST and no start/send POST. Refresh 500 keeps Change frequency usable; 403 removes every clan row. Visible buttons/selects use 44px targets; checkbox labels remain the existing larger click targets.
- Narrow/wide overview and phone confirmation visually inspected. Focus uses the existing dialog trap/return behavior, and controls remain native buttons/selects/disclosures. No screen-reader-device test claimed.
- Diff and formatting checks pass. Runtime backend/transport/storage files are unchanged.

## Local review

Preview: `http://127.0.0.1:33857/return-reminders-simple-preview.html` (PID 2245516). Actually served entry `returns-BwVtQl3T.js`, SHA256 `22dabd6370c78bd1a3fdf40b06d5309c3330b45eeddefce3fc57efb836b590a2`. Fictional rows include running/paused/idle/unsaved/expired FWA and a manual Main clan. The fixture intercepts its own reads and writes in the page; it does not call an external service or persist production state. Existing details/clear routing is represented by a local explanatory alert. Real resume semantics are proved separately by the service/store test above.

Browser reproduction, from the isolated worktree with dependencies installed:

```sh
TMPDIR=/workspace-owned/short-browser-temp node web/cwl/tests/return-reminders-simple.browser.cjs http://127.0.0.1:33857 .local/fresh-return-layout
```

Browser traffic outside the local preview origin is blocked. `window.returnFixture.calls` records local request paths/methods; `window.returnFixture.failRefresh(500)` or `(403)` injects one failed refresh. No provider, Discord, database or send credentials are present in this frontend fixture.

Evidence is retained in this worktree's `.local/p126-*` logs, mutant results and layout folders. Initial test failures used a reversed ApiError constructor; corrected tests then exercise actual 401/403 clearing. Initial browser failures were missing default Playwright browser and ambiguous Frequency region/selector; installed Chrome and a scoped selector corrected the harness. Initial standalone Vite-config import resolution failed; explicit isolated Vite main/preview build and the normal required war-check build passed. Earlier evidence/logs remain available; no passing check is claimed for those failed attempts.

## Review limits

The frontend never changes send/retry/recipient behavior. Backend authorization, revision comparison, queue receipts and send uncertainty handling remain authoritative. A stale retained row can therefore receive an honest conflict when reviewed; refresh or changed permissions do not silently replay an action. No live role changes, reminders, Discord rendering or production scheduler behavior were tested. The existing list-detail editor remains unchanged; this scope simplifies the overview and its existing bulk review control.
