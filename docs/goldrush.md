# Gold Rush giveaway

Gold Rush is opt-in. Its leaderboard ranks Discord entrants by the combined
recorded gold from all their eligible linked Clash accounts. Family members who
have not joined are not ranked. The existing family battle ledger is preserved.

## Public panel

`/loot-leaderboard` posts the active Gold Rush signup and top 10 as a standalone
channel message. Once an event exists, Update on an older family panel replaces
it with this opt-in panel too. `/goldrush post` is an administrator shortcut that
creates the initial event if needed, then posts the panel.

The initial event uses the existing tracker start and lasts 24 hours. Its prize
is one Gold Pass. No event prize is automatically purchased, awarded, or sent.

**Join Gold Rush** reads the clicker's account links through both ClashKing and
ClashPerk, checks for conflicting ownership, and enters all matching accounts
in the captured Warriors United family roster. Links unavailable or disputed
block signup with a private explanation. Untracked/outside-family accounts are
excluded. Each player tag can belong to only one entrant per event. Entered
accounts are locked; repeated joins are idempotent. New linked accounts do not
automatically alter an existing entry.

Late signup is allowed until the end. Scores count battle timestamps from the
event start, not signup time. Farming, ranked and legend gold count; screenshots
are never requested. Only `[start, end)` battle timestamps are included. For a
tie, the earlier last positive-loot battle wins (when that entrant first reached
the final score). Exact timestamp ties remain unresolved for prize review;
join time and Discord ID provide a stable display order only.

Panels auto-update every five minutes after a refresh; the Update button can
refresh sooner. The stored panel IDs and signup records survive restart. The
collector continues recording family loot independently of participation.

## Admin schedule configuration

`/goldrush configure start:2026-10-09T18:00:00-04:00 hours:24`

Use an ISO timestamp with an explicit timezone offset. The private preview
shows viewer-local start/end timestamps and a confirmation button. Only the
requesting administrator can confirm, within ten minutes. An outdated preview
cannot overwrite a more recent configuration.

A future start resets displayed scores to zero until that time. Signups and
raw battle history are retained; scoring changes its time window instead of
deleting data. A past start is allowed only within the already tracked period,
and the new end must be in the future. The duration is 1–168 hours.

At the end, signup closes and the panel says results are pending. Give upstream
history time to arrive and review completeness, then run `/goldrush finalize`
to refresh once more and lock results. It refuses when the refresh reports
failures. Successful API responses still cannot prove that upstream collection
captured every attack; the event uses the battle history actually available.
Finalized results do not change with later source corrections. Exact winning
ties and prize delivery require staff review. Finalized events cannot be
rescheduled by configure.

## Persistence

Event settings, entries, configuration confirmations, final results, and message
IDs are stored in the same SQLite database as the battle ledger. They are
included in its atomic latest recovery backup. The untouched baseline backup
predates the event and is not a replacement for the latest backup.

Only an administrator can post through the goldrush command group, configure
or finalize an event. Signup and Update are available to members in Warriors
United. Buttons are persistent and do not rely on expiring in-memory state.
