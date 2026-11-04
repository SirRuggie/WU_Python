"""Member message destinations and defaults; no Discord/network writes."""

from copy import deepcopy
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest
from utils import cwl_campaign, dashboard_urls, declaration_pings
from utils.cwl_roster_messages import closing_message
from cwl_web.app import login_destination, saved_login_destination


def test_roster_defaults_exact_copy_links_and_no_delivery_policy_changes():
    campaign = cwl_campaign.default_campaign()
    bodies = {
        "main": "The rosters are ready. Select **My clan assignments** to see your clan.\n\nFinish both attacks in your current war. Then move to your clan. Do this as soon as you can.\n\nDo you have a question? Ask in <#801950200133976124> <:warriorcat:947992348971905035>",
        "lazy": "The Lazy rosters are ready. Select **My clan assignments** to see your clan.\n\nFinish both attacks in your current war. Then move to your clan. Do this as soon as you can.\n\nDo you need help? Ask <@&769130325460254740> in <#872692009066958879>.",
    }
    for pool, body in bodies.items():
        item = campaign["messages"]["roster"]["variants"][pool]
        assert item["body"] == body
        assert [button["label"] for button in item["buttons"]][:3] == [
            "My clan assignments",
            "My tasks",
            "Wars",
        ]
        assert [button["url"] for button in item["buttons"]][:3] == [
            dashboard_urls.ASSIGNMENTS_URL,
            dashboard_urls.TASKS_URL,
            dashboard_urls.WARS_URL,
        ]
        assert len(item["buttons"]) == (3 if pool == "main" else 4)
        assert item["role_ids"] == [1080521665584308286]
        assert item["destination_channel_id"] == (
            1072714594625257502 if pool == "main" else 865726525990633472
        )
    assert campaign["messages"]["roster"]["schedule"] == {"mode": "manual"}
    assert (
        campaign["messages"]["roster"]["variants"]["lazy"]["buttons"][-1]["label"]
        == "LazyCWL Guide"
    )


def test_signup_rule_before_steps_and_short_reminder_prefix_once_after_normalization():
    campaign = cwl_campaign.normalize_signup_entry(cwl_campaign.default_campaign())
    for pool in ("main", "lazy"):
        signup = campaign["messages"]["signup"]["variants"][pool]["body"]
        assert signup.index("FWA clan members must choose Lazy CWL.") < signup.index(
            "1. Select"
        )
        assert "our dashboard" in signup
        for index in range(1, 6):
            body = campaign["messages"][f"reminder:{index}"]["variants"][pool]["body"]
            assert body.startswith(
                "**Are you signed up already? Then you do not need to do more.** If not, sign up below.\nSelect **Check my signups** to see your accounts."
            )
            assert body.count("Check my signups") == 1
            assert body.count("FWA clan members must choose Lazy CWL.") == 1
            assert "we got ya down" not in body
    for message in campaign["messages"].values():
        for variant in message["variants"].values():
            assert len(variant["buttons"]) <= 5


def test_custom_saved_campaign_is_not_overwritten_or_mutated_by_default_copy():
    saved = cwl_campaign.default_campaign()
    for message in saved["messages"].values():
        for variant in message["variants"].values():
            variant["body"] = "Custom saved text. " + cwl_campaign.SIGNUP_CHECK_LINE
    saved["messages"]["roster"]["variants"]["main"]["buttons"] = [
        {"label": "Custom roster", "url": "https://example.test/custom"}
    ]
    before = deepcopy(saved)
    normalized = cwl_campaign.normalize_signup_entry(saved)
    assert saved == before
    assert normalized == before
    assert "LAZY WAY OR NO WAY!!" in cwl_campaign.LEGACY_SIGNUP_LAZY


@pytest.mark.parametrize(
    "url,view",
    [
        (dashboard_urls.SIGNUP_URL, "signup"),
        (dashboard_urls.ASSIGNMENTS_URL, "assignments"),
        (dashboard_urls.TASKS_URL, "todo"),
        (dashboard_urls.WARS_URL, "wars"),
    ],
)
def test_every_message_dashboard_url_is_a_real_member_login_return_route(url, view):
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.netloc == "dash.warriorsunited.cc"
    assert login_destination({"view": view}) == parsed.path
    assert (
        saved_login_destination(SimpleNamespace(cookies={"wu_login_page": parsed.path}))
        == parsed.path
    )
    assert (
        saved_login_destination(
            SimpleNamespace(
                cookies={"wu_login_page": "https://bad.example" + parsed.path}
            )
        )
        == ""
    )


def test_declaration_link_preserves_recipient_and_component_limits_across_many_clans():
    from test_declaration_pings import row

    alphabet = "PYLQGRJCUV0289"
    tags = [
        "#P" + alphabet[i // len(alphabet)] + alphabet[i % len(alphabet)]
        for i in range(65)
    ]
    accounts = [
        row(tag=tag, clan=tag, owner=str(123456789012345678 + i))
        for i, tag in enumerate(tags)
    ]
    groups = declaration_pings.missing_groups(accounts, "lazy")
    payloads = declaration_pings.messages(groups)
    recipients = set()
    for payload in payloads:
        children = payload["components"][0]["components"]
        buttons = [
            button
            for child in children
            if child["type"] == 1
            for button in child["components"]
        ]
        assert (
            sum(button["url"] == dashboard_urls.ASSIGNMENTS_URL for button in buttons)
            == 1
        )
        assert all(
            len(child["components"]) <= 5 for child in children if child["type"] == 1
        )
        assert 1 + len(children) + len(buttons) <= 40
        recipients.update(payload["allowed_mentions"]["users"])
    assert recipients == {str(123456789012345678 + i) for i in range(65)}
    assert (
        closing_message()["components"][0]["components"][0]["label"]
        == "My clan assignments"
    )


def test_legacy_saved_signup_read_migration_does_not_adopt_new_default_text():
    saved = cwl_campaign.default_campaign()
    for pool, legacy in [
        ("main", cwl_campaign.LEGACY_SIGNUP_MAIN),
        ("lazy", cwl_campaign.LEGACY_SIGNUP_LAZY),
    ]:
        saved["messages"]["signup"]["variants"][pool]["body"] = legacy
    before = deepcopy(saved)
    result = cwl_campaign.normalize_signup_entry(saved)
    assert saved == before
    for pool in ("main", "lazy"):
        body = result["messages"]["signup"]["variants"][pool]["body"]
        assert "our website." in body  # Existing migration copy, not new defaults.
        assert body.index("FWA clan members must choose Lazy CWL.") > body.index(
            "4. Check"
        )
        assert body.count("Check my signups") == 1
    cwl_campaign.validate_campaign(cwl_campaign.default_campaign())
