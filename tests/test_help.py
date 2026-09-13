import asyncio

from extensions.commands import help as help_command
from utils.startup import tickets_guild_id


def _select_values(container) -> list[str]:
    for component in container.components:
        if hasattr(component, "components") and getattr(component, "components", None):
            inner = component.components[0]
            if hasattr(inner, "options"):
                return [option.value for option in inner.options]
    raise AssertionError("no select menu found in container")


def test_help_view_lists_tickets_v2_only_in_the_pilot_guild():
    pilot_view = asyncio.run(help_command.create_help_view(tickets_guild_id()))
    other_view = asyncio.run(help_command.create_help_view(123))
    no_guild_view = asyncio.run(help_command.create_help_view(None))

    assert "tickets_v2" in _select_values(pilot_view[0])
    assert "tickets_v2" not in _select_values(other_view[0])
    assert "tickets_v2" not in _select_values(no_guild_view[0])


def test_category_view_falls_back_when_tickets_v2_is_out_of_guild():
    pilot_category = asyncio.run(
        help_command.create_category_view("tickets_v2", tickets_guild_id())
    )
    assert pilot_category[0].components[0].content == "# 🧪 Ticket Pilot"

    other_category = asyncio.run(help_command.create_category_view("tickets_v2", 123))
    assert other_category[0].components[0].content == "# 🧭 Warriors United Command Guide"
