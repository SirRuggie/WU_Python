"""Regression tests for the Components V2 /accounts inventory."""

import asyncio
import re
from types import SimpleNamespace

import pytest

from extensions import components
from extensions.commands import accounts
from utils import coc_maintenance, todo_data


@pytest.fixture(autouse=True)
def _clean_account_state():
    accounts._result_cache.clear()
    todo_data._cache.clear()
    coc_maintenance.reset()
    yield
    accounts._result_cache.clear()
    todo_data._cache.clear()
    coc_maintenance.reset()


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _payload(data, page=0):
    return [component.build() for component in accounts.render_accounts(data, page)]


def _text(payload) -> str:
    return "\n".join(
        str(node.get("content", ""))
        for node in _walk(payload)
        if "content" in node
    )


def _account(index: int, *, town_hall: int | None = None, clan_name: str | None = None):
    tag = f"#TAG{index:02d}"
    return todo_data.Account(
        tag=tag,
        name=f"Player {index:02d}",
        clan_tag=f"#CLAN{index:02d}" if clan_name is not None else None,
        clan_name=clan_name,
        town_hall=town_hall if town_hall is not None else 18 - (index % 10),
        share_link=(
            "https://link.clashofclans.com/en?action=OpenPlayerProfile"
            f"&tag=%23{tag.lstrip('#')}"
        ),
    )


def _loaded_entry(index: int) -> accounts.AccountEntry:
    account = _account(index, clan_name=f"Clan {index:02d}")
    return accounts.AccountEntry(account.tag, accounts.STATUS_LOADED, account)


def test_shared_player_fetch_adds_share_link_without_changing_existing_fields():
    player = SimpleNamespace(
        tag="#PLAYER",
        name="Player Name",
        town_hall=18,
        share_link=(
            "https://link.clashofclans.com/en?action=OpenPlayerProfile"
            "&tag=%23PLAYER"
        ),
        clan=SimpleNamespace(
            tag="#CLAN",
            name="Clan Name",
            badge=SimpleNamespace(medium="https://example.com/badge.png"),
        ),
    )

    class Client:
        async def get_player(self, tag):
            assert tag == "#PLAYER"
            return player

    tag, account, error = asyncio.run(todo_data._fetch_one_player(
        Client(), "#PLAYER", asyncio.Semaphore(1)
    ))

    assert tag == "#PLAYER"
    assert error is None
    assert account == todo_data.Account(
        tag="#PLAYER",
        name="Player Name",
        clan_tag="#CLAN",
        clan_name="Clan Name",
        town_hall=18,
        clan_badge="https://example.com/badge.png",
        share_link=player.share_link,
    )


def test_link_service_failure_is_not_reported_as_no_links(monkeypatch):
    async def failed(_discord_id):
        return None

    async def must_not_fetch(*_args, **_kwargs):
        raise AssertionError("player fetch must not run after a link-service failure")

    monkeypatch.setattr(accounts, "resolve_tags", failed)
    monkeypatch.setattr(todo_data, "fetch_accounts", must_not_fetch)

    data = asyncio.run(accounts.load_accounts(object(), 123, force=True))
    text = _text(_payload(data))

    assert data.problem == accounts.LINK_FAILURE
    assert "Couldn't reach the link service" in text
    assert "No linked accounts" not in text
    assert "problem on their end, not yours" in text


def test_successful_empty_lookup_shows_link_instructions_without_player_fetch(monkeypatch):
    async def no_links(_discord_id):
        return []

    async def must_not_fetch(*_args, **_kwargs):
        raise AssertionError("player fetch must not run when there are no links")

    monkeypatch.setattr(accounts, "resolve_tags", no_links)
    monkeypatch.setattr(todo_data, "fetch_accounts", must_not_fetch)

    data = asyncio.run(accounts.load_accounts(object(), 123, force=True))
    text = _text(_payload(data))

    assert data.problem is None
    assert data.linked_count == 0
    assert "No linked accounts" in text
    assert "ClashKing's `/link`" in text


