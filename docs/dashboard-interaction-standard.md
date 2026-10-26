# WU dashboard interaction standard

Use this standard for new or meaningfully changed dashboard workflows. The family
clan reminder overview is the first complete application, not a claim that every
existing dashboard screen already meets these rules or is WCAG-certified.

For CWL layout decisions and the October 22 comparative review, also follow
[the living CWL design guide](cwl-design-guide.md). It records proposed patterns
separately from deployed behavior.

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

### New signups and visible CWL choice

Sign up now lists only linked accounts without a signup in the selected season.
Existing signup changes and withdrawals stay in My signups; removed the duplicate
show-signed-up/transfer path and its unused selection helpers. Refresh drops draft
selections that are no longer linked or have become signed up. The all-signed-up
state points directly to My signups.

Account selection retains the walkthrough and now reuses Main/Lazy tabs with the
existing gold underline, plus an explicit current-CWL label. Switching with an
unsaved selection retains the existing discard confirmation. Saved signups are
not affected by changing this choice.

Validation: 191 frontend tests and production build passed. Isolated desktop and
390px mobile checks covered unsigned-only lists, visible current pool, switching,
cancelled switching preserving selection, My signups access, and the all-signed-up
empty state. No live signups or Discord messages were changed. Existing build
chunk-size advisory remains.

### Return reminder capture-to-start review

Preserve selected clans after a bulk action, so capturing a list does not force
staff to select the same clans again. After capture, the next action becomes
Start return reminders for FWA or Send now for Main. Results remain visible until
Done; failed clans still require review. Existing lists are preserved, capture
must happen before members leave, and FWA start requires no date. Empty start
and expiry fields are omitted; unavailable actions explain missing/existing lists.
Main remains manual; optional future scheduling stays in its disclosure.

Validation: 106 backend return-service, batch, scheduling, status and destination
tests, including a new multi-clan date-free start/replay regression; 191 frontend
tests and production build passed. Reviewed stale-list checks, receipt replay,
partial capture failure, original stop limits, and Main automation rejection.
Fresh desktop/mobile visual checks were attempted with isolated fixtures, but the
in-app browser failed to attach twice. No live lists or Discord sends were used.

### Three-part member signup walkthrough

The large signup guide is now one connected, three-part navigation panel. Each
stage keeps its title visible; the active stage has the existing gold color and
expanded instructions. Other stages show the chosen CWL, account count, or the
explicit not-saved status. Previous-stage navigation preserves drafts; switching
pools still asks before discarding selections. Review is unavailable without
selected accounts or while account data is unavailable. All stage controls are
disabled during saving. Existing signup and server validation remain unchanged.

A dedicated SignupWalkthrough component owns presentation, while App retains
signup state and navigation. Removed obsolete progress-list CSS, retaining the
closed-signups guide. Checked isolated desktop, 390px and 320px layouts, unavailable
future stages, review navigation, returning to CWL choice with selections intact,
and cancelled pool changes. Native buttons, aria-current, keyboard focus outlines,
and stacked mobile stages retain readable titles. 191 frontend tests and the
production build passed; the existing bundle-size advisory remains. No live
signup or Discord message was created.

### Staff-reviewed CWL bonus raffles

Bonus winners uses integrated Main/Lazy tabs and a four-stage workflow: review
results, draw, approve, announce. Each pool has an independent minimum attack
count. Every qualifying account receives one ticket, including multiple accounts
owned by the same member. Fewer eligible accounts than slots means all qualify;
unused slots remain visible. Routine setup and progress stay visible. Qualifying
account details, correction controls and saved history use disclosures.

The default candidate list is **current season signups and working assignments**,
not an old published roster plus all historical participation records. The page
labels this source, shows the last results check and excluded historical count,
and offers a direct Clash refresh. Sync now uses current assignments (plus
retained historical records for history), works without a publication, checks
for signup/assignment changes during fetch, and accepts up to 100 hosting clans
with existing three-request concurrency and bounded war-fetch timeout. Unknown,
incomplete or identity-mismatched results block draws. Historical results are
preserved; the Results page now explains its wider historical scope.

Bonus allowance now defaults to a calculation using the saved season league,
war size and final wins. Missing evidence and special events retain an explicitly
labeled staff-confirmed count. See `cwl-bonus-allowance.md` for sources and scope. Attack totals use the actual observed round count
when known; they do not assume every season has seven rounds.

