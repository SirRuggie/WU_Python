"""Tests for the BAND sync iCal parser, against a real captured feed body.

The VEVENT below is the Sync3 feed exactly as BAND served it (verified by hand: no
cookies, no auth, HTTP 200). 18:20 Asia/Hong_Kong is 10:20Z is 6:20 AM EDT, which
matched the BAND app. That conversion is the whole point of this module, so it is
asserted against the real capture rather than a hand-built datetime.
"""

from datetime import datetime, timedelta, timezone

import pytest

from utils.band_ical_parser import (
    DISCOVERY_OFFSET,
    BandIcalParseError,
    detect_reschedule,
    discord_timestamp,
    drop_past,
    due_offsets,
    is_sync_summary,
    merge_feeds,
    normalize_start,
    parse_sync_events,
)

FIXTURE = b"""BEGIN:VCALENDAR
PRODID:-//Naver Corp.//BAND Calendar 1.0.0//EN
VERSION:2.0
CALSCALE:GREGORIAN
X-PUBLISHED-TTL:PT5M
BEGIN:VTIMEZONE
TZID:Asia/Hong_Kong
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:+0800
TZOFFSETTO:+0800
TZNAME:HKT
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
SUMMARY:\xe2\x9a\x80\xe2\x9a\x80Tie Breaker High Sync \xe2\x9e\xa1\xef\xb8\x8fClosest to Z wins
DTSTART;TZID=Asia/Hong_Kong:20260803T182000
DTEND;TZID=Asia/Hong_Kong:20260803T190000
UID:4/71428305/1006326105/19700101@band.us
END:VEVENT
END:VCALENDAR
"""

# An all-day band-anniversary entry (the UID type 8 noise the calendar export returns)
# plus a non-sync titled event, to prove both are filtered out.
NOISE = b"""BEGIN:VCALENDAR
PRODID:-//Naver Corp.//BAND Calendar 1.0.0//EN
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Band Anniversary
DTSTART;VALUE=DATE:20260803
UID:8/71428305/1/19700101@band.us
END:VEVENT
BEGIN:VEVENT
SUMMARY:Clan meeting
DTSTART;TZID=Asia/Hong_Kong:20260803T200000
UID:6/71428305/999/19700101@band.us
END:VEVENT
END:VCALENDAR
"""

SYNC_START = datetime(2026, 8, 3, 10, 20, tzinfo=timezone.utc)
SYNC_UID = "4/71428305/1006326105/19700101@band.us"


# ---- parsing ----

def test_hong_kong_start_resolves_to_utc():
    # The regression this module exists to prevent: 18:20 HKT must become 10:20Z via a
    # real timezone, never by reading the digits.
    events = parse_sync_events(FIXTURE, "Sync3")
    assert len(events) == 1
    assert events[0]["start"] == SYNC_START
    assert events[0]["end"] == datetime(2026, 8, 3, 11, 0, tzinfo=timezone.utc)


def test_extracts_uid_summary_and_calendar():
    event = parse_sync_events(FIXTURE, "Sync3")[0]
    assert event["uid"] == SYNC_UID          # the dedupe key
    assert event["calendar"] == "Sync3"
    assert "Tie Breaker High Sync" in event["summary"]


def test_all_day_and_non_sync_events_are_dropped():
    assert parse_sync_events(NOISE, "Sync") == []


def test_valid_calendar_with_no_syncs_is_not_an_error():
    # A quiet day is normal, not a parse failure - the staleness check covers it.
    assert parse_sync_events(b"BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n", "Sync") == []


def test_garbage_body_raises():
    with pytest.raises(BandIcalParseError):
        parse_sync_events(b"<html>404 not found</html>", "Sync3")


@pytest.mark.parametrize("summary,filt,expected", [
    ("⚀⚀Tie Breaker High Sync ➡️", "sync", True),
    ("TIE BREAKER HIGH SYNC", "sync", True),
    ("Clan meeting", "sync", False),
    ("anything at all", "", True),      # empty filter disables filtering
    ("anything at all", "   ", True),
    (None, "sync", False),
])
def test_is_sync_summary(summary, filt, expected):
    assert is_sync_summary(summary, filt) is expected


# ---- normalization / the Mongo round-trip trap ----

@pytest.mark.parametrize("value,expected", [
    (datetime(2026, 8, 3, 10, 20, tzinfo=timezone.utc), SYNC_START),
    (datetime(2026, 8, 3, 10, 20), SYNC_START),                        # naive from Mongo
    (datetime(2026, 8, 3, 10, 20, 0, 123000, tzinfo=timezone.utc), SYNC_START),  # ms trunc
    (None, None),
    (datetime(2026, 8, 3, 10, 20).date(), None),                       # all-day
])
def test_normalize_start(value, expected):
    assert normalize_start(value) == expected


