import asyncio
from types import SimpleNamespace
from utils import manage_field_drafts as drafts


class Fields:
    def __init__(self, **fields):
        self.fields = fields

    async def update_one(self, query, update):
        for key, expected in query.items():
            if key == '_id':
                continue
            if expected == {'$exists': False}:
                if key in self.fields:
                    return SimpleNamespace(matched_count=0)
            elif self.fields.get(key) != expected:
                return SimpleNamespace(matched_count=0)
        self.fields.update(update['$set'])
        return SimpleNamespace(matched_count=1)


def test_actor_bound_expiring_snapshots(monkeypatch):
    token = drafts.remember(1, 'notes:th18', {'notes': {'th18': 'old'}}, ['notes.th18'])
    assert drafts.consume(token, 2, 'notes:th18') is None
    assert drafts.consume(token, 1, 'link:th18') is None
    assert drafts.consume(token, 1, 'notes:th18') == {'notes.th18': 'old'}
    assert drafts.consume(token, 1, 'notes:th18') is None
    token = drafts.remember(1, 'x', {}, ['x'])
    now = drafts.time.monotonic()
    monkeypatch.setattr(drafts.time, 'monotonic', lambda: now + drafts.TTL + 1)
    assert drafts.consume(token, 1, 'x') is None


def test_web_edit_conflicts_only_on_changed_native_fields():
    baseline = {'notes.th18': 'old', 'info.th18': 'same'}
    fields = Fields(**{'notes.th18': 'dashboard edit', 'info.th18': 'same'})
    assert not asyncio.run(drafts.save_fields(fields, 'config', baseline, {'notes.th18': 'native edit'}))
    assert fields.fields['notes.th18'] == 'dashboard edit'
    assert asyncio.run(drafts.save_fields(fields, 'config', baseline, {'notes.th18': 'old', 'info.th18': 'native info'}))
    assert fields.fields['notes.th18'] == 'dashboard edit'
    assert fields.fields['info.th18'] == 'native info'


def test_missing_fields_and_multi_field_atomicity():
    baseline = {'war.th18': {'$exists': False}, 'active.th18': 'old'}
    fields = Fields(**{'active.th18': 'web'})
    assert not asyncio.run(drafts.save_fields(fields, 'config', baseline, {'war.th18': 'new', 'active.th18': 'new'}))
    assert 'war.th18' not in fields.fields
    assert asyncio.run(drafts.save_fields(fields, 'config', baseline, {'war.th18': 'new'}))


def test_native_link_modal_rejects_dashboard_change_and_saves_fresh_edit(monkeypatch):
    from extensions.commands.clan.dashboard import fwa_data
    from unittest.mock import AsyncMock
    monkeypatch.setattr(fwa_data, '_require_fwa_representative', AsyncMock(return_value=True))
    old = 'https://link.clashofclans.com/?id=old'
    web = 'https://link.clashofclans.com/?id=web'
    new = 'https://link.clashofclans.com/?id=native'
    fields = Fields(**{'fwa_base_links.th18': web})
    mongo = SimpleNamespace(fwa_data=fields)
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), respond=AsyncMock(), interaction=SimpleNamespace(
        components=[[SimpleNamespace(custom_id='base_link', value=new)]],
        create_initial_response=AsyncMock(), edit_initial_response=AsyncMock()))
    token = drafts.remember(1, 'fwa_link_submit:th18', {'fwa_base_links': {'th18': old}}, ['fwa_base_links.th18'])
    asyncio.run(fwa_data.fwa_link_submit(ctx=ctx, action_id='th18|' + token, mongo=mongo))
    assert fields.fields['fwa_base_links.th18'] == web
    assert 'changed' in ctx.interaction.edit_initial_response.call_args.kwargs['content']
    token = drafts.remember(1, 'fwa_link_submit:th18', {'fwa_base_links': {'th18': web}}, ['fwa_base_links.th18'])
    asyncio.run(fwa_data.fwa_link_submit(ctx=ctx, action_id='th18|' + token, mongo=mongo))
    assert fields.fields['fwa_base_links.th18'] == new