Draws and their candidate snapshots are durable. Approval checks current results,
roster identity and other confirmed selections. Cancellation is available only
before approval, requires a reason, retains the original winners, and invalidates
old preview requests. Announcement sends require approval and an explicit channel
review. The existing channel picker and Discord preview are reused. Long messages
split with per-part receipts. Explicit rejection supports a staff-triggered retry
of unsent parts only; uncertain/interrupted delivery never retries automatically.
No medals are awarded by the dashboard. The old slash command now opens this
workflow instead of running a second weighted, nonpersistent lottery.

Storage: new additive bonus_raffle_* tables in the existing SQLite database,
owned by utils/cwl_bonus_raffle_store.py. Existing bonus confirmations and routes
remain intact, and approval records winners in existing confirmation history.
Shared random selection/rendering lives in utils; Discord REST transport moved
to extensions with compatibility imports for the existing announcement routes.
No existing signup, publication, results or confirmation data is deleted.

Checks: backend auth/CSRF, archived/cross-season access, current-vs-published
candidate source, no-publication sync/draw, unknown results, stale previews,
changed results at approval, unique equal-weight tickets, concurrent draws and
sends, replay, cancellation, explicit rejection, partial sends, uncertain delivery,
Unicode length/mention escaping, existing participation/bonus/announcement tests,
frontend tests, production build and war-reminder gate. Isolated desktop, 390px
and 320px browser checks covered rules, candidate review, draw, approval, channel
keyboard selection, preview, mocked send receipts and narrow-width overflow.
No live signup data or Discord messages were changed for tests. This is not a
claim of live notification delivery or a complete assistive-technology audit.

### Current results and roster-source audit

Results & participation now defaults to current season signups and working
assignments. Main/Lazy use the shared integrated tabs. One source/status panel
shows the CWL month, last check, account count, and refresh actions. Attack/star
totals remain visible; corrections, sync settings, and read-only saved history
are disclosed separately. History is fetched only while expanded. Record editing
and history have separate UI components. Current exports and the retained legacy
bonus API use the same current-account boundary. Explicit history exports retain
saved records. The sync worker queries only current accounts, leaving historical
records readable without expanding the active query list.

Edits carry an account identity token (owner, tag, pool, assignment), alongside
record revision and observed source timestamp. Changed assignments reject stale
writes even without republishing. Old manual totals are not relabeled as current;
staff can refresh Clash and explicitly replace corrections with results for the
current assignment. Notes remain and the prior record is retained in the audit.
Source totals now persist an additive nullable roster_token column in
participation_source_results, migrated by Store. Old source values without a token
are usable only against a matching saved identity; a fresh sync is required to
reset corrections. A failed fetch after reassignment cannot reuse the former
assignment's cached totals. No existing participation or publication is deleted.

Roster-source audit: declaration readiness already defaults to current accounts
and labels explicitly requested outdated publications. Member assignments remain
published-only, joined to current signups and owners, and now also require the
same Main/Lazy pool. Official roster announcements, roster images, Manage's roster
send, and explicit published exports intentionally retain versioned published
snapshots. They are not substituted for current results or raffle candidates.
Bonus confirmation and draw history remain historical records. No live reminders
or announcements were sent in this review.

Validation covers removed signups without republishing across current results,
legacy bonuses and exports; no-publication edits; pool/assignment races; old source
rejection; explicit reconciliation with notes and audit retained; member published
pool isolation; historical accounts excluded from sync queries; existing auth,
CSRF, archive, source-failure, raffle, publication, image and Manage regressions.
Isolated browser checks covered Main/Lazy filtering, collapsed corrections/history,
manual save, desktop and 390px/320px reflow with no horizontal page overflow.
Frontend regression tests, production build and war-reminder validation run before
deployment. This is not a guarantee against every future bug or proof of live
Discord delivery. Existing frontend bundle-size advisory remains.


### Automatic CWL bonus allowance — October 21

The base + wins breakdown stays visible; the optional staff-confirmed count is a
collapsed disclosure. Preview, saved draw and history distinguish calculated versus
staff-entered counts. Missing final evidence blocks automatic draws; changes to
calculation evidence invalidate previews and block approval without rerolling.
Manual drafts use navigation/discard protection. Existing gold Main/Lazy tabs and
manual announcement review remain unchanged.

Checks: 607 CWL/weights/durability backend regressions (one opt-in real Mongo drill
excluded from that run), 203 frontend tests, production build, and required war
reminder gate passed. Focused additional cases cover five-round groups, zero wins,
malformed scores, cached final results, league promotion, current-month capture,
and automatic/manual snapshots. Isolated browser tests at desktop 1280px, 390px
and 320px verified automatic review, override clearing the preview, saving and
approving a fictional draw, and no horizontal overflow. Announcement remained a
separate disabled action until channel review; no live messages or real winners
were created. Existing Vite chunk-size and aiohttp warnings remain. This is scoped
feature testing, not a complete assistive-technology audit.