@pytest.mark.parametrize("stored,feed,expected", [
    (SYNC_START, SYNC_START, False),
    (datetime(2026, 8, 3, 10, 20), SYNC_START, False),                 # naive vs aware
    (datetime(2026, 8, 3, 10, 20, 0, 400000), SYNC_START, False),      # sub-second drift
    (SYNC_START, SYNC_START + timedelta(hours=2), True),               # genuine move
    (SYNC_START, SYNC_START - timedelta(minutes=30), True),            # moved earlier
    (None, SYNC_START, False),
])
def test_detect_reschedule(stored, feed, expected):
    assert detect_reschedule(stored, feed) is expected


# ---- merge / filter ----

def test_merge_dedupes_on_uid_across_calendars():
    a = parse_sync_events(FIXTURE, "Sync")
    b = parse_sync_events(FIXTURE, "Sync3")
    merged = merge_feeds(a, b)
    assert len(merged) == 1
    assert merged[0]["calendar"] == "Sync"      # first feed wins


def test_drop_past():
    events = parse_sync_events(FIXTURE, "Sync3")
    assert drop_past(events, SYNC_START - timedelta(minutes=1)) == events
    assert drop_past(events, SYNC_START) == []              # starting now is past
    assert drop_past(events, SYNC_START + timedelta(hours=1)) == []


# ---- alert scheduling ----

OFFSETS = [60, 10]


def test_first_sighting_far_out_sends_discovery_only():
    send, retire = due_offsets(SYNC_START, SYNC_START - timedelta(hours=8), set(), OFFSETS)
    assert send == [DISCOVERY_OFFSET]
    assert retire == []


def test_discovery_disabled_still_claims_the_marker():
    # The marker doc must exist regardless, or reschedule detection has no anchor.
    send, retire = due_offsets(SYNC_START, SYNC_START - timedelta(hours=8), set(), OFFSETS,
                               announce_on_discovery=False)
    assert send == []
    assert retire == [DISCOVERY_OFFSET]


def test_first_sighting_inside_a_window_retires_the_elapsed_offset():
    # Found 20 minutes out: T-60m already passed, so it is closed off rather than fired.
    send, retire = due_offsets(SYNC_START, SYNC_START - timedelta(minutes=20), set(), OFFSETS)
    assert send == [DISCOVERY_OFFSET]
    assert retire == ["60"]


def test_known_event_fires_offset_when_due():
    claimed = {DISCOVERY_OFFSET}
    send, retire = due_offsets(SYNC_START, SYNC_START - timedelta(minutes=59), claimed, OFFSETS)
    assert send == ["60"]
    assert retire == []


def test_missed_poll_fires_late_rather_than_dropping():
    # Bot was down through the whole T-60m window; both offsets are overdue and both
    # still fire. This is the catch-up that replaces a scheduler misfire_grace_time.
    claimed = {DISCOVERY_OFFSET}
    send, retire = due_offsets(SYNC_START, SYNC_START - timedelta(minutes=5), claimed, OFFSETS)
    assert send == ["60", "10"]     # descending: longest lead first
    assert retire == []


def test_already_claimed_offsets_never_refire():
    claimed = {DISCOVERY_OFFSET, "60", "10"}
    send, retire = due_offsets(SYNC_START, SYNC_START - timedelta(minutes=1), claimed, OFFSETS)
    assert send == []
    assert retire == []


def test_reschedule_forces_elapsed_offsets_to_retire():
    # After a change alert, an offset already elapsed against the NEW time must not also
    # fire - the recipients were just told the new time.
    claimed = {DISCOVERY_OFFSET}
    send, retire = due_offsets(SYNC_START, SYNC_START - timedelta(minutes=30), claimed, OFFSETS,
                               first_seen=True)
    assert send == []
    assert retire == ["60"]


@pytest.mark.parametrize("offsets", [[0], [-5], [0, -1]])
def test_non_positive_offsets_are_ignored(offsets):
    send, retire = due_offsets(SYNC_START, SYNC_START - timedelta(minutes=1),
                               {DISCOVERY_OFFSET}, offsets)
    assert send == []
    assert retire == []


def test_duplicate_offsets_collapse():
    claimed = {DISCOVERY_OFFSET}
    send, _ = due_offsets(SYNC_START, SYNC_START - timedelta(minutes=5), claimed, [60, 60, 10])
    assert send == ["60", "10"]


# ---- rendering ----

def test_discord_timestamp_is_utc_epoch():
    # 2026-08-03T10:20:00Z. Derivation, so a future reader can check it without running
    # anything: 2026-01-01T00:00:00Z = 1767225600; Aug 3 is day-of-year 215 in a
    # non-leap year, so 214 elapsed days = 18489600s; 10:20 = 37200s.
    assert discord_timestamp(SYNC_START) == "<t:1785752400:F>"
    assert discord_timestamp(SYNC_START, "R") == "<t:1785752400:R>"
    # Naive Mongo value renders identically - no drift across the round trip.
    assert discord_timestamp(datetime(2026, 8, 3, 10, 20)) == "<t:1785752400:F>"


def test_discord_timestamp_handles_missing_value():
    assert discord_timestamp(None) == "unknown"
