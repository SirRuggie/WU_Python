# Participation waiting release

PR #149 implements prompt 104's neutral current/next-month wait, while keeping later,
past, ancient, malformed, unavailable and already-observed-month warnings. It preserves
unknown account values and manual participation results. See [the feature
review](participation-wait-review.md) for the conservative rule and what the provider
code proves about the current-group endpoint.

Ruggie authorized release in Claude entry 337; Claude accepted db77420 in entry 339 and
asked for this backend/frontend release without waiting for prompt 105. The
merged/tagged revision is `0f86e9ff3d3df54c924a8e266948739059fbe465`,
`participation-wait-1`. The Mongo lifecycle PR #148 remains unmerged rework; its
workflow deadline changes are not included here. The bot was not restarted.

## Validation

45 focused backend tests, the full frontend suite (1,427 tests in 252 files), TypeScript
and production build passed. Three genuine mutants failed tests: later-month data
mislabeled neutral, real-warning counts hidden, and duplicate waiting text. Twenty
detached GET-only App states cover waiting/later/partial/ unavailable/complete with 170
synthetic accounts at 320/360/390/1440. There were no horizontal overflow, page errors
or closed-history requests. Narrow/wide waiting and warning screenshots were visually
reviewed. No production Check Clash, Import, Review, Rename, role change, notification
or DM action was performed.

## Activation

Activated on November 2 at 02:57:32 UTC. Backend PID 1798034 runs the tagged revision;
the frontend points to its immutable release. The bot remains PID 1672182 at 1af386e.
One backend restart, zero bot restarts, no rollback and no database restore occurred.
Public `index-BzHhELG4.js` SHA256 is
`ead29373187f63adbd9c0fcc7be098bbab5346655b19a9860c431ff97cef2177`.

Fresh protected counts were 3,715 active strikes, 306 accounts, 584 strike profiles, 279
eligible and 479 member profiles, with exact digests and streaks. Clean tagged immutable
artifacts, imports with network access blocked and rollback rehearsal passed. Fresh
SQLite/Mongo backups include isolated restore, canonical head/local role-progress
reconciliation and startup rehearsal. Exact SQL protections additionally include
participation records, sources, sync settings, group/war observations and fetches, plus
core bonus tables. Full SQLite backup/restore counts cover all tables; the extra strict
comparator covers the named subset. No data restore is part of activation or code
rollback. The prior backend/frontend 1e0 release is retained for rollback.

The first activation command stopped inside preflight before any switch: only
`participation_sync_settings.last_checked_at` had changed since the backup. All other
protected tables and columns matched. The old runtime stayed healthy with no restart or
rollback. That evidence is retained in the private attempt-1 folder; fresh
backup/restore and canonical proofs were taken without weakening the gate.

## Production smoke

Claude's read-only smoke in entry 341 passed runtime, public hash and the participation
API 200 checks. The page was hidden, so the new line was not visually verified live. The
ordinary capture returned unavailable rather than a month mismatch: the wait line was
not shown. That gap remains a separate approved follow-up; neither an actual 404 nor its
cause can be reconstructed from the existing generic status/log records. No provider
timing/request probe was made. A Push reminder TimeoutError was logged once without a
traceback; it is not established as participation-related. Existing stored mismatch data
is not guessed into a waiting state: an ordinary scheduled capture or a user's own check
must supply the validated reported month. The existing capture interval is unchanged.
Fixture screenshots and fake providers do not establish live Clash behavior or Discord
delivery.
