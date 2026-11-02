# Members overview timing release

Tag `members-timing-1` identifies merged PR162,
`f56fdde9f7bb2bc286c9850ae260089f9f35e695`. The staged runtime files match
reviewed head `832e1be1420c6cd8d6ab313769b7c082bf17cc13` exactly. It preserves
the CWL capture fix and all current dashboard features. Ruggie approved the
merge directly; Claude accepted the delta and authorized this release after
the capture report, before Exports.

The change reuses per-request permission results while preserving each row's
hierarchy decision. A numeric-only timing line reports directory, hierarchy,
profile, row-loop, JSON and total stages without member identities.
No new polling, provider calls, response fields or caching lifetime is added.

The accepted combined source passed 6250 guarded backend tests, 99 skipped,
267 subtests; 45 focused tests; three genuine mutations; 1484 frontend tests,
TypeScript/build and the war-reminder check (213 backend, one skipped, 35 frontend
and build). The original global-clock mutant survived a safe constructor
fallback; the added mid-request clock regression kills the meaningful timing
failure. Evidence retains that limitation rather than counting a false kill.

The bot's shared helper change is performance-only and does not require a bot
restart. Frontend source is unchanged from immutable 343. This is a backend-only
release. Fresh backup/testrestore/protected-state/staff/quiet gates, native
51-route isolated boot, imports, actual rollback-order rehearsal and public
hash checks are required before activation.

## Activation

The reviewed manifest schema correction was installed exactly after Claude421
verified the four real suite-log hashes. A fresh gate pass after the next
ordinary capture succeeded. Activation completed **2026-11-02 18:58:04 UTC**.
Backend PID2437301/invocation `ad7528f6249a4e52932624be2cf6ac84` runs the
immutable f56 artifact. One backend restart, zero bot restarts, rollback or
production database restore. Bot2047531 and immutable frontend343 are unchanged.
Staff-before/during and forbidden departure transitions were empty; unrelated
configuration and public entry/affected feature hashes matched. Evidence lives
in `.local/members-timing-release-1/live.json` and its activation/gate proofs.

The initial activation attempt stopped before any service change because the
stage writer omitted required suite manifest fields. Its original evidence and
failure log are retained. The correction did not change guards, protected fields
or the coordinator; the next gate pass used fresh backups and restore checks.

Claude's health smoke423 confirmed the new backend, unchanged bot and no
tracebacks. Three signed-in read-only loads produced numeric timing lines:
6138,7367 and5204ms total. Profiles took2224,2176 and2181ms; directory2250,1934
and1698ms; rows638,639 and644ms. These were Claude's one page open and two fetches,
**not natural traffic**, as explicitly corrected in424. They were contrary to
the requested natural-only observation; no production writes occurred. The
journal observer itself requested no page or provider and cannot identify a
request's initiator from the numeric log alone.

The CPU improvement does not establish a production speed success: total load
remains5.2–7.4s. Mongo profiles and Discord directory/hierarchy remain separate
investigation work under141. No production role change or notification delivery
was tested. Future comparisons should use natural loads where possible.
