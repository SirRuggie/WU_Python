# No league group yet and private-war polling

Claude entry 341 requested this follow-up under the release approval in 337.
The prior release remains at `participation-wait-1` until this branch is accepted
and activated with fresh gates. No provider probe or live test action is used.

## No-group classification

A `ProviderUnavailable` carrying HTTP status 404 from the league-group lookup is
classified as `no_group`. A current or next UTC month, no previously observed war
for that month, and only `no_group` or recent older-group failures may produce
the normal wait line. Past or later selected months, prior preparation/war
responses, mixed upstream failures, malformed responses, 403, 429, 5xx and
unknown failures keep warning behavior. Unknown account results are not zeros;
manual results and observations are preserved. No data migration is required.

The previous ordinary capture stored only a generic unavailable category. The
existing logs do not preserve the league-group HTTP failure type, so an actual
404 in that run cannot be established. The follow-up records a narrow category
and status code on each ordinary capture; it never makes another request to
reconstruct an earlier failure. The existing 15-minute capture schedule stays.
Only a later ordinary capture can show whether live data takes the new branch.

## Private-war backoff

Read-only logs in the current web invocation show repeated accessDenied403 for
two current-war lookups, about 55 seconds apart. The push worker sleeps 45 seconds
between passes; its fresh snapshot uses `lookup_cache=False` and `fresh_reads()`.
That bypassed the shared negative cache even for a known private war log.

Fresh reads now retain the existing 15-minute private-war negative-cache entry,
while still refreshing positive wars, no-war answers, player data and other
failures. Entries expire normally and remain bounded by the existing cache
owner. Manual cache clearing can recheck changed permissions. The private result
still means unreadable, never proof that no war exists. There is no notification
retry, subscription, authorization or delivery change.

The only production caller of `fresh_reads()` is the web push snapshot. This
change therefore needs no bot restart. The one recorded Push reminder TimeoutError
has no traceback or stage detail. Source inspection places that warning around
fresh snapshot processing; a private-war response is caught as an unreadable
result. A causal link to that timeout is not established. No timeout setting or
notification-delivery behavior was changed on that inference.

## Validation

71 focused participation, sync, cache and push tests passed, with five final
strengthened cases confirming durable status guards and private-cache behavior.
Full guarded backend: 5,861 passed, 71 optional skips, 253 subtests. Required
war-reminder checks: 213 backend passed, one skip, 35 frontend tests and build.
The unchanged frontend build retains the prior release entry and SHA256.

Four genuine mutations failed tests: outages treated as normal wait, prior-war
guard removed, current/next guard removed and private backoff bypassed. The first
prior-war mutation survived because the response adapter masked an incorrect
stored waiting status; the added durable-status regression now kills it. The
survival is retained in the evidence and was not counted as a kill. Formatting
was limited to changed functions/classes with an AST-equivalence check. No production Check Clash, Import, Review, Rename, role, Send or DM
action was performed. Production confirmation waits for Claude's read-only smoke
and the ordinary scheduled capture after an accepted release.
