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
  - Current Compare clans build: `/home/ruggie/.local/share/wu-dashboard/releases/a65b98ecc5c8d58601ec69d3efd184419b649e73/`
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

## Standby rollback targets (verified 2026-10-27)

- **Current Compare clans release:** `a65b98ecc5c8d58601ec69d3efd184419b649e73`, tag `compare-clans-1`, merged via PR #23.
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/a65b98ecc5c8d58601ec69d3efd184419b649e73/`
  - Public entry and roster/publication feature hashes verified; authenticated read-only smoke passed; protected counts unchanged.
- **Immediate rollback (previous production):** `fea7e668b21823d9e31943867e25654ce0d60bf8`.
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/fea7e668b21823d9e31943867e25654ce0d60bf8/`
  - Command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py fea7e668b21823d9e31943867e25654ce0d60bf8`
  - Verified DB backup and frontend snapshot: `.local/compare-clans-backup-20261027T230301Z/`. UI rollback must never restore this database over later edits.


- **Original roster UI, before Release 1:** `bad19e1bf3b71cddcb87e26f9f926c676e87a31b` (parent of the first Release 1 commit, `ee1023e`).
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/bad19e1bf3b71cddcb87e26f9f926c676e87a31b/`
  - Clean detached checkout build; locked dependencies; 396 frontend tests passed; TypeScript and Vite build passed. Artifact hashes are recorded in `/home/ruggie/.local/share/wu-dashboard/manifests/bad19e1bf3b71cddcb87e26f9f926c676e87a31b.json`.
  - Standby only: built and staged, **not activated**. Production now runs the Compare clans release below.
  - This restores the entire older frontend, including older moderation screens. It does not revert backend code or data. Live compatibility has not been smoke-tested; use the preserved live snapshot when that is the appropriate rollback.
  - Activation, only when explicitly authorized: `/home/ruggie/.local/share/wu-dashboard/switch-release.py bad19e1bf3b71cddcb87e26f9f926c676e87a31b`
- **Pre-deploy snapshot (already includes early Release 1 UI):** `/home/ruggie/.local/share/wu-dashboard/releases/snapshot-20261027T171555Z/`. This is not the original roster UI.
  - Command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py snapshot-20261027T171555Z`
- **Return to deployed Release 1:** `/home/ruggie/.local/share/wu-dashboard/switch-release.py fea7e668b21823d9e31943867e25654ce0d60bf8`

Switching the frontend never rolls back signups, assignments, locks or publications. Never restore a database merely to roll back UI assets.
