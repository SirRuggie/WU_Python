# FWA sync panel

Replaces the old "DM a fixed list of user IDs" alert (`extensions/tasks/band_sync_ical.py`,
pre-panel design) with a self-service channel panel: members opt themselves in per
BAND sync event and choose their own reminders, instead of an admin maintaining a
recipient list. The old broadcast path (`dm_user_ids`) still exists behind a flag - see
Deploy note below.

Owning modules:

- `utils/band_ical_parser.py` - pure feed parsing and alert-timing math (`due_offsets`,
  `drop_past`), no Mongo, no Discord.
- `extensions/tasks/band_sync_schema.py` - `SCHEMA_VERSION`, constructors and
  `normalize_*` for the four `fwa_sync_*` collections, plus the pure recipient helpers.
- `extensions/tasks/band_sync_ical.py` - the poller: fetches feeds, tracks per-event
  state, queues and sends deliveries, owns the `/fwasync` admin commands.
- `extensions/tasks/band_sync_panel.py` - the panel: every component builder and
  `register_action` handler a user clicks, plus `post_or_replace_panel`/`send_dm`,
  called by the poller.

## The panel

One message per event, posted to the channel set by `/fwasync set-channel`
(`fwa_sync_config.panel_channel_id`). `normalize_config` falls back to
`NOTIFICATION_CHANNEL_ID` whenever the stored value is `None` or the key is missing,
not only on a brand-new doc, so an existing config that predates this field still gets
a working panel channel without an admin having to run `/fwasync set-channel` first
(refuter-01 must-fix 3; `0` is the one value that stays "no panel"). Posted by the
poller the first poll it discovers a new event (`process_event`, when the event's
`panel_message_id` is still unset).
Only one panel exists at a time: posting a panel deletes whichever panel is currently
tracked in that channel first, unconditionally - not only when it belonged to a
different event. That panel comes from `fwa_sync_config.current_panel` (`{uid,
channel_id, message_id}`), not the old event's row - `purge_finished_events` deletes
that row long before the next event is discovered days later, so the config singleton
is the only place the id survives to (D013). `fwa_sync_config.current_panel` is
authoritative; the event row's `panel_channel_id`/`panel_message_id` are only a
mirror, kept for convenience on that event's own doc - nothing reads them as the
source of truth for what to delete next.

A BAND time change is handled like a brand new sync (DECISIONS.md D009), not an
in-place edit: `handle_reschedule` (`extensions/tasks/band_sync_ical.py`) keeps the
uid but deletes every DM tracked on its responses, clears `fwa_sync_responses` and
`fwa_sync_deliveries` for that uid, and resets the event row's `panel_message_id`/
`panel_version` to `None` alongside the new `start_at`/`event_version` - clearing
happens before the state write so a crash between the two just repeats the clearing
on the next poll instead of leaving stale answers pinned against the new time.
`process_event`'s "post when `panel_message_id` is unset" branch then posts a fresh
panel with the role ping, deleting the old message for that same uid via
`current_panel` above. No DM is ever sent for a reschedule; a rep who wants a
reminder has to opt back in against the reposted panel. A hand-deleted panel (outside
a reschedule) is reposted once, the next time anything tries to edit it and gets
`NotFoundError`; the new message id replaces the old one on both the event doc and
`current_panel`, and `panel_version` is set there too.

