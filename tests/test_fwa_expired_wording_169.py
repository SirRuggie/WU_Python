import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from extensions.commands.clan.dashboard import fwa_data


def test_expired_edits_keep_authorization_and_do_not_write(monkeypatch):
    authorize = AsyncMock(return_value=True)
    monkeypatch.setattr(fwa_data, '_require_fwa_representative', authorize)
    monkeypatch.setattr(fwa_data, 'consume', lambda *_args: None)
    save = AsyncMock()
    monkeypatch.setattr(fwa_data, 'save_fields', save)
    media = SimpleNamespace(upload_from_url=AsyncMock())
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), respond=AsyncMock())
    for action in (fwa_data.fwa_link_submit, fwa_data.fwa_images_submit, fwa_data.fwa_descriptions_submit):
        kwargs = {'ctx': ctx, 'action_id': 'th18|expired', 'mongo': object()}
        if action is fwa_data.fwa_images_submit:
            kwargs['media'] = media
        asyncio.run(action(**kwargs))
        ctx.respond.assert_awaited_once_with('This edit expired. Open it again before you save.', ephemeral=True)
        ctx.respond.reset_mock()
    assert authorize.await_count == 3
    save.assert_not_awaited()
    media.upload_from_url.assert_not_awaited()


def test_stale_image_edit_keeps_saved_images_and_reports_exact_recovery(monkeypatch):
    authorize = AsyncMock(return_value=True)
    monkeypatch.setattr(fwa_data, '_require_fwa_representative', authorize)
    monkeypatch.setattr(fwa_data, 'consume', lambda *_args: {'revision': 1})
    monkeypatch.setattr(fwa_data, 'validate_image_url', lambda _url: True)
    save = AsyncMock(return_value=False)
    monkeypatch.setattr(fwa_data, 'save_fields', save)
    before = dict(fwa_data.FWA_WAR_BASE)
    media = SimpleNamespace(upload_from_url=AsyncMock(return_value='https://example.test/staged.png'))
    fields = [[SimpleNamespace(custom_id='war_image', value='https://example.test/new.png')]]
    interaction = SimpleNamespace(components=fields, create_initial_response=AsyncMock(), edit_initial_response=AsyncMock())
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), interaction=interaction, respond=AsyncMock())
    asyncio.run(fwa_data.fwa_images_submit(ctx=ctx, action_id='th18|token', media=media,
                                           mongo=SimpleNamespace(fwa_data=object())))
    interaction.edit_initial_response.assert_awaited_once_with(
        content='These images changed in Discord or the dashboard. Open them again before you save.', components=[])
    save.assert_awaited_once()
    assert dict(fwa_data.FWA_WAR_BASE) == before
    authorize.assert_awaited_once_with(ctx)
