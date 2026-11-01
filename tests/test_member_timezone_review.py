from utils.member_timezone_review import preview_rows


def test_every_review_category_and_bots_excluded():
    base = dict(
        discord_id="123456789012345678",
        name="Name",
        nickname="Name | EST 🇺🇸",
        profile=dict(zone_id="gmt-5", country="US", revision=3),
        skip_reason=None,
    )
    samples = [
        base,
        dict(base, profile=dict(base["profile"], country=None)),
        dict(base, profile=None),
        dict(base, nickname="Name | GMT-5 🇺🇸"),
        dict(base, skip_reason="Above bot"),
        dict(base, nickname="Name | Co-Leader"),
        dict(base, bot=True),
    ]
    rows = preview_rows(samples)
    assert [r["category"] for r in rows] == [
        "will_change",
        "needs_flag",
        "no_time_zone",
        "already_done",
        "cant_rename",
        "check_name",
    ]
    assert rows[0]["revision"] == 3 and rows[-1]["needs_review"]
    assert rows[3]["old_nickname"] == rows[3]["new_nickname"]
    assert rows[4]["skip_reason"] == "Above bot"
