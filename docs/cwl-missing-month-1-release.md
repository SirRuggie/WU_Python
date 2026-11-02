# CWL missing-month release

PR #158 was accepted in Claude entry 358. Ruggie authorized release in entry 365:
"Yes release PR 158 and then find the members speed issue". It was merged without
source edits onto the current Members main as
`72b5a2f6ebf7b343458adbc64720f148a4179532`, tag `cwl-missing-month-1`.
The actual merge tree matched the predicted clean merge, and the participation
source is byte-for-byte identical to accepted revision `848d73d`.

The deployed rule handles a null or absent `season` as no month. Valid active
groups may then infer the selected current UTC month; an ENDED group requires
stored-tag containment or waits. Explicit valid months win, and unreadable war
states remain failures. Polling frequency and provider evidence are unchanged.

This did not fix the production capture. The initial `missing_month` diagnostic
was misread as evidence of an absent season. It actually covers a value that is
not a valid month. The provider parser rejects non-strings, and the current-month
control flow handles None before that diagnostic, so the seven observed failures
have a string failing the month pattern. The exact value is unknown; it is not
proven empty, and it is not None. Prompt 114 addresses that distinction separately.

## Validation and release boundaries

The exact merged commit passed 6,143 guarded backend tests, with 99 skips and
266 subtests; 1,484 frontend tests across 261 files; TypeScript/build; and the
required war-reminder check (213 backend passed, one skip, 35 frontend passed,
TypeScript/build). No conflict or source edit was introduced during merge.

Only `cwl_web/participation_sync.py` changes at runtime. The bot and frontend source
remain unchanged from the Members release. The rebuilt frontend entry matches
`index-DODYu6Hv.js`, SHA-256
`70ae891fce6403a70c8cbcee48863357a4a281615c93c9d461ac02762e009b1d`.
Activation restarted only the backend; it did not restart the bot or
switch the live frontend. The existing Members frontend and bot remain at
`343d9611213d1feb722d4cf72250d4e8a4e751be`. The bot kept running throughout the backend-only activation.

Fresh backups/test restores, protected-state and staff-proof comparisons,
production-shaped staged boot, runtime imports, no-queued checks, readiness,
rollback rehearsal and public hash verification remain mandatory. The staged
backend uses all 51 configured routes, a native Mongo pool and real durable owner
on owned Mongo and copied SQLite, with external networking blocked. Rollback
restores backend code; it never restores the production database or changes the
bot/frontend.

Activation completed at 2026-11-02 13:25:41 UTC. Backend PID 2096847, invocation
`75fa7dc81feb4b4a92aec7014590d881`, runs the tagged backend. Bot PID 2047531,
invocation `25c8bea0ebc54016a1b6bcc78f38f104`, and the frontend remained unchanged.
There was one backend restart, no bot restart, no rollback and no production
DB restore. The public entry and affected assets still match the retained
Members frontend manifest.

Fresh protected counts were 3,715 active strikes, 306 accounts, 586 strike
profiles, 279 eligible accounts and 479 member profiles. Exact protected Mongo
and SQLite state matched, with no staff transitions or departures. Unrelated
configuration remained identical. An active declaration delayed activation;
it completed naturally before the final all-clear queue check. No send,
cancellation or receipt edit was performed by the agent.

Claude entry 367 reports **health PASS, capture FAIL**. The frontend symlink and
public entry remained at Members, the backend PID/cwd matched this release,
and the bot remained unchanged. Unauthenticated participation returned 401;
participation GET returned 200 in 173 ms. Web and bot journals had no errors.
No rollback was needed because the affected clans retain their previous
conservative unavailable behavior.

The first ordinary capture at about 13:39:44–46 UTC reported three PREPARATION
and four ENDED groups as unavailable/missing_month, plus three no-group 404s.
The configured cycle is current November; sync remained unavailable and 169
accounts were stale. Local provider-only fixtures distinguish None (accepted)
from empty or malformed strings (unavailable). Production's exact string was
not observed, and no successful live November capture is claimed.

No live provider probe, forced capture, role/nickname change, send, cancellation
or receipt edit was performed. The first real Members role change remains
Ruggie's, on one person. Prompt 114 is a separate rework with release held;
Members and Roster/Strikes speed work follows in prompts 112 and 113, with any
speed fix also requiring separate release approval.

Evidence: `.local/cwl-missing-month-release/`. Source rules and limitations:
[CWL group review](cwl-group-no-season-review.md). The health smoke has completed. The capture failure remains open for prompt 114;
no fix is included in this audit document.
