# Roster filler release

PR138 merged at b63c0c95f5433fc7f3933cdc88c64abff849b3c0, tagged
roster-filler-1. Claude accepted the final delta in entry295. Ruggie's release
approval was relayed in Claude entries287/288 and confirmed in295.

Staff can mark persistent roster fillers, undo marks, and manually place fillers
beyond capacity. Automatic planners keep fillers fixed and include their weight.
Declaration marks update the current view without a new live check; staff DM
links use the shared identity renderer. Swap and its Undo are API-only changes.
Worker/history timing logs add diagnostics; no live pacing improvement is claimed.

## Activation

The guarded retry completed on November 1, 2026. Bot1518318 invocation
8a56a5048887466b8c611c49dc97fcfe and backend1518593 invocation
5a23a56d342c4703af90848e047f4264 run the tagged revision. Frontend current points
to its immutable release. Public index-iSn7-bh_.js SHA256 is
82bb15ff18de0e84e20ad14dd1c132ad754234c84fdf955c9de8e23deaae4660.
Nineteen affected assets matched their manifest; config returned200. Current
bot/backend startup journals had no warnings, errors or tracebacks.

Fresh SQLite/Mongo backups passed isolated restore checks. Migration on a copy
preserved every existing SQLite row and added two empty mark/audit tables.
Exact protected state matched before/after the successful rollout:3,715 active
strikes,306 accounts, 583 strike profiles, 279 eligible entries, 479 member profiles,
plus streaks, profile/settings digests and protected SQLite rows. Tagged imports
passed with network disabled in both runtime interpreters. Immutable backend
archive bytes and mocked forward/rollback checks passed. Queue and lease checks
passed before stop and after the210-second drain.

The first attempt automatically rolled back when one roster-sync departure
changed the derived replacement departed flag. Comparison confirmed current
clan removal and departure metadata with a new observation time, while other
protected values matched. The old bot/backend a700 and frontend83cf5fc were
restored and verified. No database restore or legitimate state overwrite occurred.
A fresh backup retained the updated departure before retry. Across both attempts:
three bot starts (first upgrade, rollback, final upgrade), two backend restarts
(rollback, final upgrade), and two210-second activation drains. The inherited
first rollback did not add a separate210-second drain; the retry coordinator now
enforces that drain for any future rollback, verified with a mocked clock.

Evidence: .local/roster-filler-release, including attempt-1, live.json,
postverify.json, backup-retry.log, migration-rehearsal.json, protected snapshots,
departure-investigation.json and activation-retry.log. Retained rollback artifacts:
bot/backend a7004ed5f8e30b24377c7658525e14938d6b5d36 and frontend
83cf5fcbd03284e8c0bd880be67622f77c9376bc. Never restore data blindly.

## Validation and limits

5,707 backend tests passed, 58 skipped, 224 subtests; 1,392 frontend tests in 249 files;
TypeScript/build;16 real Mongo fixtures;11 final delta mutations plus15 prior
rework mutations caught; required war-reminder check213 backend/1skip plus35
frontend/build. Twelve fixture layouts at320/360/390/1440 with26/65/125 accounts
passed. Narrow/wide and sample65/125 screenshots were inspected. Formatting and
diff checks passed.

Claude read-only smoke296 passed: runtime revisions and public hash matched.
Declaration at360 showed the expected missing/extras counts, collapsed neutral
Low TH lists, shared identities, staff DM links and unticked filler controls.
Build roster at1440 loaded without failed requests or overflow. No raw IDs were
visible. No filler was marked, so the live +N filler state remains fixture-only.
A first Declaration extras read failed once; status was not captured and reload
returned200 in3.1s. Cause remains unproven. A push-reminder TimeoutError was on
the old backend before the switch, not the new invocation. Claude did not test
live mark/Undo, Details checkbox, DM navigation or Discord timing. No agent production marks, roles,
nicknames, Import, Review, Rename, messages or DM clicks were performed. Real DM
navigation and real Discord timing remain untested. Automatic rollback was
exercised by the first attempt; no database restore was performed.
