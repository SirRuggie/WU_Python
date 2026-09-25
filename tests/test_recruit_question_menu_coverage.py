"""Every enabled recruitment choice must remain reachable in its editing menu."""
import asyncio

from extensions import components
from extensions.commands import recruitment_questions as editor
from extensions.commands.recruit import questions


def text_menus(panel):
    menus = []
    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            if node.get("type") == 3:
                menus.append(node)
            walk(node.get("components", []))
    walk([part.build()[0] for part in panel])
    return menus


def test_editing_home_matches_all_four_live_recruitment_dropdowns():
    sender = asyncio.run(questions.recruit_questions_page(action_id="source", user_id=22))
    editing = editor._home({"_id": "draft", "manage_token": "home"})
    expected = text_menus(sender)
    actual = text_menus(editing)
    assert [menu["placeholder"] for menu in actual] == [
        "Primary Questions", "FWA Questions", "Explanations", "Keep It Moving",
    ]
    assert len(expected) == len(actual) == 4
    for source, target in zip(expected, actual, strict=True):
        assert [(item["label"], item["value"]) for item in target["options"]] == [
            (item["label"], item["value"]) for item in source["options"]
        ]
        action = target["custom_id"].partition(":")[0]
        assert action in components.registered_functions
        for option in target["options"]:
            template = editor.content.default_template(option["value"])
            editor.content.validate_template(option["value"], template)
    assert sum(len(menu["options"]) for menu in actual) == 20


def test_every_group_choice_opens_an_editable_draft_without_saving(monkeypatch):
    from unittest.mock import AsyncMock
    from tests.test_recruit_question_content import mongo
    from tests.test_recruitment_questions import ctx

    db = mongo()
    state = {"_id": "home", "user_id": 1, "guild_id": 2,
             "manage_token": "manage", "view": "home"}
    monkeypatch.setattr(editor, "_state", AsyncMock(return_value=(state, None)))
    drafts = []

    async def next_draft(_mongo, original, **changes):
        draft = {**original, **changes, "_id": "draft"}
        drafts.append(draft)
        return draft

    monkeypatch.setattr(editor, "_next", next_draft)
    context = ctx()
    for group_key, definition in editor.content.GROUPS.items():
        for variant in definition["variants"]:
            context.interaction.values = (variant,)
            panel = asyncio.run(editor.group(context, f"home|{group_key}", mongo=db))
            assert drafts[-1]["variant"] == variant
            assert drafts[-1]["view"] == "editor"
            assert drafts[-1]["template"] == drafts[-1]["saved_template"]
            options = text_menus(panel)[0]["options"]
            indexes = [int(index) for option in options for index in option["value"].split(",")]
            assert sorted(indexes) == list(range(len(drafts[-1]["template"]["sections"])))
    assert len(drafts) == 20
    assert not db.bot_config.rows

    context.interaction.values = ("attack_strategies",)
    asyncio.run(editor.group(context, "home|fwa", mongo=db))
    assert len(drafts) == 20
