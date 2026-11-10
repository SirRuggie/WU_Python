"""/profile card, its buttons, and the staff New Warrior alert (fixtures only)."""

import asyncio
import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions import components
from extensions.commands import linked_accounts as accounts
from extensions.commands import profile
from extensions.events import new_warrior_alert
from utils import recruit_links, todo_data
from utils.constants import NEW_WARRIOR_ALERT_CHANNEL_ID, WARRIORS_UNITED_GUILD_ID

ROLE = 1151305219079155802
CREATED = datetime(2020, 1, 2, tzinfo=timezone.utc)
JOINED = datetime(2026, 11, 10, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    accounts._merged_cache.clear()
    accounts._result_cache.clear()
    yield
    accounts._merged_cache.clear()
    accounts._result_cache.clear()


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _built(cards):
    built = [card.build() for card in cards]
    return [item[0] if isinstance(item, tuple) else item for item in built]


def _text(payload) -> str:
    return "\n".join(str(n["content"]) for n in _walk(payload) if "content" in n)


def _identity(**changes):
    values = dict(user_id=123, display_name="Warrior [One]", username="warrior_one",
                  avatar_url="https://cdn.discordapp.com/avatars/123/abc.png",
                  created_at=CREATED, joined_at=JOINED)
    values.update(changes)
    return profile.Identity(**values)


def _entry(index):
    account = todo_data.Account(tag=f"#TAG{index:02d}", name=f"Player {index:02d}",
                                clan_tag=None, clan_name="Clan", town_hall=17)
    return accounts.AccountEntry(account.tag, accounts.STATUS_LOADED, account)


def _custom_ids(payload):
    return [str(n["custom_id"]) for n in _walk(payload) if "custom_id" in n]


def test_card_has_identity_section_with_avatar_separator_then_accounts():
    payload = _built(profile.render_profile(_identity(), accounts.AccountsData(entries=(_entry(1),))))
    children = payload[0]["components"]
    section = children[0]
    assert section["type"] == 9  # Section
    assert section["accessory"]["type"] == 11  # Thumbnail
    assert section["accessory"]["media"]["url"].startswith("https://cdn.discordapp.com/")
    assert children[1]["type"] == 14  # Separator
    text = _text(payload)
    assert "## Linked Accounts" in text and "**1 linked account**" in text
    assert "Account created:** <t:" in text and "Joined server:** <t:" in text
    assert "**Player 01** · [#TAG01](https://link.clashofclans.com/" in text


@pytest.mark.parametrize("name", ["❤️MC QUEEN❤️", "[x](https://evil.test)", "a]b(c"])
def test_name_with_link_breaking_characters_is_plain_text(name):
    text = _text(_built(profile.render_profile(_identity(display_name=name), accounts.AccountsData())))
    first = text.split("\n")[0]
    assert first.startswith("### ") and "](" not in first
    assert "[warrior\\_one](https://discord.com/users/123)" in text


def test_odd_username_falls_back_to_a_safe_label():
    text = _text(_built(profile.render_profile(_identity(username="Bad Name!"), accounts.AccountsData())))
    assert "[Discord profile](https://discord.com/users/123)" in text


def test_name_is_a_profile_link_never_a_mention_and_no_raw_id_text():
    payload = _built(profile.render_profile(_identity(), accounts.AccountsData()))
    text = _text(payload)
    assert "### Warrior \\[One\\]\n[warrior\\_one](https://discord.com/users/123)" in text
    assert "<@123>" not in text and "<@" not in text
    without_links = re.sub(r"\(https://discord\.com/users/\d+\)", "", text)
    assert "123" not in without_links


def test_no_links_still_shows_identity_and_plain_empty_state():
    payload = _built(profile.render_profile(_identity(), accounts.AccountsData()))
    text = _text(payload)
    assert "No linked accounts" in text
    assert "-# Not linked in ClashKing or ClashPerk." in text
    assert payload[0]["components"][0]["type"] == 9
    assert _custom_ids(payload) == ["profile_refresh:123:0:p"]


@pytest.mark.parametrize("entries", [(), (_entry(1),)])
def test_outage_is_never_shown_as_no_links(entries):
    data = accounts.AccountsData(entries=entries, unavailable_sources=("ClashPerk",))
    text = _text(_built(profile.render_profile(_identity(), data)))
    assert "No linked accounts" not in text
    assert "Could not reach ClashPerk" in text


def test_no_avatar_and_non_member_header():
    payload = _built(profile.render_profile(
        _identity(avatar_url=None, joined_at=None), accounts.AccountsData()))
    first = payload[0]["components"][0]
    assert first["type"] == 10
    assert "Joined server" not in _text(payload)


def test_paging_and_refresh_keep_target_and_are_registered():
    data = accounts.AccountsData(entries=tuple(_entry(i) for i in range(46)))
    for page, rows in enumerate((20, 20, 6)):
        payload = _built(profile.render_profile(_identity(), data, page))
        assert len(re.findall(r"\[(#TAG\d+)\]", _text(payload))) == rows
        ids = _custom_ids(payload)
        assert len(ids) == len(set(ids))
        assert all(i.split(":")[1] == "123" for i in ids)
        assert all(i.partition(":")[0] in components.registered_functions for i in ids)
        assert f"Page {page + 1}/3" in json.dumps(payload)


@pytest.mark.parametrize(("action_id", "expected"), [
    ("123:2:p", (123, 2, "p")),
    ("123:1", (123, 1, "p")),          # old /user-accounts buttons
    ("123:x:a", (123, 0, "a")),
    ("0:1:p", None), ("abc:1:p", None), ("123:1:z", None), ("123", None),
    ("1" * 21 + ":0:p", None), ("123:1:p:extra", None),
])
def test_parse_action(action_id, expected):
    assert profile.parse_action(action_id) == expected


def test_old_user_accounts_buttons_route_to_profile_page():
    assert components._resolve("user_accounts_page") is components.registered_functions["profile_page"]


def _button_ctx(custom_id, clicker=999):
    respond = AsyncMock()
    app = SimpleNamespace(cache=SimpleNamespace(get_member=lambda *_: None, get_user=lambda *_: None),
                          rest=SimpleNamespace(fetch_user=AsyncMock(return_value=SimpleNamespace(
                              id=123, username="warrior_one", global_name="Warrior",
                              display_avatar_url=None, created_at=CREATED))))
    interaction = SimpleNamespace(custom_id=custom_id, app=app, guild_id=WARRIORS_UNITED_GUILD_ID)
    return SimpleNamespace(interaction=interaction, user=SimpleNamespace(id=clicker), respond=respond)


def test_buttons_show_target_not_clicker_edit_quietly_and_refresh_bypasses_cache(monkeypatch):
    calls = []

    async def resolve(discord_id, *, verify_owners=True):
        calls.append((discord_id, verify_owners))
        return recruit_links.LinksResult()

    monkeypatch.setattr(recruit_links, "resolve", resolve)
    ctx = _button_ctx("profile_page:123:0:a")
    assert asyncio.run(profile.profile_page_handler(ctx=ctx, action_id="123:0:a", coc_client=object())) is None
    asyncio.run(profile.profile_page_handler(ctx=ctx, action_id="123:0:a", coc_client=object()))
    assert calls == [(123, False)]  # second page view served from the short cache
    asyncio.run(profile.profile_refresh_handler(ctx=ctx, action_id="123:0:a", coc_client=object()))
    assert calls == [(123, False), (123, False)]
    kwargs = ctx.respond.call_args.kwargs
    assert kwargs["edit"] is True
    assert kwargs["user_mentions"] is False and kwargs["role_mentions"] is False
    assert kwargs["mentions_everyone"] is False
    text = _text(_built(kwargs["components"]))
    assert "discord.com/users/123" in text and "999" not in text
    assert f"<@&{ROLE}>" in text  # the alert keeps its title, but the edit pings nobody


def test_expired_token_edits_the_message_directly_and_quietly(monkeypatch):
    monkeypatch.setattr(recruit_links, "resolve", AsyncMock(return_value=recruit_links.LinksResult()))
    ctx = _button_ctx("profile_refresh:123:0:a")
    ctx.respond = AsyncMock(side_effect=hikari.NotFoundError("u", hikari.impl.rest.__dict__.get("Headers", dict)(), b""))
    edit = AsyncMock()
    ctx.interaction.app.rest.edit_message = edit
    ctx.interaction.message = SimpleNamespace(channel_id=5, id=6)
    asyncio.run(profile.profile_refresh_handler(ctx=ctx, action_id="123:0:a", coc_client=object()))
    args, kwargs = edit.call_args
    assert args == (5, 6)
    assert kwargs["role_mentions"] is False and kwargs["user_mentions"] is False


def _long_entry(index, status=accounts.STATUS_LOADED, name=("[]_*~`()@" * 2)[:15],
                clan=("[]_*~`()|>" * 2)[:15]):
    if status != accounts.STATUS_LOADED:
        return accounts.AccountEntry(f"#L{index:02d}QQQQQ", status)
    account = todo_data.Account(tag=f"#L{index:02d}QQQQQ", name=name,
                                clan_tag=None, clan_name=clan, town_hall=17)
    return accounts.AccountEntry(account.tag, accounts.STATUS_LOADED, account)


@pytest.mark.parametrize("names", [None, "🔥" * 15, "🔥_" * 7 + "🔥"])
@pytest.mark.parametrize("mode", [profile.MODE_PROFILE, profile.MODE_ALERT])
def test_whole_message_text_stays_under_discord_limit_and_keeps_every_tag(mode, names):
    extra = {} if names is None else {"name": names, "clan": names}
    entries = (*(_long_entry(i, **extra) for i in range(60)),
               _long_entry(90, accounts.STATUS_ERROR), _long_entry(91, accounts.STATUS_NOT_FOUND))
    data = accounts.AccountsData(entries=entries, unavailable_sources=("ClashPerk",))
    identity = _identity(display_name="N" * 32, username="u" * 32)
    seen = []
    page, pages = 0, None
    while True:
        payload = _built(profile.render_profile(identity, data, page, mode=mode))
        total = sum(accounts.text_units(str(n["content"])) for n in _walk(payload) if "content" in n)
        assert total <= 4000
        seen.extend(re.findall(r"[\[`](#L\d+QQQQQ)[\]`]", _text(payload)))
        pages = int(re.search(r"Page \d+/(\d+)", json.dumps(payload)).group(1))
        page += 1
        if page >= pages:
            break
    assert sorted(seen) == sorted(entry.tag for entry in entries)


def test_listener_never_raises(monkeypatch):
    monkeypatch.setattr(new_warrior_alert, "post_alert", AsyncMock(side_effect=RuntimeError("boom")))
    event = SimpleNamespace(member=_member())
    asyncio.run(new_warrior_alert.new_warrior_joined(event, bot=object(), coc_client=object()))


def test_malformed_button_answers_privately_without_loading(monkeypatch):
    monkeypatch.setattr(recruit_links, "resolve", AsyncMock(side_effect=AssertionError))
    ctx = _button_ctx("profile_page:bad")
    assert asyncio.run(profile.profile_page_handler(ctx=ctx, action_id="bad", coc_client=object())) is None
    ctx.respond.assert_awaited_once_with("Run `/profile` again.", ephemeral=True)


def test_alert_page_keeps_alert_header():
    data = accounts.AccountsData(entries=(_entry(1),))
    payload = _built(profile.render_profile(_identity(), data, mode=profile.MODE_ALERT))
    text = _text(payload)
    assert text.startswith("# ⛩️ New Warrior at the Gate")
    assert f"<@&{ROLE}>" in text
    assert all(i.endswith(":a") for i in _custom_ids(payload))
    assert f"<@&{ROLE}>" not in _text(_built(profile.render_profile(_identity(), data)))


class _Ctx:
    def __init__(self, user):
        self.user = SimpleNamespace(id=999)
        self.guild_id = WARRIORS_UNITED_GUILD_ID
        self.defers, self.edits = [], []
        app = SimpleNamespace(cache=SimpleNamespace(get_member=lambda *_: None, get_user=lambda *_: None),
                              rest=SimpleNamespace(fetch_user=AsyncMock(side_effect=AssertionError)))
        self.interaction = SimpleNamespace(app=app, edit_initial_response=self._edit)

    async def defer(self, **kwargs):
        self.defers.append(kwargs)

    async def _edit(self, **kwargs):
        self.edits.append(kwargs)


@pytest.mark.parametrize("given", [None, "target"])
def test_command_is_public_mention_free_and_defaults_to_self(monkeypatch, given):
    seen = []

    async def resolve(discord_id, *, verify_owners=True):
        seen.append(discord_id)
        return recruit_links.LinksResult()

    monkeypatch.setattr(recruit_links, "resolve", resolve)
    target = SimpleNamespace(id=555, username="target", global_name=None,
                             display_avatar_url=None, created_at=CREATED)
    ctx = _Ctx(None)
    asyncio.run(profile.Profile.invoke(
        SimpleNamespace(discord_user=target if given else None), ctx, coc_client=object()))
    assert ctx.defers == [{"ephemeral": False}]
    assert seen == [555 if given else 999]
    edit = ctx.edits[0]
    assert edit["user_mentions"] is False and edit["role_mentions"] is False
    assert edit["mentions_everyone"] is False


def test_command_option_is_optional_native_discord_user_picker():
    options = profile.Profile._command_data.options
    assert set(options) == {"discord_user"}
    assert options["discord_user"].type is hikari.OptionType.USER
    assert options["discord_user"].default is None


def _member(guild=WARRIORS_UNITED_GUILD_ID, bot=False):
    return SimpleNamespace(id=123, guild_id=guild, is_bot=bot, username="warrior_one",
                           global_name="Warrior", display_name="Warrior",
                           display_avatar_url="https://cdn.discordapp.com/avatars/123/abc.png",
                           created_at=CREATED, joined_at=JOINED)


def _bot(side_effect=None):
    return SimpleNamespace(rest=SimpleNamespace(create_message=AsyncMock(side_effect=side_effect)))


def test_alert_posts_once_with_only_the_staff_role_ping(monkeypatch):
    monkeypatch.setattr(recruit_links, "resolve", AsyncMock(return_value=recruit_links.LinksResult()))
    monkeypatch.setattr(new_warrior_alert, "identity_from", lambda m: _identity())
    bot = _bot()
    assert asyncio.run(new_warrior_alert.post_alert(bot, _member(), object())) is True
    bot.rest.create_message.assert_awaited_once()
    args, kwargs = bot.rest.create_message.call_args
    assert args == (NEW_WARRIOR_ALERT_CHANNEL_ID,)
    assert kwargs["role_mentions"] == [ROLE]
    assert kwargs["user_mentions"] is False and kwargs["mentions_everyone"] is False
    text = _text(_built(kwargs["components"]))
    assert "# ⛩️ New Warrior at the Gate" in text and "No linked accounts" in text and "<@123>" not in text


@pytest.mark.parametrize("member", [_member(guild=1), _member(bot=True)])
def test_alert_skips_other_guilds_and_bots(monkeypatch, member):
    monkeypatch.setattr(recruit_links, "resolve", AsyncMock(side_effect=AssertionError))
    bot = _bot()
    assert asyncio.run(new_warrior_alert.post_alert(bot, member, object())) is False
    bot.rest.create_message.assert_not_awaited()


def test_lookup_failure_still_posts_incomplete_alert(monkeypatch):
    monkeypatch.setattr(recruit_links, "resolve", AsyncMock(side_effect=RuntimeError("down")))
    monkeypatch.setattr(new_warrior_alert, "identity_from", lambda m: _identity())
    bot = _bot()
    assert asyncio.run(new_warrior_alert.post_alert(bot, _member(), object())) is True
    text = _text(_built(bot.rest.create_message.call_args.kwargs["components"]))
    assert "Could not reach ClashKing, ClashPerk" in text
    assert "No linked accounts" not in text


def test_send_failure_is_logged_and_not_retried(monkeypatch):
    monkeypatch.setattr(recruit_links, "resolve", AsyncMock(return_value=recruit_links.LinksResult()))
    monkeypatch.setattr(new_warrior_alert, "identity_from", lambda m: _identity())
    bot = _bot(side_effect=hikari.HTTPError("send failed"))
    assert asyncio.run(new_warrior_alert.post_alert(bot, _member(), object())) is False
    assert bot.rest.create_message.await_count == 1


def test_manage_links_forget_clears_merged_cache():
    accounts.remember_merged(123, accounts.AccountsData())
    accounts.forget(123, None)
    assert accounts.cached_merged(123) is None
