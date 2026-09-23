import copy

import pendulum
import pytest

from utils import cwl_campaign, cwl_sequence


def configured(**overrides):
    values = {
        "mode": "evenly", "count": 4, "interval_hours": 48,
        "final_hours": 3, "min_gap_hours": 3,
    }
    values.update(overrides)
    return cwl_sequence.configure(cwl_campaign.default_campaign(), **values)


def test_configure_is_independent_and_provisions_ten_numbered_slots():
    original = cwl_campaign.default_campaign()
    original_snapshot = copy.deepcopy(original)
    reminder_five = original["messages"]["reminder:5"]

    result = cwl_sequence.configure(original, "evenly")

    assert original == original_snapshot
    assert len(result["messages"]) == 12
    assert set(cwl_sequence.REMINDER_IDS) <= set(result["messages"])
    assert result["reminder_sequence"] == {
        "enabled": True, "mode": "evenly", "count": 4,
        "interval_hours": 48, "final_hours": 3, "min_gap_hours": 3,
    }
    # Existing authored slots remain byte-for-byte equivalent.
    assert result["messages"]["reminder:5"] == reminder_five
    # New slots copy delivery/artwork/buttons but get a neutral identity.
    six = result["messages"]["reminder:6"]
    assert six["variants"]["main"]["media_url"] == reminder_five["variants"]["main"]["media_url"]
    assert six["variants"]["lazy"]["destination_channel_id"] == reminder_five["variants"]["lazy"]["destination_channel_id"]
    assert six["variants"]["main"]["buttons"] == reminder_five["variants"]["main"]["buttons"]
    assert six["variants"]["main"]["title"] == "CWL Sign-up Reminder #6"
    assert six["schedule"] == {"mode": "manual"}


def test_evenly_spaces_requested_count_between_opening_and_final_call():
    campaign = configured(mode="evenly", count=4)
    opening = pendulum.datetime(2026, 10, 20, 17, tz="America/New_York")
    deadline = pendulum.datetime(2026, 10, 29, 17, tz="America/New_York")

    result = cwl_sequence.plan(campaign, opening, deadline)

    final = deadline.in_timezone("UTC").subtract(hours=3)
    usable_seconds = final.timestamp() - opening.in_timezone("UTC").timestamp()
    for number in range(1, 5):
        expected = opening.in_timezone("UTC").add(seconds=usable_seconds * number / 4)
        assert result[f"reminder:{number}"].in_timezone("UTC") == expected
    assert all(result[f"reminder:{number}"] is None for number in range(5, 11))


def test_interval_repeats_strictly_before_final_then_appends_final():
    campaign = configured(mode="interval", interval_hours=48)
    opening = pendulum.datetime(2026, 10, 20, 17, tz="America/New_York")
    deadline = pendulum.datetime(2026, 10, 29, 17, tz="America/New_York")

    result = cwl_sequence.plan(campaign, opening, deadline)
    expected = [
        opening.add(hours=48), opening.add(hours=96), opening.add(hours=144),
        opening.add(hours=192), deadline.subtract(hours=3),
    ]
    assert [result[f"reminder:{number}"] for number in range(1, 6)] == expected
    assert result["reminder:6"] is None


def test_interval_removes_a_near_final_occurrence_instead_of_bunching():
    campaign = configured(
        mode="interval", interval_hours=48, final_hours=3, min_gap_hours=3,
    )
    opening = pendulum.datetime(2026, 1, 1, 0, tz="UTC")
    deadline = pendulum.datetime(2026, 1, 5, 5, tz="UTC")

    result = cwl_sequence.plan(campaign, opening, deadline)

    assert result["reminder:1"] == opening.add(hours=48)
    assert result["reminder:2"] == deadline.subtract(hours=3)
    assert result["reminder:3"] is None


def test_evenly_rejects_a_window_that_cannot_hold_minimum_gaps():
    campaign = configured(mode="evenly", count=4, final_hours=3, min_gap_hours=3)
    opening = pendulum.datetime(2026, 1, 1, 0, tz="UTC")
    deadline = opening.add(hours=10)

    with pytest.raises(ValueError, match="too short.*Reduce the reminder count"):
        cwl_sequence.plan(campaign, opening, deadline)


def test_interval_rejects_more_than_ten_occurrences_with_actionable_fix():
    campaign = configured(
        mode="interval", interval_hours=1, final_hours=1, min_gap_hours=1,
    )
    opening = pendulum.datetime(2026, 1, 1, 0, tz="UTC")

    with pytest.raises(ValueError, match="more than 10.*Increase interval hours"):
        cwl_sequence.plan(campaign, opening, opening.add(hours=20))


