# Staff integration and reminder health — October 26, 2026

## Scope

Improved existing Integrations and family reminder views, without a new menu,
backend endpoint, storage owner, scheduler, permission grant or notification retry.

BAND keeps monitor/connection/poll state and check times visible. Abnormal startup
and recorded problems remain visible. Healthy startup, debug state and no-problem
history are under Technical status details. Stale snapshots explicitly distinguish
historical results. Known valid ISO timestamps use local time with a timezone;
unknown/malformed values remain readable. Check status retains the existing action
request identity and pending-result handling; diagnostics stay optional.

Family reminders distinguish the latest scheduled outcome from test messages.
Unconfirmed sends require checking the channel, never automatic replay. A missing
destination no longer hides an existing delivery/check warning. Review destination
opens the existing reminder editor and preserves overview filters/focus on return.
Detailed status limits are in an optional disclosure with a 44px summary target.

Channel lookup generations reject older responses and unmounted results. Access
denial clears cached channels/roles; ordinary outages retain names with an error.
Pending/rejected reads cannot make cached channel inventory authoritative.

Signup reminder schedules already show their next planned occurrence and sender
state; this pass preserves that behavior. Exact next sends for war reminders and
BAND are not available in their existing payloads and are not invented. Channel
presence is not proof of send permission. Existing API payloads include some
history eagerly; changing that contract is outside this presentation cleanup.

## Review and validation

Sol built integration presentation, Luna built reminder clarity and lookup guards,
and an independent Sol reviewed status precedence, stale reads, denied access,
historical data, next-run limits and uncertain delivery semantics. Parent browser
review added readable dates, action-label matching and the disclosure touch target.

Full frontend suite: 387 tests passed. TypeScript and isolated Vite build passed.
Integration/server-management/return-status regressions: 27 tests and 16 subtests
passed. The required war-reminder gate passed: 186 backend tests, one existing skip,
32 focused UI checks, build and whitespace checks. Existing framework warnings
remain. The gate now builds into a temporary directory instead of risking live
web/cwl/dist assets. No production assets were used for validation builds.

Isolated fictional-data browser checks covered 320px, 390px and 1280px layouts,
long multilingual names, concise BAND status, stale snapshot warnings, disclosures,
missing destination alongside unconfirmed delivery, preserved search/focus when
opening/returning from the reminder editor, channel lookup failure, and overview
403 clearing its rows. No document overflow occurred on inspected views. Hook
regressions additionally cover pending freshness, stale concurrent responses,
unmount, ordinary outage retention and 401/403 clearing.

## Limits

No live Discord sends, BAND diagnostics, settings writes, signup changes or roster
changes were used as tests. Fictional browser data and mocked transport tests are
not evidence of live notification delivery or upstream availability. This is not a
full screen-reader or real-phone certification. Existing scheduling and durable
receipt behavior is unchanged.
