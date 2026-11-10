"""Discord flow for saving a /fwa weight result. Bridge, Mongo and Discord are isolated fakes."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.fwa import weight, weight_save as flow
from utils import clashperk_link_writes, war_weight
from cwl_web.providers import tag as normalize
from utils.clan_weight_client import WeightClientError

LOOT = 30000  # 150,000 = TH15 in the default ranges.


def run(coro):
    return asyncio.run(coro)


class Collection:
    def __init__(self):
        self.rows = {}

    @staticmethod
    def matches(row, query):
        for key, expected in query.items():
            if isinstance(expected, dict) and "$ne" in expected:
                if row.get(key) == expected["$ne"]:
                    return False
            elif isinstance(expected, dict) and "$not" in expected:
                value = row.get(key)
                if value is not None and value > expected["$not"]["$gt"]:
                    return False
            elif row.get(key) != expected:
                return False
        return True

    async def find_one(self, query, projection=None):
        row = self.rows.get(query.get("_id"))
        return dict(row) if row and self.matches(row, query) else None

    async def insert_one(self, document):
        self.rows[document["_id"]] = dict(document)

    async def update_one(self, query, update, upsert=False):
        row = self.rows.get(query.get("_id"))
        if row is None or not self.matches(row, query):
            return SimpleNamespace(matched_count=0, modified_count=0, upserted_id=None)
        row.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1, modified_count=1, upserted_id=None)

    async def delete_one(self, query):
        self.rows.pop(query.get("_id"), None)


class Bridge:
    def __init__(self):
        self.calls = []
        self.allowed = True
        self.accounts = [
            {"tag": "#P2Y", "name": "Alpha", "town_hall": 15, "clan_name": "Family",
             "available": True, "weight": None, "revision": 0},
            {"tag": "#Q2Y", "name": "Beta", "town_hall": 14, "clan_name": None,
             "available": True, "weight": 140000, "revision": 2},
        ]
        self.error = {}

    async def __call__(self, action, *, actor_id, **payload):
        self.calls.append((action, payload))
        if action in self.error:
            raise self.error[action]
        if action == "access":
            if not self.allowed:
                raise WeightClientError("You need weight saving access.", code="forbidden")
            return {"allowed": True}
        if action == "accounts":
            return {"accounts": [dict(a) for a in self.accounts], "hidden": 0}
        if action == "lookup":
            for account in self.accounts:
                if account["tag"] == payload["tag"]:
                    return {"account": dict(account)}
            return {"account": {"tag": normalize(payload["tag"]), "name": "Typed", "town_hall": 15,
                                "clan_name": None, "available": True, "weight": None, "revision": 0}}
        if action == "save":
            account = next((a for a in self.accounts if a["tag"] == payload["tag"]), {"tag": payload["tag"], "name": "Typed"})
            changed = account.get("weight") != payload["weight"]
            return {"account": {**account, "weight": payload["weight"], "revision": payload["revision"] + 1},
                    "changed": changed}
        raise AssertionError(action)


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def confirm_token(view):
    ids = [value for value in custom_ids(view) if value.startswith("fws_confirm:")]
    assert len(ids) == 1, ids
    return ids[0].partition(":")[2]


def built(components):
    return [component.build()[0] for component in components]


def text_of(components):
    return "\n".join(n.get("content", "") for n in walk(built(components)))


def custom_ids(components):
    return [n["custom_id"] for n in walk(built(components)) if "custom_id" in n]


@pytest.fixture
def env(monkeypatch):
    bridge = Bridge()
    monkeypatch.setattr(flow, "bridge", bridge)
    monkeypatch.setattr(war_weight, "load", AsyncMock(return_value=war_weight.defaults()))
    links = Links()
    monkeypatch.setattr(flow.clashperk_link_writes, "create_link", links)
    mongo = SimpleNamespace(component_state=Collection(), button_store=Collection())
    bot = SimpleNamespace(cache=SimpleNamespace(get_emojis_view=lambda: {}),
                          rest=SimpleNamespace(create_message=AsyncMock()))
    return SimpleNamespace(bridge=bridge, mongo=mongo, bot=bot, links=links)


class Links:
    """Fake ClashPerk link helper. Never reaches ClashPerk."""

    def __init__(self):
        self.calls = []
        self.status = clashperk_link_writes.LINKED
        self.message = "Linked in ClashPerk."

    async def __call__(self, user_id, player_tag):
        self.calls.append((user_id, player_tag))
        return clashperk_link_writes.LinkResult(self.status, player_tag, self.message)


def slash_ctx():
    return SimpleNamespace(
        user=SimpleNamespace(id=300, username="staff"), guild_id=2, channel_id=3,
        defer=AsyncMock(),
        interaction=SimpleNamespace(edit_initial_response=AsyncMock(), delete_initial_response=AsyncMock(),
                                    member=SimpleNamespace(display_name="Staff"), guild_id=2),
    )


def component_ctx(values=(), user=300, fields=None):
    interaction = SimpleNamespace(
        guild_id=2, values=list(values), member=SimpleNamespace(display_name="Staff"),
        create_initial_response=AsyncMock(), edit_initial_response=AsyncMock(),
        components=[[SimpleNamespace(custom_id=k, value=v) for k, v in (fields or {}).items()]],
    )
    return SimpleNamespace(user=SimpleNamespace(id=user, username="staff"), interaction=interaction,
                           respond_with_modal=AsyncMock(), respond=AsyncMock())


def start(env, loot=LOOT):
    ctx = slash_ctx()
    target = SimpleNamespace(id=100)
    run(weight.WeightCommand.invoke(SimpleNamespace(weight=loot, user=target), ctx, env.bot, env.mongo))
    components = ctx.interaction.edit_initial_response.call_args.kwargs["components"]
    sid = next(iter(env.mongo.component_state.rows), None)
    return ctx, components, sid


def call(handler, ctx, sid, env):
    return run(handler.__wrapped__(ctx, sid, mongo=env.mongo, bot=env.bot)
               if hasattr(handler, "__wrapped__") else handler(ctx, sid, mongo=env.mongo, bot=env.bot))


def posted(env):
    return [text_of(c.kwargs["components"]) for c in env.bot.rest.create_message.call_args_list]


def test_without_user_posts_immediately_with_no_question(env):
    ctx = slash_ctx()
    run(weight.WeightCommand.invoke(SimpleNamespace(weight=LOOT, user=None), ctx, env.bot, env.mongo))
    assert len(posted(env)) == 1 and "Saved for" not in posted(env)[0]
    assert env.bridge.calls == []
    ctx.interaction.delete_initial_response.assert_awaited_once()


def test_without_permission_posts_at_once_with_private_line(env):
    env.bridge.allowed = False
    ctx, components, sid = start(env)
    assert sid is None
    assert len(posted(env)) == 1
    assert "You need weight saving access." in text_of(components)
    assert "Panel posted. Nothing was saved." in text_of(components)


def test_question_offers_save_and_post_only_without_posting(env):
    _, components, sid = start(env)
    assert posted(env) == []
    assert "150,000" in text_of(components) and "TH15" in text_of(components)
    assert "Save this weight for <@100>?" in text_of(components)
    assert custom_ids(components) == [f"fws_save:{sid}", f"fws_post:{sid}"]


def test_invalid_multiple_offers_post_only(env):
    _, components, sid = start(env, loot=34850)
    assert "Cannot save 174,250. Saved weights must be a multiple of 1,000. Check the loot value." in text_of(components)
    assert custom_ids(components) == [f"fws_post:{sid}"]


def test_post_only_posts_once_even_on_double_click(env):
    _, _, sid = start(env)
    first = call(flow.on_post, component_ctx(), sid, env)
    second = call(flow.on_post, component_ctx(), sid, env)
    assert "Panel posted. Nothing was saved." in text_of(first)
    assert "already handled" in text_of(second)
    assert len(posted(env)) == 1
    assert not [c for c in env.bridge.calls if c[0] == "save"]


def test_other_user_cannot_use_the_session(env):
    _, _, sid = start(env)
    result = call(flow.on_post, component_ctx(user=999), sid, env)
    assert "expired" in text_of(result)
    assert posted(env) == []


def test_accounts_dropdown_lists_links_and_other_account(env):
    _, _, sid = start(env)
    view = call(flow.on_save, component_ctx(), sid, env)
    menu = next(n for n in walk(built(view)) if n.get("custom_id") == f"fws_pick:{sid}")
    values = [o["value"] for o in menu["options"]]
    assert values == ["#P2Y", "#Q2Y", "other"]
    assert menu["options"][0]["label"] == "Alpha · TH15"
    assert menu["options"][1]["description"] == "#Q2Y · Saved 140,000"
    assert menu["options"][0].get("emoji")  # Town Hall emoji on each linked account.


def test_no_links_and_link_outage_messages(env):
    _, _, sid = start(env)
    env.bridge.accounts = []
    view = call(flow.on_save, component_ctx(), sid, env)
    assert "This user has no linked accounts. Enter a player tag to link it in ClashPerk and save." in text_of(view)
    assert custom_ids(view) == [f"fws_tag:{sid}", f"fws_post:{sid}"]
    env.bridge.error["accounts"] = WeightClientError("Could not load linked accounts.", code="links_unavailable")
    view = call(flow.on_save, component_ctx(), sid, env)
    assert "Could not load linked accounts." in text_of(view)
    assert custom_ids(view) == [f"fws_retry:{sid}", f"fws_tag:{sid}", f"fws_post:{sid}"]


def test_unsaved_matching_account_saves_at_once_and_posts_with_saved_line(env):
    _, _, sid = start(env)
    pick = component_ctx(values=["#P2Y"])
    call(flow.on_pick, pick, sid, env)
    pick.interaction.create_initial_response.assert_awaited_once_with(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    result = text_of(pick.interaction.edit_initial_response.call_args.kwargs["components"])
    assert "Saved 150,000 for Alpha `#P2Y` (Family)." in result and "Panel posted." in result
    assert ("save", {"actor_name": "Staff", "tag": "#P2Y", "weight": 150000, "revision": 0}) in env.bridge.calls
    assert len(posted(env)) == 1 and "Saved for Alpha `#P2Y`" in posted(env)[0]
    # A late second click cannot post or save again.
    again = call(flow.on_post, component_ctx(), sid, env)
    assert "already handled" in text_of(again) and len(posted(env)) == 1


def test_different_saved_weight_and_th_mismatch_need_confirmation(env):
    _, _, sid = start(env)
    pick = component_ctx(values=["#Q2Y"])
    call(flow.on_pick, pick, sid, env)
    view = pick.interaction.edit_initial_response.call_args.kwargs["components"]
    text = text_of(view)
    assert "Saved: 140,000 → New: 150,000" in text
    assert "This account is TH14. The weight is TH15." in text
    token = confirm_token(view)
    assert custom_ids(view) == [f"fws_confirm:{token}", f"fws_back:{sid}"]
    assert [n["label"] for n in walk(built(view)) if n.get("custom_id") == f"fws_confirm:{token}"] == ["Replace"]
    assert not [c for c in env.bridge.calls if c[0] == "save"] and posted(env) == []
    done = call(flow.on_confirm, component_ctx(), token, env)
    assert "Saved 150,000 for Beta `#Q2Y` (No clan)." in text_of(done)
    assert ("save", {"actor_name": "Staff", "tag": "#Q2Y", "weight": 150000, "revision": 2}) in env.bridge.calls


def test_unsaved_th_mismatch_still_asks(env):
    env.bridge.accounts[1]["weight"] = None
    _, _, sid = start(env)
    pick = component_ctx(values=["#Q2Y"])
    call(flow.on_pick, pick, sid, env)
    view = pick.interaction.edit_initial_response.call_args.kwargs["components"]
    assert "New: 150,000" in text_of(view) and "TH14" in text_of(view)
    token = confirm_token(view)
    assert [n["label"] for n in walk(built(view)) if n.get("custom_id") == f"fws_confirm:{token}"] == ["Save"]


def preview(env, sid, tag):
    pick = component_ctx(values=[tag])
    call(flow.on_pick, pick, sid, env)
    return pick.interaction.edit_initial_response.call_args.kwargs["components"]


def test_old_confirm_button_cannot_save_the_newer_preview(env):
    # Stella's repro: preview Alpha, Back, preview Beta, then select Alpha's old button.
    env.bridge.accounts[0]["weight"] = 120000
    _, _, sid = start(env)
    alpha = confirm_token(preview(env, sid, "#P2Y"))
    call(flow.on_back, component_ctx(), sid, env)
    beta = confirm_token(preview(env, sid, "#Q2Y"))
    assert alpha != beta
    stale = call(flow.on_confirm, component_ctx(), alpha, env)
    assert "This confirm button is out of date. Select the account again." in text_of(stale)
    assert custom_ids(stale) == [f"fws_back:{sid}", f"fws_post:{sid}"]
    assert not [c for c in env.bridge.calls if c[0] == "save"] and posted(env) == []
    done = call(flow.on_confirm, component_ctx(), beta, env)
    assert "Saved 150,000 for Beta `#Q2Y`" in text_of(done)
    assert [c[1]["tag"] for c in env.bridge.calls if c[0] == "save"] == ["#Q2Y"]


def test_back_voids_the_old_confirm_button(env):
    # Stella's repro: preview Alpha, Back, then select Alpha's old Replace button.
    env.bridge.accounts[0]["weight"] = 140000
    _, _, sid = start(env)
    token = confirm_token(preview(env, sid, "#P2Y"))
    call(flow.on_back, component_ctx(), sid, env)
    stale = call(flow.on_confirm, component_ctx(), token, env)
    assert "This confirm button is out of date." in text_of(stale)
    assert not [c for c in env.bridge.calls if c[0] == "save"] and posted(env) == []


@pytest.mark.parametrize("leave", ["retry", "tag_lookup", "post", "failed_save", "used_once"])
def test_every_way_out_of_a_preview_voids_its_button(env, leave):
    env.bridge.accounts[0]["weight"] = 140000
    _, _, sid = start(env)
    token = confirm_token(preview(env, sid, "#P2Y"))
    if leave == "retry":
        call(flow.on_retry, component_ctx(), sid, env)
    elif leave == "tag_lookup":
        call(flow.on_tagged, component_ctx(fields={"tag": "#U2Y"}), sid, env)
        env.bridge.calls.clear()
    elif leave == "post":
        call(flow.on_post, component_ctx(), sid, env)
    elif leave == "failed_save":
        env.bridge.error["save"] = WeightClientError("Changed by someone else. Try again.", code="conflict")
        call(flow.on_confirm, component_ctx(), token, env)
        env.bridge.error.clear()
        env.bridge.calls.clear()
    elif leave == "used_once":
        call(flow.on_confirm, component_ctx(), token, env)
        env.bridge.calls.clear()
    before = len(posted(env))
    result = call(flow.on_confirm, component_ctx(), token, env)
    assert "out of date" in text_of(result) or "already handled" in text_of(result)
    assert not [c for c in env.bridge.calls if c[0] == "save"]
    assert len(posted(env)) == before


def test_confirm_button_is_bound_to_its_owner(env):
    env.bridge.accounts[0]["weight"] = 120000
    _, _, sid = start(env)
    token = confirm_token(preview(env, sid, "#P2Y"))
    other = call(flow.on_confirm, component_ctx(user=999), token, env)
    assert "expired" in text_of(other)
    assert not [c for c in env.bridge.calls if c[0] == "save"]


def test_concurrent_saves_in_one_session_write_once(env):
    # Stella's repro: two account selections at the same time, both unsaved TH15.
    env.bridge.accounts[1].update(town_hall=15, weight=None)
    gate = asyncio.Event()
    original = env.bridge.__call__

    async def slow(action, **kwargs):
        if action == "save":
            await gate.wait()
        return await original(action, **kwargs)

    flow.bridge = slow
    _, _, sid = start(env)
    state = env.mongo.component_state.rows[sid]

    async def both():
        first = asyncio.create_task(flow.choose(component_ctx(), env.bot, env.mongo, dict(state), "#P2Y", LOOT))
        second = asyncio.create_task(flow.choose(component_ctx(), env.bot, env.mongo, dict(state), "#Q2Y", LOOT))
        await asyncio.sleep(0.01)
        gate.set()
        return await asyncio.gather(first, second)

    results = [text_of(r) for r in run(both())]
    assert len([c for c in env.bridge.calls if c[0] == "save"]) == 1
    assert len(posted(env)) == 1
    assert any("still running" in text for text in results)
    assert any("Saved 150,000 for Alpha `#P2Y`" in text for text in results)


def test_post_only_waits_for_a_running_save(env):
    _, _, sid = start(env)
    lock = run(flow.lock_save(env.mongo, sid))
    assert lock and run(flow.lock_save(env.mongo, sid)) is None
    blocked = call(flow.on_post, component_ctx(), sid, env)
    assert "still running" in text_of(blocked) and posted(env) == []
    run(flow.unlock_save(env.mongo, sid, lock))
    assert "Panel posted. Nothing was saved." in text_of(call(flow.on_post, component_ctx(), sid, env))


def test_failed_save_releases_the_lock(env):
    env.bridge.error["save"] = WeightClientError("Changed by someone else. Try again.", code="conflict")
    _, _, sid = start(env)
    preview(env, sid, "#P2Y")
    assert run(flow.lock_save(env.mongo, sid)) is not None


def test_same_weight_already_saved_writes_nothing(env):
    env.bridge.accounts[0]["weight"] = 150000
    _, _, sid = start(env)
    pick = component_ctx(values=["#P2Y"])
    call(flow.on_pick, pick, sid, env)
    assert "Already saved for Alpha `#P2Y`." in text_of(pick.interaction.edit_initial_response.call_args.kwargs["components"])
    assert not [c for c in env.bridge.calls if c[0] == "save"]
    assert len(posted(env)) == 1


@pytest.mark.parametrize("error", [
    WeightClientError("Changed by someone else. Try again.", code="conflict"),
    WeightClientError("The save could not be confirmed. Select Try again to check the saved weight.",
                      code="uncertain", uncertain=True),
])
def test_conflict_or_uncertain_save_offers_retry_and_posts_nothing(env, error):
    env.bridge.error["save"] = error
    _, _, sid = start(env)
    pick = component_ctx(values=["#P2Y"])
    call(flow.on_pick, pick, sid, env)
    view = pick.interaction.edit_initial_response.call_args.kwargs["components"]
    assert str(error) in text_of(view)
    assert custom_ids(view) == [f"fws_retry:{sid}", f"fws_post:{sid}"]
    assert posted(env) == []
    # The session stays open so Try again can re-read the saved weight.
    assert env.mongo.component_state.rows[sid]["done"] is False


def test_other_account_opens_tag_modal_and_typed_tag_is_looked_up(env):
    _, _, sid = start(env)
    pick = component_ctx(values=["other"])
    call(flow.on_pick, pick, sid, env)
    pick.respond_with_modal.assert_awaited_once()
    assert pick.respond_with_modal.call_args.kwargs["custom_id"] == f"fws_tagged:{sid}"
    pick.interaction.create_initial_response.assert_not_awaited()
    submit = component_ctx(fields={"tag": " #u2y "})
    call(flow.on_tagged, submit, sid, env)
    assert ("lookup", {"tag": "#u2y"}) in env.bridge.calls
    view = submit.interaction.edit_initial_response.call_args.kwargs["components"]
    assert "Typed `#U2Y` · TH15" in text_of(view)  # Staff see the account before any link.
    done = call(flow.on_confirm, component_ctx(), confirm_token(view), env)
    assert "Saved 150,000 for Typed `#U2Y` (No clan)." in text_of(done)


def test_lookup_error_keeps_session_and_offers_back(env):
    env.bridge.error["lookup"] = WeightClientError("No player was found with that tag.", code="not_found")
    _, _, sid = start(env)
    submit = component_ctx(fields={"tag": "#2PP"})
    call(flow.on_tagged, submit, sid, env)
    view = submit.interaction.edit_initial_response.call_args.kwargs["components"]
    assert "No player was found with that tag." in text_of(view)
    assert custom_ids(view) == [f"fws_back:{sid}", f"fws_post:{sid}"]


def test_player_names_render_as_inert_text(env):
    env.bridge.accounts[0]["name"] = "**@everyone** <@1>"
    _, _, sid = start(env)
    pick = component_ctx(values=["#P2Y"])
    call(flow.on_pick, pick, sid, env)
    text = posted(env)[0]
    assert "@everyone" not in text.replace("@​everyone", "") and "<@1>" not in text
    for call_args in env.bot.rest.create_message.call_args_list:
        assert call_args.kwargs["user_mentions"] is False and call_args.kwargs["mentions_everyone"] is False


def test_claim_is_atomic_under_concurrent_clicks(env):
    _, _, sid = start(env)

    async def both():
        return await asyncio.gather(flow.claim(env.mongo, sid), flow.claim(env.mongo, sid))

    assert sorted(run(both())) == [False, True]


def test_weight_outside_ranges_always_confirms_with_warning(env):
    # 181,000 is above the default TH18 range: no account TH can match it.
    _, _, sid = start(env, loot=36200)
    pick = component_ctx(values=["#P2Y"])
    call(flow.on_pick, pick, sid, env)
    view = pick.interaction.edit_initial_response.call_args.kwargs["components"]
    assert "This account is TH15. The weight is outside the Town Hall ranges." in text_of(view)
    assert not [c for c in env.bridge.calls if c[0] == "save"]


def test_th_warning_rules():
    ranges = war_weight.ranges(war_weight.defaults())
    assert flow.th_warning(15, "exact", ranges, 15) is None
    assert flow.th_warning(15, "exact", ranges, None) is None
    assert flow.th_warning(15, "between", ranges, 16) is None
    assert flow.th_warning(15, "between", ranges, 14) == "⚠️ This account is TH14. The weight is between TH15 and TH16."
    assert "outside the Town Hall ranges" in flow.th_warning(None, "above", ranges, 18)


def test_access_removed_during_flow_posts_panel_once_and_saves_nothing(env):
    _, _, sid = start(env)
    env.bridge.error["save"] = WeightClientError("You need weight saving access.", code="forbidden")
    pick = component_ctx(values=["#P2Y"])
    call(flow.on_pick, pick, sid, env)
    text = text_of(pick.interaction.edit_initial_response.call_args.kwargs["components"])
    assert "Panel posted. Nothing was saved." in text and "You need weight saving access." in text
    assert len(posted(env)) == 1 and "Saved for" not in posted(env)[0]


def test_save_that_loses_race_to_post_only_still_reports_the_write(env):
    _, _, sid = start(env)
    state = env.mongo.component_state.rows[sid]
    run(flow.claim(env.mongo, sid))  # The save lock expired and Post only won first.
    result = run(flow.finish(component_ctx(), env.bot, env.mongo, dict(state),
                             {"tag": "#P2Y", "name": "Alpha", "clan_name": "Family"}, LOOT,
                             already=False, lock="expired-lock"))
    assert "Saved 150,000 for Alpha `#P2Y` (Family)." in text_of(result)
    assert "already posted without the saved line" in text_of(result)
    assert posted(env) == []


def test_session_store_failure_posts_panel(env, monkeypatch):
    monkeypatch.setattr(flow, "insert_state", AsyncMock(side_effect=RuntimeError("mongo down")))
    ctx, components, _ = start(env)
    assert len(posted(env)) == 1
    assert "Weight saving is unavailable now." in text_of(components)


def test_custom_ids_have_one_colon(env):
    _, components, sid = start(env)
    view = call(flow.on_save, component_ctx(), sid, env)
    for value in custom_ids(components) + custom_ids(view):
        assert value.count(":") == 1, value
    assert json.dumps(sid)  # State id is a plain string.


# ---------------------------------------------------------------- multi-account loop


def saved_first(env):
    """Round 1: save Alpha at once. Return (result view, next round id)."""
    _, _, sid = start(env)
    pick = component_ctx(values=["#P2Y"])
    call(flow.on_pick, pick, sid, env)
    view = pick.interaction.edit_initial_response.call_args.kwargs["components"]
    ids = custom_ids(view)
    assert len(ids) == 2 and ids[0].startswith("fws_another:"), ids
    following = ids[0].partition(":")[2]
    assert ids[1] == f"fws_done:{following}" and following != sid
    return view, following


def entry_token(ctx):
    custom_id = ctx.respond_with_modal.call_args.kwargs["custom_id"]
    assert custom_id.startswith("fws_entry:") and custom_id.count(":") == 1
    return custom_id.partition(":")[2]


def modal_fields(ctx):
    return [n["custom_id"] for n in walk([row.build()[0] for row in ctx.respond_with_modal.call_args.kwargs["components"]])
            if "custom_id" in n]


def test_save_asks_another_account(env):
    view, following = saved_first(env)
    assert "Another account?" in text_of(view)
    state = env.mongo.component_state.rows[following]
    assert state["loot"] is None and state["round"] == 2 and state["target_id"] == 100
    assert state["saved_tags"] == ["#P2Y"]


def test_another_account_lists_marks_and_has_no_post_only(env):
    _, following = saved_first(env)
    env.bridge.accounts[0]["weight"] = 150000
    view = call(flow.on_another, component_ctx(), following, env)
    menu = next(n for n in walk(built(view)) if n.get("custom_id") == f"fws_pick:{following}")
    descriptions = [o.get("description") for o in menu["options"]]
    assert descriptions[0] == "#P2Y · Saved 150,000 · Done now"
    assert descriptions[1] == "#Q2Y · Saved 140,000"
    assert f"fws_post:{following}" not in custom_ids(view)
    assert custom_ids(view)[-1] == f"fws_done:{following}"
    assert "Select the next account" in text_of(view)


def test_next_account_asks_weight_then_saves_and_posts_its_panel(env):
    _, following = saved_first(env)
    env.bridge.accounts[1].update(town_hall=15, weight=None)
    pick = component_ctx(values=["#Q2Y"])
    call(flow.on_pick, pick, following, env)
    pick.interaction.create_initial_response.assert_not_awaited()
    assert modal_fields(pick) == ["loot"]
    token = entry_token(pick)
    submit = component_ctx(fields={"loot": "29,000"})
    call(flow.on_entry, submit, token, env)
    view = submit.interaction.edit_initial_response.call_args.kwargs["components"]
    assert "Saved 145,000 for Beta `#Q2Y` (No clan)." in text_of(view)
    assert ("save", {"actor_name": "Staff", "tag": "#Q2Y", "weight": 145000, "revision": 2}) in env.bridge.calls
    assert len(posted(env)) == 2 and "Saved for Beta `#Q2Y`" in posted(env)[1]
    assert env.links.calls == []  # A listed linked account is never linked again.
    assert "Another account?" in text_of(view)


def test_all_weights_done_ends_the_loop_once(env):
    _, following = saved_first(env)
    done = call(flow.on_done, component_ctx(), following, env)
    assert "All weights done" in text_of(done) and "Alpha `#P2Y`" in text_of(done)
    again = call(flow.on_done, component_ctx(), following, env)
    assert "already handled" in text_of(again)
    late = call(flow.on_another, component_ctx(), following, env)
    assert "already handled" in text_of(late)
    assert len(posted(env)) == 1


@pytest.mark.parametrize("value,message", [
    ("abc", "Enter a storage weight from 1 to 100,000."),
    ("0", "Enter a storage weight from 1 to 100,000."),
    ("100001", "Enter a storage weight from 1 to 100,000."),
    ("34850", "Cannot save 174,250. Saved weights must be a multiple of 1,000."),
])
def test_bad_storage_weight_saves_nothing(env, value, message):
    _, following = saved_first(env)
    pick = component_ctx(values=["#Q2Y"])
    call(flow.on_pick, pick, following, env)
    submit = component_ctx(fields={"loot": value})
    call(flow.on_entry, submit, entry_token(pick), env)
    view = submit.interaction.edit_initial_response.call_args.kwargs["components"]
    assert message in text_of(view)
    assert custom_ids(view) == [f"fws_back:{following}", f"fws_done:{following}"]
    assert len([c for c in env.bridge.calls if c[0] == "save"]) == 1  # Only round 1.


def test_entry_token_is_bound_to_its_owner(env):
    _, following = saved_first(env)
    pick = component_ctx(values=["#Q2Y"])
    call(flow.on_pick, pick, following, env)
    submit = component_ctx(fields={"loot": "30000"}, user=999)
    call(flow.on_entry, submit, entry_token(pick), env)
    assert "expired" in text_of(submit.interaction.edit_initial_response.call_args.kwargs["components"])
    assert len([c for c in env.bridge.calls if c[0] == "save"]) == 1


def test_other_account_in_later_round_asks_tag_and_weight_then_links_and_saves(env):
    _, following = saved_first(env)
    pick = component_ctx(values=["other"])
    call(flow.on_pick, pick, following, env)
    assert modal_fields(pick) == ["tag", "loot"]
    submit = component_ctx(fields={"tag": "#u2y", "loot": "30000"})
    call(flow.on_entry, submit, entry_token(pick), env)
    view = submit.interaction.edit_initial_response.call_args.kwargs["components"]
    assert "🔗 Links to <@100> in ClashPerk first." in text_of(view) and env.links.calls == []
    text = text_of(call(flow.on_confirm, component_ctx(), confirm_token(view), env))
    assert env.links.calls == [(100, "#U2Y")]
    assert "🔗 Linked in ClashPerk." in text and "Saved 150,000 for Typed `#U2Y`" in text
    access = [i for i, c in enumerate(env.bridge.calls) if c[0] == "access"]
    saves = [i for i, c in enumerate(env.bridge.calls) if c[0] == "save"]
    assert access[-1] < saves[-1]  # Permission rechecked right before the link and save.


def typed(env, sid, tag):
    """First round: type a tag, return (confirm preview, result after Save)."""
    submit = component_ctx(fields={"tag": tag})
    call(flow.on_tagged, submit, sid, env)
    view = submit.interaction.edit_initial_response.call_args.kwargs["components"]
    return view, call(flow.on_confirm, component_ctx(), confirm_token(view), env)


def test_typed_tag_always_confirms_before_link_even_when_it_fits(env):
    # No saved weight and a fitting Town Hall: a listed account saves at once, a typed tag never does.
    _, _, sid = start(env)
    submit = component_ctx(fields={"tag": "#U2Y"})
    call(flow.on_tagged, submit, sid, env)
    view = submit.interaction.edit_initial_response.call_args.kwargs["components"]
    text = text_of(view)
    assert "## Confirm" in text and "Typed `#U2Y` · TH15" in text
    assert "🔗 Links to <@100> in ClashPerk first." in text
    assert env.links.calls == [] and not [c for c in env.bridge.calls if c[0] == "save"] and posted(env) == []
    token = confirm_token(view)
    assert custom_ids(view) == [f"fws_confirm:{token}", f"fws_back:{sid}"]
    call(flow.on_confirm, component_ctx(), token, env)
    assert env.links.calls == [(100, "#U2Y")]
    assert [c[1]["tag"] for c in env.bridge.calls if c[0] == "save"] == ["#U2Y"]


@pytest.mark.parametrize("status", [
    clashperk_link_writes.OTHER_OWNER, clashperk_link_writes.UNAVAILABLE,
    clashperk_link_writes.REJECTED, clashperk_link_writes.UNKNOWN,
])
def test_link_failure_saves_nothing_and_posts_nothing(env, status):
    env.links.status = status
    env.links.message = "This account is linked to a different Discord user in ClashPerk. Nothing was changed."
    _, _, sid = start(env)
    _, view = typed(env, sid, "#U2Y")
    assert "The weight was not saved." in text_of(view)
    assert custom_ids(view) == [f"fws_back:{sid}", f"fws_post:{sid}"]
    assert not [c for c in env.bridge.calls if c[0] == "save"] and posted(env) == []
    assert run(flow.lock_save(env.mongo, sid)) is not None  # The save slot is released.


def test_already_linked_typed_tag_still_saves(env):
    env.links.status = clashperk_link_writes.ALREADY_LINKED
    _, _, sid = start(env)
    _, done = typed(env, sid, "#U2Y")
    text = text_of(done)
    assert "🔗 Already linked in ClashPerk." in text and "Saved 150,000" in text


def test_typed_tag_with_same_weight_links_and_writes_no_weight(env):
    env.bridge.accounts[0]["weight"] = 150000
    _, _, sid = start(env)
    view, done = typed(env, sid, "#P2Y")
    assert "Already saved: 150,000" in text_of(view)
    assert [n["label"] for n in walk(built(view)) if str(n.get("custom_id", "")).startswith("fws_confirm:")] == ["Link"]
    text = text_of(done)
    assert env.links.calls == [(100, "#P2Y")]
    assert "Already saved for Alpha `#P2Y`." in text
    assert not [c for c in env.bridge.calls if c[0] == "save"]


def test_typed_tag_confirm_shows_link_and_links_only_on_confirm(env):
    _, _, sid = start(env)
    env.bridge.accounts.append({"tag": "#U2Y", "name": "Gamma", "town_hall": 13, "clan_name": None,
                                "available": True, "weight": None, "revision": 0})
    submit = component_ctx(fields={"tag": "#U2Y"})
    call(flow.on_tagged, submit, sid, env)
    view = submit.interaction.edit_initial_response.call_args.kwargs["components"]
    assert "🔗 Links to <@100> in ClashPerk first." in text_of(view)
    assert env.links.calls == []
    call(flow.on_back, component_ctx(), sid, env)
    assert env.links.calls == []  # Back writes no link.
    call(flow.on_tagged, submit, sid, env)
    token = confirm_token(submit.interaction.edit_initial_response.call_args.kwargs["components"])
    done = call(flow.on_confirm, component_ctx(), token, env)
    assert env.links.calls == [(100, "#U2Y")] and "Saved 150,000 for Gamma" in text_of(done)


def test_access_removed_before_link_writes_no_link(env):
    _, _, sid = start(env)
    original = env.bridge.__call__
    seen = {"lookup": False}

    async def revoke(action, **kwargs):
        if action == "lookup":
            seen["lookup"] = True
        elif action == "access" and seen["lookup"]:
            raise WeightClientError("You need weight saving access.", code="forbidden")
        return await original(action, **kwargs)

    flow.bridge = revoke
    _, done = typed(env, sid, "#U2Y")
    text = text_of(done)
    assert env.links.calls == []
    assert "Panel posted. Nothing was saved." in text
    assert len(posted(env)) == 1


def test_later_round_access_removed_posts_nothing_without_a_weight(env):
    _, following = saved_first(env)
    env.bridge.error["accounts"] = WeightClientError("You need weight saving access.", code="forbidden")
    view = call(flow.on_another, component_ctx(), following, env)
    assert "Nothing was saved." in text_of(view) and "Panel posted" not in text_of(view)
    assert len(posted(env)) == 1


def test_post_only_on_a_later_round_is_handled_and_posts_nothing(env):
    _, following = saved_first(env)
    result = call(flow.on_post, component_ctx(), following, env)
    assert flow.HANDLED in text_of(result)
    assert len(posted(env)) == 1  # Only round 1's panel.
    assert env.mongo.component_state.rows[following]["done"] is False  # The round stays open.


def test_loop_custom_ids_have_one_colon(env):
    view, following = saved_first(env)
    listing = call(flow.on_another, component_ctx(), following, env)
    for value in custom_ids(view) + custom_ids(listing):
        assert value.count(":") == 1, value
