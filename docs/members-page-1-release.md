# Members page release

Release tag: `members-page-1`, commit
`343d9611213d1feb722d4cf72250d4e8a4e751be` (PR #152).
Ruggie authorized release after review in Claude entry 294; Claude accepted the
final delta and reconfirmed the release and bot restart in entry 362. PR #158 is
explicitly excluded and remains held for separate approval.

The release adds the unified Members directory, reviewed role changes and shared
profile editing. Known Discord backoff applies across role and nickname runs and
standalone saves, including a delay recorded after a run was created. Phone
selection controls expose Actions, state-aware Select/Unselect page and the full
hidden-selection count. Existing member-picker and ticket fallback routes remain.

## Validation

The accepted branch passed 5,993 guarded backend tests, with 99 skips and 266
subtests; 1,484 frontend tests across 261 files; TypeScript and build; 125 focused
backend tests and 31 legacy-fixture checks; 15 owned-Mongo tests, including local
real-Hikari 429/Stop cases; and both requested backoff mutants. Running role
transport before lane tests also passed. All three checked-in browser suites
passed 13 cases across 320, 360, 390 and 1440px plus a short-screen case. Narrow
hidden counts and the wide overview were visually reviewed. The required war
reminder check passed 213 backend tests (one skip), 35 frontend tests and build.

Fresh release checks verified SQLite backup integrity, exact counts and protected
state; Mongo backups and isolated test restores; canonical dashboard recovery;
and unchanged startup SQLite data. Protected Mongo counts were 3,715 active
strikes, 306 accounts, 585 strike profiles, 279 eligible accounts and 479 member
profiles. Every protected value is compared, not just these counts.

The exact tagged backend passed a production-shaped boot with all 51 configured
routes, the native Mongo pool and real durable owner on owned Mongo and copied
SQLite. External networking was blocked; config returned 200, unauthenticated
auth/me returned 401, and fixture cleanup completed. Immutable artifact imports
also passed in the actual bot interpreter (Hikari 2.6.0). An initial release-only
import-list mistake named a nonexistent module; it was corrected and its failure
log retained before any service change.

The rollback coordinator passed four injected control-flow cases and a mocked
execution of its actual rollback ordering. It restores code and retained assets,
never the database. Only `participation_sync_settings.last_checked_at` retains the
previously authorized automatic-timestamp exclusion; 13 guard cases and eight
quiet-maintenance cases passed. All other protected columns remain strict.

## Activation and smoke

Activation completed at 2026-11-02 09:59:12 UTC. Bot PID 2047531 (invocation
`25c8bea0ebc54016a1b6bcc78f38f104`) and backend PID 2047653 (invocation
`0e379003c41f487ab45232f55fa76a29`) run the tagged revision; the immutable frontend
also points to that revision. There was one bot start and one backend restart,
with the full 210-second drain. No rollback or production database restore occurred.

Public entry `index-DODYu6Hv.js` has SHA-256
`70ae891fce6403a70c8cbcee48863357a4a281615c93c9d461ac02762e009b1d`.
The public HTML and affected feature assets match the staged manifest. Protected
Mongo and SQLite state matched after activation, with no staff transitions or
departures. Unrelated configuration remained identical.

The first 60 seconds of ordinary polls produced zero management poll
OperationFailure warnings. The additive `member_change_lane_backoff` index exists
with its expected keys and partial filter. Startup journals contained no traceback
or critical failure. Claude entry 362 allowed at most one first-minute warning;
none occurred.

Claude's independent read-only smoke passed in entry 363. The release symlink,
backend PID/cwd, bot PID and public entry hash matched. Unauthenticated overview
returned 401. At 360px on real data, the page showed 1,413 members, its first
checkbox at 259px, no overflow or raw-ID labels, and real avatars. The person
panel showed 245 role boxes, with 36 disabled, and Back returned to the list.
At 1440px there was no overflow or alert. No write controls were pressed. The
web journal had four `coc.http` rate-limit lines at startup; the bot journal had
zero warnings, errors or OperationFailure messages.

One unresolved speed finding remains: signed-in overview requests took 6.9, 9.0
and 9.8 seconds for a 1.09 MB response. Claude inferred that this uses the old
page's inventory, so it is not proven to be a regression. No speed fix is claimed;
a separate speed batch awaits Ruggie's decision. Live role writes, Stop and 429
backoff were not tested in production.

No agent ran a live role change, nickname change, Import, Review or Send action.
Local fake Discord transport and browser fixtures do not prove live delivery.
The first real role change remains Ruggie's, on one person.

Evidence: `.local/members-release-1/` and the accepted branch's `.local/p111-*`.
Review implementation and fixture limitations: [Members review](members-page-review.md).
