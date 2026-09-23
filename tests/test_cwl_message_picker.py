import asyncio

from extensions.commands import cwl_dashboard as ui
from tests.test_cwl_dashboard_integration import MemoryMongo, modal_context
from tests.test_cwl_navigation import nodes
from utils import cwl_campaign, cwl_sequence


def picker(components):
    return next(node for node in nodes(components) if str(node.get("custom_id", "")).startswith("cwl_message:"))


def test_picker_lists_each_post_once_with_plain_descriptions():
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        for audience in ("main", "lazy"):
            menu = picker(await ui.panel(draft, "messages_" + audience))
            assert len(menu["options"]) == len(draft["campaign"]["messages"])
            assert all(option["value"].endswith("|" + audience) for option in menu["options"])
            assert all("<:" not in option["description"] for option in menu["options"])
            assert len({option["label"] for option in menu["options"]}) == len(menu["options"])
    asyncio.run(scenario())


def test_numbered_reminders_sort_numerically_and_hide_unused_slots():
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        draft["campaign"] = cwl_sequence.configure(draft["campaign"], "evenly", count=4)
        menu = picker(await ui.panel(draft, "messages"))
        assert [option["value"] for option in menu["options"]] == [
            "signup|main", "reminder:1|main", "reminder:2|main", "reminder:3|main", "reminder:4|main", "roster|main",
        ]
        all_keys = [key for key, _ in ui._message_items(draft["campaign"])]
        assert all_keys.index("reminder:9") < all_keys.index("reminder:10") < all_keys.index("roster")
    asyncio.run(scenario())


def test_lazy_selection_opens_lazy_editor_and_back_keeps_lazy_picker():
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        ctx = modal_context(selections=("reminder:2|lazy",))
        editor = await ui.choose_message(ctx, draft["token"], mongo=mongo)
        assert any(node.get("custom_id") == f"cwl_text:{draft['token']}|reminder:2|lazy" for node in nodes(editor))
        back = next(node for node in nodes(editor) if node.get("label") == "Back to Messages")
        result = await ui.tab(ctx, back["custom_id"].split(":", 1)[1], mongo=mongo)
        assert all(option["value"].endswith("|lazy") for option in picker(result)["options"])
    asyncio.run(scenario())
