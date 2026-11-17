"""Serial delivery of frozen roster sequences through an injected transport.

The application owns one worker instance. Transport adapters perform fresh Discord
permission/destination checks and classify known rejections; unknown exceptions
are never automatically retried. No dashboard or bot imports belong here.
"""
import asyncio
import math
import logging

from utils.cwl_roster_image_store import ImageConflict


async def persist_delivery_result(write):
    """Persist an already-known result, then propagate the original cancellation.

    Unlike an unstarted claim, a confirmed transport result cannot be abandoned
    in the writer queue. The task owns only this existing storage operation;
    it never repeats a transport request or changes a delivery classification.
    """
    task = asyncio.create_task(write)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                logging.getLogger(__name__).warning(
                    'Delivery result could not be persisted during cancellation',
                    exc_info=(type(error), error, error.__traceback__),
                )
        raise


async def cancel_image_claim(storage, receipt, *, sequence_id=None,
                             error='Delivery interrupted; check Discord first'):
    """Close only this still-owned in-flight receipt; never mask cancellation."""
    try:
        await persist_delivery_result(storage.store.run_writer(lambda: storage.finish(
            receipt, 'uncertain', error=error,
            sequence_id=sequence_id, only_sending=True,
        )))
    except (Exception, asyncio.CancelledError):
        logging.getLogger(__name__).exception('Cancelled image claim cleanup unavailable')


class SequenceRejected(Exception):
    """Discord definitively rejected a request before accepting the message."""


class SequenceRateLimit(SequenceRejected):
    def __init__(self, seconds):
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid Discord retry delay')
        self.seconds = seconds
        super().__init__('Discord rate limit')


