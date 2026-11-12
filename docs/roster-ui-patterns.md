# Roster UI patterns

## CWL names and plain words (audit 119)

| Thing                                           | Visible name                                            |
| ----------------------------------------------- | ------------------------------------------------------- |
| Member clan destination                         | My clan assignments                                     |
| Member without a clan assignment                | Waiting for a clan                                      |
| Staff account without a placement               | Unplaced                                                |
| Bonus page and navigation                       | Results & bonuses                                       |
| 15/30-player limit and progress labels          | Clan size                                               |
| Hide the member roster                          | Hide roster; Roster hidden.                             |
| Campaign message/reminder workspace             | Signup reminders                                        |
| Staff workflow destinations                     | Build roster; Finalize roster; Announcements            |
| CWL clan configuration                          | Hosting clans                                           |
| Existing staff CWL page eyebrow                 | CWL                                                     |
| Member page eyebrows                            | None                                                    |
| Existing account-linking help control           | Link an account                                         |
| Search that actually matches players and clans  | Find a player or clan                                   |
| Read the latest data again                      | Refresh (use Reload the page only for a browser reload) |
| Pick an item, account, clan or permission       | Select                                                  |
| Member and staff web surface                    | Dashboard                                               |
| Short account details                           | Summary                                                 |
| One Discord send in a reviewed declaration ping | Message (keep transport chunk keys unchanged)           |

Use full forms in dashboard copy: could not, cannot, will not, do not,
you are and you will. Separate instructions into sentences. Keep the owner’s
section names with `&`, Chopping Block, Ghosted, Flew the Coop and Not loyal to WU.
The FWA phrase, Main/Lazy rules, member tour and prank wording stay unchanged.
Do not use **campaign** in visible dashboard, staff-error or Discord copy. Use
CWL month, automatic messages and time zone. Internal code names, storage fields,
transport keys, docstrings and journals keep their existing names.
Discord defaults use copy version 128; saved version 127 and unversioned legacy
text remain unchanged, including legacy typos needed to recognize stored copy.

At 320 px, the existing strip may retain My clan / Build / Finalize / Announce;
accessible names use the full destination names. Other headings and navigation
use the full names. Staff counts say signups; no-weight counts add `(all pools)`
only when that global count differs from the current pool's count. API filter
keys, CSS class names and stored capacity/status fields are not renamed.

Main: `Main: play at full strength. No hero upgrades.`
Lazy: `Lazy: relaxed CWL. You can upgrade during the event.`
The FWA line remains exactly `If you’re in FWA… it’s Lazy Way or No Way!!!`.
Tour titles and narrative stay unchanged; its 13 actual cards use sequential
card ordinals and a matching total rather than repeated 5s. The original eight
decorative progress groups retain their layout and stage advances through an
explicit `progressGroup`; these are not thirteen individually numbered dots.

The later review 137, item 6 governs empty My clan assignments: without a known
empty linked-account result, offer Signup for CWL alone. Do not add a linking
helper or fetch accounts merely to satisfy the older119 label request. Existing
linking controls elsewhere share the canonical label.

## Member signup confirmation

Home and My signups share a green confirmation naming signed accounts and pools. My signups lists every saved account and uses the account cards below for changes; My clan assignments uses a compact unpublished status or the published clan list. When some accounts are signed up, remaining linked accounts appear in a separate red card below the green confirmation without account names. Zero signups keep the grey signup action. Closed signups remove mutation-navigation links, not read-only navigation. Partial published assignments retain their clan cards; hidden publications use unpublished wording.

Optional campaign guidance uses local dates and minute-updated relative time, or the muted `Clans are not ready yet. Check back soon.` line. Missing guidance never hides saved signups. The member strip reuses the staff pattern: Sign up / My signups / My clan. My CWL starts expanded and remembers collapse.

Every dashboard page uses the global color tokens in `web/cwl/src/tokens.css`.
Roster primitives and states remain in `web/cwl/src/rosterUi/primitives.css`;
the existing `--roster-*` color names are aliases for the shared `--wu-*` tokens.

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

Global colors live on `:root` in `web/cwl/src/tokens.css`, imported first by
`main.tsx`. New code uses `--wu-*`; existing roster consumers retain aliases.

| Token                                                           | Value                             | Use                                         |
| --------------------------------------------------------------- | --------------------------------- | ------------------------------------------- |
| `--wu-bg`                                                       | `#0c0c0e`                         | Page background                             |
| `--wu-surface`                                                  | `#19191d`                         | Cards, sidebar, topbar                      |
| `--wu-surface-raised`                                           | `#242429`                         | Raised panels, menus                        |
| `--wu-surface-soft`                                             | `#2d2d33`                         | Inputs, secondary buttons, pills            |
| `--wu-card`                                                     | `#303037`                         | Roster-style cards                          |
| `--wu-border`                                                   | `#494950`                         | Default border                              |
| `--wu-border-subtle`                                            | `#38383e`                         | Dividers, quiet borders                     |
| `--wu-text`                                                     | `#f5f4f0`                         | Body text                                   |
| `--wu-text-muted`                                               | `#b9bbc4`                         | Secondary text                              |
| `--wu-accent`                                                   | `#f4cd64`                         | Primary fill, gold text, selected border    |
| `--wu-accent-hover`                                             | `#ffdc7b`                         | Primary hover                               |
| `--wu-accent-ink`                                               | `#241b08`                         | Text on a gold fill                         |
| `--wu-accent-soft`                                              | `#30291a`                         | Selected or active tint                     |
| `--wu-focus`                                                    | `#f5d66e`                         | Focus ring only; never selection            |
| `--wu-success` / `--wu-success-surface` / `--wu-success-border` | `#00d659` / `#2b4b38` / `#00d659` | Success; brand green (bot `WU_GREEN`)       |
| `--wu-warning` / `--wu-warning-surface` / `--wu-warning-border` | `#efc867` / `#30291c` / `#786435` | Warning; separate from accent               |
| `--wu-danger` / `--wu-danger-surface` / `--wu-danger-border`    | `#f19999` / `#493235` / `#ff737d` | Errors, destructive actions                 |
| `--wu-info` / `--wu-info-surface` / `--wu-info-border`          | `#b9d5ff` / `#1a212b` / `#495563` | Informational notices only; 1b applies this |

