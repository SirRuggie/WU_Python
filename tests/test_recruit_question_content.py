import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands.recruit import questions
from utils import recruit_question_content as content


def run(awaitable):
    return asyncio.run(awaitable)


class ConfigCollection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query):
        return copy.deepcopy(self.rows.get(query["_id"]))

    async def insert_one(self, row):
        if row["_id"] in self.rows:
            raise DuplicateKeyError("duplicate")
        self.rows[row["_id"]] = copy.deepcopy(row)
        return SimpleNamespace(inserted_id=row["_id"])

    async def update_one(self, query, update):
        row = self.rows.get(query["_id"])
        if row is None or row.get("revision") != query["revision"]:
            return SimpleNamespace(matched_count=0)
        row.update(copy.deepcopy(update["$set"]))
        return SimpleNamespace(matched_count=1)


def mongo():
    return SimpleNamespace(
        bot_config=ConfigCollection(),
        recruit_challenges=SimpleNamespace(update_one=AsyncMock(), delete_one=AsyncMock()),
    )


@pytest.mark.parametrize("variant", content.PRIMARY_VARIANTS)
def test_each_default_renders_original_layout_and_safe_preview(variant):
    template = content.default_template(variant)
    public = content.render_template(template, user_id=123, recruiter_id=456)
    preview = content.preview_template(template)
    assert len(public) == (2 if variant == "discord_basic_skills" else 1)
    assert public[0].build()[0]["components"][0]["content"].endswith("<@123>")
    assert public[0].build()[0]["components"][-1]["content"] == "-# Requested by <@456>"
    if variant == "discord_basic_skills":
        assert public[1].build()[0]["components"][0]["custom_id"] == "shield_basics:123:456"
        assert preview[1].build()[0]["components"][0]["disabled"] is True
    else:
        assert len(public[0].build()[0]["components"]) == 5
    if variant == "family_codes":
        text = public[0].build()[0]["components"][2]["content"]
        assert all(text.count(code) == 1 for code in content.VALID_EMOJI_CODES)


def test_save_load_reset_is_guild_scoped_and_revision_safe():
    db = mongo()
    draft = content.default_template("family_codes")
    draft["sections"][0] = "## Custom family code · {recruit}"
    saved = run(content.save_template(db, 10, "family_codes", draft, 0, 99))
    assert saved["revision"] == 1
    assert run(content.load_template(db, 10, "family_codes"))["sections"][0] == draft["sections"][0]
    assert run(content.load_template(db, 11, "family_codes"))["revision"] == 0
    with pytest.raises(content.TemplateConflict):
        run(content.save_template(db, 10, "family_codes", draft, 0, 99))
    with pytest.raises(content.TemplateConflict):
        run(content.reset_template(db, 10, "family_codes", 0, 99))
    reset = run(content.reset_template(db, 10, "family_codes", 1, 99))
    assert reset["revision"] == 2
    assert reset["sections"] == content.default_template("family_codes")["sections"]


@pytest.mark.parametrize("mutation", [
    lambda t: t["sections"].__setitem__(1, "codes removed"),
    lambda t: t["sections"].__setitem__(0, "{recruit.name}"),
    lambda t: t["sections"].__setitem__(0, "{unknown}"),
    lambda t: t.__setitem__("footer_url", "https://localhost/footer.png"),
    lambda t: t.__setitem__("accent", True),
])
def test_invalid_family_edits_rejected(mutation):
    template = content.default_template("family_codes")
    mutation(template)
    with pytest.raises(ValueError):
        content.validate_template("family_codes", template)


def test_corrupt_saved_template_fails_closed():
    db = mongo()
    db.bot_config.rows["recruit_question_template:10:family_codes"] = {
        "_id": "recruit_question_template:10:family_codes", "schema_version": 1,
        "guild_id": 10, "variant": "family_codes", "revision": 1,
        "sections": ["broken"], "footer_url": "assets/Gold_Footer.png", "accent": 1,
    }
    with pytest.raises(ValueError, match="invalid"):
        run(content.load_template(db, 10, "family_codes"))


def _ctx(choice):
    interaction = SimpleNamespace(
        values=[choice], id=100, custom_id="primary_questions:panel",
        delete_initial_response=AsyncMock(), message=SimpleNamespace(id=777),
    )
    return SimpleNamespace(
        interaction=interaction, guild_id=10, channel_id=20,
        member=SimpleNamespace(id=456, mention="<@456>", role_ids=[1554256650817511447], permissions=hikari.Permissions.NONE),
        respond=AsyncMock(),
    )


def test_primary_sender_uses_saved_copy_and_starts_family_challenge_after_validation(monkeypatch):
    db = mongo()
    template = content.default_template("family_codes")
    template["sections"][0] = "## Edited family request · {recruit}"
    run(content.save_template(db, 10, "family_codes", template, 0, 456))
    rest = SimpleNamespace(
        fetch_member=AsyncMock(return_value=SimpleNamespace(id=123, mention="<@123>")),
        create_message=AsyncMock(return_value=SimpleNamespace(id=777)),
    )
    bot = SimpleNamespace(rest=rest)
    monkeypatch.setattr(questions, "refresh_questions_panel", AsyncMock())
    monkeypatch.setattr(questions, "recruit_questions_page", AsyncMock(return_value=[]))
    ctx = _ctx("family_codes")
    run(questions.primary_questions(user_id=123, bot=bot, mongo=db, ctx=ctx))
    db.recruit_challenges.update_one.assert_awaited_once()
    sent = rest.create_message.await_args.kwargs
    assert "Edited family request" in str(sent["components"][0].build())
    assert sent["user_mentions"] == [123]
    assert sent["role_mentions"] is False and sent["mentions_everyone"] is False

    # A broken saved template must leave no challenge and post nothing.
    db.recruit_challenges.update_one.reset_mock()
    rest.create_message.reset_mock()
    db.bot_config.rows["recruit_question_template:10:family_codes"]["sections"] = ["broken"]
    ctx = _ctx("family_codes")
    run(questions.primary_questions(user_id=123, bot=bot, mongo=db, ctx=ctx))
    db.recruit_challenges.update_one.assert_not_awaited()
    rest.create_message.assert_not_awaited()
    ctx.respond.assert_awaited_once()


