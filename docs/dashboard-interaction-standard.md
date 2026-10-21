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

## Member journey — October 21 follow-up

External linking → Home → choose accounts → review → saved signup → published
assignment now has a scoped follow-up pass. Account lookup still combines both
existing providers; direct provider linking was researched, not enabled. See
`dashboard-review-backlog.md` for the provider requirements and the owner's
explicitly deferred review queue.

Refreshes and filters preserve signup choices. Account lists are searchable and
paged; selection counts and review include all pages. Changed links/pool ownership
invalidate stale selection consent. Season-service errors have their own retry,
closed seasons have useful read-only destinations, and published joining
instructions are visible. Changes remain subject to existing backend ownership,
closed-season, assignment, and transaction checks.

Validation: 185 frontend tests, 72 relevant backend tests, production build, and
`git diff --check`. Isolated browser checks used 25 fictional accounts at desktop,
390px and 320px: retained refresh/search/page selections, failed-save recovery,
confirmation and pool-change review, closed-season assignments, season-error retry,
missing-account linking guidance, escaped names/instructions, and published clan
links. Narrow inspected layouts had no document overflow. Cancelled navigation
and season changes used a fixture-controlled native-confirm response because the
browser automation auto-handled the native dialog; this is not a native-dialog or
screen-reader certification. Existing Vite bundle/import and aiohttp warnings
remain. No live Discord messages, actual provider links, or member signup records
were changed during testing.

## CWL return reminders — October 21 follow-up

Return reminders now use separate FWA/Main views, searchable clan rows, and one
visible selection/action toolbar. FWA supports shared start/stop dates applied to
selected clans; editing one clan uses the same editor as a batch. Main remains
manual. Existing channel, member-list maintenance, and durable result/retry flows
are reused. Signup reminders are outside this change.

Scheduling stores UTC dates and displays the viewer’s timezone. Windows cannot
exceed seven days or a saved list’s seasonal cutoff; editing an already-started
window cannot extend its original seven-day deadline. Future schedules survive
restarts and the sender rechecks the current start/stop window before delivery.
Storage compares the previous reminder settings to reject concurrent edits.
Reviewing or opening an editor never sends a message or starts a schedule.

Validation: 166 relevant backend tests, 187 frontend tests, production build, and
`git diff --check`. Isolated browser fixtures contained 25 clans and covered FWA/Main
separation, bulk selection, individual date prefill, confirmation/cancel, a queued
receipt with partial failure, retained search on detail return, and failed-refresh
blocking. Desktop 1280px and mobile 390/320px layouts were inspected; the inspected
mobile layouts had no horizontal overflow. Shared date payloads, request replay,
invalid windows, Main automation rejection, restart recovery and stale settings
were covered by automated tests. The browser’s datetime fill operation did not
populate blank native inputs; interactive confirmation used an existing schedule’s
prefilled dates. Native date-picker entry and assistive-technology behavior still
need real-device verification. No live reminders or actual schedules were changed
by the fixture. Existing Vite chunk-size/import warnings remain.

### My accounts war weights

Home account rows show the recorded FWA Stats war weight under the player tag,
using the existing compact `k` formatter. Missing or unavailable source records
show `Not Available`; weights are never inferred from Town Hall level. This uses
the existing cached provider and authenticated per-user dashboard snapshot, with
a five-second enrichment timeout so an optional weight outage cannot hide accounts.
Validation: 8 dashboard-account backend tests (including absent/source-failure
weights), 187 frontend tests, production build, and isolated 390px/1280px visual
checks with long account names, present weights, and missing weights.

### Return reminders: immediate start is the default

The routine FWA journey is now select clans → Start return reminders → choose
frequency → confirm. No dates are required. Shared and individual date overrides
remain behind Optional scheduling settings, while status and automatic stop times
remain visible. Main stays manual. Explicit Start replaces a future start and
queues the first check immediately, preserving earlier stop dates, seasonal expiry,
and an already-started seven-day deadline. Resume retains the saved cadence.

Validation: 129 focused backend tests, 187 frontend tests and production build.
Added regressions cover future-to-immediate activation, preserving an active
window’s deadline, and worker forwarding with stale-settings protection. Isolated
25-clan browser checks covered bulk start/frequency confirmation, partial receipts,
optional scheduling, Main manual controls, and 1280/390/320px layouts. No live
Discord messages or production reminder settings were changed during verification.

