# Roster UI patterns

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

- Compare readability (X3): row 1 starts with a 16px TownHallIcon, then the 15px/700 name and bold weight (a red No weight tag replaces missing weight); row 2 has TH, tag and lock in 12px muted text; row 3 has Now in, a 13px secondary clan name and 12px muted age (or No clan / Checking location…); row 4 has the location pill and wrapping range/family tags. A relevant publication note adds one muted fifth row. No Compare text is smaller than 12px. Cards retain the location tint, left edge, Details body action and 44px menu target.
- Compare card fills use the shared lighter green/red/neutral tokens and a 4px colored left edge. Only the location pill retains semibold emphasis below row 1. Card gaps are consistently 6px; the row gap inside each card is 0px.
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
- Loot-first single input with Loot / Full switch, live full-weight conversion and inline validation. Reuse `parseManualWeight`. Never save on typing or unit changes; explicit Save only, then focus the next editable row. Keep `ManualWeightFields` in Details.
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

## Player card

Shared player card (2026-10-27): Accounts & signups and Compare use `PlayerCard.css` for the 14px radius, 4px colored left edge, compact spacing and text hierarchy. Fills live in `rosterUi/tokens.css`: `--roster-card` (neutral), `--roster-card-success` (green), `--roster-card-danger` (red).

1. TownHallIcon first (16px), name (15px bold, ellipsis), bold weight right, existing 44px action menu.
2. Muted 12px `TH 18 · #TAG` and lock. Accounts retains its existing pool text. The lock appears only here.
3. Compare keeps `Now in X · 10m ago`, location chips and relevant publication note. Accounts shows the assigned clan in bold (or `Not assigned`) plus muted `· now in X`; unknown/stale location still shows `—`. Warning/note lines remain below.

Accounts keeps its 44px left checkbox, green for assigned and gold selection outline. Compare uses green for in-clan, red for elsewhere and neutral while checking. Status is also written in chips. Neither card changes selection, Details, menu permissions, location, swipe or request behavior. Text is at least 12px; measured text-fill colors, including muted text, must contrast at least 4.5:1 with their rendered backgrounds. Accounts readability continues in a later audit.
