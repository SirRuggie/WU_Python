"""Parser and alert-scheduling logic for the BAND FWA sync iCal feeds.

Pure and dependency-light so it can be unit-tested against a captured .ics with no
network call, no Mongo and no Discord (see tests/test_band_ical_parser.py). The async
shell that fetches feeds and sends DMs lives in extensions/tasks/band_sync_ical.py.

Two things here are easy to get wrong and are the reason this module exists separately:

1. BAND emits DTSTART;TZID=Asia/Hong_Kong, not UTC (the admin authors from Hong Kong).
   Resolving that properly instead of reading the digits is what keeps the alert from
   drifting an hour across a DST boundary.
2. Mongo hands datetimes back NAIVE (utils/mongo.py builds the client without
   tz_aware=True) and at millisecond precision, while the feed gives aware datetimes at
   second precision. Comparing the two raw either raises TypeError or reports a phantom
   reschedule on every poll. normalize_start() is the single choke point for both.
"""

from datetime import datetime, timedelta, timezone

import icalendar

# Offset label for the "a new sync just appeared in the feed" alert. Distinct from the
# numeric minute labels ("60", "10") so it can never collide with one.
DISCOVERY_OFFSET = "new"


class BandIcalParseError(Exception):
    """Raised when a payload is not a usable VCALENDAR at all.

    A valid calendar containing zero sync events is NOT an error - that is a normal
    quiet day and is reported by the staleness check instead.
    """


def normalize_start(value):
    """Return an aware UTC datetime truncated to whole seconds, or None.

    Accepts what the feed gives (aware datetime), what Mongo gives back (naive datetime,
    already UTC, millisecond precision), and what an all-day entry gives (a date, which
    has no time and is rejected). Naive input is ASSUMED UTC because the only naive
    source is our own Mongo round-trip.
    """
    if value is None:
        return None
    # A datetime.date is not a datetime, so all-day entries fall out here. Order matters:
    # a datetime IS a date, so this check must be for datetime specifically.
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def is_sync_summary(summary, summary_filter="sync") -> bool:
    """True if this event's SUMMARY looks like an FWA sync.

    Substring match, case-insensitive. An empty filter disables filtering entirely
    rather than matching nothing, so a blank config value cannot silently mute alerts.
    """
    needle = (summary_filter or "").strip().lower()
    if not needle:
        return True
    return needle in (summary or "").lower()


def parse_sync_events(ics_bytes, calendar_label, summary_filter="sync") -> list:
    """Extract matching VEVENTs from one feed's raw body.

    Returns dicts of uid/start/end/summary/calendar, starts normalized to aware UTC and
    sorted earliest first. Raises BandIcalParseError if the body is not a VCALENDAR.

    Recurring events (RRULE) are not expanded - only the master VEVENT is read. BAND
    sync events are posted individually, so there is nothing to expand in practice.
    """
    try:
        cal = icalendar.Calendar.from_ical(ics_bytes)
    except Exception as exc:
        raise BandIcalParseError(f"{calendar_label}: not a parseable VCALENDAR ({exc})") from exc

    events = []
    for component in cal.walk("VEVENT"):
        try:
            start = normalize_start(component.decoded("DTSTART"))
        except (KeyError, ValueError):
            continue
        if start is None:
            continue  # all-day entry or undecodable time

        summary = str(component.get("SUMMARY") or "")
        if not is_sync_summary(summary, summary_filter):
            continue

        uid = str(component.get("UID") or "").strip()
        if not uid:
            continue  # UID is the dedupe key; without it we cannot track state safely

        try:
            end = normalize_start(component.decoded("DTEND"))
        except (KeyError, ValueError):
            end = None

        events.append({
            "uid": uid,
            "start": start,
            "end": end,
            "summary": summary,
            "calendar": calendar_label,
        })

    return sorted(events, key=lambda e: e["start"])


def merge_feeds(*event_lists) -> list:
    """Merge events from several calendars, deduping on UID, earliest start first.

    The same sync can appear on more than one calendar; first occurrence wins, so the
    order feeds are passed in decides which calendar name gets shown.
    """
    seen = {}
    for events in event_lists:
        for event in events or []:
            seen.setdefault(event["uid"], event)
    return sorted(seen.values(), key=lambda e: e["start"])


def drop_past(events, now) -> list:
    """Keep only events that have not started yet.

    Consequence worth knowing: an offset of 0 ("alert at sync time") can never fire,
    because an event reaching its start time is dropped on that same poll. Offsets must
    be > 0 to be meaningful.
    """
    cutoff = normalize_start(now)
    return [e for e in events if e["start"] > cutoff]


def detect_reschedule(stored_start, feed_start) -> bool:
    """True if the feed has moved an event we already have state for.

    Both sides go through normalize_start, which is what makes a naive Mongo value
    comparable to an aware feed value and stops sub-second precision differences from
    reading as a move.
    """
    stored = normalize_start(stored_start)
    fresh = normalize_start(feed_start)
    if stored is None or fresh is None:
        return False
    return stored != fresh


def due_offsets(start, now, claimed, offsets, announce_on_discovery=True, first_seen=None):
    """Decide which alerts to send and which to record without sending.

    Returns (to_send, to_retire) - both lists of offset labels. Everything returned must
    be written to the dedupe collection; only to_send generates a DM. to_retire exists so
    a window that had already passed the first time we saw the event is closed off
    permanently instead of firing late and misleadingly.

    `claimed` is the set of offset labels already recorded for this UID. An empty set
    means we have never seen this event, which is what makes a late first sighting
    distinguishable from a missed poll:

      - never seen before + window already passed -> retire (do not claim it was T-60m
        away when we found it 20 minutes out)
      - seen before + window already passed       -> send, however late (this is the
        missed-poll catch-up, and is why no scheduler misfire setting is needed)

    `first_seen` can be forced True by the caller after a reschedule, so that offsets
    already elapsed against the NEW time are retired rather than fired - the recipients
    were just told the new time by the change alert.
    """
    claimed = set(claimed or ())
    if first_seen is None:
        first_seen = not claimed

    start = normalize_start(start)
    now = normalize_start(now)

    to_send, to_retire = [], []

    if DISCOVERY_OFFSET not in claimed:
        # Always claimed, even when discovery alerts are switched off: the marker doc is
        # what carries start_at, and without it reschedule detection has nothing to
        # compare against until the first offset fires.
        (to_send if announce_on_discovery else to_retire).append(DISCOVERY_OFFSET)

    for minutes in sorted({int(m) for m in offsets or ()}, reverse=True):
        if minutes <= 0:
            continue  # see drop_past(): a non-positive offset can never come due
        label = str(minutes)
        if label in claimed:
            continue
        if now < start - timedelta(minutes=minutes):
            continue  # not due yet
        (to_retire if first_seen else to_send).append(label)

    return to_send, to_retire


def discord_timestamp(value, style="F") -> str:
    """Render an aware datetime as a Discord timestamp tag.

    int(timestamp()) on an aware datetime is timezone-independent, so each recipient
    sees the sync in their own local time with no hardcoded Eastern anywhere.
    """
    moment = normalize_start(value)
    if moment is None:
        return "unknown"
    return f"<t:{int(moment.timestamp())}:{style}>"
