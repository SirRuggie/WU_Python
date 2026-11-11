# World clocks

WU Wizard renames voice channels so their names show local times, for example
`🇺🇸 EST GMT-5 · 9:30pm`. It replaces the Statbot clocks (backlog B-11).
Staff manage the clocks on the dashboard at Bot → World clocks
(`/settings/world-clocks`). The page needs the `server_tools` permission.

## Files

| Part | File |
| --- | --- |
| Name rules (pure, no I/O) | `utils/world_clocks.py` |
| Storage owner | `utils/world_clock_store.py` |
| Rename task | `extensions/tasks/world_clocks.py` (in `main.py` explicit extensions) |
| Dashboard API | `cwl_web/world_clocks.py` (section `world_clocks`, scope `server_tools`) |
| Page | `web/cwl/src/worldClocks/` |
| Tests | `tests/test_world_clocks.py`, `tests/test_world_clock_task.py`, `tests/test_cwl_web_world_clocks.py`, `web/cwl/src/worldClocks/WorldClocksWorkspace.test.tsx` |

The task and the API share `utils/`. Neither imports the other, and `utils/`
does not import `cwl_web/` (the task test checks this).

The unique index on `world_clocks.channel_id` is created by the store before
every add and every channel change, not only when the task starts.

## Channel name

`flag CODE GMT±n · time`. No city names.

- The code comes from the zone's abbreviation (`zoneinfo`), so summer time
  changes by itself. Overrides: `Asia/Manila` uses `PHT` (zoneinfo says `PST`).
- A zone whose abbreviation is numeric (for example Dubai `+04`) has no code.
  Staff must type one (2–6 capital letters) before it renames. Status: "Type a
  code for this time zone."
- A typed code equal to the automatic code is stored as automatic, so it
  follows summer time.
- Offset label: `GMT` for zero, `GMT+5:30` for half hours. A code of `GMT`
  drops the offset only when the offset is zero, so a typed `GMT` on London in
  summer shows `GMT GMT+1`.
- Time format: `9:30pm` (12h, default) or `21:30` (24h), one setting for all.
- Flag: from `zone.tab`, with Paris/Berlin/Amsterdam as 🇪🇺. Staff can change
  it. The flag may not contain letters, digits, `@ # < > \``, or invisible and
  direction characters (Unicode Cc, Cf, Zl, Zp, except the zero-width joiner
  that emoji sequences need and the tag characters of the England, Scotland and
  Wales flags), so a name cannot mention anyone or render
  scrambled.

## Storage (Mongo, majority write concern)

| Collection | Content |
| --- | --- |
| `world_clock_settings` | One row `_id: "settings"`: `category_id`, `time_format`, `interval_minutes` (int 6 or 10; anything else reads as 6), `version` |
| `world_clocks` | One row per clock: `zone`, `flag`, `code`, `channel_id` (unique when set), `enabled`, `version`, last result fields |
| `world_clock_requests` | Receipts for "Create channel and add", keyed by request id |
| `world_clock_runs` | One row per task run, pruned after 7 days |

Every staff write checks `version` (the API calls it `revision`). A mismatch
returns 409 and the page reloads with a message. The task writes only the
result fields (`last_name`, `last_renamed_at`, `status`, `status_detail`,
`checked_at`) and only if the clock `version` is unchanged, so it never
overwrites a newer staff edit.

## Rename task

- Runs at fixed UTC marks: every 6 minutes (:00, :06 … :54) by default, or 10.
  It sleeps to the next mark plus 2 seconds.
- Discord allows about 2 renames per channel in 10 minutes. This number is
  not published (inference from observed behavior), which is why 5 minutes is
  not offered.
- Renames only when the name differs from the current channel name.
- No fast retry. A rate limit (429) or a failed call waits for the next mark.
- Each Discord call has a 20-second timeout.
- Off clocks are not renamed. The name stays as it was ("Off · frozen as …").
- Before each rename the task reads the clock again. A clock that staff turned
  off, removed or edited during the run is skipped (`skipped` in the run row).
- If the channel list cannot be read (Discord down), the run row has
  `discord_unavailable: true` and nothing is renamed. Recent updates shows it.
- Missing channel, no permission or missing code becomes a problem status on
  the page. Nothing is created or deleted by the task.
- Order: clocks are sorted by GMT offset, lowest first. The task moves only its
  own clock channels, only within positions they already hold, only within one
  parent category. It never moves Statbot or other channels.
