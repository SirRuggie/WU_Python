"""Bot liveness proof from public gateway state and existing scheduler work."""

import asyncio
from contextlib import suppress
import os
import time

from apscheduler.schedulers.base import STATE_RUNNING

from utils.external_heartbeat import ExternalHeartbeat
from utils.manage_poll_cache import state_for

PERIOD_SECONDS = 5 * 60
PROOF_MAX_AGE_SECONDS = 90
ENV_NAME = "WU_BOT_HEALTHCHECK_URL"


class BotHealth:
    def __init__(self, bot, mongo, scheduler, *, sender, clock=time.monotonic):
        self.bot = bot
        self.mongo = mongo
        self.scheduler = scheduler
        self.sender = sender
        self.clock = clock
        self.last_job = float("-inf")
        self.task = None
        self.stopping = False

    def job_ran(self):
        # Called only by the already-scheduled management admission job.
        try:
            self.last_job = self.clock()
        except Exception:
            pass

    def healthy(self):
        try:
            now = self.clock()
            shards = tuple(self.bot.shards.values())
            return bool(
                not self.stopping
                and self.bot.is_alive
                and shards
                and all(shard.is_alive and shard.is_connected for shard in shards)
                and self.scheduler.state == STATE_RUNNING
                and 0 <= now - self.last_job <= PROOF_MAX_AGE_SECONDS
                and 0
                <= now - state_for(self.mongo).heartbeat_at
                <= PROOF_MAX_AGE_SECONDS
            )
        except Exception:
            return False

    def check(self):
        # A disconnected/dead/stale bot does not send a reassuring ping.
        try:
            return self.sender.submit(True) if self.healthy() else False
        except Exception:
            return False

    async def run(self):
        while True:
            await asyncio.sleep(PERIOD_SECONDS)
            self.check()

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run(), name="bot-external-health")
        return self

    async def close(self):
        self.stopping = True
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.task
        with suppress(Exception):
            await self.sender.close()


def start(bot, mongo, scheduler):
    sender = ExternalHeartbeat(os.getenv(ENV_NAME, ""), "bot")
    if not sender.enabled:
        return None
    return BotHealth(bot, mongo, scheduler, sender=sender).start()