## Dashboard Access follow-up

Access opens on the staff list, with member/role editing opened explicitly.
Permission areas use integrated underline selectors; only one group is expanded.
CWL and Clan management remain separate, without Main/Lazy or clan-scope controls.
Save/cancel actions stay with their form; removal has a visible confirmation;
verbose history is collapsed. Failed saves preserve the draft and revision
conflicts require an explicit reload. Navigation warns before discarding edits.

Validation used isolated sample data at 320px, 390px and 1280px, including editing
and saving a role grant, removal confirmation, success feedback and history.
No horizontal page overflow was observed. Native labels, fieldsets and buttons
remain keyboard-operable; this is not a full assistive-technology certification.
Backend review covered owner-only access administration, action isolation,
role revocation, stale revisions, failed writes, queued sends and partial Discord
availability. See dashboard-access.md for storage and migration details.

## Dashboard issue visibility

Owner-only issue history uses the existing Settings navigation. Search and refresh
stay together, technical detail is collapsed, loading/errors/empty matches are
separate, and stale responses are ignored after leaving. Checked isolated sample
layouts at 320, 390 and 1280 pixels, including visible keyboard focus and no horizontal
overflow. See `dashboard-issues.md` for diagnostic scope and deliberate limitations.

## Monthly Clan Games points

Tasks now shows earned points without a family goal. Existing account selection,
clan grouping, refresh controls and mobile rows are retained. Event month/source/
check time stay visible in the integrated schedule block; missing scores never
become zero. Isolated samples reviewed at 320/390/1280px, including long names and
unknown scores; no page overflow. See `clan-games-tasks.md` for source and limits.

## October 22: withdrawing an old CWL publication

A production report matched the October 15 test publication exactly. Member
assignments read the published snapshot, not the working roster, but there was no
withdrawal control. The publication now has a nullable `withdrawn_at` field.
Withdrawal marks every active version for that season, preserves accounts and
history, audits the action, and bumps the roster revision in the existing
Mongo-backed Store transaction. Publication versions continue increasing after
withdrawal. Existing publications are not automatically hidden by schema migration.

Staff with CWL publish permission can use **Hide published assignments** in the
member-visibility panel. It checks the reviewed revision and version, requires
CSRF, and explains that existing Discord posts are not removed. Publication
lookups for member assignments, announcements, images, exports, and staff
comparisons exclude withdrawn versions. Working placements remain intact.
Member assignments show the publication date and refresh on visible-page polling
and return to the tab. Already loaded old clients need a page refresh.

Validation: 331 CWL backend tests and 213 frontend tests passed; production build
passed. Regression coverage includes two publications, withdrawal without
falling back to the older version, preserved working placements, restart,
republishing as the next version, ownership/CSRF, malformed and stale requests,
duplicate submission, and blocked announcement sends (mock transport only).
The 390px isolated UI showed the visibility explanation and labeled hide control
without horizontal overflow. Browser automation stalled at the native confirmation
dialog, so full visual confirmation at wide width and the browser click-through
could not be completed; API withdrawal behavior is covered by regression tests.
Existing sent Discord messages and already-dispatched deliveries are not recalled.

## October 22: manual CWL loot and full-weight entry

Account dialogs, the inline weight editor, and the missing-weight queue share
Loot / Full weight inputs. Loot is first and uses five storages; both fields
use actual amounts, not thousands. Saving sends only the full integer weight to
the existing authorized, revision-checked, durable override endpoint. No stored
weights or clan-weight data are migrated. Blank input retains the existing
restore-source behavior; invalid input remains editable and cannot be saved.

Validated 218 frontend tests, 32 roster/weight backend regressions, and production
build. Tests cover both conversions, commas, field switching, exact preservation
of existing weights, blank restoration, invalid amounts, and bounds. Isolated
browser checks exercised save/reopen, reverse conversion, keyboard clearing,
source restoration, and missing-weight queue save. Dialog layouts checked at
320px, 390px and 1280px; labels, decimal keyboard hint, and no horizontal overflow
verified. No production player values were edited during validation.

## October 22: Lazy hosting-clan selectors

Lazy account placement, bulk assignment, and the shared account editor now offer
only active clans classified as Lazy CWL hosts. Main selectors retain their
existing behavior. An existing out-of-group placement is preserved and represented
by a disabled current-placement option; changing a weight cannot silently move it.
The placement explanation no longer advertises cross-group choices for Lazy.

Validated 221 frontend tests and production build. Added rendered-selector tests
for Main/unclassified/archived exclusions, preserved existing placements, unchanged
Main behavior, and full-clan disabling. Isolated browser checked the actual manual
placement options at desktop and 390px: only the sample Lazy host was selectable.
This changes destination presentation, not dashboard permissions or stored rosters.

