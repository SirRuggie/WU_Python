"""Sequential full-test delivery; never reads or changes production sent marks."""
import asyncio
import logging
from utils.cwl_roster_image_store import ImageConflict
from utils.cwl_roster_sequence import SequenceRejected, SequenceRateLimit, persist_delivery_result


class TestSequenceWorker:
    def __init__(self, storage, transport, authorize):
        self.storage = storage
        self.transport = transport
        self.authorize = authorize

    async def _cancel_step(self, request_id, claimed, actor):
        try:
            await persist_delivery_result(self.storage.store.run_writer(
                lambda: self.storage.finish_test_step(
                    request_id, claimed['step'], status='uncertain',
                    error='Test interrupted; check Discord before another test',
                    only_sending=True, expected_actor=actor,
                )
            ))
        except (Exception, asyncio.CancelledError):
            logging.getLogger(__name__).exception('Cancelled test-step cleanup unavailable')

    async def advance(self, request_id):
        while True:
            job = self.storage.test_sequence(request_id)
            if not job or job['status'] != 'ready':
                return job
            if not await self.authorize(job):
                await self.storage.store.run_writer(
                    lambda: self.storage.stop_test_sequence(request_id, 'Send permission was removed'))
                return self.storage.test_sequence(request_id)
            completed_claim = []
            def claim_step():
                result = self.storage.claim_test_step(request_id)
                # The entire service method, including its commit, returned.
                completed_claim.append(result)
                return result
            try:
                claimed = await self.storage.store.run_writer(claim_step)
            except asyncio.CancelledError:
                if completed_claim:
                    await self._cancel_step(request_id, completed_claim[0], job['actor_id'])
                raise
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
            except asyncio.CancelledError:
                await self._cancel_step(request_id, claimed, job['actor_id'])
                raise
            except (SequenceRejected, SequenceRateLimit) as exc:
                await persist_delivery_result(self.storage.store.run_writer(
                    lambda: self.storage.finish_test_step(request_id, step, status='failed', error=str(exc))))
                return self.storage.test_sequence(request_id)
            except Exception:
                await persist_delivery_result(self.storage.store.run_writer(
                    lambda: self.storage.finish_test_step(request_id, step, status='uncertain', error='Test delivery unconfirmed; check Discord before another test')))
                return self.storage.test_sequence(request_id)
            # Outside the transport exception handlers: cancellation of this
            # known-result write must not perform a second uncertain finish.
            await persist_delivery_result(self.storage.store.run_writer(
                lambda: self.storage.finish_test_step(request_id, step, status='posted', message_id=message)))