Gold means action or selection only. Warning amber is a separate token. Blue is
for information only; retiring existing navy surfaces belongs to the later 1b
change. The 1a foundation preserves existing roster card edge, glow and text
colors, selection surface, strong gold, type, spacing, radius, and shadow values.

- Radius: sm 10 · md 14 · lg 20 · pill 999
- Control height: 44 / 48 (visual chips can be ~36 with a ≥44 hit area)
- Borders: 1px, subtle. Surfaces: layered dark levels.
- Color meaning:
  - green background = assigned account
  - gold = accent, primary action, active filter, selection border
  - red = destructive / error / "No weight"
  - amber = warning (full clan, outside family)
  - green pill = "Signups open"

## Type scale

The dashboard self-hosts one Latin variable **WU Inter** face at weights 400–700.
`tokens.css` loads its hashed Vite asset and a local, metric-adjusted Arial
fallback. The root stack does not use the bare Inter family name; synthetic
weights remain disabled. See `web/cwl/src/assets/fonts/README.md` for the source,
license, subset and fallback metrics.

| Token                 | Value | Role                                                           |
| --------------------- | ----- | -------------------------------------------------------------- |
| `--wu-text-xs`        | 12px  | Metadata, captions, eyebrows, nav groups, badges; minimum size |
| `--wu-text-sm`        | 14px  | Dense rows, tables, secondary lines, chips, helpers            |
| `--wu-text-md`        | 16px  | Body copy, form controls, buttons, primary row text            |
| `--wu-text-lg`        | 20px  | Card titles and h3                                             |
| `--wu-text-xl`        | 24px  | Section headings and h2; h1 at 480px and below                 |
| `--wu-text-2xl`       | 32px  | Page h1 above 480px; sign-in h1 at every width                 |
| `--wu-weight-regular` | 400   | Body and metadata                                              |
| `--wu-weight-medium`  | 600   | Labels, emphasis, buttons, eyebrows and nav labels             |
| `--wu-weight-bold`    | 700   | Headings, key numbers and names                                |

1. Map by the content's role, never by the nearest size. Below-12px metadata
   moves to the 12px floor. Dense/helper copy uses 14px; primary text uses 16px.
   Existing intermediate sizes map to the appropriate heading, row or body role.
2. Use 400, 600 and 700 for the three weight roles. Former 450/500 declarations
   become body 400 or emphasis 600; 580/650 become 600; 750/800/900 become 700.
3. Page h1 uses 32px/700, line-height 1.15 and tracking -0.02em, or 24px at
   480px and below. Sign-in h1 remains 32px. H2 uses 24px/700/1.2; h3 uses
   20px/600/1.3. Headings use balanced wrapping rather than fluid clamps.
4. Eyebrows and nav group labels use 12px/600. Keep their existing uppercase
   treatment and limit tracking to 0.08em without changing their color.
5. Paragraphs use line-height 1.55 and pretty wrapping. Inputs, selects and
   textareas use at least 16px outside the locked roster exceptions. Keep
   existing reading measures, control geometry and spacing.
6. Counts, scores, stat numbers, numeric table columns and countdowns use
   tabular numerals.
7. Keep repeated roles consistent across pages. Preserve the locked roster,
   Player card and Compare type: 16px/700 names, 15px/700 clan headings,
   14px/700 Total and 12px/400 details. The four roster size aliases reference
   root tokens only at their identical 12/14/20/24px values. Dedicated moderation,
   member activity history and Discord preview styles remain outside this batch.
   Any measured narrow-screen type exception belongs in the batch evidence;
   do not change layout to compensate for a size increase.

Semantic roles take precedence over legacy markup: `.manage-heading h2` is the
Server management view's page title, so it uses the h1 role without changing its
heading element. Home's `Your tasks` h2 is a compact card title and uses
20px/600/1.3. The MAIN/LAZY roster pool captions are 12px/600 group labels.
At 480px and below, the staff CWL workflow buttons use 12px: the intermediate
14px size still introduced a second line at 360px. The member CWL step-strip
buttons and Strikes Accounts/Leave/Settings tabs use 14px. These fitting
exceptions preserve the incumbent labels without changing padding, height,
layout or copy. The staff workflow already wraps at 320px in the baseline;
that existing behavior is not claimed as a new single-line guarantee.

## Spacing scale

Spacing uses the following root tokens. This batch changes spacing and eligible
control minimum heights only; the type scale, Inter, colors, copy and DOM order
stay unchanged.

| Token          | Value | Role                                                              |
| -------------- | ----- | ----------------------------------------------------------------- |
| `--wu-space-1` | 4px   | Tight related details and eyebrow-to-title spacing                |
| `--wu-space-2` | 8px   | Title-to-lead spacing and compact controls                        |
| `--wu-space-3` | 12px  | Related groups, dense inner rows and section-heading bottom space |
| `--wu-space-4` | 16px  | Phone gutters and card insets                                     |
| `--wu-space-5` | 24px  | Page-header separation, phone section rhythm and desktop cards    |
| `--wu-space-6` | 32px  | Desktop gutters and section rhythm                                |
| `--wu-space-7` | 48px  | Generous outer spacing                                            |

| Role                                                      | Phone (650px and below)         | Desktop                         |
| --------------------------------------------------------- | ------------------------------- | ------------------------------- |
| Main top / horizontal gutter                              | 16px / 16px                     | 24px / 32px                     |
| Main bottom reserve                                       | Existing 80px                   | Existing 72px                   |
| Eyebrow → title → lead                                    | 4px / 8px                       | 4px / 8px                       |
| Header → first content                                    | 24px                            | 24px                            |
| Separate Home sections                                    | 24px                            | 32px                            |
| Home statistics/heading and toolbar/selection/list groups | 12px                            | 12px                            |
| Standard card / panel inset                               | 16px                            | 24px                            |
| Dense related rows                                        | 12px where needed to retain fit | 12px where needed to retain fit |
| Section-heading top / bottom                              | 24px / 12px                     | 32px / 12px                     |
| Eligible interactive control minimum                      | 44px                            | 44px                            |

Home keeps its existing block flow and DOM/focus order. Sibling margins implement
its outer rhythm because adding `display` or wrappers is outside scope; existing
flex/grid groups continue using gaps. Conditional children do not add empty
wrappers or a second spacing system.

