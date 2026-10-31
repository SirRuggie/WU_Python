"""Discord/PNG adapter for durable sequences; no browser drives delivery."""
import asyncio
import json
import math
from types import SimpleNamespace

import aiohttp
from aiohttp import web

from utils.cwl_roster_sequence import SequenceRateLimit, SequenceRejected
from utils.cwl_roster_image_store import RosterImageStore
from .roster_image_posts import groups_for
from .roster_images import render
from .server_management import discord, GUILD_ID


class SequenceTransport:
    def __init__(self, app):
        self.request = SimpleNamespace(app=app)
        self.storage = RosterImageStore(app['store'])

    async def _destination(self, channel):
        try:
            destination = await discord(self.request, 'GET', f'/channels/{channel}')
        except Exception as exc:
            # No message request has been attempted yet.
            raise SequenceRejected('Could not verify the reviewed Discord channel') from exc
        if str(destination.get('guild_id')) != str(GUILD_ID) or destination.get('type') not in (0, 5):
            raise SequenceRejected('The reviewed channel is no longer a text channel in this server')

    async def image(self, job, item):
        await self._destination(job['channel_id'])
        publication = self.storage.publication(job['season_id'], job['target_version'])
        if not publication:
            raise SequenceRejected('The reviewed publication is unavailable')
        _, pub, groups = groups_for(publication)
        group = groups.get(item['tag'])
        if not group or group['pool'] != job['pool']:
            raise SequenceRejected('Clan is not in the reviewed publication')
        frozen = item['frozen']
        group = {**group, 'name': frozen['name'], 'league': frozen['league']}
        pages = math.ceil(len(group['accounts']) / 15)
        if not 1 <= pages <= 10:
            raise SequenceRejected('The roster must fit in one Discord message')
        try:
            images = await asyncio.gather(*(asyncio.to_thread(
                render, {'label': frozen['season_label']}, pub, group, page,
            ) for page in range(1, pages + 1)))
        except Exception as exc:
            raise SequenceRejected('Could not render the reviewed roster') from exc
        payload = self._payload(frozen['payload'], item['request_id'])
        payload['attachments'] = [
            {'id': index, 'filename': f'roster-{item["tag"][1:]}-{index + 1}.png'}
            for index in range(len(images))
        ]
        form = aiohttp.FormData()
        form.add_field('payload_json', json.dumps(payload))
        for index, png in enumerate(images):
            form.add_field(f'files[{index}]', png,
                           filename=payload['attachments'][index]['filename'], content_type='image/png')
        return await self._post(job['channel_id'], data=form)

    async def test_announcement(self, job, item):
        await self._destination(job['channel_id'])
        return await self._post(job['channel_id'], json=self._payload(item['payload'], item['request_id']))

    async def closing(self, job, item):
        await self._destination(job['channel_id'])
        return await self._post(job['channel_id'], json=self._payload(item['payload'], item['request_id']))

    @staticmethod
    def _payload(frozen, nonce):
        if frozen.get('allowed_mentions') not in ({'parse': []}, {'parse': [], 'roles': []}):
            raise SequenceRejected('Sequence messages must not allow mentions')
        return {**frozen, 'nonce': nonce, 'enforce_nonce': True}

    async def _post(self, channel, **kwargs):
        try:
            response = await discord(self.request, 'POST', f'/channels/{channel}/messages',
                                     roster_delivery=True, **kwargs)
        except web.HTTPTooManyRequests as exc:
            raise SequenceRateLimit(float(json.loads(exc.text)['retry_after'])) from exc
        except (web.HTTPForbidden, web.HTTPNotFound) as exc:
            raise SequenceRejected(exc.text) from exc
        # Connection loss, 5xx, invalid JSON and absent IDs remain uncertain.
        return str((response or {}).get('id') or '')
