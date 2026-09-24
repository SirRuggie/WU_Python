"""Integration boundaries for the LazyCWL dashboard.

These assertions deliberately serialize real Hikari builders and dispatch
through the shared component router, rather than only calling render helpers.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
from bson import ObjectId

from extensions import components as component_router
from extensions.commands import lazycwl_dashboard as dashboard
from extensions.commands.fwa import lazy_cwl_service as service
from tests.test_lazy_cwl_service import _fake_mongo, _list_doc


def _nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nodes(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _nodes(child)


def _walk_text(value):
    if isinstance(value, dict):
        if isinstance(value.get("content"), str):
            yield value["content"]
        for child in value.values():
            yield from _walk_text(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_text(child)


def _active(list_id, tag):
    document = _list_doc(list_id, clan_tag=tag)
    document["section"] = "FWA"
    document["expires_at"] = datetime.now(timezone.utc) + timedelta(days=3)
    return document


def _session():
    dashboard._sessions.clear()
    return dashboard._session(owner=10, guild=20)


def test_section_clan_queries_use_live_main_categories_and_keep_fwa_strict(monkeypatch):
    mongo = _fake_mongo(clans=[
        {"_id": 1, "tag": "#FWA", "name": "FWA", "type": "FWA"},
        {"_id": 2, "tag": "#TAC", "name": "Tactical", "type": "Tactical"},
        {"_id": 3, "tag": "#FUN", "name": "Fun", "type": "Flexible Fun"},
        {"_id": 4, "tag": "#OLD", "name": "Legacy", "type": "Competitive"},
        {"_id": 5, "tag": "#HOST", "name": "Host", "type": "CWL Hosting"},
        {"_id": 6, "name": "No tag", "type": "Tactical"},
    ])
    queries = []
    original_find = mongo.clans.find
    def find(query):
        queries.append(query)
        return original_find(query)
    monkeypatch.setattr(mongo.clans, "find", find)

    token = _session()
    fwa = asyncio.run(dashboard._clans(mongo, token))
    dashboard._sessions[token]["section"] = "MAIN"
    main = asyncio.run(dashboard._clans(mongo, token))

    assert queries == [
        {"type": "FWA"},
        {"type": {"$in": ["Tactical", "Flexible Fun", "Competitive"]}},
    ]
    assert [clan["tag"] for clan in fwa] == ["#FWA"]
    assert [clan["tag"] for clan in main] == ["#FUN", "#OLD", "#TAC"]


def test_serialized_24_clan_and_50_player_panels_fit_discord_and_do_not_silently_truncate():
    token = _session()
    clans = [{"tag": f"#C{i:03}", "name": f"Clan {i:03}"} for i in range(24)]
    document = _active(ObjectId(), "#C000")
    document["players"] = [
        {"tag": f"#P{i:03}", "name": f"Player {i:03}", "town_hall": 16}
        for i in range(50)
    ]

    home = dashboard.render_home([document], clans, "ALL", token=token, tab="reminders")
    payload = [item.build() for item in home]
    nodes = list(_nodes(payload))
    assert len([node for node in nodes if "type" in node]) <= 40
    assert all(len(node["custom_id"]) <= 100 for node in nodes if "custom_id" in node)
    assert "Showing the first" not in "\n".join(_walk_text(payload))

    mongo = _fake_mongo([document])
    page = asyncio.run(dashboard._player_page(mongo, token, "#C000", 2))
    page_payload = [item.build() for item in page]
    page_text = "\n".join(_walk_text(page_payload))
    assert "page 3 of 3" in page_text
    assert "Player 040" in page_text and "Player 049" in page_text
    assert len([node for node in _nodes(page_payload) if "type" in node]) <= 40
    assert all(len(node["custom_id"]) <= 100 for node in _nodes(page_payload) if "custom_id" in node)


def test_bound_confirmation_uses_raw_bson_id_and_is_one_shot(monkeypatch):
    token = _session()
    object_id = ObjectId()
    document = _active(object_id, "#ABC")
    mongo = _fake_mongo([document])
    nonce = dashboard._bind(token, "#ABC", [document], operation="send")
    calls = []

    async def remind(tag, *, expected_list_id=None, section=None):
        assert section == "FWA"
        calls.append((tag, expected_list_id))
        return {"ok": True}

    monkeypatch.setattr(service, "remind_now", remind)
    asyncio.run(dashboard._apply_bound(mongo, token, nonce, "send", None))
    asyncio.run(dashboard._apply_bound(mongo, token, nonce, "send", None))

    assert calls == [("#ABC", object_id)]


def test_forged_cross_operation_confirmation_is_refused_without_service_call(monkeypatch):
    token = _session()
    document = _active(ObjectId(), "#ABC")
    mongo = _fake_mongo([document])
    nonce = dashboard._bind(token, "#ABC", [document], operation="close")
    called = []

    async def remind(*args, **kwargs):
        called.append(True)
        return {"ok": True}

    monkeypatch.setattr(service, "remind_now", remind)
    response = asyncio.run(dashboard._apply_bound(mongo, token, nonce, "send", None))
    assert called == []
    assert "does not match" in "\n".join(_walk_text([item.build() for item in response]))


def test_allow_binds_admin_session_to_owner_and_guild():
    token = _session()
    admin = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)

    class Ctx:
        def __init__(self, user=10, guild=20, member=admin):
            self.user = SimpleNamespace(id=user)
            self.member = member
            self.interaction = SimpleNamespace(user=self.user, guild_id=guild, member=member)
            self.responses = []
        async def respond(self, text, **kwargs): self.responses.append(text)

    assert asyncio.run(dashboard._allow(Ctx(), token)) is True
    assert asyncio.run(dashboard._allow(Ctx(user=11), token)) is False
    assert asyncio.run(dashboard._allow(Ctx(guild=21), token)) is False
    assert asyncio.run(dashboard._allow(Ctx(member=SimpleNamespace(permissions=hikari.Permissions.NONE)), token)) is False


def test_modal_submission_dispatches_real_shape_and_passes_raw_object_id(monkeypatch):
    token = _session()
    object_id = ObjectId()
    nonce = dashboard._bind(token, "#ABC", [_active(object_id, "#ABC")], operation="add")
    calls = []

    async def add(tag, player, *, expected_list_id=None, section=None):
        assert section == "FWA"
        calls.append((tag, player, expected_list_id))
        return {"ok": True, "error": None}

    async def home(*args, **kwargs): return []
    monkeypatch.setattr(service, "add_player_by_tag", add)
    monkeypatch.setattr(dashboard, "build_home", home)
    monkeypatch.setattr(dashboard, "_player_page", home)
    # The production dispatcher supplies this through Lightbulb DI.  Replace
    # only the registered callable with the undecorated handler so this test
    # can exercise the router using a lightweight interaction fixture.
    action = component_router.registered_functions["lazycwl_add_submit"]
    monkeypatch.setitem(
        component_router.registered_functions,
        "lazycwl_add_submit",
        replace(action, fn=dashboard.handle_add_submit.__wrapped__._func),
    )
    async def no_component_state(*args, **kwargs): return None
    monkeypatch.setattr(component_router, "get_state", no_component_state)

    admin = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)
    field = SimpleNamespace(custom_id="player_tag", value="#P123")
    interaction = SimpleNamespace(
        custom_id=dashboard._id("lazycwl_add_submit", token, nonce), user=SimpleNamespace(id=10), guild_id=20,
        member=admin, components=[SimpleNamespace(components=[field])], created=[], edited=[],
    )
    async def create(response_type): interaction.created.append(response_type)
    async def edit_initial_response(**kwargs): interaction.edited.append(kwargs)
    interaction.create_initial_response = create
    interaction.edit_initial_response = edit_initial_response

    class Ctx:
        user = interaction.user
        member = admin
        async def respond(self, *args, **kwargs): raise AssertionError("modal should update original panel")
    ctx = Ctx(); ctx.interaction = interaction
    asyncio.run(component_router._dispatch(ctx, _fake_mongo()))

    assert calls == [("#ABC", "#P123", object_id)]
    assert interaction.created == [hikari.ResponseType.DEFERRED_MESSAGE_UPDATE]
    assert len(interaction.edited) == 1


def test_badge_status_and_bulk_capture_are_visible_without_implicit_selection():
    token = _session()
    document = _active(ObjectId(), '#ABC')
    document['players'] = [{'tag': '#P1', 'name': 'Player'}]
    clans = [{'tag': '#ABC', 'name': 'Home', 'logo': 'https://example.com/badge.png'},
             {'tag': '#DEF', 'name': 'New clan'}]
    panel = dashboard.render_home([document], clans, '#ABC', away_counts={'#ABC': 0}, token=token)
    payload = [item.build() for item in panel]
    assert 'Everyone returned' in '\n'.join(_walk_text(payload))
    assert any(node.get('url') == 'https://example.com/badge.png' for node in _nodes(payload))
    assert panel[0].accent_color == dashboard.GOLD_ACCENT
    no_list = dashboard.render_home([document], clans, '#DEF', token=token)
    assert no_list[0].accent_color == dashboard.GOLD_ACCENT
    bulk = dashboard.render_home([document], clans, 'ALL', token=token)
    capture = next(node for node in _nodes([item.build() for item in bulk])
                   if str(node.get('custom_id', '')).startswith('lazycwl_capture:'))
    assert not capture.get('disabled', False)


def test_cancel_invalidates_confirmation_and_returns_to_reminders(monkeypatch):
    token = _session()
    doc = _active(ObjectId(), '#ABC')
    nonce = dashboard._bind(token, '#ABC', [doc], operation='disable')
    dashboard._confirm('Disable?', ['Home'], 'lazycwl_disable_yes', token, nonce, dashboard.RED_ACCENT)
    screens = []
    async def home(mongo, tag, **kwargs):
        screens.append((tag, kwargs['tab']))
        return []
    monkeypatch.setattr(dashboard, 'build_home', home)
    ctx = SimpleNamespace(user=SimpleNamespace(id=10), member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR), interaction=SimpleNamespace(guild_id=20))
    asyncio.run(dashboard.handle_cancel(ctx=ctx, action_id=f'{token}|{nonce}', mongo=object()))
    assert screens == [('#ABC', 'reminders')]
    assert dashboard._parse_bound(token, nonce) is None


def test_remove_entire_page_passes_exact_list_and_returns_to_same_page(monkeypatch):
    token = _session()
    doc = _active(ObjectId(), '#ABC')
    doc['players'] = [{'tag': f'#P{i}', 'name': f'Player{i}'} for i in range(40)]
    mongo = _fake_mongo([doc])
    chosen = [p['tag'] for p in doc['players'][20:40]]
    ctx = SimpleNamespace(user=SimpleNamespace(id=10), member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR), interaction=SimpleNamespace(guild_id=20, values=chosen))
    reviewed = asyncio.run(dashboard.handle_remove_pick(ctx=ctx, action_id=f'{token}|#ABC,1', mongo=mongo))
    confirm = next(node['custom_id'] for node in _nodes([item.build() for item in reviewed])
                   if str(node.get('custom_id', '')).startswith('lazycwl_remove_yes:'))
    calls, pages = [], []
    async def remove(mongo, tag, players, *, expected_list_id, section):
        assert section == "FWA"
        calls.append((tag, players, expected_list_id))
        return len(players)
    async def page(mongo, token, tag, page, note=None):
        pages.append(page)
        return []
    monkeypatch.setattr(dashboard.store, 'remove_players', remove)
    monkeypatch.setattr(dashboard, '_player_page', page)
    asyncio.run(dashboard.handle_remove_yes(ctx=ctx, action_id=confirm.partition(':')[2], mongo=mongo))
    assert calls == [('#ABC', chosen, doc['_id'])]
    assert pages == [1]


def test_full_bulk_review_and_reminders_fit_text_budget(monkeypatch):
    token = _session()
    docs = [_active(ObjectId(), f'#C{i:03}') for i in range(24)]
    for doc in docs:
        doc['clan_name'] = 'A long clan display name ' * 4
    clans = [{'tag': d['clan_tag'], 'name': d['clan_name']} for d in docs]
    panel = dashboard.render_home(docs, clans, 'ALL', token=token, tab='reminders')
    payload = [item.build() for item in panel]
    assert sum(len(text) for text in _walk_text(payload)) <= 4000
    async def active(mongo, *, section):
        assert section == "FWA"
        return docs
    monkeypatch.setattr(dashboard.store, 'list_active', active)
    review = asyncio.run(dashboard._review(object(), token, 'ALL', 'close'))
    review_payload = [item.build() for item in review]
    assert sum(len(text) for text in _walk_text(review_payload)) <= 4000
    assert all(len(node['custom_id']) <= 100 for node in _nodes(review_payload) if 'custom_id' in node)
    assert len(next(iter(dashboard._sessions[token]['pending'].values()))['ids']) == 24
