"""All four Recruit Questions groups publish their saved, editable native layouts."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.recruit import questions
from utils import recruit_question_content as content
from utils.recruit_question_native import native_base_result, native_components
from tests.test_recruit_question_content import mongo


def run(coro):
    return asyncio.run(coro)


ADDED = tuple(variant for variant in content.VARIANTS if variant not in content.PRIMARY_VARIANTS)


def test_native_base_result_preserves_link_destination_and_approved_label():
    components = native_base_result(
        recruit_mention="<@22>", recruiter_mention="<@11>",
        friendly_name="Example", th_number="16", base_info="Example status",
        base_link="https://example.org/base", war_base_media="https://example.org/war.png",
        active_war_base_media="https://example.org/active.png",
    )
    built = [component.build()[0] for component in components]
    button = built[1]["components"][2]["components"][0]
    assert button["label"] == "Open base link"
    assert button["url"] == "https://example.org/base"
    assert button["style"] == hikari.ButtonStyle.LINK


@pytest.mark.parametrize("variant", ADDED)
def test_expanded_defaults_match_native_and_saved_text_media_are_guild_scoped(variant):
    template = content.default_template(variant)
    rendered = content.render_template(template, user_id=22, recruiter_id=11, action_id="panel-state")
    native = native_components(variant, recruit_mention="<@22>", recruiter_mention="<@11>", action_id="panel-state")
    # The editor normalizes trailing whitespace; Discord renders both identically.
    def normalized(value):
        if isinstance(value,str):return value.rstrip()
        if isinstance(value,dict):return {k:normalized(v) for k,v in value.items()}
        if isinstance(value,(list,tuple)):return [normalized(v) for v in value]
        return value
    assert normalized([part.build() for part in rendered]) == normalized([part.build() for part in native])
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
        delete_initial_response=AsyncMock(), message=SimpleNamespace(id=777), guild_id=10,
    )
    return SimpleNamespace(
        interaction=interaction, guild_id=10, channel_id=20,
        member=SimpleNamespace(id=456, mention="<@456>", role_ids=[1554256650817511447], permissions=hikari.Permissions.NONE), respond=AsyncMock(),
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
    monkeypatch.setattr(questions, "refresh_questions_panel", AsyncMock())
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
    monkeypatch.setattr(questions, "refresh_questions_panel", AsyncMock())
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


def test_lazy_cwl_native_default_preserves_baseline_participation_and_fwa_rule():
    template = content.default_template('lazy_cwl_explanation')
    rendered = content.render_template(template, user_id=22, recruiter_id=11, action_id='panel-state')
    texts = [node.content for node in content._text_nodes(rendered)]
    participation = next(text for text in texts if '**Participation Requirement**' in text)
    assert 'Follow the Lazy CWL rules and complete **at least 4+ attacks (60%)**.' in participation
    assert '**Bonus Medals**' in participation
    important = next(text for text in texts if 'IMPORTANT:' in text)
    assert '*Participating in CWL outside of Warriors United is **__not allowed if__** you are part of our FWA Operation.*' in important
    assert '**__Lazy Way is My Way!!__**' in important


def test_fwa_native_overview_uses_exact_approved_benefit_lines():
    rendered = native_components('what_is_fwa', recruit_mention='<@22>', recruiter_mention='<@11>', action_id='panel')
    texts = [part.content for container in rendered for part in container.components if hasattr(part, 'content')]
    overview = next(text for text in texts if 'Maximized Loot and XP' in text)
    from utils.emoji import emojis
    assert overview == (
        "## 📌 FWA Clans in Clash of Clans: A Quick Overview\n"
        f"> Minimum TH for FWA: TH13 {emojis.TH13}\n\n"
        "FWA, or Farm War Alliance, is a unique concept in Clash of Clans. The goal is to get the most loot and clan XP, not only to win wars.\n\n"
        "### **__<a:FWA:1398229188363948055> What are the benefits?__**\n"
        "**<a:Gold_Coins:1398229429892808745> Maximized Loot and XP**\n"
        "FWA clans give a steady supply of resources and XP. Use them to upgrade bases, troops and heroes.\n\n"
        "**<a:sleep_zzz:1398229533617946646> War Participation with Upgrading Heroes**\n"
        "In FWA you can take part in a war even when your heroes are down for upgrades. So you can upgrade all the time.\n\n"
        "**<:CoolOP:1398229909339508839> Fair Wars**\n"
        "A lottery decides the war winner. Both sides have a fair chance and get a lot of loot.\n\n"
        "**<:Waiting:1398229981003382815> Is it against the rules?**\n"
        "No. FWA clans follow the game rules and do not use hacks or exploits. They stay within the game's terms of service. It is a different but accepted way to play."
    )


def test_lazy_rules_link_retains_destination_with_approved_label():
    from utils.recruit_question_native import LAZY_CWL_RULES_URL
    rendered = native_components('lazy_cwl_explanation', recruit_mention='<@22>', recruiter_mention='<@11>', action_id='panel')
    buttons = [child for container in rendered for row in container.components
               for child in getattr(row, 'components', ()) if getattr(child, 'label', None) == 'Lazy CWL Rules']
    assert len(buttons) == 1
    assert buttons[0].url == LAZY_CWL_RULES_URL


def test_fwa_review_native_uses_exact_do_not_ping_copy():
    rendered = native_components('fwa_leaders_reviewing', recruit_mention='<@22>', recruiter_mention='<@11>', action_id='panel')
    fields = [part.content for container in rendered for part in container.components if hasattr(part, 'content')]
    assert ('Thank you for applying! Our **FWA leadership team** is now reviewing your submission. '
            'This can take a little time as we adjust rosters to accommodate your application.\n\n'
            '**Do not ping anyone** during this time.\n'
            'We know that you are here. We will update you as soon as we can.') in fields


def test_fwa_chat_and_flexible_fun_native_fields_use_exact_approved_copy():
    expected = [
        ('fwa_clan_chat', (
            'Here’s what to expect from activity and chat in our FWA clans. FWA is one of the easiest'
            ' ways to get loot in the game. It suits players who are less active than players who pla'
            'y for social contact or for competition. So our clans are not very chatty. Clan chat is '
            'quiet most of the time, and donations can take longer. You still get them, but they do n'
            'ot always come fast. Our Discord server is a good place to talk if you want more convers'
            'ation.\n\n**Would any of this be an issue for you?**'
        )),
        ('what_is_flexible_fun', (
            '### Concept\nWe are a laid-back farm/war clan — **NOT A CAMPING CLAN**. All Town Hall lev'
            'els are welcome, and heroes are not required for war. You may not feel sure about attack'
            'ing without heroes. This is normal. Our simple default war plan is Drop 2. Everyone must'
            ' make at least the first war attack. We do not judge the result. Do your best. Our ultim'
            'ate goal is a stress-free, fun and flexible experience.\n\n### Purpose\nOur goal is a fun a'
            'nd flexible war clan. Heroes can be down here. Every member can make war attacks, and no'
            'body sits out because of hero upgrades.\n\n### Core Rules\n**No camping:** This clan is for'
            ' war. Members must take part.\n**Minimum Participation:** Even with heroes down, every me'
            'mber is required to execute at least one war attack. Failure to participate in war earns'
            ' a strike. If you get enough strikes, we can replace you.'
        )),
    ]
    for variant, field in expected:
        rendered = native_components(variant, recruit_mention='<@22>', recruiter_mention='<@11>', action_id='panel')
        texts = [part.content for container in rendered for part in container.components if hasattr(part, 'content')]
        assert field in texts