- Audit log reason: "World clocks update".

## Dashboard API (`/api/cwl/manage/world-clocks`)

| Method | Path | Use |
| --- | --- | --- |
| GET | `` | Settings, clocks, categories, voice channels, chips, next update, recent runs |
| GET | `/zones` | Zone list for the search, with each zone's letter codes now and in the other half of the year (`codes`, for example `["CST", "CDT"]`) |
| POST | `/preview` | Name now and in the other half of the year |
| PUT | `/settings` | Category, time format, interval |
| POST | `` | Add a clock (`mode: create` or `existing`, `request_id` UUID) |
| PATCH | `/{clock_id}` | On/Off switch, saves at once |
| PUT | `/{clock_id}` | Save zone, flag, code, channel |
| DELETE | `/{clock_id}` | Delete the clock's voice channel in Discord, then remove the clock (see Remove below) |

"Create channel and add" creates a voice channel in the selected category and
copies the category's permission overwrites. A receipt keyed by the request id
makes a second press safe:

- Created before: returns the same clock.
- Channel created but clock not saved: the second press saves the clock for
  that channel. It does not create another channel.
- Discord did not confirm the create (timeout): the receipt is `uncertain`, the
  API returns 503, and later presses with that id return 409 without calling
  Discord. Staff check the category and, if the channel is there, add it with
  "Use an existing voice channel". The page keeps the id after a network
  error, any 5xx or a 409, and makes a new id only after a 400, 403 or 404
  (a definite refusal: no channel was made).
- A receipt still `creating` after 15 minutes (for example the web process
  restarted mid-create) is answered like `uncertain`.
- Discord refused (for example 429 or missing permission): the receipt is
  `failed`. A 429 returns 503, so the page keeps the id and the next press
  tries again with it. A missing permission returns 400, so the page makes a
  new id.
- While any create in the same category is `creating` or `uncertain` and less
  than 15 minutes old, a new request id is refused with 409. After 15 minutes
  it stops blocking. This covers a page
  that closed the sheet and made a new id. Adding an existing channel still
  works.
- A Discord 403 on create returns 400, never 403, because the page treats 403
  as "dashboard access changed".

A full category (50 channels) is refused before any Discord call. Maximum 25
clocks.

## Page behavior

- Zone search matches city, country, region, offset and code (EST, EDT, CST,
  CDT, PST, GMT, BST, PHT …). Zones whose code equals the typed word come
  first, and the 12 chip cities lead each group, so "CST" shows Chicago first.
  Search-only codes fill common zones where tzdata has only a number (BRT for
  São Paulo, GST for Dubai, SGT for Singapore); those zones still need a typed
  code for the channel name.
- Time zone, "New channels go in" (Settings) and both voice channel fields
  (Add clock and the clock edit panel) use the shared `SearchPicker`
  (`web/cwl/src/SearchPicker.tsx`, pilot for the dashboard-wide dropdown
  change, 2026-11-11). The closed field shows the selected value with its
  icon and second line. On a phone (700 px or less) the list opens as a
  full-screen sheet sized to the visible area above the keyboard
  (`visualViewport`); on wider screens it opens under the field and moves the
  content down. With an empty search the time zone list shows the chip cities.
  A voice channel that already has a clock shows "has a clock" and cannot be
  selected. Selecting only changes the draft; nothing saves until Save.

- Each On/Off switch saves at once. A failed switch goes back and shows the
  error.
- An open clock has its own Save. Changes show at the next update. There is no
  "Update now".
- Remove asks first (red confirm that names the channel) and fully removes:
  it deletes the clock's voice channel in Discord, then the clock (Ruggie,
  2026-11-11, replacing D6 "channel stays"). To keep the channel, turn the
  clock Off instead.
- Remove rules: the revision is checked before any Discord call. The channel is
  read first and deleted only if it is a voice channel in this server;
  anything else is kept and reported. A channel that is already gone still
  removes the clock. If Discord refuses or does not confirm the delete (403,
  429, timeout, 5xx), the clock is not removed and the page shows why, so the
  next press tries again.
- A clock with a problem shows a red switch, a message and a Fix button.
- Raw Discord IDs are never shown.

## Rollout (D10, Ruggie 2026-11-10)

After release, Ruggie creates the new clock channels himself from the page,
checks that they update, then turns off the Statbot clocks and deletes the old
channels himself. No Discord changes are made for him as part of the build.
