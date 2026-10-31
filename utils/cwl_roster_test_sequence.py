"""Sequential full-test delivery; never reads or changes production sent marks."""
import asyncio
from utils.cwl_roster_image_store import ImageConflict
from utils.cwl_roster_sequence import SequenceRejected, SequenceRateLimit


class TestSequenceWorker:
    def __init__(self, storage, transport, authorize):
        self.storage = storage
        self.transport = transport
        self.authorize = authorize

    async def advance(self, request_id):
        while True:
            job = self.storage.test_sequence(request_id)
            if not job or job['status'] != 'ready':
                return job
            if not await self.authorize(job):
                self.storage.stop_test_sequence(request_id, 'Send permission was removed')
                return self.storage.test_sequence(request_id)
            try:
                claimed = self.storage.claim_test_step(request_id)
            except ImageConflict:
                return self.storage.test_sequence(request_id)
            step, item = claimed['step'], claimed['item']
            item = {**item, 'request_id': claimed['nonce']}
            try:
                if item['kind'] == 'announcement':
                    message = await self.transport.test_announcement(job, item)
                elif item['kind'] == 'image':
                    message = await self.transport.image(job, item)
                elif item['kind'] == 'closing':
                    message = await self.transport.closing(job, item)
                else:
                    raise SequenceRejected('Unknown test step')
                self.storage.finish_test_step(request_id, step, status='posted', message_id=message)
            except asyncio.CancelledError:
                self.storage.finish_test_step(request_id, step, status='uncertain', error='Test interrupted; check Discord before another test')
                raise
            except (SequenceRejected, SequenceRateLimit) as exc:
                self.storage.finish_test_step(request_id, step, status='failed', error=str(exc))
                return self.storage.test_sequence(request_id)
            except Exception:
                self.storage.finish_test_step(request_id, step, status='uncertain', error='Test delivery unconfirmed; check Discord before another test')
                return self.storage.test_sequence(request_id)