The named roster stylesheets and roster-workspace rules stay byte-equal, including
6px card gaps and zero row gaps. The global card spacing rule excludes roster
cards with a zero-specificity `:where()` filter; their existing 22px fallback
padding remains unchanged. The exclusive RosterHeader stylesheet also stays byte-equal. Its outer gap remains 2px; the summary keeps a 2px/8px gap and 5px/10px
inset, while summary content keeps its 6px inset/gap and zero margins. These locks take priority over the general scale.

The Discord sign-in CTA retains its existing padding, gap and minimum height.
Its welcome-card clamp padding also stays unchanged because that is the winning
inherited geometry controlling the CTA width. Ordinary controls use the new
spacing without increasing selector specificity. Shared defaults also retain
locked roster, Compare, Player card and ActionMenu trigger/portal recipients;
only other recipients receive the mapped spacing.

Entry 740 preserves exactly the 17 reviewed functional-geometry records: avatar
insets, trailing action reserves, roster-header widths, walkthrough aside offsets,
tour clearance, drawer width, artwork heights and brand/menu clearance. Ordinary
components in their mixed shorthands still use tokens. Visually-hidden -1px
margins preserve accessibility clipping. Each functional component and retained
2px hairline inset is enumerated in the batch's declaration ledger.

Native checkbox/radio glyphs keep their existing dimensions; measure their label
hit area instead. Inline reference links cannot gain a 44px hit area through
`min-height` without changing their display, so any such remaining controls are
reported as explicit row-9 exceptions. Apart from the sole entry-742 exception below, no display, width, paragraph
measure, font, color or wording change is used to make the spacing fit.

The narrow fit exceptions use smaller scale steps: Tasks clan-header padding and
gap at 320px, Wars card padding at 320px, and My clan assignments' clan-header
inset and gap at 360px and below. Their measured outcomes are recorded in the
batch report.
Entries 741/742 also allow a 12px inline main gutter at 320px and below for
Activity and Events only; top 16px and bottom 80px remain unchanged.

Entry 742 authorizes one non-spacing exception: at 320px and below,
`.member-status-line strong` uses `white-space: normal`. Its existing nowrap
status title already extended the baseline page to 334px; the exception permits
that specific title to wrap while its font, color and wording remain unchanged.
All other non-spacing declarations remain equal to the baseline.

Entry 743 defines the wrapping guard at the visible text-block level: no extra
line or increased text-block height. Inline phrase/code breaks may move when
the containing block keeps the same line count and height; the report preserves
those raw observations. It also distinguishes authored/fixed roster spacing
from unchanged auto-margin or JavaScript free-space results that naturally vary
with the approved outer gutter. Those formulas are not changed to force old
computed free-space numbers.

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
  - Outside family matches only `outside_family_and_hosts`, with the same count, active chip and Clear all behavior as other statuses.
  - Footer: `Reset` + `Show N accounts`. One line explaining OR within a section, AND across sections.
- **Active filter chips:** removable (`Assigned ✕`) + `Clear all`, above the list.
- **Tabs, chips and navigation items (B-6, 2026-11-11):** three patterns only; see "Dashboard choice patterns" below.
- **Status pill:** `Draft · not published` / `Published` / `Unpublished changes`, the same height as the buttons beside it.
- **Undo toast:** `Assigned 5 to W. U. Lazy.127 · Undo`; shows "Undo no longer available" when a later edit invalidates it. aria-live.

## Dashboard choice patterns (B-6, decided 2026-11-11)

Every group of choices on the dashboard uses one of three patterns. Prompt 191
introduced A and B; B-6 finished the last groups and added C.

| Pattern | Use | Component | Selected look |
|---|---|---|---|
| A. Section tabs | Switch views inside one page (Strikes, Tasks, Tickets, Moderation, Clan settings, roster views) | `SectionTabs`, or `section-tabs section-tabs--flow` on a custom rail | Gold text, gold underline |
| B. Filter chips | Filter one list (clan type, Town Hall, search kinds) | `FilterChips`, `variant="pill"` for pills | Gold outline, gold text |
| C. Navigation items | Lists of records or clans that open an item (settings record list, Family clans directory); the sidebar uses the same look | `nav-list` class (`navList.css`) | Gold edge, 3px gold left bar, gold bold text |

- No solid-gold selected state and no segmented control. Unselected navigation items keep the normal button look.
- Every tab and chip rail scrolls inside its own strip and fades the edge that hides items (`useChoiceRail`, `has-horizontal-fades`). The page never scrolls sideways at 320, 360 and 390px.
- Targets are at least 44px high.
- Groups keep `aria-pressed` buttons in a named group. Only Clan settings uses the full ARIA tab pattern with arrow keys. Do not add `role="tab"` without that keyboard behavior (see `dashboard-interaction-standard.md`).
- Later work (handoff backlog B-14): sidebar, Results and CWL step links become real `<a href>` links, and the selected tab can live in the URL.

## Layout and format rules

- Touch targets ≥44×44 (WCAG 2.5.8 AA minimum is 24px; Apple 44pt, Material 48dp).
- No horizontal page overflow at 320, 360 and 1440px.
- Horizontal rows: hidden scrollbar + edge fade + scroll-snap.
- List: render 50 + Load more. Never paginate selection. Select 15 / Select 30 replace selection with the first unlocked matching accounts in displayed order; All N appears only when N ≤ 50. Keep Clear visible when selected. Enforce the 50 cap on every selection path, counting hidden selections; quick-pick targets stay at least 44px on one mobile row.
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
- Default player sort is Weight: high to low, reset on pool changes; unknown weights sort last in stable name order. Other sort choices remain unchanged.
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
- Live range preview uses Compare's formatter: min–max, min+, up to max, Any weight; minimum and maximum inclusive (Ruggie, 2026-10-30). Same-pool shared endpoints show a non-blocking “179k fits both Clan A and Clan B.” note.
- Changed ranges show a known-weight-only impact disclosure. Over-full war sizes show a red +N over count, with no reassignment.
- Archived seasons use text values and no Save. Settings-save feedback is never labelled draft-only.
- Phone Compare rail commits selection after scroll settles and keeps arrows/taps/player swipes synchronized. League, tag and optional range live on the phone rail card; desktop headers stay unchanged.

## Weights

- Assign current/projected and Balance current/preview weight labels show the total of known effective weights, formatted with grouped `k` values (for example `4,512.5k`). Keep `N of M weighed` for partial totals and say `Total: no weights yet` when none are known. Clan cards use the same total rule. `Avg TH` remains a separate Town Hall measure; display copy does not change balancing, sort order, save payloads or permissions.

