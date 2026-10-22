# CWL design guide

Status: research and redesign direction, October 22, 2026. This document is a
living companion to [the dashboard interaction standard](dashboard-interaction-standard.md).
It does not imply that the proposed CWL layout has been implemented or deployed.
Update it when a pattern is tested, adopted, changed or rejected. Keep behavior
and accessibility requirements from the interaction standard authoritative.

## Purpose

Make roster work feel like managing a clear list of players rather than navigating
a collection of buttons and menus. Preserve WU's signup, placement, weight,
readiness and publication workflows. Borrow interaction ideas, not another
product's business rules or branding.

## Evidence inspected

Authenticated browser inspection of [ClashPerk rosters](https://clashperk.com/rosters)
and [ClashKing dashboard](https://dash.clashk.ing/) on October 22, plus the owner's
mobile recording. These are observations of the available screens, not claims
about every feature or successful end-to-end notification delivery.

| Observed pattern | Useful WU adaptation | Qualification |
| --- | --- | --- |
| ClashPerk: roster selector, compact capacity/status header, common player list | Keep season/roster context above the list without a stack of explanatory cards | WU uses Main/Lazy pools and hosting clans; do not introduce redundant roster objects |
| ClashPerk: selection count with shared change-roster/group/remove controls | One contextual Assign/Move toolbar for selected players | Make selection scope and destination explicit; keep destructive actions separate |
| ClashPerk: search, war-preference counts, sort and export beside the list | One compact search/filter/sort toolbar with relevant counts | WU needs assignment/readiness filters, not identical war-preference filters |
| ClashPerk: Add players offers list lookup or paste tags in one dialog | One Add accounts entry point, with search and optional bulk input | Reuse existing linked-account checks and signup validation |
| ClashPerk: settings grouped into Basics, Sign-ups, Requirements and Display | Move occasional configuration out of daily placement work | Its long editor and dense column picker should not be copied wholesale |
| ClashPerk: roster overflow contains clone, close sign-ups, refresh and delete | Quiet overflow for infrequent actions | Keep refresh discoverable; distinguish destructive actions |
| ClashKing: roster detail separates Members, Automations and Settings | Separate daily roster work from scheduling/configuration | Keep WU publish review and readiness safeguards |
| ClashKing: member-name popover exposes tag, clan, TH and profile link | One focused details surface for account context | Owner previously requested plain player names; use an explicit Details control instead |
| ClashKing: configurable displayed columns | Start with a purposeful default field set | Do not add a complex column editor unless staff need it |
| ClashKing: compare mode selects 2–4 rosters with a visible count | Explicit selection and comparison context | WU comparison requires total weight, capacity and unknown-weight counts |

Observed usability failures to avoid: ClashKing's member button exposed as
"Actions" immediately removed a member, rather than opening a menu. The affected
DragonSlayer003 entry was restored using its linked account (#LQG2YCGGU), and
Dandelion was verified back at two members. WU destructive controls must say what
they do and require an explicit confirmation. Several column-reorder controls
also lacked useful accessible names in the inspected tree. Do not copy these.
ClashPerk's Change roster control was unavailable with the single available roster;
that transfer path was not exercised. ClashKing comparison exposed drag handles and
horizontal scrolling on the narrow layout; WU must retain an explicit, accessible
Move alternative and avoid relying on drag gestures alone. Group-change dialog and cancel were inspected,
but no group changes were saved. No notifications were sent.

## WU clutter identified in code

- Roster work stacks global context, page heading, Build/Finalize/Announcements,
  Main/Lazy, four working modes and a toolbar before the account list.
- Assign accounts repeats destinations as review-settings and missing-weight shortcuts.
- Manage signups repeats Open roster and separates member finder from list controls.
- Publication stacks status, readiness, form and preview cards with repeated headings.
- Repeated row buttons give occasional edits the same emphasis as placement work.

## Design rules for the CWL refresh

1. **One clear task at a time.** One page heading, one working-view selector and
   one toolbar. Do not add another tab row inside an existing tab row. Keep season
   and Main/Lazy context visible without making them extra navigation levels.
2. **Players are the content.** Use a shared list surface with quiet row dividers.
   Avoid a bordered card inside another card for each player. Desktop may use
   aligned columns; mobile uses compact stacked rows with the same essential fields.
3. **Default row information:** selection, TH artwork, player name, player tag,
   full weight, assigned hosting clan and assignment/readiness status. Show current
   clan as supporting context. Keep Discord identity available through Details;
   never make a name tap silently open an edit form.
4. **One action hierarchy.** A filled gold control marks the main next action.
   Secondary controls use neutral/quiet styling. A toolbar owns bulk actions;
   every row must not repeat Edit, Message, Move and Details as large buttons.
   Do not hide frequent placement behind an ambiguous ellipsis.
5. **Selection gives context.** Show how many accounts are selected, Clear selection,
   and the available Assign/Move action. Explicitly distinguish visible rows from
   all matching results. Do not silently carry hidden selections into a mutation.
6. **Edit in one focused surface.** Use a side panel on wide screens or a focused
   sheet/page on phones. Group related fields; keep Save/Cancel together. Preserve
   draft input on failure and protect navigation away from unsaved changes.
7. **Compact does not mean tiny.** Keep at least 44px touch targets. Initial styling
   direction: 4/8/12/16/24px spacing, restrained 8–12px control/surface radii,
   readable body text and 16px editable input text on mobile. Treat these as starting
   tokens to validate, not excuses to clip long names or shrink content to fit.
8. **Use color for meaning.** Neutral default; gold selection; green saved placement;
   red actionable errors and changes affecting assigned players. Always include
   text. Preserve the owner's visible per-player placement highlighting; comparison
   and declaration colors have their own meanings and must not share a generic rule.
9. **Totals must be useful.** Show total clan weight, not average weight. Format
   large totals clearly and retain exact values when needed. Show unknown-weight
   counts so a partial sum is never presented as complete.
10. **Status before explanation.** Put concise status and important errors where
    staff work. Hide history, weight provenance and lengthy help behind Details.
    Remove duplicated "ready to place" explanations, not actionable warnings.
11. **Navigation is not an action.** Use clear destination labels; avoid duplicate
    cross-links at every level. Keep old URLs functioning while generated links use
    canonical paths. Preserve Back/Forward, search, pool, season and scroll context.
12. **Destructive actions are explicit.** Say Remove from roster, not Actions.
    Confirm the player/count and destination; cancellation must not mutate anything.
    Preview before bulk placement or member-facing publication.

## Workflow invariants

- Dashboard grants remain server-enforced; only the protected owners manage access.
- CWL management and clan management remain separate permission areas.
- Working placements remain staff-only until explicitly published.
- Main and Lazy remain distinct placement pools; Lazy destinations use Lazy hosts.
- Saved clan weights remain authoritative for family players; manual loot/full-weight
  editing and source fallback rules remain intact. Do not reset saved weights.
- Show signup-change alerts only for previously assigned players, with former hosting
  clan and review state. Preserve audit history separately.
- Keep season boundaries, readiness checks, capacity validation, revision conflicts,
  stale-response protection, unsaved guards and duplicate-submission protection.
- Review/confirmation precedes publication and Discord sends. A visual redesign must
  not introduce autosend or automatic retry of uncertain sends.

## Proposed implementation order

1. Prototype Assign accounts: compact rows, one toolbar, contextual selection and
   focused Details editor, using isolated sample data.
2. Carry the same patterns into Manage signups; remove duplicated navigation.
3. Align Compare clans and readiness without losing their distinct status meanings.
4. Simplify publication review and announcements while keeping explicit save/send gates.
5. Reuse only patterns that survive testing in other dashboard areas.

Do not combine this with a storage migration, new permission model or unrelated
feature work. Move existing controls and reuse their handlers before replacing logic.

## Acceptance checks for each adopted pattern

- Viewports: desktop, 390px, 320px, short landscape; no horizontal page overflow.
- Long names/tags, many accounts, empty lists, no matches and missing/upstream data.
- Keyboard focus, accessible names, 44px targets, Escape/Cancel and focus restoration.
- Selection → filter → assign/move → cancel/save → return; count and state stay clear.
- Failed save, stale revision, revoked permission, pending requests and dirty navigation.
- Staff draft versus member published views, Main/Lazy destination restrictions,
  source-weight persistence, unknown totals and assigned-change alerts.
- Relevant automated regressions, frontend build and isolated browser verification;
  deployed revision, service health and served assets when deployment is authorized.

## Decision log

| Date | Decision | Status |
| --- | --- | --- |
| 2026-10-22 | Shared sidebar frame and mobile menu improved | Already deployed separately |
| 2026-10-22 | Reduce CWL navigation layers and repeated row buttons | Proposed; no CWL UI changes in this research pass |
| 2026-10-22 | Borrow compact lists/contextual actions, preserve WU workflow | Direction from owner; prototype next |
| 2026-10-22 | Retain green assigned-player indication and total weights | Existing owner requirements |

### Assign accounts implementation — 2026-10-22

Adopted compact rows in one shared list surface, grouped search/filter controls,
inline totals, and a contextual bulk toolbar above results. Assigned rows remain
green; selection overrides them with gold. Explicit Assign/Move and Details are
the row actions. Details reuses the player editor and discloses source/provenance
information without repeating edit fields in every row. Closing restores focus.
Routine touch targets remain at least 44px.

Cross-page selection is retained and explicitly counted. Selecting a page that
would exceed 50 is disabled with an explanation, rather than silently truncating.
Bulk confirmation states the count and destination. Existing revision, permission,
capacity, official-weight and publication boundaries are unchanged.

Validation: 233 frontend tests and 51 backend roster, publication, placement,
official-weight and access tests passed; TypeScript/Vite build and diff checks
passed. Sol implemented and Luna independently reviewed affected paths and added
a Lazy-host destination regression. Isolated SQLite fixtures covered 65 accounts,
long/external-looking names, missing weights, green/gold states, desktop 1440px and
mobile 390px/320px, 44px row controls, no horizontal overflow, dialog focus return,
cross-page selection/50 limit, filter selection reset, Lazy-only destinations,
single assignment, manual loot conversion, failed save retaining input, retry and
reload persistence. Bulk cancel made no write; simulated 409 retained selection
and displayed refresh feedback; retry saved and cleared selection.

Native browser confirmation UI could not be driven reliably by the browser tool.
Its boolean outcomes were injected only in the isolated fixture to verify cancel
and submit paths; this does not validate the native popup or assistive technology.
No live roster data or Discord notifications were used. Existing Vite bundle/import
and aiohttp warnings remain. Compare, readiness, publication and Manage signups
redesigns remain separate stages.

### Manage signups implementation — 2026-10-22

Carry the shared-list pattern into signup administration. Search, CWL type,
placement and Refresh share one filter area; Discord member lookup is an optional
filter within that area. Remove the duplicate Open roster shortcut. The sidebar
remains the route to placement work.

Group accounts by Discord member, with visible identity and compact player rows.
Keep exact hosting clan and assignment state visible, with green saved placement
and gold selection. Edit signup opens the existing selected-account action flow;
pool switches and removal still require explicit save/confirmation and explain
which placements will be cleared. Add signup remains the single entry point for
member lookup or player-tag entry. Do not duplicate its underlying editor.

Preserve revision checks, member ownership, FWA eligibility, staff-only placement
data, archived-season restrictions, and published-roster separation. Changing the
layout must not change any weights, grants, saved signups or notifications.

Validation: Sol implemented and Luna independently reviewed the changed signup
paths. 235 frontend tests and 100 relevant backend tests passed, covering staff
signup changes, ownership, FWA eligibility, stale revisions, archived seasons,
publication privacy, access scopes, signup entry/anchors and roster behavior.
Production build and diff checks passed; existing Vite chunk/import and aiohttp
warnings remain.

Isolated SQLite/browser checks used 45 fictional accounts across 15 members.
Checked desktop 1440px and mobile 390px/320px, long and external-looking names,
username search, exact assigned clan, identity-service fallback, and 44px row and
confirmation controls. No horizontal document overflow on inspected screens.
Verified Cancel focus return; failed save retaining selections/action; stale-save
error, Cancel and Refresh recovery; successful removal of an entire member group
with persistent success feedback and stable heading focus; a pool change removing
the current filtered group with the same focus fallback; reload persistence; and
503/403 list errors clearing records without presenting an empty-success state.
Add signup member/tag modes remain reachable, and dirty tag entry disables list
actions. Native discard cancellation was simulated only in the isolated fixture;
native popup operation and assistive technology are not certified. No live
signups, weights, permissions or Discord messages were changed during testing.

### Outside-clan warning in Assign accounts — 2026-10-22

A confirmed current clan outside both the family directory and active hosting
directory gives the Assign accounts row yellow shading and an explicit
“Outside family / hosting clans” label. It takes priority over assigned green;
checked selection retains its separate styling. Compare and declarations are
unchanged. Stale/unavailable location, no clan, or unavailable family directory
does not prove an outside clan and therefore does not trigger the warning.
No persistent data is changed.

Validation: 235 frontend tests, 39 roster/publication backend tests and production
build passed. Added regressions for family, outside, active host without lineup,
archived host, directory outage, no clan, stale and unavailable locations.
Independent review found no blocker. Isolated 390px browser verified yellow
assigned-outside rows, green family rows, visible explanation and no overflow;
desktop Compare had no outside-row classes. Existing build warnings remain.

### Compact mobile assignment rows — 2026-10-22

Place weight beside player identity on mobile, hosting clan beside the quiet
Assign/Move action, and current clan beside Details. Replace the standalone Kept
line with a non-interactive lock icon next to the destination, with an accessible
explanation. Details calls the existing control Lock placement and explains that
auto-place will not move it. Held-unassigned entries retain an explicit explanation.
Move/Details remain native buttons with visible keyboard focus and 44px targets,
but no filled boxes. Green/yellow/gold row meanings are unchanged.

Validation: 235 frontend tests and build passed; isolated browser checks at 320px,
390px and 1440px showed no horizontal overflow. Standard sample mobile rows were
151px tall (long names 162px), versus about 200px previously. Verified 44px actions,
selection colors, Details open/close, unchanged Lazy-only assignment editor, and
held-unassigned text spanning the desktop summary. Independent review caught the
held-unassigned explanation and summary-grid issue; both were corrected and
verified before release. No API, storage, permission or auto-placement changes.

### Compare clans and declaration readiness — 2026-10-22

Compare uses one filter toolbar and compact player rows with explicit Details and
DM actions. Clan selection remains capped at ten; ordering and column replacement
are secondary disclosures. Desktop retains side-by-side columns; mobile shows one
selected clan with previous/next and a named selector. Main/Lazy selection and
order are saved separately. Total weights include all assigned players even when
a Town Hall filter hides rows; unknown weights remain explicit. Clan totals show the full calculated number with comma separators (for example,
`1,542,000`), never `k` or `m`. Individual player weights retain their compact format. Location colors retain their
own meaning: green in the selected clan, red elsewhere, gray unverified.

Declaration readiness starts with source, search, attention filter and clan counts.
Compact expandable clan groups show arrived totals and individual current-location
states; ordinary actions are quiet text controls with 44px targets. Names are plain
text. Published snapshots remain distinct and read-only, including the no-publication
fallback. Invalid/missing/stale or in-flight checks cannot count as arrived. Ready
requires at least 15 assigned accounts, every one freshly arrived, and no loading,
error or outdated-publication state. This remains a location check, not a claim
that all in-game declaration requirements have been checked.

Read failures clear records and offer Retry; they do not continue an automatic
failure loop. Open account dialogs pause polling and lock filters. Existing player
editing, save revisions and source weights are reused; declaration navigation now
protects dirty account edits and pending writes. Closing Details restores focus.
No storage migration, permission grant, publication or notification changes.

Validation: Sol implemented Compare and reviewed the readiness integration; Luna
reviewed source/state boundaries and added readiness regressions. 242 frontend
tests, 73 relevant declaration/publication/roster backend tests and production build
passed. Isolated SQLite/sample-data browser checks covered desktop 1440px and
mobile 390px/320px, long external-looking names rendered as text, 44px row controls,
no horizontal document overflow, mobile clan switching, reorder persistence across
Main/Lazy, search opening ready groups, a 20/20 ready clan and below-15 exception,
invalid timestamp handling, 403 clearing and Retry recovery, read-only published
fallback, dialog open/close/filter lock and focus return. Published-outdated and
concurrent-write behavior are covered by regression tests; live Discord delivery
and assistive technologies were not tested. No live rosters, weights or messages
were changed during validation. Existing build size/import warnings remain.

### Softer rows and Discord identity in account Details — 2026-10-22

Use low-opacity status tints over the neutral row surface with slim colored edges;
retain green assigned, yellow outside family/hosts and gold selected semantics.
On mobile, group hosting/current clan information together and place quiet Move
and Details actions side by side. Avoid a separate 44px band for every datum.
Keep touch targets 44px, with names and exceptional states wrapping naturally.

Account Details resolves the linked Discord member only while the dialog is open.
Show a small avatar, display name, username and exact Discord ID together, with a
quiet DM link. Use the existing staff-protected directory endpoint, matching the
requested ID exactly; allow only Discord CDN avatars. Keep a visible unavailable
fallback and Retry after lookup failure. Identity reads do not change links or
permissions. Current clan and weight are compact facts rather than separate boxes.

Validation: independent identity/access review and 58 related backend regressions
passed. Isolated browser inspected successful profile/PFP loading, failed lookup
with ID retained, successful Retry, narrow 320/390px layout and 44px actions.
Normal mobile rows now group information in two bands; unusually long clan names
and warning text still expand rather than truncate. 242 frontend tests and production build passed; the desktop 1440px layout
and narrow modal width were also verified without horizontal overflow. No live account or roster
writes or Discord messages were used in verification.

### Finalize, publish and announcements — 2026-10-22

Finalization uses a compact visibility/count summary, readiness checks, and a
searchable clan preview before the publish action. The preview's Main/Lazy filter
does not limit publication: both pools are explicitly included in the action and
confirmation. Keep unassigned acknowledgement, archived-season rules, revision
checks and published snapshot separation. Names are plain text with quiet Details
controls. Pending writes and account dialogs lock conflicting navigation/refresh;
failed preview reads clear protected records and offer recovery.

Announcements use separate Main/Lazy tabs with visible saved/delivery state,
destination, a message/link disclosure and optional mounted-on-open preview.
Use one primary action: Save when edited, Send when saved. Saving is not sending.
Test delivery and combined-pool sending are secondary disclosures. Preserve the
confirmation's destinations and role-ping warning. Sent/pending/sending/uncertain
states block replay; delivery receipts and backend owners are unchanged.
Announcement permission gates editing and sending controls as well as server writes.
CWL month edits participate in dirty/navigation/refresh protection. Profile, image,
and message previews are not newly fetched/rendered in closed preview sections.

Validation: Sol implemented publication review and Luna independently reviewed
permission/state boundaries. 242 frontend tests, 27 bridge/announcement regressions,
9 publication regressions, and the production build passed. Isolated SQLite and
simulated announcement transport verified canceled publication, acknowledged
sample publication advancing to announcements, independent pool drafts, failed
save preserving content, successful save without sends, canceled refresh retaining
edits, mounted preview, uncertain-delivery resend blocking, and desktop 1440px /
mobile 390px and 320px layouts without document overflow. Confirmation outcomes
were injected in the fixture; native popup operation and assistive technology were
not certified. Sample publication affected only temporary SQLite. No live roster
publication, Discord send, or role ping occurred. Existing build/aiohttp warnings
remain. These checks do not prove live notification delivery.

### Lazy bonus review and draw — 2026-10-22

Bonus winners now starts with season/host context, a compact allowance/candidate
summary, searchable rows and focused account review. The review carries the three
season flags, a reasoned eligibility exception and saved author/time. Manual
candidates use verified player-tag lookup and an explicit reason. The role picker
loads on demand. Ordinary row actions are quiet 44px controls; mobile steps wrap,
long names reflow, and the candidate list reveals 20 records at a time.

Reviewing or opening an editor cannot draw. Unsaved/open review and add forms
invalidate the preview and block saving winners. A saved draw leads to approval,
then a separate announcement; equal-or-fewer candidates than slots uses Save all
winners. Flags, provenance, incomplete source and role failures remain visible.
Main retains its configured minimum. See `cwl-lazy-bonuses.md` for Lazy rules,
manual-candidate boundaries, ticket weighting, history and durable storage.

Validation: Sol implemented the UI, Luna implemented/reviewed storage/domain,
and both independently reviewed the other boundary. 246 frontend tests, 116
bonus/participation/recovery backend tests (one external integration skipped),
and 26 access/architecture regressions passed. TypeScript/Vite build and diff
checks passed. Tests include Main compatibility, 3/8 qualification, streak/reset,
reasoned overrides, multiplier validation, no duplicate winners, stale approvals,
archived/unauthorized writes, malformed inputs, foreign roles, role outage,
manual-candidate add/remove without signup mutation, and database reopen.

Isolated SQLite/provider browser checks covered 24 fictional accounts, long
external-looking names, search, manual addition, representative role save,
failed save retaining the reason, canceled discard, successful save with focus
return, preview invalidation on review open, six-winner draw and approval,
403 clearing/retry recovery, empty hosting clan, and 1440px/390px/320px layouts
without horizontal document overflow. Role/channel providers were simulated;
the real announcement transport was not used. Native confirmation cancellation
was fixture-controlled; native popup and assistive-technology operation are not
certified. Existing aiohttp warnings and Vite chunk-size warning remain.

### Results and participation — 2026-10-22

Use compact rows with attacks, stars, assigned hosting clan and source status.
Details opens one focused native dialog with the linked Discord identity, source
provenance, existing correction fields and staff notes. Keep incomplete/source
warnings visible, and distinguish staff corrections from captured observations.
Unknown totals remain unknown. Capture health and last check stay visible; capture
settings and saved historical records are disclosures. Profile and history reads
start only when their sections are opened. Pagination precedes history.

Preserve existing per-account audit records and source/reset semantics. Failed
saves retain edits; concurrent changes require explicit adoption of latest values.
Capture settings now expose an optional timestamp concurrency token, consumed by
the dashboard without changing legacy API payload support. Background checks do
not advance that token, and a settings edit during capture invalidates its result.
Malformed/naive source timestamps are stale rather than fatal. No storage migration
or bonus-policy change is included.

Validation: Sol implemented the frontend and Luna independently reviewed the
participation contracts and state handling. 246 frontend tests, 137 relevant
backend/access/durability tests passed (one external integration skipped), plus
TypeScript/Vite build and diff checks. Existing aiohttp and bundle-size warnings
remain. Isolated SQLite/provider checks used 45 fictional accounts with complete,
partial and unavailable sources. Tested search, pagination, external-looking names,
Discord identity, history on demand, failed-save retention, canceled discard,
successful save/focus return, actual row-revision conflicts, actual settings-token
conflicts and explicit discard recovery. A 503 refresh retained labeled old data
and paused writes; list/history 403 cleared protected results; Retry recovered both.

Inspected desktop 1440px, mobile 390px/320px and short 740×320 layouts without
horizontal page overflow. Dialog controls retained 44px targets; the short-screen
footer was non-sticky. Tab/Shift+Tab wrapped inside the dialog; Escape closed it
and returned focus. Confirmation cancellation used a fixture-controlled boolean,
not native popup automation; assistive-technology operation is not certified.
No live roster/results edits or Discord notifications were used for validation.

### Season exports and history — 2026-10-22

Season exports provides a searchable preview for accounts, current participation,
saved participation history and bonus-selection history. Preview and CSV download
use the same read-only snapshot builder, so the displayed row count and CSV basis
come from one consistent server-side read. Search filters the preview only; the
download includes every saved row for the selected export. Names and notes remain
literal spreadsheet-safe text, and Discord IDs retain their full values.

Published-roster exports use the immutable published identities and weights. A
result recorded for a different account assignment is not silently attached to a
published or current roster row: it is identified as belonging to another
assignment, while its original provenance remains in saved participation history.
Archived working-placement exports intentionally use the latest saved working
weights; those weights are not frozen by archiving. Published snapshots remain
separate. No storage migration is required.

Validation: the combined CWL backend gate passed 182 tests with one external test
skipped, including the 95-test export/roster/participation/bonus/backup gate, 15
dashboard-state tests, and 72 Lazy-bonus, announcement, bridge, signup-change and
clan-permission tests. The frontend suite passed 249 tests and the production
build passed. The seasonal journey covered signup, pool consent, withdrawal,
autoplacement, hiding member placement before publication, publication, results,
Main bonus, archive, exports and storage reopen; Lazy rules were checked in
independent suites. Mongo backup behavior was exercised with simulated tests, not a
live production restore. Browser checks covered desktop 1440px, mobile 390px and
320px, archived-season notes, search, safe literal names, successful download,
503 recovery and preview clearing/retry. No live Discord or push delivery was
tested, and these checks do not prove production authentication or a live write.


### CWL reminders and announcements — 2026-10-22

The reminder editor presents message audience, destination, schedule and delivery
state together, with contextual save, refresh and retry actions. Signup links stay
locked in this editor. Previewing is silent; saving changes settings but does not
send a message. The published-roster announcement review shows the CWL month,
publication version, destination, role recipients and rendered message before a
staff member queues one or both pool announcements. Canceling the review queues
nothing. Delivery labels distinguish queued, sending, sent, failed, uncertain and
stale states; the UI shows confirmed-send time, otherwise status-update or first-request
time when the existing receipt has it. No storage migration or delivery-policy change
is included.

Validation: 252 frontend tests and the production build passed. The backend run
passed 116 tests across the 77-test campaign/reminder/announcement/worker suite and
39 additional reminder, status and dashboard regressions. Isolated browser checks
covered 1440px, 390px and 320px widths without horizontal overflow; reminder 503
save retention and 403 clearing/retry; announcement lookup 403 clearing; canceling
send review with zero queued requests; one confirmed mock queue followed by pending
and uncertain send blocking; dialog focus containment/restoration; and contextual
return-selection controls and filter clearing. Tests exercise existing Mongo
persistence semantics but are not a new disaster-recovery restore. No live Discord
messages were sent; mock queue success does not prove live delivery. The delayed initial-load race was checked in the browser; publication refreshes
retain unsaved drafts. Full assistive-technology operation is not certified.

### 2026-10-22: Lighter green status highlights

Brightened assigned/arrived/success green backgrounds and borders across roster,
signup, comparison, readiness, member assignments and matching dashboard status
views. Existing alpha values are unchanged (assigned roster rows remain 0.105);
yellow warnings, gold selection and red errors retain their meanings.
Validation: 252 frontend tests and production build passed; isolated sample roster
visually checked at 390px and 1440px. Desktop had no horizontal overflow. This is
a palette-only change; no authorization, persistence or notification behavior
changed. Physical phone display differences were not tested.

### 2026-10-22: Optional Discord grouping in Assign accounts

The League picker now uses the short label “League”. Filters includes “Group by
Discord user”, off by default and reset on remount. It preserves existing roster
rows/highlights and groups the filtered results by exact Discord ID. Within each
member, the selected account sort is retained; member order follows the first
matching account. Unlinked accounts remain separate. Pagination keeps a member
whole, allowing an oversized group its own page; the existing 50-account bulk
mutation limit is unchanged. Grouping can be disabled without losing selection.
Manage signups is unchanged.

Names, avatars and Discord IDs use one season-scoped lookup only while grouping
is enabled. Stale responses are ignored on season/toggle changes; failures preserve
ID-based groups with explicit retry. Account dialogs retain on-demand lookup.
Independent review found and corrected per-header request fan-out. 260 frontend
tests and TypeScript/Vite build passed. Tests cover unlinked identity separation,
ordering, pagination and oversized groups. Isolated 390px/1440px browser checks
covered default-off, League label, group identity, selecting 24 accounts together,
clearing selection and returning to 20-account ungrouped pagination. No production
roster mutations or live Discord messages were used. Existing build size warning
remains; physical-device/assistive-technology testing was not performed.

### 2026-10-22: One roster and signup workspace

Replace the separate Manage signups page with one roster workspace. Preserve
Compare clans beside Assign accounts, with its existing Main/Lazy comparisons,
clan selection and account operations. The account list supports All/Main/Lazy;
auto-placement and bulk placement require an explicit Main or Lazy group.

Signup status stays visible. Add signup is secondary; opening/closing the signup
window is disclosed and requires CWL settings permission. Selected accounts reveal
signup actions and a review that explains cleared placements and unchanged
published rosters. Details offers occasional account signup changes. Signup and
placement permissions remain distinct; the sidebar admits either grant to this
workspace, not to every action. Old Manage signups URLs resolve to the roster with
the season retained. Remove the obsolete duplicate list/editor and its styling.

Signup changes across members use explicit selected tags, a maximum of 50, and one
revision-checked transaction. A malformed/missing account, ineligible Main change,
or concurrent revision rejects the whole request. Existing member-scoped callers
remain supported. Published snapshots and saved weights remain separate. No data
migration or notification delivery change.

Completion review: 259 frontend tests and the TypeScript/Vite production build
passed; 112 backend tests plus 49 subtests passed. Backend regressions cover
separate signup/roster grants, atomic cross-member changes, malformed/duplicate
and oversized selections, stale revisions, ineligible switches, saved weights,
and published snapshot preservation. Independent review corrected archived
editor controls and stale Details drafts after a revision conflict.

Isolated browser checks covered legacy-link normalization, retained Compare clans,
All/Main/Lazy selection, signup-only versus roster-only controls, member details,
Add signup, bulk review/cancel, a simulated failed save with inline recovery, and
a successful sample removal with refreshed counts. Responsive checks included
320px, 390px and 1440px widths. Fixture permission responses test UI visibility;
server authorization is covered by backend tests. No production signup/roster
mutations or live Discord messages were used. Physical-device and assistive-
technology testing was not performed; the existing bundle-size warning remains.

### 2026-10-22: CWL clutter cleanup

Keep the daily working area ahead of explanatory material. Roster modes now sit
above pool/status controls; counts use one compact strip only on Accounts & signups.
Compare clans remains a first-level working view with all picker, ordering, filter,
location and editing controls. Its totals explanation is disclosed. Placement
colors, selection behavior and the separate comparison/readiness meanings remain.

Remove the extra More row from the roster header. Exports is directly available
in the sidebar Results & bonuses group; CWL settings remains in the sidebar.
Publication-only staff have a direct Publish roster entry. Hide empty permission
subgroups and useless single-destination shortcut bars. Keep the publish workflow
shortcuts compact on phones. Signup-window controls remain available in both the
contextual disclosure and season settings so settings-only staff retain their
existing workflow; these use the same API and do not add another storage owner.

Publication shows only nonzero readiness issues and keeps the member/Discord
publication distinction beside Publish. Readiness snapshot details use the compact
status line; outdated snapshots retain their warning and working-roster action.
Results/bonus headings no longer repeat their tabs. Bonus rule essentials and
source problems stay visible; calculation details, historical qualifications and
sent-message links are secondary. Bonus announcement preview mounts only when its
disclosure is open. Reminder explanations move below the working area. Export
format help follows records; working/published basis and full-download scope stay
visible. Existing-member signup shortcuts now say Account details accurately.
Remove obsolete summary and heading styles alongside the markup.

Validation: independent agent review, 261 frontend tests, 34 backend permission,
signup and bonus regressions, and TypeScript/Vite build passed. Isolated browser
checks covered roster/Compare reachability, publication warnings and member-visible
status, reminder overview-to-editor, export summary, results, saved bonus preview
open/closed, and readiness working/published switching with an outdated snapshot.
Layouts were inspected at 320px, 390px and 1440px; inspected pages had no horizontal
document overflow. Navigation render tests cover signup-only, roster-only,
publication-only and results-only permissions. No production records or live
Discord messages were changed during testing. Physical-device and screen-reader
checks were not performed; existing bundle-size and aiohttp warnings remain.
