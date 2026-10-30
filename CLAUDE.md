# CLAUDE.md — Warriors United dashboard (CWL roster)

Read before any work on the CWL roster:
1. `docs/cwl-roster-redesign.md`: decisions, behavior contracts, backend facts, release status, next stages.
2. `docs/roster-ui-patterns.md`: UI system: shapes, states, components, layout targets, sources.

## Process (these win on conflict)
Repo process rules: `.claude/rules/orchestration.md`, `docs/agent-orchestration.md`, `docs/editing-this-repo.md`, `AGENTS.md`. Where this file differs from `~/.claude/CLAUDE.md`, this file wins.
- **Roles.** Claude Code = planner and reviewer. It reads the code, walks Ruggie through decisions one item at a time (restate in plain terms, recommend with pros/cons, wait for "next"), writes ONE Codex prompt per decision batch, and reviews Codex's HTML report. It does not edit code or docs, build, commit, push or deploy in this workspace; it may use read-only agents for review. **Codex is the only writer**: code, docs, commits, pushes, deploys. One writer avoids conflicting edits. For this project Codex replaces the `builder` role in `.claude/rules/orchestration.md`.
- **Loop.** Walkthrough → decisions confirmed → one Codex prompt (scope, exact behavior, contracts, checkpoints, red-team rule, self-contained HTML review with embedded screenshots at 360×800 and 1440×1000, exact doc update) → Codex implements → Ruggie brings back the HTML report → Claude Code reviews it against the decisions and docs, lists every issue (evidence vs inference), and writes the next prompt.
- **Record.** `docs/cwl-roster-redesign.md` is the decision record. Every Codex prompt carries its exact update (decisions, status, Later list).
- No `sed -i` / `awk` / `perl -pi`. Commit only what Ruggie or a Ruggie-approved prompt asks for. Conventional Commits. No Co-Authored-By or Claude-Session trailers.

## Stack
- Frontend: `web/cwl/`, React 19 + TypeScript + Vite, plain CSS, Lucide icons, React Aria (custom menus). Routing: custom History API (`dashboardHistory.ts`, `App.tsx`), not React Router.
- Backend: Python. Roster logic in `app.py` (`_auto_plan`), `cwl_balance.py`, `cwl_permissions.py`, `roster_locations.py`. API prefix `/api/cwl`.
- Shared roster UI: `web/cwl/src/rosterUi/primitives.css` (tokens, chip/card state rules), `ActionPanel.tsx`, `Roster*.tsx`.
- Checks: frontend tests (vitest), TypeScript check, Vite build, scoped Prettier, `git diff --check`, full backend suite in a network-isolated copy. No lint script exists; never claim lint ran.

