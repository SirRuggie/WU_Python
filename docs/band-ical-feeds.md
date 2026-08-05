# BAND iCal feeds — why the Open API was not enough

## The problem

FWA sync times are posted in BAND as **calendar events**, not as text in a post
body. The existing post-text monitor (`extensions/tasks/band_monitor.py`, which
uses the BAND Open API at `https://openapi.band.us/v2/band/posts`) therefore
**cannot see the actual sync timestamp** — it can read the post, but the time
that matters is not in it.

The Open API surfaces posts, albums and comments. It does not expose the band's
calendar events, so no amount of post polling gets the sync time.

## The solution

Per-calendar **iCal subscription feeds**. Each BAND calendar publishes its own
feed URL; three are consumed (`Sync`, `Sync2`, `Sync3`), configured via
environment variables `BAND_ICAL_SYNC1` / `2` / `3`
(`extensions/tasks/band_sync_ical.py`).

Parsing is in `utils/band_ical_parser.py`. It uses the `icalendar` package
deliberately, so `DTSTART;TZID=Asia/Hong_Kong` resolves against a real timezone
database rather than being read as digits — that is what stops sync alerts
drifting an hour across a DST boundary. On slim containers this needs system
tzdata; a `ZoneInfoNotFoundError` in the logs means `pip install tzdata`.

## The feed URLs are credentials

**A feed URL grants unauthenticated read access to that calendar.** Treat them
exactly like secrets:

- read from the environment only,
- never committed,
- never copied into Mongo.

This is stated at the top of `band_sync_ical.py` and is easy to violate by
accident, because a URL does not look like a password.

## Operational notes

- BAND publishes `X-PUBLISHED-TTL:PT5M`. `POLL_SECONDS_FLOOR = 300` enforces
  never polling faster than that.
- Feed order matters: the first feed carrying a UID decides which calendar name
  is displayed.
- Event timing and notification delivery are separate durable records. Each
  `(event version, offset, recipient)` has its own queued/pending/sent state and
  a ten-minute lease. A failed recipient retries without duplicating DMs to
  recipients who already succeeded; a pending lease can be reclaimed after a
  crash.
- A reschedule queues per-recipient change notifications before advancing the
  stored event time. If no recipients are configured, the old timing remains so
  the reschedule is detected again instead of being silently consumed.
- Recipient IDs are stored once each in configured order. Older global claim
  documents are migrated as already-seen offsets so deployment does not replay
  historical alerts.
- **The task ships disabled.** The config document is seeded with
  `enabled=False` on first run regardless of the `SYNC_DM_ENABLED` seed value,
  and only if the document does not already exist. Turn it on from Discord with
  `/fwasync enable` once the feeds check out.
- It shares no state, schedule or collection with `band_monitor.py`. The two are
  independent by design.

## Related

- [lightbulb-context-api.md](lightbulb-context-api.md) — `/fwasync check`
  originally inherited the `edit_last_response` bug from `band_monitor.py`.
- [deployment.md](deployment.md) — where `.env` lives.
