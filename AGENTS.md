# Repository working rules

These rules apply to future work in this repository. They record the owner's
request for organized implementation, cleanup, and adversarial review.

## Feature boundaries

- Put bot lifecycle and Discord transport in `extensions/`; keep reusable domain
  logic and services in `utils/`. Shared services and bot tasks must not import
  dashboard modules to obtain reusable functionality.
- Put HTTP authorization and request/response adaptation in `cwl_web/`. Use public
  provider methods; do not reach into private provider methods from feature code.
- Give a persistent feature one storage owner. Keep collection selection, query
  indexes, concurrency checks, and durable receipt semantics there. Preserve
  existing data and routes during refactors; document any actual migration.
- Split substantial UI work by responsibility. Format source for humans; do not
  compress an entire editor or stylesheet into one line. Reuse existing public
  helpers before adding another abstraction.
- Keep routine controls and current status visible. Put occasional testing,
  verbose history, and explanations behind clearly labeled disclosures; keep
  errors discoverable and avoid fetching previews while their section is closed.
- Remove code, styles, imports, and temporary fixtures made obsolete by a change.
  Do not leave an abandoned implementation alongside the replacement.

For dashboard workflow changes, follow `docs/dashboard-interaction-standard.md`
and record the scope of the usability/accessibility checks.

## Required completion review

For meaningful feature changes, review the affected feature end to end before
calling it complete. This is an evidence-based review, not a promise of no bugs.

- Check authorization, destination ownership, malformed inputs, mention scope,
  external text rendering, and partial/unavailable upstream data.
- Check concurrent edits, duplicate submissions, restarts, cancellation, partial
  delivery, and stale UI responses where applicable. Do not automatically retry
  a notification when Discord may already have accepted it.
- Test important behavior and failure modes, not just implementation details.
  Run the relevant regression suites and frontend build for UI changes. Inspect
  significant UI changes at narrow and wide widths using isolated sample data.
- Record what was tested and any unresolved limitations. Never report mocked
  notification tests as proof of live Discord or push-notification delivery.
- For deployment authorized by the user, verify the pushed revision, runtime
  imports/startup, service health, and served dashboard assets. Do not send live
  test messages unless the recipient and destination are authorized.

For war reminders, run `./.venv/bin/python tools/check_war_reminders.py`. The
architecture tests enforce the shared-service and storage boundaries; add
regressions for any newly discovered failure. See `docs/war-reminders.md` for
storage lifetime, scheduling, and delivery guarantees.

## Production frontend isolation

- The production dashboard frontend is served from
  `/home/ruggie/.local/share/wu-dashboard/current`, an atomic symlink to an
  external immutable release directory. Workspace `web/cwl/dist` is never a
  deployment target. Do not restore the old shared-output configuration.
- Build deployable frontend assets only from a clean tagged isolated checkout;
  follow `docs/dashboard-frontend-releases.md`. Preserve other deployed features.
- Never report "not deployed" without fetching the public page and comparing its
  entry and affected feature asset hashes to the known deployed release.
- For approved deployments, record backup/count evidence, retain rollback assets,
  verify public hashes, and use read-only smoke checks unless writes are explicitly
  authorized. A successful local build is not deployment evidence.

## Run off Shaka approval

"Shaka" is Claude, the reviewer. When Ruggie says "run off Shaka approval" (or "merge on Shaka approval") for a task or PR, Ruggie has already approved the merge. Do not ask Ruggie again.

- Merge the PR when all of these are true:
  1. Shaka's verdict says APPROVED and names the PR's current head SHA (full or first 7 characters).
  2. The PR head SHA has not changed since that verdict. Any new commit voids the approval; get a new Shaka review.
  3. Required checks pass and the PR has no merge conflicts.
- Shaka's verdict reaches you as text that Ruggie pastes or as a comment on the PR. Both count.
- If the verdict says REWORK, fix the must-fix items, push, and request a new Shaka review. Do not merge.
- After the merge, report the merge commit SHA and PR URL. Then stop.
- Under the standing "Release on Shaka approval" rule below, the same APPROVED verdict also covers the release.
- It applies to the task or PR where Ruggie said it. "From now on, run off Shaka approval" makes it the standing rule until Ruggie says "ask me before merge".

## Release on Shaka approval (standing since 2026-11-07)

When Shaka's verdict says APPROVED with the PR's current full head SHA, merge AND release that work without asking Ruggie. This covers code releases of the frontend, backend and bot.

- Release only through the documented procedure (`AGENTS.md` "Deploy procedure", `docs/dashboard-frontend-releases.md`, `docs/dashboard-backend-releases.md`): verified DB backup; protected counts before and after; build from a clean checkout of the merged commit; atomic switch; read-only smoke; counts must match exactly.
- On any count mismatch, failed smoke, failed readiness or startup error: roll back at once to the previous release, then post BLOCKED with the evidence. Never restore a database to roll back code.
- Post DONE with the release SHA, served asset hashes, service PIDs and the before/after counts. Shaka then posts a SMOKE entry.
- Still needs Ruggie's own words in the task (quoted in the handoff entry): schema or data migrations, backfills or any production data write, Discord posts or edits, and secret, config or systemd changes other than the normal release switch.
- "Ask me before release" from Ruggie ends this rule.

