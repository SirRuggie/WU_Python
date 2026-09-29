# Family Code completion recovery

Family Code challenges remain in `settings.recruit_challenges` with a 24-hour
expiry. A valid reply atomically claims either an active challenge or a processing
challenge whose two-minute lease has expired. No restart or replacement prompt
is needed to recover an interrupted check: the next valid reply can reclaim it.
Fresh processing claims and expired challenges are never reclaimed.

Each attempt has a random claim ID, separate from the recruit's Discord message
ID. Claim acquisition is scoped to the observed prompt session. Failure rollback
and completion deletion target only that exact claim, so a delayed handler cannot
reset or remove a replacement prompt or another attempt on the same message.

Moderator lookup and confirmation delivery share a 60-second timeout, shorter
than the processing lease. Known delivery failures/timeouts release the claim
immediately for another reply. Abrupt cancellation leaves the lease to expire.
Startup no longer resets every processing record; normal lease recovery applies
across restarts too. Existing processing records already have the required lease
field, so no Mongo migration is needed.

The displayed text, artwork, code parsing, warning cooldown, and warning deletion
behavior are unchanged. Discord delivery and Mongo completion are separate
operations; a crash after delivery but before completion can still produce a
repeat confirmation on a later valid reply. Recovery preserves the challenge
rather than silently losing it.
