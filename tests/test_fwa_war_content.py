import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands.fwa import war_plans
from extensions.commands.fwa.message_templates import WarCopyTexts, WarMessageTemplates
from utils import fwa_war_content as content


def run(awaitable):
    return asyncio.run(awaitable)


class ConfigCollection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query):
        row = self.rows.get(query["_id"])
        return copy.deepcopy(row) if row is not None else None

    async def insert_one(self, row):
        if row["_id"] in self.rows:
            raise DuplicateKeyError("duplicate")
        self.rows[row["_id"]] = copy.deepcopy(row)
        return SimpleNamespace(inserted_id=row["_id"])

    async def update_one(self, query, update):
        row = self.rows.get(query["_id"])
        if row is None or row.get("revision") != query.get("revision"):
            return SimpleNamespace(matched_count=0)
        row.update(copy.deepcopy(update["$set"]))
        return SimpleNamespace(matched_count=1)


def mongo():
    return SimpleNamespace(bot_config=ConfigCollection())


@pytest.mark.parametrize("variant", content.VARIANTS)
def test_defaults_render_exact_native_components_and_copy(variant):
    template = content.default_template(variant)
    components, copy_text = content.render_template(
        template, opponent="Example", author="Planner",
        clan_role_id=111, fwa_rep_role_id=222,
    )
    native = (
        WarMessageTemplates.blacklisted_message("Example", "Planner", "111", "222")
        if variant == "blacklisted"
        else getattr(WarMessageTemplates, f"{variant}_message")("Example", "Planner", "111")
    )
    assert components[0].build() == native[0].build()
    assert copy_text == getattr(WarCopyTexts, f"{variant}_copy")("Example")


def test_save_load_reset_is_guild_scoped_and_revision_safe():
    db = mongo()
    first = content.default_template("win")
    first["sections"][0] = "# Custom {opponent}"
    first["copy_text"] = "Instructions for {opponent}"
    saved = run(content.save_template(db, 10, "win", first, 0, 99))
    assert saved["revision"] == 1
    assert run(content.load_template(db, 10, "win"))["sections"][0] == "# Custom {opponent}"
    assert run(content.load_template(db, 11, "win"))["sections"][0] != "# Custom {opponent}"
    with pytest.raises(content.TemplateConflict):
        run(content.save_template(db, 10, "win", first, 0, 99))
    with pytest.raises(content.TemplateConflict):
        run(content.reset_template(db, 10, "win", 0, 99))
    reset = run(content.reset_template(db, 10, "win", 1, 99))
    assert reset["revision"] == 2
    assert reset["sections"] == content.default_template("win")["sections"]


@pytest.mark.parametrize("invalid", [
    {"sections": ["one"]},
    {"copy_text": "{user.name}"},
    {"copy_text": "{unknown}"},
    {"copy_text": "@everyone " + "x" * 1900},
    {"footer_url": "https://localhost/x.png"},
    {"accent": True},
])
def test_invalid_edits_are_rejected(invalid):
    template = content.default_template("win")
    template.update(invalid)
    with pytest.raises(ValueError):
        content.validate_template("win", template)


def test_corrupt_saved_row_fails_closed():
    db = mongo()
    db.bot_config.rows["fwa_war_template:10:win"] = {
        "_id": "fwa_war_template:10:win", "schema_version": 1,
        "guild_id": 10, "variant": "win", "revision": 1,
        "sections": ["broken"], "copy_text": "copy", "accent": 1,
        "footer_url": "assets/Green_Footer.png",
    }
    with pytest.raises(ValueError, match="invalid"):
        run(content.load_template(db, 10, "win"))


def test_public_war_plan_uses_saved_template_and_allows_only_clan_role_mentions(monkeypatch):
    db = mongo()
    db.clans = SimpleNamespace(find_one=AsyncMock(return_value={"tag": "#ABC", "announcement_id": 777}))
    monkeypatch.setattr(war_plans, "Clan", lambda data: SimpleNamespace(announcement_id=777))
    custom = content.default_template("win")
    custom["sections"][0] = "# Custom win against {opponent}"
    custom["copy_text"] = "Copy: {opponent}"
    run(content.save_template(db, 10, "win", custom, 0, 5))
    create = AsyncMock(return_value=SimpleNamespace(id=123))
    member = SimpleNamespace(
        role_ids=[war_plans.FWA_WAR_PLANS_CONFIG["fwa_clan_rep_role_id"]],
        display_name="Planner",
    )
    ctx = SimpleNamespace(
        member=member, user=SimpleNamespace(id=5, username="Planner"),
        interaction=SimpleNamespace(guild_id=10),
        client=SimpleNamespace(rest=SimpleNamespace(create_message=create)),
        defer=AsyncMock(), respond=AsyncMock(),
    )
    command = war_plans.WarPlans()
    command.clan_name = "Our Clan|#ABC|12345"
    command.war_result = "win"
    command.opponent = "Enemy"
    run(command.invoke(ctx, mongo=db, coc_client=object()))
    assert create.await_count == 1
    kwargs = create.await_args.kwargs
    assert kwargs["channel"] == 777
    assert kwargs["role_mentions"] == [12345]
    assert kwargs["user_mentions"] is False and kwargs["mentions_everyone"] is False
    assert "Custom win against Enemy" in str(kwargs["components"][0].build())
    assert ctx.respond.await_args.kwargs["content"] == "Copy: Enemy"


def test_corrupt_template_prevents_public_send(monkeypatch):
    db = mongo()
    db.clans = SimpleNamespace(find_one=AsyncMock(return_value={"tag": "#ABC", "announcement_id": 777}))
    db.bot_config.rows["fwa_war_template:10:win"] = {
        "_id": "fwa_war_template:10:win", "schema_version": 1,
        "guild_id": 10, "variant": "win", "revision": 1, "sections": [],
    }
    monkeypatch.setattr(war_plans, "Clan", lambda data: SimpleNamespace(announcement_id=777))
    create = AsyncMock()
    ctx = SimpleNamespace(
        member=SimpleNamespace(role_ids=[war_plans.FWA_WAR_PLANS_CONFIG["fwa_clan_rep_role_id"]], display_name="Planner"),
        user=SimpleNamespace(id=5, username="Planner"),
        interaction=SimpleNamespace(guild_id=10),
        client=SimpleNamespace(rest=SimpleNamespace(create_message=create)),
        defer=AsyncMock(), respond=AsyncMock(),
    )
    command = war_plans.WarPlans()
    command.clan_name = "Our Clan|#ABC|12345"
    command.war_result = "win"
    command.opponent = "Enemy"
    run(command.invoke(ctx, mongo=db, coc_client=object()))
    create.assert_not_awaited()
    assert ctx.respond.await_count == 1
