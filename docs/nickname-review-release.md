# Nickname import and review: prompts 83–86

## Production diagnosis

Read-only request evidence: the first Import started at 2026-11-01 08:51:17.921325 UTC and became uncertain at 08:52:58.617835, after 100.6965 seconds. Its message is the import-specific wrapper, which encloses directory fetch and serial profile writes in a 100-second timeout. The bot journal shows the management poll occupied throughout, with overlapping scheduler ticks skipped, and completion at 03:52:58 EST. The old handler did not log the underlying exception; the request timing identifies the budget boundary, while the exact contribution of Atlas latency cannot be reconstructed. No claim is made that other Mongo timeouts caused this request.

Ruggie's explicit retry started at 08:54:18.358778 UTC and finished at 08:55:14.400688, after 56.0419 seconds: 479 known, 44 unknown, 887 without a zone, 149 imported, 330 preserved, zero conflicts and 37 bots. This is evidence of resumable preserved progress. Codex did not retry either action. Sanitized receipt/timing evidence and journal are retained under `.local/p83-evidence` in the worktree.

## Implementation

Import validates the bounded directory, reads existing profiles in one batch and skips prior staff/Warrior/imported decisions. Eight workers reuse the existing per-member write owner, leases, fresh revision/source checks and CAS. TaskGroup cancels and drains siblings on failure; committed profiles remain. The storage owner also prevents an imported decision from displacing an earlier import. Partial confirmed counts are retained in the uncertain receipt and future import timing/cause/counts are logged. This changes worker code and needs one bot restart after acceptance, with the required 210-second lease drain.

The only entry point is Review nicknames: Import then a fresh token/revision preview, with no rename until confirmation. Terminal uncertain/failed imports get a fresh request ID on an explicit retry; an unconfirmed transport outcome retains its identity. Reusing an old ID returns its original durable receipt and does not rerun the queue. Errors are shown once. The profile-only import message says: Import stopped early. No nicknames changed. Press Review nicknames again.

Preview classification is a pure domain helper: Will change, Needs flag, No time zone, Already done, Can't rename and optional Check name. Bots are excluded. Filters reuse the extracted Strikes chip implementation; search and 25-row pages retain selection. The sticky count and submitted IDs use the same selection, and hidden selections can be shown. Check name starts unticked. Run manifests, token/revision checks, one-at-a-time worker, Stop and uncertain nickname outcomes are preserved. Past runs load only on request. The directory, member editor and Warrior workflow are unchanged.

## Rename speed and declaration copy

Read-only production receipts measured the owner's two-member run at 68.958 seconds, rather than the earlier code-only estimate of 40–50 seconds. The first child waited 9.379 seconds, the second was created 22.069 seconds after the first finished, and the parent finished 14.680 seconds after the last child. This identifies scheduler/cursor delays in addition to Discord and storage work. No production retry or nickname write was performed by Codex.

A lightweight one-second pending check drives the existing atomic request claim and single lane; the ten-second maintenance tick remains the fallback. One owned background task avoids overlapping scheduler jobs, and shutdown cancels and drains it. Durable child completion advances the cursor immediately, schedules the next child three seconds after completion, and finishes the parent without an extra tick. Restart uncertainty is retained and never replayed automatically. Other queue actions retain their transport and authorization paths.

Roles and the bot member are cached for at most 60 seconds in a bounded per-run cache. Each actual edit reads the target and actor freshly, checks current access, hierarchy and exact old nickname, verifies the owned profile lease after preparation, then makes one bounded Discord edit. Slow preparation that expires the lease cannot edit. Discord rate-limit waits are awaited; uncertain requests are not automatically retried. Timing logs cover claim delay, authorization, Discord reads/edit and profile save.

The run replaces review immediately on confirmation, disables duplicate submissions, polls at one second only while active, and opens on Changed. Its progress and result rows contain only the selected members, including older manifests that recorded unselected skips. Stop and partial/uncertain outcomes remain visible.

The separate prompt 85 frontend commit removes the Declaration ping paragraph, adds one confirmation line about finishing despite lineup changes, and shows Save channel/Discard only for an edited channel. The protected ChannelCombobox and its existing hint remain unchanged; no new hint prop was added.

