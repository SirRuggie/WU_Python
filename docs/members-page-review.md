# Unified Members page: development review

This change replaces the separate Members hub/time-zone directory with one
searchable, selectable list and a reusable person panel. Legacy member deep links
are retained. Per Claude298, the whole page keeps the existing `member_roles`
grant; no new permission or grant migration is introduced. Tickets move to their
own menu group. Protected moderation files and ChannelCombobox are unchanged.

The existing ProfileRuns owner stores typed role manifests and one-at-a-time
children in the existing management lane. Roles do not create a second storage
owner or replay uncertain effects. The separate old time-zone renderer and its
unused styles are removed; its tests now exercise the unified page.

## Review evidence and limits

| Area | Behavior checked |
| --- | --- |
| Access | Actual dashboard policy denies viewers without member_roles before reading a confirmation body; UI makes no directory/run call without access. Profiles-only is not a new grant. |
| Selection | Stable ID sets across search/filter/page, page-only selection, bot exclusion, hidden counts, frozen exact payloads, separate row opener and checkbox. |
| Role changes | Explicit bulk confirmation; one ordinary person applies directly with guarded Undo; protected roles require confirmation; fresh actor/target/bot/roles/guild and policy inputs before a detached fake Discord write. |
| Recovery | Owned Mongo: restart retains done/uncertain/running children, Stop prevents later people, protected confirmation and duplicate confirmation share one durable run/lane. |
| Failure | Unknown confirmation is not automatically retried; unreadable progress blocks new writes until safe refresh; malformed directory/Undo data fails closed; role receipt/audit failures never claim delivery certainty. |
| Editor/navigation | Existing conflict/draft reload, save retry identities, uncertain outcome and country-zone editor cases migrated intact; dirty person changes use the shared discard guard and stable Details history. |
| Layout/keyboard | Four widths320/360/390/1440; usable bounded list, no page overflow, left alignment, hidden-label containment; exact hidden-inclusive bulk/Stop flow. Real Tab/Space/Enter/Escape at360/1440 and640×460, uncovered focus and preserved selection/filter/Back. |

Final checks: 5,920 full guarded backend tests passed, 75 skipped and 253
subtests; 1,470 frontend tests in 259 files; TypeScript and production build;
82 focused backend and 82 focused frontend cases; six canonical-route tests with
58 subtests; 20 owned Mongo role/profile cases; 15 fixture endpoint safety cases;
ten genuine behavioral mutants; required war reminders (213 backend, one skip,
35 frontend); four-width layouts and three keyboard/short-screen workflows.
The configurable fixture URI rejects non-loopback hosts, credentials, database
paths, query options and ports outside 27150–27169 before creating a client.
The final owned server used 27161 and was stopped and removed.
Evidence is in `.local/p93-*`. All browser and transport data is disconnected
sample data; Mongo fixtures are owned loopback databases and are removed after
checks. No real roles, nicknames, notifications, imports or DM clicks were tested.


## Final workflow review checkpoint

The whole page keeps `member_roles` under Claude entry 298. Shared editors keep
their existing text and behavior; new page-owned words are in `members/strings`.
Moderation is a generic history link under entry 309; no moderation file changes.

The end-to-end review found and fixed two UI gaps: hidden selected nickname rows
can now be revealed without changing selection or parent filters; a person's
pending or failed role update now stays visible inside the phone/desktop person
panel instead of relying on progress behind that panel. Regressions exercise
the actual components with fake responses.

No old-worker compatibility is claimed for new typed role manifests. Release
requires no queued Standardize or bulk work and the normal 210-second drain. A
rollback after role use must retain a compatible worker or safely freeze queued
role work before an older worker is reintroduced; never erase accepted receipts
or restore production data to make a code rollback appear clean.

