# Prompt54 PR A review evidence

This backend batch adds official-API player activity capture, a bounded raid
summary, one-time attack-history seed and explicit strike-retention migration.
It adds no Discord command, public write route, notification or mention output.
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