## October 22: compact roster records and placement-change alerts

The staff change panel filters durable audit events by the assignment immediately
before a member withdrawal or pool change, before applying the 100-event limit.
Unassigned changes remain in history. New events snapshot the hosting clan name;
older events resolve the retained clan record and fall back to the tag. Review
receipts and existing staff authorization remain unchanged. No audit is deleted.

Placement-change alerts use a red background/border, warning symbol and explicit
heading. Roster records are neutral, with gold selection. Names are plain text;
placement and an aria-expanded Details control share an action row. Details holds
editing, Discord contact and weight provenance. Repeated readiness copy is removed,
but placement blockers remain visible. Targets remain at least 44px.

Validation: 92 backend tests passed, one opt-in Mongo drill skipped; 221 frontend
tests and production build passed. Tests include assignment removal, unassigned
changes, 105 irrelevant events not masking an older alert, clan rename preserving
the captured name, review/CSRF/season permissions and duplicate review. Isolated
browser checks covered 320px, 390px and 1280px without horizontal overflow, neutral
and gold cards, red alerts, Details/editor open/close, manual placement save, and
alert review. The sample narrow card was 246px high with 44px action buttons.
No live messages or production player mutations were used for verification.

## October 22: Manage Signups member groups

Saved signups use compact member groups with one Message link per member, TH icons,
player identity, pool, exact working assignment and a labeled Manage action.
Search includes member and clan names; a placement filter complements Main/Lazy.
Inline management supports one account or selected accounts within a member group.
Selection is gold, controls retain 44px targets, and the editor explicitly explains
placement clearing before a pool switch or removal. Removal requires the labeled
Confirm removal action. Placement editing remains in Roster. Filters and paging
stay fixed while an edit is selected, and saves refresh rows without unmounting
all groups. Missing Discord names retain a visible retry and player-based fallback.

The staff-only signup response includes assignment name/tag and revision; member
responses never include those unpublished assignments. The new staff change endpoint
uses the existing Store transaction/audit and cwl_signups permission, rechecks the
revision and member ownership after upstream checks, validates current FWA eligibility
for Main transfers, and writes a whole selected batch atomically. Removed signups and
pool changes preserve saved weights and publication snapshots. No schema migration.

Validation: 73 backend tests passed, one opt-in Mongo drill skipped, 223 frontend
tests passed and production build passed. Coverage includes member privacy, CSRF,
wrong member, malformed/duplicate input, FWA batch rejection, concurrent revision
change during upstream lookup, stale retry, removal and audit preservation. Browser
checks used isolated data at 320/390/1280px, with long names, missing Discord names,
multi-selection, pool switch save, explicit single removal, and inline controls.
No horizontal overflow; Manage targets measured 44px. No live messages or production
player changes were used. Existing build-size and aiohttp warnings remain.

## October 22: Clan Weights URL

Clan Weights now generates /clan-weights. Legacy ?view=weight-trial and the short
/weight, /weights, /weight-trial entry paths still resolve to that canonical path.
The explicit OAuth destination allowlist supports returning to Clan Weights;
normal staff authorization remains required. Existing API paths are retained.
Corrected outdated page copy to reflect saved clan weights' source priority.
Validation: 47 backend tests, 225 frontend tests and production build passed;
isolated browser verified legacy and short aliases normalize to /clan-weights.
Member links remain /signup, /assignments, /tasks, /wars, /events and /search.
Other staff tools retain their existing query-based URLs; no general route rewrite.

## Member URL rollout — batch one prepared, not deployed

Member URLs are /signup, /my-signups, /assignments, /tasks, /wars, /events and
/search. My signups is a route to the saved tab of the existing signup feature,
not a duplicate page. Signup tab navigation creates history entries; Back/Forward,
refresh and login entry preserve the requested tab. Legacy query links continue
working, including signup aliases; trailing slashes normalize to the canonical
path. Member pages still resolve only the staff-enabled season. A conflicting
query view cannot override a recognized member path during login.

Validation: 51 backend tests, 228 frontend tests and isolated production build
passed. Covered static paths/trailing slashes, authentication requirements,
allowlisted login returns, historical links, member-season enforcement, and
history navigation/cancellation regression tests. Isolated browser checked direct
saved-tab entry, register/saved Back and Forward, refresh, signed-out destination
and local fixture login, plus an old season=999 link resolving to the enabled
fixture season. No live Discord OAuth login was performed for this batch.

This batch is intentionally held for the combined URL release after staff CWL
and remaining management routes are completed. Do not restart production or
replace its served assets for this batch alone.