Current main includes participation follow-up PR151. Final regression, mutation,
keyboard and layout gates passed. Members is now a direct navigation link rather
than a one-item disclosure. Screenshots at 360 and 1440 were reviewed. The old
fixture has 1,447 synthetic members; the new fixture has 1,448 including 37 bots,
with 1,411 visible by default, so before/after fixture counts differ. The new
fixture does not supply a guild icon. Full frontend tests passed despite one
loopback proxy ECONNREFUSED diagnostic; no warning-free harness claim is made.
Vite reports its existing large-chunk advisory. No production role, nickname,
import, notification or DM action was performed.

## Prompt 106 rework

Real Hikari members include the guild's everyone role. Both REST review state
and Hikari write state now normalize that ID away, with actual entity-factory
regressions. The directory moved to `/manage/members/overview`; the original
member picker keeps its real route and ticket-settings fallback.

Per-person hierarchy refusal is a 422 review result with named blocked people,
not loss of page authorization or a silently reduced selection. Unmanageable
person switches are disabled. Clear selection remains available after a person
leaves. Role runs share the profile 150-second edit / 200-second worker budget
and known-429 retry boundary. Forbidden and NotFound are confirmed failures;
missing members have an explicit Left-the-server explanation. History pruning
uses separate per-type caps and preserves role receipts needed for auditing.

On phones, search, chips and Showing precede the list. Refresh, Fix nicknames,
Past nickname changes and About share one action menu; Bots is in Filters.
Page/all selection appears after the first tick. The bar is one horizontal line,
and the document is the sole vertical scroll surface. First-row top was 278.3px
at 360×800, including the local-fixture notice. At 320/360/390, the selection bar
was 58px high. Four-width checks also covered single-tap menus, Escape focus
return, keyboard opening, and Back restoring document scroll and opener focus.
Narrow selected and wide overview screenshots were visually reviewed.

Removed the unreachable `RoleMembers` disclosure, old roles-editor introductory
copy, role-only draft/action branches and their obsolete styles from
ServerManagement. Its catalog already routes that section to Members. The
original shared member picker remains for other authorized editors. Role
progress stays bounded to the current run's rows; no speculative polling API
or interval change was introduced.

Checks: guarded backend 5,988 passed / 89 skipped / 266 subtests; final frontend
1,479 passed in 260 files, TypeScript/build. Additional focused HTTP/transport
35 passed. Seven owned-Mongo role cases passed in 82.53 seconds, including real
Hikari against loopback HTTP: four role changes completed after a 70-second
429 wait; Stop during a two-second wait completed only the current person and
left three untouched. These are disconnected transport tests, never live
Discord evidence. The fixture database/server were removed. All six requested
survivor mutants were killed: Undo guard, receipt failure, Stop write permission,
second Stop check, protected confirmation and Stop pending guard. Required war
checks passed: 213 backend / 1 skip plus 35 frontend and build.

The first full frontend attempt failed 12 old-route/menu expectations in the
existing time-zone flow tests. Those were updated to exercise the new public
route and menu, and the final full suite passed. The exact staged boot check
is recorded separately before READY. First real role change remains Ruggie's,
on one person; no agent live role, rename, import, send or DM action was run.

## Prompt 109 follow-up

A new role or nickname run now inherits the largest unexpired known
`retry_not_before` from the same guild's shared member-change lane, including
cross-kind runs. Its manifest stays queued until that deadline; Stop still
settles a waiting run without starting a child. No uncertain effect is replayed.
The storage owner creates the additive partial `member_change_lane_backoff`
index and uses a projected, hinted lookup. Existing receipts remain unchanged;
active parent/standalone deadlines survive history pruning until they expire.
There is no new collection or SQL migration.

On phones the single-line bar contains the selected count and a visible Actions
button. The existing ActionMenu lists Add role, Remove role, Fix nicknames,
Select page, Select all matching and Select none. Write actions retain their
existing disabled rules; the menu and Select none remain usable while writes
are blocked. The bar does not scroll sideways. Desktop controls are unchanged.
Removed the now-unused member/role branch in `actionConfirmation`; the original
member picker remains intact for its other callers.

