# Server settings, FWA and integrations review — 2026-10-23

## Scope and behavior

Reviewed the shared server-settings directory, FWA tools (messages, points, sync,
Town Hall resources and blacklist), BAND runtime status, and their save/action
adapters. Existing Members, Tickets, Commands and CWL workflows remain separate.
No new account-link provider or parallel configuration store was introduced.

- Compact grouped tool rows replace the generic tile directory for this scope.
  Large groups are disclosed; search exposes matches. Returning to the index
  preserves its state and restores focus to the original tool.
- Runtime information is a complete labeled status summary, not disabled inputs
  split across arbitrary pages. BAND diagnostics and test DMs are secondary.
- FWA previews are explicit on desktop and mobile. Editing with the preview closed
  does not request one. Save remains distinct from preview and publishing.
- BAND status and calendar reads need no mutation confirmation. Other actions,
  including test messages, still confirm. Pending request recovery is labeled
  separately from starting a new status check.
- A manually checked completed request reloads the selected saved document and
  clears earlier polling errors, without replaying the action. Pending requests
  block navigation, reload and duplicate actions; revisions preserve conflicts.
- Readonly operation documents reject PATCH. Weight inputs require bounded whole
  numbers; sync channels are validated before Discord lookup and checked for the
  current guild/type/permissions. Sync defaults match the bot's normalized config.
- FWA points monitoring uses compare-and-set in its existing storage owner.
  Ambiguous test-DM delivery is recorded as uncertain rather than retryable success.
- FWA runtime snapshots, revisions and image-cache refresh helpers live in utils;
  affected worker paths no longer import dashboard presentation helpers. Other
  pre-existing worker/dashboard dependencies were not broadly refactored here.
- BAND snapshots explicitly distinguish stale status. Last check is readable UTC;
  malformed timestamps are unavailable. Arbitrary upstream errors are sanitized
  before storing snapshots and again when reading older saved snapshots.

## Credential and deployment gate

BAND reads BAND_ACCESS_TOKEN from runtime environment and fails closed when
missing. The owner explicitly authorized reuse of the existing token without
rotation on October 23. It was transferred without printing into botrunner's
private runtime .env (mode 0600), and loading was verified. The previous automatic
approval block was resolved by that explicit authorization. No token rotation
was performed; the historical token remains in Git history.

The complete reviewed dashboard and bot code revision 86bacc8 was deployed.
Runtime imports passed, BAND logged monitor_started after restart with no startup
traceback or missing-token error, and both services were active/running with zero
automatic restarts. Public settings routes, entry assets and ServerManagement
chunks matched the full production build. No live test messages were sent.

## Verification

- Independent UI and backend implementation agents; independent read-only review.
- Final full frontend suite: 301 tests passed, including the final request-status
  wording and disabled-control refinements. Final production build passed.
- Root backend selection: 215 tests and 16 subtests passed. Backend agent's broader
  selection passed 269 tests and 9 subtests before the final UTC formatting tests.
- Shared war-reminder gate passed: 185 backend tests, one existing skip, 32 frontend
  tests, and production build. Existing aiohttp key warnings remain.
- Browser fixtures at 320px, 390px and desktop: grouped index; full BAND status;
  collapsed diagnostics/testing; conflict preserves edited checkbox and disables
  saving; return-to-directory restores focus; explicit preview only; failed status
  poll recovers via GET and clears error without another action submission.
- Native discard confirmation was observed. Browser tooling could not complete
  that native dialog reliably, so subsequent isolated navigation checks used a
  fixture-only confirmation override. Production confirmation behavior was not
  removed. No fixture override is included in the build.
- No live Discord sends, settings writes, role changes, calendar changes, or
  provider credential rotation were used for verification. Simulated outcomes
  are not evidence of live delivery. Full screen-reader and real-phone testing
  remain separate from these scoped checks.
