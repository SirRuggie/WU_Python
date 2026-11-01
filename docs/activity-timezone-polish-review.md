# Activity and timezone polish review

Follow-ups214,219,221: clan-read warnings name the affected clans; unused history
output is removed; a route regression keeps unrelated healthy chains intact.
Successful but malformed war reads retry daily; actual read exceptions retain
bounded backoff. No storage migration or TTL change.

Cold identity lookups update a mounted activity search without reloading. Polling
is bounded, skips hidden/busy views, cancels stale views and handles revoked access.
Only identity fields merge: strike counts, revisions, notes and selections stay.
A component regression searches a newly resolved name and checks the unchanged
strike count. Cached names survive failures; owner nickname lookup failures now
log their exception class without upstream text or credentials.

Compare recognizes UK/NZT/MT/MTN/AET at standard offsets, strips subdivision flag
tag characters, and normalizes decorated Unicode letters. The live287-owner
sample's unknown labels were checked; `GMT+8 (NEW)` remains unknown because an
annotation is not a recognized zone. No seasonal inference was added.

Signup-activity over-polling predates PR112: its hook is unchanged fromd9d21c1.
Its interval was30seconds, but every visible visibilitychange requested a read.
The throttle applies only to visibility events; regular visible interval ticks
always attempt a read even if browser scheduling puts them slightly early. It preserves
manual retry, prevents overlapping reads and ignores abandoned views. A fake-clock
regression dispatches30visibility events/rerenders and gets one initial read,
then regular interval reads. A separate early-tick test exercises29,980ms ticks;
real scheduling is approximately30seconds, not an exact timing guarantee. This
explains the observed rate without claiming
that an ordinary component rerender alone recreated the timer.

Completion checks:5,494guarded backend tests/26skips/221subtests;1,247frontend
tests/230files, TypeScript/build; five isolated real-Mongo checks; seven mutation
kills (no auto-refresh, retained subdivision tags, UK unknown, silent lookup
failure, unthrottled visibility, fast malformed retry, decorated zone unknown).
All eight build/layout stages passed at the initial polish checkpoint, including
the newly wired timezone browser fixture. Rework63 adds26relevant backend checks,
five isolated mutation kills (pending flag false, generation removed, busy skip
removed, interval visibility guard reused, mixed-case MT inferred), and a real
Chrome cadence measurement. Reads were0,29.982,59.982,89.981seconds with visibility
events every100ms: no skipped alternate ticks, page errors or non-login writes.
The early-tick fake-clock regression also covers29,980ms scheduling. MT/MTN
are case-sensitive; a mixed-case word like Mt stays unknown.360×800/1440×1000 timezone screenshots were inspected; existing activity
cases also cover320/390/short viewports. No page overflow or non-login writes in
the timezone fixture. This is not a physical-phone or assistive-technology audit.

Initial local checks found harness issues: restricted fixture socket binds,
callback mock typing, a default60-second Mongo TTL monitor incompatible with the
existing12-second test, and occupied staff fixture ports returning404. Each was
corrected and the affected checks rerun. Local Mongo uses a1-second monitor;
production indexes are untouched. Fixed-port layout launches now refuse occupied
ports before contacting another server. The successful full lane used verified
free8908–8915; unrelated previews were preserved. Both owned Mongo fixtures stopped.

Authorization/destination ownership, malformed inputs, stale reads, cancellation,
partial upstream data and duplicate write boundaries were reviewed. All changed
UI reads remain behind existing staff routes. There are no live Discord writes,
notification tests or new automatic write retries. Dashboard interaction-standard
scope: preserve search/selection/notes during background reads, visible error
states, bounded visible-view polling, narrow/wide reflow and existing targets.
