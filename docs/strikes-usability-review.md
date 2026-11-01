# Strikes usability review — prompt65

The account list ignores the API's legacy risk/watch/active classification; those
fields remain for compatibility. Ruggie removed those badges on October31,2026.
Strike actions, priority editing, eligibility, retention and tracking rules are
unchanged. Tracking reads now have visibility/in-flight/event guards, as requested
in review228; no delivery or tracker mutation was added.

## Presentation and behavior

Not attacking defaults to three or more consecutive known wars without attacking,
sorted by that chain then strikes. Inactive uses fourteen quiet days; Replacements
retains its existing marked/eligible rule; All has no hidden view predicate. Every
threshold has a removable applied chip. The shared panel has searchable clans,
all requested criteria, a live count and Clear filters. activity_view is separate
from the dashboard's view route, so sign-in and Back retain the complete filter
state. Select all uses the visible matching population, with its existing fifty
account bound and full confirmation; sort changes retain selection.

Phone rows show name/priority and plain strikes, TH/clan/weight, then one muted
summary: Quiet days, attacked/known wars, attacked/known raid weekends. Chains and
missed attack slots stay in detail. Unknown samples remain blank or unavailable,
not false zero. No activity yet is a compact label for a known tracking start;
ClashKing seeds keep a ~ marker and explanatory tooltip/detail. Over limit, New
this week, departure and notes remain in detail when they would wrap the row.
Only Chopping Block is red; High is amber and Normal has no label.

Wide screens use Player, TH, Clan, Weight, Strikes, Quiet, Wars, Raids and Priority
columns with sortable headers and a sticky header. Skipped raids is also exposed
as the matching sort for the Raids header. Search/sort/filter controls occupy54px
and stick below the mobile topbar. Copy list uses every matching account across
pages and reports clipboard rejection; names are plain text with mention syntax
neutralized. Recruit lookup moved unchanged into its own component and stays
closed until requested. External names and notes render as React text.

## Clan control sweep

Participation and Bonus Hosting clan choices now reuse searchable RosterMenu,
retaining disabled states, selection and discard behavior. Roster/Compare,
assignment and weight trial already have searchable clan controls. ClanHistory's
Show, DashboardHome and Events controls select categories/scopes rather than a
clan and remain unchanged. ClanDestinationOptions has no runtime consumer.

## Verification and limitations

Full guarded backend:5533 passed,29 skipped,221 subtests. The stale inherited Mongo
assertion found in review232 was corrected to the new storage-outcome wording;
all three real-Mongo cases now pass on this branch, and its owned fixture stopped.
The same assertion correction is present in PR119's rework branch; its complete
four-case rework lane is not yet claimed green. No live Discord delivery was
performed or proven by these fixtures.

Six behavioral mutants were killed: unknown wars count as misses; unknown sort
becomes zero; hidden rows enter bulk selection; sort label disagrees; unknown
renders as zero; a tab's bulk predicate loses its applied chip. Baselines pass.
Unit coverage includes all sorts/filters, both directions, headers, tabs, complete
URL/login restoration, unknown/contradictory samples, Copy across65 accounts,
searchable/disabled clans, permission loss and full selected names.

Latest sixteen-scenario visual run covers320/360/390/1440 with26/65/125/560
accounts. No overflow, cell-overlap or page errors;54px toolbar. Final rows measure
90px phone and44.5px desktop, versus Claude's production reference181/87px. With
controls stuck, the fixture shows seven full phone rows plus a partial and twenty
desktop rows; initial viewport counts are four/thirteen because page headings and
tabs are still visible. These populations differ from the original production
sample. Narrow/wide screenshots and each tab were inspected. A first nine-column
CSS iteration incorrectly forced mobile44px rows; visual inspection caught the
overlap, and stricter per-cell geometry checks verify the corrected90px rows.

Real Chrome measured reads at about30/60 seconds, none during35 seconds hidden,
and one on return despite forty focus events. The full layout chain exposed a
one-millisecond early interval skip; scheduled visible ticks now read regardless
of the event throttle. Seven component cases include that jitter and StrictMode
replay. Initial identity refresh is unchanged. Auth/seasons keep their separate
existing sixty-second visible polls. This is an isolated browser observation,
not a signed-in production trace or a complete assistive-technology audit.

Final frozen-source validation passed:1,268 frontend cases across232 files,
TypeScript/build and every stage of the ten-stage integrated layout command.
The final cadence sample was29.93/59.93/100.01 seconds. Full logs and screenshots
are retained in.local/p65-final-evidence; no required gate remains pending. Earlier harness failures (searchbox
role, counted checkbox label, panel-entry URL restoration and teardown races) were
corrected; failed runs are not counted as passes. No production65 write or
activation occurred.

Claude addendum 236: compact mobile summaries and the desktop Wars column now show
“Missed last war” / “Missed last N wars” for a known consecutive no-attack chain.
A zero chain retains the known attacked/observed ratio; unknown observations remain
hidden. Full detail keeps the attacked/observed count. Wars sorting continues to
use the unchanged prompt 60 chain. Targeted regression tests cover singular,
plural, zero and unavailable values.

## Prompt 69 rework

Tracking reads have a 10-second deadline and abort signal. Their generation owns
the pending slot, so a timed-out read cannot block future polls. A successful
Retry invalidates/aborts older polls and forces a fresh read; old responses cannot
replace Retry queued. Copy closes its menu and uses a four-second fixed viewport
toast, cleared when filters change. A pending clipboard response also checks the
filter identity before displaying feedback.

Extra filters retain the selected tab. Its base predicate is shown as static
text, not a removal button that silently changes the tab. Clear removes extra
filters on that tab; an empty state identifies the selected tab. Tab counts
respect the active extra filters and predict the corresponding tab switch; the
active tab count matches Showing N. Old marked=0 links map to All. Clan option
counts include left accounts consistently. Tracking stalls cannot claim No
activity yet, and a latest unusable war produces an unavailable chain instead of
a misleading zero ratio/sort value. Valid chain rules are unchanged.

Direct links and post-action refreshes request activity. Historical accounts
outside the family retain a ledger fallback after the activity lookup, with
absent activity honestly unavailable. The shared Hosting clan menu closes without
calling its change handler for the current choice. Actual Bonus and Participation
component regressions cover this; Bonus retains its manual slot draft and does
not ask to discard it.

The header combines routine navigation on desktop; occasional Add strike / Find
war / help are within Activity actions, at most two taps. Tabs use one horizontally
scrolling line on phones. The repeated visual Family accounts heading is now
screen-reader-only. Focus scroll margins allow for the real shell plus sticky
controls. Final 560-account fixture: first row about280px on phones, about188px
on desktop; 90px phone /44.5px desktop rows, five/eighteen complete initial rows,
seven/twenty after scrolling. All16 width/population cases have no page overflow
or cell overlap and retain 44px controls.

Validation: 1279 frontend tests/233 files, tsc/build, 402 network-isolated relevant
backend cases/5 skips, four behavioral mutants killed. All11 layout stages passed,
including a real App-shell browser Back/forward/direct-link check at360/1440.
The integrated command first refused occupied8981 without contacting it; the next
run passed its first three stages, then an obsolete replacement test tried to
remove the now-fixed tab predicate. That test now explicitly selects All, passes,
and the remaining seven stages passed against unchanged application source.
Logs and screenshots: .local/p69-final-evidence. No production activation, live
Discord test or delivery proof is claimed. Eventual release remains backend plus
frontend only; the bot can retain its independently deployed revision.
