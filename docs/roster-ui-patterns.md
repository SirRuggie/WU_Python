# Roster UI patterns

## Member signup confirmation

Home and My clan assignments share a green confirmation naming signed accounts and pools. When some accounts are signed up, remaining linked accounts appear in a separate red card below the green confirmation without account names. Zero signups keep the grey signup action. Closed signups remove mutation-navigation links, not read-only navigation. Partial published assignments retain their clan cards; hidden publications use unpublished wording.

Optional campaign guidance uses local dates and minute-updated relative time, or a muted taking-longer line. Missing guidance never hides saved signups. The member strip reuses the staff pattern: Sign up / My signups / My clan. My CWL starts expanded and remembers collapse.

The roster page's UI system. Source of truth for tokens and states: `web/cwl/src/rosterUi/primitives.css`. Scope: roster page only (other dashboard pages adopt these later, by decision, not by drift).

## Visual direction

Ruggie's reference screenshots (2026-10-27):

- Pill buttons with a Lucide icon + label (`+ Add players`, `✏ Edit`, round `⋯`)
- A `● Open` status pill
- A thin rounded progress bar (`0/50 signed up`)
- Outlined tag chips
- Tall rounded inputs with icons and helper text
- A sticky `Cancel | Save` footer
- A custom dropdown with large rows, icons, and a tinted selected row with a check

The goal was to replace the old square buttons and native OS pickers ("early 2000s"). Accent color is **gold** (no orange).

## Tokens

- Radius: sm 10 · md 14 · lg 20 · pill 999
- Control height: 44 / 48 (visual chips can be ~36 with a ≥44 hit area)
- Borders: 1px, subtle. Surfaces: layered dark levels.
- Color meaning:
  - green background = assigned account
  - gold = accent, primary action, active filter, selection border
  - red = destructive / error / "No weight"
  - amber = warning (full clan, outside family)
  - green pill = "Signups open"

## Shape rule

- **Pill (999)** ONLY for single-line, short elements: buttons, status pills, stat chips, filter/tag chips.
- **Rounded rectangle (md ~14px)** for anything with 2+ lines or a progress bar: clan capacity cards, account cards, panels. A pill shape on multi-line content squeezes the text and bar into the curved ends.

## Interactive states (chips, cards, buttons — one set of rules everywhere)

| State                    | Treatment                                                                                                |
| ------------------------ | -------------------------------------------------------------------------------------------------------- |
| Default                  | neutral 1px border                                                                                       |
| Hover                    | subtle border lightening only; no outline, no size change                                                |
| Active filter / selected | gold border + gold tint background + gold text                                                           |
| Keyboard focus           | `:focus-visible` only (never plain `:focus`), a single white ring; base border transparent while focused |
| Disabled                 | dimmed + reason text nearby                                                                              |

- Never stack two rings (border + offset outline). That was the "doubled highlight" bug.
- Focus must never look the same as active.
- Destructive buttons: red border/fill, never gold.

## Components

- **Button:** variants are primary (gold fill), secondary (dark fill, subtle border), danger (red), icon-only circle (`⋯`). Lucide icon + label.
- **Menu/Select:** React Aria. Large rows, optional icon, selected = tint + check. Opens as a bottom sheet on mobile. No native `<select>` on the roster page.
- **ActionPanel:**
  - Mobile: bottom sheet. Desktop: centered dialog.
  - Header with title + Close; initial focus on Close (never a footer or destructive button).
  - Sticky footer above the safe-area inset. One close control (no Close + Cancel duplicates).
  - Focus trap, focus returned to the trigger, reduced motion. Back closes the panel without clearing the selection.
- **Selection bar:**
  - Sticky at the bottom when ≥1 account is selected: `N selected` chip, info chips (`X hidden by filters`, `Y not shown yet`, `Max 50 per action`), ✕, then Assign / Balance / Signup.
  - Two rows below 400px; floating bottom-center on desktop. The page gets a measured bottom spacer so the bar never covers content.
