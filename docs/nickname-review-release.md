# Nickname import and review: prompts 83–86

## Production diagnosis

Read-only request evidence: the first Import started at 2026-11-01 08:51:17.921325 UTC and became uncertain at 08:52:58.617835, after 100.6965 seconds. Its message is the import-specific wrapper, which encloses directory fetch and serial profile writes in a 100-second timeout. The bot journal shows the management poll occupied throughout, with overlapping scheduler ticks skipped, and completion at 03:52:58 EST. The old handler did not log the underlying exception; the request timing identifies the budget boundary, while the exact contribution of Atlas latency cannot be reconstructed. No claim is made that other Mongo timeouts caused this request.

Ruggie's explicit retry started at 08:54:18.358778 UTC and finished at 08:55:14.400688, after 56.0419 seconds: 479 known, 44 unknown, 887 without a zone, 149 imported, 330 preserved, zero conflicts and 37 bots. This is evidence of resumable preserved progress. Codex did not retry either action. Sanitized receipt/timing evidence and journal are retained under `.local/p83-evidence` in the worktree.

## Implementation

Import validates the bounded directory, reads existing profiles in one batch and skips prior staff/Warrior/imported decisions. Eight workers reuse the existing per-member write owner, leases, fresh revision/source checks and CAS. TaskGroup cancels and drains siblings on failure; committed profiles remain. The storage owner also prevents an imported decision from displacing an earlier import. Partial confirmed counts are retained in the uncertain receipt and future import timing/cause/counts are logged. This changes worker code and needs one bot restart after acceptance, with the required 210-second lease drain.

The only entry point is Review nicknames: Import then a fresh token/revision preview, with no rename until confirmation. Terminal uncertain/failed imports get a fresh request ID on an explicit retry; an unconfirmed transport outcome retains its identity. Reusing an old ID returns its original durable receipt and does not rerun the queue. Errors are shown once. The profile-only import message says: Import stopped early. No nicknames changed. Press Import again to continue.

Preview classification is a pure domain helper: Will change, Needs flag, No time zone, Already done, Can't rename and optional Check name. Bots are excluded. Filters reuse the extracted Strikes chip implementation; search and 25-row pages retain selection. The sticky count and submitted IDs use the same selection, and hidden selections can be shown. Check name starts unticked. Run manifests, token/revision checks, one-at-a-time worker, Stop and uncertain nickname outcomes are preserved. Past runs load only on request. The directory, member editor and Warrior workflow are unchanged.

## Rename speed and declaration copy

Read-only production receipts measured the owner's two-member run at 68.958 seconds, rather than the earlier code-only estimate of 40–50 seconds. The first child waited 9.379 seconds, the second was created 22.069 seconds after the first finished, and the parent finished 14.680 seconds after the last child. This identifies scheduler/cursor delays in addition to Discord and storage work. No production retry or nickname write was performed by Codex.

A lightweight one-second pending check drives the existing atomic request claim and single lane; the ten-second maintenance tick remains the fallback. One owned background task avoids overlapping scheduler jobs, and shutdown cancels and drains it. Durable child completion advances the cursor immediately, schedules the next child three seconds after completion, and finishes the parent without an extra tick. Restart uncertainty is retained and never replayed automatically. Other queue actions retain their transport and authorization paths.

Roles and the bot member are cached for at most 60 seconds in a bounded per-run cache. Each actual edit reads the target and actor freshly, checks current access, hierarchy and exact old nickname, verifies the owned profile lease after preparation, then makes one bounded Discord edit. Slow preparation that expires the lease cannot edit. Discord rate-limit waits are awaited; uncertain requests are not automatically retried. Timing logs cover claim delay, authorization, Discord reads/edit and profile save.

The run replaces review immediately on confirmation, disables duplicate submissions, polls at one second only while active, and opens on Changed. Its progress and result rows contain only the selected members, including older manifests that recorded unselected skips. Stop and partial/uncertain outcomes remain visible.

The separate prompt 85 frontend commit removes the Declaration ping paragraph, adds one confirmation line about finishing despite lineup changes, and shows Save channel/Discard only for an edited channel. The protected ChannelCombobox and its existing hint remain unchanged; no new hint prop was added.

## Validation and limits

The production evidence cannot reconstruct the original import's underlying exception because the old handler did not log it. Fixture timings below use fake Discord transport and a dedicated temporary local MongoDB, not live delivery. No production Import, Standardize, Rename or Send was pressed. No deployment is claimed by this implementation review.

Final validation totals and fixture measurements are recorded with the READY handoff after the integrated gates finish. Earlier failed checks were corrected before READY; their logs remain in the worktree.

| Fixture | Members | Elapsed | First edit |
|---|---:|---:|---:|
| before | 2 | 50.739 s | 10.335 s |
| after | 2 | 3.431 s | 0.221 s |
| after | 25 | 76.636 s | 0.224 s |

The 25-member fixture refreshes roles and the bot member twice across its minute-long cache boundary, with exactly one fresh target read per member. Its edit gaps remain above three seconds. Baseline source is the pre-speed commit aeef3fe; only the after cases were rerun after the final safety fix.