def test_interval_prunes_tenth_near_final_before_enforcing_capacity():
    campaign = configured(
        mode="interval", interval_hours=10, final_hours=1, min_gap_hours=3,
    )
    opening = pendulum.datetime(2026, 1, 1, 0, tz="UTC")
    deadline = opening.add(hours=102)

    result = cwl_sequence.plan(campaign, opening, deadline)

    assert result["reminder:9"] == opening.add(hours=90)
    assert result["reminder:10"] == opening.add(hours=101)


def test_elapsed_hour_spacing_survives_spring_dst_transition():
    campaign = configured(mode="evenly", count=2, final_hours=3, min_gap_hours=3)
    opening = pendulum.datetime(2026, 3, 7, 0, tz="America/New_York")
    deadline = pendulum.datetime(2026, 3, 10, 0, tz="America/New_York")

    result = cwl_sequence.plan(campaign, opening, deadline)

    assert (result["reminder:1"].in_timezone("UTC") - opening.in_timezone("UTC")).total_hours() == 34
    assert (result["reminder:2"].in_timezone("UTC") - opening.in_timezone("UTC")).total_hours() == 68
    assert (deadline.in_timezone("UTC") - result["reminder:2"].in_timezone("UTC")).total_hours() == 3


def test_unconfigured_campaign_returns_all_slots_unused():
    campaign = cwl_campaign.default_campaign()
    result = cwl_sequence.plan(
        campaign,
        pendulum.datetime(2026, 1, 1, tz="UTC"),
        pendulum.datetime(2026, 1, 10, tz="UTC"),
    )
    assert result == {message_id: None for message_id in cwl_sequence.REMINDER_IDS}


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("count", 0, "Reminder count must be from 1 to 10"),
        ("count", True, "whole number"),
        ("interval_hours", 745, "Interval hours must be from 1 to 744"),
        ("final_hours", 0, "Final reminder hours must be from 1 to 744"),
        ("min_gap_hours", 25, "Minimum gap hours must be from 1 to 24"),
    ],
)
def test_configuration_bounds_are_explicit(field, value, match):
    values = {field: value}
    with pytest.raises(ValueError, match=match):
        configured(**values)


def test_interval_must_respect_minimum_gap_but_final_offset_is_independent():
    with pytest.raises(ValueError, match="Interval hours must be at least"):
        configured(mode="interval", interval_hours=2, min_gap_hours=3)
    campaign = configured(final_hours=1, min_gap_hours=3)
    assert campaign["reminder_sequence"]["final_hours"] == 1


def test_configure_preserves_custom_message_and_uses_remaining_slot_capacity():
    campaign = cwl_campaign.default_campaign()
    custom = copy.deepcopy(campaign["messages"]["signup"])
    custom["label"] = "Staff custom reminder"
    campaign["messages"]["custom:extra"] = custom

    result = cwl_sequence.configure(campaign, "evenly")

    assert result["messages"]["custom:extra"] == custom
    assert len(result["messages"]) == 12
    assert all(f"reminder:{number}" in result["messages"] for number in range(1, 10))
    assert "reminder:10" not in result["messages"]


def test_even_count_rejects_more_slots_than_custom_messages_leave():
    campaign = cwl_campaign.default_campaign()
    campaign["messages"]["custom:extra"] = copy.deepcopy(campaign["messages"]["signup"])

    with pytest.raises(ValueError, match="Custom messages leave 9 reminder slots.*reduce count"):
        cwl_sequence.configure(campaign, "evenly", count=10)


def test_interval_plan_rejects_more_slots_than_custom_messages_leave():
    campaign = cwl_campaign.default_campaign()
    campaign["messages"]["custom:extra"] = copy.deepcopy(campaign["messages"]["signup"])
    campaign = cwl_sequence.configure(
        campaign, "interval", interval_hours=1, final_hours=1, min_gap_hours=1,
    )
    opening = pendulum.datetime(2026, 1, 1, 0, tz="UTC")

    with pytest.raises(ValueError, match="Custom messages leave 9 reminder slots.*increase interval"):
        cwl_sequence.plan(campaign, opening, opening.add(hours=11))


def test_naive_times_and_backwards_windows_are_rejected():
    campaign = configured()
    with pytest.raises(ValueError, match="include a timezone"):
        cwl_sequence.plan(campaign, datetime_without_timezone(), pendulum.now("UTC"))
    opening = pendulum.datetime(2026, 1, 2, tz="UTC")
    with pytest.raises(ValueError, match="deadline must be after"):
        cwl_sequence.plan(campaign, opening, opening.subtract(hours=1))


def datetime_without_timezone():
    from datetime import datetime

    return datetime(2026, 1, 1, 12, 0)