- **Stat chips:** one horizontally scrolling row (`125 signed · 111 unplaced · Auto-place · 3 no weight`). Tapping one sets a filter.
- **Clan capacity cards:**
  - Mobile 78vw (next card peeks in); desktop 240–360px; equal height; scroll-snap; edge fade; no visible scrollbar.
  - Full name (wraps, never truncated) + `5 / 15` right-aligned.
  - `Total 698k` at the same size/weight as the count; "4 of 5 weighed" small and muted, only when incomplete.
  - Thin capacity bar pinned to the bottom (green with room, amber full, red over).
- **Account card:** shared Player card below; left checkbox target remains 44px.
- **Filter panel:**
  - Sections (Status, Weight, Town Hall, Assigned clan) with per-option counts.
  - Footer: `Reset` + `Show N accounts`. One line explaining OR within a section, AND across sections.
- **Active filter chips:** removable (`Assigned ✕`) + `Clear all`, above the list.
- **Tabs:** section tabs = gold-tinted pill; pool tabs (All / Main / Lazy) = underline. One indicator each.
- **Status pill:** `Draft · not published` / `Published` / `Unpublished changes`, the same height as the buttons beside it.
- **Undo toast:** `Assigned 5 to W. U. Lazy.127 · Undo`; shows "Undo no longer available" when a later edit invalidates it. aria-live.

## Layout and format rules

- Touch targets ≥44×44 (WCAG 2.5.8 AA minimum is 24px; Apple 44pt, Material 48dp).
- No horizontal page overflow at 320, 360 and 1440px.
- Horizontal rows: hidden scrollbar + edge fade + scroll-snap.
- List: render 50 + Load more. Never paginate selection.
- Numbers: `172k`, `174.5k`. Clan card totals use grouping (`Total 2,579k`). Full values only in Details.
- No instructional paragraphs to explain a flow. If a flow needs instructions, redesign the flow.
- Labels: Assign / Unassign, Assigned clan, Pool (Main/Lazy), "Not in assigned clan".

## Research sources and what they informed