- Compact missing-weight queue: TH icon and name open Details; TH/tag/pool/source metadata stays readable at 12px. Desktop controls sit beside identity; phone controls sit below it.
- One queue-level `Enter weights as: Loot | Full` switch sits below search, defaults to Loot and controls every missing-weight input; rows have no unit toggle. Switching reinterprets unsaved text and updates each full-weight hint without changing saved weights. Reuse `parseManualWeight` and inline validation. Never save on typing or unit changes; explicit Save only, then focus the next editable row. Details keeps its own `CompactWeightField` unit control and explicit Save/clear-to-source behavior. The unit conversion and save payload are unchanged.
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

- The CWL sidebar follows the season: Seasons → Signup reminders → Build roster → Finalize roster → Announcements → Declaration check → Return reminders → Results & bonuses → Exports. Other staff destinations use flat Clans, Members, Bot and Admin groups, plus direct Staff overview and Moderation links.
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

| Location (both pages)   | Row 3                                                                            |
| ----------------------- | -------------------------------------------------------------------------------- |
| In assigned clan        | Green bold assigned clan + nonshrinking green `In clan` pill + muted · age       |
| Assigned elsewhere      | Bold assigned clan → red current clan name (No clan when clanless) + muted · age |
| Not assigned (Accounts) | Muted Not assigned → current clan (in no clan if clanless) · age                 |
| No result (Accounts)    | Assigned clan / Not assigned · location not checked yet                          |
| Checking (Compare)      | Column clan · Checking…                                                          |

One shared component renders both pages. Compare's column clan is the assigned clan; its former In this clan / Not in this clan / Checking chips are removed. Other warnings retain their own row, omitted when empty. No weight stays at the headline weight position.

Keep row 3 on one line below the menu hit area in compact cards, using the full line width. Assigned name gets priority; the suffix ellipsizes first. If the assigned name alone is too long, it ellipsizes and the arrow suffix hides. The In clan pill never shrinks; its fixed width is reserved before the name. Full text stays in title and accessible words (hours and minutes). Determine same clan by tags; fall back to names only when a tag is missing. Never show the green text or pill before a completed location read. Only the current clan name is red, not its age.

Glow top opacity: green/red 20%, neutral 8%, fading out at 44px before line 3. Upper text passes 4.5:1 at the brightest point; saturated green/red clan text and pills pass 4.5:1 at their actual lower-card position, including hover. Compare tint, tally and status all share tag-first/name-fallback matching with a completed read. The age formatter and ticking now remain unchanged.

Item 6: withdrawn rosters with placements show the amber step dot; the Build banner shares Finalize's Hidden from members wording. Background metadata enrichment includes checked_at with the location name/tag/status so already-mounted cards render completed reads. Existing season/revision/request guards remain; no backend change.

### Plain list cards (Results & bonuses, Exports; 2026-11-11, page names updated by prompt 229)

Results & bonuses (the player lists, Review and the draw lists) and the Exports preview use one card: `AccountCard` with the `account-card-plain` modifier (neutral surface, no glow; metadata and flag lines wrap). Attacks and stars use `CardTally` (number tinted by the outcome tone); the outcome is a `StatusPill` beside it.

- A card that opens a panel stretches its name button (`account-card-open`) over the whole card; the `⋯` menu repeats that action. The player list opens Details; a clan's steps open Review.
- Bonus Review opens in the shared `ActionPanel` (bottom sheet on phones, centered dialog on desktop), never inline below the list. Close, Escape, backdrop and Back go through the unsaved-edit discard confirm. Without bonus access the card button and menu item are disabled.
- Exports cards are read-only: no menu. Rows show TH, tag, CWL and hosting clan in the metadata line; Roster adds `Weight`, Signups and Results history add `Clash capture`, Saved bonus history shows the selection as a pill plus the date and reason.

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

### Build roster readability (approved 2026-10-29)

These rules supersede the older Accounts card, status-pill and single-alert descriptions above. The shared `PlayerClanStatus` uses a text-sized outline MapPin, announced as “Now in”, before the current clan on Accounts, Compare, Declaration and dialogs; the status colors, age and truncation priority remain. At desktop widths of about 900px and above, Accounts rows align Name (TH icon, name, tag and TH), Pool, Assigned clan, Now in, Weight and `⋯` into readable columns. Phones retain their existing card layout, checkbox, select-all, Details and menu behavior.

The Build header keeps its season and signup controls. One slim gold-accent status line replaces both Draft pills and the larger publication card; it states Draft, Hidden, or Published with version/date, and a permission-gated Review link where appropriate. When a published roster has unpublished changes, name the version members still see and say the changes are draft only. Directly below, an amber line shows the number of signup changes and opens review; when an affected clan is below its known 15/30 size, a separate red line below it names the worst shortage, adds `+N more` as needed and opens Compare. Missing capacity uses one line for non-archived hosting clans with assigned accounts and no 15/30 setting; the link focuses the first affected clan in Clan settings. Empty pooled clans do not count. Publication fetch/retry safeguards remain.

Roster exits with unsaved edits use an in-app ConfirmDialog that names the number of unsaved weights when weights alone are dirty. Keep editing, Escape and backdrop retain values and focus; Discard clears drafts and runs only the requested tab, season, rules/Compare pool, sidebar or capacity-link action. A save in flight shows an OK-only wait message and refuses navigation. Accounts & signups All/Main/Lazy are filters: switching them preserves selected accounts and does not ask to discard. Other dashboard native confirmations are outside this roster pattern.

The summary-chip and main-tab rows stay one line and show a soft fade only at edges with more content to scroll into view. Clan cards with no known weights say `Total: no weights yet`; other totals keep their existing format. This is frontend presentation only: saves, Undo, publication, signup review, permissions and endpoints retain their behavior.

The card's capacity-note suppression matches the current server reason string from `cwl_web/placement_status.py:17`; keep the match in sync if that server copy changes.

## Accounts back to top and empty quick selection

Only Accounts & signups on phones ≤800px has the stationary `↑ Back to top` pill. Show it after scrolling more than two viewport heights and then upward by 40px, with an 80ms debounce. Hide on downward travel or within one viewport of the top; do not reveal from small direction changes. Hide it for Details, dialogs and other panels, and unmount it on other tabs or desktop.

