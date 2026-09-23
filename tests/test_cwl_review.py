import copy

from utils.cwl_campaign import default_campaign
from utils.cwl_review import change_summary


def test_deadline_change_shows_which_dependent_reminders_move():
    before = default_campaign()
    before["messages"]["reminder:5"]["schedule"] = {"mode": "before_close", "offset_minutes": 1440}
    after = copy.deepcopy(before)
    after["signup_deadline"] = {"day": 27, "hour": 17, "minute": 0}
    summary = change_summary(before, after, "2026-10")
    assert "Signup deadline:" in summary
    assert "Sign-up reminder 5** timing: <t:" in summary
    assert "Signups open** timing" not in summary


def test_variant_changes_show_scope_without_dumping_long_message_body():
    before = default_campaign()
    after = copy.deepcopy(before)
    after["messages"]["signup"]["variants"]["lazy"].update(body="Changed", media_url="https://example.com/new.gif")
    summary = change_summary(before, after, "2026-10")
    assert "Signups open · Lazy**: text, artwork" in summary
    assert "Main" not in summary
    assert "Changed" not in summary


def test_unchanged_review_is_explicit():
    campaign = default_campaign()
    assert change_summary(campaign, campaign, "2026-10") == "No content or timing changes."
