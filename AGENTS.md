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

- Release only through the documented procedure (`CLAUDE.md` "Deploy procedure", `docs/dashboard-frontend-releases.md`, `docs/dashboard-backend-releases.md`): verified DB backup; protected counts before and after; build from a clean checkout of the merged commit; atomic switch; read-only smoke; counts must match exactly.
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
