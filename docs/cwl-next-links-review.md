# CWL Next links review (120)

Release is held. This frontend-only change keeps the existing three-step strip
and adds one small shared read-only destination cue at the end of each eligible
CWL page. It does not expand the strip or change publishing, signup, delivery or
HTTP authorization rules.

## Destinations

Following review 460, the main chain is Seasons → Build roster → Finalize roster
→ Announcements → Declaration check → Results → Bonus medals. Seasons has only
Next: Build roster; Signup reminders also returns to Build roster. Return
reminders is an independent recurring campaign and has no Next cue. Existing
sidebar access to both reminder pages remains.

Build shows its cue only in Accounts & signups when no account is unplaced;
otherwise it gives the count and placement reason. Finalize uses persisted
publication state, not the temporary success notice, so its cue survives refresh.
Announcements still requires a confirmed sent pool in the matching publication,
not a queued or uncertain delivery. Declaration uses in-app Finalize navigation
when a roster is not published; its Results cue is available for a published
snapshot. Results leads to Bonus medals. Bonus ends the chain.

Navigation uses existing guarded application callbacks, selected-season context
and history. The Finalize Next callback uses the existing history-pushing helper,
so refresh and Back retain Finalize instead of replacing it with Announcements.
The automatic successful-Publish step callback stays separate so a pending
operation does not block its own completion. Destination permissions remain authoritative; unavailable targets
do not receive a usable Next callback. The tested Next/sidebar paths protect unsaved edits: review 149 adds the
previously missing Seasons pool-role dirty check, with one confirmation before
leaving. This is not a claim that every workspace historically had that guard.
A changed joining instruction disables the Finalize Next cue until resolved. No cue saves, publishes, sends, marks or changes a
season. Empty/loading/failed protected reads do not synthesize successful state.

## Single signup control location

Build roster is the primary home for `StaffSignupControls`. Staff who can open
Build get a Seasons Next link to Accounts & signups. Staff with only
`cwl_settings`, who cannot open Build, retain that same shared component on
Seasons; they keep their existing open/close permission. There is no second
signup implementation or server permission change. Seasons also keeps season
creation and member-season visibility.
The obsolete per-user Hosting clans moved notice and storage preference are
removed; Hosting clans remains a Build roster tab.

## Publish explanations

The Publish button's existing boolean gates and submission guard are unchanged.
A nearby accessible reason reports the first failed condition in that same order:
missing draft, permission, current operation/edit, refresh, read error, archived
season, joining instructions over 2,000 characters, changes not ready, no accounts,
or unacknowledged unplaced accounts. A pending comparison keeps its existing
Loading changes status; a failed comparison asks for Refresh draft, rather than
claiming the staff member has not reviewed it. Existing archived/status
explanations remain visible; the adjacent reason uses distinct wording. No warning is mistaken for a
new prohibition, and the unplaced acknowledgement still permits publication.

## Validation and limits

Validation results and isolated browser evidence are recorded after the final
source freeze. Initial stale test expectations and fixture/harness corrections
remain in local logs. No production data, provider calls, live messages, role
changes or notification tests are used. Real assistive-technology coverage and
live delivery remain outside these local checks.

### Post-147 validation checkpoint — not READY

Accepted dependency 147 (`93a5b179`) merged without conflicts. The combined
frontend passes 1,592 tests in 271 files (94.48 seconds), TypeScript and build.
A nine-file syntax/argument audit against 147 preserves API calls and existing
link destinations, including the two newly added pure helpers. The prior
missing-Publish-reason mutant remains applicable: its publication source and
tests are byte-identical after this dependency merge. The original successful
Publish setter remains separate from navigation-only callbacks.

All 18 functional browser cases at 360/1440 reached their Next, refresh and Back
assertions, with no page errors or campaign/signup/profile/role mutations. Six
additional Build/Return cases pass the strict all-POST assertion: unplaced
reason/no Next, clear Build one 44 px cue, Back, no cue on Compare, and no Return
cue. Narrow Build and wide Finalize screenshots were visually reviewed.

**The full 18-case zero-POST gate has not passed.** Initial and subsequently
more-settled navigation matrices recorded one or two
`POST /api/cwl/issues/browser` requests, whose payload is only
`{kind: "network_error"}`. These are retained failures, not a telemetry whitelist.
They occur around Announcements; no domain mutation is observed. Passive
pass-through fetch tracing records `TypeError: Failed to fetch`, not the earlier
hypothesized `AbortError`. Transport cancellation remains an inference, not a
confirmed explanation of the original payload. Waiting for network-idle both
before and after navigation did not eliminate every telemetry request. No claim
is made that settled or rapid navigation universally emits zero POSTs.

A bounded independent comparison served exact accepted-147 and combined-120
assets from separate synthetic fixtures. Eight runs (two sources × settled or
unsettled × two repeats) exercised Finalize/Announcements, refresh/Back and
Declaration transitions. Both versions had rejected fetches (147: one to four;
120: three to four per run), zero POSTs, zero domain mutations and zero page
errors. This establishes pre-existing rejected-fetch behavior; its narrower
sequence did not reproduce or attribute the full-matrix telemetry POSTs.
The temporary baseline fixture was stopped gracefully; existing previews and
all original traces remain. Application API/telemetry handling is unchanged.

