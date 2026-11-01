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
