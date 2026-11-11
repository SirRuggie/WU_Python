"""Names, zones, marks and order for World clocks (B-11)."""
from datetime import datetime, timezone

import pytest

from utils import world_clocks as rules

WINTER = datetime(2026, 11, 11, 2, 30, tzinfo=timezone.utc)
SUMMER = datetime(2027, 7, 1, 2, 30, tzinfo=timezone.utc)


def clock(zone, flag="", code=None, **extra):
    return {"zone": zone, "flag": flag, "code": code, **extra}


@pytest.mark.parametrize("zone,flag,winter,summer", [
    ("America/New_York", "🇺🇸", "🇺🇸 EST (GMT-5) · 9:30pm · Tue 10", "🇺🇸 EDT (GMT-4) · 10:30pm · Wed 30"),
    ("America/Chicago", "🇺🇸", "🇺🇸 CST (GMT-6) · 8:30pm · Tue 10", "🇺🇸 CDT (GMT-5) · 9:30pm · Wed 30"),
    ("America/Denver", "🇺🇸", "🇺🇸 MST (GMT-7) · 7:30pm · Tue 10", "🇺🇸 MDT (GMT-6) · 8:30pm · Wed 30"),
    ("America/Los_Angeles", "🇺🇸", "🇺🇸 PST (GMT-8) · 6:30pm · Tue 10", "🇺🇸 PDT (GMT-7) · 7:30pm · Wed 30"),
    ("Europe/London", "🇬🇧", "🇬🇧 GMT · 2:30am · Wed 11", "🇬🇧 BST (GMT+1) · 3:30am · Thu 1"),
    ("Europe/Paris", "🇪🇺", "🇪🇺 CET (GMT+1) · 3:30am · Wed 11", "🇪🇺 CEST (GMT+2) · 4:30am · Thu 1"),
    ("Asia/Kolkata", "🇮🇳", "🇮🇳 IST (GMT+5:30) · 8:00am · Wed 11", "🇮🇳 IST (GMT+5:30) · 8:00am · Thu 1"),
    ("Asia/Manila", "🇵🇭", "🇵🇭 PHT (GMT+8) · 10:30am · Wed 11", "🇵🇭 PHT (GMT+8) · 10:30am · Thu 1"),
    # Southern hemisphere: November is Sydney summer time.
    ("Australia/Sydney", "🇦🇺", "🇦🇺 AEDT (GMT+11) · 1:30pm · Wed 11", "🇦🇺 AEST (GMT+10) · 12:30pm · Thu 1"),
])
def test_names_switch_summer_time_both_ways(zone, flag, winter, summer):
    assert rules.clock_name(clock(zone, flag), WINTER) == winter
    assert rules.clock_name(clock(zone, flag), SUMMER) == summer


def test_us_switch_happens_at_the_real_moment():
    before = datetime(2027, 3, 14, 6, 59, tzinfo=timezone.utc)  # 1:59am EST
    after = datetime(2027, 3, 14, 7, 0, tzinfo=timezone.utc)    # 3:00am EDT
    assert rules.clock_name(clock("America/New_York"), before) == "EST (GMT-5) · 1:59am · Sun 14"
    assert rules.clock_name(clock("America/New_York"), after) == "EDT (GMT-4) · 3:00am · Sun 14"


def test_24_hour_format_and_midnight_noon():
    midnight = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
    assert rules.clock_name(clock("Europe/London"), midnight) == "GMT · 12:00am · Wed 11"
    assert rules.clock_name(clock("Europe/London"), midnight, "24h") == "GMT · 00:00 · Wed 11"
    noon = datetime(2026, 11, 11, 12, 5, tzinfo=timezone.utc)
    assert rules.clock_name(clock("Europe/London"), noon) == "GMT · 12:05pm · Wed 11"


