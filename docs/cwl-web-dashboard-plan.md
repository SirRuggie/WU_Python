# WU CWL web dashboard plan

Updated: 2026-10-02. Status: **approved design direction; interactive mockup**.
The user likes the present direction and explicitly requires mobile-friendly
operation. Preserve this design baseline and update this document as decisions
or implementation change. Production integration remains to be built.

## Preview and scope

- Preview: [cwl.ruggie.zone](https://cwl.ruggie.zone/).
- Original task: **Plan Discord bot dashboard**
  (`01a0d384-7043-7ad0-b292-15c57d053ba8`).
- Redesign task: **Find dash.clashk.ing API**
  (`01a0fd68-fb78-7821-bf31-98a5fae6e48a`).
- 240 fictional accounts, 16 example LazyCWL clans, and an October 2026 season.
  Leagues, dates, weights, Town Halls, participation, and bonuses are illustrative.
- HTML/CSS/JavaScript prototype with browser-local saved state. No live data,
  staff authentication, shared editing, database writes, Discord delivery, or
  actual bonus awards are implemented.
- Separate from the existing Discord [CWL campaign editor](cwl-dashboard.md),
  [saved CWL rosters](lazycwl-dashboard.md), and [Server Management](manage-dashboard.md).
  Do not reuse their retention/expiry rules or replace their collections without
  an explicit migration design.

## Problem and intended workflow

Slayer's process begins with Google Form responses copied into a preparation
workbook. FWA weights are brought into the monthly sheet; staff manually fill
roster slots; final assignments are copied into a separate public roster
workbook. Participation and previous bonuses live in another spreadsheet.

The proposed process is:

1. Collect or import season signups once, with player tags as stable identity.
2. Review Discord links, missing weights, source freshness, and exceptions.
3. Set hosting clans, capacities, and placement rules for the season.
4. Preview automatic placement, then manually move, swap, or keep accounts.
5. Resolve remaining issues and review the complete draft.
6. Publish a fixed roster version and a Discord announcement referring to it.
7. Let members find all their linked accounts and assigned clans on mobile.
8. Record participation, review/confirm bonuses, and archive the season.

Google Sheets remains a possible import/export bridge. The preferred direction
is one canonical backend shared by website and bot; bidirectional Sheets sync
is not an approved requirement yet.

## Research and design decisions

The public [ClashKingDashboard source](https://github.com/ClashKingInc/ClashKingDashboard/tree/bcac613aeb36ba365d846cc1d8989bb787a5fb64)
was inspected at commit `bcac613aeb36ba365d846cc1d8989bb787a5fb64`.
Public source, rather than an authenticated ClashKing session, informed this work.
Relevant files: `app/globals.css`, `components/dashboard/sidebar.tsx`,
`app/dashboard/rosters/page.tsx`, `_components/RosterCard.tsx`,
`_components/MembersTable.tsx`, and `app/dashboard/rosters/compare/page.tsx`.

Adopted patterns: grouped navigation, neutral surfaces, red active states,
rounded roster cards, configurable member tables, mobile account cards, and
comparison columns. WU keeps its identity and specific CWL workflow. ClashKing
logos, custom font, and product code were not copied.

Supporting research:

- [Carbon data-table guidance](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines):
  consistent controls, contextual batch actions, adequate data space, and
  progressive disclosure of secondary details.
- [NN/g bulk-action guidance](https://www.nngroup.com/videos/bulk-actions-design-guidelines/):
  explicit selection scope, Select all, feedback, and Undo.

Retain these design decisions:

- ClashKing-style red by default; optional WU gold.
- System/dark/light themes and comfortable/compact table density.
- Desktop sidebar; collapsible phone navigation.
- Prioritize finding and placing accounts over large summary cards.
- Visible tags and Discord identity available in columns and details.
- Clear hidden selections when changing search/filter scope.
- Tap/button alternatives for every drag action; no hover-only controls.
- Explicit separation of draft, published version, and preview.

## Screens and prototype capabilities

| Screen | Purpose and interactions |
| --- | --- |
| Season overview | Counts, missing data, timeline, next work item. |
| Rosters | Searchable grid/list; capacity, average TH/known weight, target range; open, edit, compare. |
| Roster builder | All players, unassigned, clan groups; names/tags/Discord search; filters, sorting, optional columns, pagination/all 240 rows. |
| Compare clans | Two desktop columns; reviewed moves/swaps; phones switch sides while retaining selections. |
| Player drawer | Identity, linked accounts, manual/source weight, keep placement, move/unassign, history. |
| Publish & announcements | Readiness, partial-roster acknowledgment, saved demo snapshot, Discord preview, member search, My CWL accounts. |
| Results & bonuses | Sample participation/history, eligibility rules, staff selections, recipient preview. |
| Season history | Example archives/player timelines and recent draft activity. |
| Settings | Proposed access/connections, appearance, CSV export, demo reset. |

## Placement and review rules

- Slayer's stated starting point was **174k and above** going to an undetermined
  new hosting clan. Confirm the real clan/league mapping before implementation.
- The mockup maps 174k+ to example Unranked clans and 160k to below 174k to example
  Master II clans. Each clan's range and 15/30 capacity can be edited.
- Missing weight or no eligible capacity leaves an account unassigned.
- Default auto-placement fills unassigned, unkept accounts. Rebalancing unlocked
  accounts is a separate action. Preview changes before applying either.
- Preserve kept accounts during automatic placement. Manual moves mark placements
  as kept. Manually unassigned accounts can remain kept; release that flag before
  expecting automatic placement to assign them again.
- Manual weight overrides retain the original sample FWA weight and can restore
  it explicitly. Editing a weight never automatically moves an account.
- Capacity is a hard limit. Full destinations offer one-for-one swaps; bulk
  moves cannot overfill. Out-of-range manual placement has visible override review.
- Batch actions show selection counts and distinguish displayed rows from all
  matches. Placement/weight changes provide one-step Undo.

## Publishing, bonuses, and history

- Demo publishing saves a fixed assignment snapshot locally. Later draft edits
  leave it unchanged until explicitly republished.
- Partial publication requires acknowledgment; unassigned accounts show Awaiting
  placement. The mockup never sends Discord messages or pings.
- Member previews provide searchable rosters and linked-account assignments.
  Production identity, access, and privacy must be enforced server-side.
- Sample bonus rules: five attacks minimum, three months since a bonus, three
  slots. These are illustrative, not confirmed WU policy. Agree actual available
  bonuses, eligibility, override rules, and confirmation before implementation.
- Recommendations/previews are not confirmed awards.
- Production archives must preserve published versions, source/override weights,
  participation, confirmed bonuses, and actor/time history independently of later
  edits. Browser demo history is not a durable audit trail.

## Mobile acceptance requirements

Mobile is required for staff work and member lookup, not just summary viewing.

- Support 320px, 390px, and 430px phones, tablet widths, and desktop.
- No document-wide horizontal scrolling or clipped primary actions. Secondary
  historical tables may scroll inside their own container.
- Present builder accounts as phone cards; wrap long tags and Discord IDs.
- At least 44px effective touch targets for buttons, selectors, and player
  selection; 16px editable field text on narrow screens.
- Collapsible navigation with clear open/close state, Escape dismissal, and
  automatic closing when choosing a destination.
- Phone comparison switches sides without traversing two long rosters. Preserve
  selections across sides and expose reviewed move/swap buttons. Never require drag.
- Dialogs remain within the viewport even with all 240 rows displayed. The phone
  player drawer fills available width and scrolls internally.
- Clear selection when changing the underlying player/clan/filter scope.
- Keyboard access, visible focus, labels, readable errors, status text beyond
  color, and reduced-motion support remain required.
- Test empty searches, long lists, weight editing, full-clan swaps, publishing,
  and themes at narrow widths.
- Before production, validate actual iOS Safari and Android Chrome: on-screen
  keyboards, landscape, zoom, safe areas, and poor network recovery. Desktop
  resizing does not establish physical-device behavior.

## Proposed production architecture

Recommendations and planned work, not completed infrastructure:

- React **web**, TypeScript, Vite, and a suitable router/query layer. React Native
  is unnecessary. Choose/pin exact dependencies when implementation starts.
- Accessible reusable cards, tables, drawers, dialogs, forms, navigation, and
  feedback. The prototype is the behavior/design reference; its string-rendering
  layer is not the proposed production implementation.
- Server API coordinating website operations with bot services and canonical
  saved seasons. Agree hosting and collection contracts before implementation.
- Discord sign-in plus guild/role/staff authorization for every protected action;
  separate editing permission from member access to published data.
- Verified game-stat, linking, and FWA-weight sources. Store provenance, freshness,
  lookup failures, and manual overrides independently.
- Revision checks for concurrent staff edits, atomic capacity checks, recoverable
  drafts, and durable change history.
- Immutable published versions; idempotent queued Discord delivery with receipts.
  Browser retries must not duplicate announcements.
- Validate and deduplicate spreadsheet imports, then review before applying.
  Retain CSV export and avoid competing editable sources of truth.

## Delivery checklist

### Prototype baseline

- [x] Record the manual signup/preparation/roster/bonus workflow.
- [x] Research ClashKing and table/bulk-action patterns.
- [x] Publish the sample-data restyle and preserve rollback.
- [x] Keep placement, weight, swap, Undo, preview, and export flows.
- [x] Record this plan in the bot repository and documentation index.
- [x] Complete the additional mobile audit and record results below.

### Production work, not started

- [ ] Ruggie/Slayer phone usability check: place ten accounts, swap full clans,
  find member assignments, and review bonuses.
- [ ] Confirm clan mappings, weight source/ranges, signup sources, capacities,
  account grouping, late signups, withdrawals, and exceptions.
- [ ] Confirm permissions, member privacy, destinations, and bonus policy.
- [ ] Agree hosting/database contracts; scaffold the React application.
- [ ] Implement auth, sources, imports, and season persistence.
- [ ] Implement edits with concurrency/capacity guarantees.
- [ ] Implement published versions, member lookup, and bot delivery receipts.
- [ ] Implement participation, confirmed bonuses, and durable archives.
- [ ] Validate accessibility, real phones, failure/recovery paths, and rollback.
- [ ] Pilot one season using reviewed data before broader adoption.

## Artifacts, rebuild, and hosting

Mockup sources currently live outside the repository. These paths make them
findable but do not put them under Git version control. Move the maintained
production implementation into a versioned project when development begins.

Source directory:

```text
/home/ruggie/.codex/visualizations/2026/10/02/01a0fd68-fb78-7821-bf31-98a5fae6e48a/cwl-redesign/
```

| File | Purpose |
| --- | --- |
| `base-mockup.html` | Earlier prototype copied for the build. |
| `redesign.css`, `shell.html`, `redesign.js` | Editable theme, shell, and interaction layer. |
| `build.py` | Assembles and renders the prototype. |
| `cwl-clashking-mockup.html` | Generated inline preview. |
| `index.html` | Generated standalone website. |
| `RESEARCH-AND-HANDOFF.txt`, `DEPLOYMENT.txt` | Earlier research/deployment notes. |

Run `python3 build.py` from that directory. Absolute source and bundled-renderer
paths are recorded in the script; update them if relocating. Building does not
publish. Preserve the viewport-sized export wrapper: content-height iframe
resizing previously placed dialogs below the visible screen on long lists.

The existing transient `wu-cwl-demo-web` user service reads this export per request:

```text
/home/ruggie/.codex/visualizations/2026/09/24/01a0d384-7043-7ad0-b292-15c57d053ba8/warriors-united-full-dashboard-demo.html
```

Publish by backing up that file, atomically replacing it with built `index.html`,
then verifying the local service and public URL. No Discord bot restart is
needed. Durable production hosting/startup persistence remains separate work.

Original pre-restyle rollback copy:

```text
/home/ruggie/.codex/visualizations/2026/09/24/01a0d384-7043-7ad0-b292-15c57d053ba8/warriors-united-before-clashking-restyle-20261002-125229.html
```

Preserve the current export before restoring an older one. Page rollback does
not migrate or delete browser-local saved state.

## Verification record

Initial restyle: desktop 1440×1000, phone 390×844, and additional 320px drawer
checks. Verified placement preview/apply/Undo, manual/source weights, full-clan
swap/Undo, filter selection clearing, capacity edits, bonus preview, publication
acknowledgment, state reload, and dialogs with all 240 accounts displayed. The
public site returned the new export successfully.

Additional mobile audit completed on 2026-10-02:

- Tested browser widths 320, 390, 430, 768, and 1440px. Roster builder and
  comparison fit without page-level horizontal overflow at these widths.
- Phone comparison shows one clan at a time; left/right switches preserve
  selections. Selected accounts on both sides, reviewed and confirmed a swap,
  and used Undo successfully. Tablet/desktop show both clans together.
- Enlarged phone/tablet buttons, selectors, and player checkbox hit areas to
  44px; editable fields use 16px text. Measured visible enabled roster-builder
  controls at 390px with no controls below 44px height.
- Corrected a 320px search/filter toolbar overflow. Checked the full-width
  player drawer and scrollable auto-placement preview at 320×740; preview
  actions remain inside the viewport.
- Mobile navigation closes with Escape and updates its expanded state.
- No browser console errors were captured during this audit.
- Published the updated export. Local service returned HTTP 200 with the new
  markup/CSS. A direct public HTTP probe returned 403; the public page loaded
  successfully in the browser and its new mobile script/styles were verified.

These are browser viewport checks, not physical iOS/Android device tests.
Before production release, test Safari/Chrome on real phones, the on-screen
keyboard, touch scrolling, screen readers, and all live-data error states.

Pre-mobile-update rollback copy:

```text
/home/ruggie/.codex/visualizations/2026/09/24/01a0d384-7043-7ad0-b292-15c57d053ba8/warriors-united-before-mobile-audit-20261002-131633.html
```

## Goldenrod color update — 2026-10-02

WU goldenrod is the approved default accent, replacing the initial ClashKing red.
Use goldenrod primary actions, active navigation, selection indicators, focus
rings, and meters with warm pale-gold surfaces. Filled gold controls use dark
text; text-only accents use a deeper gold in light mode for readability.
Previously saved mockup appearances migrate to goldenrod while preserving roster
assignments and other saved work. Mobile layouts remain unchanged.


## Preview hosting restored — 2026-10-14

The public preview returned HTTP 502 because `wu-cwl-demo-web.service` was
missing. The saved October 2 export and redesign sources remained intact.
Restored the existing loopback server on port 8766 using a persistent user unit
at `/home/ruggie/.config/systemd/user/wu-cwl-demo-web.service`, enabled for
startup with `Restart=on-failure`. User lingering is enabled. This supersedes
the earlier description of the web service as transient; the existing tunnel
is still a separate transient service and was not changed.

Verified that `https://cwl.ruggie.zone/` serves bytes identical to the saved
redesign `index.html` (SHA-256
`d633eee11459cbdadeaae29835c5daab5898ed89ad639263b5e29af2ead15462`).
The preview still depends on this machine and its tunnel. Dedicated production
hosting, authentication, and shared persistence remain future work.


## Access, hosting clans, and signup direction — 2026-10-14

### Confirmed owner requirements

- The Discord server owner and Discord user ID `505227988229554179` are the
  primary owners for this server. Resolve the current server owner from Discord.
- Owners can grant and revoke additional dashboard access through an access
  management screen. No other user receives roster/staff editing access by
  default, including users with Discord administrator or staff roles.
- Enforce authorization on the server for every protected operation. Member
  self-service signup permissions are distinct from staff roster editing.

### Confirmed clan-management requirements

- Hosting clans vary by season. Allow adding a hosting clan by tag, looking up
  its identity, and including it in the season lineup.
- Allow removing clans from a lineup and archiving clans for later reuse.
- Proposed implementation: separate the reusable clan directory from each
  season's lineup; archive without deleting past roster/publication history.
  If a clan has assigned players, require explicit reassignment or unassignment
  before removal. Never silently lose players or alter a published snapshot.

### Recommended signup flow — pending user approval

The user prefers replacing Google Forms with a smooth integrated experience.
Recommend a mobile signup page reached from a Discord announcement: Discord
sign-in, select verified linked accounts, answer only required season questions,
review, and submit once. Prefill available player data; provide a linking flow
for missing accounts. Members can update or withdraw their own signup until
closure, without gaining staff editing privileges. Signup joins a season pool;
staff assigns hosting clans afterward. Keep spreadsheet import/export optional.

Build access control, season/clan storage, and member signups first, then connect
persistent roster editing and publication. The mockup does not yet implement
these requirements.


## Confirmed Lazy CWL signup experience — 2026-10-14

The supplied existing Google Form screenshots are workflow references, not
instructions to reproduce manual data entry. This decision supersedes the
previous pending recommendation for linked-account selection.

- Members never choose a hosting clan. Staff defines hosting clans and assigns
  players; member signup enters the season's Lazy CWL pool only.
- Require linked accounts and allow selecting multiple linked accounts in one
  submission. Provide Select all and individual checkboxes with a selected count.
- Populate Discord identity from authenticated identity and verified links.
  Populate each selected player's tag, in-game name, Town Hall, and current clan
  from available game data. Do not ask members to type those fields manually.
- Current clan is source information, not the assigned CWL hosting clan. Preserve
  signup-time clan information separately from refreshed current-clan data.
- Missing linked accounts need a linking action and refresh; failed game-data
  lookups need a visible retry state rather than silently blank identity fields.
- A single review and submit action registers all selected accounts. Deduplicate
  by server, season, signup pool, and player tag; repeated submissions must not
  create duplicate entries. Check linked-account ownership server-side.
- Show registered accounts and allow permitted signup changes before closure.
  Clearly distinguish withdrawing a signup from merely filtering account lists.
- Keep Lazy CWL clearly labeled and distinct from Main Clan CWL.

Confirmed by the user: the per-account Yes/No preference is "Would you prefer
Crystal I or lower for this account?" Present it for each selected account with
an "Apply to all selected accounts" option. This is a placement preference,
not a guaranteed league assignment or a hosting-clan selection. Staff retains
control of final placement. This resolves the old form's inconsistent wording
about being below Crystal I versus including Crystal I itself.
The old repeated 'Do you have another account?' sections are replaced entirely
by multiple-account selection. This is a saved requirement, not yet implemented
in the hosted mockup or production application.


## Implementation decisions — 2026-10-14

- A member may register different accounts for Main and Lazy CWL in the same
  season. A single player tag cannot have active registrations in both pools.
  Enforce this across pools atomically on the server, not just in the browser.
- Lazy CWL eligibility requires the account to currently belong to an approved
  family clan. Check authoritative current-clan data again at submission.
  Unknown/unavailable data must not be treated as eligible.
- Approved family clans are distinct from season hosting clans. Joining the
  hosting lineup does not implicitly make a clan eligible for family signup.
- Begin with an isolated development application and durable development data;
  preserve the existing bot and public sample-data mockup during implementation.


## Family directory source confirmed — 2026-10-14

The existing bot MongoDB clan directory is authoritative for family membership.
Do not require owners to maintain another approved-family-clan list on the web.
Read the `clans` alias through the bot's configured namespace routing (default
`settings.clan_data`). Family categories are FWA, Tactical, Flexible Fun, and
legacy Competitive. CWL/CWL Hosting categories represent hosting destinations,
not automatic eligibility. The web app exposes the family list read-only with
source status and fails closed for Lazy signup if that source is unavailable.
This supersedes the separate manual family-approval setup described earlier.
Season hosting lineups remain independently editable. No bot MongoDB records
are modified by the web foundation.


## Public preview transition — 2026-10-14

With user authorization, https://cwl.ruggie.zone/ now serves the real OAuth web
foundation instead of the static mockup. Original mockup files are preserved.
See [development and deployment notes](cwl-web-development.md) for service,
rollback, data isolation, and verification details. Public fixture login is off;
full member login remains to be verified by completing Discord authorization.


## Linked-account verification policy

User confirmed that a provider-reported link to the authenticated Discord user
is sufficient for signup. Do not require the provider's extra verification flag.
This supersedes earlier verified-only language. Both pools accept linked accounts
regardless of that flag; family eligibility, ownership association, signup closure,
and cross-pool uniqueness remain enforced server-side.


## Signup completion UX

A successful signup must visibly complete the task, not leave members on the
same selected-account form with only a toast. Show the saved accounts, pool and
season, explain that staff will assign hosting clans and the member may close
the page, and provide Add more accounts and View my signups actions. Clear the
submitted draft. Saving success must remain distinguishable from a subsequent
refresh failure, so members are not told a successful registration failed.


## Family membership is a staff notation — 2026-10-14

User superseded the family-clan eligibility restriction: linked accounts may
register for Main or Lazy CWL regardless of their current clan. Staff signup
pools show "Not in an approved family clan" for signup-time clans outside the
bot directory. Directory outages are shown as unknown and do not block signup.
Existing saved accounts receive the same annotation. Ownership, season closure,
and one pool per account per season remain enforced.

The Lazy question now follows the supplied form: "Do you want to participate in
a league lower than Crystal 1 with this account?" The helper explains C1's
eight-star goal, fewer medals, and suitability for rushed accounts. The legacy
boolean API field is retained for compatibility; existing answers are preserved.


## Signup discovery and confirmed pool moves — 2026-10-14

Registered accounts must be directly accessible near the top of the member
page. Make choosing Main or Lazy an explicit, prominent first step. Members
may move their own linked account between pools in either direction while
signups are open. Selecting an account in the opposite pool prompts for
confirmation; the review identifies the move and submission saves it. Canceling
leaves the existing signup intact. Bulk selection must not silently consent to
moves. The backend validates the expected source pool, ownership and season
state, then updates atomically so one account never occupies both pools. Stale
confirmations fail without changing registrations.


## Staff weights and placement implementation — 2026-10-14

The original weight workflow was confirmed in task “Plan Discord bot dashboard”:
Slayer's preparation workbook imported individual weights from FWA Stats. The
mockup generated illustrative weights; neither it nor the bot contains a real
player-weight lookup adapter. `utils/war_weight.py` stores Town Hall reference
ranges; `/fwa weight` converts manually supplied storage values to total weight.
Do not infer an account's actual weight from its Town Hall.

FWA Stats Clans and Data HTML pages redirect to login, but its public JSON
feeds remain accessible. Verified `https://www.fwastats.com/Weights.json` has
player `tag`, raw total `weight`, `townhall`, and `lastModified` (UTC). No scaling
is needed. Four and Twenty (`#8CV0GPPR`) had 49 of 50 members matching the global
feed; all 49 weights matched its `/Clan/8CV0GPPR/Members.json` feed exactly.
The supplied SimpleWeight sheet links to a clan-level summary via
`http://tiny.cc/FwaWeightSummary`; that summary is not the player-weight feed.
The live adapter fetches the public global feed with timeout, size validation
and a 15-minute cache; it retains only requested account weights in season
records. Source last-modified and fetch times remain separate. Missing players
remain missing, not inferred from Town Hall. Source refresh failures preserve
prior values and manual overrides, while marking source unavailable. Staff can
explicitly restore the source value by clearing an override.

Staff hosting assignment is separate from member signup pool. Staff may place
any signup in any season hosting clan, including Main signups in a Lazy host.
This override stays in the staff workspace and does not add member controls or
announcements. Capacity still applies. Auto-placement uses configured pool,
weight ranges and capacity; Lazy Yes/No matches the hosting rule for leagues
lower than Crystal 1. No real clan thresholds are inferred from the mockup.
Preview first and apply only against unchanged roster state. Missing weights
or configured matching destinations remain unassigned. Keep manual placements
and unassignments from automatic changes.


## Active directory destinations and bulk placement — 2026-10-14

Every active hosting-directory clan is immediately available to staff for
manual roster assignments; adding it a second time to a season lineup is no
longer required. Archived hosts cannot receive new assignments, while existing
assignments remain visible for staff to move. Season-specific rules remain
configurable independently and are not invented automatically.

Staff may select multiple accounts and assign/unassign the batch atomically.
Validate capacity for the entire batch, excluding selected accounts already at
the destination; failures change none. Manual assignments keep placements.
Filters and season changes clear selection; sorting retains it. Support numeric
Town Hall and effective-weight ascending/descending sorts, with missing values
last and deterministic ties. Unconfigured manual destinations allow up to 50
roster accounts; explicitly configured capacity limits remain enforced.


## Published rosters and member assignments — 2026-10-14

Implemented staff Publish roster preview and explicit publication. Each publish
saves an immutable numbered snapshot of account identity, signup pool, hosting
clan identity, weight provenance/overrides, and joining instructions. Partial
rosters require explicit acknowledgement; empty rosters cannot be published.
Draft changes remain private until another publication. Publishing checks the
reviewed revision, advances it to prevent competing staff overwrites, records
an audit event, and handles exact retries without duplicating a version.

My assignments is directly available to members. Its authenticated endpoint
returns only the signed-in user's accounts from the latest published snapshot,
with hosting clan links, instructions, version/time, and Awaiting placement
states. It exposes neither other users' accounts nor staff weight/actor data.
Withdrawals and later roster edits do not rewrite published snapshots.
Archived seasons remain readable but cannot be published again.

Database migration is additive. Private pre-migration SQLite backup:
`.local/cwl-web-data/before-publication.sqlite`. No real roster was published
as part of deployment. Discord announcement delivery remains future work.
Validation: 46 backend and 13 frontend tests passed; isolated browser fixture
confirmed staff publication followed by member assignment/instruction display,
including a 390px mobile layout. Existing aiohttp test warnings remain.


## Immediate member placements and Discord announcements — 2026-10-14

User superseded publication-gated member visibility: My assignments now reads
current saved signup/placement rows for the authenticated user only, immediately
after staff assignment. Placements are labeled provisional when unpublished or
changed since the official version. Publishing still preserves immutable history;
withdrawals no longer appear in the current member view, but remain in snapshots.
No staff weights or other members' accounts are exposed.

Publish roster includes separate per-season Main and Lazy Discord channel
selectors, validated against the Warriors United guild text/announcement channels.
Staff explicitly save destinations and send previews; publication never sends.
Announcements use the published pool counts and dashboard link, without pings or
private player lists. Each version/pool/channel has a durable delivery receipt.
Exact duplicate sends return the saved receipt; concurrent sends reserve once.
Definitive rejections can be retried explicitly, while uncertain or in-progress
attempts block blind resend. A stranded uncertain delivery requires operator
review before further action; there is no automatic resend or reconciliation UI.

Dashboard environment now includes the existing bot DISCORD_TOKEN and
CWL_WEB_PUBLIC_URL privately. The bot account's readable environment was used
with explicit user authorization; no credential values were printed. Read-only
live Discord lookup succeeded. No real Discord messages were sent during rollout.
Backup: `.local/cwl-web-data/before-announcements.sqlite`.
Validation: 52 backend and 16 frontend tests pass; isolated browser fake-transport
flow verified channel save, explicit send receipt, and duplicate-send disabled UI.
Discord request fields checked against the official Message Resource:
https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx


## Clan comparison, atomic swaps, and placement Undo — 2026-10-14

Roster builder now compares two active hosting clans side by side, with current
occupancy, average known Town Hall/weight, and numeric TH/weight sorting. Staff
select one account per clan, review both moves, and swap atomically, including
when both clans are at capacity. Cross-pool moves remain staff-only and preserve
signup pool. Manual swap placements are kept. Mobile A/B switches retain both
selections; changing clans, season, or roster revision clears stale selections.

One-step Undo is server-backed for single placement/keep changes, bulk assignment,
automatic placement, and swaps. It belongs to the acting staff member and the
exact resulting roster revision. Later roster edits or publication invalidate it.
Undo restores only assigned clan and keep status, preserving weight provenance,
manual weights, and immutable publication snapshots. Final destination capacities
and active clans are checked transactionally; Undo is consumed once, without redo.

Validation: 58 CWL backend tests and 18 frontend tests passed. Browser fixture
verified a swap between two full 15-account clans and Undo restoration, plus
390px mobile side switching with both selections retained. No live placements
were changed for testing. Pre-migration private database backup:
`.local/cwl-web-data/before-swap-undo.sqlite`.


## Searchable channels and Manage integration boundary — 2026-10-14

Discord destinations now use searchable comboboxes supporting partial name/ID,
click selection, arrow keys, Enter, Escape, and scrolling active results. Results
are capped at 30 with a narrow-search hint. Removed the separate joining
instructions input from publication and its member display. Legacy snapshot
instructions are retained for compatibility and are not silently erased; staff
instructions belong in the roster announcement.

Research confirmed `/manage` → CWL → Publish Final Roster is distinct from
CWL Return Pings. Its `_publish` handler in extensions/commands/cwl_dashboard.py
calls extensions/tasks/cwl_reminder.py `send_campaign_message` with message key
`roster`, cycle YYYY-MM, and Main/Lazy audiences. utils/cwl_campaign.py loads
saved template body, artwork, role IDs, channel and roster/guide buttons from
routed bot_config (normally settings.bot_config). Native delivery claims and
receipts are in that campaign and cwl_pending_reminders. Return-ping lists in
lazy_cwl_lists are not assignment publications.

The web SQLite announcement sender is NOT integrated with Manage. Shared channel
IDs alone do not share receipts or prevent duplicate sends between both systems.
A future bridge must use a bot-owned worker and the native ledger, then retire
the web direct send path; no live campaign settings/messages were changed here.
Required bridge details: explicit season-to-campaign month mapping (signup month
may precede CWL month), version-aware native occurrence identity and uncertain
send handling, a stable My assignments link surviving OAuth, preservation of
native artwork/roles/guide buttons, and deliberate authorization mapping between
web owner-granted editors and Manage administrators. These were researched,
not implemented in this UI update.

Validation: 20 frontend tests and production build passed. Browser fixture
verified partial channel-name search and Enter selection without sending.

## Participation tracking implementation scope — 2026-10-14

Next after shared Manage publishing: staff manually records seasonal CWL attacks,
stars, and notes against published roster accounts. Unrecorded values remain
blank, distinct from zero. Saved rows retain the original publication/account/
hosting-clan identity, even if the account withdraws or a later roster changes.
Staff can search/filter results; archived seasons remain readable but not editable.
Edits require current per-account revisions and record actor/time in the audit.
Participation edits do not change placements or native Manage campaign state.

This first slice does not import live war data or determine/award bonuses. The
mockup's example thresholds and cooldowns remain unconfirmed policy.

## Automatic participation collection scope — 2026-10-14

Automatic results collect CWL league-group and war observations through the
existing Clash API credentials. Staff selects the exact CWL month independently
of season display labels, then enables periodic syncing or requests a refresh.
Only published hosting-clan/account context is tracked. Match league month,
select the correct war side, deduplicate wars, and count player attack stars
rather than clan win bonuses. Retain collected war evidence for later outages.

Source observations and staff corrections remain separate. Previously entered
results are retained as manual overrides; staff can explicitly restore synced
values. Notes-only edits must not freeze changing source counts. Partial,
pending, unavailable, and stale evidence must be visible rather than reported
as complete results or unexplained zeroes. Archived seasons are read-only and
excluded from background collection. No Discord sends or bonus awards occur.

## Bonus review and history scope — 2026-10-14

Build staff-only bonus planning over published participation accounts, with
per-clan capacities, draft recipients, explicit preview/confirmation, and durable
history. Confirmation records the staff decision in this dashboard; it does not
award medals in Clash of Clans or send a Discord announcement. Missing earlier
spreadsheet history must be described as no recorded selection, not never awarded.

Rules remain unset until staff configures them; the mockup's sample attack count,
slot count, and cooldown are not defaults. Manual selections remain reviewable
with explicit reasons where eligibility or evidence is uncertain. Confirmed
snapshots retain clan/player identity, reviewed results, policy, actor and time;
corrections void a record with a reason without deleting history. Archived seasons
remain read-only. Separate compact Review, History, and Rules views avoid long
stacked pages on phones.
