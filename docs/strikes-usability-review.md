# Strikes usability implementation checkpoint

Prompt 65 is an account-list presentation/filter change. Strike actions,
replacement eligibility, retention and trackers remain separate. The new model
ignores the API's legacy risk/watch/active classification; those response fields
remain for compatibility. UI replacement and the staff clan-picker sweep are
still in progress, so this increment is not ready for review or deployment.

The filter model records every predicate in URL state and removable applied
chips, including a tab's known-war/inactivity/replacement criteria. Unknown war
samples never count as misses, and numeric unknowns sort last in either direction.
Copy uses all matching accounts, normalizes name line breaks and neutralizes
Discord mention syntax. Replacement and optional low-strike eligibility rules
remain unchanged.

A small read-only projection adds attacked/known wars, the last attacking war's
end, and attacked/known samples from the latest two ended raid weekends. Exact
attack timestamps are not stored: the sort label explicitly says Last attack
(war end), with a matching explanation planned in the detail. Unknown samples
are excluded from both numerator and denominator; no tracker or storage writes
are added. Existing activity status and replacement logic are unchanged.

Current targeted checks: eighteen filter/sort/URL/copy cases and twenty-two
activity signal cases pass. Full feature validation and required mutations will
follow the completed UI. No live writes or deployment have occurred.

The tracking panel now skips hidden-tab interval reads, coalesces in-flight
reads and throttles focus/visibility bursts to one read per thirty seconds.
Explicit checks and retry completion may refresh immediately. Its pre-change
thirty-second timer explains two tracking reads per minute; this alone is not
proof of a render loop. Five component regressions pass, including a hung read,
ninety seconds hidden and repeated focus events. Real browser cadence measurement
and the full UI review remain pending.

The account list now uses the new visible tab/filter model, searchable clan
filter panel, sort direction, removable threshold chips, Copy list and compact
single-summary rows. Recruit weight lookup moved unchanged into its own component.
Thirty-four targeted UI/model/polling checks pass. StrictMode effect replay keeps
the initial coalesced tracking read. The semantic desktop table and full activity disclosure are implemented;
shared staff clan-picker sweep and full browser validation remain;
this is still an implementation checkpoint, not READY.

The latest full frontend run passed 1,261 cases across 231 files, with TypeScript
and build. Four required mutants were killed: unknown wars counted as misses,
unknown sort values becoming zero, hidden rows entering Select all, and a sort
label disagreeing with the selected value. A sixteen-scenario Chrome run passed
320/360/390/1440 widths with 26/65/125/560 accounts: no horizontal overflow,
54 px sticky toolbar, 90 px phone rows and 52.5 px desktop rows. Visual inspection
caught an exposed table caption and hidden mobile priority; those styles were
corrected, so final screenshots and measurements will be refreshed. The prior
reference rows were about 181 px phone/87 px desktop. This is not final evidence
for the subsequent style corrections.

URL state uses activity_view to preserve the dashboard's separate view route
parameter. Sign-in and Back restoration regression coverage includes every new
threshold. Removed the obsolete status/chip view implementation and seven tests
for that retired behavior; the new model has nineteen cases plus component/detail
regressions. All existing strike actions, permissions and replacement eligibility
remain. Hosting-clan controls in Participation and Bonus now use the shared
searchable RosterMenu while retaining disabled and discard behavior.
