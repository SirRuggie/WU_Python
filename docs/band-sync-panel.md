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
(`fwa_sync_config.panel_channel_id`). Posted by the poller the first poll it discovers
a new event (`process_event`, when the event's `panel_message_id` is still unset).
Only one panel exists at a time: posting a new event's panel deletes whichever other
event's panel is currently in that channel first (events never overlap across the
three BAND feeds - D003 in `.claude/scratch/band-sync-panel/DECISIONS.md`). That
panel comes from `fwa_sync_config.current_panel` (`{uid, channel_id,
message_id}`), not the old event's row - `purge_finished_events` deletes that row
long before the next event is discovered days later, so the config singleton is the
only place the id survives to (D013). `fwa_sync_config.current_panel` is authoritative;
the event row's `panel_channel_id`/`panel_message_id` are only a mirror, kept for
convenience on that event's own doc - nothing reads them as the source of truth for
what to delete next.

Once posted, the panel is edited in place whenever the event row's `panel_version`
lags its `event_version` - most often a reschedule, which changes `event_version`
without touching `panel_message_id`. `process_event` checks this on every poll (not
only right after a detected reschedule), so an edit that raised, or a bot restart
between the reschedule's Mongo write and the edit, simply retries on the next poll
instead of leaving the panel on the old time forever; `panel_version` is only set to
the new `event_version` after the REST call actually succeeds. A hand-deleted panel is
reposted once, the next time anything tries to edit it and gets `NotFoundError`; the
new message id replaces the old one on both the event doc and `current_panel`, and
`panel_version` is set there too.

Content: the sync summary, start time as `<t:...:F>`/`<t:...:R>`, then three lists -
Going / Maybe / Not going - built from `fwa_sync_responses` fresh on every render
(never from memory). Row 1: **Opt in** / **Maybe** / **Deny** / **Open BAND** (link) /
**DM me the time**. Row 2: a reminder select, always present. It is rejected
ephemerally ("Opt in first...") unless the clicker's own response status is `"in"` -
components are per-message, not per-user, so there is no way to hide it from anyone
who has not opted in; the handler is the only gate.

Every button/select uses a stateless custom_id, `fwa_sync_<action>:<uid>` (one colon,
the BAND event UID as the whole action_id) - no `component_state` row, so the panel
keeps working indefinitely, unlike the 24h-lifetime stateful panels elsewhere in the
bot. An unknown or already-purged uid answers "This sync has passed."

## The DM rule (D001)

One DM per user per event, replaced rather than appended: before sending any DM for
`(uid, user)`, the previous message recorded on that user's `fwa_sync_responses` row
(`dm_channel_id`/`dm_message_id`) is deleted (`NotFoundError` ignored - already gone is
not an error), the new one is sent, and its id is stored. This applies to "DM me the
time" (one-time, no schedule, available without opting in), opted-in reminders, and
reschedule "change" alerts - anyone with a response row gets the interactive DM
(status line + the same Opt in/Maybe/Deny/Open BAND/reminders as the panel). A
`legacy_broadcast` recipient (`dm_user_ids`, no response row - see below) still gets
the old plain, buttonless embed; they never opted in through the panel, so there is
nowhere to store a replaceable message id for them.

"DM me the time" never sets a status: a first-time clicker with no response row yet
gets one created with `status: None` (`response.status` is one of `None`/`"in"`/
`"maybe"`/`"no"`) purely so the DM's message id has somewhere to live - it does not
mark them Not going, does not appear in any of the panel's three lists, and still
needs an explicit Opt in/Maybe/Deny click to get one (refuter-03 must-fix 3).

Clicking a button inside a DM edits that DM in place and also re-renders the channel
panel (two different messages); a channel click only edits the panel.

## The reminder rule (D002)

Reminders are only selectable once a response's status is `"in"` for THAT event -
opting in never carries over to the next sync. Choosing "All" sets `[60, 10, 0]`.
Changing status away from `"in"` (Maybe/Deny) clears the reminders list. Times are
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
| `set-band-url` | Set the Open BAND link button's fallback URL (`fwa_sync_config.band_url`) - used whenever an event carries no `url` of its own, which is always today (the iCal parser does not extract one) |
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
  or reminder change, carrying `dm_channel_id`/`dm_message_id` for the DM-replace rule.
- `fwa_sync_deliveries` - one row per queued/sent reminder or change alert.

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
