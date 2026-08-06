import asyncio
import importlib


def test_shutdown_cancels_and_awaits_all_owned_tasks():
    async def scenario():
        # This extension starts AsyncIOScheduler at import, so import it only
        # after a running loop exists, just as Hikari does in production.
        task_manager = importlib.import_module(
            "extensions.events.message.task_manager"
        )

        delete_task = asyncio.create_task(asyncio.sleep(60))
        cleanup_task = asyncio.create_task(asyncio.sleep(60))
        task_manager.delete_tasks[123] = delete_task
        task_manager.session_cleanup_tasks.add(cleanup_task)

        await task_manager.cleanup_tasks(None)

        return task_manager, delete_task, cleanup_task

    task_manager, delete_task, cleanup_task = asyncio.run(scenario())

    assert delete_task.done() and delete_task.cancelled()
    assert cleanup_task.done() and cleanup_task.cancelled()
    assert task_manager.delete_tasks == {}
    assert task_manager.session_cleanup_tasks == set()
    assert not task_manager.scheduler.running
