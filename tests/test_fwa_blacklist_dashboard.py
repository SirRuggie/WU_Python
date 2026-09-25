import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands import fwa_blacklist_dashboard as ui


def run(coro):
    return asyncio.run(coro)


def call(handler, ctx, token, db, **extra):
    return run(handler.__wrapped__._func(ctx=ctx, action_id=token, mongo=db, **extra))


def text(panel):
    return "\n".join(
        part["content"] for part in panel[0].build()[0]["components"]
        if "content" in part
    )


def controls(panel):
    rows = panel[0].build()[0]["components"]
    return [
        item for row in rows if row["type"] == hikari.ComponentType.ACTION_ROW
        for item in row["components"]
    ]


def ids(panel):
    return {item.get("custom_id") for item in controls(panel) if item.get("custom_id")}


def entry(index, *, name=None, classification=None):
    doc = {
        "_id": f"TAG{index:03d}", "name": name or f"Clan {index:03d}",
        "source": "manual", "added_at": f"2026-09-{(index % 28) + 1:02d}T00:00:00+00:00",
    }
    if classification:
        doc["classification"] = classification
    return doc


class Context:
    def __init__(self, *, user=10, guild=20, editor=False, admin=False, values=(), fields=()):
        roles = [ui.ROLE_ID] if editor else []
        self.user = SimpleNamespace(id=user, username="Tester")
        self.member = SimpleNamespace(
            role_ids=roles, display_name="Staff",
            permissions=hikari.Permissions.ADMINISTRATOR if admin else hikari.Permissions.NONE,
        )
        self.interaction = SimpleNamespace(
            guild_id=guild, member=self.member, values=values, components=fields,
            custom_id=None, message=SimpleNamespace(id=5),
            edit_initial_response=AsyncMock(), create_initial_response=AsyncMock(),
        )
        self.defer = AsyncMock()
        self.respond = AsyncMock()
        self.respond_with_modal = AsyncMock()


@pytest.fixture
def harness(monkeypatch):
    states = {}
    docs = {row["_id"]: row for row in (entry(i) for i in range(26))}

    async def insert_state(_db, state, ttl):
        assert ttl == ui.TTL
        states[state["_id"]] = copy.deepcopy(state)

    async def get_state(_db, token):
        return copy.deepcopy(states.get(token))

    async def listing(_db):
        return sorted((copy.deepcopy(row) for row in docs.values()), key=lambda row: row["name"])

    async def add(_db, tag, name, author_id, author_name, source):
        current = docs.get(tag)
        if current:
            current["name"] = name
        else:
            docs[tag] = {
                "_id": tag, "name": name, "source": source,
                "added_at": "2026-09-25T00:00:00+00:00",
                "added_by_id": author_id, "added_by_name": author_name,
            }
        return tag

    async def remove(_db, tag, *, expected_added_at):
        if tag not in docs or docs[tag].get("added_at") != expected_added_at:
            return False
        return docs.pop(tag, None) is not None

    async def find_one(query):
        return copy.deepcopy(docs.get(query["_id"]))

    monkeypatch.setattr(ui, "insert_state", insert_state)
    monkeypatch.setattr(ui, "get_state", get_state)
    monkeypatch.setattr(ui, "list_blacklisted", listing)
    monkeypatch.setattr(ui, "add_blacklisted", add)
    monkeypatch.setattr(ui, "remove_blacklisted", remove)
    db = SimpleNamespace(fwa_blacklist=SimpleNamespace(find_one=AsyncMock(side_effect=find_one)))
    state = run(ui._new(db, kind="fwa_blacklist", user_id=10, guild_id=20, manage_token="manage", view="list", page=0, query=""))
    return db, states, docs, state


def test_pagination_keeps_every_entry_and_bounds_components(harness):
    db, states, docs, state = harness
    ctx = Context()
    seen = set()
    current = state
    for page in range(3):
        panel = run(ui._panel(db, current, editor=False))
        built = panel[0].build()[0]
        words = text(panel)
        assert f"Page {page + 1}/3" in words
        assert "26 total" in words
        assert "Management › FWA › Blacklist" in words
        assert all("fwa_blacklist_add" not in value for value in ids(panel))
        for row in docs.values():
            if f"#{row['_id']}" in words:
                seen.add(row["_id"])
        assert len(built["components"]) < 40
        assert all(len(part.get("content", "")) <= 4000 for part in built["components"])
        if page < 2:
            current = call(ui.page, ctx, f"{current['_id']}|{page + 1}", db)
            assert "Page" in text(current)
            current = states[next(reversed(states))]
    assert seen == set(docs)


