"""Bot lifecycle for the bounded official-API member activity service."""
import asyncio

import coc
import hikari
import lightbulb

from utils.mongo import MongoClient
from utils.player_activity_polling import run

loader = lightbulb.Loader()
_task = None


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def started(event, mongo: MongoClient = lightbulb.di.INJECTED,
                  coc_client: coc.Client = lightbulb.di.INJECTED):
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(run(mongo, coc_client), name='player-activity')


@loader.listener(hikari.StoppingEvent)
async def stopped(event):
    global _task
    task, _task = _task, None
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