## Subagents (required for every batch)

Use the project subagents in `.codex/agents/` for every batch. One agent writes per worktree; the refuter is never the agent that built the change.

- `wu_scout` (GPT-6 Luna): find files, symbols and call sites before planning.
- `wu_builder` (GPT-6.1 Sol): implement one scoped piece and run its tests.
- `wu_refuter` (GPT-6.1 Terra): review the diff against the prompt, rerun all checks, try to prove each acceptance item false, and report ACCEPT or REWORK.
- Use the main model only for integration and judgment, or when a subagent failed twice.
- Every READY entry names which agent built, refuted and scouted what.

## Process (these win on conflict)
Repo process rules: `.claude/rules/orchestration.md`, `docs/agent-orchestration.md`, `docs/editing-this-repo.md`, `AGENTS.md`. Where this file differs from `~/.claude/CLAUDE.md`, this file wins.
- **Roles.** One writer per task. **Default: Codex writes** (code, docs, commits, pushes, deploys) and Claude Code plans and reviews: it reads the code, walks Ruggie through decisions one item at a time (restate in plain terms, recommend with pros/cons, wait for "next"), writes ONE Codex prompt per decision batch, and reviews Codex's HTML report. In this mode Claude does not edit code or docs, build, commit, push or deploy; it may use read-only agents for review. **Override:** when Ruggie tells Claude in a task to do it itself, Claude is the writer for that task only (edit, check, commit to its own branch, push, draft PR) and follows the same red-team checklist and review-artifact rules. No Codex prompt is written for the same files. The override ends with the task unless Ruggie says "from now on"; "back to Codex" restores the default. **Merge:** see "Run off Shaka approval" in `AGENTS.md`. Release: see "Release on Shaka approval" in `AGENTS.md`; migrations, data writes, Discord posts and secret/config/systemd changes still need Ruggie's word. For this project the active writer replaces the `builder` role in `.claude/rules/orchestration.md`.
- **Loop.** Walkthrough → decisions confirmed → one Codex prompt (or, on Ruggie's override, Claude builds it) (scope, exact behavior, contracts, checkpoints, red-team rule, self-contained HTML review with embedded screenshots at 360×800 and 1440×1000, exact doc update) → Codex implements → Ruggie brings back the HTML report → Claude Code reviews it against the decisions and docs, lists every issue (evidence vs inference), and writes the next prompt. If Ruggie said "run off Shaka approval", the writer merges when Shaka approves; see `AGENTS.md`.
- **Record.** `docs/cwl-roster-redesign.md` is the decision record. Every Codex prompt carries its exact update (decisions, status, Later list).
- No `sed -i` / `awk` / `perl -pi`. Commit only what Ruggie or a Ruggie-approved prompt asks for. Conventional Commits. No Co-Authored-By or Claude-Session trailers.

## Stack
- Frontend: `web/cwl/`, React 19 + TypeScript + Vite, plain CSS, Lucide icons, React Aria (custom menus). Routing: custom History API (`dashboardHistory.ts`, `App.tsx`), not React Router.
- Backend: Python. Roster logic in `app.py` (`_auto_plan`), `cwl_balance.py`, `cwl_permissions.py`, `roster_locations.py`. API prefix `/api/cwl`.
- Shared roster UI: `web/cwl/src/rosterUi/primitives.css` (tokens, chip/card state rules), `ActionPanel.tsx`, `Roster*.tsx`.
- Checks: frontend tests (vitest), TypeScript check, Vite build, scoped Prettier, `git diff --check`, full backend suite in a network-isolated copy. No lint script exists; never claim lint ran.

## Safety rules (non-negotiable)
- Never use the production database or live API in development or tests. Use isolated fixture data only (26-, 65- and 125-account fixtures exist). For frontend-only releases, Ruggie separately approved a read-only production DB backup and pre/post count verification as standing release steps (2026-10-29 Codex chat, recorded in `/home/ruggie/wu-handoff/ruggie.md`). This does not authorize application data writes, backend/bot/schema changes or service restarts.
- Production serves a `current` symlink → `releases/<commit-sha>/`, outside the workspace (set up in the `fea7e66` deploy). A workspace `npm run build` must never affect production. Deployment paths verified through the October 30 moderation release:
  - Current symlink: `/home/ruggie/.local/share/wu-dashboard/current`
  - Releases directory: `/home/ruggie/.local/share/wu-dashboard/releases/`
  - Release and rollback records: `docs/release-history.md`. Read it before any release or rollback.
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