def test_long_names_are_bounded_without_dropping_entries(harness):
    db, states, docs, state = harness
    for row in docs.values():
        row["name"] = "Z" * 5000
        row["classification"] = "C" * 5000
    panel = run(ui._panel(db, state, editor=True))
    words = text(panel)
    assert "10 matching" not in words
    assert words.count("added 2026") == ui.PAGE_SIZE
    assert len(words) < 4000
    assert len(controls(panel)) <= 25


def test_read_only_can_search_but_forged_mutations_are_denied(harness):
    db, states, docs, state = harness
    viewer = Context(admin=True)
    panel = run(ui._panel(db, state, editor=ui._can_manage(viewer)))
    assert not any(key.startswith("fwa_blacklist_add:") for key in ids(panel))
    assert not any(key.startswith("fwa_blacklist_select:") for key in ids(panel))
    call(ui.search, viewer, state["_id"], db)
    viewer.respond_with_modal.assert_awaited_once()
    denied = call(ui.select, viewer, state["_id"], db)
    assert "FWA Clan Rep role" in text(denied)
    call(ui.add, viewer, state["_id"], db)
    assert "FWA Clan Rep role" in viewer.respond.await_args.args[0]
    assert len(docs) == 26


def test_owner_guild_and_expired_state_are_checked_on_callbacks(harness):
    db, states, docs, state = harness
    assert "Open your own" in text(call(ui.refresh, Context(user=99), state["_id"], db))
    assert "Open your own" in text(call(ui.page, Context(guild=99), f"{state['_id']}|1", db))
    states[state["_id"]]["kind"] = "other_dashboard"
    assert "not a FWA Blacklist panel" in text(call(ui.refresh, Context(), state["_id"], db))
    del states[state["_id"]]
    assert "expired" in text(call(ui.clear, Context(), state["_id"], db))
    assert len(docs) == 26


def test_search_by_name_or_tag_and_clear_resets_page(harness):
    db, states, docs, state = harness
    ctx = Context()
    ctx.interaction.components = ((SimpleNamespace(custom_id="query", value="#tag011"),),)
    call(ui.search_submit, ctx, state["_id"], db)
    result = ctx.interaction.edit_initial_response.await_args.kwargs
    assert result["user_mentions"] is False and result["role_mentions"] is False
    filtered = states[next(reversed(states))]
    assert filtered["query"] == "#tag011" and filtered["page"] == 0
    assert "TAG011" in text(result["components"])
    assert "1 matching" in text(result["components"])
    cleared = call(ui.clear, ctx, filtered["_id"], db)
    assert "26 matching" in text(cleared)
    assert states[next(reversed(states))]["query"] == ""


def test_add_validates_raw_tag_and_looks_up_name_when_blank(harness):
    db, states, docs, state = harness
    ctx = Context(editor=True)
    coc_client = SimpleNamespace(get_clan=AsyncMock(return_value=SimpleNamespace(name="API Clan")))
    ctx.interaction.components = ((SimpleNamespace(custom_id="tag", value="#ABC.123"),
                                   SimpleNamespace(custom_id="name", value="Spoof")),)
    call(ui.add_submit, ctx, state["_id"], db, coc_client=coc_client)
    assert "plain clan tag" in text(ctx.interaction.edit_initial_response.await_args.kwargs["components"])
    assert "ABC123" not in docs
    ctx.interaction.components = ((SimpleNamespace(custom_id="tag", value="#ABC123"),
                                   SimpleNamespace(custom_id="name", value="")),)
    call(ui.add_submit, ctx, state["_id"], db, coc_client=coc_client)
    coc_client.get_clan.assert_awaited_once_with("#ABC123")
    assert docs["ABC123"]["name"] == "API Clan"
    assert docs["ABC123"]["source"] == "manual"
    assert ctx.interaction.edit_initial_response.await_args.kwargs["user_mentions"] is False


