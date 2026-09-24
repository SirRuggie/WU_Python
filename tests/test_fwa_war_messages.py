import asyncio
import copy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from extensions import components
from extensions.commands import fwa_war_messages as ui
from utils import fwa_war_content as service


def run(coro):
    return asyncio.run(coro)


class StrictCollection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query, projection=None):
        row = self.rows.get(query["_id"])
        return copy.deepcopy(row) if row is not None else None

    async def insert_one(self, row):
        if row["_id"] in self.rows:
            raise DuplicateKeyError("duplicate _id")
        self.rows[row["_id"]] = copy.deepcopy(row)
        return SimpleNamespace(inserted_id=row["_id"])

    async def update_one(self, query, update):
        row = self.rows.get(query["_id"])
        if row is None or row.get("revision") != query.get("revision"):
            return SimpleNamespace(matched_count=0)
        row.update(copy.deepcopy(update["$set"]))
        return SimpleNamespace(matched_count=1)

    async def delete_one(self, query):
        self.rows.pop(query["_id"], None)


def mongo():
    return SimpleNamespace(
        component_state=StrictCollection(),
        bot_config=StrictCollection(),
        button_store=StrictCollection(),
    )


class Context:
    def __init__(self, custom_id=None, *, values=(), guild=20, user=10, role=True, fields=()):
        self.user = SimpleNamespace(id=user)
        role_ids = [ui.ROLE_ID] if role else []
        self.member = SimpleNamespace(role_ids=role_ids, get_roles=lambda: [SimpleNamespace(id=role) for role in role_ids])
        self.events = []
        self.interaction = SimpleNamespace(
            id=333,
            custom_id=custom_id,
            values=values,
            guild_id=guild,
            member=self.member,
            components=fields,
            message=SimpleNamespace(id=44, channel_id=55),
            create_initial_response=AsyncMock(side_effect=lambda *args, **kw: self.events.append(("initial", args, kw))),
            edit_initial_response=AsyncMock(side_effect=lambda **kw: self.events.append(("edit", kw))),
            app=SimpleNamespace(rest=SimpleNamespace(edit_message=AsyncMock())),
        )

    async def defer(self, **kw):
        self.events.append(("defer", kw))

    async def respond(self, *args, **kw):
        self.events.append(("respond", args, kw))

    async def respond_with_modal(self, **kw):
        self.events.append(("modal", kw))


def use_dispatch(monkeypatch, name, db):
    action = components.registered_functions[name]
    original = action.fn.__wrapped__._func

    async def invoke(**kw):
        return await original(mongo=db, **kw)

    monkeypatch.setitem(components.registered_functions, name, replace(action, fn=invoke))


def button_ids(panel):
    result = []
    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            if node.get("type") == hikari.ComponentType.BUTTON:
                result.append(node["custom_id"])
            for key in ("components", "accessory"):
                if key in node:
                    walk(node[key])
    walk([item.build()[0] for item in panel])
    return result


def latest_state(db, view=None):
    rows = list(db.component_state.rows.values())
    if view is not None:
        rows = [row for row in rows if row["view"] == view]
    return rows[-1]


def test_editor_registers_at_startup_and_all_default_previews_fit_discord():
    from utils.startup import load_cogs
    assert "extensions.commands.fwa_war_messages" in load_cogs(disallowed={"example"})
    for variant in service.VARIANTS:
        template = service.default_template(variant)
        state = {
            "_id": "x" * 32, "variant": variant, "template": template,
            "saved_template": copy.deepcopy(template), "manage_token": "h" * 32,
        }
        for panel in (ui._editor(state), [*service.preview_template(template)[0]]):
            built = [item.build()[0] for item in panel]
            nodes = []
            def walk(node):
                if isinstance(node, list):
                    for child in node:
                        walk(child)
                elif isinstance(node, dict):
                    nodes.append(node)
                    for key in ("components", "accessory"):
                        if key in node:
                            walk(node[key])
            walk(built)
            assert len(nodes) <= 40
            assert all(len(node["custom_id"]) <= 100 for node in nodes if "custom_id" in node)
            assert sum(len(node.get("content", "")) for node in nodes) <= 4000


@pytest.mark.parametrize("variant", service.VARIANTS)
def test_variant_selection_creates_unique_owned_editor_state(monkeypatch, variant):
    db = mongo()
    root = {
        "_id": "home", "user_id": 10, "guild_id": 20,
        "manage_token": "manage", "view": "home",
    }
    db.component_state.rows["home"] = root
    use_dispatch(monkeypatch, "fwa_war_variant", db)
    ctx = Context("fwa_war_variant:home", values=(variant,))
    run(components._dispatch(ctx, db))
    assert ctx.events[0][0] == "defer"
    assert ctx.events[-1][0] == "respond"
    editor = latest_state(db, "editor")
    assert editor["_id"] != "home"
    assert editor["variant"] == variant
    assert editor["saved_template"] == editor["template"]
    assert f"fwa_war_block:{editor['_id']}" in str(ctx.events[-1])


