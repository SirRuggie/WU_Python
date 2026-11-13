# Release and rollback history

## UI audit Phases 5 and 6 — 2026-11-13 (frontend only)

- PRs [#338](https://github.com/SirRuggie/WU_Python/pull/338) (Phase 5, merge
  `8077764dd115a8f04654a31694a604e2b7723991`) and
  [#337](https://github.com/SirRuggie/WU_Python/pull/337) (Phase 6, merge
  `a1b8df6e46d6b3cd09048b2f09ab99c0c003aae8`), local tag `ui-audit-5-6-1`.
  Released by Shaka (Claude) on Ruggie's "merge and release 338 337"
  (2026-11-13 17:43 UTC).
- Changes: shared CSS tokens for colors, type, corners and breakpoints
  (Phase 5); the four largest screens split into smaller files (Phase 6).
  Only `web/cwl/` and docs changed since the bot release `32d9c56f`. No Python,
  route, schema or data change.
- Backend not changed or restarted: `backend/523cc293…`, PID 830330, active.
  Bot not changed or restarted (`32d9c56f…`, PID 871536).
- Frontend `current`: `523cc293…` → `a1b8df6e…` (clean tagged clone, `npm ci`,
  `tsc -b` and 2517 tests in 365 files passed before staging). Entry
  `index-u6269ilZ.js`, SHA-256
  `c9f659984de22ca414c735df479801f0e7de5aa71a3120b32b67261094402976`. Served
  `index.html` equals the release file on `/`, `/signup`, `/strikes`,
  `/server/members`, `/settings/integrations`; all 181 manifest files match the
  public site (`/index.html` first returned a stale edge copy; the cache-busted
  and repeat fetches matched).
- Backup `.local/ui-audit-5-6-release-20261113T175329Z/before.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `05f7a1003e0ff2b59426705bce883f1ab4439c939769b7902900b92ef9894604`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Smoke: signed-out HTTP only; anonymous `/api/cwl/auth/me` 401. Browser and
  signed-in smoke SKIPPED. No app writes, no Discord post.
- Rollback: frontend `switch-release.py
  523cc293c823a7fb9ff9e4dd0dc881976708e8e0`. No backend change to roll back.
  Never restore the database for a code rollback.

## Ticket "Link account" control — 2026-11-13 (bot only)

- PR [#340](https://github.com/SirRuggie/WU_Python/pull/340), merge commit
  `32d9c56f3e3fc84b486a4603125f9bfac1a13e8d`, local tag
  `ticket-link-account-340-1`. Merged and released by Shaka (Claude) on
  Ruggie's "you build and deploy the changes" (2026-11-13 16:45 UTC).
- Changes: staff "Link account" control on ticket cards writes ClashPerk links
  (`extensions/commands/tickets/link_account.py`, `player_info.py`,
  `console.py`, `utils/clashperk_link_writes.py`). No schema change, no data
  write. The control was not run live; no Discord post, no ClashPerk write.
- Checks: main merged into the branch (`1dc4d223`, tree equal to the merge
  commit); backend suite 8186 passed, 134 skipped, in a network-isolated
  namespace.
- Bot: `/home/botrunner/wu-bot` `0a061726…` → `32d9c56f…` (detached, clean,
  fast-forward; requirements unchanged). Other bot-side files since `0a061726`
  are not imported by the bot. Import check as botrunner passed. PID 385930 →
  871536, InvocationID `c5aa5b2fdb9341aeb14e6887dd34b986`, NRestarts 0; 60
  extensions loaded (same as before), `extensions.commands.tickets` loaded,
  `[Tickets] thread_runtime_ready configured_fields=6/6 index_errors=0`, no
  tracebacks or errors in the journal.
- Backend not changed or restarted (`backend/523cc293…`, PID 830330; it does
  not import the changed modules). Frontend not changed.
- Backup `.local/ticket-link-account-340-release-20261113T172008Z/before.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `b1e6389a7d056aa4f437d9e925a7669d84a34090151d27001921c488884080b9`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 and the lineup-rules digest identical before and
  after. Mongo counts not compared (the live bot writes continuously).
- Rollback: `sudo -n -u botrunner git -C /home/botrunner/wu-bot checkout
  --detach 0a06172621a542bae2ee0864b5ecf251b298614a`, then `sudo -n systemctl
  restart wu-bot.service`. Never restore the database for a code rollback.

## Non-members can sign in, Base bank members-only — 2026-11-13 (backend and frontend)