def test_rerunning_command_bypasses_an_old_empty_link_cache(monkeypatch):
    todo_data.cache_put("links:123", [], todo_data.TTL_LINKS)
    calls = []

    async def newly_linked(discord_id):
        calls.append(discord_id)
        return ["#NEW"]

    player = todo_data.Account(
        tag="#NEW",
        name="New Account",
        clan_tag=None,
        clan_name=None,
        town_hall=12,
    )

    async def fetch(_client, tags):
        assert tags == ["#NEW"]
        return [player], []

    monkeypatch.setattr(accounts, "resolve_tags", newly_linked)
    monkeypatch.setattr(todo_data, "fetch_accounts", fetch)

    data = asyncio.run(accounts.load_accounts(object(), 123, force=True))

    assert calls == [123]
    assert data.loaded_count == 1
    assert data.entries[0].tag == "#NEW"


def test_every_linked_tag_is_reconciled_as_loaded_not_found_or_error(monkeypatch):
    async def linked(_discord_id):
        return ["one", "#TWO", "#THREE", "#TWO"]

    loaded_account = todo_data.Account(
        tag="#ONE",
        name="Loaded",
        clan_tag="#CLAN",
        clan_name="The Clan",
        town_hall=17,
    )

    async def partial(_client, tags):
        assert tags == ["#ONE", "#TWO", "#THREE"]
        return [loaded_account], ["#TWO: GatewayError"]

    monkeypatch.setattr(accounts, "resolve_tags", linked)
    monkeypatch.setattr(todo_data, "fetch_accounts", partial)

    data = asyncio.run(accounts.load_accounts(object(), 123, force=True))
    by_tag = {entry.tag: entry.status for entry in data.entries}

    assert data.linked_count == 3
    assert data.linked_count == (
        data.loaded_count + data.not_found_count + data.error_count
    )
    assert by_tag == {
        "#ONE": accounts.STATUS_LOADED,
        "#TWO": accounts.STATUS_ERROR,
        "#THREE": accounts.STATUS_NOT_FOUND,
    }

    text = _text(_payload(data))
    for tag in by_tag:
        assert text.count(f"`{tag}`") == 1
    assert "1 account couldn't be loaded this time" in text
    assert "1 linked tag returned no player profile" in text


def test_loaded_accounts_sort_by_town_hall_then_name_and_show_required_fields():
    low = todo_data.Account(
        tag="#LOW",
        name="Zulu",
        clan_tag=None,
        clan_name=None,
        town_hall=1,
    )
    alpha = todo_data.Account(
        tag="#ALPHA",
        name="Alpha [One] @everyone",
        clan_tag="#A",
        clan_name="Clan *A*",
        town_hall=18,
    )
    beta = todo_data.Account(
        tag="#BETA",
        name="Beta",
        clan_tag="#B",
        clan_name="Clan B",
        town_hall=18,
    )
    data = accounts.AccountsData(entries=tuple(sorted([
        accounts.AccountEntry(low.tag, accounts.STATUS_LOADED, low),
        accounts.AccountEntry(beta.tag, accounts.STATUS_LOADED, beta),
        accounts.AccountEntry(alpha.tag, accounts.STATUS_LOADED, alpha),
    ], key=accounts._entry_sort_key)))

    text = _text(_payload(data))

    assert text.index("#ALPHA") < text.index("#BETA") < text.index("#LOW")
    assert "TH18" in text
    assert "🏰 TH1" in text
    assert "No clan" in text
    assert "Alpha \\[One\\] @\u200beveryone" in text
    assert "Clan \\*A\\*" in text
    assert (
        "https://link.clashofclans.com/en?action=OpenPlayerProfile&tag=%23ALPHA"
        in text
    )


def test_each_account_is_one_compact_mobile_row():
    loaded = _loaded_entry(1)
    missing = accounts.AccountEntry("#MISSING", accounts.STATUS_NOT_FOUND)
    failed = accounts.AccountEntry("#FAILED", accounts.STATUS_ERROR)

    rows = [
        accounts._entry_line(loaded, 1),
        accounts._entry_line(missing, 2),
        accounts._entry_line(failed, 3),
    ]

    assert all("\n" not in row for row in rows)
    assert rows[0].startswith("**1.**")
    assert "TH17" in rows[0]
    assert "Player 01" in rows[0]
    assert "`#TAG01`" in rows[0]
    assert "Clan 01" in rows[0]
    assert rows[0].index("TH17") < rows[0].index("Player 01")
    assert rows[0].index("Player 01") < rows[0].index("`#TAG01`")
    assert rows[0].index("`#TAG01`") < rows[0].index("Clan 01")
    assert "https://link.clashofclans.com/" in rows[0]
    assert rows[1].startswith("**2.** ⚠️ `#MISSING`")
    assert rows[2].startswith("**3.** ⏳ `#FAILED`")
    assert accounts._text_blocks(rows) == ["\n".join(rows)]


