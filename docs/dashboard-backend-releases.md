# Dashboard backend releases

Since the Clan settings deployment on 2026-10-27 (2026-10-28 UTC), `wu-cwl-demo-web.service` runs from an isolated git archive, never the shared workspace. A workspace edit or frontend build cannot change the deployed backend on restart.

## Layout and invariants

- Current release: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`, tag `cwl-flow-1`.
- Rollback: `/home/ruggie/.local/share/wu-dashboard/backend/1a8b035461ec46fba60f6ed4808111d3c67d87cf/`.
- Both are clean `git archive` exports. All 168 tracked files under `cwl_web/` and `utils/` were byte-compared with their commits.
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
# Frontend rollback:
/home/ruggie/.local/share/wu-dashboard/switch-release.py 1a8b035461ec46fba60f6ed4808111d3c67d87cf
# Backend rollback (preserves frontend-routing.conf and storage-guard.conf):
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/1a8b035461ec46fba60f6ed4808111d3c67d87cf\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user show -p WorkingDirectory,DropInPaths wu-cwl-demo-web.service
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

## Pending Announcements B1 release

Ruggie approved one read-only backend extension: `_delivery()` in `cwl_web/manage_bridge.py` exposes the existing send record's `publication_version` as an integer or null. No schema, new endpoint or write-path change. The Announcements batch therefore requires an isolated `backend/<sha>/` release plus `release.conf`, daemon-reload and restart when deployment is separately approved. Never restart from the workspace. After activation, poll the public `/api/cwl/config` until two consecutive 200 responses (maximum 90 seconds) before HTTP verification. Retain the prior backend and frontend rollback targets. Nothing in this checkpoint activates a release.
