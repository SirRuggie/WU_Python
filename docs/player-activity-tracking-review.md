# Prompt54 PR A review evidence

This backend batch adds official-API player activity capture, a bounded raid
summary, one-time attack-history seed and explicit strike-retention migration.
It adds no Discord command, notification or mention output. Prompt 56 adds one
explicit staff-only, CSRF- and revision-protected quarantine resolution action.
The existing Discord/API client and collection routes are reused. Domain logic
lives in utils; extensions/tasks owns lifecycle only.

## Behavior and failure review

- First observations initialize baselines; counter decreases update them without
  claiming activity. Unobserved partial fields retain their earlier baseline.
  Unit unlocks count only after an earlier read observed the unit list.
- Failed reads and identity mismatches do not write. Older responses cannot
  overwrite newer data. CAS revisions protect concurrent observations, seed,
  membership and raid updates. Seed timestamps never overwrite official readings.
- Startup index outages are retried. Duplicate lifecycle starts produce one task;
  cancellation propagates and awaits the background seed and session cleanup.
- Family departure writes require a complete roster sweep. Leave/return clear or
  set the departure timestamp. Raid skips require bracketing observed membership,
  full clan reads and a <=90minute observation gap. A family-clan move preserves
  attack evidence; past logs never infer a skip.
- Per-player arrays are capped at30 active days/8 weekends.125players simulated
  for400days remain125documents. The minimal fixture occupied110250 BSON bytes,
  max882bytes/document. This is not a full-unit production size measurement.
- A real isolated Mongo7 on27154 verifies actual BSON restore, TTL index options,
  purge invariance and a seed/official race. The migration preserves profiles,
  refuses pending streak receipts and extended active expiries, and creates no
  TTL until all three local dumps have restored and matched hashes/counts.
- The seed source correction is Claude199: public observed battle history,
  bounded to90days, five requests at once and a120second overall run. Empty,
  malformed, non-200 and timeout outcomes do not invent a date. Source attribution
  stays clashking_seed, whose limitations are documented for PR B's UI.

## Validation record

Required mutations were killed: reset decreases becoming activity; seed overriding
an official reading; one document per poll; streak derived from records after a
purge. Logs and JSON summaries are retained in .local/p54-evidence. Source was
restored after each mutation and targeted checks rerun. The complete frontend
suite passed1164tests/224files with the released signup frontend merged in.

The first full backend run was guarded against outbound access:5394tests passed,
but two opt-in ticket tests inherited a remote test URI and were blocked. Both
passed when explicitly pinned to a narrowly scoped user on the local fixture
Mongo. The final full suite uses that local URI and the same production-port and
outbound network guard. No live read or write was used as test evidence.

Final counts and review SHA are recorded in the handoff READY after the final
run completes. Production remains gated on Claude review, backup/test-restore,
protected-state/collection-size verification, first-hour worker logs, readiness
and rollback. The fixture evidence does not imply any production TTL was enabled.


Final validation: full guarded backend5407passed/19skipped (221subtests), full
frontend1164passed/224files, actual isolated Mongo2passed. Final post-suite raid
calendar/empty-family regression and review cleanup passed the24-test targeted
suite (2optional Mongo tests skipped there; they passed in their explicit lane).
All four required mutations were refreshed and killed, then source was restored.
The raid calendar supplies only the ended weekend identity when every clan log
is empty; it never substitutes for observed membership. Backup directories use
private0700 permissions. No live Discord or notification test was sent.


## Prompt 55 rework

Deferred snapshots have no TTL; finalized snapshots use 30 days and incomplete
placeholders 90 days. Old unresolved wars are quarantined for visible staff review
without stopping subsequent wars. Migration uses an explicit separate local server,
refuses unacknowledged empty collections and corrupt restores even under `-O`, and
records partial index success. Recovery restores verified dumps into a fresh local
database. Real Mongo 7.0.41 proves deferred/incomplete survival across actual TTL
sweeps and finalized deletion, with no dry-run source changes.

Roster failures retain healthy polling and suppress departure writes; archived
clans are excluded. Every family clan participates in raid reads. Completed raid
weekends avoid repeat API/Mongo writes, incomplete weekends retry, builder trophy
decreases are ignored, and transient seed attempts retry at most three times.
Membership CAS conflicts are logged. Writer-level dates, retained expiry and
replacement eligibility are covered. PR B will label retained counts Last 90 days.
A full baseline is approximately 7.8 KB, about 8 MB for 1000 players before overhead.

Final rework suite counts and mutation table are recorded in the new READY entry;
the previous READY counts above describe the pre-review revision only. No live
Discord test, notification or production migration was performed.

A quarantined old war remains a streak blocker until an explicit staff-reviewed
resolution clears the hold. Quarantine changes its retry state, not its effect on
newer streak credit; a regression covers both sides of that resolution.


Prompt 56 adds real-run-order raid tests at :15/:30/:59, durable bracket evidence,
archived-clan reads, last-known roster polling, rate-limited failure logs and
daily/no-change write suppression. Old review wars always remain visible even
when incident rows exist. The actual resolution owner checks guild/revision and
retains a bounded audit receipt; real Mongo exercises stale resolution rejection
and the new 30-day audit date. PR B supplies the review button. Final counts and
mutation table are in the next READY, superseding the earlier review snapshots.