Content (band-sync-panel-restyle, DECISIONS.md D001): a Components V2 Container styled
like band_monitor's old post-monitor panel (red accent, `## ⚔️ War Sync Event has been
posted.`), with a role ping (`create_message(role_mentions=[ALLOWED_ROLE_ID],
user_mentions=True)`, on both the initial post and the NotFound-repost path - same as
the old post-monitor panel), a **Sync Time** line (`<t:...:F>`/`<t:...:R>`), a "Check
FWA Sync Time" link button, the yes/maybe/no legend, and a "Rep Availability" list -
one line per responder, in → maybe → no order - built from `fwa_sync_responses` fresh
on every render (never from memory). The list's char budget is measured against every
other Text already in the container (not hardcoded at 4000 on its own), so a big
roster truncates with "+N more" instead of risking a whole-container 400 on edit; that
edit's BadRequestError/HTTPError is also caught so a button click never crashes.
Row 1: **Yes** / **Maybe** / **No** / **DM Me the Sync Time**
(no separate "Open BAND" button - the link button above already carries that URL).
Row 2: a reminder select, always present. It is rejected ephemerally ("Choose Yes or
Maybe first...") unless the clicker's own response status is in
`band_sync_schema.REMINDER_STATUSES` (`"in"` or `"maybe"`, D007) - components are
per-message, not per-user, so there is no way to hide it from anyone who has not
opted in; the handler is the only gate.

`extensions/tasks/band_monitor.py`'s old post-monitor panel (`send_war_sync_to_discord`)
no longer posts anything of its own - this Container is the only sync panel posted
per event. `band_monitor.on_war_response` and its Container builder are kept only to
keep already-posted legacy panels (posted before this restyle) working; they are not
reachable from any new post.

Every button/select uses a stateless custom_id, `fwa_sync_<action>:<uid>` (one colon,
the BAND event UID as the whole action_id) - no `component_state` row, so the panel
keeps working indefinitely, unlike the 24h-lifetime stateful panels elsewhere in the
bot. An unknown or already-purged uid answers "This sync has passed."

## The DM rule (D001)

One DM per user per event, replaced rather than appended: before sending any DM for
`(uid, user)`, the previous message recorded on that user's `fwa_sync_responses` row
(`dm_channel_id`/`dm_message_id`) is deleted (`NotFoundError` ignored - already gone is
not an error), the new one is sent, and its id is stored. This applies to "DM me the
time" (one-time, no schedule, available without opting in) and opted-in reminders -
the only two DMs that exist. Anyone with a response row gets the interactive DM (the
same Container as the panel, minus the role ping and the Rep Availability list, with
a "**Your response:**" line and the same Yes/Maybe/No/DM Me the Sync Time/reminders
row in their place). A `legacy_broadcast` recipient (`dm_user_ids`, no response row -
see below) still gets the old plain, buttonless embed; they never opted in through the
panel, so there is nowhere to store a replaceable message id for them.

There is no reschedule "change" DM (DECISIONS.md D009 supersedes the old D003 change-
alert behaviour and the earlier restyle's D003 change-DM title): a time change deletes
the panel and every response/delivery for that uid instead, so nobody gets DMed about
it - see the reschedule paragraph above.

"DM Me the Sync Time" never sets a status: a first-time clicker with no response row yet
gets one created with `status: None` (`response.status` is one of `None`/`"in"`/
`"maybe"`/`"no"`) purely so the DM's message id has somewhere to live - it does not
mark them Not going, does not appear in the panel's Rep Availability list, and still
needs an explicit Yes/Maybe/No click to get one (refuter-03 must-fix 3).

Clicking a button inside a DM edits that DM in place and also re-renders the channel
panel (two different messages); a channel click only edits the panel.

### DM auto-delete (D006)

Every sync DM `send_dm` sends deletes itself `DM_TTL_SECONDS` (600s / 10 minutes) after
it is sent, and carries a footer line - `-# This message will be deleted <t:{epoch}:R>` -
as the last `Text` component, placed right after the "**Your response:**" line and
before the Yes/Maybe/No/reminders rows so the buttons a reader clicks stay at the
bottom of the DM. `fwa_sync_responses.dm_delete_at` (a UTC datetime, alongside
`dm_channel_id`/`dm_message_id`) records when. `_render_after_change` re-reads
`dm_delete_at` and passes it back into `dm_container` on every click, so the footer
survives every RSVP/reminder edit of the DM, not just the initial send.

Two independent mechanisms enforce the TTL:
- **In-process timer** - `send_dm` schedules an `asyncio` task
  (`band_sync_panel._schedule_dm_delete`) that sleeps until `dm_delete_at`, then deletes
  the DM only if the response row still holds that exact `dm_message_id` (a newer DM
  replacing it has already deleted the old one and stored its own id). Every scheduled
  task is tracked in a module-level set and cancelled cleanly in
  `band_sync_ical.py`'s `on_bot_stopping` (this module has no listener of its own, so
  the poller module calls `panel.cancel_dm_delete_tasks()` directly).