## Validation and limits

The production evidence cannot reconstruct the original import's underlying exception because the old handler did not log it. Fixture timings below use fake Discord transport and a dedicated temporary local MongoDB, not live delivery. No production Import, Standardize, Rename or Send was pressed. The production release evidence is recorded below.

Final integrated validation after prompt 88: 5,683 guarded backend tests passed, 57 skipped, 224 subtests passed; 1,356 frontend tests across 242 files; TypeScript and production build; 139 focused integrated backend checks plus 13 rework edge checks; and 15 dedicated real Mongo lease/CAS, atomic claim, restart, Stop and import checks. The required war-reminder command passed 213 backend checks (one skip), 35 frontend checks, TypeScript and isolated build. All ten original behavioral mutants were caught: saved-profile overwrite, bot inclusion, reused uncertain ID, extra hidden ID, preview before import, preselected Check name, unsaved Declaration channel Ping, missing atomic claim guard, missing old-nickname check and zero pacing.

The 1,447-member isolated browser flow passed at 320, 360, 390 and 1440 pixels, including the unchanged editor, Import/Preview order, all categories, hidden selection, pagination, immediate selected-only run, Stop, lost permission, no overflow, 44px controls and 12px minimum text. Final 360/1440 preview and result screenshots were visually reviewed. Declaration copy has 12 isolated layout states and its own frontend-only commit. These fixture requests use fake transport. Earlier failed checks were corrected before READY; their logs remain in the worktree.

Evidence is retained under `.local/p83-evidence`, `.local/p86-evidence`, `.local/p87-layout-css` and the validation logs in the feature worktree. Review preview port 8938 serves an isolated fixture; entry `index-D7-4dqtM.js` SHA256 `02a3b5b8dd9fca3cd5d5f572d53c21088a68a078904839579a9c12be89ffb856`. Declaration copy preview remains on port 40585. These are review assets, not a production deployment.

| Fixture | Members | Elapsed | First edit |
|---|---:|---:|---:|
| before | 2 | 50.739 s | 10.335 s |
| after | 2 | 3.547 s | 0.279 s |
| after | 25 | 76.758 s | 0.291 s |

The final 25-member fixture refreshes roles and the bot member three times with the preparation safety margin, with exactly one fresh target read per member. Its edit gaps remain above three seconds. Baseline source is the pre-speed commit aeef3fe; only the after cases were rerun after the final safety fix.

## Prompt 87 review delta

The editor displays confirmed uncertain saves and an explicit repeat obtains a fresh request ID; transport-unknown outcomes retain their identity. Review and run hide the member directory, search and pager. Confirm establishes the live run immediately; a failed later status read keeps Stop available and polling recovers. The run has one live progress heading, opens on Changed, and shows attribution only in Past runs. The help line hides during review/run; single-page pagers are absent. The interrupted-import message now names Review nicknames. The three requested Prettier files are formatted.

Idle work detection is one indexed projected query per second, with the small additive `management_ready_work` partial index over pending management requests and queued profile runs. A dedicated 20,000-document archived fixture verifies zero documents examined on idle. No existing documents are migrated. Rollback to the prior runtime can retain this compatible index; it is unused there and may be removed only after rollback is healthy, never by restoring production data.

Retention pruning is throttled to once per minute during work and also runs at completion/Stop. Non-profile actions keep their five-per-ten-second budget across fast passes and fallback ticks. The CWL bridge shares the management lane lock because both can touch campaign/management state. Only the fast job's APScheduler execution messages are filtered; other jobs retain their logs. Shutdown closes the start gate before awaiting cancellation, and reconciliation cannot reopen it. Claim timing reads are inside exception handling.

Roles/bot refresh in preparation with enough headroom for the bounded edit and lease verification, using one 60-second TTL constant. A known Discord rate-limit retry time is persisted on the uncertain child and delays the next member. No uncertain edit is retried. Profile edits allow 150 seconds, inside a 200-second member_profiles worker budget and owned lease, so Hikari's configured rate-limit wait of up to 120 seconds can finish. Other sections retain 120 seconds. Uncertain edits are never retried automatically; the 210-second release drain remains above the member lease/budget.

