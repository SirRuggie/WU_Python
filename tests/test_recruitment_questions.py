import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hikari
from extensions.commands import recruitment_questions as editor


def run(coro): return asyncio.run(coro)

def ctx(user=1, guild=2, permissions=hikari.Permissions.MANAGE_GUILD):
    member = SimpleNamespace(permissions=permissions)
    interaction = SimpleNamespace(guild_id=guild, member=member, values=("attack_strategies",))
    return SimpleNamespace(user=SimpleNamespace(id=user), member=member, interaction=interaction)


def test_editor_is_manage_guild_gated_and_discord_basic_disables_artwork():
    assert editor.allowed(ctx())
    assert not editor.allowed(ctx(permissions=hikari.Permissions.NONE))
    template = {"variant": "discord_basic_skills", "sections": ["a", "b", "c"], "footer_url": None, "accent": 1, "revision": 0}
    state = {"_id":"x", "manage_token":"home", "variant":"discord_basic_skills", "template":template, "saved_template":template}
    payload = editor._editor(state)[0].build()[0]
    buttons = [b for row in payload["components"] if row["type"] == 1 for b in row["components"]]
    upload = next(b for b in buttons if b["custom_id"] == "recruit_question_footer:x")
    assert upload["disabled"] is True


def test_preview_uses_private_renderer_without_pings(monkeypatch):
    state = {"_id":"x", "user_id":1, "guild_id":2, "manage_token":"home", "view":"editor", "variant":"attack_strategies", "template": {}}
    monkeypatch.setattr(editor, "_state", AsyncMock(return_value=(state, None)))
    rendered = [hikari.impl.ContainerComponentBuilder(components=[hikari.impl.TextDisplayComponentBuilder(content="Preview")])]
    monkeypatch.setattr(editor.content, "preview_template", lambda template: rendered)
    interaction = SimpleNamespace(edit_initial_response=AsyncMock())
    context = ctx(); context.interaction = interaction
    run(editor.preview(context, "x", mongo=object()))
    sent = interaction.edit_initial_response.await_args.kwargs
    assert sent["user_mentions"] is False and sent["role_mentions"] is False and sent["mentions_everyone"] is False


def test_editor_select_edit_save_and_owner_guard(monkeypatch):
    """A private draft must become public copy only after Save."""
    from tests.test_recruit_question_content import mongo
    db = mongo()
    states = {}

    async def insert_state(_mongo, state, ttl=None):
        if state["_id"] in states:
            raise AssertionError("duplicate editor state ID")
        states[state["_id"]] = state

    async def get_state(_mongo, token):
        return states.get(token)

    monkeypatch.setattr(editor, "insert_state", insert_state)
    monkeypatch.setattr(editor, "get_state", get_state)
    context = ctx()
    context.interaction.custom_id = None
    context.interaction.edit_initial_response = AsyncMock()
    run(editor.open_dashboard(context, db, manage_token="home", deferred=True))
    assert len(states) == 1
    home_id = next(iter(states))

    context.interaction.values = ("attack_strategies",)
    run(editor.variant(context, home_id, mongo=db))
    draft = next(state for state in states.values() if state.get("view") == "editor")
    context.interaction.message = None
    context.interaction.components = [[SimpleNamespace(custom_id="text", value="## Updated · {recruit}")]]
    context.defer = AsyncMock()
    run(editor.submit(context, f"{draft['_id']}|0", mongo=db))
    assert not db.bot_config.rows
    updated = next(state for state in states.values()
                   if state.get("view") == "editor" and state["_id"] != draft["_id"])
    assert "Updated" in updated["template"]["sections"][0]
    assert "Updated" not in updated["saved_template"]["sections"][0]

    intruder = ctx(user=99)
    denied = run(editor.save(intruder, updated["_id"], mongo=db))
    assert "Open your own" in str(denied[0].build())
    assert not db.bot_config.rows

    run(editor.save(context, updated["_id"], mongo=db))
    stored = db.bot_config.rows["recruit_question_template:2:attack_strategies"]
    assert stored["sections"][0] == "## Updated · {recruit}"
    assert stored["revision"] == 1


def test_expanded_image_slot_is_selected_and_restored_in_private_draft(monkeypatch):
    from utils import recruit_question_content as content
    variant = "lazy_cwl_explanation"
    original = content.default_template(variant)
    slot = next(iter(original["media"]))
    states = {}

    async def insert_state(_mongo, state, ttl=None):
        if state["_id"] in states:
            raise AssertionError("duplicate editor state ID")
        states[state["_id"]] = state

    async def get_state(_mongo, token):
        return states.get(token)

    monkeypatch.setattr(editor, "insert_state", insert_state)
    monkeypatch.setattr(editor, "get_state", get_state)
    state = {
        "_id": "first", "user_id": 1, "guild_id": 2, "manage_token": "home",
        "view": "editor", "variant": variant,
        "template": original, "saved_template": original,
    }
    states["first"] = state
    context = ctx()
    context.interaction.values = (slot,)
    rendered = run(editor.choose_media(context, "first", mongo=object()))
    selected = next(item for item in states.values() if item.get("selected_media_slot") == slot)
    assert f"{content.MEDIA_LABELS[variant][slot]} selected" in str(rendered[0].build())
    assert not editor._dirty(selected)

    changed = content.default_template(variant)
    changed["media"][slot] = "https://example.com/replacement.png"
    selected["template"] = changed
    assert editor._dirty(selected)
    run(editor.restore_footer(context, selected["_id"], mongo=object()))
    restored = next(item for item in states.values() if item["_id"] not in {"first", selected["_id"]})
    assert restored["template"]["media"][slot] == original["media"][slot]
    assert not editor._dirty(restored)


def test_fwa_base_preview_is_separate_and_has_no_pings(monkeypatch):
    from utils import recruit_question_content as content
    template = content.default_template("fwa_bases_upon_approval")
    state = {
        "_id": "base", "user_id": 1, "guild_id": 2, "manage_token": "home",
        "view": "editor", "variant": "fwa_bases_upon_approval",
        "template": template, "saved_template": template,
    }
    monkeypatch.setattr(editor, "_state", AsyncMock(return_value=(state, None)))
    context = ctx()
    context.interaction.edit_initial_response = AsyncMock()
    run(editor.preview(context, "base", mongo=object()))
    selector = context.interaction.edit_initial_response.await_args.kwargs
    assert selector["user_mentions"] is False
    assert "recruit_question_base_preview:base" in str(selector["components"][-1].build())
    run(editor.base_preview(context, "base", mongo=object()))
    result = context.interaction.edit_initial_response.await_args.kwargs
    assert result["user_mentions"] is False and result["role_mentions"] is False
    assert "example.org" in str([part.build() for part in result["components"]])
    assert "recruit_question_preview:base" in str(result["components"][-1].build())