@pytest.mark.parametrize("fail_create", [False, True])
def test_shield_click_keeps_original_edited_copy(monkeypatch, fail_create):
    message = SimpleNamespace(
        id=777,
        components=[hikari.ContainerComponent(
            type=hikari.ComponentType.CONTAINER, id=1, accent_color=hikari.Color(0x123456),
            is_spoiler=False,
            components=[
                hikari.TextDisplayComponent(type=hikari.ComponentType.TEXT_DISPLAY, id=2,
                                            content="## Edited Basics · <@123>"),
                hikari.SeparatorComponent(type=hikari.ComponentType.SEPARATOR, id=3,
                                          spacing=hikari.SpacingType.SMALL, divider=True),
                hikari.TextDisplayComponent(type=hikari.ComponentType.TEXT_DISPLAY, id=4,
                                            content="Custom instructions remain here."),
                hikari.SeparatorComponent(type=hikari.ComponentType.SEPARATOR, id=5,
                                          spacing=hikari.SpacingType.SMALL, divider=True),
                hikari.TextDisplayComponent(type=hikari.ComponentType.TEXT_DISPLAY, id=6,
                                            content="-# Requested by <@456>"),
            ],
        )],
    )
    rest = SimpleNamespace(
        fetch_member=AsyncMock(side_effect=[SimpleNamespace(id=123, mention="<@123>"), SimpleNamespace(id=456, mention="<@456>")]),
        edit_message=AsyncMock(), create_message=AsyncMock(return_value=SimpleNamespace(id=888)),
    )
    from tests.test_recruit_goblin_challenges import db as goblin_db
    db = goblin_db()
    ctx = SimpleNamespace(
        guild_id=10, channel_id=20, user=SimpleNamespace(id=123, mention="<@123>"),
        member=SimpleNamespace(id=456),
        interaction=SimpleNamespace(custom_id="shield_basics:123:456", message=message),
        respond=AsyncMock(),
    )
    if fail_create:
        rest.create_message.side_effect = RuntimeError("Discord unavailable")
        with pytest.raises(RuntimeError):
            run(questions.on_shield_basics_button("123:456", bot=SimpleNamespace(rest=rest), mongo=db, ctx=ctx))
        rest.edit_message.assert_not_awaited()
        return
    run(questions.on_shield_basics_button("123:456", bot=SimpleNamespace(rest=rest), mongo=db, ctx=ctx))
    edited = rest.edit_message.await_args.kwargs["components"]
    payload = edited[0].build()[0]
    text = [part["content"] for part in payload["components"] if part["type"] == hikari.ComponentType.TEXT_DISPLAY]
    assert "Custom instructions remain here." in text
    assert text[-1] == "-# Requested by <@456>"
    assert len(edited) == 1
    kwargs = rest.edit_message.await_args.kwargs
    assert kwargs["user_mentions"] is False
    assert kwargs["role_mentions"] is False
    assert kwargs["mentions_everyone"] is False


def test_recruit_question_menu_uses_approved_labels_and_retains_values():
    panel = run(questions.recruit_questions_page('panel', 123))[0]
    menus = [child for row in panel.components if hasattr(row, 'components')
             for child in row.components if hasattr(child, 'options')]
    options = {option.value: option.label for menu in menus for option in menu.options}
    assert options['leaders_checking_you_out'] == 'Application Under Review'
    assert options['fwa_bases_upon_approval'] == 'FWA Bases (After Approval)'
    assert content.VARIANT_LABELS['leaders_checking_you_out'] == 'Application Under Review'
    assert content.VARIANT_LABELS['fwa_bases_upon_approval'] == 'FWA Bases (After Approval)'


def test_cwl_recruit_default_uses_exact_league_copy_and_signup_link():
    from utils.dashboard_urls import SIGNUP_URL
    template = content.default_template('warriors_united_cwl')
    assert template['sections'][1] == (
        "We use 20 clans for CWL, with leagues ranging from Master 1 to Gold 1. "
        "Players in all clans except our High Tactical Clans join these clans for CWL.\n\n"
        "Three factors determine the League you'll be placed in:\n\n"
        "1) War activity\n2) War performance\n3) Account strength\n\n"
        "We judge each factor against the League that you join.\n\n"
        "If you are new to the family and have no war history, your first CWL season can be in a lower league. "
        "This is for support or for strength. It is nothing personal. You are new and we do not know you yet. "
        "*We can make exceptions.*\n\n"
        f"You must sign up for CWL on the dashboard: {SIGNUP_URL}. "
        "Sign-ups open around Clan Games each month so that we can prepare rosters.\n\n"
        "## Is it a problem for you to sign up on the dashboard and move to another clan for CWL?"
    )


def test_family_code_default_uses_671_precedence_and_keeps_placeholders():
    template = content.default_template('family_codes')
    assert template['sections'][1] == (
        'You can move between family clans for donations, a Friendly Challenge, help with Clan Games or a Family Event. '
        'When you send a Clan Request, use one of these three emoji combinations as your request message.\n\n'
        '{family_codes}\n\n'
        '**DO NOT** use the default join message: "I\'d like to join your clan."\n\n'
        'To show that you understand, send one of the three codes above in this chat. '
        'Send it the same way you would send a request to join.'
    )
