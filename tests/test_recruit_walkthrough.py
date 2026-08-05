import asyncio

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
