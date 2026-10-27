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
