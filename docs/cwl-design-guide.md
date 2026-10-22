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