Use a native labelled button with a Lucide ArrowUp, at least 44px height, gold boundary/text against the dark card surface and visible keyboard focus. Place it 16px from the right and bottom plus the safe-area inset; when the selection action bar is present, use its measured height to place the pill above it. Reserve bottom space so the final account's buttons remain tappable. Explicit activation focuses Build roster and scrolls to zero smoothly, or instantly for reduced motion, without changing filters, selection, tab or URL.

Select 15/30 with no unlocked matches retains the current selection, including hidden selected accounts, and reports `Only 0 unlocked accounts match`. With any unlocked matches, the existing ordered replacement behavior remains. These controls only adjust transient selection; they do not save roster or signup data.

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

## Compare: Time zone sort

Compare can sort each clan west to east from the owner's Discord nickname. The
parser uses text after the last `|`, removes flag emoji and trims it. Explicit
UTC/GMT offsets support hours and minutes; recognized abbreviations use their
literal standard/daylight offset, without seasonal inference. CST means US
Central, IST India, AST Atlantic and BST British. EASTERN/CENTRAL/PACIFIC/MOUNTAIN
mean their US standard offsets. Unknown text groups alphabetically after known
zones; owners with no zone come last. Within a zone, owner nicknames then user IDs
keep accounts together, with weight descending inside an owner. Assignments and
other sorts do not change.

Only recognized zones get a compact card label; unknown or missing zones add no
label. The cached owner-nickname map is keyed by the roster user ID. A cold or
failed directory lookup does not delay the roster; one bounded background refresh
warms the cache and failures have a two-minute cooldown. The existing bounded
metadata refresh merges owner names without replacing assignments or drafts. Normal roster permissions
apply, and only owners present in that roster appear in the response. No signup,
assignment, nickname or Discord write is performed. Release verification records
counts of family owners with known, unknown and missing zones.

Saved member profiles supply Compare time zones before nickname parsing. Scoped
background metadata enrichment merges only owner zones/nicknames, preserving
working placements and drafts. Invalid/unavailable profiles fall back to cached
nicknames; no sort or navigation action writes a Discord nickname.

Member time zones follows the dashboard interaction standard: native labeled
controls, 44 px targets, phone cards, retained conflict drafts, row focus on
return, explicit loading/unavailable/revoked states, and no preview fetch while
Standardize is closed. The infrequent import and full change preview are labeled
disclosures; their errors remain visible. Isolated 360/1440 checks cover edit,
conflict, untick, confirmation and uncertain results with simulated transport.

## Strikes usability checks (prompt 65)

Account list controls reuse ActionPanel, RosterFilterOptions and the shared
RosterMenu clan search. Participation and Bonus Hosting clan menus use the same
searchable menu, retaining disabled and discard behavior. Every filter has an
applied chip and URL key; activity_view stays distinct from dashboard view.
Scoped browser checks cover 320, 360, 390 and 1440 widths and 26, 65, 125 and 560
accounts, keyboard focus, no overflow, minimum 44 px controls and minimum 12 px
text. Compact rows measured 90 px phone and 44.5 px desktop after visual fixes,
with a 54 px sticky toolbar; screenshots were inspected at narrow and wide widths.
The table caption remains accessible without consuming visual space and mobile
priority labels remain visible while the summary truncates. Full detail holds
the unabridged evidence and notes. Isolated fake transport never proves live
Discord or clipboard permissions on another browser.

## Declaration ping interaction

Keep a saved destination, its revisioned save action and `Ping N missing` next to
the active pool. Reuse ChannelCombobox and the shared accessible ConfirmDialog.
The initial click reads fresh arrivals; only the confirmation can enqueue delivery.
Show clan counts, unlinked names, excluded unknown locations and the destination
before Send. Put the approximate rendered message and occasional no-ping test in
labeled disclosures. Preview controls never send or open in-game links.

Preserve a channel draft on errors and ask before discarding it on pool, season or
page changes. Block local conflicting actions during short requests; after a job
is queued, navigation is safe because its real delivery receipt is durable. Show
confirmed chunk IDs and an explicit uncertain state, not a generic success toast.
Never let a status reload resend a notification. Refresh only active, visible
delivery views, with one read in flight; do not re-fetch the channel directory on
each progress poll. Permission loss clears protected controls and an open review.

Check the controls, confirmation, test review and rendered sample at 320/360/390
and wide widths with 26, 65 and 125 missing-account fixtures. Verify keyboard/focus,
44px controls, no horizontal overflow and read-only state. This is scoped product
QA, not a claim of full assistive-technology certification or live Discord delivery.

## Extra-member observations on Declaration check

Treat not-on-roster as an amber read-only observation, separate from arrival
readiness and missing-player pings. Keep ordinary rows available while a separate
member read runs. Show name, TH, account tag and assignment context in a native
disclosure; do not infer account membership from its Discord owner. Make zero,
checking, unavailable and previously checked states distinct.

The extra-member filter applies to visible Lazy clan cards, never to the pool's
ping-recipient estimate. Preserve it across pool changes; provide Clear filter for
an empty result. Keep failure counts visible even when a filter hides those cards.
Main has no extra-member checks or flag controls. Re-check only on load/source
change/manual Refresh, with cancellation and generation guards; a page's periodic
arrival refresh must not turn into extra-member polling.

QA covers 320/360/390 and desktop, slow-read rows first, empty and failed official
reads, alt identities, published/draft changes, Main exclusion, stale responses,
filtering and an unchanged pool-wide ping count. This feature has no notification
delivery to prove and no production test send.

## Members page (prompt 93, in development)

Use one directory, search, filter state, pager and ID selection set for member
roles and profiles. Selecting a page never selects hidden pages or bots. Selection
survives query, filter and page changes; hidden selections stay in the count.
Freeze the reviewed IDs before a bulk confirmation, and derive the sent count
from those exact IDs. A row opener and its checkbox are separate targets.

Reuse DiscordIdentity with the batch directory profile, FilterChips, RoleSelect,
DetailsFrame, the existing timezone editor and the nickname result/run surface.
Keep frequent controls visible; occasional history belongs in a disclosure.
New Members strings live together in src/members/strings.ts. Narrow filters use
one sideways removable-chip row; status and errors do not rely on colour.

Permission clarification (Claude 298): keep the existing member_roles grant for
both roles and profiles. There is no member_profiles grant today; this batch
adds no grant or migration and nobody gains or loses access. A viewer without
member_roles must be rejected by every server route as well as the UI.