## Assign accounts: restore saved-placement color

Restored green background and border only on Assign accounts cards with a saved
assigned_clan_tag. Unassigned cards remain neutral and selected cards remain gold
through the later selection rule. Hosting clan text remains visible, so color is
not the only placement indication. Compare clans and declaration readiness styles
are unchanged. This is a scoped color correction; dimensions, controls, focus and
44px targets are unchanged. Validation: 228 frontend tests and production build
passed; CSS scope and selection precedence reviewed. No new browser visual check
or production deployment was performed; held with the pending local changes.

## Staff CWL URL rollout — batch two prepared, not deployed

Staff CWL pages generate /cwl/signups, /cwl/roster, /cwl/readiness,
/cwl/reminders/signup, /cwl/reminders/return, /cwl/publish, /cwl/results,
/cwl/bonuses, /cwl/exports and /cwl/settings. Season-based pages retain their
season query; publishing retains review/announce step. Existing query links and
trailing slashes resolve to canonical destinations. Existing local filters are
unchanged; URL-backed filter sharing is not introduced by this routing batch.

OAuth return destinations use explicit internal mappings and validated season/step
values, including clean cookie paths. Unknown/external paths cannot become login
redirects. Existing navigation grants and server API authorization remain in force.
No data, schema, external messages, or API endpoints are migrated. Compatibility
mappings serve the same components, not duplicate implementations. Keep old links
for bookmarks and Discord history while generated navigation uses the new paths.

Validation: 67 backend tests (including dashboard permission scopes), 229 frontend
tests and isolated build passed. Covered all route/trailing-slash entries, legacy
links, path precedence, malformed seasons/steps, hostile return destinations and
history cancellation. Isolated browser checked roster to announcements, Back/Forward,
reload retaining announcement step/season, legacy readiness normalization, and the
signed-out OAuth link. No live Discord OAuth or notification delivery was tested.
No layout or control sizes changed. Existing build chunk-size/aiohttp warnings remain.
Held for combined deployment with batch one and remaining management URLs.

## Staff access identity clarity — prepared, not deployed

Owner access lists resolve current Discord nicknames/usernames and role names on
read and after save. Stored labels, grant IDs, permissions, revisions and audit
history are not rewritten by identity lookups. Requests use bounded concurrency
and per-request timeouts; missing members/roles and unavailable Discord retain
saved entries with explicit status. Owner-only access and existing revision/CSRF
checks remain unchanged.

The list shows labeled selectable Discord IDs, usernames, member/role distinctions,
Discord profile links, and name/username/ID search. Removal confirmation includes
the ID to distinguish identical names. Validation: 17 backend permission/identity
tests, 229 frontend tests and build passed. Isolated browser checked long names,
missing-member fallback, role identity, username search, and 320/390/1280px layout
without horizontal overflow. No production permissions or Discord messages changed.
Held alongside the URL rollout for combined deployment.

## Staff access workspace redesign — prepared, not deployed

Replaced the separate form/list with a people-and-roles directory and selected
identity editor. Add access uses the existing searchable MemberPicker (nickname,
username, avatar) and searchable role results, then an explicit Choose permissions
step. IDs remain visible for disambiguation, not required as input. Existing entries
open directly in the editor. On mobile the directory gives way to a focused editor
with Back; editor heading and return list receive focus. Owners remain protected.

Permission sections show counts, explanatory labels and native checkbox switches.
All actions selects only currently listed permission IDs; individual exceptions
remain editable. No wildcard, implied future grant or authorization model changes.
Save/Reset is sticky except on short screens. Unsaved navigation confirmation,
revision-checked saves, role/member lookup recovery, explicit removal confirmation,
and owner-only API protection remain. Empty roles are distinguished from loading.
No storage migration, production permissions or external messages changed.

Validation: 231 frontend tests, 26 backend access/identity/member-lookup tests and
production build passed. Isolated browser exercised name lookup, role search,
selecting existing identities, group on, individual off, Reset, saving to the
fixture store, and returning to the directory. Reviewed 320/390/1280px with long
names, readable identity, selected state, visible save bar and no page overflow.
Existing backend tests cover non-owner denial, stale revisions, role loss and lookup
outages. These checks do not constitute live Discord permission changes or a full
assistive-technology audit. Existing build-size warnings remain. Hold for combined
release with URL batches.

## Staff access profile pictures — prepared, not deployed