def test_back_to_variants_mints_home_state_that_can_select_another_variant(monkeypatch):
    db = mongo()
    editor = {
        "_id": "first", "user_id": 10, "guild_id": 20, "manage_token": "manage",
        "view": "editor", "variant": "win", "template": service.default_template("win"),
        "saved_template": service.default_template("win"),
    }
    db.component_state.rows["first"] = editor
    use_dispatch(monkeypatch, "fwa_war_leave_variants", db)
    use_dispatch(monkeypatch, "fwa_war_variant", db)
    back = Context("fwa_war_leave_variants:first")
    run(components._dispatch(back, db))
    home = latest_state(db, "home")
    assert home["_id"] != "first"
    assert f"fwa_war_variant:{home['_id']}" in str(back.events[-1])
    choose = Context(f"fwa_war_variant:{home['_id']}", values=("lose",))
    run(components._dispatch(choose, db))
    assert latest_state(db, "editor")["variant"] == "lose"


def test_invalid_selection_and_modal_submission_do_not_change_draft(monkeypatch):
    db = mongo()
    state = {
        "_id": "draft", "user_id": 10, "guild_id": 20, "manage_token": "manage",
        "view": "editor", "variant": "win", "template": service.default_template("win"),
        "saved_template": service.default_template("win"),
    }
    db.component_state.rows["draft"] = state
    use_dispatch(monkeypatch, "fwa_war_block", db)
    bad_menu = Context("fwa_war_block:draft", values=("999",))
    run(components._dispatch(bad_menu, db))
    assert not any(event[0] == "modal" for event in bad_menu.events)
    assert bad_menu.events[-1][0] == "edit"
    assert len(db.component_state.rows) == 1

    use_dispatch(monkeypatch, "fwa_war_submit", db)
    bad_form = Context("fwa_war_submit:draft|999", fields=[[SimpleNamespace(custom_id="text", value="bad")]])
    run(components._dispatch(bad_form, db))
    assert bad_form.events[0][0] == "initial"
    assert bad_form.events[-1][0] == "edit"
    assert len(db.component_state.rows) == 1


def test_text_edit_save_conflict_and_reset_follow_strict_cas(monkeypatch):
    db = mongo()
    base = service.default_template("win")
    for sid in ("a", "b"):
        db.component_state.rows[sid] = {
            "_id": sid, "user_id": 10, "guild_id": 20, "manage_token": "manage",
            "view": "editor", "variant": "win",
            "template": copy.deepcopy(base), "saved_template": copy.deepcopy(base),
        }
    use_dispatch(monkeypatch, "fwa_war_submit", db)
    use_dispatch(monkeypatch, "fwa_war_save", db)
    for sid, value in (("a", "# First"), ("b", "# Second")):
        form = Context(f"fwa_war_submit:{sid}|0", fields=[[SimpleNamespace(custom_id="text", value=value)]])
        run(components._dispatch(form, db))
        assert form.events[0][0] == "initial"
        assert form.events[-1][0] == "edit"
    drafts = [row for row in db.component_state.rows.values() if row.get("view") == "editor" and row["_id"] not in {"a", "b"}]
    assert len(drafts) == 2
    first, second = drafts
    run(components._dispatch(Context(f"fwa_war_save:{first['_id']}"), db))
    assert db.bot_config.rows["fwa_war_template:20:win"]["sections"][0] == "# First"
    conflict = Context(f"fwa_war_save:{second['_id']}")
    run(components._dispatch(conflict, db))
    assert "changed elsewhere" in str(conflict.events[-1])
    assert db.bot_config.rows["fwa_war_template:20:win"]["revision"] == 1

    use_dispatch(monkeypatch, "fwa_war_reset_confirm", db)
    saved = latest_state(db, "editor")
    run(components._dispatch(Context(f"fwa_war_reset_confirm:{saved['_id']}"), db))
    assert db.bot_config.rows["fwa_war_template:20:win"]["revision"] == 2
    assert db.bot_config.rows["fwa_war_template:20:win"]["sections"] == base["sections"]


