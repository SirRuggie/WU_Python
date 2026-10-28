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
- Never use the production database or live API in development or tests. Use isolated fixture data only (26-, 65- and 125-account fixtures exist).
- Production serves a `current` symlink → `releases/<commit-sha>/`, outside the workspace (set up in the `fea7e66` deploy). A workspace `npm run build` must never affect production. Verified deployment paths (2026-10-27):
  - Current symlink: `/home/ruggie/.local/share/wu-dashboard/current`
  - Releases directory: `/home/ruggie/.local/share/wu-dashboard/releases/`
  - Current Announcements frontend: `/home/ruggie/.local/share/wu-dashboard/releases/73fe3fa92d8d0d89491be6e350c130b9d375aaaf/`
  - Pre-deploy rollback snapshot: `/home/ruggie/.local/share/wu-dashboard/releases/snapshot-20261027T171555Z/` (the only rollback snapshot present at verification).
  - Rollback command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py snapshot-20261027T171555Z`
- Never report "not deployed" (or "deployed") without checking which asset hashes production is actually serving. (On 2026-10-27, a workspace build went live by accident because the old setup served `web/cwl/dist` directly.)
- Deploy procedure: back up and verify the DB → record live counts per season/pool (signups, assigned, locks, publication version) → build from a clean checkout of a tagged commit into `releases/<sha>/` → atomic symlink switch → read-only smoke test → counts must match exactly. Rollback = point the symlink back at the previous release.
- Frontend-only unless Ruggie explicitly approves backend, schema, endpoint or policy changes. If a fix seems to need one, stop and ask.
- No UI path may write signups, assignments, locks, weights or publications without an explicit user action through the existing endpoints and their revision checks.
- The workspace is shared with a concurrent moderation task. Never format or edit its files (`ChannelCombobox.tsx`, `ModerationSettings.tsx`, `moderationSettingsModel.ts`, and the rest of the moderation work). Run Prettier only on files you changed.

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

## Standby rollback targets (verified 2026-10-28)

- **Current frontend + backend — Announcements:** `73fe3fa92d8d0d89491be6e350c130b9d375aaaf`, tag `announcements-1`, PR #32.
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


- **Previous CWL flow frontend / current backend:** `61290a4ce2b87611119483d6376b879a675aeb81`, tag `cwl-flow-1`, PRs #27 (`3631408`) and #28 (`61290a4`).
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
