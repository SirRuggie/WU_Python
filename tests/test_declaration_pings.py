from utils.declaration_pings import missing_groups, messages, text_units


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
        assert text_units(text) <= 4000
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
