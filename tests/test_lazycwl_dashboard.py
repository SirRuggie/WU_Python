from datetime import datetime, timedelta, timezone
import asyncio
from types import SimpleNamespace

import hikari

from hikari.impl import ContainerComponentBuilder as Container
from extensions.commands import lazycwl_dashboard as dashboard

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
def _clan(i): return {"tag": f"#A{i}", "name": f"Clan {i}"}
def _doc(i=1): return {"_id": f"saved-{i}", "clan_tag": f"#A{i}", "clan_name": f"Clan {i}", "status": "active", "saved_at": NOW, "expires_at": NOW + timedelta(days=7), "players": [{"tag": "#P1", "name": "Player"}], "reminders": {"enabled": False}}
def _nodes(components):
    for container in components:
        assert isinstance(container, Container)
        for component in container.components:
            yield component
            yield from getattr(component, "components", [])
def _text(components): return "\n".join(getattr(node, "content", "") for node in _nodes(components))

def test_dashboard_starts_without_a_clan_or_implicit_bulk_scope():
    rendered = dashboard.render_home([_doc()], [_clan(1)], None, NOW, token="preview")
    assert "Choose a clan" in _text(rendered)
    assert "Captured:" not in _text(rendered)

def test_overview_has_explicit_capture_facts_and_no_internal_list_id():
    rendered = dashboard.render_home([_doc()], [_clan(1)], "#A1", NOW, {"#A1": 1}, token="preview")
    text = _text(rendered)
    assert all(label in text for label in ("Captured:", "Players captured:", "Away now:", "Status:", "Expires:"))
    assert "saved-1" not in text

def test_selector_is_limited_to_24_clans_plus_explicit_bulk_option():
    rendered = dashboard.render_home([], [_clan(i) for i in range(30)], None, NOW, token="preview")
    select = next(node for node in _nodes(rendered) if hasattr(node, "options"))
    assert len(select.options) == 25 and select.options[0].value == "ALL"

def test_rendered_component_ids_are_short_and_component_count_is_safe():
    rendered = dashboard.render_home([_doc(i) for i in range(1, 25)], [_clan(i) for i in range(1, 25)], "ALL", NOW, token="preview", tab="reminders")
    nodes = list(_nodes(rendered))
    assert len(nodes) < 40
    assert all(len(node.custom_id) <= 100 for node in nodes if getattr(node, "custom_id", None))

def test_review_scope_uses_a_short_server_side_nonce_and_is_one_shot():
    token = dashboard._session(1, 1)
    nonce = dashboard._bind(token, "ALL", [_doc(1), _doc(2)], operation="send")
    assert "saved-1" not in nonce and "saved-2" not in nonce
    assert dashboard._parse_bound(token, nonce)["operation"] == "send"
    assert dashboard._parse_bound(token, nonce) is None

def test_reminder_controls_are_explicit_enable_and_disable():
    rendered = dashboard.render_home([_doc()], [_clan(1)], "#A1", NOW, token="preview", tab="reminders")
    labels = [node.label for node in _nodes(rendered) if getattr(node, "label", None)]
    assert "Enable reminders" in labels and "Disable reminders" in labels


class _Ctx:
    def __init__(self, token, values=None):
        self.user = SimpleNamespace(id=44)
        self.member = SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)
        self.interaction = SimpleNamespace(guild_id=55, values=values or [], components=[])
        self.token = token
        self.responses = []
    async def respond(self, message, ephemeral=False): self.responses.append((message, ephemeral))


def _bound_session(operation, docs, *, capture_tags=None):
    token = dashboard._session(44, 55)
    nonce = dashboard._bind(token, "ALL", docs, operation=operation)
    if capture_tags is not None:
        dashboard._sessions[token]["pending"][nonce]["capture_tags"] = capture_tags
    return token, nonce, _Ctx(token)


def test_capture_confirmation_saves_each_reviewed_single_or_bulk_clan_once(monkeypatch):
    calls, screens = [], []
    async def save(tag, saved_by):
        calls.append((tag, saved_by)); return {"ok": True, "player_count": 2}
    async def home(mongo, selected_tag=None, note=None, **kwargs):
        screens.append((selected_tag, note)); return ["home"]
    monkeypatch.setattr(dashboard.service, "save_list", save)
    monkeypatch.setattr(dashboard, "build_home", home)
    token, nonce, ctx = _bound_session("capture", [], capture_tags=["#A1", "#A2"])
    result = asyncio.run(dashboard.handle_capture_yes(ctx=ctx, action_id=f"{token}|{nonce}", mongo=object()))
    assert result == ["home"]
    assert calls == [("#A1", 44), ("#A2", 44)]
    assert screens[0][0] == "ALL" and "2" in screens[0][1]
    # A confirmation nonce cannot capture a second time.
    asyncio.run(dashboard.handle_capture_yes(ctx=ctx, action_id=f"{token}|{nonce}", mongo=object()))
    assert len(calls) == 2