Bulk roles extend the existing ProfileRuns storage owner, legacy parent kind and
single queued lane. A role manifest is explicitly typed; nickname confirmations,
status and Stop cannot consume role manifests. Existing profile manifests keep
their old shape. One child is materialized at a time with fresh expiry; terminal
or uncertain children never reset on restart. Stop prevents later writes; an
already accepted Discord operation is never automatically replayed. Each role
write checks fresh actor, target, bot member, roles and guild, plus current access,
hierarchy, protected-role confirmation and the exact reviewed role state. Confirmed
role changes leave a durable audit receipt in the same child's storage owner.
No real roles or nicknames have been changed in development. Final page wiring,
API failure-mode tests, recovery fixtures, mutants, full gates and layouts remain
before READY; these notes are not a completion claim.

### Members workflow refinements

Use a bounded scrolling directory with a usable minimum height, rather than
shrinking it to a single row under a tall phone toolbar. Place the selected-action
region before the directory; its sticky position must not cover a focused row.
On short screens it becomes ordinary document flow. Position each row so its
visually hidden labels cannot extend the document with blank overflow.

Keep one DetailsFrame instance when switching people. Run the shared navigation
and discard guard before changing the person; update the frame's existing URL
entry rather than stacking a new history entry for each person. Use task-specific
discard wording, preserve the directory filters/selection/scroll, and restore
focus to the opening row on Back. The previous parallel time-zone directory is
removed; its editor, conflict/retry-identity and accessible-metadata regressions
now run through the unified page.

Treat unavailable or malformed role progress as a write fence until an explicit
safe refresh succeeds. Validate optional Undo metadata before exposing an action.
If a role run completes before its first status read, refresh the directory
immediately. Undo reviews one exact person with the expected post-change role
set, so a later concurrent edit cannot be overwritten. Keep the current run state
visible in a disclosure summary even when its detailed results are collapsed.

### Compact CWL pages (121)

Build keeps its title and season on one row. Its count/status disclosure names
the current view on phones, such as **Accounts & signups**. The existing view
buttons, including **Missing weights · N**, appear when it opens. Wide layouts
keep those views directly visible; the separate **Signup & status** disclosure
opens staff signup controls, publication status and count-filter actions. At
360 and 1440, both closed summaries remain 46 pixels high. Components stay mounted,
so closing a disclosure does not discard an editor or start another read.
Signup errors, visibility warnings, notices and active editors remain visible.
Publication changes and missing clan sizes remain visible action notices.

Pool choices, Filters, sort and Refresh remain direct buttons. Filters, sort and
Refresh share a row, with at least 44-pixel touch targets. The heading and tools
scroll away with the page. Finalize and Announcements use the same title/season
row and omit the repeated CWL eyebrow.

Declaration's compact overview is followed directly by its clan list. Pings is
a closed, keyboard-operable disclosure after the list, with its last confirmed
ping in the summary. Errors, active sends and open reviews remain visible.
Checking counts say **Checking… 3 of 10 clans confirmed ready**, distinguishing
confirmed partial results from a final readiness fraction. The existing ping
settings/history read still runs; opening the disclosure does not fetch or send
a preview.

My signups has one account list: the editable saved list. The status summary
retains totals, assignment links, dates and read-failure warnings without
repeating account names. Clan-change guidance appears once and only while
changes are allowed. The closed Sign up page leaves **Signups closed** to its
heading and keeps the season name and existing destinations.

151 regression checks keep recovery actions next to visible failures, preserve
role=status on compact current status, and avoid repeating a uniform unavailable
result in every row. A distinct row result stays visible. Forced-open ping errors
have a summary action that scrolls and focuses the existing error; they do not
add a send or retry path. The checked-in four-width local layout command is
`npm run test:less-on-top-layout`; its isolated fixtures exercise 26/65/125-account
Build layouts and member/declaration failure states without production traffic.

## 122: shared CWL controls and theme

CWL write and discard decisions use the existing ConfirmDialog. The small
useConfirmDialog adapter supplies an awaited decision for existing action owners;
it does not own API calls or retries. Cancel, Escape, unmount, a changed season,
changed document/permissions or a newly locked scope resolves to Cancel. A second
opener cannot replace a decision. Each mutation retains its existing pending,
revision, authorization and uncertain-outcome rules. Browser unload protection
remains browser-owned. Native confirmations still present in App concern access
or other management pages, outside this CWL pass.

Results, Bonus, Exports and Declaration use RosterMenu for seasons; Signup
reminders joins the existing Build/Finalize/Seasons picker pattern. Existing
selection callbacks, empty choices, disabled states and URL/history ownership are
retained. CwlPageHeader supplies one compact title/season/action row and preserves
publication focus targets. Member pages reuse its title hierarchy without adding
a season selector. Results' long title may wrap inside its column on a phone.
The global phone page-head stack is explicitly overridden for this shared row.

TodoWorkspace and ClanFilters replace navy values with the roster surface,
border, text, gold, success and attention tokens. Bonus and member assignments
reuse matching tokens. Font, spacing and shadow tokens are added and used only in
touched surfaces. ClanFilters' FilterPicker remains an existing dormant export:
current Compare imports its matching helpers, not that control. No new filter was
introduced just to demonstrate its CSS. FWA and pool-change dialogs retain their
wording and ordinary GIF display; reduced-motion users get the same explanation
and controls without the animated image.

Safety review exercises actual Results reset/discard, staff add/discard, Bonus
candidate removal/discard, publishing and member withdrawal: Cancel has zero
writes, double activation confirms one write, document/permission changes cancel,
and closing during an accepted request does not replay it. The shared adapter's
tests were written first and failed before implementation. Additional integration
regressions retain navigation continuation, exact account names, request identity
and season callback behavior. Four valid no-confirm mutants in Results, staff
signup, Bonus removal and publishing are assertion-killed with source hashes
restored. An initial sandbox subprocess produced no test output and is not counted.

