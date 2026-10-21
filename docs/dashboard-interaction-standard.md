# WU dashboard interaction standard

Use this standard for new or meaningfully changed dashboard workflows. The family
clan reminder overview is the first complete application, not a claim that every
existing dashboard screen already meets these rules or is WCAG-certified.

## Evidence and design comparisons

These are comparisons with published administrative product/design-system patterns,
not claims of testing private installations of other products.

| Reference | Useful pattern | WU application |
| --- | --- | --- |
| [IBM Carbon data tables](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines) | Keep search, filters, and global actions together; use expansion for secondary detail. | Searchable family index, count filters, explicit row action, separate clan editor. |
| [Shopify Polaris patterns](https://polaris-site-prod-kit.shopify.prod.shopifyapps.com/patterns) | Resource indexes organize objects and the actions taken on them; loading should preserve context. | Overview to clan editor and back, preserving filters and focus; no duplicate editing system. |
| [Atlassian empty states](https://atlassian.design/components/empty-state/) | Explain the absence of data and what the user can do next. | Different loading, empty family, unmatched filter, and service-failure states. |
| [Carbon disclosures](https://www.carbondesignsystem.com/building-blocks/core/patterns/disclosures) | Reveal secondary interactive content when requested. | Testing, verbose history, and explanation sections start collapsed. |
| [GOV.UK validation recovery](https://design-system.service.gov.uk/patterns/validation/) | Distinguish user input errors from service/permission problems and provide recovery. | Preserve edits after failed saves; service retry does not masquerade as an empty family; revoked access clears overview data. |
| [WCAG 2.2](https://www.w3.org/TR/WCAG22/) | Keyboard operation, visible/unobscured focus, adequate targets, reflow, and status feedback. | Native controls, manual-activation settings tabs, mobile cards, visible focus, 44px control targets, and short-screen sticky-bar fallback. |

## Required interaction rules

1. **Design around frequency.** The landing view answers what exists, what is on,
   and what needs attention. Open an editor for changes. Collapse occasional tools
   and long explanations, but never hide the only indication of an error.
2. **Keep the user's place.** Preserve search/filter state when returning from a
   detail view. Restore focus to the triggering row, falling back to the overview
   heading if that row has disappeared. Avoid automatic scrolling during refresh.
3. **Use explicit actions.** Name the action and its object. Opening a row must not
   enable a feature, send a message, or save edits. Keep the existing channel picker,
   provider APIs, and editor instead of building duplicate implementations.
4. **Be honest about state.** Enabled is not healthy. Differentiate missing setup,
   disabled, awaiting verification, current monitoring, outdated checks, and failed
   or uncertain delivery. Display dates for checks and deliveries. Exclude sample
   sends from scheduled-delivery health. Never use color alone to communicate status.
5. **Separate absent data from failed loading.** Initial loading, an empty account,
   no filter matches, an unavailable service, and lost permission need distinct
   feedback. A failed refresh may retain clearly labeled old data; a 401/403 must
   clear protected overview data. Retrying a read must not retry a notification.
6. **Protect work.** Preserve unsaved input after errors, confirm discarding it, and
   block conflicting local actions while a mutation is pending. Settings use
   revisions. Notifications use durable request identities and do not automatically
   replay an uncertain delivery.
7. **Make mobile an equally complete workflow.** Use one-column labeled records
   when a comparison table no longer fits. Avoid horizontal page scrolling and
   hover-only controls. Retain all important fields and actions. Prefer 44px tap
   targets (a product standard stronger than WCAG 2.2 AA's 24px minimum, which has
   documented exceptions). Test at 390px and 320px as well as desktop.
8. **Use native semantics and predictable movement.** Use buttons for actions,
   links for destinations, details/summary for disclosures, labeled inputs, and
   semantic tables. Settings tabs use arrow/Home/End focus movement and Enter/Space
   activation. Focus must stay visible above sticky controls; disable sticky save
   bars on short viewports. Honor reduced-motion preferences. No decorative motion
   is needed to make an administrative interface feel polished.
9. **Refresh without fighting the user.** Poll only visible/active views. Prevent
   overlapping reads, ignore responses for abandoned views, and preserve filters.
   Keep a visible refresh action and last-loaded time. Do not load preview data
   while the preview section is collapsed.
10. **Reuse visual hierarchy.** One page heading, one focused task heading, a compact
    toolbar, then content. Use restrained colors and consistent spacing; amber is
    attention or selection, never the sole status signal. Avoid adding cards,
    switches, warnings, and explanatory paragraphs without a specific user need.

## Review before shipping

Run the feature's automated quality gate, then verify the actual rendered UI with
isolated data. For clan management use `./.venv/bin/python tools/check_war_reminders.py`.

- Complete search → filter → open clan → edit/save → return, using mouse and keyboard.
- Check long names, symbols, 25+ clans, no clans, no matches, disabled setup, missing
  channels, stale checks, settings changed since last check, and uncertain sends.
- Fail a read and a save; revoke permission; leave while a read is in flight.
  Confirm no stale response overwrites a newer view and no failed read changes data.
- Check narrow/short viewports, focus visibility, labels, and target sizes. Browser
  accessibility-tree checks help but do not replace testing with assistive technology.
- Verify a sample Discord rendering independently of dashboard navigation. UI tests
  do not prove live push notifications. Send live tests only to authorized destinations.
- Record scope, passed checks, existing warnings, and remaining limitations. Avoid
  claiming exhaustive coverage of the entire bot from a feature-specific review.

## Next adoption opportunities

Apply this standard as ticket, roster, announcement, and campaign workflows are
next changed. Audit their landing summaries, empty/error states, save boundaries,
return navigation, and occasional diagnostic tools before redesigning visuals.
Do not introduce an app-wide component library or bulk rewrite merely to conform
names: extract a shared component when multiple real uses need the same behavior.

## October 21 follow-up: navigation and recovery

Applied the next five audit fixes to the existing workflows:

- Dashboard page visits use indexed browser history; Back/Forward restores the
  page and season. Canceling a discard returns to the original history entry,
  preserving the draft and forward stack. Page URLs use an internal allowlist and
  navigation grants; the narrower public OAuth redirect allowlist is unchanged.
- CWL reminder confirmations use a native modal dialog, initial Cancel focus,
  Tab/Shift+Tab cycling, Escape cancellation, and focus restoration to the opener.
- Channel and role reads have independent loading, failure, and Retry controls.
  Retrying options never reloads the campaign or resubmits a notification.
- Returning from a ticket restores focus to its Read ticket button after the
  refreshed list arrives, or the Tickets heading if the item disappeared.
- Selected roles remain visible and removable by name. Raw IDs are under Advanced
  role settings. Clan “Activity” is now Settings history, with the difference
  between saved settings and reminder delivery history explained explicitly.

Validation: the full frontend suite, history cancellation/forward-stack regression
cases, relevant ticket/history/campaign backend tests, and the war-reminder gate.
An isolated browser fixture exercised retries with a dirty draft, role addition
and removal, dialog keyboard handling, canceled and accepted Back/Forward, ticket
return and disappeared-row fallback. Visual checks covered desktop, 390px and
320px layouts; the inspected pages had no horizontal document overflow. No live
Discord messages were sent. These checks cover the changed workflows, not every
screen or a complete assistive-technology audit. Staff deep links require an
existing signed-in session; OAuth still returns only to approved member pages.

## CWL workflow and authenticated dashboard comparison — October 21

Read-only inspection of ClashPerk's authenticated clan directory, clan details,
reminders, and roster creation informed these changes. Keep WU's gold selection
color and existing data owners. Adopt integrated section navigation, compact
resource lists, status before settings, and optional detail on demand. This is
not a copy of its dashboard or an implementation of capital-raid/clan-game
reminders; those require their own scheduling and delivery work.

- Clan category filters use existing stored types. Tactical, Flexible Fun, FWA,
  and CWL remain visible, additional types remain reachable, and legacy Farming
  is displayed/grouped as FWA without rewriting stored records.
- CWL roster rules, weight edits, player dialogs, participation notes/sync settings,
  and bonus selections report unsaved work to dashboard navigation. Reload and
  season/section changes protect drafts; hidden participation/weight rows retain
  drafts across pagination and filters. Rule conflicts preserve typed values.
- Announcement saves acknowledge only the saved pool. A simultaneous change to
  the other pool blocks adoption of its newer generation while preserving the
  local draft. Main/Lazy tabs support manual keyboard activation and panel labels.
- Participation uses expandable records and 20 visible accounts per page.
  Source warnings remain visible outside the disclosure. Sync configuration and
  roster image/testing tools are optional. Closed roster images are not mounted;
  announcement polling runs only in the announcement step.
- Roster search, mode, page, sort, hosting-clan selection and filters are session
  preferences, not saved drafts. Publication review/announcement steps are encoded
  in browser history. Initial roster/catalog failures provide read-only retries.
- Return reminder status is derived from the existing saved list and scheduler
  limits, never from a second storage system. Scheduled describes configuration,
  not worker health. Manual, paused, not started, no-list, and expired states are
  distinct. List expiry and the seven-day window take precedence over enabled.

Validation: 173 frontend tests; 60 affected CWL backend tests; 13 return status/
settings tests; the required war-reminder gate (149 backend and 32 focused UI
checks), and production build. Existing aiohttp AppKey/deprecation and Vite bundle
size/import warnings remain. Browser checks used isolated simulated APIs with
50 accounts and 28 clans: failed reads/saves, canceled page/section navigation,
both-pool draft isolation, keyboard tab movement, pagination draft retention,
bonus protection, category filtering, preserved roster search, publication
Back/Forward steps, and no image requests while closed. Viewports included 1280,
390 and 320 pixels with no document overflow on inspected layouts. Native confirm
outcomes were simulated in the fixture after the in-app browser could not operate
one native dialog; this is not an assistive-technology certification. No live
Discord sends, pings, clan edits, or roster mutations were used for validation.

## Dashboard icons

Use `DashboardIcon` (Lucide outline SVGs) for interface navigation and supporting
symbols. Keep one stroke weight and consistent 18px sizing, with 24px icons only
for larger feature treatments. Icons inherit text/selection color; preserve the
WU gold theme. Always pair decorative icons with visible labels and hide them
from assistive technology. Remove redundant decoration instead of adding an icon
to every label. Keep real clan badges, Town Hall artwork, and Discord message
content separate from this interface convention. Import only the required Lucide
icons; do not use an entire dynamic icon bundle.

Reference: [Lucide React](https://lucide.dev/guide/react) provides typed,
tree-shakable SVG components with configurable stroke and sizing.

The October 21 icon pass was reviewed in an isolated desktop/member-home and
staff-navigation fixture at 1280px and narrow 320/390px viewport settings. Expanded
navigation, long labels, card alignment, accessible text, and page overflow were
checked. The fixture was removed after verification. This visual pass does not
represent a new audit of backend or Discord delivery behavior.

## Everyday navigation and integrated controls

Home and Search remain directly visible. Activity groups Tasks, Wars, and Events;
My CWL follows, then authorized staff tools. Search uses the existing linked-account
endpoint and current clans; only existing editors request the family directory.
It is not a global player lookup. Events now has a recurring UTC-based game calendar, displayed in the viewer’s
timezone, plus whole-clan raid status. See `activity-calendar.md` for schedule
sources and limitations. Wars uses full-clan API scores rather than personal task
rows. Existing `/todo` links remain valid.

Use gold underline strips for sibling sections and a single segmented container
for short filter sets. Keep actual actions (Save, Retry, Send) as buttons. Narrow
activity strips scroll within their rail rather than overflowing the page; keyboard
focus makes off-screen buttons reachable. Do not apply tab roles without tab keyboard
behavior: current activity filters remain native pressed buttons in a named group.

Validation: 50-account/28-clan isolated browser samples at desktop 1280px and mobile
320/390px settings; member versus staff navigation; escaped names; player search to
filtered tasks and Back; Ctrl+K; keyboard activity activation; partial family-directory
failure, denied access with zero results, failed-load Retry, and no-match recovery.
Search keeps its query/filter/page in the signed-in app session and clears them on
identity change. Review fixed clan-tag matching, exact player-tag handoff, mobile
CSS specificity, and duplicate focus borders. Activity and search use existing GET
APIs; these checks do not assert new live Discord delivery or full-game search.

### Distinct Activity destinations

Tasks answers “What do my accounts still need to do?” Wars answers “How is my
clan’s war going?” Events answers “When does the next game event start or end?”
Do not add a sidebar destination that is merely a preset of another page's task
filters. Reuse the underlying data service while presenting a genuinely different
level of information. Unknown/private clan data must remain visible as unknown.
