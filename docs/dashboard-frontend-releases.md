# Dashboard frontend releases

## No-war-strikes-1 — October 30, 2026

Frontend `73eda11a1e883b711bc40494f023b4d87efd5a6b` is live and Claude smoke 131 passed.
Entry `index-BipoOtjv.js`, hash `bea1b2f126251a5c63bf144354f930b6a8138f288540f32c9413277484e80297`.
Clean tagged npm ci/build and 1,034 frontend tests passed. See the backend release
record for coordinated rollback, backup/count evidence and the approved correction.


## Moderation-logs-1 — October 30, 2026

Latest verified frontend: `c494022e924994435496c3e4f0722eb781460380`, tag
`moderation-logs-1`, [PR #68](https://github.com/SirRuggie/WU_Python/pull/68).
Bot first, then backend readiness, then frontend switch: all three layers reached
this revision. Claude read-only smoke 98 passed at 360px; no Send test was used.
The prior back-to-top release below is now the retained frontend rollback target.

The public index SHA256 was
`fed368901df9253bceb08651ebb303c72b4029fd86eb3093aeda42b559de195e`.
Entry `index-D5Y54of8.js`:
`9758d884cdd8b31f72f7eb764827e07ff4e8418d908765ee796d6636e83a2f8a`.
Owning moderation/history bundle `ModerationWorkspace-Bd-OU08t.js`:
`13731dd4da39867082c733c089b067c9f183bd2ebd8cbbc805857ed57dcfaca8`;
CSS `ModerationWorkspace-9PLgs2ZU.css`:
`3fdb28e45923aa80dba4d9b5a20faa11f7ba0301b0dba250082be6196e9e3d51`.
The public index and 34 selected assets matched; MemberActivityHistory is bundled in
ModerationWorkspace, not a standalone chunk. Clean tagged checks passed 933
frontend tests, TypeScript and build; 120 frontend files were staged, including
nested tour assets via the reviewed recursive finalizer.

Backups, exact four-event routing parity, protected data, runtime checks and
[durable guarded rollback commands](dashboard-backend-releases.md#guarded-moderation-rollback)
are recorded with the backend release. Rollback targets are frontend a803108,
backend 23235cc and bot b517afd; restore/verify old frontend and backend before
old bot. A staff save using inheritance requires renewed routing review before
bot downgrade. Never restore data. Claude observed three of eight avatar reads
returning 503 with initials fallback; prompt 33 item 6 remains open.


## Back-to-top-1 — October 30, 2026

Frontend at the 08:30 smoke checkpoint: `back-to-top-1`, PR #65,
`a8031084eed09ee89b8063828d4bc2c5d40cc628`, activated after the releases below.
Public `index-zCmtmF3Z.js` SHA-256
`9f28a7a1b9aebbe14da09d48a5b2f94f3ee42ea9b7b5668da11929d4b774b5a0`
matched in `/tmp/wu-back-to-top-release/live.json`. Claude's read-only smoke 93
passed at 360px: hidden at the top; after three viewports down and 200px up,
shown at (205, 740), 139×44px; tap returns to scrollY 0 and focuses Build roster.
Backend stayed `23235cc`, PID 2951316; bot stayed `b517afd`, PID 2920748;
both invocation IDs and routing/storage drop-in hashes were unchanged, with no restart.

The clean tagged frontend passed 924 tests, TypeScript/build and isolated layout.
Review 91 accepted the visibility/focus/accessibility and zero-unlocked-selection
carry-in, with three required plus five extra mutations killed. Fixture checks
covered 360×800 and 1440×1000; the selected-state button cleared the action bar
by 20px. This is not a physical-phone or full assistive-technology audit.

Release evidence (`/tmp/wu-back-to-top-release/preflight.json`, `live.json`,
`backup.log`):

- Staged 120 files from the tagged checkout. Public index SHA-256:
  `884abc0df5506c94094e8c5c30c4b290f106a05654cbe7644396bbff052d1a41`.
- Roster JS `RosterWorkspace-Dr5JK0D6.js` SHA-256:
  `19a5063fa9889851cd73e2ef21b9059f75ff5e868c0b3a08ad661ce978c8225d`;
  CSS `RosterWorkspace-CGlA1JPS.css`:
  `9046fde769de0f45920e696abcbba7fcf992bae30dd2fad54500ddab05fa7d7b`.
- Backup `.local/back-to-top-1-backup-20261030T115115Z/dashboard.sqlite3`:
  1,282,048 bytes, integrity `ok`, SHA-256
  `dcf9918a850372991ab21a3ff839f1356569be82c94a63c60f9b508cab76a8a1`.
  Protected digest stayed
  `34449fa23beafcae682188bf3d7cfddaf47b12a455f10d433119288a004cc4f7`.
- Config readiness returned 200; anonymous commands read returned 401.

Later from review 91: hide the button while the undo toast is visible (about
12px overlap); check real-phone toolbar resize/upward-travel behavior; add
workspace-level bar-height and open-panel hide-gate tests. Smoke 93 does not
close these items.

Frontend-only rollback, only when authorized and still at this release boundary:
verify served hashes first and run this guarded command. A later release needs
its own rollback decision; do not bypass the guard.

```bash
set -euo pipefail
release_root=/home/ruggie/.local/share/wu-dashboard
test "$(readlink -f "$release_root/current")" = "$release_root/releases/a8031084eed09ee89b8063828d4bc2c5d40cc628"
test -d "$release_root/releases/23235ccf2671dfe5675f0bc98d38ab11a011ab09"
test "$(systemctl --user show -p WorkingDirectory --value wu-cwl-demo-web.service)" = "$release_root/backend/23235ccf2671dfe5675f0bc98d38ab11a011ab09"
test "$(git -C /home/botrunner/wu-bot rev-parse HEAD)" = b517afd46ecfa9cc08488798eba53393ed5b649f
/home/ruggie/.local/share/wu-dashboard/switch-release.py 23235ccf2671dfe5675f0bc98d38ab11a011ab09
```

Verify public hashes afterward against the weight-range manifest: entry
`index-BKbAuOsh.js`, SHA-256
`35683c3f84401a77d6ecf60031a9c33bb25ef25111809ba19c1161073ade1f5e`.
This restores the weight-range frontend without changing backend, bot or data.
Retain both immutable release directories and shared assets. Do not restore a
database or restart services for this frontend rollback.

## October 30 release records

These entries describe the verified release boundaries. A later frontend-only
release can advance the frontend independently of backend and bot; verify the
served hashes before acting on a rollback target.

| Release | Frontend/backend revision | Bot | Read-only smoke |
| --- | --- | --- | --- |
| `trigger-delete-1`, [PR #63](https://github.com/SirRuggie/WU_Python/pull/63) | `b517afd46ecfa9cc08488798eba53393ed5b649f` | Same revision, restarted | Passed, Claude handoff 90 |
| `weight-range-1`, [PR #64](https://github.com/SirRuggie/WU_Python/pull/64) | `23235ccf2671dfe5675f0bc98d38ab11a011ab09` | Stayed at `b517afd`, no restart | Passed, Claude handoff 92 |

Trigger-delete public entry `index-LzSl5cD4.js` SHA-256:
`693fe2b517b88b25c51ce8681d588bed46b33e54784b9c070cbd53868b5af392`.
Weight-range entry `index-BKbAuOsh.js` SHA-256:
`35683c3f84401a77d6ecf60031a9c33bb25ef25111809ba19c1161073ade1f5e`.
Weight-range verified the index and 36 selected assets, including owning
RosterWorkspace chunks rather than nonexistent standalone Compare/ClanSettings
chunks. Public hashes, backups, protected-state evidence, tooling corrections
and [guarded manual rollback commands](dashboard-backend-releases.md#guarded-manual-rollback-for-trigger-delete-and-weight-range)
are recorded with the backend releases.

Trigger-delete rolls all three code layers back to `6a2f8d7`; weight-range rolls
frontend/backend back to `b517afd`, leaving the bot alone. Never restore data.
The installed staging helper's nested-assets defect remains: both releases used
a reviewed recursive finalizer after the build, without modifying that helper.

Production frontend serving is separate from the workspace as of 2026-10-27.

- Public domain: `https://dash.warriorsunited.cc`
- User service `wu-dashboard-static.service`: Caddy gateway bound to loopback 8766.
- Existing user service `wu-cwl-demo-web.service`: API, loopback 8767; now runs from a clean isolated backend release (see [backend releases](dashboard-backend-releases.md)).
  Its historical name does not mean it is a test service.
- Gateway `/api/*` requests go to the API. Legacy `cwl.ruggie.zone` requests go
  through the existing canonical-host middleware. HTTPS remains at the existing
  public tunnel; the tunnel destination stays loopback 8766.
- Release root: `/home/ruggie/.local/share/wu-dashboard`.
- `current` points to `releases/<full-commit-sha>/`. `shared/assets` retains hashed
  assets for already-open browser tabs. Do not delete old assets during rollout.
- Workspace builds cannot affect either directory. Do not repoint production to
  workspace `web/cwl/dist`.

## Stage and activate (only with deployment authorization)

Back up and verify the live DB, record protected counts/publication versions, and
snapshot the current release first. Use a clean isolated checkout at a tagged
commit. Preserve existing deployed features when branches differ.

```bash
/home/ruggie/.local/share/wu-dashboard/stage-release.py /path/to/clean/checkout TAG
/home/ruggie/.local/share/wu-dashboard/switch-release.py FULL_COMMIT_SHA
```

The staging helper refuses dirty checkouts, mismatched tags, the main workspace,
existing release output, and conflicting hashed asset contents. It builds but
never activates. The switch helper atomically replaces `current`; it requires
no API or gateway restart. Verify the public index and entry/feature asset
SHA-256 values after every switch, not just the filesystem symlink.

## Rollback

Release 1 baseline snapshot: `snapshot-20261027T171555Z` (the previously live
mixed working-tree build). Release 1: `fea7e668b21823d9e31943867e25654ce0d60bf8`,
local tag `release-1`; roster baseline `a72939f`, preserving deployed moderation
frontend changes from `2d7d2c9`. Backend code was not deployed by this release.

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py snapshot-20261027T171555Z
# Re-enable the verified Release 1 artifact:
/home/ruggie/.local/share/wu-dashboard/switch-release.py fea7e668b21823d9e31943867e25654ce0d60bf8
```

Rollback triggers: protected count mismatch, console errors on load, or a
staff-reported write issue. Rollback changes the UI only; it does not undo data
writes. Investigate data discrepancies separately; never restore the DB blindly
and overwrite legitimate concurrent staff edits. Existing tabs need a reload to
use the switched UI. Public hash verification took about 0.1 seconds in the
release test; client/network timing varies.

No separate roster flag is currently needed: both retained frontend artifacts
are backend-compatible and rollback is atomic. Consider a flag for a future
staged audience rollout, not as a substitute for isolated build artifacts.

Never report "not deployed" without checking actual public asset hashes.
The release-1 tag is local; remote publication was not authorized in this run.