def test_footer_upload_stays_in_draft_until_save(monkeypatch):
    db = mongo()
    base = service.default_template("win")
    db.component_state.rows["draft"] = {
        "_id": "draft", "user_id": 10, "guild_id": 20, "manage_token": "manage",
        "view": "editor", "variant": "win",
        "template": copy.deepcopy(base), "saved_template": copy.deepcopy(base),
    }
    media = SimpleNamespace(upload_bytes=AsyncMock(return_value="https://img.example.com/footer.png"))
    attachment = SimpleNamespace(size=1024, read=AsyncMock(return_value=b"image"))
    monkeypatch.setattr(ui, "pop_file_upload", lambda *_: {"id": "1"})
    monkeypatch.setattr(ui, "_modal_attachment", lambda payload: attachment)
    action = components.registered_functions["fwa_war_footer_submit"]
    original = action.fn.__wrapped__._func
    async def invoke(**kw):
        return await original(mongo=db, media=media, **kw)
    monkeypatch.setitem(components.registered_functions, "fwa_war_footer_submit", replace(action, fn=invoke))
    ctx = Context("fwa_war_footer_submit:draft")
    run(components._dispatch(ctx, db))
    assert ctx.events[0][0] == "initial"
    assert ctx.events[-1][0] == "edit"
    assert db.bot_config.rows == {}
    staged = latest_state(db, "editor")
    assert staged["template"]["footer_url"] == "https://img.example.com/footer.png"
    assert staged["saved_template"]["footer_url"] == base["footer_url"]
    media.upload_bytes.assert_awaited_once()
    use_dispatch(monkeypatch, "fwa_war_save", db)
    run(components._dispatch(Context(f"fwa_war_save:{staged['_id']}"), db))
    assert db.bot_config.rows["fwa_war_template:20:win"]["footer_url"] == "https://img.example.com/footer.png"


def test_preview_suppresses_all_mentions_and_does_not_publish(monkeypatch):
    db = mongo()
    base = service.default_template("blacklisted")
    db.component_state.rows["draft"] = {
        "_id": "draft", "user_id": 10, "guild_id": 20, "manage_token": "manage",
        "view": "editor", "variant": "blacklisted",
        "template": copy.deepcopy(base), "saved_template": copy.deepcopy(base),
    }
    for name in ("fwa_war_preview", "fwa_war_copy_preview"):
        use_dispatch(monkeypatch, name, db)
        ctx = Context(f"{name}:draft")
        run(components._dispatch(ctx, db))
        assert ctx.events[0][0] == "defer"
        assert ctx.events[-1][0] == "edit"
        kwargs = ctx.events[-1][1]
        assert kwargs["user_mentions"] is False
        assert kwargs["role_mentions"] is False
        assert kwargs["mentions_everyone"] is False


def test_revoked_role_and_cross_guild_cannot_save(monkeypatch):
    db = mongo()
    base = service.default_template("win")
    db.component_state.rows["draft"] = {
        "_id": "draft", "user_id": 10, "guild_id": 20, "manage_token": "manage",
        "view": "editor", "variant": "win",
        "template": copy.deepcopy(base), "saved_template": copy.deepcopy(base),
    }
    use_dispatch(monkeypatch, "fwa_war_save", db)
    for ctx in (
        Context("fwa_war_save:draft", role=False),
        Context("fwa_war_save:draft", guild=21),
        Context("fwa_war_save:draft", user=11),
    ):
        run(components._dispatch(ctx, db))
        assert ctx.events[-1][0] == "respond"
        assert db.bot_config.rows == {}


def test_edit_save_then_war_command_posts_saved_content(monkeypatch):
    from extensions.commands.fwa import war_plans
    db = mongo()
    original = service.default_template("lose")
    db.component_state.rows["draft"] = {
        "_id": "draft", "user_id": 10, "guild_id": 20, "manage_token": "manage",
        "view": "editor", "variant": "lose",
        "template": copy.deepcopy(original), "saved_template": copy.deepcopy(original),
    }
    use_dispatch(monkeypatch, "fwa_war_submit", db)
    use_dispatch(monkeypatch, "fwa_war_save", db)
    form = Context("fwa_war_submit:draft|0", fields=[[SimpleNamespace(custom_id="text", value="# Edited loss against {opponent}")]])
    run(components._dispatch(form, db))
    edited = latest_state(db, "editor")
    run(components._dispatch(Context(f"fwa_war_save:{edited['_id']}"), db))
    assert db.bot_config.rows["fwa_war_template:20:lose"]["sections"][0] == "# Edited loss against {opponent}"

    db.clans = SimpleNamespace(find_one=AsyncMock(return_value={"tag": "#ABC", "announcement_id": 777}))
    monkeypatch.setattr(war_plans, "Clan", lambda data: SimpleNamespace(announcement_id=777))
    send = AsyncMock()
    ctx = Context()
    ctx.client = SimpleNamespace(rest=SimpleNamespace(create_message=send))
    ctx.member.display_name = "Planner"
    command = war_plans.WarPlans()
    command.clan_name = "Our Clan|#ABC|12345"
    command.war_result = "lose"
    command.opponent = "Enemy"
    run(command.invoke(ctx, mongo=db, coc_client=object()))
    assert send.await_count == 1
    assert "Edited loss against Enemy" in str(send.await_args.kwargs["components"][0].build())
    assert send.await_args.kwargs["role_mentions"] == [12345]