- PR [#339](https://github.com/SirRuggie/WU_Python/pull/339), merge commit
  `523cc293c823a7fb9ff9e4dd0dc881976708e8e0`, local tag
  `non-member-sign-in-339-1`. Prompt 238, built and released by Shaka (Claude)
  on Ruggie's "you build and release fully". Independent refuter: REWORK for 2
  missing tests, both added; Base bank gate added on Ruggie's "next".
- Changes: sign-in no longer needs the server; CWL signup save and Base bank
  check membership live (`cwl_web/server_membership.py`); `/auth/me` adds
  `server_member`. No schema change, no data write. See
  `docs/dashboard-sign-in.md`.
- Checks on the merged commit: backend 8168 passed (branch head), frontend 2516
  passed in 365 files and `tsc` in the clean release clone.
- Backend: `release.conf` `backend/22abb00b…` → `backend/523cc293…`; PID
  741607 → 830330, cwd verified, active, ready after 5 s, no journal errors,
  anonymous `/auth/me` and `/bases` 401; other drop-ins byte-identical. Bot not
  changed or restarted.
- Frontend `current`: `22abb00b…` → `523cc293…` (stage-release from the clean
  tagged clone). Entry `index-XXoQk8bM.js`, SHA-256
  `f67142247646c98b366795c75e8e93d9ed0f2709b1105432794028c006b10443`; served
  `index.html` equals the release file on `/`, `/signup`, `/bases`; all 147
  manifest assets match the public site.
- Backup `.local/non-member-sign-in-339-release-20261113T171411Z/before.sqlite3`: integrity ok, equal to live,
  SHA-256 `9c26c4be69ba5afd87edfcd1a68492921ea2f7e1158b13d5ed70345d69676628`.
  All 76 table counts, Main 23/23/23 and Lazy 147/146/131
  (signups/assigned/locks), publication max version 6 and the lineup-rules
  digest identical before and after.
- Signed-in read-only smoke (Ruggie's session): `/auth/me` `server_member`
  true from the live Discord check, no join line on Sign up, `/bases` 200 with
  13 bases. Non-member sign-in on production: SKIPPED (no non-member account).
- Rollback: frontend `switch-release.py
  22abb00bfd4f8106cffbf517a6d0beeb377ad8e7`; backend `release.conf`
  `WorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/22abb00bfd4f8106cffbf517a6d0beeb377ad8e7`,
  daemon-reload, restart. Never restore the database for a code rollback.

## Lazy announcement compact row — 2026-11-13 (frontend only)

- PR [#330](https://github.com/SirRuggie/WU_Python/pull/330), merge commit
  `f3021d21bb54cc218d47fb2db750b8a730aa0e8e`, local tag
  `lazy-announcement-330-1`. Released by Shaka (Claude) on Ruggie's "merge and
  release 330" (2026-11-13 14:49 UTC).
- Changes: the Lazy announcement entry is one compact row
  (`LazyAnnouncementCard.tsx`, `LazyAnnouncement.css`). No Python, route,
  schema or data change.
- Backend not changed or restarted: `backend/7a4abbe6…`, PID 434692, active.
  Bot not changed or restarted.
- Frontend `current`: `7a4abbe6…` → `f3021d21…` (clean tagged clone, `npm ci`,
  `tsc -b` and 2510 tests in 364 files passed before staging). Entry
  `index-u0CibkhF.js`, SHA-256
  `8dba029ed5b4ce42fea3dde713e1a7f38d7a52ef956d761776df72ed8f9def55`; feature
  `LazyAnnouncementCard-DCj-doV3.js`, SHA-256
  `cb3f0bbf8abf42c2df84c660a7655bcf592d0b5172e867a550e7fd19c10e8b39`. Served
  `index.html` (SHA-256
  `ffac0f3d3b9f2d0cc4d38998093e7d3736a633a1a0f080fed739f3a85175cb7a`) equals
  the release file on `/`, `/cwl/results`, `/cwl/bonuses`, `/cwl/exports`; all
  147 manifest assets match the public site.
- Backup `.local/lazy-announcement-330-release-20261113T145019Z/before.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `c64a639531302490c05ec18678d5b7b913c82ab3973e383041816b2c6730632e`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, no horizontal overflow, only the expected 401 on
  `/api/cwl/auth/me`, no app writes (only Cloudflare RUM beacons). Signed-in
  smoke SKIPPED. Send was not selected; no Discord post.
- Rollback: frontend `switch-release.py
  7a4abbe66ad87909544c22f9165fe26cc62936e6`. No backend change to roll back.
  Never restore the database for a code rollback.

## FWA Rep 1 per member, no Lazy sit-out — 2026-11-13 (backend and frontend)

- PR [#327](https://github.com/SirRuggie/WU_Python/pull/327), merge commit
  `7a4abbe66ad87909544c22f9165fe26cc62936e6`, local tag
  `fwa-rep-no-sit-out-327-1`. Prompt 237, built and released by Shaka (Claude)
  on Ruggie's "merge and release". Refuter ACCEPT. Rebased on `ab1fd2dd`
  (UI audit 323–326) after that release finished; checks rerun (backend 8145
  passed, frontend 2510 passed).
- Changes: 1 FWA Rep account per linked member (second add refused; existing
  duplicates kept with "Keep 1 account"); a listed Lazy account skips the
  sit-out (`sit_out_exempt`); wording in the help, Settings and chip. No schema
  change, no data write.
- Backend: `release.conf` `backend/8f64316e…` → `backend/7a4abbe6…`; PID
  333211 → 434692, cwd verified, active, ready after 9 s, public config 200,
  anonymous seasons 401, no tracebacks; other drop-ins byte-identical. Bot not
  restarted (does not import the changed modules).
- Frontend `current`: `ab1fd2dd…` → `7a4abbe6…` (clean tagged clone, `npm ci`,
  2510 tests passed before staging). Entry `index-DApwRnP1.js`, SHA-256
  `e1b50e0b361331f37590400a03bf39b5b4fec3a49034e77ce54215f3385cee74`; served
  `index.html` SHA-256
  `49575742ca9aeb370d8318a6fdec8559f0727365c661beccfc982e1ce2509491` equals the
  release file; all 147 manifest assets match the public site.
- Backup `.local/fwa-rep-327-release-20261113T143135Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `e543e51eddf77176a84cd8948a8b2b3b1e2981ecbfac7c5f6a666684d7f8c7f5`. All 76
  table counts identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, GET only.
  Signed-in smoke SKIPPED.
- Rollback: backend `release.conf` back to
  `backend/8f64316e6f4fa2100ef9e7a4dafcfe8658a88a0d`, daemon-reload, restart
  `wu-cwl-demo-web`; frontend `switch-release.py
  ab1fd2dd95b1a7015e3c13ac571267de2e2ea379`. Never restore the database for a
  code rollback.

## UI audit phases 1–4 — 2026-11-13 (frontend only)

- PRs [#323](https://github.com/SirRuggie/WU_Python/pull/323),
  [#324](https://github.com/SirRuggie/WU_Python/pull/324),
  [#325](https://github.com/SirRuggie/WU_Python/pull/325) and
  [#326](https://github.com/SirRuggie/WU_Python/pull/326); release commit
  `ab1fd2dd95b1a7015e3c13ac571267de2e2ea379` (merge of #326), local tag
  `ui-audit-1-4-1`. Released by Shaka (Claude) on Ruggie's "Merge and release
  all 4, from what I see it looks good" (2026-11-13 14:19 UTC).
- Scope: `git diff 8f64316e..ab1fd2dd` touches only `web/cwl/` and `docs/`
  (93 files; #321 in the range is docs only). No backend, bot, schema, data,
  config or systemd change. No service restart: backend PID 333211 before and
  after, still on `backend/8f64316e…`.
- Build: clean clone at the tag, `npm ci`, `tsc -b` passed, vitest 2509 tests
  in 364 files passed, checkout clean after; staged with `stage-release.py`
  (181 files).
- Frontend `current`: `8f64316e…` → `ab1fd2dd…` at 2026-11-13 14:24:13 UTC
  (`switch-history.jsonl`). Entry `index-Df6mkzza.js`, SHA-256
  `b71d17959d4b6ba9c6f8bf47a1f5c7b551f982160f4a2d0dea71d775ff73774d`. Served
  `index.html` (SHA-256
  `ddbf9f17e58f4d6ff0c6cb3bd145f4de4984a7a128f16887648c1ea8ba58ae1b`) equals
  the release file; all 147 release asset files match the public site.
  Feature chunks: `StaffOverview-BZLhPlAt.js` (SHA-256
  `4c9874a24b84732d9cbb8f163abe7273ed818829182d4699535867950fd0fdf6`),
  `ModerationWorkspace-CVJm4ap1.js` (SHA-256
  `b7ba36974737501caacf5f32cdcc5327f01038f304736ccdf9e39da4561c19e4`).
- Smoke (read only): config 200 twice, anonymous seasons 401. Served bundles
  contain "Members & moderation" and "Band monitor" (entry), "Activity
  history", "Invites" and "Log channels" (`ModerationWorkspace`); the old
  release contains none of the first two. Public home page loads; the only
  console error is the anonymous 401. No Save, Send or other write; no Discord
  post.
- Signed-in smoke 14:44 UTC (Ruggie signed in; served release was by then
  `7a4abbe6`, which includes `ab1fd2dd`): 7/7 PASS read-only. Sidebar groups,
  Moderation tabs, Band monitor opens directly, Results ends with "Next:
  Exports & history" and has no tab bar, Strikes ⋯ menu items, Members
  buttons; only console error the pre-sign-in 401. Ruggie's phone touch check
  of the ⋯ menus passed 14:55 UTC.
- Backup `.local/ui-audit-1-4-release-20261113T142158Z/dashboard.sqlite3`
  (SQLite backup API, 2,306,048 bytes): integrity ok, equal to live, SHA-256
  `fdef6411caf80aab70472200d2d82282d78b3f6fcd15d0eba1e62ac07ee809b5`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Rollback (frontend only): `python3
  /home/ruggie/.local/share/wu-dashboard/switch-release.py
  8f64316e6f4fa2100ef9e7a4dafcfe8658a88a0d`, then verify public hashes. Never
  restore the database for a code rollback.

## Lazy announcement card and renderer — 2026-11-13 (backend and frontend)

- PR [#322](https://github.com/SirRuggie/WU_Python/pull/322), merge commit
  `8f64316e6f4fa2100ef9e7a4dafcfe8658a88a0d`, local tag
  `lazy-announcement-322-1`. Released by Shaka (Claude) on Ruggie's "Merge and
  release 322" (2026-11-13 04:21 UTC).
- Changes: Participation shows the Lazy announcement card
  (`ParticipationWorkspace.tsx`); the renderer
  (`utils/cwl_bonus_announcement.py`) puts the role ping first and shows names
  in last month's winners. No route, schema, migration or data change.
- Backend: `release.conf` `backend/4ed8462b…` → `backend/8f64316e…` (clean
  `git archive`; imports verified from the release folder). PID 324752 →
  333211, InvocationID `a26748afe0804fca8e78f48693dfd2e3`, cwd verified,
  config 200 three times, anonymous seasons 401, anonymous
  `lazy-announcement?scope=all&ping=0` 401, unknown route 404. No tracebacks
  from the new PID. `frontend-routing.conf` and `storage-guard.conf`
  byte-identical. Bot (PID 3529055) not changed or restarted. Workspace
  fast-forwarded to `8f64316e`.
- Frontend `current`: `4ed8462b…` → `8f64316e…` (clean tagged clone, `npm ci`,
  `tsc -b` and 2483 tests in 357 files passed before staging; backend
  announcement/raffle tests 94 passed). Entry `index-BlbSQ1yr.js`, SHA-256
  `b9e8bf5303ecc57d3943741a878899a5924f18196397494bce20a17c4c1ae442`; feature
  `ParticipationWorkspace-BLelAMct.js`, SHA-256
  `23c7e6936a4ffc0e614471169834d01ec43c98335d9c46cbc998d6d65cba87c3`. Served
  `index.html` (SHA-256
  `30c39d380004235c67ded60dbc89344b9787d7bc8854d8d825c9691577ac1e5c`) equals
  the release file; all 147 release asset files match the public site.
- Backup `.local/lazy-announcement-322-release-20261113T042413Z/dashboard.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `f46db71da22e782780f46f5dbafa09b98b11ce9a5c5c5db46c103d2583663188`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Signed-in smoke SKIPPED. Send was not selected; no Discord post.
- Rollback: backend `release.conf` back to
  `backend/4ed8462be26c82f88e0a8930328166501136dd6a`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  4ed8462be26c82f88e0a8930328166501136dd6a`. Never restore the database for a
  code rollback.

## Lazy bonus announcement — 2026-11-13 (backend and frontend)

- PR [#320](https://github.com/SirRuggie/WU_Python/pull/320), merge commit
  `4ed8462be26c82f88e0a8930328166501136dd6a`, local tag
  `lazy-announcement-320-1`. Released by Shaka (Claude) on Ruggie's "Merge and
  release 320" (2026-11-13 04:06 UTC).
- Changes: staff send the Lazy bonus announcement to a channel from Results &
  bonuses (new `GET/POST /api/cwl/seasons/{id}/bonus-raffle/lazy-announcement`,
  `DiscordTransport.send_components`). No schema change, no migration, no data
  write during the release.
- Backend: `release.conf` `backend/e6477bd9…` → `backend/4ed8462b…` (clean
  `git archive`; imports verified from the release folder). PID 146074 →
  324752, InvocationID `28f6864421f347418dde523992c0d4d7`, cwd verified,
  config 200 three times, anonymous seasons 401, anonymous
  `lazy-announcement?scope=all&ping=0` 401 (route exists; unknown route 404).
  No tracebacks; Clash `accessDenied` lines also occur before the release.
  `frontend-routing.conf` and `storage-guard.conf` byte-identical. Bot
  (PID 3529055) not changed or restarted: it imports none of the changed
  modules. Workspace fast-forwarded to `4ed8462b`.
- Frontend `current`: `2e041c4d…` → `4ed8462b…` (clean tagged clone, `tsc -b`
  and 2481 tests in 356 files passed before staging). Entry
  `index-CeQw4APr.js`, SHA-256
  `b538ff920ccc7e5b3b085cfc29e22b8844be90744079fb890fe53223e9f4aa86`; feature
  `BonusWorkspace-CRtibwIa.js`, SHA-256
  `04b8b60efd2f16a1a579e6e55d9571b9b793fc4140c80040a59e6eade7e66512`. Served
  `index.html` (SHA-256
  `a85b4d23057b662537f21b182c927f37911a030473a605ce46846ad604239d52`) equals
  the release file; all 147 release asset files match the public site.
- Backup `.local/lazy-announcement-320-release-20261113T040738Z/dashboard.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `e5132ec202bfbf2be39995dd222029ea8f7816ab384d22b9cb0a8bdd250ff5b2`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Signed-in smoke SKIPPED. Send was not selected; no Discord post.
- Rollback: backend `release.conf` back to
  `backend/e6477bd9b599461aa7499ecb9ce84fa9219bbe51`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  2e041c4d7417d5e8f55854b66525e9e4b8f24752`. Never restore the database for a
  code rollback.

## November 12, 2026 —232/233 completed (Shaka1041/1042)

These dated records supersede the older current/standby labels below. Recorded
frontend: `3f9792e7489118db1b07b6d12e63780e39e6bbf1` (233); backend:
`e6477bd9b599461aa7499ecb9ce84fa9219bbe51` (232); bot checkout:
`0a06172621a542bae2ee0864b5ecf251b298614a`. These are retained release facts,
not fresh live probes or permission to rerun completed release tools.

- **232**, PR313, tag `exports-excel-1`, FE/BE `e6477bd9…`: verified backup
  `.local/exports-excel-release-evidence-232-1037/pre-stage/.local/discord-links-defaults-1-backup-20261112T211057Z/dashboard.sqlite3`,
  SHA256 `ebd213bee483f0e76595a2ff4483006c9946f53a3d5c122cdf3de717fa21e813`.
  All182 public hashes matched; index SHA256
  `c33e0a4ef07c85de38129f36e946a62b55180535f8d9a2e6bfaa4a3d78849f72`,
  `index-vW-gTMbx.js` SHA256
  `ace397d5710963bcd524148721145dc5c772ab5d77185f5dd03b7fae553c7688`.
  Backend normal switch/restart PID4059855→146074, InvocationID
  `982912e2ee254ade929bcc8f1aa821b7`; bot3529055/gateway307279 unchanged.
  Native read-only Exports closed/open at360/1440, no downloads/writes; separate
  receipt/validator/post each exit0. Shaka1041 runtime SMOKE PASS.
- **233**, PR314, tag `season-picker-labels-1`, frontend `3f9792e7…`: plain
  documented stage/switch after fresh backup
  `.local/season-picker-labels-release-evidence-233/plain-before/.local/discord-links-defaults-1-backup-20261112T212002Z/dashboard.sqlite3`,
  SHA256 `b4560dbeb56b95831ead88b3798d9d516ea3a5a83048b316d4f6a76eea65bfcf`.
  All180 public hashes matched; index SHA256
  `07a4a5b4311390bfe0b941e1148e96961887f9ec609b41b3cd12d484e1199876`,
  `index-IAlUYglT.js` SHA256
  `b1ccc6e89830ea0963576ea019d6a0a00c17924f5ac21d693bf11cea95683f6d`.
  Backend232 PID146074, bot3529055, gateway and configuration unchanged; no
  backend restart. Parent native Roster/Results/Exports and range checks at360/1440
  were read only. Results native OS popup visual was skipped; AX/DOM option
  proof retained. Shaka1042 runtime SMOKE PASS, signed-in UI SKIPPED by Shaka.

Both releases: all76 table counts/schema/raw digests, Main23/23/23 and
Lazy147/146/131 (signups/assigned/locks), imported winners82 and six publication
versions36/473/475/476/544/597 exact.232 four unchanged committed comparison
proofs and233 one proof each have changed_rows0. Sequential Mongo readbacks
matched their own SQL phases; no cross-phase transactional snapshot claim.
Evidence: private232 `release-done.json`/`done-summary.json` and233
`plain-done.json`/`plain-counts-proof.json`, with self-contained release reports.
The233 escaped-test incident was closed with production SQLite read **unknown**;
immediate parent runtime/public verification and final232 raw data were exact.
Per1041 the private233 coordinator/tests were deleted, not repaired or rerun.
No live workbook/Discord/AT/device/all-pages claim.230–233 closed by1042.

## Current standby and rollback targets

`signup-reminders-ack-1`, commit
`e4f9574ca6243fa4a6c3bf33c70acfb662c0f61f`, is the verified frontend,
backend **and bot** standby for the next approved release. It passed read-only
smoke on November 2, 2026 (local time). See
[`docs/signup-reminders-ack-1-release.md`](signup-reminders-ack-1-release.md)
for the actual runtime, hashes, backups and testing limits.

The bot rollback target is that same full commit, not the older bot snapshots
below. A bot rollback requires a newly scoped, reviewed coordinator with actual
runtime verification, the full 210-second inactive lease drain, import/readiness
checks and the recorded war-fetch gap. A bare reset/restart is insufficient.
Backend and immutable frontend targets are also that same commit; preserve their
retained artifacts and verify served hashes. Never rerun a completed activation
coordinator, restore databases for a code rollback, or reverse approved data
corrections. The older entries below are historical snapshots, not the current
standby targets.

Rollback from the currently running `e4f9574` itself remains bot `343d961`, backend `e91982d` and frontend `c55c7f0`; the standby above is for subsequent releases.

## Verified standby release (Shaka smoke 466)

`signup-reminders-ack-1`, commit
`e4f9574ca6243fa4a6c3bf33c70acfb662c0f61f`, is the verified frontend,
backend **and bot** standby for the next approved release. It passed read-only
smoke on November 2, 2026 (local time). See
[`docs/signup-reminders-ack-1-release.md`](signup-reminders-ack-1-release.md)
for the actual runtime, hashes, backups and testing limits.

The bot rollback target is that same full commit, not the older bot snapshots
below. A bot rollback requires a newly scoped, reviewed coordinator with actual
runtime verification, the full 210-second inactive lease drain, import/readiness
checks and the recorded war-fetch gap. A bare reset/restart is insufficient.
Backend and immutable frontend targets are also that same commit; preserve their
retained artifacts and verify served hashes. Never rerun a completed activation
coordinator, restore databases for a code rollback, or reverse approved data
corrections. The older entries below are historical snapshots, not the current
standby targets.

Rollback from the currently running `e4f9574` itself remains bot `343d961`, backend `e91982d` and frontend `c55c7f0`; the standby above is for subsequent releases.

## Historical deployed snapshot (Claude smoke 131)

`no-war-strikes-1`: frontend, backend and bot at `73eda11a1e883b711bc40494f023b4d87efd5a6b`.
Read-only smoke passed. Previous dashboard code: `cb0052dc93cc30b127e2cbe5006a06c149c43671`;
previous bot: `c9b4ac0f5ca7f64a6fc329d06dde419af403ab46`.
Use the guarded rollback in `docs/dashboard-backend-releases.md`; do not reverse
approved NO WAR corrections or restore databases for a code rollback.

## Dated production and rollback records

  - Latest recorded frontend/backend/bot at Claude smoke 98: `moderation-logs-1` / `c494022e924994435496c3e4f0722eb781460380`, public hashes and runtime checks passed. Bot shipped first, then backend readiness, then frontend. Guarded rollback targets: frontend `a8031084eed09ee89b8063828d4bc2c5d40cc628`, backend `23235ccf2671dfe5675f0bc98d38ab11a011ab09`, bot `b517afd46ecfa9cc08488798eba53393ed5b649f`. Follow [moderation rollback](dashboard-backend-releases.md#guarded-moderation-rollback); any staff inheritance save requires a settings recheck before old-bot downgrade. Never restore data.
  - Historical rollback snapshot: `/home/ruggie/.local/share/wu-dashboard/releases/snapshot-20261027T171555Z/`.
  - Weight-range rollback restores frontend/backend to `b517afd` with the bot unchanged. Trigger-delete rollback restores all three to `6a2f8d7`. Follow the [guarded manual procedure](dashboard-backend-releases.md#guarded-manual-rollback-for-trigger-delete-and-weight-range); a later frontend release must be rolled back first. Never restore databases for code rollback.

## Infractions in player Details — 2026-11-12 (frontend only)

- PR [#309](https://github.com/SirRuggie/WU_Python/pull/309), merge commit
  `e947b72399193b3d542acdf522ef0ec459f5c0da`, local tag `infractions-309-1`.
  Built and released by Shaka (Claude) on Ruggie's "release 309". Refuter
  ACCEPT on `cdcfb5d5`; the notes-lock fix `37073477` followed (2368 tests,
  `tsc -b`, fixture browser check).
- Changes: Lazy infractions (Missed sync, Lingering, Left family, staff
  exception) in the player Details panel with one Save for notes and
  infractions; ⋯ "Infractions" and flag chips on step cards; staff notes are
  no longer locked by their own open Details sheet.
- No Python changed. Backend `backend/ea46425a…` (PID 3671110) and bot not
  changed or restarted.
- Frontend `current`: `ea46425a…` → `e947b723…` (clean tagged clone, 2368
  tests in 348 files passed before staging). Entry `index-CA-3Aok5.js`,
  SHA-256 `a6c82c98910e84212e16fedddf1fa01e6a5feac9b03d56166d678d4d22f1a81b`;
  served `index.html` SHA-256
  `41b9fb4c67c9c29a1581a5fcbfcc6bb62a2a7007ba7163ff4e8cefc76cf54aab` equals the
  release file; all 148 manifest assets match the public site.
- Backup `.local/infractions-309-release-20261112T153438Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `c3dc513bd9535e287441a83c8661966f37db8b0f1582dbc241230c790241bd21`. All 75
  table counts identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, app requests
  GET only. Signed-in smoke SKIPPED.
- Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py
  ea46425a44eeb3327e12efe7748da7e649fad7a1`. Never restore the database for a
  code rollback.

## Clan Rep picker for FWA Rep accounts — 2026-11-12 (backend and frontend)

- PR [#306](https://github.com/SirRuggie/WU_Python/pull/306), merge commit
  `ea46425a44eeb3327e12efe7748da7e649fad7a1`, local tag
  `clan-rep-picker-306-1`. Built and released by Shaka (Claude) on Ruggie's
  "merge and release". Refuter ACCEPT; its 2 should-fixes applied in `14e6930d`.
- Changes: read-only `GET .../bonus-raffle/clan-rep-members` (FWA Clan Rep role
  `769130325460254740`, editor access); "Find Clan Rep (x2 odds)" picker in FWA
  Rep accounts with "Add for x2". No schema change.
- Backend: `release.conf` `backend/eccff038…` → `backend/ea46425a…`; PID
  3619459 → 3671110, cwd verified, active, ready after 8 s, public config 200,
  anonymous seasons and clan-rep-members 401, no tracebacks; other drop-ins
  byte-identical. Bot not restarted (does not import the changed modules).
- Frontend `current`: `eccff038…` → `ea46425a…` (clean tagged clone, `npm ci`,
  2338 tests passed before staging). Entry `index-BdiAtLud.js`, SHA-256
  `f5a84cd711efe2daf06774735395296df4e05654cb13fefed49111cef2508c2d`; served
  `index.html` SHA-256
  `bef986e9271d2377718a16b28866f6b2b8f3c20cc11ddce264875e0ccd436aea` equals the
  release file; all 149 manifest assets match the public site.
- Backup `.local/clan-rep-306-release-20261112T023546Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `105f22d92b48873ef7dfffbe717200519092e19812f2c968354e2c13b00c88b9`. All 75
  table counts identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, GET only.
  Signed-in smoke SKIPPED.
- Rollback: backend `release.conf` back to
  `backend/eccff03812d9e94580cfc23ea3283a7846f87e03`, daemon-reload, restart
  `wu-cwl-demo-web`; frontend `switch-release.py
  eccff03812d9e94580cfc23ea3283a7846f87e03`. Never restore the database for a
  code rollback.

## FWA Rep accounts for Lazy x2 odds — 2026-11-12 (backend and frontend)

- PR [#304](https://github.com/SirRuggie/WU_Python/pull/304), merge commit
  `eccff03812d9e94580cfc23ea3283a7846f87e03`, local tag `fwa-rep-304-1`.
  Built and released by Shaka (Claude) on Ruggie's "Merge and release".
  Refuter ACCEPT on `9f03c9b8`.
- Changes: Lazy x2 raffle odds come from one family-wide FWA Rep account list
  (Settings sheet), not the Discord role. New additive tables
  `bonus_raffle_rep_accounts` and `bonus_raffle_rep_account_audit`; the old role
  tables stay unread. Lazy draws use `rules_version` 3. The list starts empty;
  no data was written.
- Backend: `release.conf` `backend/ab2e217b…` → `backend/eccff038…`; PID
  3574547 → 3619459, cwd verified, active, local and public config 200,
  anonymous seasons, bonus-status and rep-accounts 401, no tracebacks. Other
  drop-ins byte-identical. The bot imports neither changed module, so it was
  not restarted.
- Frontend `current`: `ab2e217b…` → `eccff038…` (clean tagged clone, `npm ci`,
  2337 tests in 344 files passed before staging). Entry `index-CBlehv8O.js`,
  SHA-256 `c3a9fe428a132291ffc77d9303bdf7bb4ed802f1671341aec505cf1880983373`;
  served `index.html` SHA-256
  `de1d95b9bcf8d030ca970945caf5c2155d47c52c6d0a46f99ad4dc9345a5d90b` equals the
  release file; all 149 manifest assets match the public site.
- Backup `.local/fwa-rep-304-release-20261112T011449Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `39ea13dfd603d6673d5f4f36343f1e69a5e5580635210f4761aa28396b28db52`. All 73
  existing table counts identical after; 2 new tables, both empty.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, app requests
  GET only. Signed-in smoke SKIPPED.
- Rollback: backend `release.conf` back to
  `backend/ab2e217b9e5ac6ece40cb6bb5e233625a178331a`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  ab2e217b9e5ac6ece40cb6bb5e233625a178331a`. The new tables stay; never restore
  the database for a code rollback.

## Clan dropdown and Lazy-only sit-out — 2026-11-11 (backend and frontend)

- PR [#302](https://github.com/SirRuggie/WU_Python/pull/302), merge commit
  `ab2e217b9e5ac6ece40cb6bb5e233625a178331a`, local tag
  `clan-dropdown-302-1`. Built and released by Shaka (Claude) on Ruggie's
  "Release 302". Refuter ACCEPT on `0ac81f82`; a copy/CSS polish commit
  followed (2334 frontend tests rerun).
- Changes: one "Hosting clan" dropdown with state in each option (clan cards
  and "Find a clan" removed); Find a player and Sort on one row; overview gets
  the shared `roster-ui` tokens; the Lazy 3-month sit-out counts only earlier
  Lazy bonuses (Ruggie: "per pool").
- Backend: `release.conf` `backend/0a061726…` → `backend/ab2e217b…`; PID
  3529151 → 3574547, cwd verified, active, config 200, anonymous seasons 401,
  no tracebacks. Python diff limited to `utils/cwl_bonus_raffle*.py` and its
  test; the bot imports neither, so it was not restarted (`wu-bot` active).
- Frontend `current`: `0a061726…` → `ab2e217b…` (clean tagged clone, 2334
  tests in 344 files and 75 Lazy bonus backend tests passed before staging).
  Entry `index-DVjQeDFr.js`, SHA-256
  `e17c2c975eee7b7a36da3974db7bca3aeb9f29c99a2505b6ae1075576f814500`; served
  `index.html` SHA-256
  `617acf39966b8fec9055e45929c3d72ab30f7b189d4d17dd89fcc1e3193e9d36` equals the
  release file; all 149 manifest assets match the public site.
- Backup `.local/clan-dropdown-302-release-20261111T223740Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `a607fee98edbed2a0ad6bc6f5469e8254877f3045243cc8b7a116acfefd5b819`. All 73
  table counts identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, app requests
  GET only. Signed-in smoke SKIPPED.
- Rollback: backend `release.conf` back to
  `backend/0a06172621a542bae2ee0864b5ecf251b298614a`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  0a06172621a542bae2ee0864b5ecf251b298614a`. Never restore the database for a
  code rollback.

## Results & bonuses one flow — 2026-11-11 (frontend only)

- PR [#299](https://github.com/SirRuggie/WU_Python/pull/299), merge commit
  `11959254eedfef916e2a136e5df9370a3890a3c8`, local tag
  `results-bonuses-229-1`. Built and released by Shaka (Claude) on Ruggie's
  "release 229". Final refuter verdict ACCEPT on head `56c82382`.
- The diff from the live `7771de45` (plus docs-only `afbf2472`) touches only
  `web/cwl/src` and docs. Backend (`backend/8e800f7a…`, PID 3222929) and bot
  were not changed or restarted.
- Frontend `current`: `7771de45…` → `11959254…` at about 2026-11-11T20:38Z,
  through `stage-release.py` (clean tagged clone, `npm ci`, 2331 tests in 344
  files passed before staging) and `switch-release.py`.
- Public entry `index-DKmp4ptE.js`, SHA-256
  `45224e61561c467832ac486a48dc5052d038805bf8121b32c15c62b2078c181f`; served
  `index.html` SHA-256
  `d601404d9c24ff82820e10a0fc78b1e2e5a0286ce39590fd4a73a35a8a6ddefb` equals the
  release file. All 149 manifest assets fetched from the public site match.
  `/api/cwl/config` 200; anonymous `/api/cwl/seasons` and `bonus-status` 401.
- SQLite online backup
  `.local/results-bonuses-229-release-20261111T203343Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `a41ba2ed3c4ae729e2ee50b02ced62054f370653ec82e4f3921eaf26882ed606`. All 73
  table counts identical before and after.
- Signed-out smoke at 360 px: `/cwl/results`, `/cwl/bonuses` and
  `/cwl/exports` load the new entry; only console error is the expected 401;
  no horizontal overflow; app requests GET only. Signed-in smoke SKIPPED
  (built-in browser signed out).
- Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py
  7771de450d0a8b6400db1f02411021dbaab25cae`. Never restore the database for a
  code rollback.

## Shared player cards on Bonus medals and Exports — 2026-11-11 (frontend only)

- PR [#297](https://github.com/SirRuggie/WU_Python/pull/297), merge commit
  `7771de450d0a8b6400db1f02411021dbaab25cae`, local tag
  `bonus-exports-cards-297-1`. Released by Shaka (Claude) on Ruggie's
  "Release 297".
- The diff from the live `8e800f7a` touches only `web/cwl/src` and docs.
  Backend (`backend/8e800f7a…`, PID 3222929) and bot were not changed or
  restarted; gateway PID 307279 unchanged.
- Frontend `current`: `8e800f7a…` → `7771de45…` at 2026-11-11T18:15:20Z,
  through `stage-release.py` (clean tagged clone, `npm ci`, 2256 tests in 339
  files passed; `tsc -b` and build ran in the helper) and `switch-release.py`.
- Public entry `index-BbWuEoxV.js`, SHA-256
  `413d79834735d44a43819785e2ad7d7e237cd3c687447e23b21319d499ab2327`;
  `index.html` SHA-256
  `818c69d32ed93b264b083ad04704fcb911f1872cd56492f4f055154cfcc2b10c` equals
  the served file. Index and 13 affected assets (BonusWorkspace,
  ExportWorkspace, ParticipationWorkspace, AccountCard, PlayerCardMeta,
  exportPreview JS/CSS) match the manifest. `/api/cwl/config` 200, anonymous
  `/api/cwl/seasons` and `bonus-status` 401, no tracebacks.
- SQLite online backup
  `.local/bonus-exports-cards-297-release-20261111T181331Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `c83842c890a8a9c2b66d94bf4bce063b4d75f599baab2f88f08306ef3efb3fcd`.
  Season 1: lazy 147 signups / 146 assigned / 131 locks, main 23 / 23 / 23,
  publication version 6, roster revision 621. All 73 table counts identical
  before and after.
- Signed-out smoke: `/cwl/bonuses`, `/cwl/exports` and `/cwl/results` load
  the new entry; only console error is the expected 401 on `auth/me`; GETs
  only. Signed-in smoke by Shaka SKIPPED (built-in browser signed out).
- Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py
  8e800f7a50b5ee54ec3c8b5058eae7b79095485b`. Never restore the database for a
  code rollback.

## Did not join release — 2026-11-11 (backend and frontend)

- PR [#295](https://github.com/SirRuggie/WU_Python/pull/295), merge commit
  `8e800f7a50b5ee54ec3c8b5058eae7b79095485b`, local tag `did-not-join-295-1`.
  Built and released by Shaka (Claude) on Ruggie's decisions in the thread
  "CWL results are incomplete"; merge on Ruggie's "merge it". Independent
  refuter: REWORK (bonus rules not gated on a finished group) → ACCEPT on head
  `256a96b`.
- Changes: Did not join (finished CWL group, not in league-group or war
  rosters), Filler and Not assigned outcomes; Did not join never counts as
  incomplete and is excluded from Main and Lazy draws without blocking; "Add
  strike" ⋯ item only opens Strikes; Main "Resolve incomplete" links to Results.
- Backend: `release.conf` `backend/d225e33d…` → `backend/8e800f7a…`; PID
  3100542 → 3222929, cwd verified, config 200, anonymous seasons 401, no
  tracebacks. Bot unchanged and not restarted (it imports none of the changed
  modules); workspace fast-forwarded.
- Frontend `current`: `d225e33d…` → `8e800f7a…` (clean tagged clone, 2248 tests
  and `tsc -b` passed). Entry `index-BEbs58hr.js`; served `index.html` equals
  the release file; 9 affected assets match.
- Backup `.local/did-not-join-295-release-20261111T171652Z/dashboard.sqlite3`: integrity ok, equal to live. All 73 table
  counts identical before and after.
- Signed-in smoke by Shaka SKIPPED (the browser was not signed in).
- Rollback: backend `release.conf` back to
  `backend/d225e33d14a357e566d4caa35f4ad1f0c9383b29`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  d225e33d14a357e566d4caa35f4ad1f0c9383b29`. Never restore the database for a
  code rollback.

## Read-only results release — 2026-11-11 (backend and frontend)

- PR [#293](https://github.com/SirRuggie/WU_Python/pull/293), merge commit
  `d225e33d14a357e566d4caa35f4ad1f0c9383b29`, local tag
  `readonly-results-293-1`. Built and released by Shaka (Claude) on Ruggie's
  decisions in the thread "Audit bonus medals pages". Head `f5a8bdb` ACCEPTED
  after one REWORK round (card body mouse click, partial-results label).
- Changes: attacks and stars are read only (save route returns 400 for changes;
  notes still save); a logged bonus review reason covers never-captured Lazy
  results; the whole Results card opens a read-only Details panel; shared ⋯ menu
  with DM and Details; amber "Partial results" label.
- Backend: `release.conf` `backend/965c3f74…` → `backend/d225e33d…`; PID
  3051555 → 3100542, cwd verified, config 200, anonymous seasons 401, no
  tracebacks. Bot unchanged and not restarted; workspace fast-forwarded.
- Frontend `current`: `be2a40c7…` → `d225e33d…` (clean tagged clone, 2244
  tests and `tsc -b` passed). Entry `index-6U8qQMH3.js`; served `index.html`
  equals the release file; 6 affected assets match the manifest.
- Backup `.local/readonly-results-293-release-20261111T163949Z/dashboard.sqlite3`:
  integrity ok, equal to live; 162 participation records with 0 staff
  overrides. All 73 table counts identical before and after.
- Signed-in smoke by Shaka SKIPPED (no signed-in browser).
- Rollback: backend `release.conf` back to `backend/965c3f746b75793b37a1c7862de8a435e9e5fe76`
  then daemon-reload and restart `wu-cwl-demo-web`; frontend
  `switch-release.py be2a40c7ecdc128f7e4833b8f07c92ee50d1581c`. Never restore
  the database for a code rollback.

## Bonus and participation flow release — 2026-11-11 (backend and frontend)

- PR [#291](https://github.com/SirRuggie/WU_Python/pull/291) (prompt 228),
  merge commit `be2a40c7ecdc128f7e4833b8f07c92ee50d1581c`, local tag
  `bonus-flow-228-1`. Built and released by Shaka (Claude) on Ruggie's
  instruction in the thread "Audit bonus medals pages". Head `7241561`
  passed four independent reviews (last gap fixed and its mutation checked).
- Changes: bonus host check uses the season pool (fixes "Hosting clan is no
  longer an active Lazy clan in this season"); new read-only
  `GET /api/cwl/seasons/{id}/bonus-status`; any bonus in the previous 3 months
  blocks a Lazy bonus; shared step bar, outcome chips, clan cards, phone layout.
- Backend: `release.conf` WorkingDirectory `backend/14bcded8…` →
  `backend/be2a40c7…`; service restarted, PID 2779146 → 3031436, cwd verified.
  `/api/cwl/config` 200, anonymous `/api/cwl/seasons` and `bonus-status` 401,
  no tracebacks. Bot code unchanged and not restarted (the bot does not import
  the changed modules); workspace checkout fast-forwarded to `be2a40c7`.
- Frontend `current`: `c95dee7e…` → `be2a40c7…` through `stage-release.py`
  (clean tagged clone, `npm ci`, 2235 tests and `tsc -b` passed) and
  `switch-release.py`. Entry `index-BJNXaOik.js`; `index.html` SHA-256
  `b8c77c481b6c49fc38feb63dd004316eecbd3486be9246061d82a359520f5fd5` equals
  the served file; 9 affected assets match the manifest.
- SQLite online backup `.local/bonus-flow-228-release-20261111T150821Z/dashboard.sqlite3`:
  integrity ok, equal to live. Season 1 signups lazy 147, main 23. All 73
  table counts identical before and after.
- Bug evidence on the backup: season 1 has 8 Lazy hosting clans; the old rule
  accepted 6, the new rule accepts 8.
- Signed-in smoke by Shaka SKIPPED (built-in browser signed out; Chrome
  extension not connected).
- Rollback: backend `release.conf` back to `backend/14bcded82ca26147e146635acfe05d19a3017ab1`,
  `systemctl --user daemon-reload && systemctl --user restart wu-cwl-demo-web`;
  frontend `/home/ruggie/.local/share/wu-dashboard/switch-release.py c95dee7ec2b4da31d4931f7995960ce333d4c268`.
  No data migration; never restore the database for a code rollback.

## B-6 tab cleanup release — 2026-11-11 (frontend only)

- PR [#280](https://github.com/SirRuggie/WU_Python/pull/280), merge commit
  `3d04372aa4b9614489dfd0dcf1434c9c32d22033`, local tag `b6-tab-cleanup-1`.
  Shaka APPROVED head `5aa382a`. Released by Shaka (Claude).
- Frontend `current`: `38c68ae625d1de4292410e5b318cb87fbc9e1c0b` →
  `3d04372aa4b9614489dfd0dcf1434c9c32d22033` at 2026-11-11T01:59Z, through
  `stage-release.py` (clean tagged worktree, `npm ci`) and `switch-release.py`.
  The `web/cwl` diff from `38c68ae` contains only PR #280. Backend
  (`249a83e3`) and bot were not changed or restarted.
- Public entry `index-s3SoFMZS.js`, CSS `index-DXqKCkzK.css`; `index.html`
  SHA-256 `ad4cdf23c006814e36a3307f42e3e96e7f27332f05b3fcc242e723e214a6b1ce`.
  Index and 13 changed feature assets (ClanManagement, ModerationWorkspace,
  ServerManagement, RosterWorkspace, navList, FilterChips, TextCommands) match
  the manifest. `/api/cwl/config` 200, anonymous `/api/cwl/seasons` 401.
- SQLite online backup
  `.local/b6-tab-cleanup-release-280-20261111T015830Z/dashboard.sqlite3`:
  integrity ok, equal to live. Season 1: lazy 147 signups / 146 assigned /
  131 locks, main 23 / 23 / 23, publication version 6, roster revision 621.
  All 73 table counts identical before and after.
- Signed-in smoke by Shaka SKIPPED (built-in browser signed out; Chrome
  extension not connected). Signed-out home checked at 375 and 800 px. Ruggie
  checked Family clans, Moderation and an FWA tools setting signed in on his
  phone at 2026-11-11T02:10Z: "Looks good".
- Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 38c68ae625d1de4292410e5b318cb87fbc9e1c0b`.

## Moderation logging release — 2026-10-30

- PR #68 / `moderation-logs-1` at `c494022e924994435496c3e4f0722eb781460380` shipped bot → ready → backend → ready → frontend. Integrated 4,863 backend tests / 21 skipped / 162 subtests and 933 frontend tests passed; final tagged frontend tests/TypeScript/build passed, with only three documentation files changed from the integrated checked tree. Seventeen mocked release checks passed.
- Raw moderation settings stayed unchanged at revision 1 with read-only normalization: Join/Leave enabled at channel 1564485264364011580, Kick/Ban disabled with no channel, all forum tags null, exact before/after parity. Backups/counts, hashes and readiness are in [backend releases](dashboard-backend-releases.md#moderation-logs-1--october-30-2026).
- Claude's read-only smoke 98 passed; no production Send test or test Discord message. Three of eight avatar requests returned 503 with initials fallback; prompt 33 item 6 remains open. Mock transport evidence is not live Discord delivery proof.

## Back-to-top release — 2026-10-30 (historical)

- `back-to-top-1`, PR #65/tag `a8031084eed09ee89b8063828d4bc2c5d40cc628`, released frontend only. Claude's read-only 360px smoke 93 passed: hidden at the top, visible after three viewports down and 200px up, 139×44 target, tap returns to zero and focuses Build roster. Backend PID 2951316 and bot PID 2920748/invocations stayed unchanged.
- 924 frontend tests, TypeScript/build and isolated layout passed; review 91 confirmed three required and five extra mutations killed. Public entry/roster hashes, verified backup, protected digest and guarded rollback are in [frontend releases](dashboard-frontend-releases.md).
- Later from review 91: hide the button during the undo toast (about 12px overlap); confirm real-phone toolbar resize behavior that can require extra upward travel; add workspace-level bar-height and open-panel hide-gate tests. These remain open after the passing smoke.

## Trigger-delete and weight-range releases — 2026-10-30

- `trigger-delete-1`, PR #63/tag at `b517afd46ecfa9cc08488798eba53393ed5b649f`, released frontend/backend/bot. Plain and recipient trigger messages are deleted only after a successful reply when the new default-on option is enabled. Delete failures remain visible and later success clears the warning. Claude smoke 90 passed; Codex and Claude did not post a live trigger. Ruggie's own Discord test is separate.
- `weight-range-1`, PR #64/tag at `23235ccf2671dfe5675f0bc98d38ab11a011ab09`, released frontend/backend; bot stayed at b517afd, PID 2920748 with unchanged invocation. Inclusive range bounds, descending-weight Compare and capped quick picks passed Claude's read-only 360px smoke 92, including Jujupon 179k inside Lazy.128's 172–179 range.
- Tagged checks: trigger-delete 4,839 backend / 21 skipped / 133 subtests and 908 frontend; weight-range 4,844 backend / 21 skipped / 153 subtests and 914 frontend. TypeScript/build passed for both. Verified backups, public entry/feature hashes and protected-state comparisons are in [backend releases](dashboard-backend-releases.md#weight-range-1--october-30-2026).
- Tooling limits are recorded there: nested-asset staging fallback; trigger-delete first rolled back after a wrong journal window, then passed with InvocationID-scoped checks; weight-range's owning-bundle verifier corrected nonexistent standalone chunk assumptions. Preserve routing/storage drop-ins and all data during rollback.
- Later: prompt 31 fixes the pre-existing command pattern hyphen under browser `v` regex semantics. Prompt 32 cleanup retains the unreachable Max-50 branch, stale selection documentation and first-only shared-boundary note as review items. The zero-unlocked selection correction is carried by the separate accepted back-to-top change.

## Strike-tracking release — 2026-10-30 (historical)

- At that release, frontend/backend/bot were `strike-tracking-2`, `6a2f8d735d1ee6e5ea912be10d3bba75a143ce09`, PR #61. Claude read-only smoke PASSED; the official bot pass checked 25 clans, and Tracking showed 12 On track / 13 Behind, 0 private / 0 error. Public entry and feature hashes, backend readiness/cwd, protected data and durable backups passed. No historical gap backfill or live test messages. See `docs/strike-system.md` and `docs/dashboard-backend-releases.md` for policy, rollback and Later items.

## Weight totals release — 2026-10-29

- Previous frontend: `weight-totals-1`, `4f57d6e73941d3adc3b3223611927081bf794df9`, PR #59. Assign and Balance display known-weight totals instead of weight averages; `Avg TH` remains. Empty clans say `Total: no weights yet`. Fill spot / Signup Details no longer opens a second dirty dialog after roster Discard. The accepted branch passed 901 frontend tests, TypeScript/build and full isolated layout. Claude's read-only owner 360px smoke PASSED (handoff 65): Assign showed `Current total 2,652k` and the no-weights state; Balance showed totals without horizontal overflow or weight Avg labels. Only GETs appeared, with no console errors.
- Public `index-5dIAUgQj.js` SHA256 `b3f78cd7daba401cd67513e69fced2d6bf989e8a0b44b9e7f840d28a742d5c12` matched the release. Backend remained `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061, without restart. Config returned 200 and anonymous access 401. Protected signups/assigned/locks matched before and after: Main 22/18/18, Lazy 118/89/71. Backup `.local/weight-totals-1-backup-20261030T012727Z/dashboard.sqlite3`: 1,232,896 bytes, SHA256 `4a86e9aa42e477d87267e1bb9e77df8f6297bc3c6f02eac0ccb503f7a13bdeee`, integrity OK and all table counts matched. Evidence `/tmp/wu-weight-totals-release/`. Frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 8c7b5a8c29c6dab65801879cf20226f94e7efc7c`.

## Roster hotfix release — 2026-10-29

- Previous frontend: `roster-hotfix-1`, `8c7b5a8c29c6dab65801879cf20226f94e7efc7c`, PR #57. Only hosting clans with assigned accounts count toward the missing-capacity warning, shown as one line. Unsaved roster navigation uses an in-app Discard / Keep editing dialog; in-flight saves show OK-only wait copy. Assign-mode pool filters still preserve selections without a discard prompt. Missing weights has one queue-level `Enter weights as: Loot | Full` control, default Loot, with unchanged save payloads and explicit Save.
- Frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 30676446e559cab33d108aeb68711e74c8b98a33`. Backend remains `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061; no service or bot restart. Public `index-DKL_Envz.js` SHA256 `e077320fdc59a84311fba3c28069e3ea60f7b633fff9999063f8595164165b20` and release assets matched. Config returned 200 and anonymous access 401. Claude's read-only owner 360px smoke PASSED (handoff 62): one two-clan capacity line, one top weight-unit switch, and a dirty weight Discard opened Clan settings. Only GETs and Cloudflare's beacon appeared; no application writes or console errors.
- Backup `.local/roster-hotfix-1-backup-20261030T002634Z/dashboard.sqlite3`: 1,224,704 bytes, SHA256 `b116d76b7a4e0153c56020dce1eab445b1813348148d84faff5da9a42c2863ba`, integrity OK and all table counts matched. Protected signups/assigned/locks matched immediately before and after this release: Main 22/18/18, Lazy 118/89/71. Accepted branch: 899 frontend tests, TypeScript/build and isolated layout passed; the clean tagged release matched the accepted asset hash. Evidence `/tmp/wu-roster-hotfix-release/`. The duplicate `playerDirty` dialog for Fill spot / Signup Details was fixed in weight-totals-1.

## Roster readability release — 2026-10-29

- Previous frontend: `roster-readability-1`, `30676446e559cab33d108aeb68711e74c8b98a33`, PR #56. Desktop Accounts columns, shared MapPin location labels, slim publication status, separate amber signup changes and red shortage, edge fades, and no-weight total copy. Claude accepted the fixture review (handoff 55); 883 frontend tests, TypeScript/build, layout and four of five targeted mutations passed. Public `index-DWX3fCZu.js` SHA256 `48cf0177d49a4a1a25393fc1bb609ca65417b6a1a3d64123cf2dfdaea1704a18` matched the release.
- **Initial phone smoke FAILED** (handoff 56): 23 missing-capacity rows pushed the page down; a pre-existing native weight-draft confirmation silently trapped Android navigation; per-row Loot/Full toggles looked selected. The live release remained in place until roster-hotfix-1 addressed these issues. Readability's own backup `.local/roster-readability-1-backup-20261029T232554Z/dashboard.sqlite3` passed integrity/count checks; Main 22/18/18 and Lazy 118/92/74 matched across that deployment. Backend stayed at `f95830b`/PID 2249061 with no restart. Evidence `/tmp/wu-roster-readability-release/live-proof.json`. Do not describe this initial smoke as passed.

## Staff navigation release — 2026-10-29

- Previous frontend: `staff-nav-1`, `95808221f85200c3f51a9a036a6fbb266b2eda57`, PR #54. Flat staff groups, distinct icons and unchanged routes/permissions. Automatic current-group opening never persists; only explicit choices do. The tour temporarily shows only its target group.
- Frontend-only rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py ae511de81bde1a2220fa51f604125099a9caecee`. Backend remains `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061; no restart or bot change. Public `index-Dd77bclu.js`, SHA256 `a9745e061c0092a2b6baa8a85f74f297adc50305a80333e2d581290396d34a61`; index and 47 assets match the manifest, config 200, anonymous seasons 401, journal clean. Claude read-only owner smoke PASSED (handoff52): correct flat menu and saved preferences, no dialogs or errors.
- Backup `.local/staff-nav-1-backup-20261029T220729Z/dashboard.sqlite3`: 1,216,512 bytes, integrity OK and all 58 table counts matched. Protected records unchanged: Main signups/assigned/locks 22/18/18, Lazy 118/92/73. Clean tagged checkout: 865 tests, TypeScript/build passed. Full isolated layout passed at 360×800 and 1440×1000; five mutations caught. Evidence `/tmp/wu-staff-nav-release/`; no database restore for frontend rollback.
- Used the established recursive scratch staging helper for nested assets; installed helper and service config unchanged. Deferred moderation copy: `ModerationWorkspace.tsx` eyebrow “Server tools” belongs to the moderation batch.

## Owner prank speed release — 2026-10-29

- Previous frontend: `owner-prank-3`, `ae511de81bde1a2220fa51f604125099a9caecee`, PR #52. Cards advance immediately while confirmed progress writes serialize; all 13 private card images preload. An uncertain failure halts dependent writes without notification retries; cards remain viewable with an error, and reload resumes confirmed progress. Completion and replay remain server-confirmed.
- Frontend-only rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py b200c77d67f525a4a1afed515e2baed34dc31dd2`. Backend stays `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061; no restart or bot changes. Public `index-BBPDdxUl.js`, SHA256 `f9404755282073e043a96e9a533279589147bef9f3d202c28864111ad9fb7867`; index plus 47 assets match the manifest, config 200, anonymous seasons 401, clean journal. Claude infrastructure smoke PASSED (handoff 49), including anonymous prank state 404. Ruggie's replay experience check remains separate; no live DM delivery claim.
- Backup `.local/owner-prank-3-backup-20261029T212323Z/dashboard.sqlite3`: 1,216,512 bytes, SHA256 `9ac153db6f69019f75813df33988175bda8c73109a723ef4445325de99417d0c`, integrity OK, all 58 table counts matched. Protected signups/assigned/locks unchanged: Main 22/18/18, Lazy 118/92/73; publication/rule/weight/image records unchanged. Clean tagged checkout: 865 frontend tests, TypeScript/build passed. Accepted branch: full isolated layout passed. Evidence `/tmp/wu-owner-prank-3-release/`.
- Used the previously verified recursive scratch staging helper for nested assets; no installed helper or service configuration edits. No database restore for frontend rollback.

## Tour copy release — 2026-10-29

- Previous frontend: `tour-copy-1`, `b200c77d67f525a4a1afed515e2baed34dc31dd2`, PR #50. Tour card 5d now says “This button signs you up” and shows its practice guidance in two separate lines; review buttons visibly say “Change CWL” and “Change accounts”. Frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 567cd2d37acdff6d27be62e42dfe8ceebb9df789`.
- Backend remains `owner-prank-1`, `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061; no restart. Bot unchanged. The public `index-DYh42jNc.js` and affected asset hashes matched the release. Config returned 200, anonymous access 401, and Claude's read-only smoke PASSED (handoff 47). This smoke did not test live owner DM delivery; Ruggie reported that the prank looks good but pauses between cards; entry 45 tracks the speed fix.
- Backup `.local/tour-copy-backup-20261029T205253Z/dashboard.sqlite3`: 1,216,512 bytes, SHA256 `b66137ba1c45ead853a3ec90c4aa8b4cff535fb54ef2c8d5607d5929aefd7df5`, integrity OK. All 58 table counts matched. Protected signups/assigned/locks stayed Main 22/18/18 and Lazy 118/92/73. The clean tagged checkout passed 850 frontend tests and TypeScript/build; the accepted frontend branch passed the full isolated layout suite. Evidence: `/tmp/wu-tour-copy-release/live-proof.json` and `backup-verification.json`.
- The installed `stage-release.py` first failed while handling the nested `assets/tour` directory. A corrected scratch copy staged the release; no production activation occurred before that correction. The original installed helper still needs its nested-assets handling fixed. Inode recovery removed only regenerable dependencies from inactive checkouts; evidence `/tmp/wu-tour-copy-release/inodes.json`.

## Owner prank release — 2026-10-29

- Previous frontend: `owner-prank-2`, `567cd2d37acdff6d27be62e42dfe8ceebb9df789`, at `/home/ruggie/.local/share/wu-dashboard/releases/567cd2d37acdff6d27be62e42dfe8ceebb9df789/`. It starts on the first dashboard page, including the PWA Tasks landing page, and defers while an editor is dirty or another dialog is open. Its frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py f95830b5b774ba34b29f4756a1cc9e3747148f1b`.
- Backend remains `owner-prank-1`, `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, at `/home/ruggie/.local/share/wu-dashboard/backend/f95830b5b774ba34b29f4756a1cc9e3747148f1b/`; no restart for owner-prank-2. Bot unchanged. The earlier backend rollback is `8e0ee01337db50da8f2f289d257449c46440a440`; disable `PRANK_ENABLED` in the private environment file before a backend rollback. Retain the additive `owner_prank_state` table and all other database data.
- Owner-prank-2 backup `.local/owner-prank-2-backup-20261029T202118Z/dashboard.sqlite3`: 1,216,512 bytes, SHA256 `1bbadbf3926fa83be3b43db5103982dfcfea5b3e52f2ecc460e23b34bd0183ba`, integrity OK, all table counts matched. Protected signups/assigned/locks stayed Main 22/18/18 and Lazy 118/92/73. The owner-prank-1 migration backup is `.local/owner-prank-backup-20261029T194759Z/dashboard.sqlite3`.
- Public `index-BGemXK8m.js` SHA256 `615d4d3959b1c2edce25867a3e994bc6056d5c3345f1a146fc40204ec9a4e97d`; release entry `index.html` SHA256 `9af0db3958c2abfa75bc46f8a97b82975cb57abc4480b2dde95659d3ea70850e`. Claude read-only infrastructure smoke passed (handoff 44): public entry matched byte for byte, current symlink and backend cwd matched, anonymous prank state returned 404. Ruggie reported that the prank looks good but pauses between cards; entry 45 tracks the speed fix; no live DM delivery has been verified by Codex.
- Owner-prank-2: 850 frontend tests, TypeScript/build. Evidence `/tmp/wu-owner-prank-2-release/live-proof.json` and `backup-verification.json`. Owner-prank-1 backend: accepted 4,807 tests with 21 skipped; evidence `/tmp/wu-owner-prank-release/live-proof.json`.

```bash
# Frontend-only rollback from owner-prank-2 to owner-prank-1; backend stays unchanged.
/home/ruggie/.local/share/wu-dashboard/switch-release.py f95830b5b774ba34b29f4756a1cc9e3747148f1b
```

For an additional rollback of the original owner-prank backend, first set `PRANK_ENABLED=false` in the private `.local/cwl-web.env`, then use:

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py ef90834282142b1d924a9f24077d39f9b95105a4
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/8e0ee01337db50da8f2f289d257449c46440a440\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
```

Verify readiness, runtime cwd and public hashes after rollback. Never restore a database to roll back code.

## Historical rollback targets (verified through 2026-10-29)

- **Previous frontend — Member signup polish (2026-10-29):** `ef90834282142b1d924a9f24077d39f9b95105a4`, tag `signup-polish-1`, PR #44. Prior release docs merged through PR #43.
  - Release `/home/ruggie/.local/share/wu-dashboard/releases/ef90834282142b1d924a9f24077d39f9b95105a4/`. Backend unchanged at `8e0ee01`, PID 1961058; no restarts.
  - Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 539853ec37b62ad67a5157a8c10234688fc28af9`. Restore shared `assets/tour/SOURCES.md` from that release if rolling back provenance too. No database restore.
  - Verified backup `.local/signup-polish-backup-20261029T175358Z/dashboard.sqlite3`: 1,204,224 bytes, integrity OK, all 57 table counts matched. Main 21/18/18 and Lazy 114/92/73 unchanged (signups/assigned/locks), publications and protected records identical. Transient OAuth/session table activity is excluded only from activation equality, not backup verification.
  - Public `index-CcecPS0C.js`, SHA256 `d98a05b60ffca4c414f91fe7dac4c5de9de7527d1f574bdcda3289fc413d86ca`; index and 45 assets matched the manifest. Config 200, anonymous seasons 401, clean journal.
  - 804 frontend tests, TypeScript/build and full isolated layout passed. No backend source changes; prior backend suite 4,799 passed, 21 skipped. Claude smoke PASSED (handoff 30): 360px signup copy/art, icons, account menu, no overflow, GET only. Evidence `/tmp/wu-signup-polish-release/`.

- **Previous frontend — Signup card + tour refinements (2026-10-29):** `539853ec37b62ad67a5157a8c10234688fc28af9`, tag `signup-card-1`, PR #42.
  - Release `/home/ruggie/.local/share/wu-dashboard/releases/539853ec37b62ad67a5157a8c10234688fc28af9/`. Backend unchanged at `8e0ee01`, PID 1961058; no services restarted.
  - Frontend-only rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 8e0ee01337db50da8f2f289d257449c46440a440`. No backend restart or database restore.
  - Backup `.local/signup-card-backup-20261029T163441Z/dashboard.sqlite3`: 1,204,224 bytes, integrity OK, all 57 table counts matched. Main 21/18/18 and Lazy 114/92/73 unchanged (signups/assigned/locks), including publication and protected records.
  - Public `index--G6lVqgC.js`, SHA256 `52eff54228f85c7d0c0db4eac26c44ea550c6e2e3c37f2f13636226e7c3426e1`; public index and affected assets matched the manifest. Config 200, anonymous seasons 401, clean journal.
  - 788 frontend tests, TypeScript/build and isolated layout passed; 78 tour measurements, 24 cleanup scenarios and both required mutations passed. No backend source changed; prior 4,799 backend tests passed. Claude smoke PASSED (handoff 23): red card and dates at 360px, tour copy/replay, no overflow, GET only. Evidence `/tmp/wu-signup-card-release/`.

- **Previous frontend/backend — Tour/deadline hotfix (2026-10-29):** `8e0ee01337db50da8f2f289d257449c46440a440`, tag `tour-deadline-1`, PR #40.
  - Frontend/backend: `/home/ruggie/.local/share/wu-dashboard/{releases,backend}/8e0ee01337db50da8f2f289d257449c46440a440/`. Bot remains `16cc79e`; no bot restart.
  - Rollback frontend with `/home/ruggie/.local/share/wu-dashboard/switch-release.py 16cc79e7db39e3aaadf99c99117994b9103a47e8`; set only `release.conf` WorkingDirectory to `/home/ruggie/.local/share/wu-dashboard/backend/16cc79e7db39e3aaadf99c99117994b9103a47e8`, then `systemctl --user daemon-reload` and `systemctl --user restart wu-cwl-demo-web.service`. Restore shared `assets/tour/SOURCES.md` from that previous release if rolling back its provenance too. Never restore the DB for a code rollback.
  - Backup `.local/tour-deadline-backup-20261029T151849Z/dashboard.sqlite3`: 1,204,224 bytes, integrity OK, 57 table counts match. Main 21/18/18 and Lazy 114/92/73 unchanged (signups/assigned/locks), along with all protected records.
  - Public `index-DUNRfMkr.js`, SHA256 `25bdc11e4013c79ef2a70e10d15c6ecca02f27e823abd5e201fe05d68a2207c9`; 42 asset hashes verified. Two readiness 200s by 6.42s, isolated backend cwd verified, clean journal with `refreshed=1 failures=0`.
  - 782 frontend / 4,799 backend passed, 21 skipped; typecheck/build/layout and 24 cleanup cases passed. Claude smoke PASSED (handoff 17); Ruggie ran the real-page tour. November deadline correctly uses the stored October campaign: Oct 30 21:00Z; placements Oct 31 21:00Z. The initial Oct 29 expectation was corrected by Claude; the first attempt was safely rolled back before retry. Evidence `/tmp/wu-tour-deadline-retry/`.

- **Previous frontend/backend; current bot — Member tour + timing (2026-10-29):** `16cc79e7db39e3aaadf99c99117994b9103a47e8`, tag `member-tour-1`, timing PR #38 and tour PR #39.
  - Frontend/backend: `/home/ruggie/.local/share/wu-dashboard/{releases,backend}/16cc79e7db39e3aaadf99c99117994b9103a47e8/`; bot at the same SHA. Rollback all three to `5539cba3c800d91372fd5c6adc62564a758ddff4` using switch-release, release.conf + daemon-reload/dashboard restart, and bot reset/restart. Never restore the database for a code rollback.
  - Backup `.local/member-tour-backup-20261029T122118Z/dashboard.sqlite3`: 1,196,032 bytes, integrity OK, 57 table counts matched. Main 19/18/18 and Lazy 113/92/73 unchanged.
  - 774 frontend / 4,797 backend passed (21 skipped, 126 subtests); typecheck/build/layout including 78 tour measurements passed. Public `index-CKbJjEBO.js`, 28 asset hashes, backend cwd and bot startup verified. Timing refresh completes in 5.8s every five minutes.
  - Claude smoke **PASSED WITH DEFECTS — keep live**: 360px date line/invite/art, runtime/hashes, zero writes. Ruggie sees dates in Discord but the wrong campaign month. Original missing-date timeout fixed; wrong-month and real-page tour defects were fixed by tour-deadline-1; remaining spotlight sizing and copy refinements are queued under handoff prompt 11. Evidence `/tmp/wu-tour-release/live-proof.json`.

- **Previous frontend, backend and bot — Member signup (2026-10-29):** `5539cba3c800d91372fd5c6adc62564a758ddff4`, tag `member-signup-1`, PR #37; moderation preservation merged first through PR #36.
  - Frontend and backend under `/home/ruggie/.local/share/wu-dashboard/{releases,backend}/5539cba3c800d91372fd5c6adc62564a758ddff4/`; bot `/home/botrunner/wu-bot` at the same SHA.
  - Previous frontend/backend `2279c95c3bc62ac74447c4a66a0a924dde45bda4`; previous bot `2d7d2c92c246db886994dee8a3a515b6e0bf1076`.
  - Backup `.local/member-signup-backup-20261029T044244Z/dashboard.sqlite3`: 1,167,360 bytes, integrity OK, all 57 table counts matched; Main 19/18/18 and Lazy 95/92/73 signups/assigned/locks unchanged.
  - 761 frontend / 4,792 backend tests passed (21 skipped), typecheck/build/layout passed. Public `index-BosjyeFk.js` and 28 hashes verified; dashboard readiness and bot startup/gateway passed. Evidence `/tmp/wu-member-signup-release/retry-live-proof.json`.
  - Claude read-only web smoke passed; Ruggie confirmed private Discord My signups and accounts: "Yes that looks fine". Date-line defect: fix in progress (handoff prompt 01); the current 1.5-second Mongo budget is too short.
  - Rollback frontend with `switch-release.py 2279c95c3bc62ac74447c4a66a0a924dde45bda4`; set only `release.conf` WorkingDirectory to the matching backend directory, daemon-reload and restart dashboard. Bot rollback (only when approved): `sudo -n -u botrunner git -C /home/botrunner/wu-bot reset --hard 2d7d2c9`, then `sudo -n systemctl restart wu-bot.service`. Never restore the DB to roll back code.

- **Previous frontend + backend — Roster images:** `2279c95c3bc62ac74447c4a66a0a924dde45bda4`, tag `roster-images-1`, PR #35.
  - Release root `/home/ruggie/.local/share/wu-dashboard`: frontend `releases/2279c95c3bc62ac74447c4a66a0a924dde45bda4/`; backend `backend/2279c95c3bc62ac74447c4a66a0a924dde45bda4/`, PID 1639904 verified.
  - Previous frontend `190313b81f4c8373dc08f5a63fca966c6caffab2`; previous backend `73fe3fa92d8d0d89491be6e350c130b9d375aaaf`.
  - Backup `/nvme0n1-disk/Projects/Bot - Warriors United/.local/roster-images-backup-20261029T030832Z/dashboard.sqlite3`: 1,142,784 bytes, integrity OK, all 54 existing table counts matched. Main 19/18/18 and Lazy 95/92/73 signups/assigned/locks unchanged.
  - The three additive image tables stay on rollback; never restore the DB to roll back code.
  - Public `index-DuQyJREr.js` and feature hashes matched. 753 frontend tests; 4,775 backend passed, 21 skipped; M16 killed. Claude read-only 360px smoke PASSED: Announcements loads, authenticated image reads 200, anonymous endpoints 401, no writes. November is hidden: channel pickers, statuses and Preview were not visible and were not checked live.
  - Evidence `/tmp/CWL-roster-images-release-2279c95.html` and `/tmp/wu-roster-images-release/live-proof.json`.

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py 190313b81f4c8373dc08f5a63fca966c6caffab2
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
```

- **Previous frontend — Declaration:** `190313b81f4c8373dc08f5a63fca966c6caffab2`, tag `declaration-1`, PR #34.
  - Release: `/home/ruggie/.local/share/wu-dashboard/releases/190313b81f4c8373dc08f5a63fca966c6caffab2/`.
  - Previous frontend / rollback: `c767b55c010dd0de82416301a2c60057775a3662`; command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py c767b55c010dd0de82416301a2c60057775a3662`.
  - Backend unchanged: `backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf`, PID 1366655, no restart.
  - Backup: `.local/declaration-backup-20261029T003303Z/dashboard.sqlite3`; 1,142,784 bytes, integrity OK, all 54 tables matched.
  - Public `index-B4f6VDw2.js` and 16 hashes verified; Main 19/18/18 and Lazy 93/92/73 signups/assigned/locks unchanged, all protected checksums identical.
  - 736 frontend tests, TypeScript/build and layout passed. Claude read-only 360px smoke PASSED: hidden version 1 message, no clan list, no errors. Clan sections verified on preview.
  - Evidence: `/tmp/wu-declaration-release/live-proof.json`.

- **Previous frontend — Details:** `c767b55c010dd0de82416301a2c60057775a3662`, tag `details-1`, PR #33.
  - Release: `/home/ruggie/.local/share/wu-dashboard/releases/c767b55c010dd0de82416301a2c60057775a3662/`.
  - Previous frontend / rollback: `73fe3fa92d8d0d89491be6e350c130b9d375aaaf`; command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 73fe3fa92d8d0d89491be6e350c130b9d375aaaf`.
  - Backend unchanged: `/home/ruggie/.local/share/wu-dashboard/backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf/`, PID 1366655; no restart.
  - Backup: `.local/details-backup-20261028T232301Z/dashboard.sqlite3`; 1,142,784 bytes, integrity OK, all 54 table counts matched.
  - Public `index-CsYgjk4R.js` and 15 asset hashes matched; Main 19/18/18 and Lazy 92/90/71 (signups/assigned/locks), publications, member season, signup activity and manual/saved weight checksums stayed identical.
  - 719 frontend tests, TypeScript/build and layout passed in the clean tagged checkout. Layout required `WU_TEST_PYTHON` to point to the existing interpreter.
  - Claude read-only 360px smoke PASSED, relayed by Ruggie: open/Next/focus/Back retain account URLs, direct link opens Ace, clean Save disabled; no errors or writes.
  - Evidence: `/tmp/wu-details-release/live-proof.json`.


- **Previous frontend/backend — Announcements:** `73fe3fa92d8d0d89491be6e350c130b9d375aaaf`, tag `announcements-1`, PR #32.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/73fe3fa92d8d0d89491be6e350c130b9d375aaaf/`.
  - Backend: `/home/ruggie/.local/share/wu-dashboard/backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf/`; approved isolated restart, PID 1366655 at verification.
  - Previous frontend / rollback: `4404c3672872ebff706519402efa4ee9940d3a60`; previous backend / rollback: `61290a4ce2b87611119483d6376b879a675aeb81`.
  - Backup: `.local/announcements-backup-20261028T205112Z/dashboard.sqlite3`; 1,138,688 bytes, integrity OK, all 54 table counts matched.
  - Deployment signups/assigned/locks unchanged: Main 19/18/18; Lazy 91/90/71. Publication v1 remains withdrawn, member season 1/revision 0, unreviewed signup activity 1 and November 2026 Manage binding unchanged.
  - Public `index-Dn86Au-2.js` and feature hashes match the manifest; config readiness passed twice consecutively; unauthenticated Manage read returns 401; clean restart journal. 681 frontend tests, 4,702 backend tests (21 skipped), TypeScript/build, layout and all four send-guard mutations passed.
  - Claude read-only 360px smoke PASSED, relayed by Ruggie: entry/backend, hidden status line, real channels/roles, Preview, Edit opened/closed with no unsaved change; zero write requests, no errors, clean journal.
  - Evidence: `/tmp/CWL-announcements-release-73fe3fa.html`, `/tmp/wu-announcements-release/live-proof.json`.

Rollback both code layers (never restore the DB to roll back code):

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py 4404c3672872ebff706519402efa4ee9940d3a60
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
readlink /proc/$(systemctl --user show -p MainPID --value wu-cwl-demo-web.service)/cwd
```

- **Previous frontend — Signup changes:** `4404c3672872ebff706519402efa4ee9940d3a60`, tag `signup-changes-1`, PR #31.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/4404c3672872ebff706519402efa4ee9940d3a60/`.
  - Backend unchanged: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`; PID 1053095, no restart.
  - Previous frontend / rollback: `00170063e15b7df43bd769f2c97b0a69bd0ebdf5`.
  - Rollback command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 00170063e15b7df43bd769f2c97b0a69bd0ebdf5` (frontend only).
  - Backup: `.local/signup-changes-backup-20261028T191131Z/dashboard.sqlite3`; 1,138,688 bytes, integrity OK, all 54 table counts matched.
  - Deployment signups/assigned/locks unchanged: Main 19/18/18; Lazy 91/90/71. Publication version 1 remains withdrawn; member season 1/revision 0 unchanged. Unreviewed signup changes 1 → 1; reviewed rows 41 → 41.
  - Public entry `index-DptKfiRQ.js` and roster hashes matched the manifest; 657 frontend tests, TypeScript/build and layout 10/10 passed. Evidence: `/tmp/wu-signup-release/live-proof.json`.
  - Claude read-only smoke PASSED, relayed by Ruggie: at 360px the shortage-first alert fits, panel opens/closes without review (1 still unreviewed), summary shows “+21 clans with no players”, inline emoji is 22px, cards are 74px, and no errors occurred.

- **Previous frontend — Player card 3:** `00170063e15b7df43bd769f2c97b0a69bd0ebdf5`, tag `player-card-3`, PR #30.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/00170063e15b7df43bd769f2c97b0a69bd0ebdf5/`.
  - Backend unchanged: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`; PID 1053095, no restart.
  - Previous frontend / rollback: `374e0995280dad7d13483a2fa655975d0af72280`.
  - Rollback command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 374e0995280dad7d13483a2fa655975d0af72280` (frontend only).
  - Backup: `.local/player-card-3-backup-20261028T173130Z/dashboard.sqlite3`; integrity OK, 54 table counts matched. Signups/assigned/locks unchanged: Main 19/18/18; Lazy 90/83/64. Publication and member-season unchanged.
  - Public entry `index-CScTR1be.js` and feature hashes matched; 634 frontend tests and clean tagged TypeScript/build passed. Evidence: `/tmp/wu-player-card-3-release/live-proof.json`.
  - Claude read-only smoke PASSED, relayed by Ruggie: release/build, backend unchanged, line 2 one line on all 19 Main cards, no errors.


- **Previous frontend — Player card v2:** `374e0995280dad7d13483a2fa655975d0af72280`, tag `player-card-2`, PR #29.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/374e0995280dad7d13483a2fa655975d0af72280/`.
  - Backend unchanged: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`; PID 1053095, no restart.
  - Previous frontend / rollback: `61290a4ce2b87611119483d6376b879a675aeb81`.
  - Rollback command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 61290a4ce2b87611119483d6376b879a675aeb81` (frontend only; no backend restart).
  - Scripted public index/feature hashes, counts, publication and member-season checks passed. Main 19/18/18 and Lazy 89/83/64 unchanged during deployment. No backup required by the approved frontend-only release prompt.
  - Claude read-only smoke PASSED, relayed by Ruggie: build, strip dot, hidden banner, 109 cards, line 3 all correct. Real long-tag line-2 polish is a separate preview batch.
  - Evidence: `/tmp/wu-player-card-2-release/live-proof.json`; 631 frontend tests and clean tagged TypeScript/build passed.


- **Previous CWL flow frontend/backend:** `61290a4ce2b87611119483d6376b879a675aeb81`, tag `cwl-flow-1`, PRs #27 (`3631408`) and #28 (`61290a4`).
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/61290a4ce2b87611119483d6376b879a675aeb81/`.
  - Backend: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`.
  - Previous frontend + backend: `1a8b035461ec46fba60f6ed4808111d3c67d87cf` (`finalize-1`).
  - Backup: `.local/cwl-flow-backup-20261028T145938Z/dashboard.sqlite3`; integrity OK, all 54 table counts matched, 1,134,592 bytes. The activation recheck found no changes, so this remained the baseline.
  - Readiness: public config returned 200 twice at 5.15/6.21 seconds; service/cwd, public entry and roster/publication/seasons hashes passed; lookup/publication unauthenticated reads returned 401. Main 19/18/18 and Lazy 87/83/64 (signups/assigned/locks), publications, weights, lineup/rules, season state and member-season remained identical.
  - Claude's read-only production smoke passed (relayed by Ruggie): sidebar, Build/strip/cards, Clan settings Add panel (Close only), Seasons and Finalize; no errors. No production writes during smoke.
  - Validation: 607 frontend tests, typecheck/build; 4,701 backend passed, 21 skipped.

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py 1a8b035461ec46fba60f6ed4808111d3c67d87cf
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/1a8b035461ec46fba60f6ed4808111d3c67d87cf\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
```


- **Previous Finalize frontend + backend:** `1a8b035461ec46fba60f6ed4808111d3c67d87cf`, tag `finalize-1`, PR #26.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/1a8b035461ec46fba60f6ed4808111d3c67d87cf/`.
  - Backend: `/home/ruggie/.local/share/wu-dashboard/backend/1a8b035461ec46fba60f6ed4808111d3c67d87cf/`.
  - Backup: `.local/finalize-backup-20261028T040608Z/dashboard.sqlite3`; integrity OK, all 54 table counts matched, 1,122,304 bytes.
  - Scripted checks passed: active service/cwd, public entry and roster/publication hashes match manifest, unauthenticated publication GET returns 401. Protected data unchanged: Main 18/18/18; Lazy 84/84/65 (signups/assigned/locks), plus publications/instructions, weights and rules.
  - Authenticated metadata read and click smoke are delegated to Claude; Ruggie approved leaving the release live after scripted checks. No Publish or Hide submitted.
  - Previous frontend: `e6353fb9ef77244a6b366550f030d7fd8e75daf7`; previous backend: `c19db57523928f6fee9d6bc93d95d83fa5814bb0`.

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py e6353fb9ef77244a6b366550f030d7fd8e75daf7
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/c19db57523928f6fee9d6bc93d95d83fa5814bb0\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
```

- **Previous Weights frontend:** `e6353fb9ef77244a6b366550f030d7fd8e75daf7`, tag `weights-1`, merged via PR #25.
  - Release: `/home/ruggie/.local/share/wu-dashboard/releases/e6353fb9ef77244a6b366550f030d7fd8e75daf7/`.
  - Frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py c19db57523928f6fee9d6bc93d95d83fa5814bb0`.
  - Reactivate Weights: `/home/ruggie/.local/share/wu-dashboard/switch-release.py e6353fb9ef77244a6b366550f030d7fd8e75daf7`.
  - Backend unchanged, **no restart**: `/home/ruggie/.local/share/wu-dashboard/backend/c19db57523928f6fee9d6bc93d95d83fa5814bb0/`; PID and cwd verified before/after.
  - Backup and retained frontend snapshot: `.local/weights-backup-20261028T022902Z/`. SQLite integrity ok, 54 table counts matched, 1,122,304 bytes.
  - Season 1 protected counts unchanged: Lazy 84 signups / 84 assigned / 65 locks; Main 18 / 18 / 18; publication version 1. All 102 manual-weight rows (26 non-null), 27 saved weights and lineup rules identical.
  - Public entry and roster JS/CSS hashes match the manifest. Authenticated smoke: type/clear only, Details open/close, no Save or Publish, no console errors.
  - Clean tagged checkout with `npm ci`: 542 frontend tests, TypeScript and build passed. Three missing-guard mutations caught.
  - Rollback on count mismatch, load errors or staff-reported write issues. Never restore the database just to roll back the frontend.

- **Previous Clan settings frontend / previous backend:** `c19db57523928f6fee9d6bc93d95d83fa5814bb0`, tag `clan-settings-1`, merged via PR #24.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/c19db57523928f6fee9d6bc93d95d83fa5814bb0/`.
  - Backend: `/home/ruggie/.local/share/wu-dashboard/backend/c19db57523928f6fee9d6bc93d95d83fa5814bb0/`, clean tag archive.
  - Frontend rollback: `a65b98ecc5c8d58601ec69d3efd184419b649e73`; backend rollback: `2f7ae7a53cedd70d9485dfd75151533194c69e01` (clean pre-merge archive).
  - Backup: `.local/clan-settings-backup-20261028T011847Z/`; integrity ok, all 54 table counts matched.
  - Post-deploy signups/assignments/locks/publication and lineup rules unchanged; public asset hashes and authenticated read-only smoke passed.
  - Backend must never run from the workspace. See [isolated backend procedure](dashboard-backend-releases.md).

```bash
# Frontend rollback:
/home/ruggie/.local/share/wu-dashboard/switch-release.py a65b98ecc5c8d58601ec69d3efd184419b649e73
# Backend rollback (preserves frontend-routing.conf and storage-guard.conf):
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/2f7ae7a53cedd70d9485dfd75151533194c69e01\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user show -p WorkingDirectory,DropInPaths wu-cwl-demo-web.service
systemctl --user restart wu-cwl-demo-web.service
readlink /proc/$(systemctl --user show -p MainPID --value wu-cwl-demo-web.service)/cwd
```

To reactivate this release, use `switch-release.py c19db57523928f6fee9d6bc93d95d83fa5814bb0` and set the same drop-in's `WorkingDirectory` to `/home/ruggie/.local/share/wu-dashboard/backend/c19db57523928f6fee9d6bc93d95d83fa5814bb0/`, then daemon-reload and restart as above. Never remove the drop-in to roll back: that would restore the unsafe workspace directory.


- **Previous Compare clans release:** `a65b98ecc5c8d58601ec69d3efd184419b649e73`, tag `compare-clans-1`, merged via PR #23.
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/a65b98ecc5c8d58601ec69d3efd184419b649e73/`
  - Public entry and roster/publication feature hashes verified; authenticated read-only smoke passed; protected counts unchanged.
- **Older Release 1 rollback:** `fea7e668b21823d9e31943867e25654ce0d60bf8`.
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/fea7e668b21823d9e31943867e25654ce0d60bf8/`
  - Command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py fea7e668b21823d9e31943867e25654ce0d60bf8`
  - Verified DB backup and frontend snapshot: `.local/compare-clans-backup-20261027T230301Z/`. UI rollback must never restore this database over later edits.


- **Original roster UI, before Release 1:** `bad19e1bf3b71cddcb87e26f9f926c676e87a31b` (parent of the first Release 1 commit, `ee1023e`).
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/bad19e1bf3b71cddcb87e26f9f926c676e87a31b/`
  - Clean detached checkout build; locked dependencies; 396 frontend tests passed; TypeScript and Vite build passed. Artifact hashes are recorded in `/home/ruggie/.local/share/wu-dashboard/manifests/bad19e1bf3b71cddcb87e26f9f926c676e87a31b.json`.
  - Standby only: built and staged, **not activated**. Production now runs the CWL flow frontend and backend listed above.
  - This restores the entire older frontend, including older moderation screens. It does not revert backend code or data. Live compatibility has not been smoke-tested; use the preserved live snapshot when that is the appropriate rollback.
  - Activation, only when explicitly authorized: `/home/ruggie/.local/share/wu-dashboard/switch-release.py bad19e1bf3b71cddcb87e26f9f926c676e87a31b`
- **Pre-deploy snapshot (already includes early Release 1 UI):** `/home/ruggie/.local/share/wu-dashboard/releases/snapshot-20261027T171555Z/`. This is not the original roster UI.
  - Command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py snapshot-20261027T171555Z`
- **Return to deployed Release 1:** `/home/ruggie/.local/share/wu-dashboard/switch-release.py fea7e668b21823d9e31943867e25654ce0d60bf8`

Switching the frontend never rolls back signups, assignments, locks or publications. Never restore a database merely to roll back UI assets.
