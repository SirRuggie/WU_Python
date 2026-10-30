# Dashboard frontend releases

Current frontend: `strike-tracking-2`
(`6a2f8d735d1ee6e5ea912be10d3bba75a143ce09`, PR #61), paired with the
matching isolated backend and bot. Claude's read-only smoke passed; public
`index-CEDGmeqX.js` SHA-256 was
`8d11c9f20cfd22fa5946f7b682fdcc62e15d0da9abf0529ff9ce50aae41968de`.
Frontend rollback target: `4f57d6e73941d3adc3b3223611927081bf794df9`.
Use the [three-layer rollback procedure](dashboard-backend-releases.md#strike-tracking-2--october-30-2026)
for this release; switching only the frontend does not roll back its backend or
bot changes. The installed staging helper still needs a nested-asset fix;
this release used a reviewed scratch helper without changing the installed one.

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
