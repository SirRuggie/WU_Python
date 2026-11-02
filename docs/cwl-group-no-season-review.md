# CWL groups without a season

Prompt 107 follows the ordinary capture diagnostics in handoff 671. At
06:23:52 UTC on November 2, seven normalized groups had no season value:
four `ENDED`, three `PREPARATION`. Three other clans returned leaguegroup 404.
The agent made no provider probe or Check Clash request.

For the selected cycle equal to the current UTC month, a valid group with no
season and `PREPARATION`, `INWAR` or `WAR` is attributed to that month. This is
an explicit inference requested in prompt 107, not a verified provider contract.
Explicit month values always win: older/later groups are never relabeled.
A group without a month in `ENDED` is not captured as active; it can yield a
normal wait only when no matching-month war has been observed. Past, future
and archived selections never infer a missing month. Ownership, roster and
round shape validation still precede either inference or waiting.

A war with an explicit different season remains rejected. In-progress groups
never complete early. Waiting clans mixed with active clans produce partial
progress with no outage warning; unavailable or invalid responses, denied
access and timeouts still warn. Counts remain unknown for waiting clans.
Cached source/receipt data is not attributed to a different month. No schema
migration or provider polling was added.

Group month diagnostics log a validated clan tag, whitelisted state and boolean
season presence/inference, never response bodies. Results and Bonus consumers
read cycle-keyed participation observations rather than interpreting raw group
season fields themselves. The existing strict group validator receives only a
local effective copy; normalized provider evidence is unchanged.

The official [API documentation](https://developer.clashofclans.com/#/documentation)
was checked read-only. Its JavaScript shell exposed no readable specification
of when season is omitted. Existing provider normalization preserves an absent
or null season as `None`; the captured safe diagnostics establish the seven
missing values but not the API's general omission rules. No claim about those
rules or live November capture is made from isolated tests.

Release is held pending Ruggie's approval and Claude's review. No production
activation, role change, notification or forced capture is part of these checks.