def test_maintenance_replaces_generic_partial_failure_copy():
    data = accounts.AccountsData(entries=(
        _loaded_entry(1),
        accounts.AccountEntry("#FAILED", accounts.STATUS_ERROR),
    ))
    coc_maintenance.note_maintenance()

    text = _text(_payload(data))

    assert "Clash is in maintenance" in text
    assert "Nothing is wrong with your accounts" in text
    assert "couldn't be loaded this time" not in text
    assert "`#FAILED`" in text


def test_forty_six_accounts_use_three_complete_bounded_pages():
    entries = tuple(_loaded_entry(index) for index in range(46))
    data = accounts.AccountsData(entries=entries)
    seen_tags: list[str] = []

    for page, expected_rows in enumerate((20, 20, 6)):
        payload = _payload(data, page)
        text = _text(payload)
        page_tags = re.findall(r"`(#[^`]+)`", text)
        seen_tags.extend(page_tags)

        assert len(page_tags) == expected_rows
        assert f"Page {page + 1}/3" in str(payload)

        custom_ids = [
            str(node["custom_id"])
            for node in _walk(payload)
            if "custom_id" in node
        ]
        assert len(custom_ids) == len(set(custom_ids))
        assert all(custom_id.count(":") == 1 for custom_id in custom_ids)
        assert all(
            custom_id.partition(":")[0] in components.registered_functions
            for custom_id in custom_ids
        )

        nested_components = sum(
            1 for node in _walk(payload) if "type" in node
        )
        assert nested_components <= 40
        assert all(
            len(str(node["content"])) < 4000
            for node in _walk(payload)
            if "content" in node
        )

    assert len(seen_tags) == 46
    assert set(seen_tags) == {entry.tag for entry in entries}

    assert re.findall(r"`(#[^`]+)`", _text(_payload(data, -999))) == [
        entry.tag for entry in entries[:20]
    ]
    assert re.findall(r"`(#[^`]+)`", _text(_payload(data, 999))) == [
        entry.tag for entry in entries[40:]
    ]


def test_markdown_heavy_max_length_rows_split_below_discord_text_limit():
    entries = []
    for index in range(accounts.PAGE_SIZE):
        tag = f"#MAX{index:02d}"
        account = todo_data.Account(
            tag=tag,
            name=("[]_*~`()@" * 2)[:16],
            clan_tag=f"#C{index:02d}",
            clan_name=("[]_*~`()|>" * 2)[:15],
            town_hall=18,
        )
        entries.append(accounts.AccountEntry(
            tag, accounts.STATUS_LOADED, account
        ))

    payload = _payload(accounts.AccountsData(entries=tuple(entries)))
    contents = [
        str(node["content"])
        for node in _walk(payload)
        if "content" in node
    ]

    assert all(len(content) <= accounts.TEXT_BLOCK_LIMIT for content in contents)
    assert len([
        content for content in contents if "`#MAX" in content
    ]) >= 2
    assert set(re.findall(r"`(#[^`]+)`", _text(payload))) == {
        entry.tag for entry in entries
    }


@pytest.mark.parametrize(
    ("guild_id", "expected_ephemeral"),
    [(456, True), (None, False)],
)
def test_command_keeps_guild_account_lists_private(
    monkeypatch, guild_id, expected_ephemeral
):
    async def loaded(_client, _discord_id, *, force=False):
        assert force
        return accounts.AccountsData(entries=(_loaded_entry(1),))

    monkeypatch.setattr(accounts, "load_accounts", loaded)

    class Interaction:
        def __init__(self):
            self.edits = []

        async def edit_initial_response(self, **kwargs):
            self.edits.append(kwargs)

    class Context:
        def __init__(self):
            self.guild_id = guild_id
            self.user = SimpleNamespace(id=123)
            self.interaction = Interaction()
            self.defers = []

        async def defer(self, **kwargs):
            self.defers.append(kwargs)

    ctx = Context()
    asyncio.run(accounts.Accounts().invoke(ctx, coc_client=object()))

    assert ctx.defers == [{"ephemeral": expected_ephemeral}]
    assert len(ctx.interaction.edits) == 1
    assert ctx.interaction.edits[0]["components"]
