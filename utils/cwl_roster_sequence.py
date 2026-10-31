"""Serial delivery of frozen roster sequences through an injected transport.

The application owns one worker instance. Transport adapters perform fresh Discord
permission/destination checks and classify known rejections; unknown exceptions
are never automatically retried. No dashboard or bot imports belong here.
"""
import asyncio
import math

from utils.cwl_roster_image_store import ImageConflict


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
            while True:
                if resume:
                    job = self.storage.sequence(sequence_id)
                    if not job or not await self.authorize(job):
                        return {'status': 'stopped', 'error': 'Send permission was removed'}
                    self.storage.resume_sequence(sequence_id)
                result = await self._advance(sequence_id, resume=resume)
                if result['status'] != 'rate_limited':
                    return result
                await asyncio.sleep(result['retry_after'])
                resume = True

    async def _advance(self, sequence_id, *, resume=False):
        import json
        job = self.storage.sequence(sequence_id)
        if not job or job['status'] != 'ready' or not job['announcement_message_id']:
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
            try:
                if receipt and resume:
                    receipt = self.storage.retry_sequence_image(sequence_id, item['request_id'])
                    acquired = True
                else:
                    receipt, acquired = self.storage.claim(
                        job['season_id'], job['pool'], item['tag'], job['target_version'],
                        item['request_id'], 'post', job['channel_id'], None, item['frozen'],
                        job['actor_id'], sequence_id=sequence_id,
                    )
            except ImageConflict as exc:
                return {'status': 'stopped', 'clan_tag': item['tag'], 'error': str(exc)}
            if not acquired:
                return self._blocked(item['tag'], receipt)
            try:
                message = await self.transport.image(job, item)
                self._message_id(message)
            except asyncio.CancelledError:
                self.storage.finish(receipt, 'uncertain', error='Delivery interrupted; check Discord first')
                raise
            except SequenceRateLimit as exc:
                self.storage.finish(receipt, 'failed', error=str(exc), retry_after=exc.seconds)
                return {'status': 'rate_limited', 'clan_tag': item['tag'], 'retry_after': exc.seconds}
            except SequenceRejected as exc:
                self.storage.finish(receipt, 'failed', error=str(exc))
                return {'status': 'stopped', 'clan_tag': item['tag'], 'error': str(exc)}
            except Exception:
                self.storage.finish(receipt, 'uncertain', error='Delivery outcome unknown; check Discord first')
                return {'status': 'uncertain', 'clan_tag': item['tag']}
            self.storage.finish(receipt, 'posted', str(message))
        if not await self.authorize(job):
            return {'status': 'stopped', 'step': 'closing', 'error': 'Send permission was removed'}
        try:
            receipt, acquired = self.storage.claim_sequence_closing(sequence_id, retry_failed=resume)
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
            self.storage.finish_sequence_closing(sequence_id, status='uncertain',
                                                 error='Delivery interrupted; check Discord first')
            raise
        except SequenceRateLimit as exc:
            self.storage.finish_sequence_closing(sequence_id, status='failed',
                                                 error=str(exc), retry_after=exc.seconds)
            return {'status': 'rate_limited', 'step': 'closing', 'retry_after': exc.seconds}
        except SequenceRejected as exc:
            self.storage.finish_sequence_closing(sequence_id, status='failed', error=str(exc))
            return {'status': 'stopped', 'step': 'closing', 'error': str(exc)}
        except Exception:
            self.storage.finish_sequence_closing(sequence_id, status='uncertain',
                                                 error='Delivery outcome unknown; check Discord first')
            return {'status': 'uncertain', 'step': 'closing'}
        self.storage.finish_sequence_closing(sequence_id, status='posted', message=str(message))
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
