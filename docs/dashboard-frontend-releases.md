# Dashboard frontend releases

Latest recorded frontend: `back-to-top-1`, PR #65,
`a8031084eed09ee89b8063828d4bc2c5d40cc628`, activated after the releases below.
Public `index-zCmtmF3Z.js` SHA-256
`9f28a7a1b9aebbe14da09d48a5b2f94f3ee42ea9b7b5668da11929d4b774b5a0`
matched in `/tmp/wu-back-to-top-release/live.json`. Claude smoke is pending at
this documentation checkpoint. Backend stays `23235cc`, PID 2951316; bot stays
`b517afd`, PID 2920748; neither restarted. Its frontend-only rollback is:

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py 23235ccf2671dfe5675f0bc98d38ab11a011ab09
```

Verify public hashes afterward. This restores the weight-range frontend without
changing backend, bot or data. The back-to-top smoke and full release report are
separate follow-up documentation; the records below cover prompts 30 and 32.

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
