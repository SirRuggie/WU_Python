# Live integration audit — October 23, 2026

## Scope

Read-only production checks plus isolated automated failure/concurrency tests.
The owner confirmed Android phone notification delivery before this audit.
No synthetic live notifications, Discord messages, grants, roles, signups,
roster placements, or BAND settings were changed. No UI changes in this pass.
Prior narrow/wide UI checks remain documented in the individual workflow reviews;
this pass does not claim a new device/accessibility certification.

## Findings and correction

The web journal contained 62 push reminder check timeouts in the preceding four
hours. A fresh standalone read of the enabled subscription's 47 accounts completed
in approximately 10.5 seconds before the fix and 5.3 seconds afterwards. This does
not reproduce or establish the cause of every historical timeout.

Code review established that one stalled CWL view could discard an already-finished
regular-war view because both were gathered under one overall timeout. The worker
now bounds each enabled view independently to 20 seconds and skips unavailable
views while retaining fresh successful views. Disabled reminder kinds are not
requested. Account lookup is bounded to 20 seconds, with an overall 75-second
safety bound accommodating the existing link, client initialization and history
budgets. Cancellation propagates and unfinished view tasks are cancelled.

This changes only scheduled push data collection. It does not change dashboard
loading, authorization, notification delivery retries, recipient selection, or
storage. Fresh reads still bypass both shared derived caches and coc.py lookup
caches. Existing linkage checks, subscription rechecks, deadline checks and durable
claims remain. Ambiguous delivery is never automatically resent. An unavailable
upstream can still cause a reminder to be skipped; these tests do not guarantee
external API availability or phone receipt.

The initial full suite also exposed an obsolete clan-activity test that treated a
Discord guild owner as a dashboard owner. Corrected its fixture to a protected
owner and added an explicit regression proving guild ownership alone grants no
family dashboard access. Production authorization was not broadened.

## Production evidence

- Web and bot services active/running with zero automatic restarts before deploy.
  Bot/shared integration files match the deployed bot revision despite newer
  web-only commits.
- Mongo ping and read-only SQLite integrity check passed.
- BAND status healthy/running, configured key present, recent successful poll,
  fresh heartbeat and no current error. Token contents were not displayed or changed.
- Both enabled Discord war reminders reported `Tracking battle day` with no current
  error. Eight non-test `sent` receipts existed in the preceding seven days; these
  are delivery records, not independent proof every recipient read a message.
- CWL bridge heartbeat fresh. Historical bot traceback markers at restart were
  cancellation-related; no recurring startup failure was established.
- Live Discord GETs succeeded for bot identity, guild, roles, channels, and both
  protected owner identities. Both owner names and avatars were available.
- Linked-account, official player, clan-history and war/CWL reads succeeded using
  the real subscription's selected accounts. No delivery function was invoked by
  diagnostic scripts.
- Public page paths returned HTML; entry JavaScript/CSS matched the local deployed
  assets. Production fixture mode disabled. Signed-out protected API reads returned
  401; forged OAuth callback returned 403.
- OAuth/session, destination, CSRF, user/role scope, revoked access, owner-only
  administration, cross-user ownership, unpublished roster and partial-upstream
  behavior are covered by the full regression suite. No real person's OAuth login
  was completed or interrupted during this audit.

## Validation

- Full backend rerun: 4,519 passed, 65 subtests passed, 19 opt-in checks skipped.
- All 18 optional Lazy CWL Mongo contract/concurrency/schema tests subsequently
  passed against disposable local MongoDB 7 replica-set storage.
- The remaining optional authenticated recovery drill passed against a temporary
  local MongoDB process, including persisted roster weight and bonus allowance
  restoration. Temporary containers/processes were removed/stopped afterwards.
- Two ticket concurrency tests also passed against the configured restricted
  `wubot_test` database. Its account cannot run `collMod`; the initial attempt to
  run Lazy CWL schema tests there failed on that permission, so those checks were
  moved to local disposable storage. No production/test account privileges changed.
- Full frontend: 327 tests in 76 files passed; production build passed to an
  isolated output directory without replacing live assets during validation.
- War-reminder validation gate: 186 backend tests, 32 frontend tests, build and
  whitespace checks passed. Its one optional recovery skip was covered separately.
  Used the gate's commands with only the build output redirected to `/tmp`.
- New failure tests cover a stalled CWL view preserving a fresh war reminder,
  cancellation of unfinished reads, disabled kinds, malformed view failure, and
  shutdown cancellation. Existing tests cover durable duplicate prevention,
  expired subscriptions, unlinking, ownership, changed preferences and CSRF.
- Existing framework/deprecation warnings remain; they are not test failures.

## Limits

Live notification delivery on the owner's phone is owner-confirmed. Fresh production
reads and historical delivery records supplement, but do not replace, future real
usage across devices and upstream outages. Native screen-reader speech, OS text
scaling, and other untested device settings remain device-level checks. No claim
of zero possible bugs or universal external delivery is made.

## Deployment verification

Implementation revision `cc26a52` pushed to origin/main and loaded by the web
service on October 23 at 21:14:32 UTC. Startup restored Mongo revision 4340.
An immediate request during restart returned 502; the subsequent complete public
check passed after initialization. No frontend assets or bot restart were needed.
Web service remained active with zero automatic restarts; public HTML/assets and
signed-out authorization checks passed again. Post-restart read-only fresh reminder
lookup completed in about 4.5 seconds. No push-check failure, traceback or durability
error appeared during the initial post-restart observation. BAND and both Discord
war monitors remained healthy. This short observation is not a long-term uptime
or delivery guarantee.