Delta checks so far: 139 integrated focused backend plus seven new queue/edge checks; 13 real Mongo checks including the archived index fixture; 1,353 frontend tests, TypeScript/build, required war-reminder gate, and eight backend mutant kills (five new, three retained speed safety checks). Final full guarded backend passed 5,677 tests/55 skips/224 subtests; refreshed browser checks passed all four widths. Final 360/1440 overview, preview and result screenshots were visually reviewed. Five new backend and three new frontend mutants were killed, as were all three rerun speed safety mutants. Total unique behavioral mutation cases across the batch: 18. Requested Prettier checks pass. Prior failed fixture/build attempts are retained; they are not claimed as passing.

Rework fake-Discord/local-Mongo timings: 2 members 3.547 seconds, 25 members 76.758 seconds. The 25-member case has 25 target reads and three roles/bot refreshes with the safety margin; no live timing or edits.

## Prompt 88 review delta

The profile-only edit timeout is now 150 seconds, its worker budget is 200 seconds, and its storage-owned edit lease is 200 seconds with retention longer than that lease. Other queue sections retain their 120-second worker budget and ordinary profile writes retain their default 60-second lease. The 210-second release drain covers the extended lease. This allows Hikari's configured rate-limit wait of up to 120 seconds to complete instead of being cancelled after 20 seconds. An edit remains one-shot and an uncertain outcome is never automatically retried.

A real Hikari 2.6 client, pointed exclusively at a local fake Discord HTTP server and dedicated temporary Mongo, passes a 70-second 429 window followed by four confirmed members. A second case presses Stop during a local rate-limit wait: the current member completes and the other three remain untouched. All 15 real Mongo checks pass. The first fixture attempts used an invalid zero-second successful-response reset header, causing Hikari division-by-zero failures on subsequent members; a short HTTP diagnostic identified the fixture error, positive reset headers corrected it, and the final full real-client run passes. No live Discord timing is claimed.

The fast scheduler filter suppresses only INFO and lower records; warnings/errors remain. A real APScheduler job raising RuntimeError confirms the error stays logged. The startup docstring is restored. New run attribution depends on a viewed past run rather than an open history control, recovered polling clears its error, and the obsolete Import-button wording is removed.

Survivor regression coverage now includes non-profile budget-window reset, profiles uncapped and not charged to that budget, Started clearing the shutdown gate, prune on Stop, malformed created_at contained inside the request handler, retry_not_before only for profiles, and the list/attribution/pager/help-line states. Focused integration passes 139 backend checks plus 13 rework edge checks; full frontend passes 1,356 tests across 242 files, TypeScript/build and four-width isolated layouts pass, as does the war-reminder command. Final full guarded backend passed 5,683 tests/57 skips/224 subtests. Four new targeted mutations (hiding fast-job errors, missing window reset, counting profiles in the non-profile cap, and not clearing the Started gate) were killed. Requested Prettier checks pass. The rate-limit/mutation and ordinary two/25-member timing evidence is retained under `.local/p88-*`.

Final prompt 88 evidence: `.local/p88-full-be.log`, `.local/p88-full-fe.log`, `.local/p88-real-mongo-final.log`, `.local/p88-edges2.log`, `.local/p88-mutants.json`, `.local/p88-timing.log` and `.local/p88-layout`. Narrow/wide results were visually reviewed. Real Discord timing and browser focus after Back remain unverified; fixture flows clicked Back but did not assert its focus target. No production rename or notification was sent.

## Production release: nickname-review-1

PR133 was accepted in Claude entry 279 and released at 2026-11-01 11:50:31 UTC (06:50:31 EST), tag `nickname-review-1`, merge `a7004ed5f8e30b24377c7658525e14938d6b5d36`. Ruggie's approval is quoted in entry 274. Claude's post-release read-only smoke passed in entry 280.