- **Restart backstop** - `band_sync_ical.sweep_dm_deletions`, called at the end of every
  `poll_once` alongside `purge_finished_events`, finds any response row with
  `dm_delete_at` in the past and `dm_message_id` still set (a bot restart drops every
  pending in-process timer with it) and deletes it there.

Either path unsets the DM tracking fields (`dm_channel_id`/`dm_message_id`/
`dm_delete_at`) only after the delete succeeds or Discord reports the message already
gone (`NotFoundError`); any other exception (rate limit, timeout, ...) leaves the fields
in place so the next `sweep_dm_deletions` pass retries instead of orphaning a DM that is
still live. A response's `status` and `reminders` are untouched either way, so a deleted
DM never changes someone's RSVP or scheduled reminders.

## The reminder rule (D002, superseded in part by D007)

Reminders are selectable once a response's status is `"in"` or `"maybe"`
(`band_sync_schema.REMINDER_STATUSES`) for THAT event - opting in never carries over to
the next sync, and a reschedule (D009) clears it too, so a rep re-opts in against the
reposted panel. Choosing "All" sets `[60, 10, 0]`. Switching between `"in"` and
`"maybe"` keeps the reminders list; only switching to `"no"` clears it. Times are
always Discord timestamps; no per-user timezone is stored anywhere.

Offset `0` ("at sync time", D011) is due only in the ten minutes starting at the
event's start - `due_offsets()` in `utils/band_ical_parser.py` now treats it specially
(never before start, never more than ten minutes late, never twice), and `drop_past()`
keeps an event visible to the poller for the same hour the purge below runs on, so a
poll landing right at start still has the event to act on.

## Config commands (`/fwasync`, ADMINISTRATOR only)

| Command | Effect |
|---|---|
| `enable` / `disable` | Turn the poller's delivery on/off |
| `set-channel` | Set the invoking channel as the panel channel |
| `set-band-url` | Set the "Check FWA Sync Time" link button's fallback URL (`fwa_sync_config.band_url`) - used whenever an event carries no `url` of its own, which is always today (the iCal parser does not extract one) |
| `set-recipients` | Replace the legacy broadcast list (`dm_user_ids`) |
| `set-offsets` | Replace the reminder offsets available config-wide |
| `legacy-broadcast on\|off` | Gate the old fixed-list broadcast (see Deploy note) |
| `status` / `check` / `preview` | Diagnostics; unchanged by this panel |

## Collections and cleanup

Four collections, all declared in `utils/mongo.py`, owned by
`band_sync_schema.py`/`band_sync_ical.py`:

- `fwa_sync_config` - singleton, permanent. Carries `current_panel`
  (`{uid, channel_id, message_id}` or `None`), the durable record of which panel is
  posted - not an event row, since those get purged (D013).
- `fwa_sync_events` - one row per BAND event, now also carrying `panel_channel_id` /
  `panel_message_id`.
- `fwa_sync_responses` - one row per `(uid, user)`, replaced in place on every status
  or reminder change, carrying `dm_channel_id`/`dm_message_id` for the DM-replace rule
  and `dm_delete_at` for the auto-delete TTL (D006, see above).
- `fwa_sync_deliveries` - one row per queued/sent reminder or DM-once delivery.

`purge_finished_events` (in `band_sync_ical.py`, run at the end of every poll) deletes
an event's responses, deliveries, and each response's last DM one hour after the event
started, then the event row itself. **The panel message is never deleted by purge**
(D003) - only the next event's discovery replaces it.

## Deploy note

The migration from the old single `fwa_sync_alerts` collection
(`_migrate_legacy_config`) always sets `legacy_broadcast: False`, so production DMs are
silent until an admin runs `/fwasync legacy-broadcast on` - the flag exists so the
panel can be verified live before the old fixed-list broadcast resumes alongside it.
The old broadcast code itself is intentionally still present (not removed by this
brief); it is retired in a later pass once the panel has run in production.
