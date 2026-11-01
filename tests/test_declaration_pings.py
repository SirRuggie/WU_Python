from utils.declaration_pings import missing_groups, messages, text_units
import pytest


def row(tag="#PYY", owner="123456789012345678", clan="#PQQ", **extra):
    return dict(
        tag=tag,
        user_id=owner,
        assigned_clan_tag=clan,
        assigned_clan_name="Fixture clan",
        player_name="Fixture player",
        pool="lazy",
        arrival_status="missing",
        **extra
    )


def content(payload):
    return payload["components"][0]["components"][0]["content"]


def test_group_dedupe_unlinked_unknown_and_awaiting():
    rows = [row(), row("#PYP"), row("#PPR", owner=None), row("#PPC", clan=None)]
    rows.append(dict(row("#P2Y"), arrival_status="unknown"))
    groups = missing_groups(rows, "lazy")
    assert len(groups) == 1 and len(groups[0]["accounts"]) == 3
    assert groups[0]["users"] == ["123456789012345678"]
    payload = messages(groups)[0]
    assert content(payload).count("<@123456789012345678>") == 1
    assert "Fixture player" in content(payload) and "Total missing: 3" in content(
        payload
    )
    assert payload["allowed_mentions"] == dict(
        parse=[], users=["123456789012345678"], roles=[]
    )
    assert messages(groups, test=True)[0]["allowed_mentions"] == dict(
        parse=[], users=[], roles=[]
    )


def test_chunk_boundaries_and_external_text_cannot_create_mentions():
    # Distinct valid player tags, with100+ users assigned to one clan.
    alphabet = "0289PYLQGRJCUV"
    rows = [
        row(
            "#P" + alphabet[i // 14] + alphabet[i % 14],
            owner=str(123456789012345678 + i),
        )
        for i in range(145)
    ]
    rows[0]["assigned_clan_name"] = "@everyone <@&123456789012345678>"
    rows[1]["player_name"] = "@everyone <@123456789012345679>"
    rows[1]["user_id"] = None
    chunks = messages(missing_groups(rows, "lazy"))
    assert len(chunks) >= 2
    for payload in chunks:
        text = content(payload)
        labels = [
            b["label"]
            for c in payload["components"][0]["components"]
            if c["type"] == 1
            for b in c["components"]
        ]
        assert text_units(text) + sum(map(text_units, labels)) <= 3800
        assert "@everyone" not in text and "<@&" not in text
        assert len(payload["allowed_mentions"]["users"]) <= 100
        assert (
            payload["allowed_mentions"]["parse"] == []
            and payload["allowed_mentions"]["roles"] == []
        )
        assert all(
            text.count("<@" + uid + ">") == 1
            for uid in payload["allowed_mentions"]["users"]
        )
    assert sum(len(p["allowed_mentions"]["users"]) for p in chunks) == 144


def test_component_and_utf16_button_limits_with_many_clans():
    alphabet = "0289PYLQGRJCUV"
    rows = [
        row(
            "#P" + alphabet[i // 14] + alphabet[i % 14],
            clan="#Q" + alphabet[i // 14] + alphabet[i % 14],
            owner=str(123456789012345678 + i),
        )
        for i in range(65)
    ]
    for r in rows:
        r["assigned_clan_name"] = "😀" * 40

    def count(node):
        return 1 + sum(count(n) for n in node.get("components", []))

    for payload in messages(missing_groups(rows, "lazy")):
        assert sum(count(n) for n in payload["components"]) <= 40
        for component in payload["components"][0]["components"]:
            if component["type"] == 1:
                assert len(component["components"]) <= 5
                assert all(
                    text_units(b["label"]) <= 80 for b in component["components"]
                )
        labels = [
            b["label"]
            for c in payload["components"][0]["components"]
            if c["type"] == 1
            for b in c["components"]
        ]
        assert text_units(content(payload)) + sum(map(text_units, labels)) <= 3800


def test_hosting_pool_is_authoritative_and_conflicts_fail_closed():
    main = dict(row(), hosting_pool="main")
    assert missing_groups([main], "lazy") == []
    assert len(missing_groups([main], "main")) == 1
    with pytest.raises(ValueError):
        missing_groups([row(), dict(row(), assigned_clan_tag="#RYY")], "lazy")
    assert missing_groups([dict(row(), arrival_status="arrived")], "lazy") == []


def test_review_identity_ignores_display_names_but_keeps_pool_lineup():
    from utils.declaration_pings import review_fingerprint

    first = missing_groups([row()], "lazy")
    other = missing_groups(
        [dict(row(), player_name="Renamed", assigned_clan_name="New label")], "lazy"
    )
    assert review_fingerprint(
        first, version=1, channel_id="channel", revision=1
    ) == review_fingerprint(other, version=1, channel_id="channel", revision=1)
    other[0]["accounts"][0]["user_id"] = "223456789012345678"
    assert review_fingerprint(
        first, version=1, channel_id="channel", revision=1
    ) != review_fingerprint(other, version=1, channel_id="channel", revision=1)


def test_pool_signature_ignores_weights_but_keeps_arrived_lineup_members():
    from cwl_web.declaration_lineup import signature

    rows = [
        row(),
        dict(row("#PYP"), arrival_status="arrived"),
        dict(row("#PPR"), hosting_pool="main", assigned_clan_tag="#RYY"),
    ]
    before = signature(rows, "lazy", {"#PQQ": "lazy", "#RYY": "main"})
    rows[0]["manual_weight"] = 200
    rows[2]["user_id"] = "223456789012345678"
    assert signature(rows, "lazy", {"#PQQ": "lazy", "#RYY": "main"}) == before
    rows[1]["user_id"] = "223456789012345678"
    assert signature(rows, "lazy", {"#PQQ": "lazy", "#RYY": "main"}) != before