Checked-in local layout commands are `npm run test:less-on-top-layout` and
`npm run test:same-look-layout`. The former retains the 52-case
320/360/390/1440 and 26/65/125-account matrix. The latter captures 13 changed
pages at 360 and 1440 plus actual FWA/pool dialogs, verifies the computed shared
header row, and checks reduced-motion behavior. Before images use the exact
accepted 20b9e580 artifact; candidate images use this branch. Both phases use new
owned loopback SQLite/MemoryMongo fixtures. Settled Tasks, reminder and linked
account GET responses are explicitly synthetic. Page loading/clock differences
are not evidence of a changed domain result. No domain writes or page errors were
recorded in either screenshot phase. Narrow/wide images were visually reviewed.

Earlier diagnostic failures remain in workspace .local: the first full test run
used the repository rather than web/cwl working directory, old native-select and
native-confirm browser assertions needed migration, and the before harness used
a nonexistent assignments URL and a wrong account-card selector. The publication
recovery fixture initially enabled successful background reads before clicking
Retry; it now keeps failure pinned until the actual click. Visual review also
caught a global display:block rule defeating the first row override; computed
flex-row/overlap assertions now guard it. Assertions were retained against the
new controls rather than dropped.

No API method, body, polling policy, grant or selection permission was changed.
Semantic API-call ASTs (ignoring quote formatting) match accepted 20b9e580 for all
53 calls across nineteen reviewed runtime modules. Mocked publishing checks are
not proof of live Discord delivery. This is not a full assistive-technology audit.

This branch starts at exact accepted 121/151 commit 20b9e580, not a main merge.
Accepted predecessor 185's background filler queue is not in that source base.
Later integration must preserve that queue and stop for review on any behavior
conflict; it must not overwrite its changes. Existing 121 staff/member previews
remain untouched. Release is held for owner approval and 123 implementation has
not started.

122 completion evidence: 1,667 frontend tests across 282 files, TypeScript and
production-format Vite build pass. The final four-width suite passes all 52
scenarios; the same-look comparison passes 30 before and 30 after scenarios
(26 page states and four dialog states each). All screenshot runs record zero
non-GET requests after local login and zero page errors. Computed header display
and title/picker vertical overlap are asserted, not inferred from screenshots.
The actual two new review previews also pass a login/render/served-hash smoke.

Adversarial review checked that dynamic season/account names remain React text,
no new external URL or mention construction was added, no modal opens a write by
itself, pending/uncertain writes are not replayed, Cancel retains edits and
selection, and changed authority/document scopes abandon pending decisions.
Existing partial/unavailable location, visibility-check failure, forced-open ping
error, archived/read-only and member closed-season regressions remain in the
four-width suite. Data/storage/provider authorization remains with existing
owners; browser sample checks do not establish production delivery or freshness.

### Review 152 corrections

The first regression exercises the actual ParticipationWorkspace month-change
handler and its POST to participation/sync-settings: Cancel makes zero writes,
Confirm makes one, and a double click still makes one. The child editor supplies
its existing dirty-change contract in this isolated test; this is not live editor
or Discord evidence. Removing the confirmation produces an assertion failure.
Actual ArrivalCheck and App pool-change tests likewise retain drafts on Cancel,
clear them on Confirm, and make no writes.

All CWL headers now share a 44px title row, 20px phone/24px wide title, and a
152px phone/200px wide season field, including read-only My assignments. At 360px
all ten season fields span x193–345; at 1440px they span x1212–1412. Obsolete
page-specific header rules were removed. The accepted Build height targets remain
covered. Clean staff Signup Back closes synchronously without restoring an extra
history marker. Withdraw uses the existing danger dialog style. The danger text
token now passes 4.5:1 on the selected surface (the old token measured 4.039:1);
seven semantic text/surface pairs are checked. MessagePublish retains its dialog
change with only 10 added/four removed lines against the accepted predecessor;
formatting-only changes were reverted.

Validation: 57 focused tests, 1,680 frontend tests across 286 files, typecheck and
Vite build pass. Six genuine assertion-killed mutants cover the month guard,
both pool guards, clean Back, withdrawal danger style and contrast. The semantic
API comparison retains all 53 calls in 19 modules. The four-width suite passes
52 scenarios at 320/360/390/1440; the page/dialog comparison passes 30 before and
30 after cases at 360/1440, with zero non-GET requests and page errors. Narrow
and wide before/after headers were visually reviewed. The separately documented
Declaration Back URL/menu mismatch remains unproven and unchanged. No production
operation or task 123 implementation occurred. Release remains held; later
integration must preserve the accepted background filler queue predecessor.

## Motion (217)

- Action panels enter only: centered panel 180ms scale 0.97 + fade, side panel 200ms 16px slide, phone sheet
  240ms from the bottom edge with cubic-bezier(0.32,0.72,0,1). Close is instant. Reduced motion: 150ms fade only.
- Press feedback: scale 0.97 (rows and cards 0.99), 120ms cubic-bezier(0.23,1,0.32,1). No tap highlight.
- All :hover rules sit inside @media (hover: hover) and (pointer: fine). Moderation files are not yet gated.
- Load status lines must not change page height after first paint (Build roster target: layout shift < 0.01).

## Web guidelines (219)

- :root uses color-scheme: dark. The Sign up guide keeps color-scheme: only light.
- Page sections under the h1 start at h2. Change the tag, not the look.
- Disclosures (summary) and standalone arrow links are at least 44px high. Links inside a sentence are not.
- Confirms use useConfirmDialog, never window.confirm. beforeunload stays native.
- theme-color and the manifest use #0c0c0e.

## Top bar

- On phones the account menu is fixed width at the right edge; only the title block flexes.

## Search picker (dropdown rollout, 2026-11-11)

Long-list fields use the shared `web/cwl/src/SearchPicker.tsx` (piloted on
World clocks, PR #286). Rule: a list of about 12 or more options, or a list
that grows (channels, roles, members, countries, time zones, commands, saved
messages, records), uses SearchPicker. A short fixed list (sort, status,
priority, units) keeps the native `<select>`.

- Closed field: gold label, 48 px field with 14 px corners, the selected value
  as a card (icon, name, second line). Optional remove button (`clearable`).
- Phone (700 px or less): a full-screen sheet with the search on top, sized to
  the area above the keyboard. Wider screens: the list opens under the field
  and moves the content down.
- Selecting only calls `onChange`. Picking the value that is already selected
  does nothing (native select parity). Opening, searching and closing write
  nothing.
- Add mode: `value=""` and the handler appends (RolePicker, ignored channels,
  ignored bots, reminder roles). The field stays on its placeholder.
- Never show raw Discord IDs in rows or the closed field. Search may still
  match a pasted ID. `ChannelCombobox` keeps its forum post lookup row
  ("Look up channel or forum post ID"), which calls `onResolve`.
- Shared wrappers: `ChannelCombobox`, `RoleSelect`, `RolePicker`
  (`roleOption` builds a role row with its colour dot), `StrikeMemberSelect`.
  Tests drive pickers through `searchPickerTestUtils.ts`.

Short lists (dropdown rollout PR 2):

- Native selects take the World clocks field look from one base rule in
  `style.css`: 14 px corners, `var(--wu-bg)` field, `var(--wu-border)` edge.
  The phone's own picker and arrow stay. Size is unchanged (min-height 44 px,
  padding, font size, border width), so compact dropdowns keep their size. The
  rule has element specificity (`:where`), so any page rule wins.
