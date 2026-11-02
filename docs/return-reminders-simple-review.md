# Return reminders review (126 / 135 / 140)

Source only. Release remains held for Ruggie's preview approval. No production requests, sends, backend runtime changes, scheduling rules, recipients or destination settings changed.

## Current workflow

Rows retain Members & details. Change frequency lives only in the selection actions. The first tick opens the shared Members-style selection bar: count, Select all, Select none and applicable actions. Phones use the shared ActionMenu; desktop uses plain buttons. There is no action dropdown or preselected action. The reusable SelectionActionBar shell is also used by MemberBulkBar; its existing labels, ARIA, partial-page checkbox, busy-action behavior and callbacks remain unchanged.

Actions include Change frequency, Pause, Resume, Start return reminders, Capture current members, Send now, Check away players, Replace saved lists and Clear lists where applicable. Replace/Clear reuse existing bulk endpoints. Clearing closes/archives lists and stops reminders while retaining history. Optional scheduling keeps its existing disclosure.

Every review names selected clans and their scope. Hidden clans, paused/non-running frequency targets and unavailable clans are listed by name with reasons and skipped. Only applicable, visible clans enter the durable bulk request. A filter edit retains selection but cannot silently act on hidden clans. The count button shows hidden selection; activating it clears filters to reveal selected rows. Changing home-clan type retains the existing selection-clear rule. Back and refresh retain valid selection. Permission denial clears protected rows/selection.

Frequency review shows each applicable clan's current interval and applies one chosen interval to all. Confirmation names the action and applicable count, for example Change frequency for 3 clans. It uses the existing resume endpoint, retains the stop time and does not send. Existing durable request identity, receipt/status checking and per-clan outcome text remain authoritative. A failed clan does not hide successful or other failed outcomes; no uncertain send is automatically replayed.

Frequency text is Every 30 minutes, Every hour or Every 2 hours throughout. Search, Filters and the overflow menu follow the Members pattern. Status lives in Filters; Refresh, Return channels and About this page live in the menu. Existing context is behind About. The plain month labels new member-list captures: existing UTC policy maps captures from the 16th to the next month, including December to January. It does not infer an older saved list's persisted month; its existing start/stop dates remain visible.

## Prerequisite proof, before original UI work

`tests/test_return_frequency_resume.py` invokes the real existing service/store for 30/60/120-minute changes on an already-running FWA list. Last-send/count/start/stop remain exact, one scheduler job is replaced, next run equals last successful send plus interval and remains future, and no sender callback runs. An immediate-next-run mutation is killed. No backend change was needed.

## Final prompt 140 checks

- Full frontend: **1502 tests / 263 files**, TypeScript, main and isolated preview builds pass.
- **21 focused UI tests** include the original MemberBulkBar phone-menu/busy/hidden-count cases, a shared-shell callback/ARIA/partial-page regression, all action confirmations, five mixed clans, hidden-filter exclusions, no preselected action, refresh failure/denial and receipt failure visibility.
- **31 isolated backend regressions**: real frequency prerequisite plus existing bulk API/native retry tests. These are local fixtures, not live delivery evidence.
- Three genuine mutants killed: include hidden clans in the write; route frequency to Send; automatically open Start after a selection. Each fails a meaningful assertion; original source restored.
- Checked-in browser harness at **320 / 360 / 390 / 1440**, 20 recorded states. Select five mixed clans; one reviewed bulk resume request names exactly the three running clans. Paused/no-list clans are named and skipped. Current 30/60/120 intervals are visible; the chosen interval applies to all three. Existing mixed outcome text shows the failed clan alongside successes. No send/start request occurs.
- Hidden-filter case retains selection, names hidden clans as skipped and writes only the visible selected running clan. Keyboard Space selects the first checkbox; Enter activates menu/desktop actions. Cancel/Back and completed refresh retain selection. No horizontal overflow or browser errors. Final narrow/wide selection and phone confirmation visually reviewed.
- Formatting/diff checks pass. The earlier required war-reminder check passed 213 backend / 1 skip, 35 frontend, TypeScript/build; this delta is frontend-only.

## Preview

`http://127.0.0.1:34017/return-reminders-simple-preview.html` — static server PID 2406134. Entry `return-reminders-simple-preview-CuoSBXXN.js`, SHA256 `2ea705bacd3204f131bd66eaacc60441d6c2f5d92fd6c65d5b19cfb0e761d83a`.

Fictional FWA clans have three running intervals, one paused list and one absent list; Main has a manual list. Its in-page fixture intercepts local reads/writes and records `window.returnFixture.calls` including request bodies. `failRefresh(500)` or `(403)` injects one failure. It has no provider, Discord or production database credentials. The browser blocks all requests outside this local origin. The fixture returns simulated per-clan outcomes; real service semantics are proved separately above.

Reproduce from this worktree:

```sh
TMPDIR=/workspace-owned/short-browser-temp node web/cwl/tests/return-reminders-simple.browser.cjs http://127.0.0.1:34017 .local/fresh-return-layout
```

The older 33857 preview and its files remain untouched for comparison. Prompt 135's actual first clan position was 222.14px at 360×800; its final 28 states and 1499-test frontend evidence are retained. The initial standalone preview config failed dependency resolution; the checked-in config and final main/preview builds pass. Earlier harness failures and their corrected passing evidence remain under `.local/p126-*`, `p135-*` and `p140-*`.

## Adversarial review and limits

Existing server authorization, list revision snapshots, destination ownership, durable receipts and uncertain-delivery handling are unchanged. Fresh options can remove a clan from the applicable scope rather than submitting stale authority. Malformed timing and frequency remain server validated. User/upstream text renders as React text. No new automatic retries or sends are introduced. A stale retained row can still receive an honest conflict, shown in its outcome. No live role changes, reminders, Discord rendering or production scheduler timing was tested. Clear/Replace remain explicit reviewed operations; history and unrelated lists are not rewritten by this frontend.
