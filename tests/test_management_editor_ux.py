"""Navigation and saved-state cues for the three private content editors."""
import asyncio
import copy

from extensions.commands import content, recruitment_questions, fwa_war_messages, manage
from utils import recruit_question_content, fwa_war_content
from unittest.mock import AsyncMock
from types import SimpleNamespace


def _built(panel):
    return panel[0].build()[0]["components"]


def _text(rows):
    return " ".join(row["content"] for row in rows if "content" in row)


def _buttons(row):
    return [item for item in row["components"] if item["type"] == 2]


def test_content_panel_uses_real_snapshot_and_separate_navigation_footer():
    document = content.DOCUMENTS["about-us"]
    sections = [node.content for node in content.text_nodes(asyncio.run(content.baseline(document)))]
    state = {
        "_id": "draft", "guild_id": 2, "document": document.key, "sections": sections,
        "media": {}, "destination_channel_id": 123, "manage_token": "home",
        "view": "document",
    }
    state["saved_snapshot"] = content.draft_snapshot(state)
    rows = _built(content.panel(state))
    assert "Management › Recruit Gauntlet › About Us" in _text(rows)
    assert "Saved" in _text(rows)
    assert "Posting target: <#123>" in _text(rows)
    assert [button["label"] for button in _buttons(rows[-1])] == ["Back to Recruit Gauntlet", "Management Home"]
    assert all(button.get("emoji") for button in _buttons(rows[-1]))
    state["sections"] = sections.copy()
    state["sections"][0] += " changed"
    rows = _built(content.panel(state))
    assert "Unsaved changes" in _text(rows)
    assert "Management Home" not in [button["label"] for button in _buttons(rows[-3])]


def test_question_editor_status_and_navigation_follow_saved_template():
    variant = "attack_strategies"
    template = recruit_question_content.default_template(variant)
    state = {
        "_id": "draft", "manage_token": "home", "variant": variant,
        "template": template, "saved_template": copy.deepcopy(template),
    }
    rows = _built(recruitment_questions._editor(state))
    assert "Management › Recruitment Questions ›" in _text(rows)
    assert "Saved" in _text(rows)
    assert "Posting target: Future `/recruit questions`" in _text(rows)
    assert [button["label"] for button in _buttons(rows[-1])] == ["Back to Questions", "Management Home"]
    assert _buttons(rows[-1])[1]["custom_id"] == "manage_home:home"
    state["template"] = copy.deepcopy(template)
    state["template"]["sections"][0] += " changed"
    rows = _built(recruitment_questions._editor(state))
    assert "Unsaved changes" in _text(rows)
    assert _buttons(rows[-1])[1]["custom_id"] == "recruit_question_leave:draft"


def test_war_editor_status_and_navigation_follow_saved_template():
    template = fwa_war_content.default_template("win")
    state = {
        "_id": "draft", "manage_token": "home", "variant": "win",
        "template": template, "saved_template": copy.deepcopy(template),
    }
    rows = _built(fwa_war_messages._editor(state))
    assert "Management › FWA › War Messages › Win" in _text(rows)
    assert "Saved" in _text(rows)
    assert "Posting target: Future `/fwa war-plans`" in _text(rows)
    assert [button["label"] for button in _buttons(rows[-1])] == ["Back to War Messages", "Back to FWA", "Management Home"]
    assert _buttons(rows[-1])[1]["custom_id"] == "manage_fwa:home"
    assert _buttons(rows[-1])[2]["custom_id"] == "manage_home:home"
    state["template"] = copy.deepcopy(template)
    state["template"]["sections"][0] += " changed"
    rows = _built(fwa_war_messages._editor(state))
    assert "Unsaved changes" in _text(rows)
    assert _buttons(rows[-1])[1]["custom_id"] == "fwa_war_leave:draft"
    assert _buttons(rows[-1])[2]["custom_id"] == "fwa_war_leave_home:draft"


def test_war_home_route_requires_review_only_for_dirty_draft(monkeypatch):
    template = fwa_war_content.default_template("win")
    state = {
        "_id": "draft", "manage_token": "home", "variant": "win", "view": "editor",
        "template": copy.deepcopy(template), "saved_template": copy.deepcopy(template),
    }
    context = SimpleNamespace()
    monkeypatch.setattr(fwa_war_messages, "_state", AsyncMock(return_value=(state, None)))
    monkeypatch.setattr(manage, "home", AsyncMock(return_value=["management"]))
    assert asyncio.run(fwa_war_messages.leave_home(context, "draft", mongo=object())) == ["management"]
    manage.home.assert_awaited_once()
    state["template"]["sections"][0] += " changed"
    review = asyncio.run(fwa_war_messages.leave_home(context, "draft", mongo=object()))
    assert "Unsaved changes" in str(review[0].build())
    assert "manage_home:home" in str(review[0].build())
    assert "fwa_war_back_editor:draft" in str(review[0].build())
    manage.home.assert_awaited_once()