The earlier prompt-106 READY used the separate `.local/p106-layout-final.cjs`
and keyboard harness. It did **not** run the checked-in
`web/cwl/tests/members-page.browser.cjs`, which still asserted a bounded nested
scroller. That was a missed check. The file now checks the document scroll
surface and the 300px first-row target at 360×800. All three checked-in Members
browser files now run at 320, 360, 390 and 1440; keyboard also covers 640×460.
All 13 cases pass. Narrow bulk-bar and wide overview screenshots were reviewed.
The fixture network block can leave its remote guild icon unavailable; this is
not a production rendering check.

Final frontend: 1,483 tests in 261 files, TypeScript/build pass. The first full
attempt had one obsolete MemberPicker confirmation-text expectation after the
dead branch was removed; it was updated deliberately and the final suite passes.
Guarded backend: 5,991 passed / 96 skipped / 266 subtests; 95 final focused
backend cases include two added queued-deadline regressions after full collection.
Twelve owned-Mongo tests pass in 92.09 seconds. They include real Hikari's local
130-second rate-limit refusal for role/profile and both cross-kind sequences,
subsequent queued runs, Stop, expiry/guild scope, restart persistence and active
receipt retention. The separate 70-second SDK wait cases remain covered. This
is loopback transport evidence, never live Discord delivery.

The first cross-run test incorrectly awaited the whole queued delay and then
counted a request made after the 130-second deadline. It was interrupted and
its owned fixture cleaned up; the corrected tests observe the wait asynchronously
and Stop before expiry. Five backoff cases pass in about 10.5 seconds. All six
new guard mutants die: overview hierarchy, preview target refusal, disabled
person switch, genuine preview 403, unmatched receipt and reset backoff. No
collection/import failure is counted as a killed mutant. Owned exports and
Mongo instances were removed. War-reminder checks pass: 213 backend / 1 skip,
35 frontend, TypeScript/build. Exact staged startup evidence precedes READY.
No production role, nickname, import, notification or DM was exercised.

### Prompt 111: late backoff and phone selection delta

The durable owner now exposes one projected, indexed lane-backoff lookup. Run
creation uses it as before; `advance()` also checks immediately before creating a
child, so a delay recorded after creation is respected. A waiting parent records
the deadline and returns before child insertion. The worker excludes nickname and
role requests from claiming while the shared delay is active, leaves standalone
saves pending, and continues unrelated sections. The fast worker still sleeps on
an unhandled poll; it does not claim and requeue the same blocked request.

Phone Actions now says Unselect page when that page is selected. The phone count
uses a short visible form such as `1411 · 1410 hidden`, retaining the full selection
text as its accessible name. Desktop selection controls retain their existing form.
Checked-in browser tests exercise both toggle labels and measure the whole hidden
count inside its button at 320, 360 and 390px, as well as the existing desktop,
confirmation, Stop, keyboard and short-screen cases. The 320px hidden-count and
1440px overview screenshots were visually reviewed. An unavailable remote guild
icon in the network-blocked fixture is still a fixture limitation.

The test-order leak was a fixture authorization binding: role transport imports
`dashboard_allowed` by name, so patching only the source module depended on import
order. The lane fixture now patches both bindings, with automatic restoration.
Role transport followed by lane tests passes, and the full owned-Mongo role suite
followed by lane tests passes. This changes test isolation, not authorization.

Owned Mongo regressions cover a backoff arriving after parent creation, standalone
saves staying pending, unrelated sections proceeding, and dispatch after expiry.
Dropping either new recheck makes its real-Mongo regression fail; both requested
mutants were killed in disposable source exports. Real Hikari tests use a local
fake HTTP endpoint, never Discord. No live role change, nickname change or send
was performed. The first real role change remains Ruggie's, on one person.

Initial full-suite attempts hit temporary-storage quota errors (EDQUOT), rather
than a source regression. Their logs are retained. Temporary files were moved to
owned workspace storage; Chrome additionally needed a short temporary-path alias
for its Unix socket. Final check counts are recorded in the READY handoff.
PR158 remains separate and explicitly held; it is not included in this branch.
