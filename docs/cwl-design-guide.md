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