Staff directory and editor now include Discord avatars with initial fallbacks;
roles have a distinct @ marker. Reused the existing Discord member avatar URL
builder (server avatar, user avatar or default) and restricted image rendering to
Discord CDN URLs. Labels show display name, username and explicit Discord/role ID,
wrapping long values. No permission or storage changes. Validation: 232 frontend
tests, 17 backend identity/access tests and build passed; isolated browser verified
loaded avatars in list/editor and no horizontal overflow at 320px. The screenshot
reported by the owner was the older live layout; these changes remain held with
the redesign and URL batches, not yet deployed.

## Mobile access removal correction

Removal confirmation uses a separate wrapping action group beneath its text;
mobile buttons stack full-width with 44px minimum height. Hide Save/Reset during
confirmation and restore it on cancellation. Corrects shared notice flex/button
styles that pushed Confirm removal outside the mobile viewport. No authorization
or removal API changes. 232 frontend tests and build passed. Isolated 320px browser
verified both buttons inside viewport, 44px heights, absent save bar during
confirmation and restoration on Cancel. No live access entries removed.

## Reachable mobile menu

Reviewed the supplied mobile recording. Mobile topbar now stays at the viewport top
with an explicit Menu label and 44px control. The drawer brand/close row stays pinned
while its navigation scrolls. Drawer remains above the header and its backdrop;
existing close, Escape, navigation and unsaved-change behavior remains. At very narrow
widths, account avatar stays visible while username yields space to page/menu labels.
Desktop navigation is unchanged. 232 frontend tests and build passed. Isolated
390px check opened navigation after 2448px page scroll, then scrolled the drawer
953px and verified its close button stayed at 15px. 320px menu remained at 9.5px
with a 44px target and no horizontal overflow. No data or API changes.

## Shared dashboard frame — October 22

Removed duplicate server branding and aligned page content 28px from the desktop
sidebar instead of centering it across a large empty gutter. Navigation uses a
consistent row style, gold active state and restrained section labels. The server
header and account footer stay visible while only the navigation list scrolls.
The footer reuses Discord avatar/name fallback and includes the username. Existing
page components, permission filters, routes and unsaved-edit guards remain intact.
Obsolete community-panel and conflicting navigation styles were removed.

The mobile Menu stays sticky. Closed navigation is inert; open navigation has
modal semantics, keeps keyboard focus inside, and restores focus to Menu on close.
The page behind it is inert. Resizing to desktop closes the drawer. Native dialogs
retain their own keyboard handling. No persistent data or API changes.

Validation: Sol implemented the visual frame; Luna independently reviewed navigation
permissions and keyboard risks. 232 frontend tests, 17 backend access/navigation
regressions and the production build passed. Isolated sample-data checks covered
1440px desktop, 390px mobile and 320x480px short mobile: no horizontal document
overflow, 44px minimum menu targets, pinned close/account controls, nested active
navigation, Tab/Shift+Tab wrapping and Escape focus restoration. Existing permission
and history tests remain green. Native confirmation cancellation was not verified
in the browser; existing canLeave handlers are unchanged. No live permissions,
rosters or Discord messages were modified. Existing Vite bundle/import and aiohttp
warnings remain; this is not a full assistive-technology audit.

### 2026-10-22: CWL Assign accounts

Applied the compact-row, contextual bulk-action and focused Details patterns
documented in docs/cwl-design-guide.md. Validation scope and limitations are recorded
there: 233 frontend/51 backend tests, isolated desktop/mobile checks and failure
paths. No storage migration, permission change or notification behavior change.

### 2026-10-22: Manage signups

Adopted the CWL compact list/filter pattern, visible Discord identities, explicit
signup actions, and reliable focus after cancellation or refreshed removal.
The signup status bar keeps one Add signup entry. Read failures are distinct from
empty results; filters cannot disrupt an active edit. See cwl-design-guide.md
for the stage's regression and isolated browser evidence and limitations.

## October 22: Remaining dashboard URLs completed

All dashboard views now have clean page paths. Management destinations include
`/staff`, `/clans`, `/clans/strikes`, `/clans/replacements`, `/tickets`, `/server`,
`/server/members`, `/server/applications`, `/server/fwa`, `/server/commands`,
`/settings/access`, `/settings/integrations`, `/settings/image-gallery`, and
`/settings/issues`. Existing member, CWL and clan-weight paths remain unchanged.
Legacy `?view=` bookmarks still resolve and normalize after authentication. Existing
Discord posts do not need deletion or replacement. OAuth API query parameters are
intentional API inputs, not old page URLs. Season and publication-step parameters
remain on the relevant CWL pages. Member pages still use the current member season.

Sign-in preserves allowlisted management destinations without widening permissions;
unknown destinations, external redirects and traversal-like return cookies are
rejected. Management return URLs discard unrelated query parameters. The installed
app starts at `/tasks` with its existing app ID. Push payloads and service-worker
clicks now use `/tasks`, including clicks on older notifications. No data migration.