def test_remove_requires_page_selection_confirmation_and_fresh_role(harness):
    db, states, docs, state = harness
    editor = Context(editor=True, values=("TAG000",))
    chosen = call(ui.select, editor, state["_id"], db)
    selected = states[next(reversed(states))]
    assert selected["selected_tag"] == "TAG000"
    assert "Remove selected clan" in [item.get("label") for item in controls(chosen)]
    review = call(ui.remove, editor, selected["_id"], db)
    confirmation = states[next(reversed(states))]
    assert confirmation["view"] == "confirm"
    assert "TAG000" in text(review)
    labels = {item["label"]: item for item in controls(review) if "label" in item}
    assert labels["Yes, remove clan"]["emoji"]
    assert labels["No, keep clan"]["emoji"]
    assert review[0].build()[0]["accent_color"] == ui.RED_ACCENT
    denied = call(ui.confirm, Context(admin=True), confirmation["_id"], db)
    assert "FWA Clan Rep role" in text(denied) and "TAG000" in docs
    cancelled = call(ui.cancel, Context(editor=True), confirmation["_id"], db)
    assert "Removal cancelled." in text(cancelled) and "TAG000" in docs
    done = call(ui.confirm, Context(editor=True), confirmation["_id"], db)
    assert "TAG000" not in docs
    assert "removed" in text(done)
    again = call(ui.confirm, Context(editor=True), confirmation["_id"], db)
    assert "no longer" in text(again)


def test_stale_selection_cannot_remove_readded_or_off_page_clan(harness):
    db, states, docs, state = harness
    editor = Context(editor=True, values=("TAG025",))
    off_page = call(ui.select, editor, state["_id"], db)
    assert "Choose a clan shown on this page" in text(off_page)
    editor.interaction.values = ("TAG000",)
    call(ui.select, editor, state["_id"], db)
    selected = states[next(reversed(states))]
    call(ui.remove, editor, selected["_id"], db)
    confirmation = states[next(reversed(states))]
    docs["TAG000"]["added_at"] = "2026-10-01T00:00:00+00:00"
    result = call(ui.confirm, editor, confirmation["_id"], db)
    assert "changed" in text(result)
    assert "TAG000" in docs


def test_open_dashboard_is_private_and_has_retry_on_database_error(harness, monkeypatch):
    db, states, docs, state = harness
    ctx = Context()
    run(ui.open_dashboard(ctx, db, manage_token="manage", deferred=True))
    kwargs = ctx.interaction.edit_initial_response.await_args.kwargs
    assert kwargs["user_mentions"] is False
    assert "View only" in text(kwargs["components"])
    async def broken(_db):
        raise RuntimeError("db unavailable")
    monkeypatch.setattr(ui, "list_blacklisted", broken)
    failure = run(ui._panel(db, state, editor=False))
    assert "Could not load" in text(failure)
    assert any(key.startswith("fwa_blacklist_refresh:") for key in ids(failure))


def test_manual_clan_punctuation_is_safe_in_private_panel(harness):
    db, states, docs, state = harness
    ctx = Context(editor=True, fields=((
        SimpleNamespace(custom_id="tag", value="#NEW123"),
        SimpleNamespace(custom_id="name", value="Clan @ Home <3"),
    ),))
    coc_client = SimpleNamespace(get_clan=AsyncMock())
    call(ui.add_submit, ctx, state["_id"], db, coc_client=coc_client)
    coc_client.get_clan.assert_not_awaited()
    assert docs["NEW123"]["name"] == "Clan @ Home <3"
    shown = text(ctx.interaction.edit_initial_response.await_args.kwargs["components"])
    assert "@ Home" not in shown
    assert "＠ Home" in shown


def test_confirm_preserves_entry_readded_between_read_and_delete(harness, monkeypatch):
    from utils.fwa_blacklist import remove_blacklisted

    db, states, docs, state = harness
    tag = "TAG000"
    confirmation = run(ui._next(
        db, state, view="confirm", selected_tag=tag,
        selected_added_at=docs[tag]["added_at"], selected_name=docs[tag]["name"],
    ))

    async def racing_delete(query):
        docs[tag] = {**docs[tag], "added_at": "2026-09-25T23:59:59+00:00"}
        matches = all(docs[tag].get(key) == value for key, value in query.items())
        if matches:
            del docs[tag]
        return SimpleNamespace(deleted_count=int(matches))

    db.fwa_blacklist.delete_one = AsyncMock(side_effect=racing_delete)
    monkeypatch.setattr(ui, "remove_blacklisted", remove_blacklisted)
    panel = call(ui.confirm, Context(editor=True), confirmation["_id"], db)
    assert tag in docs
    assert "entry changed or was removed" in text(panel)
    assert db.fwa_blacklist.delete_one.call_args.args[0]["added_at"] == confirmation["selected_added_at"]
