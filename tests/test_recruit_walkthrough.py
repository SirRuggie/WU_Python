import asyncio
from types import SimpleNamespace

from extensions import components
from extensions.commands.recruit.dashboard import manage_roles
from extensions.commands.recruit.dashboard import server_walkthrough


def test_walkthrough_running_covers_starting_and_active_states():
    key = (1, 2)
    server_walkthrough.active_walkthrough_tasks.clear()
    server_walkthrough._starting_walkthroughs.clear()

    server_walkthrough._starting_walkthroughs.add(key)
    assert server_walkthrough.walkthrough_is_running(key)
    server_walkthrough._starting_walkthroughs.clear()

    async def scenario():
        task = asyncio.create_task(asyncio.sleep(30))
        server_walkthrough.active_walkthrough_tasks[key] = task
        assert server_walkthrough.walkthrough_is_running(key)
        await server_walkthrough.stop_walkthrough_tasks(None)
        assert task.cancelled()
        assert not server_walkthrough.walkthrough_is_running(key)

    asyncio.run(scenario())


def test_legacy_role_page_handler_checks_original_compound_state_id():
    # Dispatcher state lookup cannot run first: old buttons encode
    # ``<original_action_id>:<page>`` in the action-id segment.
    assert not components.registered_functions["remove_roles_page"].requires_state


def test_expired_begin_walkthrough_never_falls_back_to_clicker(monkeypatch):
    async def missing_state(*args, **kwargs):
        return None

    monkeypatch.setattr(server_walkthrough, "get_state", missing_state)

    class Ctx:
        user = SimpleNamespace(id=22)
        interaction = SimpleNamespace(
            guild_id=11,
            custom_id="begin_walkthrough:expired-state:#CLAN",
        )

        def __init__(self):
            self.responses = []

        async def respond(self, content, **kwargs):
            self.responses.append((content, kwargs))

    member = SimpleNamespace(role_ids=[1003797104088592444])
    guild = SimpleNamespace(get_member=lambda user_id: member)
    bot = SimpleNamespace(cache=SimpleNamespace(get_guild=lambda guild_id: guild))
    ctx = Ctx()

    asyncio.run(server_walkthrough.begin_walkthrough_handler(
        ctx=ctx,
        action_id="expired-state:#CLAN",
        mongo=SimpleNamespace(),
        bot=bot,
    ))

    assert ctx.responses == [(
        "This walkthrough button has expired. Please run the recruit dashboard again.",
        {"ephemeral": True},
    )]
    assert server_walkthrough.active_walkthrough_tasks == {}
    assert server_walkthrough._starting_walkthroughs == set()