def test_day_is_the_zones_own_day_and_changes_at_local_midnight():
    # Ruggie's examples (2026-11-11 17:12 UTC).
    at = datetime(2026, 11, 11, 17, 12, tzinfo=timezone.utc)
    assert rules.clock_name(clock("America/New_York", "🇺🇸"), at) == "🇺🇸 EST (GMT-5) · 12:12pm · Wed 11"
    assert rules.clock_name(clock("Europe/London", "🇬🇧"), at) == "🇬🇧 GMT · 5:12pm · Wed 11"
    assert rules.clock_name(clock("Australia/Sydney"), at) == "AEDT (GMT+11) · 4:12am · Thu 12"
    before = datetime(2026, 11, 12, 4, 54, tzinfo=timezone.utc)  # 11:54pm EST
    after = datetime(2026, 11, 12, 5, 0, tzinfo=timezone.utc)    # 12:00am EST
    assert rules.clock_name(clock("America/New_York"), before) == "EST (GMT-5) · 11:54pm · Wed 11"
    assert rules.clock_name(clock("America/New_York"), after) == "EST (GMT-5) · 12:00am · Thu 12"
    assert rules.clock_name(clock("America/New_York"), after, "24h") == "EST (GMT-5) · 00:00 · Thu 12"


def test_typed_gmt_code_in_summer_keeps_the_offset():
    assert rules.clock_name(clock("Europe/London", code="GMT"), SUMMER) == "GMT (GMT+1) · 3:30am · Thu 1"


def test_longest_name_fits_the_discord_limit():
    england = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F"
    name = rules.clock_name(clock("Asia/Kathmandu", england, "ABCDEF"), WINTER)
    assert name.endswith("ABCDEF (GMT+5:45) · 8:15am · Wed 11")
    assert len(name) < rules.NAME_LIMIT


def test_numeric_abbreviation_needs_a_typed_code():
    assert rules.auto_code("Asia/Dubai", WINTER) is None
    with pytest.raises(ValueError, match="Type a code"):
        rules.clock_name(clock("Asia/Dubai"), WINTER)
    assert rules.clock_name(clock("Asia/Dubai", "🇦🇪", "GST"), WINTER) == "🇦🇪 GST (GMT+4) · 6:30am · Wed 11"
    assert rules.preview(clock("Asia/Dubai"), WINTER)["needs_code"] is True


def test_negative_half_hour_offset():
    assert rules.offset_label(-rules.timedelta(hours=3, minutes=30)) == "GMT-3:30"
    assert rules.offset_label(rules.timedelta(hours=5, minutes=45)) == "GMT+5:45"


def test_validate_rejects_bad_input_and_keeps_auto_code():
    with pytest.raises(ValueError):
        rules.validate_clock({"zone": "Mars/Base"}, WINTER)
    with pytest.raises(ValueError):
        rules.validate_clock({"zone": "EST5EDT"}, WINTER)
    with pytest.raises(ValueError, match="2 to 6 letters"):
        rules.validate_clock({"zone": "America/New_York", "code": "E1"}, WINTER)
    with pytest.raises(ValueError, match="flag"):
        rules.validate_clock({"zone": "America/New_York", "flag": "<@123>"}, WINTER)
    with pytest.raises(ValueError, match="flag"):
        rules.validate_clock({"zone": "America/New_York", "flag": "USA"}, WINTER)
    with pytest.raises(ValueError):
        rules.validate_clock("not a dict", WINTER)
    # Typing today's own code keeps it automatic, so summer time still switches.
    assert rules.validate_clock({"zone": "America/New_York", "code": "est"}, WINTER)["code"] is None
    assert rules.validate_clock({"zone": "America/New_York", "code": "ET"}, WINTER)["code"] == "ET"


def test_marks_for_6_and_10_minutes():
    now = datetime(2026, 11, 11, 2, 41, 59, tzinfo=timezone.utc)
    assert rules.mark(now, 6) == datetime(2026, 11, 11, 2, 36, tzinfo=timezone.utc)
    assert rules.next_mark(now, 6) == datetime(2026, 11, 11, 2, 42, tzinfo=timezone.utc)
    assert rules.mark(now, 10) == datetime(2026, 11, 11, 2, 40, tzinfo=timezone.utc)
    late = datetime(2026, 11, 11, 23, 59, tzinfo=timezone.utc)
    assert rules.next_mark(late, 6) == datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)


def test_sort_by_offset_lowest_first():
    clocks = [clock(zone, _id=zone) for zone in
              ("Australia/Sydney", "Europe/London", "America/Los_Angeles", "Asia/Kolkata", "America/New_York")]
    assert [c["zone"] for c in rules.sort_clocks(clocks, WINTER)] == [
        "America/Los_Angeles", "America/New_York", "Europe/London", "Asia/Kolkata", "Australia/Sydney"]


