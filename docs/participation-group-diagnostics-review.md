# Ordinary participation failure diagnostics

The first ordinary capture after participation-no-group-1 logged three HTTP404
no-group results and seven other unavailable results. Their underlying response
shapes were not retained. This change does not infer that those seven failures
are normal, request extra provider calls, or change participation status rules.

Existing ordinary failure records gain the validated clan tag, exception type,
a fixed reason code and a whitelisted group-state enum. No external exception
message, response body, clan name, member data or credentials are logged. Unknown
or malformed states collapse to `other`; forbidden, throttled, timeout, corrupt
and unconfirmed empty states retain warnings. Existing HTTP404 and recent older
month rules remain unchanged.

After an accepted deployment, use the next naturally scheduled capture to map
those safe reasons to the affected clans. Only a confirmed normal no-group
response can justify a later wording change. No live provider probe or UI
refresh is part of this development check.
