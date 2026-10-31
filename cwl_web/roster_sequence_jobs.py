"""Backend lifecycle for the durable image sequence following the bot announcement."""
import asyncio
import logging
from contextlib import suppress
from types import SimpleNamespace

from utils.cwl_roster_image_store import ImageConflict, RosterImageStore
from utils.cwl_roster_sequence import SequenceWorker
from utils.cwl_web_bridge import BridgeConflict, get_roster_send_status, queue_roster_send
from utils.dashboard_access import OWNER_IDS, AccessRepository, effective, expand_legacy
from .manage_bridge import _mongo
from .roster_sequence_transport import SequenceTransport
from .server_management import GUILD_ID, discord

LOG = logging.getLogger(__name__)


class SequenceJobs:
    def __init__(self, app):
        self.app = app
        self.request = SimpleNamespace(app=app)
        self.storage = RosterImageStore(app['store'])
        self.tasks = {}

    async def authorized(self, job):
        uid = job['actor_id']
        if uid in OWNER_IDS:
            return True
        member = await discord(self.request, 'GET', f'/guilds/{GUILD_ID}/members/{uid}')
        async with _mongo(self.request) as mongo:
            document = await AccessRepository(mongo.bot_config).read()
            if document is not None:
                return 'cwl_send' in effective(document, uid, member.get('roles', []))
            grant = await mongo.bot_config.find_one({'_id': 'dashboard-access:' + uid}) or {}
            return 'cwl_send' in expand_legacy(grant.get('permissions', []))

    async def advance(self, sequence_id, *, resume=False):
        if resume:
            self.storage.resume_sequence(sequence_id)
        job = self.storage.sequence(sequence_id)
        if not job or job['status'] not in ('awaiting_announcement', 'ready'):
            return
        if not await self.authorized(job):
            self.storage.stop_sequence(sequence_id, 'Send permission was removed')
            return
        if job['status'] == 'awaiting_announcement':
            async with _mongo(self.request) as mongo:
                bridge = await get_roster_send_status(mongo, GUILD_ID, job['cycle'], job['pool'])
                if bridge is None:
                    # Revalidate the saved intent before recovering a missing native queue.
                    publication = self.storage.publication(job['season_id'])
                    if not publication or publication[1]['version'] != job['target_version']:
                        self.storage.stop_sequence(sequence_id, 'Published roster changed; review again')
                        return
                    # Recover a crash after SQLite intent but before native queue insertion.
                    try:
                        await queue_roster_send(
                            mongo, guild_id=GUILD_ID, cycle=job['cycle'], pool=job['pool'],
                            publication_version=job['target_version'], expected_generation=job['generation'],
                            expected_channel_id=int(job['channel_id']), requested_by=int(job['actor_id']),
                            sequence_id=sequence_id,
                        )
                    except BridgeConflict:
                        # The HTTP sender may have queued this same saved intent concurrently.
                        queued = await get_roster_send_status(mongo, GUILD_ID, job['cycle'], job['pool'])
                        if not queued or queued.get('sequence_id') != sequence_id:
                            raise
                    return
            if bridge.get('sequence_id') != sequence_id:
                self.storage.stop_sequence(sequence_id, 'Announcement belongs to another review; refresh')
                return
            if bridge.get('status') in ('pending', 'sending'):
                return
            if bridge.get('status') != 'sent':
                self.storage.stop_sequence(sequence_id, bridge.get('error') or 'Announcement is not confirmed')
                return
            try:
                self.storage.confirm_sequence_announcement(sequence_id, bridge)
            except ImageConflict as exc:
                self.storage.stop_sequence(sequence_id, str(exc))
                return
        worker = SequenceWorker(self.storage, SequenceTransport(self.app), self.authorized)
        result = await worker.advance(sequence_id, resume=resume)
        if result['status'] in ('stopped', 'uncertain'):
            where = result.get('clan_tag') or result.get('step') or 'sequence'
            self.storage.stop_sequence(sequence_id, f"Stopped at {where}: {result.get('error') or result['status']}")

    async def _run(self, sequence_id):
        try:
            await self.advance(sequence_id)
        except asyncio.CancelledError:
            raise
        except BridgeConflict as exc:
            self.storage.stop_sequence(sequence_id, str(exc))
        except Exception:
            # Persisted receipts prevent replay of any uncertain external side effect.
            LOG.exception('Roster sequence pass failed for %s', sequence_id)
        finally:
            self.tasks.pop(sequence_id, None)

    async def _run_test(self, request_id):
        from utils.cwl_roster_test_sequence import TestSequenceWorker
        try:
            await TestSequenceWorker(self.storage, SequenceTransport(self.app), self.authorized).advance(request_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception('Roster full-test pass failed for %s', request_id)
        finally:
            self.tasks.pop('test:' + request_id, None)

    def poll(self):
        for job in self.storage.pending_sequences():
            key = job['sequence_id']
            if key not in self.tasks:
                self.tasks[key] = asyncio.create_task(self._run(key), name='roster-sequence-' + key)

        for job in self.storage.pending_test_sequences():
            key = 'test:' + job['request_id']
            if key not in self.tasks:
                self.tasks[key] = asyncio.create_task(self._run_test(job['request_id']), name=key)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def lifecycle(app):
    if app.get('dev_fixture'):
        yield
        return
    jobs = SequenceJobs(app)
    app['roster_sequence_jobs'] = jobs
    async def loop():
        while True:
            try:
                jobs.poll()
            except Exception:
                LOG.exception('Could not read roster sequence queue; retrying next pass')
            await asyncio.sleep(5)
    task = asyncio.create_task(loop(), name='roster-sequences')
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await jobs.close()