def test_positions_move_only_clock_channels_inside_their_own_slots():
    clocks = [clock("Australia/Sydney", channel_id="1"), clock("America/New_York", channel_id="2"),
              clock("Europe/London", channel_id="3")]
    channels = {
        "1": {"position": 2, "parent_id": "9"},
        "2": {"position": 5, "parent_id": "9"},
        "3": {"position": 7, "parent_id": "9"},
        "4": {"position": 3, "parent_id": "9"},  # Statbot channel: never moves.
    }
    changes = rules.positions_for(clocks, channels, WINTER)
    assert changes == {"2": 2, "3": 5, "1": 7}
    assert "4" not in changes
    for channel_id, position in changes.items():
        channels[channel_id]["position"] = position
    assert rules.positions_for(clocks, channels, WINTER) == {}


def test_positions_skip_duplicate_slots_and_other_categories():
    clocks = [clock("Australia/Sydney", channel_id="1"), clock("America/New_York", channel_id="2")]
    assert rules.positions_for(clocks, {"1": {"position": 1, "parent_id": "9"},
                                        "2": {"position": 1, "parent_id": "9"}}, WINTER) == {}
    assert rules.positions_for(clocks, {"1": {"position": 1, "parent_id": "8"},
                                        "2": {"position": 0, "parent_id": "9"}}, WINTER) == {}


def test_preview_gives_the_other_half_of_the_year():
    result = rules.preview(clock("America/New_York", "🇺🇸"), WINTER)
    assert result["name_now"] == "🇺🇸 EST (GMT-5) · 9:30pm · Tue 10"
    assert result["name_other"] == "🇺🇸 EDT (GMT-4)"
    assert rules.preview(clock("Asia/Kolkata"), WINTER)["name_other"] is None


def test_flags_from_zone_table_and_overrides():
    assert rules.flag_for("Europe/Paris") == "🇪🇺"
    if rules._zone_countries():
        assert rules.flag_for("America/New_York") == "🇺🇸"
        assert rules.flag_for("Asia/Manila") == "🇵🇭"


def test_chip_zones_are_valid():
    for _label, zone in rules.CHIPS:
        rules.zone_info(zone)


def test_positions_skip_when_another_channel_shares_a_clock_slot():
    # Sydney (3, id 200), Statbot (3, id 250), Los Angeles (5, id 300). Swapping the
    # clocks would move Statbot too, so nothing moves.
    clocks = [clock("Australia/Sydney", channel_id="200"), clock("America/Los_Angeles", channel_id="300")]
    channels = {"200": {"position": 3, "parent_id": "9"}, "250": {"position": 3, "parent_id": "9"},
                "300": {"position": 5, "parent_id": "9"}}
    assert rules.positions_for(clocks, channels, WINTER) == {}
    channels["250"]["parent_id"] = "8"  # In another category it does not matter.
    assert rules.positions_for(clocks, channels, WINTER) == {"300": 3, "200": 5}


def test_typed_gmt_code_keeps_a_non_zero_offset():
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert rules.zone_label({"zone": "Europe/London", "flag": "", "code": "GMT"}, summer) == "GMT (GMT+1)"
    assert rules.zone_label({"zone": "Europe/London", "flag": "", "code": None}, WINTER) == "GMT"


@pytest.mark.parametrize("flag", ["\u202e", "🇺🇸\u200b", "\u2066🇺🇸", "\x00"])
def test_flag_rejects_invisible_and_direction_characters(flag):
    with pytest.raises(ValueError):
        rules.validate_clock({"zone": "America/New_York", "flag": flag, "code": None}, WINTER)


@pytest.mark.parametrize("flag", ["🏴\u200d☠\ufe0f", "🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f"])
def test_flag_keeps_joiner_sequences_and_subdivision_flags(flag):
    assert rules.validate_clock({"zone": "America/New_York", "flag": flag, "code": None}, WINTER)["flag"] == flag


@pytest.mark.parametrize("zone, codes", [
    ("America/New_York", ["EST", "EDT"]), ("America/Los_Angeles", ["PST", "PDT"]),
    ("Europe/London", ["GMT", "BST"]), ("Asia/Manila", ["PHT"]), ("Asia/Kolkata", ["IST"]),
    ("Australia/Sydney", ["AEDT", "AEST"]), ("Asia/Dubai", ["GST"]), ("America/Sao_Paulo", ["BRT"]),
    ("Asia/Kathmandu", []),
])
def test_zone_codes_cover_both_halves_of_the_year(zone, codes):
    assert rules.zone_codes(zone, WINTER) == codes