- [Eleken – Bulk actions UX](https://www.eleken.co/blog-posts/bulk-actions-ux): sticky bottom bulk-action bar on mobile, explicit selection scope ("Select all N matching"), confirm only irreversible actions and use Undo for reversible ones, ~44px targets.
- [AllAccessible – WCAG 2.5.8 target size](https://allaccessible.org/blog/wcag-258-target-size-minimum-implementation-guide): 24px AA minimum, 44px AAA; Apple 44pt, Material 48dp → our 44/48 control heights.
- [Baymard – Filter UI best practices](https://baymard.com/blog/ecommerce-filter-ui): filters in a sheet on mobile, always-visible removable active-filter chips, per-option counts, a "Show N results" apply button, Clear all + per-section reset, sticky filter trigger.
- [SaaS UI – Bulk action patterns](https://www.saasui.design/blog/saas-bulk-actions-ux-patterns) and [UX Movement – Better bulk actions](https://uxmovement.substack.com/p/a-better-ux-approach-to-bulk-actions): bulk-action bar placement and selection feedback.
- Patterns referenced from well-known apps: Gmail/Google Photos (tap toggles selection in selection mode; "select all matching"), Linear (floating bottom-center bulk bar on desktop), Trello-style board (deferred board view).

## Compare clans

- Clan header uses the clan capacity card style (no stat chips).
- Card colors: green = in this clan, red = not in this clan (an exception to "green = assigned", at staff request).
- Tags are outlined with a dark fill and never color-only.
- Card body opens Details; the shared `⋯` menu holds DM + Details.
- All `⋯` action menus (roster and Compare): a React Aria popover, at most one open at a time, closing on an outside tap, Escape, choosing an item, focus leaving it, or a tab/pool/season change.
- Desktop columns keep a **visible horizontal scrollbar** (exception to "hidden scrollbar", for mouse users). Navigation shows only on overflow.
- Phones use a swipeable clan-card row.
- The unpublished-changes banner is amber, compact and not dismissible while pending; it names the published version/time, says placement changes are draft only, and offers permission-gated Finalize navigation. Signup changes are never labelled draft.

- Compare cards use the Player card v2 rules below: 40px TownHallIcon, 16px bold name/weight, 5px rounded left edge. Shared one-line clan status replaces location status chips. Range/family warnings appear on a separate chip line only when applicable; a publication note adds one line. Card gap stays 6px and internal row gap stays 0.
- Clan headings/counts use 15px/700 primary text, Total uses 14px/700, and supporting details use 12px/400 muted text. Tally numbers use green/red/neutral/amber with muted labels. Gold identifies only the selected rail border, never header text.

## Clan settings

- Overview rows reuse the roster clan capacity card style, grouped by pool; Needs a pool appears in both tabs.
- Tap a row to edit in ActionPanel; Close gets initial focus and dirty/stale protections remain. Explicit Save is the only write boundary.
- Weight inputs use a k suffix, digits and one decimal point, up to 0.001k precision. Zero is an inline error; blank means no limit.
- Live range preview uses Compare's formatter: min–max, min+, under max, Any weight; min inclusive, max exclusive.
- Changed ranges show a known-weight-only impact disclosure. Over-full war sizes show a red +N over count, with no reassignment.
- Archived seasons use text values and no Save. Settings-save feedback is never labelled draft-only.
- Phone Compare rail commits selection after scroll settles and keeps arrows/taps/player swipes synchronized. League, tag and optional range live on the phone rail card; desktop headers stay unchanged.

## Weights

- Compact missing-weight queue: TH icon and name open Details; TH/tag/pool/source metadata stays readable at 12px. Desktop controls sit beside identity; phone controls sit below it.
- Loot-first single input with Loot / Full switch, live full-weight conversion and inline validation. Reuse `parseManualWeight`. Never save on typing or unit changes; explicit Save only, then focus the next editable row. Details now shares `CompactWeightField` with its own explicit Save and clear-to-source behavior.
- Render 50 rows and Load more. Search covers all missing accounts; keep unsaved drafts even when rows are filtered out, and retain the app's leave guard.
- Clan-weight-managed accounts have no manual input. Share the `clan_weights`-permission-gated link in queue and Details, using the app's normal guarded navigation. Otherwise show the staff-access guidance.
- Header: Needs weight count, primitive Refresh button with Lucide icon, full-width search, and one muted note about preserving placements/manual weights.

## Finalize roster

- Page order: status + one Refresh draft, changes, Before you publish chips,
  joining instructions/acknowledgement/Publish, collapsed full preview, Hide roster.
- Chips use 44px targets, informational missing-weight/over-capacity counts;
  route to weights mode, unassigned accounts or Compare without renaming modes.
- Joining instructions: labelled textarea, hint, counter at 1,800 and 2,000 limit;
  dirty edits guarded; only confirmed Publish saves. Preview reuses the member
  card and preserves whitespace. Refresh preserves unsaved text.
- Hide roster: bottom danger area only for publishers with an active publication;
  existing ConfirmDialog, Cancel focus, red confirmation, revision/version guard.
- Review styles are scoped to Finalize; announcement editors retain their styles.
  Change list displays four entries then explicit expansion. Archived publishing
  stays disabled. Short dates share the publication banner formatter.

## CWL flow navigation and season controls

- The CWL sidebar follows the season: Seasons → Signup reminders → Build roster → Finalize roster → Announcements → Declaration readiness check → Return reminders → Results. Other sections are unchanged.
- Use the compact `1 Build · 2 Finalize · 3 Announce` strip with 44px targets, gold for the active step, an amber unpublished-changes indicator, and a check for a current publication. Keep existing routes and independent publish/send permissions.
- Show the next-step cue at the end of Build, after a successful publication, and after a confirmed announcement delivery (not a queued send). Sidebar entry resets Build to Accounts & signups; in-visit tab choices remain remembered.
- Seasons and the roster signup controls share one signup-visibility action. Re-read on opening, confirm explicitly, and preserve partial success without automatic retries. An open hidden season uses an amber warning and Fix; Fix only makes that season visible when signups remain open.
- Create-season confirmation has no estimated clan count. First season says it starts with no hosting clans; otherwise it says it inherits hosting clans and settings from the previous season. The success message uses the server's actual copied count and states that signups start empty.
- Add hosting clan lives in Clan settings: searchable non-host family clans or a read-only tag lookup, followed by explicit Confirm through the existing add endpoint. Archive uses a red confirmation, explains its global effect, and preserves existing assignments. Settings-only staff receive no partial roster access; hosting controls also require Build roster access and retain existing backend mutation authorization.

## Player card

Player card v2 (2026-10-28), superseding the earlier shared-card dimensions above. Accounts stays green when assigned / neutral when unassigned; Compare stays green in clan / red elsewhere / neutral before a result.

- Compact: phones ≤700px and every Compare card. TownHallIcon 40px; name and weight 16px/700 on row 1; metadata 13px muted on row 2; location row 3 uses the full available width below the name. Compare chips/notes and Accounts warnings/notes stay. Target about 76px; wrapping tags and notes add height.
- Wide Accounts (>700px): 56px icon centered left; 18px bold name; metadata/location below; 22px bold weight centered right. Keep the 44px checkbox and 44px menu target. Emoji source and size=64 unchanged by Ruggie's choice; fallback is TH text.
- Surface: existing base fill tokens, plus `--roster-card-glow-neutral/success/danger` top-to-bottom internal gradient. Rounded 5px left edge uses `--roster-card-edge-*`; no external glow. Gold selection/focus remains. Card-local text tokens meet 4.5:1 including hover: upper text at the brightest gradient, clan text where line 3 sits below the glow.

| Location (both pages) | Row 3 |
| --- | --- |
| In assigned clan | Green bold assigned clan + nonshrinking green `In clan` pill + muted · age |
| Assigned elsewhere | Bold assigned clan → red current clan name (No clan when clanless) + muted · age |
| Not assigned (Accounts) | Muted Not assigned → current clan (in no clan if clanless) · age |
| No result (Accounts) | Assigned clan / Not assigned · location not checked yet |
| Checking (Compare) | Column clan · Checking… |

One shared component renders both pages. Compare's column clan is the assigned clan; its former In this clan / Not in this clan / Checking chips are removed. Other warnings retain their own row, omitted when empty. No weight stays at the headline weight position.

Keep row 3 on one line below the menu hit area in compact cards, using the full line width. Assigned name gets priority; the suffix ellipsizes first. If the assigned name alone is too long, it ellipsizes and the arrow suffix hides. The In clan pill never shrinks; its fixed width is reserved before the name. Full text stays in title and accessible words (hours and minutes). Determine same clan by tags; fall back to names only when a tag is missing. Never show the green text or pill before a completed location read. Only the current clan name is red, not its age.

Glow top opacity: green/red 20%, neutral 8%, fading out at 44px before line 3. Upper text passes 4.5:1 at the brightest point; saturated green/red clan text and pills pass 4.5:1 at their actual lower-card position, including hover. Compare tint, tally and status all share tag-first/name-fallback matching with a completed read. The age formatter and ticking now remain unchanged.

Item 6: withdrawn rosters with placements show the amber step dot; the Build banner shares Finalize's Hidden from members wording. Background metadata enrichment includes checked_at with the location name/tag/status so already-mounted cards render completed reads. Existing season/revision/request guards remain; no backend change.

## Signup-change review

A single header alert below the summary chips opens a side panel on desktop or full-screen sheet on phones. Amber is the default; red means a previous hosting clan is now below its known war size. Keep loading silent, Retry visible on read failure, short local dates, and the published-version caveat only for an active publication. Mark all requires confirmation with names; sequential review failures retain remaining rows and report partial progress. Reviews never modify placements or signup records.

### Player card — inline icon refinement (2026-10-28)

Supersedes the v2 40/56px icon column: TownHallIcon sits inside line 1 before the name, 22px compact / 26px wide, centered within the existing 20/23px name row. Same source and size=64, same TH text fallback. Metadata and clan status start at the left content edge in both views. Preserve one-line priority: assigned clan first, age disappears before the current-clan suffix; never wrap. Realistic layout worst cases use **15-character maximum player and clan names** and 8–9-character player tags; ellipsis remains a safety net. Layout tests and fixtures live in `web/cwl/tests/`, run with `npm run test:layout` and the documented Playwright runtime.

The summary clan row initially shows only occupied clans. A small per-pool reveal exposes empty clans for the current visit; an empty pool says No clans have players yet. This is a presentation filter only, not a hosting or assignment rule.

Signup-change review fix: Fill spot prepends the affected clan to the saved Compare
set (deduplicated, existing order retained, maximum 10; drop the last when full).
A missing clan tag leaves the preference unchanged. Dirty/busy guards run before
navigation or storage changes. The red alert leads with the below-war-size clan
or clan count. Row actions share the 44px secondary-button style. The inline TH
image may extend beyond the name line box; only the name text clips/ellipsizes.

## Announcements

- Main CWL and Lazy CWL use two compact pool cards. Show destination and named roles; use IDs only when lookups fail, with Retry. Preview opens the Discord preview dialog; Edit opens ActionPanel with Close initially focused.
- The editor contains channel, message (4,000 characters), roster link/Change link and Save message. Test sending is under “Send test · no pings” and needs a Cancel-first confirmation. Empty links prefill only on editing; saving is explicit. Delivery-locked templates stay locked.
- One primary Review and send includes ready pools only and lists their destinations/roles before queueing. Keep per-pool results separate. A lone ready pool can show Send/Retry; failed/stale only may retry. Publishing and sending remain separate actions.
- Status text: Not announced yet; Queued · waiting for the bot; Sending…; Sent <short local date>; Failed · <reason>; Check Discord first: it may have posted. Resending is blocked.; Message settings changed since it was queued · review and retry. Older sent versions explain that the roster link shows the new version and announcements are not resent.
- Publication status reuses Finalize's version/date and hidden-publication wording. One Refresh status control; no sender-ready badge. Three text levels: 15px bold, 13–14px regular, 12px muted. Check text-fill as well as color; links must stay legible on dark cards.
- Images keep their existing select/preview/download/test behavior. This batch does not add real image posting.


## Details panel

- Desktop (≥768px): nonmodal right-side panel; phone: full-screen sheet. Keep the opener list mounted. Previous/Next use its current order and filters; disable at the ends and hide when no list exists.
- Use the existing route with encoded `?account=`. Opening pushes one entry, switching replaces it, direct links get a list baseline, and shared actionPanelHistory handles Back. Close restores opener focus. Dirty weight text uses ConfirmDialog with the player's name; clean navigation does not prompt.
- Order: header with TH/name, PlayerCardMeta and Discord/DM; At a glance; Placement; Weight; collapsed Source & history; Signup; Danger; signup date. Use 15px bold / 13–14px regular / 12px muted text. Shared PlayerClanStatus supplies the location pill, mismatch and last-check age.
- Save each section separately. Placement/lock changes are explicit instant actions with revision-checked Undo. Unassign and signup changes retain confirmation. CompactWeightField defaults to Loot; weight requires Save, and blank clears to source. Keep unsaved text through background refreshes. Never force a location check on open.
- View-only reasons distinguish archived, Declaration and missing roster access. Hide editing sections rather than disabling a form. Signup-only permission exposes Signup/Remove only. Clan-managed weight links remain permission-gated.
- Register the lightweight shared Details request host eagerly in staff CWL views. Keep panel UI and roster CSS lazy to preserve the base/primitive cascade. Retain the latest open request while the chunk loads; mount one panel once loaded. Re-run `test:layout` when changing that boundary.

Direct-link Details uses the hosting page’s refresh, busy, open and dirty callbacks. Preserve account and panel history during same-page access refreshes; clear them on season/page changes. Finalize and Add signup use the shared confirmed pool switch.

## Declaration readiness check

- Collapsed clan sections are green Ready or red Not ready, with in-clan count, war size and stale-confirmation text. Phones allow one open group; desktop allows several. Keep late players visible even when an overfilled clan is ready.
- Compare and Declaration share the location transport/scheduler and compact player-card pieces. Declaration's variant has inline TH + a name button, DM only on red, TH/tag metadata, and the shared one-line clan status. No weight or menu. Before the first location result the card is red; old results retain their color and age. Outside family never applies to a clanless player.
- Ready requires at least the configured 15/30 players in the assigned clan, checked within five minutes. Unknown war size links to Clan settings and cannot be ready. Unassigned players have an Awaiting placement section.
- Name opens published-snapshot Details, view-only, with Previous/Next following the open clan order. Removed players show the published identity/placement plus “No longer signed up · removed after version N”. No write callbacks are permitted.
- Copy mentions is an explicit clipboard-only action on an open not-ready clan. List unlinked names and offer selectable text on clipboard failure. Never send automatically.
- Preserve labels, 44px actions, shared card surfaces, ≥12px text and ≥4.5:1 contrast. Current 360px first-header offset is 402px including the app header and fixture banner; the requested ~250px target is still open for review.

## Roster image posting

Announcements keeps image posting in its existing disclosure. Main and Lazy each show the saved image channel, concise delivery status and applicable Post / Resume / Retry failed / Update action. Per-clan history and previews are collapsed. Reuse ChannelCombobox, Button, ActionPanel and ConfirmDialog; confirmation lists destinations and clans. Progress is live text, not color alone.

Every run is sequential and explicitly confirmed, with one shared synchronous busy guard. Close stops future requests after the current request finishes. Known rate limits wait then continue; uncertain delivery never retries automatically. New-post uncertainty has a duplicate warning; uncertain edits retry the same message with a separate confirmation. Test all has a temporary channel, confirmation and progress/error feedback inside its panel, and never changes saved channels or posted status.

Uncertain image deliveries appear in the pool status as “N needs checking.” Recovery controls name the current publication version; edit confirmations name that version and explicitly promise the same message. An uncertain drop for a clan that has returned becomes an update. Same-version retries reuse frozen metadata; newer-version retries freeze new metadata from the current publication.

For removed clans, an uncertain update offers “Mark as no longer hosting · version N” with a same-message confirmation. An uncertain new post instead asks staff to check Discord and offers “Mark as checked”; its confirmation explains that Discord is not changed. Only “Post again anyway” carries explicit duplicate consent to the server. Checked rows are no longer counted as needing checking; their historical receipts remain available to the audit trail.

## Member tour / spotlight

`memberTour/model.ts` owns numbered steps, exact copy, artwork and browser preferences. Add a step there and a matching `data-tour-target` on the existing UI; practice targets belong only in `Practice.tsx`. Never import API mutation helpers into the tour. A transparent modal overlays the measured target so a tap advances without invoking the underlying action. The sidebar remains inert to real navigation while touring.

`MemberTour.tsx` owns dialog focus, restoring the starting location, menu coordination and target geometry. Phone navigation space is measured against the bottom card; cleanup restores its original inline height. `tour.css` scopes all visuals and reduced-motion behavior. Art lives in `public/assets/tour/` because the backend already serves `/assets`; keep the source manifest and 80KB-per-image budget. Test the entire sequence with zero requests and verify phone targets are not covered, in addition to preference and focus tests.

Crop art above alpha 60 and size by height, with aspect-aware text padding; wide art uses a separate top-edge layout. `placement.ts` tries both sides then below/above; never clamp a right-hand position through the target. The layout runner includes every tour step at 360×800, 360×640, 960, 1024, 1280 and 1440 widths, checking real rendered art size, overlap, minimum text size and zero writes. Session invitation state survives reloads in sessionStorage; only automatic skips count toward the localStorage cap.

## Member signup polish (prompt 10)

Member navigation uses unique labelled icons; staff icon changes are limited to the CWL group. Member page pills are unnumbered; the signup wizard alone uses steps 1–3, with one large gold active card and compact inactive captions. Official Fan Kit Villager assets 52545/52538/52543 appear only on the current step, using alpha-cropped 340px WebP files. One local-time season line replaces member-only Draft and repeated season labels; staff pages retain their statuses.

Pool cards remain full keyboard/touch buttons. Review Change actions preserve eligible selections; switching to Main lists FWA/otherwise ineligible accounts removed from the unsaved selection. No automatic submit. Help is a footer menu row; profile/mobile avatar open a React Aria account menu with a separated Sign out action. The real-page tour retains its non-GET guard and whole-block targets.
