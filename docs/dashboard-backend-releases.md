# Dashboard backend releases

## Weight-range-1 — October 30, 2026

PR [#64](https://github.com/SirRuggie/WU_Python/pull/64), tag `weight-range-1`,
released frontend and backend `23235ccf2671dfe5675f0bc98d38ab11a011ab09`.
The bot stayed at `b517afd46ecfa9cc08488798eba53393ed5b649f`, PID 2920748,
with the same invocation and no restart. Backend PID 2951316 ran from the
matching isolated archive; readiness reached two consecutive config 200s after
six attempts, and its current-invocation journal was clean. Anonymous commands
returned 401. These are release-time observations, not a promise that later
frontend releases use the same revision.

The index and 36 selected public assets matched the manifest, including the
owning RosterWorkspace JS/CSS chunks. Entry `index-BKbAuOsh.js` SHA-256:
`35683c3f84401a77d6ecf60031a9c33bb25ef25111809ba19c1161073ade1f5e`.
Tagged checks passed: 4,844 backend tests, 21 skipped, 153 subtests; 914 frontend
tests; TypeScript/build. Fourteen accepted mutations were killed. Claude's
read-only 360px smoke (handoff 92) confirmed quick picks, descending-weight
Compare, and Jujupon at 179k inside Lazy.128's 172–179 range. No assignment,
lock, publication or live Discord test writes were performed.

Durable backup: `.local/weight-range-1-backup-20261030T114234Z/dashboard.sqlite3`
under the repository, 1,282,048 bytes, SHA-256
`732fd66b55a776c1b0a61c84157b3038a8c923575b7b4b1754185f1c0bbe7b98`.
Integrity and all 58 table counts passed; protected pre/post digest remained
`34449fa23beafcae682188bf3d7cfddaf47b12a455f10d433119288a004cc4f7`.
Evidence: `/tmp/wu-weight-range-release/{live.json,preflight.json,activation.log,independent-review.md}`
and the durable backup's `verification.json`/`before.json`.

The scratch verifier initially required standalone Compare/ClanSettings assets,
although both live in RosterWorkspace. It was corrected to check the owning
bundle; independent mocked missing/corrupt-bundle checks passed before actual
public verification. The installed staging helper still failed on nested tour
assets; a reviewed recursive finalizer completed staging without editing the
installed helper. Rollback restores **frontend and backend to b517afd only**;
the bot remains unchanged. Use the guarded manual procedure below.

## Trigger-delete-1 — October 30, 2026

PR [#63](https://github.com/SirRuggie/WU_Python/pull/63), tag `trigger-delete-1`,
released frontend, backend and bot at
`b517afd46ecfa9cc08488798eba53393ed5b649f` after direct user approval.
Backend PID 2920362 ran from the isolated archive; config returned two consecutive
200s after six attempts. Bot PID 2920748 was on clean `main`, with startup and
gateway readiness confirmed. Both current-invocation journals were clean;
anonymous commands returned 401. Public entry `index-LzSl5cD4.js` SHA-256 was
`693fe2b517b88b25c51ce8681d588bed46b33e54784b9c070cbd53868b5af392`;
TextCommands-2Qkug76B.js was
`900a2f44f333b8cd28975af5ada128e3768abbebf2bc6e69a13056536b8e8d5e`.
Checked entry/feature assets matched the release manifest.

Tagged checks passed: 4,839 backend tests, 21 skipped, 133 subtests; 908 frontend
tests; TypeScript/build. Claude's read-only smoke (handoff 90) confirmed the
checked Delete the trigger message control for `!lazy`, runtime revisions and
clean journal. Codex and Claude sent no live trigger; Ruggie's own `!lazy` test
remains separate from this evidence.

Durable backup: `.local/trigger-delete-1-backup-20261030T111258Z/dashboard.sqlite3`,
1,282,048 bytes, SHA-256
`911b4ef0774226df384deffda42e43203db53afd788a5c19d521e5e9aa8dd9c0`.
Integrity and all 58 table counts matched. Protected signups/assigned/locks
were Main 26/22/22 and Lazy 126/117/101; publication remained version 1 withdrawn.
Pre/post digest stayed
`5b32f1132ecf3aced3b37fba18504e4861299d1262e6525f224b45c327dd8e16`.
Ten Mongo collections were verified; command definitions/history were 3/10 and
strike_records 7,722. Protected definitions, history and policy were unchanged.
Evidence: `/tmp/wu-trigger-delete-release/{live.json,runtime-proof.json,baseline.json,activation.log}`
and `attempt-1/`; durable backup verification accompanies the database.

The first activation was rolled back across all three code layers because the
verifier included a prior bot shutdown cancellation in its journal window.
Readiness was corrected to the new systemd InvocationID, with three focused
checks; the retry passed. An import-module typo was also corrected, and 199
generated pyc files were removed only from the inactive new archive before
exact-archive verification. Nested assets required the same reviewed recursive
staging fallback. These tooling errors are not hidden as a first-pass success.

### Guarded manual rollback for trigger-delete and weight-range

Run only with rollback authorization. This procedure uses permanent artifacts,
not `/tmp` coordinators. It refuses unexpected frontend/backend/bot revisions;
if a later frontend release is active, roll that release back through its own
procedure first. Preserve all database changes and retained assets. Never
restore SQLite or Mongo for a code rollback.

Choose **one** release in the same shell, then run the common guarded block:

```bash
# Weight-range: frontend/backend rollback; bot stays b517afd.
release_sha=23235ccf2671dfe5675f0bc98d38ab11a011ab09
rollback_sha=b517afd46ecfa9cc08488798eba53393ed5b649f
rollback_bot=no
```

```bash
# Trigger-delete: all three code layers roll back to strike-tracking-2.
release_sha=b517afd46ecfa9cc08488798eba53393ed5b649f
rollback_sha=6a2f8d735d1ee6e5ea912be10d3bba75a143ce09
rollback_bot=yes
```

```bash
(
set -eu
release_root=/home/ruggie/.local/share/wu-dashboard
test "$(readlink -f "$release_root/current")" = "$release_root/releases/$release_sha"
test "$(systemctl --user show wu-cwl-demo-web.service -p WorkingDirectory --value)" = "$release_root/backend/$release_sha"
test "$(sudo -n -u botrunner git -C /home/botrunner/wu-bot rev-parse HEAD)" = b517afd46ecfa9cc08488798eba53393ed5b649f
test "$(sudo -n -u botrunner git -C /home/botrunner/wu-bot branch --show-current)" = main
test -z "$(sudo -n -u botrunner git -C /home/botrunner/wu-bot status --porcelain)"
test -d "$release_root/releases/$rollback_sha"
test -d "$release_root/backend/$rollback_sha"
dropin_dir=/home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d
preserved_before=$(find "$dropin_dir" -maxdepth 1 -name '*.conf' ! -name release.conf -type f -exec sha256sum {} + | sort)
"$release_root/switch-release.py" "$rollback_sha"
printf '[Service]\nWorkingDirectory=%s/backend/%s\n' "$release_root" "$rollback_sha" > "$dropin_dir/release.conf"
test "$preserved_before" = "$(find "$dropin_dir" -maxdepth 1 -name '*.conf' ! -name release.conf -type f -exec sha256sum {} + | sort)"
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
if [ "$rollback_bot" = yes ]; then
  sudo -n -u botrunner git -C /home/botrunner/wu-bot reset --hard "$rollback_sha"
  sudo -n systemctl restart wu-bot.service
fi
)
```

Keep `frontend-routing.conf` and `storage-guard.conf` unchanged; do not remove
`release.conf` or restart from the workspace. Afterward verify two consecutive
public `/api/cwl/config` 200s, anonymous commands 401, actual `/proc/<PID>/cwd`,
and current-invocation journals. Check bot startup/gateway readiness if restarted;
otherwise verify its PID and InvocationID are unchanged. Fetch the public index
and its entry/affected feature assets and compare bytes/hashes with the retained
target release, not just the symlink. Recheck protected data against the rollback
preflight snapshot; stop and investigate discrepancies without restoring data.

## Strike-tracking-2 — October 30, 2026

`strike-tracking-2` (`6a2f8d735d1ee6e5ea912be10d3bba75a143ce09`, PR #61)
was the frontend, isolated backend, and bot revision at that release. The backend ran
from `backend/6a2f8d735d1ee6e5ea912be10d3bba75a143ce09`; the frontend
`current` symlink pointed to the matching release, and the bot was at the same
clean main SHA. The old frontend/backend/bot rollback targets are respectively
`4f57d6e73941d3adc3b3223611927081bf794df9`,
`f95830b5b774ba34b29f4756a1cc9e3747148f1b`, and
`16cc79e7db39e3aaadf99c99117994b9103a47e8`.

The clean tagged build and isolated backend imports passed; public index and
32 selected asset hashes matched the staged manifest. Backend readiness reached
two consecutive 200s; anonymous tracking returned 401. The bot journal recorded
`[strikes] pass: 25 clans, 0 wars finalized, 13 behind`. Authenticated read-only
tracking showed 12 On track / 13 Behind / 0 private / 0 error, and Claude's
360px smoke passed. Durable verified backups are in
`.local/strike-tracking-2-backup-20261030T035630Z/` (SQLite and protected Mongo).
Protected SQLite rows and the Mongo strike ledger/settings/leaves matched before
and after; six profile policy records were unchanged. Ten war snapshots were
created by normal monitoring. No import previews were active at the release
gate, so zero were modified; no gap backfill or live test messages ran.
The frontend staging helper's nested-asset defect remains a [Later item](strike-system.md#later--non-blocking-review-items).
Detailed release evidence is in `/tmp/wu-strike-tracking-release/LIVE.md`.

Rollback is a code-only operation. Verify the bot is still on clean `main` at
the release SHA before resetting it; keep the backups and all database changes.
The retained release coordinator performs these checks and verifies old public
hashes/readiness:

```bash
'/nvme0n1-disk/Projects/Bot - Warriors United/.venv/bin/python' /tmp/wu-strike-tracking-release/release.py rollback
```

If that scratch coordinator is unavailable, use the retained artifacts with
the same guard and steps:

```bash
(
set -eu
test "$(sudo -n -u botrunner git -C /home/botrunner/wu-bot rev-parse HEAD)" = 6a2f8d735d1ee6e5ea912be10d3bba75a143ce09
test "$(sudo -n -u botrunner git -C /home/botrunner/wu-bot branch --show-current)" = main
test -z "$(sudo -n -u botrunner git -C /home/botrunner/wu-bot status --porcelain)"
test -d /home/ruggie/.local/share/wu-dashboard/releases/4f57d6e73941d3adc3b3223611927081bf794df9
test -d /home/ruggie/.local/share/wu-dashboard/backend/f95830b5b774ba34b29f4756a1cc9e3747148f1b
/home/ruggie/.local/share/wu-dashboard/switch-release.py 4f57d6e73941d3adc3b3223611927081bf794df9
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/f95830b5b774ba34b29f4756a1cc9e3747148f1b\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
sudo -n -u botrunner git -C /home/botrunner/wu-bot reset --hard 16cc79e7db39e3aaadf99c99117994b9103a47e8
sudo -n systemctl restart wu-bot.service
)
```

Recheck dashboard readiness, runtime cwd, bot startup, and old public asset
hashes. Do not restore either database during code rollback.

## Owner prank released — 2026-10-29

`owner-prank-1` (`f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PR #46) was the previous isolated backend. Ruggie explicitly approved its additive state table, owner-only endpoints/private assets, private configuration and dashboard restart. Existing data is preserved; durable notification claims precede background transport and uncertain delivery is never automatically retried. Bot was unchanged by that release.

Backup/migration, effective paths/imports, readiness, journal, 97 public hashes and protected counts passed. Main22/18/18 and Lazy116/92/73 unchanged. Claude infrastructure smoke passed; owner experience and live DM delivery not claimed. The PWA Tasks landing-page start bug is a separate frontend fix (handoff42). See CLAUDE.md for complete rollback commands and evidence.

## Member tour + timing released — 2026-10-29

`member-tour-1` (`16cc79e7db39e3aaadf99c99117994b9103a47e8`) runs from the isolated backend archive and matching frontend; bot is at the same SHA. Background timing refresh fixes the request timeout, with 5.8s refreshes every five minutes. Readiness, journal, public hashes and protected counts passed. Smoke passed with defects: wrong campaign month and phone tour spotlight, tracked in handoff prompt 07; keep live. Backup `.local/member-tour-backup-20261029T122118Z/dashboard.sqlite3`; evidence `/tmp/wu-tour-release/live-proof.json`. Rollback all code layers to `5539cba3c800d91372fd5c6adc62564a758ddff4`, without restoring data.

## Member signup released — 2026-10-29

`member-signup-1` at `5539cba3c800d91372fd5c6adc62564a758ddff4` deployed with approved dashboard and bot restarts. Read-only UTC-aware timing adds 24 elapsed hours, including DST weekends; no schema/write-path change. Imports, two consecutive config 200s, public hashes and unchanged protected counts passed. Backup `.local/member-signup-backup-20261029T044244Z/dashboard.sqlite3`; evidence `/tmp/wu-member-signup-release/retry-live-proof.json`. Claude web and Ruggie Discord smoke passed. Date-line defect: fix in progress (prompt 01): Mongo exceeds the current request-path 1.5-second budget.

Since the Clan settings deployment on 2026-10-27 (2026-10-28 UTC), `wu-cwl-demo-web.service` runs from an isolated git archive, never the shared workspace. A workspace edit or frontend build cannot change the deployed backend on restart.

## Layout and invariants

- Latest backend recorded here: `/home/ruggie/.local/share/wu-dashboard/backend/23235ccf2671dfe5675f0bc98d38ab11a011ab09/`, tag `weight-range-1`; bot remains `b517afd46ecfa9cc08488798eba53393ed5b649f`.
- Its rollback backend is `/home/ruggie/.local/share/wu-dashboard/backend/b517afd46ecfa9cc08488798eba53393ed5b649f/`; paired frontend and bot rules are listed above.
- Both are clean `git archive` exports. Current release imports were verified from the isolated directory using the existing virtualenv.
- Interpreter remains `/nvme0n1-disk/Projects/Bot - Warriors United/.venv/bin/python`; do not replace shared dependencies during an application release.
- Environment files remain at their absolute existing paths: workspace `.local/cwl-web.env` and `/home/ruggie/.local/share/wu-dashboard/frontend-routing.env`. The database path is absolute; routing sets `CWL_WEB_STATIC_DIR=/home/ruggie/.local/share/wu-dashboard/current`.
- The original service unit stays unchanged. Preserve `frontend-routing.conf` and `storage-guard.conf` byte-for-byte. The only new drop-in is `~/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf`, containing `[Service]` and one `WorkingDirectory=` line.
- Never restart from the workspace, copy the workspace into a release, or remove `release.conf` as a rollback.

## Stage and activate

Back up the database using SQLite's backup API and verify integrity and table counts. Record signups, assignments, locks by season/pool, publication versions and every lineup-rule row. Retain rollback assets; never restore the DB merely to roll back code.

Create a clean tagged frontend checkout; run `npm ci` inside `web/cwl` and verify `git status --porcelain` is empty before invoking `stage-release.py`. Do not symlink workspace `node_modules`: the symlink is untracked and staging rejects it.

Export the approved tag to a new `backend/<full-sha>/` directory with `git archive`. Create/verify the rollback archive before switching. Verify all environment filesystem paths are absolute and imports resolve from the release, with the existing absolute virtualenv. Stop if any path is relative.

Write only `release.conf` with the new `WorkingDirectory`. Run daemon-reload, inspect `systemctl --user show -p WorkingDirectory,DropInPaths wu-cwl-demo-web.service`, switch the frontend, and restart immediately; do not pause between these steps.

Prove `/proc/<MainPID>/cwd`, active service and clean restart journal. Verify public entry and feature hashes against the frontend manifest. Perform authenticated read-only smoke: open Clan settings, open and close a clan panel without saving, and render Compare cards. Never Save or Publish during smoke. Compare protected counts and lineup rules exactly with the snapshot.

## Rollback both on failure

Triggers include startup/journal failure, wrong cwd or public hashes, failed smoke, or protected-data mismatch. Do not overwrite data to resolve a count mismatch; investigate legitimate concurrent edits separately.

Use the [guarded release-specific commands](#guarded-manual-rollback-for-trigger-delete-and-weight-range)
for weight-range or trigger-delete, after rolling back any later frontend-only
release. Strike-tracking-2 and older targets remain historical; do not apply
them directly to an unexpected newer runtime.

Re-check service health, cwd, public hashes, protected counts and rules after rollback. A full rollback switches both code layers, not just the frontend. Existing tabs need a reload.

## Finalize read metadata (Ruggie-approved backend extension)

Deployed 2026-10-28 as `finalize-1` (`1a8b035461ec46fba60f6ed4808111d3c67d87cf`) from an isolated release directory with a service restart. The draft response adds
`last_publication` (latest version including withdrawn, publication/withdrawal dates
and joining instructions) and `next_version` (the publish path's season-scoped
MAX + 1). `published` retains its active-only meaning. This is read-only: no schema
or publication/withdrawal write-path change. Scripted checks passed and protected data matched before/after. Authenticated metadata read and click smoke remain with Claude, as approved by Ruggie; the release remains live. Backup: `.local/finalize-backup-20261028T040608Z/dashboard.sqlite3`.

## Deployed CWL flow backend release — S1/S2/S3

Ruggie approved these changes for the CWL flow batch (2026-10-28): S1 atomically carries the most recent nonempty season's active lineup and rules into a new, empty season; S2 adds optional strict-boolean `expected_signup_open` compare-and-set protection; S3 adds editor-authorized `GET /api/cwl/clans/lookup?tag=…` using the existing provider and tag parser, returning only tag/name without database writes. Invalid tags return 400, missing clans 404. Existing add POST remains the save path. No schema change.

Deployed together on 2026-10-28 at `61290a4ce2b87611119483d6376b879a675aeb81` (`cwl-flow-1`) from a clean archive, with the approved service restart. Public config readiness passed twice consecutively before A4; public assets, 401 authorization checks, cwd and protected data matched. Claude's read-only click smoke passed. Backup: `.local/cwl-flow-backup-20261028T145938Z/dashboard.sqlite3`. Never restart from the workspace. S4 was declined: the frontend confirmation omits the copied count before creation and uses S1's response count afterwards.

## Deployed Announcements B1 release

Ruggie approved one read-only backend extension: `_delivery()` in `cwl_web/manage_bridge.py` exposes the existing send record's `publication_version` as an integer or null. No schema, new endpoint or write-path change.

Deployed 2026-10-28 as `announcements-1` (`73fe3fa92d8d0d89491be6e350c130b9d375aaaf`, PR #32), with a clean frontend build, isolated backend archive and approved service restart. Only `release.conf` changed; `frontend-routing.conf` and `storage-guard.conf` remained byte-identical. Imports, MainPID cwd, active service and restart journal passed. Public config returned two consecutive 200s after 5.53 seconds (transient startup 502s before readiness); public entry/feature hashes matched the manifest, and unauthenticated Manage read returned 401. Protected SQLite data, including Manage bindings, matched exactly. No scripted send/test-send/bind/save or Mongo access; normal backend startup retained its existing restore behavior.

Backup: `.local/announcements-backup-20261028T205112Z/dashboard.sqlite3`; integrity OK, all 54 table counts matched. Previous frontend `4404c3672872ebff706519402efa4ee9940d3a60` and backend `61290a4ce2b87611119483d6376b879a675aeb81` remain the rollback pair. Claude's read-only 360px smoke PASSED, relayed by Ruggie: entry `index-Dn86Au-2.js`, backend, hidden status, real channels/roles, Preview and Edit open/close with no unsaved change; zero write requests, no errors, clean journal. Release complete.

## Deployed roster images batch

Released as `roster-images-1` (`2279c95c3bc62ac74447c4a66a0a924dde45bda4`, PR #35). Six imports resolved from the archive; effective absolute paths verified. Only release.conf changed; routing/storage drop-ins preserved. Readiness returned 200 twice at 4.41/5.53 seconds after transient startup 502s. PID 1639904/cwd, journal, public hashes and both anonymous 401s passed. Backup `.local/roster-images-backup-20261029T030832Z/dashboard.sqlite3`, integrity OK; migration dry run preserved all 54 old table counts, as did production activation. Three image tables empty; no scripted Discord calls. Main 19/18/18 and Lazy 95/92/73 unchanged. New tables remain on rollback.

Claude read-only 360px smoke PASSED: Announcements loads, image reads 200, public asset hash/runtime correct, zero writes. Hidden November meant channel pickers, status labels and Preview were not visible or checked live. The Declaration restart request-loop observation and hidden channel-configuration limitation are recorded in the redesign Later list, not claimed fixed.

Ruggie approved the roster-image channel/post schema, per-clan post/update/drop endpoints, opt-in rate-limit metadata, and durable **text-only** request receipts. Release requires a clean tagged backend archive, release.conf WorkingDirectory switch, restart and the usual readiness gate. The implementation checkpoint leaves production on verified Declaration frontend `190313b` and backend `73fe3fa`.

Additive tables: `roster_image_channels`, `roster_image_posts`, `roster_image_requests`. Never store PNG bytes in SQLite/audit logs. Retry rendering uses the immutable publication and frozen metadata. Preserve these tables on code rollback; never restore a database to roll back code. Uncertain posts require a duplicate warning; uncertain edits PATCH the saved message ID. No automatic resend or Discord DELETE.

Use normal backup/integrity/count evidence, retain both rollback targets, then verify public assets, runtime cwd, readiness and protected counts. Fake-Discord tests are not proof of live delivery; no live test send is authorized by the implementation batch.

Prompt 07 tour/deadline hotfix (not yet released): member timing reads the existing
campaign one month before the CWL binding. No schema or write-path change. Deploy
its backend from an isolated tagged release only after approval; current runtime
remains member-tour-1 / 16cc79e.
