# Assignment locations release

This release bundles prompts 100–103: the Outside family correction, verified
location checks on the member's own plan assignments, and Declaration row and
mention fixes. Unknown or stale locations do not become mention targets. A last
verified location remains visible through an unavailable refresh and clears when
a newer verified move contradicts it. Declaration groups accounts by person for
one DM action, while keeping account-level filler and presence details.

Ruggie authorized the combined backend/frontend release in Claude entry 329.
Claude accepted PR146 at `40345517ed5c57c571f6a92e34d303d355dc7cea` in entry 332.
The merged revision is `1e0f39ec7c7c8fcb4a7a886b6d89e6be6d7d5492`, tagged
`assignment-locations-1`. The bot does not need a restart for this release.

## Validation

The final source passed 5,842 guarded backend tests (71 skips, 253 subtests) across
three disjoint groups, 1,421 frontend tests in 251 files, TypeScript and production
builds, and the war-reminder checks (213 backend tests, one skip, 35 frontend tests
and build). Three new behavioral mutants were killed: mentioning unknown accounts,
forgetting verified locations, and falsely flagging rostered low-TH accounts. The
prior false-arrival mutant was also rerun and killed.

Isolated UI checks covered 320, 360, 390 and 1440 pixels, grouped Declaration,
member assignments, and 26/65/125-account filler views. Narrow and wide screenshots
were inspected. Real UI fixture transitions covered cache expiry retaining a
check, a newer verified move clearing it, and cold unknown locations remaining
unknown. These fixtures do not prove live Discord delivery or real member refresh.

## Activation evidence

The backend and immutable frontend activated on 2026-11-02 at 01:33:08 UTC.
Backend PID 1750397, invocation `067f2ab23e55443584fd20b996a4d349`, runs the
tagged backend. Bot PID 1672182 and invocation
`a2175e62d29d4e419f0888e35942f2d9` remain on the prior `1af386e` revision.
There was one backend restart, no bot restart and no rollback.

Fresh backup/test restores, canonical Mongo/SQLite and role-progress restoration,
startup rehearsal, artifact imports, no-queued-work gates, rollback rehearsal,
readiness and public hashes passed. Protected counts were 3,715 active strikes
across 306 accounts, 584 strike profiles, 279 eligible accounts and 479 member
profiles. Exact protected digests and streaks matched; the staff-write proof
observed no transitions before or during activation.

Public entry `index-C8FlbBgH.js` SHA256 is
`467d3605429dcff3be647d9cb8b7e5de6ffcdc8eb8dff4dbd314ce7310b6559d`.
MemberAssignments, ArrivalCheck, Roster and other affected assets matched the
release manifest. Backend startup, unrelated configuration and bot state passed.
The private evidence folder is `.local/assignment-location-release`.

Early preparation errors (non-executable staging helper, an incorrect import
name and a coordinator subprocess module path) stopped before switching any
production component. Corrected final gates and activation passed. No database restore is part of the
activation or code rollback. No agent performed live role, nickname, mark, Import,
Review, Rename, Send or DM actions.

## Production smoke

Claude entry 333 passed read-only API smoke on the actual release. The frontend
symlink, backend PID/cwd, unchanged bot PID and public entry hash matched. The
backend journal since 20:30 EST had no warning or traceback.

Through the signed-in page, GET-only checks found 170 arrival accounts: 154 arrived,
15 missing, one unassigned and zero Outside family. Declaration extras returned
200 with eight clans and four accounts not on the roster. Own assignments returned
14 accounts, initially unknown and then all arrived on three reads after the
background refresh.

Claude's browser pane reported hidden visibility. Production check icons, header
count, grouped rows and narrow/wide layout were therefore not visually verified
in this smoke. Isolated visual evidence remains the layout evidence; it is not a
claim about production rendering. A real member view, DM click and a move clearing
a check were not tested. Ruggie can confirm the visual result on his phone.