- The Tasks sort pill (`.todo-sort select`) is excluded and keeps its own look.
- Field labels (a `<label>` wrapping a select, text input or textarea, or
  naming the field right after it with `for`) are gold. Checkbox and radio
  labels stay muted. Page rules that set a label colour are left as they were:
  `.clan-settings-panel label`, `.hub-toolbar label`, `.preference label`,
  `.roster-ui-input label`, the joining-instructions editor label.
- `MemberPicker` and the Compare clan picker (`.compare-clan-picker`) take the
  look only, with no behaviour or size change.

## Results and Bonus (prompt 228; the flow is superseded by prompt 229 below)

- Cards stay neutral: no background or edge tint by outcome. One small chip
  gives the outcome: green Meets rule, red Below rule, amber Not checked (no
  result captured; a bonus review reason can cover it) or amber Partial
  results (some numbers, not complete; a reason cannot cover it). Attacks and
  Stars numbers take the same tone;
  labels stay muted; the clan name is quieter than the player name.
- The rule and the tone live in one helper, `participationOutcome.ts`. Lazy: 4+
  attacks, or 3+ attacks and 8+ stars. Main: the saved minimum; with no saved
  minimum, Main shows no chip. Bonus rows use the same chip, plus only
  player-specific reasons. Clan-wide reasons show once in a notice above the
  list.
- Step bar, clan cards and blockers: superseded by prompt 229 below.
- Results has 5 outcome filter chips with counts (All · Meets rule · Below rule
  · Partial results · Not checked, `FilterChips`), a 3-option Sort and a Hosting clan short-list
  select (the search picker above 20 clans). The count line counts the
  selected pool only.
- `pool`, `clan`, `outcome`, `sort` and `step` are in the URL; Back, Forward and
  shared links restore them (the clan address names the step, see prompt 229).
- Results cards: the card body opens Details; the shared `⋯` menu holds DM +
  Details (`participationMenuItems` list). Attacks and stars come from Clash
  and are read only; Details saves staff notes only.

### Results & bonuses one page (prompt 229)

- One page, "Results & bonuses". No clan selected: overview. Clan selected: the
  five steps.
- Only one step panel is open. A done step shows one summary line with Change.
- A blocker shows once, in the open panel, beside its fix. The bar shows the
  same short reason. A disabled action gets one line naming the first blocker.
- One "Hosting clan" dropdown (`BonusClanSelect.tsx`) sits directly under the
  Main/Lazy tabs, on the overview and in the steps. "All clans" is first; each
  option reads "{name} · {state}" ("19 of 23 meet · Draft"; after a draw
  "Draw saved", "Approved" or "Sent"). One muted line under it: "Select a clan
  to open its bonus steps." for All clans, else the clan's state. Native select
  up to 20 clans, `SearchPicker` above. There is no clan-card row and no
  "Find a clan" search. Results-only staff use the same dropdown to filter the
  list. The player row below holds "Find a player" (Name or #TAG…) and Sort on
  one line down to 320 px.
- Settings and capture options open in a sheet (`ActionPanel`) from the page ⋯
  menu. Saved histories live in Exports. Staff who cannot open Exports (bonus
  access without results access) keep a "Saved bonus history" disclosure at the
  bottom of the page; it reads only when opened.
- The step bar (`BonusStepBar.tsx`) is Results → Rules & count → Draw → Approve
  → Announce, for the selected pool and clan. Done ✓, current gold, blocked red
  with one short reason. Each step is a link with the `pool`, `clan` and `step`
  keys. Phones (700 px or less) show one line, "Step 2 of 5 · Rules & count",
  with dots that expand to the full bar. It reads the light `bonus-status`
  endpoint after the list; a failure shows one muted "Status unavailable ·
  Retry" and never blocks the list.
- Blockers come from `bonusStepBlockers` in `bonusRaffle.ts`, the one source for
  the step lines, the bar reasons and every disabled action. Draw, Approve and
  Announce wait for the steps before them. The Draw preview loads by itself
  when the step opens and never writes; a response from another clan, pool or
  count is dropped.
- Selecting a clan in the dropdown, from the list or the steps, pushes an
  address that names the first step that is not done (`firstOpenStep`), so Back
  and Forward return to the same screen. An address with no clan shows the
  dropdown only.
- Each notice shows once: "Archived season" (the page notice only), "CWL month
  not set" (the Results blocker only; the month line shows a month only when
  set) and the medals line in Announce ("Give the medals in Clash. The
  announcement does not award them."). The old-results warning is one line
  with "Check Clash now" inline on the overview and in the steps.
- Phones (700 px or less): the Rules & count count field takes a full-width row
  with its label above and hint below, the two tiles share the next row, the
  minimum field and Save minimum share a row, blocker lines are text lines (the
  44px target overlaps the line), and "Bonus count and source" sits below the
  player list. No horizontal overflow at 320, 360 and 390 px.
- Infractions (2026-11-12): the player Details sheet holds an "Infractions"
  section for Lazy players (`InfractionsSection.tsx`, shared fields in
  `InfractionFields.tsx`); the steps open the same fields in an `ActionPanel`
  ("Infractions for {name}"). The ⋯ item reads "Infractions". Step cards show a
  neutral `Chip` per set flag and "Staff reason"; overview cards show none.
  Details has one footer Cancel and Save. Read only after the draw
  ("Draw saved · read only"), in archived seasons and without the manage grant.

Results & bonuses has one 44px “How bonuses work” header CircleHelp button opening the shared side ActionPanel with Close only, five read-only rule explanations and trigger-focus restoration; the season control stays unchanged (prompt234).
