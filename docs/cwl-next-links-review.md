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
do not receive a usable Next callback. Unsaved edits retain existing leave
confirmation, and a changed joining instruction disables the Finalize Next cue
until the edit is resolved. No cue saves, publishes, sends, marks or changes a
season. Empty/loading/failed protected reads do not synthesize successful state.

## Single signup control location

Opening/closing signups stays in `StaffSignupControls` on Build roster. Seasons
keeps season creation and member-season visibility but removes its duplicate
signup mutation/dialog/visibility-reader hook. Its Next link leads to Accounts &
signups on Build, where the existing controls and permission checks remain.
The obsolete per-user Hosting clans moved notice and storage preference are
removed; Hosting clans remains a Build roster tab.

## Publish explanations

The Publish button's existing boolean gates and submission guard are unchanged.
A nearby accessible reason reports the first failed condition in that same order:
missing draft, permission, current operation/edit, refresh, read error, archived
season, joining instructions over 2,000 characters, changes not ready, no accounts,
or unacknowledged unplaced accounts. Existing archived/status explanations remain
visible; the adjacent reason uses distinct wording. No warning is mistaken for a
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
