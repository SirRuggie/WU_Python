# LazyCWL dashboard

`/lazycwl` is the administrator dashboard for CWL saved player lists. It
replaces the retired `/fwa lazycwl-*` workflow; those commands open the
dashboard so existing command habits still lead to the supported screen.

## Dashboard flow

Open `/lazycwl`, choose a clan, then use **Overview**, **Players**, or
**Reminders**. The dashboard does not preselect a clan. The selector retains
the existing maximum of 24 clans plus the explicit bulk choice.

- Overview shows the selected clan badge, capture time, roster size, away
  count, reminder state, and expiry. No saved list is a neutral state;
  everyone returned is green; away or unavailable status needs attention.
- Capture current roster reviews the selected clan first. In bulk mode it
  names only clans without an active list. Existing saved rosters are not
  replaced. Close saved list is a red confirmation that stops reminders and
  closes the reviewed roster, allowing a fresh capture afterward.
- Players displays 20 players per page with Town Hall and current return
  status. Add player opens a tag form. Select up to the whole page to remove
  players, review the names, and confirm. Navigation and clan context remain
  visible, and mutations refresh the current player page.
- Reminders shows the destination channel, explicit on/off state, frequency,
  and next run. Choose 30, 60, or 120 minutes and confirm to enable/update.
  Disable and manual sends also review their affected saved lists. Manual
  send review distinguishes away players from linked Discord accounts;
  recipients are checked again before sending.

Green confirmation buttons apply changes immediately; there is no separate
unsaved dashboard draft or final Save template step. Discord timestamps show
dates in the viewer's local time. Old slash command names are redirect aliases.

Panels are private, expire after 20 minutes, and belong to the opening user
and server. Every interaction rechecks Administrator permission. Confirmation
payloads are kept server-side, bound to the operation and specific roster ids,
and consumed once. Cancel invalidates the pending action. Restarting the bot
expires open panels; reopen `/lazycwl` without losing saved rosters.

The dashboard has one active saved list per clan. A list contains the saved
players, their Discord links when available, optional repeating reminders,
and the date it expires. The service asks the Clash API for the current clan
roster whenever it needs to identify players who are away. Away state is
never stored as a fact about a player.

## Dashboard flow

The dashboard opens without a clan selected. Choose one clan to inspect it,
or choose **All saved lists (bulk)** for an explicitly scoped bulk action.
Overview, Players, and Reminders are separate tabs. The Players tab shows 20
players per page and supports reviewed add and remove actions.

Capture, send, close, and reminder enable or disable actions always show a
review before the final confirmation. The review names the affected clans,
their count, and the reminder destination where relevant. It never exposes
database ids. Confirmations are session-bound and one-time use.

## Storage and lifecycle

`utils/lazy_cwl_store.py` owns the `lazy_cwl_lists` collection. Active lists
are unique by clan tag. Finished and expired lists remain available until
MongoDB removes them 90 days after their expiry date.

On startup, the service creates its indexes, imports active records from the
retired `lazy_cwl_snapshots` collection, expires due lists, and restores
enabled reminder jobs. Each migrated list records its legacy snapshot id, so
repeating startup never creates a second list. The legacy row is retired only
after its destination is present, preserving existing active rosters and
their reminder configuration through the transition.

Legacy snapshots did not have an expiry date. A live snapshot imported at
startup receives the current CWL expiry window: midnight UTC on the next
applicable 16th. This avoids immediately expiring a previously active list
solely because it was created in an earlier month.

New lists expire at midnight UTC on the 16th of their saved month. A list
saved on or after the 16th expires on the 16th of the following month.

## Reminders

An enabled reminder runs at its chosen interval for up to seven days. The
scheduler records successful sends and restores the next future run after a
restart, without replaying missed intervals. A scheduler registration failure
is retried by the startup reconciler; the database never claims that a newly
enabled reminder is running when its job could not be registered.

Manual reminders and scheduled reminders recompute the current away players
from the Clash API. If nobody is away, no Discord message is sent.

## Safe dashboard actions

Every destructive or state-changing action from a rendered list carries the
saved-list id that was displayed to the administrator. The service includes
that id in the database write query. If the list was finished and replaced
while a confirmation was open, the action returns a stale-list result and
does not change the replacement roster or its reminder configuration.

This applies to finishing a list, removing players, adding a player, turning
reminders on or off, and sending a manual reminder. Refresh the dashboard
after a stale result, then make the intended change from the current list.

## Data shape

An active list has a normalized `#UPPERCASE` clan tag, a UTC save time,
normalized players, and this reminder state:

```
reminders: {
  enabled: bool,
  every_minutes: int | null,
  started_at: datetime | null,
  last_sent_at: datetime | null,
  sent_count: int
}
```

Each player records tag, name, Town Hall, optional Discord id, whether it was
added manually, and its UTC add time. A failed Discord-link lookup is kept
distinct from a successful lookup with no linked players: saving a new list
stops when the lookup fails, while a manual addition proceeds and reports
that its link could not be checked.