### Signup reminders: dates before rules

The routine schedule editor displays opening-announcement and advertised-deadline
calendar dates in the campaign timezone. It no longer exposes numeric month
relative-to-CWL controls. Existing monthly and month-end rules remain unchanged
until explicitly edited; choosing a date replaces that rule and the existing
backend converts it to recurring monthly settings on save. Advanced timing keeps
manual/custom rules available. Timezone and minimum spacing are disclosed under
Advanced reminder settings. Copy distinguishes announcements from opening/closing
website signups, which this scheduler does not control.

This applies [NN/g progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/)
and [GOV.UK date input guidance](https://design-system.service.gov.uk/components/date-input/):
show routine choices first, use labeled date controls, and defer exceptional rules.
Validation: 191 frontend tests, 16 campaign/API regression tests, production build,
and isolated browser checks at 1280/390/320px. Checks covered no dirty changes on
view, keyboard date edits, review validation and successful preview, discard
confirmation, monthly offsets across year boundaries, short months/leap years,
absolute timestamps in the campaign timezone, and collapsed advanced controls.
Native date fill via the browser tool did not fire the React change; native keyboard
entry did and was verified. No live campaigns, signup states or Discord messages
were changed. Existing bundle-size/import and aiohttp AppKey warnings remain.

### Reminder workspace hierarchy and attached actions

Signup reminders now open on Schedule. Messages, Schedule and Delivery history
share the gold underline rail; it scrolls horizontally on narrow screens rather
than wrapping into disconnected rows. Refresh and Pause/Resume are grouped inside
the status bar. Review/Save share one action group, shown only for unsaved changes.
Repeated introduction panels were removed. About this schedule, saved schedules,
delivery settings, images and Discord previews start collapsed. A requested
schedule review opens automatically; message preview content mounts only when its
section opens. Errors remain visible outside collapsed settings and initial-load
failure retains a retry action.

Use this approach for future dashboard work: routine status and controls visible,
secondary content disclosed, and each action group attached to its context. Do
not style action buttons as navigation tabs or claim unrelated screens were audited.
Validation: 191 frontend tests, production build, diff check, and isolated desktop
1280px/mobile 390px/320px browser review. Checked default disclosure state, lazy
Discord preview opening/closing, draft review auto-expansion, grouped save actions,
confirmed discard, and retained gold navigation styling. These are presentation
changes; no scheduler, saved campaign, permissions or live Discord sends changed.

### Return reminder selection and first-time setup

Select-all operates on visible clans independently of the chosen action. It names
its scope (all FWA/Main clans or matching clans), preserves hidden selections,
shows a mixed checkbox state, and provides a separate clear-selection control.
Selection controls and actions share one toolbar. Long selected-clan lists are
collapsed in the batch editor; frequency and errors remain visible.

Starting FWA reminders captures current members only when no list exists, then
starts the existing scheduler at the reviewed frequency. Existing lists are never
replaced. Main remains manual. The review explains that members already away
cannot be recovered through a new current-member capture. Snapshot checks reject
stale selections; capture refuses concurrent existing lists; partial capture/start
failure is reported rather than silently overwriting or retrying notifications.

Validation: 133 backend regressions and 191 frontend tests, production build,
diff check, and isolated browser review at 1280/390/320px. Covered missing-list
select-all, filtered selection preserving hidden selections, mixed checkbox state,
Main action separation, bulk review and partial-failure receipt, stale worker
snapshots, preservation of existing lists, and capture/start partial failure.
No live lists or Discord messages were changed by these tests. Existing bundle-size
warnings remain. This review covers return reminders, not the entire dashboard.

### Signup dates and direct saving

Opening and deadline each have one date control. Removed the duplicate advanced
rule editors from these fields; existing recurring rules remain untouched until
edited and month-end rules are described beside the resolved date. Opening has
an explicit scheduling checkbox for manual-only announcements. Individual message
timing remains available in the existing advanced reminder settings.

Save is enabled for dirty editable drafts without requiring a separate preview.
It validates through the existing preview endpoint before confirmation and PATCH;
the server still validates generation and schedule on save. Preview schedule is
optional. Validation errors are also shown in the save bar and clear on editing.
Validation: 191 frontend tests, 16 campaign/API regressions, production build,
and isolated desktop/mobile browser checks for date editing, immediate Save
availability, invalid opening/deadline order, successful validation/confirmation,
and collapsed secondary controls. No live campaigns or Discord sends were changed
for testing. Existing build and aiohttp warnings remain.

### Announcement-to-signup entry

Signup announcements and signup reminders now use one “Sign up for CWL” button
targeting https://cwl.ruggie.zone/?view=signup. The existing allowlisted OAuth
return preserves the signup destination. The link uses the dashboard's selected
active-season behavior rather than inventing a mapping between campaign month
and SQLite season IDs. It is not a permanent historical-season link.

Loaded campaigns and rendered older snapshots normalize signup buttons. Exact
legacy template paragraphs are upgraded to short instructions; custom prose and
roster messages remain unchanged. Normalization is idempotent and does not mutate
stored delivery receipts or resend past messages. Already-posted Discord messages
are not edited. Custom saved prose should still be reviewed before publishing.

The gold guide remains. Signup steps use shorter language; closed seasons show
saved-signup/assignment next steps instead of an unusable signup invitation.
Validation: 82 backend tests across signup entry, campaign integration, reminder
API and authentication; 191 frontend tests; production build; desktop/mobile
isolated signup-entry and closed-state inspection. No live Discord messages sent.
This change does not complete the remaining member/staff journey redesign.

### Member and staff signup workspace

My CWL keeps the personal signup guide; staff work lives in Manage signups.
The staff workspace reuses the existing signup APIs and account editor, groups
saved accounts by member, and offers account search, select-all matching unsigned
accounts, clear selection, and optional Discord member filtering. Display names
use the existing member directory; IDs remain usable when names are unavailable.
Unsaved form/editor work is guarded across navigation, season changes and reload.

Members see a plain-language restriction when an account has a staff placement.
The API exposes only that boolean, not unpublished clan details, and existing
server-side authorization and placement checks remain authoritative. Main and
Lazy descriptions use the owner's supplied wording. The gold walkthrough stays.

Validation: 193 frontend tests, 71 targeted backend tests, production build,
isolated staff selection/save/discard checks and member mobile layout checks.
Browser testing used fictional accounts and local SQLite fixtures; no live
signups or Discord messages were changed. Existing build/aiohttp warnings remain.
This scope does not finish the later assignment, joining and return journey.

### Notification setup wording

Renamed the personal reminder disclosure/action to Notifications / Enable
notifications and added account-selection → enable → Allow instructions. The
existing iPhone Home Screen prerequisite and blocked-permission recovery remain.
This is copy only; delivery, permissions and subscription behavior are unchanged.
Reviewed button/instruction consistency and existing responsive markup; push
regression suites and production build passed. No live notification was sent.

### Bulk actions in My signups

Select accounts reveals an inline toolbar with select-all available, clear,
move-to-Main/Lazy and withdraw. Staff-placed accounts cannot be selected. Moves
reuse the existing atomic signup transfer API and review screen, preserving
preferences and source-pool consent; accounts already in the destination stay.
Withdrawals reuse the existing authorized single-account endpoint, confirm the
named batch once, stop on the first error and report confirmed progress. This
operation is intentionally not atomic; uncertain deletions are never retried
automatically. Refresh saved signups reconciles the server state.

Checked mixed pools, excluded staff placements, successful reviewed batch moves,
selection cancellation and successful batch withdrawal using isolated fixtures;
confirmation responses in the fixture are deterministic, not native-dialog tests.
Desktop and 320px layouts inspected. 195 frontend tests and 38 signup backend
tests passed, including transfer ownership/rollback and partial withdrawal stop
coverage. Production build passed. No live member signups changed during testing.

### Signup member-name resolution

Manage signups resolves names through a season-scoped version of the existing
staff member-directory endpoint. It filters to signup owners before returning
results and does not apply the member picker's 50-result search cap. Search keeps
its existing cap. Names refresh after signup changes; unavailable names show a
clear fallback with a secondary Discord ID, and directory failures offer retry.
Validation: a 120-member fixture with 65 signup owners beyond the first 50,
member authorization and malformed season checks; 39 backend and 195 frontend
tests passed, production build passed. No live signup data changed. Members who
are absent from the Discord directory can still have unavailable names.

### Inline CWL pool editing

Existing signup edits now stay in My signups. Single and bulk actions stage an
inline source → destination label, gold border/tint, and explicit Not saved yet
text. Save changes commits the pending edits; Cancel removes only pending edits
and preserves account selection. The new-signup guide remains, but selecting a
cross-pool account no longer opens a per-account confirmation popup. Its inline
text leads to the existing review and final submit action.

Navigation/reload guards cover pending saved-signup changes. Save errors stay
with the save controls and retain unsaved edits. Existing backend source-pool,
ownership and placement validation remains authoritative. Opposite-direction
edits use one existing atomic request per destination; if the second fails,
confirmed changes are kept and remaining changes reported, with no silent retry.
No whole-batch atomicity across both destinations is claimed.

Validation: 198 frontend tests (including both directions, preserved preferences,
partial failure and no retry), 39 backend signup tests, production build;
isolated desktop/390px/320px browser checks for highlight, inline save, failed
save, and Cancel preserving bulk selection. No live signups or messages changed.

### FWA signup guidance and staff review flag

Lazy CWL includes the owner's FWA slogan. Accounts whose directory category is
FWA show a warning when choosing Main, including inline saved-signup edits and
final signup review. Main remains allowed. Manage signups displays FWA → Main
CWL for staff; this is an on-page review flag, not a Discord alert.

The existing clan provider now includes its stored category. A nullable
signup_clan_type column is added idempotently to the existing SQLite signup
store. Server-side member/staff saves capture known category data, retaining FWA
history across later clan moves. The flag applies only while the pool is Main.
Older signups use their saved origin clan tag against the directory; unavailable
historical categories cannot be reconstructed during directory outages.

Validation: 77 backend tests covering signups, roster and account loading,
including allowed FWA Main signup, legacy classification, non-FWA accounts,
clan move/outage persistence and switching to Lazy; 198 frontend tests;
production build; isolated mobile warning and slogan inspection. No live
signups or Discord messages changed for testing.

### Explicit unsaved pool-change wording

Switch notices now lead with Not saved. The signup guide names both remaining
actions (Continue, then Sign up); My signups names Save changes. The unselected
account hint says prepare a change rather than confirm a move. Success remains
reported only after the save succeeds. Copy-only change; 198 frontend tests,
production build and diff checks passed. No live signup or notification tests.

### Declaration readiness uses current signups by default

Both the page and arrival-check API now default to current signups / working
assignments. Published snapshots require explicit selection. The existing
publication-content comparison supplies an outdated warning, timestamp, and
added/removed signup counts, with a Use current signups action. Location refresh
is explicitly distinguished from updating the publication. Snapshot account names
are read-only rather than opening an editor for potentially removed accounts.
Outdated snapshots cannot display the CWL declaration ready badge. With no
publication, the current-roster fallback is explicitly explained.

Validation: 60 backend tests covering declaration/roster, including default source
with an existing publication, removed/new signups, changed pools, unchanged
snapshots, missing publication, invalid source and staff authorization; 198
frontend tests; production build; isolated desktop/mobile default, outdated
warning and return-to-current checks. Existing live signups and publications were
not modified. Readiness remains a clan-location check, not proof of declaration
inside Clash of Clans.

### Assigned-account restriction wording

Member signup hints and API errors now explain that staff have assigned the
account to a CWL clan and ask the member to contact staff to change or withdraw
its signup. Removed the internal term unassign from these member-facing errors.
Restrictions are unchanged. Validation: 41 signup backend tests, production
frontend build and diff checks passed; no live signup changes or messages.

### Return reminder connection fixes

Main return messages now include an Open Clan link built from the saved home-clan
tag, matching FWA messages. FWA recipient lookup now shares Main's current-link
resolution before sending: relinked accounts mention their current Discord user,
unlinked accounts remain listed without an old mention, and lookup failures stop
the send. Existing active-list/destination checks remain after lookup. Main stays
manual and FWA scheduling is unchanged.

Validation: 99 return service/scheduler/bulk/destination tests passed, including
encoded Main home-clan link, fresh FWA links, unlinked recipients, no ping for
players already home, lookup failure, and list closure during lookup in both
sections. Tests use fake Discord transport; no live reminder was sent.
