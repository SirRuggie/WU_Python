# Isolated ticket testing

## Open a test window

1. Run `/tickets testing` in Warriors United as an administrator.
2. Select **Open test window**. Enter the window duration (1–1440 minutes)
   and cleanup delay **after the window ends** (0–10080 minutes).
3. Opening the window includes you automatically. **Add myself** restores your
   explicit membership if needed. Administrators are included by default;
   **Toggle include admins** changes that setting.
4. Use the member or role dropdown to allow other testers. Each selection
   replaces that complete list; the panel displays current members and roles.
5. Testers run `/tickets testing`, then choose **Open Main test ticket** or
   **Open FWA test ticket**. Normal application buttons still open live tickets;
   joining the allowlist does not change them.

The bot creates `ticket-test-applicants` and `ticket-test-staff` on first use.
They are hidden from @everyone and accessible to selected testers and Discord
administrators. Testers may exercise both applicant and staff actions. The bot
retains these private parent channels for reuse, removing tester overwrites
when the window closes. Discord administrators always bypass channel denies.

Windows survive a bot restart and expire automatically. Old-window ticket
controls cannot be used in a later window. The private panel itself expires
in 30 minutes; reopen the command for a fresh panel.

## Isolation

All mutable testing records are stored in **MongoDB database `ticket_testing`**,
including tickets, creation state, open slots, component state, configuration,
flags, cleanup checkpoints and counters. Production collections are not used
for test writes. Only necessary ticket configuration is copied before the bot
binds dedicated test parents. No database drop or live counter reset is used.

Test records carry `mode: test` and a window generation before number allocation.
A separate counter produces `TEST001`, `TEST002`, etc. It is never reset by
cleanup, so test identifiers are not reused. Test tickets do not contribute to
live counts, recruitment history, or Gauntlet completion. Approval and denial
are simulated: no real member roles, applicant DMs, recruiter role pings, or
production history flags are created.

The real questions and ticket controls are reused under an isolated database
and REST scope. `tt|` component IDs select the scope before state lookup.
Every callback checks the current allowlist and ticket window generation.
Discord writes are limited to verified test threads under bot-owned private
parents. Unknown REST mutations and member-role changes are blocked.

## Cleanup

**Close test window** stops access; scheduled cleanup remains at the displayed
original deadline. **Clear test tickets** asks for confirmation, ends the window,
and requests deletion of test threads and ticket records. A background worker
checks every minute, so expiration/cleanup can take approximately one minute.

Cleanup verifies the durable parent ownership marker, guild, actual thread
parent, and TEST name. It records each completed thread deletion and retries
failures after a restart. Each ticket retains its own cleanup deadline, even if
a new test window is opened. The test counter, access settings and cleanup audit
checkpoints remain separate from live data. Expiring component/creation state
is removed by its TTL index.

If channel ownership markers or permissions were changed manually, cleanup
fails closed and logs an error instead of deleting an unverified channel.
Restore the owned test channel configuration before retrying.
