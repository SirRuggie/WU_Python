# Nickname import and review: prompts 83–84

## Production diagnosis

Read-only request evidence: the first Import started at 2026-11-01 08:51:17.921325 UTC and became uncertain at 08:52:58.617835, after 100.6965 seconds. Its message is the import-specific wrapper, which encloses directory fetch and serial profile writes in a 100-second timeout. The bot journal shows the management poll occupied throughout, with overlapping scheduler ticks skipped, and completion at 03:52:58 EST. The old handler did not log the underlying exception; the request timing identifies the budget boundary, while the exact contribution of Atlas latency cannot be reconstructed. No claim is made that other Mongo timeouts caused this request.

Ruggie's explicit retry started at 08:54:18.358778 UTC and finished at 08:55:14.400688, after 56.0419 seconds: 479 known, 44 unknown, 887 without a zone, 149 imported, 330 preserved, zero conflicts and 37 bots. This is evidence of resumable preserved progress. Codex did not retry either action. Sanitized receipt/timing evidence and journal are retained under `.local/p83-evidence` in the worktree.

## Implementation

Import validates the bounded directory, reads existing profiles in one batch and skips prior staff/Warrior/imported decisions. Eight workers reuse the existing per-member write owner, leases, fresh revision/source checks and CAS. TaskGroup cancels and drains siblings on failure; committed profiles remain. The storage owner also prevents an imported decision from displacing an earlier import. Partial confirmed counts are retained in the uncertain receipt and future import timing/cause/counts are logged. This changes worker code and needs one bot restart after acceptance, with the required 210-second lease drain.

The only entry point is Review nicknames: Import then a fresh token/revision preview, with no rename until confirmation. Terminal uncertain/failed imports get a fresh request ID on an explicit retry; an unconfirmed transport outcome retains its identity. Reusing an old ID returns its original durable receipt and does not rerun the queue. Errors are shown once. The profile-only import message says: Import stopped early. No nicknames changed. Press Import again to continue.

Preview classification is a pure domain helper: Will change, Needs flag, No time zone, Already done, Can't rename and optional Check name. Bots are excluded. Filters reuse the extracted Strikes chip implementation; search and 25-row pages retain selection. The sticky count and submitted IDs use the same selection, and hidden selections can be shown. Check name starts unticked. Run manifests, token/revision checks, one-at-a-time worker, Stop and uncertain nickname outcomes are preserved. Past runs load only on request. The directory, member editor and Warrior workflow are unchanged.

## Verification checkpoint

Focused backend: 65 passed, including a scaled 1,447-member Atlas-latency budget and partial failure/rerun without duplicate writes. Focused frontend: 32 passed; initial full frontend 1,346 passed across 242 files. TypeScript/build passed after an obsolete test import was removed. Four-width isolated browser flow (320/360/390/1440) passed, including the unchanged editor, import-before-preview, bots excluded from counts, pagination, hidden selection, sticky action visibility, Stop, lost permission, no overflow and 44px targets. Narrow/wide screenshots were visually reviewed.

Remaining before READY: final integrated frontend, full guarded backend, real Mongo lease/CAS/import verification and required mutation checks. Isolated UI fixture writes are fake transport, never live Discord nickname edits. No production Import, Standardize or Rename was pressed. No deployment is claimed by this review checkpoint.
