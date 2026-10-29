# Dashboard backend releases

## Pending Member signup flow

Ruggie approved a read-only season projection of `signup_deadline` and `placements_by`, from the bound Mongo campaign with a five-minute process cache. UTC-aware arithmetic adds exactly 24 elapsed hours, including DST weekends; missing/unavailable campaigns return null. No schema or write-path change. This batch needs a separately authorized isolated dashboard backend release **and bot release** for Check my signups (see `cwl-discord-member-release.md`). This review does not activate either service.

Since the Clan settings deployment on 2026-10-27 (2026-10-28 UTC), `wu-cwl-demo-web.service` runs from an isolated git archive, never the shared workspace. A workspace edit or frontend build cannot change the deployed backend on restart.

## Layout and invariants

- Current release: `/home/ruggie/.local/share/wu-dashboard/backend/2279c95c3bc62ac74447c4a66a0a924dde45bda4/`, tag `roster-images-1`.
- Rollback: `/home/ruggie/.local/share/wu-dashboard/backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf/`; paired frontend rollback `190313b81f4c8373dc08f5a63fca966c6caffab2`.
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

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py 4404c3672872ebff706519402efa4ee9940d3a60
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
readlink /proc/$(systemctl --user show -p MainPID --value wu-cwl-demo-web.service)/cwd
```

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