## Safety rules (non-negotiable)
- Never use the production database or live API in development or tests. Use isolated fixture data only (26-, 65- and 125-account fixtures exist). For frontend-only releases, Ruggie separately approved a read-only production DB backup and pre/post count verification as standing release steps (2026-10-29 Codex chat, recorded in `/home/ruggie/wu-handoff/ruggie.md`). This does not authorize application data writes, backend/bot/schema changes or service restarts.
- Production serves a `current` symlink → `releases/<commit-sha>/`, outside the workspace (set up in the `fea7e66` deploy). A workspace `npm run build` must never affect production. Deployment paths verified through the October 30 weight-range release:
  - Current symlink: `/home/ruggie/.local/share/wu-dashboard/current`
  - Releases directory: `/home/ruggie/.local/share/wu-dashboard/releases/`
  - Latest recorded frontend: `back-to-top-1` / `a8031084eed09ee89b8063828d4bc2c5d40cc628`, activated with public hashes verified, Claude smoke pending at this checkpoint. Backend remains weight-range `23235ccf2671dfe5675f0bc98d38ab11a011ab09`; bot remains `b517afd46ecfa9cc08488798eba53393ed5b649f`. See [frontend releases](docs/dashboard-frontend-releases.md) for the frontend-only rollback to 23235cc before any older layered rollback.
  - Historical rollback snapshot: `/home/ruggie/.local/share/wu-dashboard/releases/snapshot-20261027T171555Z/`.
  - Weight-range rollback restores frontend/backend to `b517afd` with the bot unchanged. Trigger-delete rollback restores all three to `6a2f8d7`. Follow the [guarded manual procedure](docs/dashboard-backend-releases.md#guarded-manual-rollback-for-trigger-delete-and-weight-range); a later frontend release must be rolled back first. Never restore databases for code rollback.
- Never report "not deployed" (or "deployed") without checking which asset hashes production is actually serving. (On 2026-10-27, a workspace build went live by accident because the old setup served `web/cwl/dist` directly.)
- Deploy procedure: back up and verify the DB → record live counts per season/pool (signups, assigned, locks, publication version) → build from a clean checkout of a tagged commit into `releases/<sha>/` → atomic symlink switch → read-only smoke test → counts must match exactly. Rollback = point the symlink back at the previous release.
- Frontend-only unless Ruggie explicitly approves backend, schema, endpoint or policy changes. If a fix seems to need one, stop and ask.
- No UI path may write signups, assignments, locks, weights or publications without an explicit user action through the existing endpoints and their revision checks.
- The former moderation-file protection is retired: landed via PR #36; retired 2026-10-29 with Ruggie’s approval. The four preserved workspace files were verified byte-identical to origin/main before restoring them to workspace HEAD. Run Prettier only on files you changed.

## Red-team checklist (every change, before commit; report how each item was verified)
1. List every changed file; confirm the scope.
2. Run all tests, the type check and the build, not just the new tests.
3. Can any path write without explicit confirmation (double tap, Back, closing mid-request, stale preview)?
4. Are hidden or filtered-out selections ever changed without being listed?
5. Are other seasons or pools affected?
6. Do permission-restricted actions stay hidden or blocked?
7. Network failure, timeout, expired login, concurrent staff edit: no partial or silent writes.
8. Undo and refresh restore exactly the prior state and never overwrite a later edit.
9. Do the other dashboard pages still work?
10. Before/after fixture counts (signups, assigned, locks per pool) are identical unless a change was deliberate.

## Working with Ruggie
- Terse and direct. Answer first. Assume a systems engineer; don't explain general IT concepts. Label evidence vs. inference.
- Design discussions: go one item at a time. Restate what he said in plain language, confirm, and wait for "next" before moving on.
- Ask only when the decision is his to make (product behavior, policy, scope). Give a recommendation with pros/cons.
- Keep changes small and reviewable; commit only when asked. Stop at agreed checkpoints with screenshots before continuing.
- Review artifacts must be ONE self-contained HTML file with every screenshot embedded as base64 (no relative/`/tmp` links; he reviews on other devices and in other chats). Viewports: 360×800 and 1440×1000. Include the changed files, test results, before/after counts, and the red-team results.
- When changing a script: return the full updated script.
- He reviews on his phone; mobile layout matters as much as desktop.

## Trigger-delete and weight-range releases — 2026-10-30

- `trigger-delete-1`, PR #63/tag at `b517afd46ecfa9cc08488798eba53393ed5b649f`, released frontend/backend/bot. Plain and recipient trigger messages are deleted only after a successful reply when the new default-on option is enabled. Delete failures remain visible and later success clears the warning. Claude smoke 90 passed; Codex and Claude did not post a live trigger. Ruggie's own Discord test is separate.
- `weight-range-1`, PR #64/tag at `23235ccf2671dfe5675f0bc98d38ab11a011ab09`, released frontend/backend; bot stayed at b517afd, PID 2920748 with unchanged invocation. Inclusive range bounds, descending-weight Compare and capped quick picks passed Claude's read-only 360px smoke 92, including Jujupon 179k inside Lazy.128's 172–179 range.
- Tagged checks: trigger-delete 4,839 backend / 21 skipped / 133 subtests and 908 frontend; weight-range 4,844 backend / 21 skipped / 153 subtests and 914 frontend. TypeScript/build passed for both. Verified backups, public entry/feature hashes and protected-state comparisons are in [backend releases](docs/dashboard-backend-releases.md#weight-range-1--october-30-2026).
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
  - Backend must never run from the workspace. See [isolated backend procedure](docs/dashboard-backend-releases.md).

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
