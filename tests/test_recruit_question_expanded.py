"""All four Recruit Questions groups publish their saved, editable native layouts."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.recruit import questions
from utils import recruit_question_content as content
from utils.recruit_question_native import native_components
from tests.test_recruit_question_content import mongo


def run(coro):
    return asyncio.run(coro)


ADDED = tuple(variant for variant in content.VARIANTS if variant not in content.PRIMARY_VARIANTS)


@pytest.mark.parametrize("variant", ADDED)
def test_expanded_defaults_match_native_and_saved_text_media_are_guild_scoped(variant):
    template = content.default_template(variant)
    rendered = content.render_template(template, user_id=22, recruiter_id=11, action_id="panel-state")
    native = native_components(variant, recruit_mention="<@22>", recruiter_mention="<@11>", action_id="panel-state")
    assert [part.build() for part in rendered] == [part.build() for part in native]
    assert content.validate_template(variant, template)["media"] == template["media"]

    changed = copy.deepcopy(template)
    changed["sections"][0] = "## Edited {recruit}"
    first_slot = next(iter(changed["media"]))
    changed["media"][first_slot] = "https://cdn.example.org/recruitment/edited.png"
    db = mongo()
    saved = run(content.save_template(db, 10, variant, changed, 0, 99))
    assert saved["revision"] == 1
    loaded = run(content.load_template(db, 10, variant))
    assert loaded["sections"][0] == "## Edited {recruit}"
    assert loaded["media"][first_slot].endswith("edited.png")
    assert run(content.load_template(db, 11, variant))["revision"] == 0
    public = content.render_template(loaded, user_id=22, recruiter_id=11)
    assert "Edited <@22>" in str([item.build() for item in public])
    assert "edited.png" in str([item.build() for item in public])


def test_fwa_base_required_tokens_and_safe_separate_previews():
    template = content.default_template("fwa_bases_upon_approval")
    selector = content.preview_template(template)
    result = content.preview_template(template, stage="result")
    assert len(selector) == 1 and len(result) == 3
    assert "'disabled': True" in str(selector[0].build())
    assert "'disabled': True" in str([part.build() for part in result])
    assert "Example FWA base instructions" in str([part.build() for part in result])
    for index, token in ((3, "{recruit}"), (4, "{town_hall}"), (5, "{th_number}"),
                         (6, "{base_info}"), (7, "{recruiter}")):
        changed = copy.deepcopy(template)
        changed["sections"][index] = changed["sections"][index].replace(token, "hardcoded")
        with pytest.raises(ValueError, match="placeholders"):
            content.validate_template("fwa_bases_upon_approval", changed)
    changed = content.default_template("what_is_fwa")
    changed["sections"][0] = "{base_info}"
    with pytest.raises(ValueError, match="placeholders"):
        content.validate_template("what_is_fwa", changed)


def _ctx(group, variant):
    interaction = SimpleNamespace(
        values=[variant], id=100, custom_id=f"{group}:panel",
        delete_initial_response=AsyncMock(), guild_id=10,
    )
    return SimpleNamespace(
        interaction=interaction, guild_id=10, channel_id=20,
        member=SimpleNamespace(id=456, mention="<@456>"), respond=AsyncMock(),
    )


@pytest.mark.parametrize("group,variant", [
    (group, variant)
    for group in ("fwa", "explanations", "keep_it_moving")
    for variant in content.GROUPS[group]["variants"]
    if variant != "fwa_bases_upon_approval"
])
def test_expanded_sender_handlers_use_saved_copy_and_selected_recruit(monkeypatch, group, variant):
    db = mongo()
    template = content.default_template(variant)
    template["sections"][0] = "## Saved for {recruit}"
    run(content.save_template(db, 10, variant, template, 0, 456))
    rest = SimpleNamespace(
        fetch_member=AsyncMock(return_value=SimpleNamespace(id=123, mention="<@123>")),
        create_message=AsyncMock(return_value=SimpleNamespace(id=777)),
    )
    monkeypatch.setattr(questions.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(questions, "recruit_questions_page", AsyncMock(return_value=[]))
    handler = {
        "fwa": questions.fwa_questions,
        "explanations": questions.explanations,
        "keep_it_moving": questions.keep_it_moving,
    }[group]
    ctx = _ctx({"fwa": "fwa_questions", "explanations": "explanations", "keep_it_moving": "keep_it_moving"}[group], variant)
    run(handler(user_id=123, bot=SimpleNamespace(rest=rest), mongo=db, ctx=ctx))
    sent = rest.create_message.await_args.kwargs
    assert "Saved for <@123>" in str([part.build() for part in sent["components"]])
    assert sent["user_mentions"] == [123]
    assert sent["role_mentions"] is False and sent["mentions_everyone"] is False


def test_fwa_base_selector_and_public_th_result_use_saved_copy_with_live_base_data(monkeypatch):
    db = mongo()
    template = content.default_template("fwa_bases_upon_approval")
    template["sections"][1] = "Choose a TH for {recruit}."
    template["sections"][6] = "Saved lead. {base_info}"
    run(content.save_template(db, 10, "fwa_bases_upon_approval", template, 0, 456))
    rest = SimpleNamespace(
        fetch_member=AsyncMock(return_value=SimpleNamespace(id=123, mention="<@123>")),
        create_message=AsyncMock(return_value=SimpleNamespace(id=777)),
    )
    monkeypatch.setattr(questions.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(questions, "recruit_questions_page", AsyncMock(return_value=[]))
    selector_ctx = _ctx("fwa_questions", "fwa_bases_upon_approval")
    run(questions.fwa_questions(user_id=123, bot=SimpleNamespace(rest=rest), mongo=db, ctx=selector_ctx))
    selector = selector_ctx.respond.await_args_list[0].kwargs["components"]
    assert "Choose a TH for <@123>" in str(selector[0].build())
    assert "th_select:panel" in str(selector[0].build())
    rest.create_message.assert_not_awaited()

    base = SimpleNamespace(
        fwa_base_links=SimpleNamespace(th18="https://example.org/live-base"),
        base_information={"th18": "Live instructions from Mongo"},
    )
    monkeypatch.setattr(questions, "get_fwa_base_object", AsyncMock(return_value=base))
    monkeypatch.setitem(questions.FWA_WAR_BASE, "th18", "https://example.org/live-war.png")
    monkeypatch.setitem(questions.FWA_ACTIVE_WAR_BASE, "th18", "https://example.org/live-active.png")
    public_ctx = _ctx("th_select", "th18")
    run(questions.th_select(user_id=123, bot=SimpleNamespace(rest=rest), mongo=db, ctx=public_ctx))
    sent = rest.create_message.await_args.kwargs
    payload = str([part.build() for part in sent["components"]])
    assert "Saved lead. Live instructions from Mongo" in payload
    assert "https://example.org/live-base" in payload
    assert "live-war.png" in payload and "live-active.png" in payload
    assert sent["user_mentions"] == [123]