Review: independent Sol backend implementation and Luna adversarial review, plus
frontend/backend route, OAuth, history, permission and push regressions. Isolated
browser checks covered direct Staff access, navigation to Family clans, Back,
refresh, and legacy-link normalization at desktop/mobile widths. The mobile page
had no horizontal overflow; unavailable fixture settings retained a visible error.
Live Discord OAuth and notification delivery were not exercised. Existing API
permissions and unsaved-edit history guards remain in force.

Validation totals: 256 frontend tests, 46 backend tests and 49 route subtests passed;
TypeScript/Vite build passed. Existing aiohttp warnings and bundle-size warning
remain. No live messages were sent.


## Ticket browser applicant flags — October 23

Ticket browser results and conversation details show active applicant flag names
and recruiter reasons. The archive search matches flag names, and an explicit
flag filter can be combined with status, ticket type, and opened-date filters.
Flag summaries are limited to kind, label, and reason and remain behind the
existing recruiter and dashboard authorization checks. Approved tickets retain
their approved status alongside the flag.

Validation for this scope: ticket browser backend tests (10 passed), frontend
suite (68 files / 275 tests passed), and frontend production build passed. The
new flag and reason were represented in the isolated preview fixture at
`http://127.0.0.1:8784/manage/tickets` using `/tmp/wu-ticket-preview-flew.py`
and `/tmp/wu-ticket-browser`. Isolated headless Chrome checks covered the list
at 1280/390/320px, selecting Flew the Coop, and opening conversation details
at 1280/320px. Flag reasons and Approved status were visible; no horizontal
document overflow was observed. Native labeled selects and existing focus/return
behavior are retained. This is not a full assistive-technology audit. No live
Discord writes were made.

## Commands and image tools — October 23 review

Command triggers and Image Gallery now follow the directory/editor pattern, with
one save location, deliberate preview/testing, compact image filters and guarded
drafts. Gallery storage indexing is an explicit maintenance action. See
[the scoped review](commands-images-review.md) for browser widths, regression
coverage, concurrency contracts and limits; simulated sends are not live delivery.

### Pool-change confirmation follow-up — October 23

Shortened both directions to an account name, explicit source → destination,
one plain-language description and a save reminder. Placement removal remains
visible when applicable. At the owner’s explicit request, the supplied GIF is always displayed without
a Play/Hide control, including when reduced motion is enabled. The FWA restriction
and save boundary are unchanged.

Validation: 301 frontend tests; production builds; isolated browser checks at
320px and desktop for both directions, GIF playback and cancellation/focus return.
No live signups were changed. Released as a frontend-only patch over 2042b0b;
the separate server-settings/BAND rollout remains pending credential setup.

### Wars — October 26

Use compact matchup cards with personal accounts visible, exact dates and task
handoff under Details, and inactive clans in a disclosure. Current-member scope is
the default; staff explicitly opt into family scope. Unknown/private results remain
visible. See [Wars review](wars-review.md) for membership and hosting-clan rules,
regression evidence, responsive checks, and limitations.

### Events visual clarity — October 26

Events now uses 40px icon containers with the established 24px interface icons,
stronger event titles, countdowns above descriptions, and quieter exact dates.
Styles are scoped to Events. Event order, recurring schedule calculations, timezone
controls, staff raid scope, refresh, sources disclosure and CWL navigation are unchanged.

Review: 346 frontend tests, 13 activity backend tests and production build passed.
Isolated browser checks at 1280/390/320px covered no document overflow, timezone
switching, staff scope, member control exclusion, sources disclosure, CWL handoff,
and last-known raid data after failed refresh. Screenshots were inspected at desktop
and narrow mobile widths. Calendar tests cover event boundaries and signup versus
battle timing. No live records or notifications were modified; fixture checks are
not proof of live game data or a full assistive-technology audit.

### Home / Tasks / Wars journey — October 26

Preserve view-only search, sort, page and scroll position across the activity journey.
Store clan-task handoff context in its browser history entry; new explicit CWL links
must not inherit an unrelated prior tab. Tasks has a direct clan-score link and an
explicit search reset. See [journey audit](home-tasks-wars-audit.md) for reviewed
boundaries, browser evidence and limitations. Signup selections and notifications
remain outside the new transient view-state helper.


### Home and mobile menu hierarchy — October 26

Keep the collapsible mobile Menu; do not add permanent bottom navigation. Put frequent member destinations before a permission-filtered Staff tools disclosure. Opening a staff destination must expose its active navigation group. Home should emphasize one CWL next action and keep secondary activity links compact. Incomplete, cached, or failed account reads must not appear as settled totals or invite account selection. Keep existing signup review and save boundaries.

