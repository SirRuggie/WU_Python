# Dashboard visitors

The owner-only Visitors card in Staff overview shows unique authenticated people
for today, seven days and thirty days, plus a thirty-day daily series. Days use
America/New_York, including DST changes. Daily counts are available as a table.
Non-owners do not fetch this endpoint; the server independently requires owner
permission. No per-person visit list is exposed.

The storage owner is utils/dashboard_visit_store.py. The non-durable sibling SQLite file (`<dashboard-path>.visits.sqlite3`) uses WAL
and a 200 ms busy timeout. Its visit_days table
contains only user_id, day, first_seen_at and is_staff; (user_id, day) is its primary
key. Authenticated auth/me calls insert once per day. Anonymous calls and bot OAuth
identities do not count. A counting failure does not block sign-in. Staff status is
frozen on the first call each day; aggregate periods classify a person as staff if
any retained daily row in that period classified them as staff. No IP, user agent,
path or device metadata is retained.

Rows are retained for 90 local calendar days, pruned once daily on calls and by an
hourly lifecycle task. The ninety-day boundary is inclusive of today and 89 prior
days. A fresh process can repeat pruning safely. Code rollback leaves the additive
table intact; never restore the database just to roll back this feature.

Previous verification: 5107 backend passed,21 skipped,162 subtests;1071 frontend passed;
TypeScript/build passed. Additional OAuth-bot exclusion and focused HTTP/storage
regressions passed92 tests. Tests cover concurrent duplicate insertions, repeated
DST hour, staff status changes, retention boundary, aggregate uniqueness and zero
fill, authorization, anonymous exclusion and counting failure isolation. Owner
browser checks at360/1440 used synthetic local data; the unrelated staff overview
response was stubbed. The visitor HTTP response was real isolated SQLite data and
contained aggregates only. Thirty daily table rows fit at360px without overflow;
SVG has an accessible description, controls retain44px targets, disclosure exposes
a semantic table. No live visits were queried or written for verification.

Limitations: these are authenticated visitors, not all page views. Failed counting
attempts can undercount until a later successful session call; no notification or
external delivery is involved. First daily staff classification is intentionally
not rewritten after a later permission change.


Rework48 separates counts from the Mongo-authoritative dashboard database. Main
restore replaces only its exact target and journals; encode dumps only its own
connection, so the sibling is never restored or published. Existing unreleased
visit tables in development main databases are left untouched; new visits use the
sibling exclusively. Host loss may lose counts. No counting failure can poison
main durability. The first daily insert, summary and retention run in worker
threads. A bounded 100,000-entry daily cache skips repeats, resets at the local day
boundary and undercounts on saturation. Errors are logged at most once per minute.

OAuth authentication behavior is preserved: an additive sessions.is_bot flag
records Discord identity metadata solely to skip counting known bots; no new403 is
introduced. Existing sessions default to human. Role-check outages may freeze a
role-based staff member as a member for that day; this accepted limitation does
not alter authorization. Final rework checks are recorded in the review handoff.
