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

### Paused checkpoint before review

Paused for higher-priority 147 rework of dependency119. Current source passed
1,571 frontend tests/270 files with two workers, TypeScript/build, API AST audit
and the missing-Publish-reason assertion mutant. An earlier parallel full run
hit one unrelated five-second quick-select timeout; its focused rerun and the
complete bounded-worker run passed without changing a timeout or excluding tests.
The browser run is unfinished: six narrow Next routes reached their screenshot
and navigation checks, but Back from the refreshed Bonus destination was attempted
before its loading/dirty state settled. Diagnose and complete the entire 360/1440
matrix on resume; this checkpoint is not READY. Existing harness failures and
fixture-only read overlays are retained in `.local/p120-*` evidence. Integrate
accepted147 changes before final validation and review.