class SequenceWorker:
    def __init__(self, storage, transport, authorize):
        self.storage = storage
        self.transport = transport
        self.authorize = authorize
        self._lock = asyncio.Lock()

    async def advance(self, sequence_id, *, resume=False):
        """Advance confirmed work; failed/unknown receipts require explicit recovery.

        Reopening after a crash skips confirmed receipts. An in-flight receipt is
        reported as uncertain, not retried, even if Discord's nonce window expired.
        """
        async with self._lock:
            saved = self.storage.sequence(sequence_id)
            resume = resume or bool(saved and saved.get('resume_requested'))
            while True:
                if resume:
                    job = self.storage.sequence(sequence_id)
                    if not job or not await self.authorize(job):
                        return {'status': 'stopped', 'error': 'Send permission was removed'}
                    (await self.storage.store.run_writer(lambda: self.storage.resume_sequence(sequence_id)))
                result = await self._advance(sequence_id, resume=resume)
                if result['status'] != 'rate_limited':
                    return result
                resume = True

    async def _advance(self, sequence_id, *, resume=False):
        import json
        job = self.storage.sequence(sequence_id)
        if not job or job['status'] != 'ready' or not (job['announcement_message_id'] or self.storage.announcement_assumption(sequence_id)):
            return {'status': job['status'] if job else 'missing'}
        plan = json.loads(job['plan_json'])
        for item in plan['clans']:
            receipt = self.storage.receipt(item['request_id'])
            if receipt:
                if receipt['status'] == 'posted' and receipt['message_id']:
                    continue
                if receipt['status'] != 'failed' or not resume:
                    return self._blocked(item['tag'], receipt)
            if not await self.authorize(job):
                return {'status': 'stopped', 'clan_tag': item['tag'], 'error': 'Send permission was removed'}
            completed_claim = []
            def claim_image():
                if receipt and resume:
                    result = (self.storage.retry_sequence_image(sequence_id, item['request_id']), True)
                else:
                    result = self.storage.claim(
                        job['season_id'], job['pool'], item['tag'], job['target_version'],
                        item['request_id'], 'post', job['channel_id'], None, item['frozen'],
                        job['actor_id'], sequence_id=sequence_id,
                        confirm_duplicate=item.get('confirm_duplicate', False),
                    )
                completed_claim.append(result)
                return result
            try:
                if receipt and resume:
                    if receipt.get('retry_after') is not None:
                        await asyncio.sleep(receipt['retry_after'])
                        if not await self.authorize(job):
                            return {'status': 'stopped', 'clan_tag': item['tag'], 'error': 'Send permission was removed'}
                receipt, acquired = await self.storage.store.run_writer(claim_image)
            except asyncio.CancelledError:
                if completed_claim and completed_claim[0][1]:
                    await cancel_image_claim(self.storage, completed_claim[0][0], sequence_id=sequence_id)
                raise
            except ImageConflict as exc:
                return {'status': 'stopped', 'clan_tag': item['tag'], 'error': str(exc)}
            if not acquired:
                return self._blocked(item['tag'], receipt)
            try:
                message = await self.transport.image(job, item)
                self._message_id(message)
            except asyncio.CancelledError:
                await cancel_image_claim(self.storage, receipt, sequence_id=sequence_id)
                raise
            except SequenceRateLimit as exc:
                (await persist_delivery_result(self.storage.store.run_writer(lambda: self.storage.finish(receipt, 'failed', error=str(exc), retry_after=exc.seconds, sequence_id=sequence_id))))
                return {'status': 'rate_limited', 'clan_tag': item['tag'], 'retry_after': exc.seconds}
            except SequenceRejected as exc:
                (await persist_delivery_result(self.storage.store.run_writer(lambda: self.storage.finish(receipt, 'failed', error=str(exc), sequence_id=sequence_id))))
                return {'status': 'stopped', 'clan_tag': item['tag'], 'error': str(exc)}
            except Exception:
                (await persist_delivery_result(self.storage.store.run_writer(lambda: self.storage.finish(receipt, 'uncertain', error='Delivery outcome unknown; check Discord first', sequence_id=sequence_id))))
                return {'status': 'uncertain', 'clan_tag': item['tag']}
            await persist_delivery_result(self.storage.store.run_writer(
                lambda: self.storage.finish(receipt, 'posted', str(message))))
        if not await self.authorize(job):
            return {'status': 'stopped', 'step': 'closing', 'error': 'Send permission was removed'}
        prior_closing = self.storage.closing_receipt(sequence_id)
        if resume and prior_closing and prior_closing.get('retry_after') is not None:
            await asyncio.sleep(prior_closing['retry_after'])
            if not await self.authorize(job):
                return {'status': 'stopped', 'step': 'closing', 'error': 'Send permission was removed'}
        completed_closing = []
        def claim_closing():
            result = self.storage.claim_sequence_closing(sequence_id, retry_failed=resume)
            completed_closing.append(result)
            return result
        async def cancel_closing(owned):
            try:
                await persist_delivery_result(self.storage.store.run_writer(
                    lambda: self.storage.finish_sequence_closing(
                        sequence_id, expected_request_id=owned['request_id'], status='uncertain',
                        error='Delivery interrupted; check Discord first')))
            except (Exception, asyncio.CancelledError):
                logging.getLogger(__name__).exception('Cancelled closing-note cleanup unavailable')
        try:
            receipt, acquired = await self.storage.store.run_writer(claim_closing)
        except asyncio.CancelledError:
            if completed_closing and completed_closing[0][1]:
                await cancel_closing(completed_closing[0][0])
            raise
        except ImageConflict as exc:
            return {'status': 'stopped', 'step': 'closing', 'error': str(exc)}
        if not acquired:
            return {'status': 'complete' if receipt['status'] == 'posted' else
                    'uncertain' if receipt['status'] in ('sending', 'uncertain') else 'stopped',
                    'step': 'closing'}
        try:
            message = await self.transport.closing(job, plan['closing'])
            self._message_id(message)
        except asyncio.CancelledError:
            await cancel_closing(receipt)
            raise
        except SequenceRateLimit as exc:
            (await persist_delivery_result(self.storage.store.run_writer(lambda: self.storage.finish_sequence_closing(sequence_id, expected_request_id=receipt['request_id'], status='failed',
                                                 error=str(exc), retry_after=exc.seconds))))
            return {'status': 'rate_limited', 'step': 'closing', 'retry_after': exc.seconds}
        except SequenceRejected as exc:
            (await persist_delivery_result(self.storage.store.run_writer(lambda: self.storage.finish_sequence_closing(sequence_id, expected_request_id=receipt['request_id'], status='failed', error=str(exc)))))
            return {'status': 'stopped', 'step': 'closing', 'error': str(exc)}
        except Exception:
            (await persist_delivery_result(self.storage.store.run_writer(lambda: self.storage.finish_sequence_closing(sequence_id, expected_request_id=receipt['request_id'], status='uncertain',
                                                 error='Delivery outcome unknown; check Discord first'))))
            return {'status': 'uncertain', 'step': 'closing'}
        await persist_delivery_result(self.storage.store.run_writer(
            lambda: self.storage.finish_sequence_closing(sequence_id, expected_request_id=receipt['request_id'], status='posted', message=str(message))))
        return {'status': 'complete'}

    @staticmethod
    def _message_id(value):
        import re
        if not re.fullmatch(r'\d{15,22}', str(value or '')):
            raise ValueError('Discord did not confirm a message ID')

    @staticmethod
    def _blocked(tag, receipt):
        return {'status': 'uncertain' if receipt['status'] in ('sending', 'uncertain') else 'stopped',
                'clan_tag': tag, 'error': receipt.get('error'), 'retry_after': receipt.get('retry_after')}
