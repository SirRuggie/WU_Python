"""Old upload controls remain safe, read-only entry points after245."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from extensions.commands.clan.dashboard import image_uploads as uploads
from test_town_halls_discord_bases_245 import context, bases_doc, GUILD_ID
from utils import town_halls


def test_clan_upload_entry_points_keep_existing_read_only_destination(monkeypatch):
    from extensions.commands.clan.dashboard import read_only_clan
    show=AsyncMock();monkeypatch.setattr(read_only_clan,'show_clan',show)
    ctx=context();mongo=object()
    asyncio.run(uploads._open(ctx,'logo:#P2Y',mongo,'clan'))
    show.assert_awaited_once_with(ctx,mongo,'logo:#P2Y')
    asyncio.run(uploads.clan_image_upload.__wrapped__._func(ctx=ctx,action_id='banner:#P2Y',mongo=mongo))
    assert show.await_args.args==(ctx,mongo,'banner:#P2Y')


@pytest.mark.parametrize('target',['war:th19','active:th19_new','war:th0','malformed'])
def test_old_fwa_upload_buttons_never_open_modal_or_write(monkeypatch,target):
    monkeypatch.setattr(town_halls,'_snapshot',bases_doc());monkeypatch.setattr(town_halls,'_snapshot_guild',str(GUILD_ID))
    ctx=context();ctx.respond_with_modal=AsyncMock();write=AsyncMock();mongo=NS(fwa_data=NS(update_one=write))
    asyncio.run(uploads.fwa_image_upload.__wrapped__._func(ctx=ctx,action_id=target,mongo=mongo))
    ctx.respond_with_modal.assert_not_awaited();write.assert_not_awaited()
    assert ctx.respond.await_args.kwargs['ephemeral'] is True


@pytest.mark.parametrize('allowed',[True,False])
def test_old_submissions_consume_attachment_cache_but_cannot_save(monkeypatch,allowed):
    calls=[]
    monkeypatch.setattr(uploads,'pop_file_upload',lambda *args:calls.append(args) or {'url':'https://cdn.discordapp.com/attachments/fake','size':5})
    ctx=context(allowed);media=NS(upload_bytes=AsyncMock());mongo=NS(fwa_data=NS(update_one=AsyncMock()))
    asyncio.run(uploads.dashboard_image_submit.__wrapped__._func(ctx=ctx,action_id='old-token',mongo=mongo,media=media))
    assert calls==[(999,'dashboard_image_submit:old','image')]
    media.upload_bytes.assert_not_awaited();mongo.fwa_data.update_one.assert_not_awaited()
    assert ctx.respond.await_count==1
    if allowed:assert ctx.respond.await_args.kwargs['user_mentions'] is False
    else:assert 'role required' in ctx.respond.await_args.args[0]