The bot is PID 1326839/invocation `452c8e9118a5493f82401096dcc660df` at the tagged revision. Backend PID 1327025/invocation `1f75735ffa9c4a0d98e28bcaad298d55` runs from the immutable `backend/a7004ed5f8e30b24377c7658525e14938d6b5d36`; the atomic frontend points to the matching immutable release. One bot restart and one backend restart followed the required 210-second bot-stop lease drain. No rollback or production data restore occurred.

Fresh SQLite backup/integrity/test restoration and Mongo backup/dedicated local restore passed. Exact protected before/after state remained equal: 3,560 active strikes, 301 accounts, 582 strike profiles, 274 eligible entries and 479 member profiles, including streaks, replacement state, profile/settings digests and SQLite tables. The fresh 582-profile baseline supersedes older notes saying 581; existing state was preserved. Backup evidence is `.local/nickname-review-release/backup-result.json` and `backup-folder`, with protected snapshots before backup, pre-activation, stopped, after bot and after start. The owned restore Mongo was stopped and removed.

The `management_ready_work` partial index is present with kind/status/state keys and the reviewed pending-request/queued-run predicate. The production collection had 118 documents; the idle explain examined zero documents and zero keys and returned zero rows. This is a read-only observation, not a live workflow test. Code rollback may retain this compatible index and restores no data.

Clean tagged staging produced a byte-verified 1,936-file immutable backend and immutable frontend. Network-blocked imports passed under both runtime interpreters, including the actual bot Hikari 2.6.0. Mocked rollback plus successful activation and injected readiness-failure rehearsals passed. Readiness samples, startup journals, unrelated service configuration digests and public entry/affected feature hashes passed. Initial install/staging invocation retries happened before activation and caused no extra production restarts.

Public entry `index-D7-4dqtM.js` SHA256 `02a3b5b8dd9fca3cd5d5f572d53c21088a68a078904839579a9c12be89ffb856`; `MemberTimezones-D1xceJ-f.js` SHA256 `150dd2b2f46e76d87ca7f3d4a363da2c49290e8179af399f8c0d206e562688c2`; `MemberTimezones-DRqTiy2S.css` SHA256 `1b906c324b1d656bd900c5157eacd4f5b42c1318e44eff545fa887edaa1575f9`. Preserved roster, Strikes and Base bank hashes are recorded in `.local/nickname-review-release/live.json`.

Rollback assets retain bot `27b1bcc5b974b2cbc51b16fe4f98d834bd11c80d` independently from backend/frontend `3b22bf8608e61705c81370a06686ad97b6d95243`. The explicit guarded coordinator is `.local/nickname-review-release/activate.py`; do not execute it again for this completed activation. Ruggie alone performs live Import/Review/Rename testing. Codex sent no production Import, Review nicknames, Rename or Send action. Real Discord timing and Back-focus behavior remain unverified.

### Read-only smoke and limits

Claude smoke 280 passed at 2026-11-01 06:59:11 EST. Runtime symlinks, backend PID/cwd, bot PID and public entry hash matched LIVE 524. Member time zones at 360 and 1440 showed 1,447 members, the new entry controls/help line, no old panels or raw IDs and no overflow. The 1440 load made four API calls with no failures. Declaration at 360 in Lazy showed the saved channel, Ping 74 missing and No-ping test; the old paragraph was gone and Save channel stayed hidden until edited. Strikes chips remained intact, showing 131 of 564 without overflow. Nothing was pressed or written.

Claude's backend journal check over the prior 20 minutes found no traceback, error or warning. Claude could not read the bot journal; Codex separately read the current bot invocation: 473 records, no warnings, errors or tracebacks. The one fast-job INFO match was its startup registration, not repeated execution messages. Private evidence is `.local/nickname-review-release/bot-post-smoke-summary.json` and `bot-post-smoke.log`.

Not tested live: Review nicknames, Rename, Ping, real Discord timing or Back-focus behavior. The loading-time Declaration zeros observed by Claude are queued for a later polish PR; this release does not claim to fix them. PR134's test-only follow-up was accepted in 281 and merged as `eb6157d8bc9ae0f0c854d2aa4c1989d8f2b0c253`, closing the surviving profile-worker-budget mutant without application activation or restart.