Evidence: `.local/p120-full-fe-after147.log`, `.local/p120-build-after147.log`,
`.local/p120-api-proof-147.json`, `.local/p120-navigation-after147.log`,
`.local/p120-navigation-fully-settled.log`,
`.local/p120-layout/settled-with-telemetry-results.json`,
`.local/p120-layout/fetch-failure-matrix-results.json`,
`.local/p120-baseline-comparison.json` and `.local/p120-build-layout.log`.
This is a concrete review checkpoint pending judgment of the instrumentation
limit, not READY or permission to change API behavior or release.

### Final review gate — 475 exception

Review 475 accepts one narrowly scoped exception for this PR only. After explicit
fixture login, the final checker records every navigation non-GET. It rejects
all of them except the exact `POST /api/cwl/issues/browser` diagnostic route;
there is no prefix, other-method or domain-write exemption. All raw requests
remain in the report, and each viewport run prints its diagnostic count and
`kind`. No API/error-reporting implementation changed.

The final complete 18-case matrix passes this approved gate: at 360 px it records
one diagnostic POST of kind `network_error`; at 1440 px it records zero. Every
other navigation non-GET count is zero, fixture domain state is unchanged and
both runs have zero page errors. Six additional Build/Return cases retain the
original all-POST assertion and pass with zero POSTs. The old red results above
remain failures under the original criterion; the exception does not explain or
hide them. The rejected-fetch/noise cause remains unproven and is listed under
Later in the redesign notes.

All other gates remain satisfied: 1,592 frontend tests/271 files, TypeScript,
production build, all Publish explanations and preserved publication gates,
asserted missing-explanation mutant, nine-file API/link argument comparison,
normal Back/refresh and narrow/wide geometry/screenshots. Final evidence:
`.local/p120-navigation-approved475-final.log`, `.local/p120-layout/results.json`,
`.local/p120-build-layout.log` and `.local/p120-ready-evidence.json`.
No full backend suite was repeated for this frontend-only batch. Live sends,
production writes and full assistive-technology coverage remain untested.
Release remains held.

## Review 149 delta checkpoint

The reviewed c638ec3 source had five reproduced failures: settings-only staff
could not reach open/close controls; publish-only staff saw the Announcements
Next cue; Declaration treated another publication step's grant as Finalize
permission; and dirty Seasons role edits left through Next or the sidebar
without confirmation. The runtime was changed only after those red assertions.
The initial happy-DOM confirm mock was corrected before reproducing both real
dirty-navigation failures; all logs remain.

The shared signup control fallback preserves settings-only users, while Build
remains home for everyone who can open it. Finalize checks `cwl_send` before
showing Announcements; Declaration and manual publication navigation check the
exact `cwl_publish`/`cwl_send` step using the existing navigation permission
filter. Unavailable actions are hidden, with neutral unpublished status retained.
Seasons and Reminders both use the existing guarded Accounts-tab navigation
helper. Seasons aggregates role/signup dirty and busy state; Next and sidebar
ask exactly once and retain the role draft when cancelled.

Comparison loading/error explanations now match the actual read state; all
original Publish boolean gates remain. A rendered seven-case test compares the
real Publish button with its helper explanation. Singular unplaced accounts use
it, the unused Seasons userId prop and hosting-notice CSS are removed, and the
location update is dated in the web development notes.

Requested checks currently pass: full frontend 1,621 tests/272 files (100.15s),
TypeScript/build, 16 targeted assertion mutants, and seven-file API/link argument
comparison. Chrome covers the owner chain's 27 cases and 15 limited-permission
cases at 320/360/1440. Every non-GET except the exact 475 diagnostic route is
absent; owner runs print diagnostic counts 0/1/0 (one network_error at 360), and
all 15 limited-permission cases print zero. Domain state is unchanged, no page
errors or overflow occurred. Real unsaved pool-role selection shows four correct
native confirmations per width: Next dismiss/accept and sidebar dismiss/accept,
with draft preservation and Accounts-tab restoration. Narrow/wide fallback and
neutral unpublished-state images were visually reviewed. These are synthetic
UI-grant overlays, not evidence of changed server authorization or live writes.

Initial browser failures were fixture-selector mismatches: native role labels
include option text, the mobile trigger is Open menu, and the CWL group is
collapsed. Their logs remain; no app behavior or assertions were changed for
those corrections.

One adjacent pre-existing automatic-Publish behavior was identified during the
completion review: the original successful-Publish callback still calls the
Announcements setter even without cwl_send. Manual Next is fixed; the separate
automatic setter was deliberately retained in 120. Actual-source AST execution
with a fake successful API confirms it. No server permission bypass or live
operation is claimed. Scope judgment is pending in question 967 before changing that behavior
or declaring the final 149 delta READY. No adjacent automatic-setter fix or
deferral is assumed by this checkpoint.
