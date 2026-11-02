# CWL unreadable-month correction release audit

## Scope and approval

PR161, tag `cwl-unreadable-month-1`, commit
`516bbfdd8b5bbc6c8d3a69ea94d040097b56f5a0` corrects unreadable month strings
for groups and wars. Ruggie approved release after review in handoff 369;
Claude accepted the final `b03881f` delta in 371. The accepted head and merge
have the identical tree `4a29d5eb0b9611b6200ccf74f7e8f569c179eebe`.
Only `cwl_web/participation_sync.py` changes runtime behavior relative to 72b5a2f.

The prior `cwl-missing-month-1` release was healthy but failed its capture
purpose: seven clans still reported invalid month strings and 169 accounts were
stale. Those strings were not null; their exact values were not observed.
This audit does not infer that they were empty strings. See the earlier release
audit and `docs/cwl-group-no-season-review.md` for the corrected diagnosis.

Groups and wars share the null-or-unreadable-string rule. Valid explicit months
win; a valid different war month rejects an inferred group. ENDED groups still
need stored tag containment. War summaries expose only month-kind counts,
masked shapes (at most five, each at most twelve characters), and mismatch count.
No raw month value or provider response body is logged.

## Validation

The identical accepted/merged tree passed 6201 backend tests, 99 skipped and 272
subtests; 219 focused tests and 19 subtests; 1484 frontend tests in 261 files;
TypeScript/build; war reminders 213 backend tests, 1 skipped, 35 frontend tests and
build. Four new war mutants were killed, including the allowance-only old rule;
the four group mutants from 114 remain recorded. The initial mutant detector
missed pytest's SUBFAILED label; actual assertion failures were inspected and
results corrected. No surviving mutant was called killed.

Real public group and war parsers use stubbed HTTP bodies. Active inferred groups
capture seven attacks and 21 stars; matching ENDED groups establish
`source_complete=True`. Valid older wars store neither the inferred group nor an
allowance. These are isolated tests and do not establish production capture.

The tagged isolated frontend build is byte-identical to 343. The deployment is
backend only; bot and immutable frontend 343 are retained. No bot restart or drain
is needed. Source exports and rollback assets are retained; no database restore
is an application rollback step.

## Activation and observation

LIVE at `2026-11-02T14:54:32.759893+00:00`. Backend PID `2141451`,
invocation `42df4e59007348caa09c1f3b2502be2f`, runs from the immutable 516
archive. Bot PID 2047531/invocation 25c8bea0ebc54016a1b6bcc78f38f104 and
immutable frontend 343 remain unchanged. One backend restart, zero bot restarts,
no drain, rollback or database restore. The explicit activation process exited 0;
never repeat it.

Fresh SQLite/Mongo backups and isolated test restores, canonical-state and
committed SQL staff proof, exact protected 3715 active strikes/306 accounts/586
strike profiles/279 eligible/479 member profiles and digests all passed. Staff
transitions and departures were empty. The staged production-shaped boot used 51
configured routes, the native pool, real durability owner, copied SQLite and owned
Mongo with external networking blocked; config 200/auth 401 and cleanup passed.
Tagged imports, 13 timestamp guards, 8 maintenance guards, noqueued gate and
backend-only rollback order/four injected failure cases passed. Unrelated
configuration was unchanged.

Public entry `index-DODYu6Hv.js` SHA256
`70ae891fce6403a70c8cbcee48863357a4a281615c93c9d461ac02762e009b1d` and all
verified affected feature hashes match the retained 343 release. The exact source
and evidence are in `.local/cwl-unreadable-month-release/live.json`,
`activation.log`, `merge-proof.json`, `merged-suite-proof.json` and gate proofs.

Claude's read-only smoke (373, capture time corrected by 374) passed: actual
runtime/public entry match, unauthenticated participation 401, bot unchanged.
No production write was exercised.

The first ordinary worker capture finished at 15:08:38 UTC on November 2. Four
`PREPARATION` groups were inferred and stored with `season_kind=invalid` and
masked shape `ddddxddxdd`. One ENDED group with the same shape waited without
stored tag containment. Four `NOT_IN_WAR` groups remained unavailable with
`invalid_group_shape`; one other group returned 404. The war summary reports 16
fetched wars, all `none`, zero empty/invalid/valid, no shapes and zero month
mismatches. No raw month value or separator was observed. The shape resembles a
full date; interpreting it as an explicit month is future prompt 116, not behavior
claimed for this release.

Overall status remains `stale`, with no successful full capture and no attacks
yet. Current working signups: 170 rows, including 49 preparation, 90 stale,
27 waiting, 3 no_data and 1 unassigned. These counts exclude historical source rows.
The raw stored source table also contains five historical rows (two stale and
three unassigned), which explains the initial observer's 92 stale/four unassigned
counts. Four group and four clan-side war observations are stored for the cycle.

The three no_data accounts are current assigned signups absent from the observed
group roster; the source warning also reports absence from observed war rosters.
Their attacks/stars remain unknown and complete is false. This is no evidence of
a code bug or zero attacks; no fix is made for them.

This is a real improvement for four clans, not a full capture PASS. Residual
NOT_IN_WAR shape handling and date-shaped month interpretation are queued for
separate review and release approval. No forced capture, provider probe, restart
or rule weakening was used to obtain these facts.

Evidence: `ordinary-capture.json`, `ordinary-capture-journal.json` and
`current-working-capture.json` in the release folder. Initial observer output is
retained as `ordinary-capture-initial.json`: its startswith selection missed the
logger prefix. Extraction was corrected and eleven masked messages were bound
to the exact live invocation; the invocation filter itself was correct.

The Members speed optimization is a separate unreleased branch and is not
included in this release.

## Follow-up 116 interpretation

The observed month has a date shape. The exact raw value and separators were
not fetched. Follow-up 116 recognizes only a fully matching dash-separated
YYYY-MM-DD-shaped string as explicit YYYY-MM month evidence, while masking the
day in diagnostics; other invalid strings retain the no-month rule. It also
classifies empty NOT_IN_WAR responses per clan. This describes the follow-up
source change, not a claim that 516 already has that behavior or that its
partial capture was complete.