The scoped implementation and usability/accessibility checks are recorded in [the comparative review](clashperk-dashboard-review-2026-10-26.md#homemenu-implementation-review--october-26).

Before validation builds, check the configured static asset directory. On this host the live web service serves web/cwl/dist; use an isolated Vite --outDir under /tmp for testing. Only a deliberate release should replace the served index, after copying its assets and retaining older hashed files for active sessions.


### Member player and clan details — October 26

Home and Search use the same compact, read-only details dialog. Opening details must not toggle an account checkbox, clear selections, navigate away, or save anything. Preserve the underlying search/filter/page/scroll state; Close and Escape restore focus to the opener, falling back to the focusable dashboard main region if it disappears.

Use known linked-account identity immediately. Discord identity is contextual to the signed-in member and is passed only for that member's linked accounts; it is not a general Discord-owner lookup. Label timestamps as data loaded, not proof of fresh game-source verification. Missing optional league fields do not deserve empty cards. A clan's linked-player subset is not its full roster; partial/unavailable reads must say so.

War & CWL is opt-in and uses the existing authenticated member-scope activity endpoint, without polling while closed. Select regular war for the current clan and CWL independently by the exact linked player tag, including recent hosting clans after the player returns home. Missing lineup data, explicit nonparticipation, unavailable counts, private logs, no returned war, and failed requests remain distinct. Never borrow another account's attacks or infer absent history. Permission failures clear protected detail/list data and invalidate in-flight reads.

Review evidence: Sol built the base dialog, Luna built on-demand activity, and a separate Sol adversarial pass reviewed integration, ownership, URL constraints, authorization loss, stale-response races, and signup boundaries. Parent browser fixtures used fictional data and rejected all writes. Checked 320px/390px/1280px layouts, long names, avatar fallback, keyboard focus trapping/Escape, retained checkbox selection and Search query, member vs family-directory clan scope, separate home-war/CWL-host activity, activity error recovery UI, close during slow read, and immediate modal/list clearing on 403. Basic dialogs made zero activity requests before expansion.

Validation: 85 frontend test files / 361 tests passed; TypeScript and Vite isolated build passed; backend navigation regression suite passed (2 tests); diff whitespace check passed. Tests include malformed URLs and stats, absent/partial activity, unrelated players, and CWL hosting after returning home. No backend routes, durable storage, signup writes, schema migrations, or live notifications changed. Historical clan statistics and full attack logs remain separate backlog work. Fixture checks do not establish live game-data freshness or real-phone behavior.

### Wars lineups and attack log — October 26

Keep matchup, timing, scores, and personal remaining attacks on the compact card.
Place lineups and attacks inside its existing War details disclosure and fetch only
while open. Show one view at a time: Lineup (clan/opponent selector) or Attack log;
paginate twenty rows. Identify each attack's side and mark only verified own-side
linked accounts. Use the established goldenrod selected state and native controls.

Tie detail responses to the displayed war identity and authorized scope. Cancel on
close/change; reject stale responses; clear protected data on permission loss.
Missing/private/partial data must not imply no attacks or a complete lineup. Do not
add historical claims, stored member records, or extra overview polling for details.
See wars-review.md for validation scope and limitations.

### Member attention and linking recovery — October 26

Use one compact Needs attention summary for related read failures on Home, Search,
and CWL signups. Each recovery action names its purpose. Retain separate save errors,
consent, withdrawal and placement warnings; do not combine them with read status.
Technical diagnostics start collapsed, but the failure and recovery action stay
visible. A failed check is not a missing link or zero signups. Only a completed
successful account lookup may offer confirmed-empty linking guidance.

Keep linking instructions in one disclosure per applicable page. Link accounts must
open it, focus its summary and leave focus below the sticky mobile header. Summarize
missing links for saved accounts with a count, Accounts to check disclosure, and
Refresh accounts; retain a brief row hint explaining unavailable pool changes.
Refresh must retain the existing unsaved-change confirmation. Family-directory
failures remain staff-specific; do not fetch staff diagnostics on member Home.

See member-attention-review.md for scope, test evidence and limitations.

### Staff integration and reminder health — October 26

Keep operational failures and last scheduled outcomes visible; put technical
status details behind a disclosure. A missing destination must not replace an
unconfirmed-delivery warning. Use the existing editor for Review destination.
Cached channel names may remain during an ordinary outage, but are not current
inventory until a successful read; clear them on permission denial and ignore
older requests. Do not invent exact next-run times or infer send permissions from
channel presence. See [staff health review](staff-health-review.md) for scope,
validation and limits.