def test_capture_reports_partial_failure_without_claiming_success(monkeypatch):
    async def save(tag, saved_by): return {"ok": tag == "#A1", "error": "already captured"}
    async def home(mongo, selected_tag=None, note=None, **kwargs): return [note]
    monkeypatch.setattr(dashboard.service, "save_list", save)
    monkeypatch.setattr(dashboard, "build_home", home)
    token, nonce, ctx = _bound_session("capture", [], capture_tags=["#A1", "#A2"])
    result = asyncio.run(dashboard.handle_capture_yes(ctx=ctx, action_id=f"{token}|{nonce}", mongo=object()))
    assert "1" in result[0] and "could not" in result[0]


def test_apply_confirmation_passes_raw_expected_list_ids_and_keeps_per_clan_results(monkeypatch):
    docs = [_doc(1), _doc(2)]
    docs[0]["_id"] = object(); docs[1]["_id"] = object()
    token, nonce, ctx = _bound_session("send", docs)
    sent = []
    async def active(mongo): return docs
    async def remind(tag, *, expected_list_id):
        sent.append((tag, expected_list_id)); return {"ok": tag == "#A1", "error": "failed"}
    monkeypatch.setattr(dashboard.store, "list_active", active)
    monkeypatch.setattr(dashboard.service, "remind_now", remind)
    result = asyncio.run(dashboard._apply_bound(object(), token, nonce, "send", ctx))
    assert sent == [("#A1", docs[0]["_id"]), ("#A2", docs[1]["_id"])]
    assert "not applied" in _text(result)


def test_enable_and_disable_reviews_remain_explicit_and_use_selected_frequency(monkeypatch):
    docs = [_doc()]
    async def active(mongo): return docs
    monkeypatch.setattr(dashboard.store, "list_active", active)
    token = dashboard._session(44, 55)
    rendered = asyncio.run(dashboard._review(object(), token, "#A1", "enable", minutes=60))
    assert "Frequency: every 60 minutes" in _text(rendered)
    assert "Enable reminders?" in _text(rendered)
    rendered = asyncio.run(dashboard._review(object(), token, "#A1", "disable"))
    assert "Disable reminders?" in _text(rendered)


def test_player_page_clamps_and_marks_away_status(monkeypatch):
    doc = _doc(); doc["players"] = [{"tag": f"#P{i}", "name": f"P{i}"} for i in range(50)]
    async def active(mongo, tag): return doc
    async def active_lists(mongo): return [doc]
    async def clans(mongo): return [_clan(1)]
    async def away(saved): return [doc["players"][0]]
    monkeypatch.setattr(dashboard.store, "get_active", active)
    monkeypatch.setattr(dashboard.store, "list_active", active_lists)
    monkeypatch.setattr(dashboard, "_fwa_clans", clans)
    monkeypatch.setattr(dashboard.service, "away_players", away)
    token = dashboard._session(44, 55)
    rendered = asyncio.run(dashboard._player_page(object(), token, "#A1", 999))
    text = _text(rendered)
    assert "page 3 of 3" in text and "Returned" in text


def test_player_add_button_uses_a_live_add_nonce(monkeypatch):
    """The player header must bind the add action to the displayed saved list."""
    doc = _doc()
    async def active(mongo, tag): return doc
    async def active_lists(mongo): return [doc]
    async def clans(mongo): return [_clan(1)]
    async def away(saved): return []
    monkeypatch.setattr(dashboard.store, "get_active", active)
    monkeypatch.setattr(dashboard.store, "list_active", active_lists)
    monkeypatch.setattr(dashboard, "_fwa_clans", clans)
    monkeypatch.setattr(dashboard.service, "away_players", away)
    token = dashboard._session(44, 55)
    rendered = asyncio.run(dashboard._player_page(object(), token, "#A1", 0))
    add = next(node for node in _nodes(rendered) if getattr(node, "custom_id", "").startswith("lazycwl_add:"))
    _, payload = add.custom_id.split(":", 1)
    received_token, nonce = dashboard._split(payload)
    bound = dashboard._sessions[received_token]["pending"][nonce]
    assert bound["operation"] == "add" and bound["ids"] == [doc["_id"]]
