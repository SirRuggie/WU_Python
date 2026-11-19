"""245 base permissions/upload/redirect contracts; fixture Mongo and media only."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from cwl_web import town_halls as api, town_hall_bases as bases, manage_operations
from cwl_web import server_management as shared
from test_town_halls_bases import v2, LINK


def fixture():
    doc = v2()
    doc['_id'] = str(shared.GUILD_ID)
    return doc


@asynccontextmanager
async def mongo(_):
    yield object()


@pytest.mark.parametrize('weight,base', [(False, True), (True, False), (True, True)])
def test_mixed_sections_permissions_are_explicit_and_saved_link_drives_status(weight, base):
    result = api.document(fixture(), '19', can_weight=weight, can_bases=base)
    assert {field['group'] for field in result['fields']} == {'Town Hall', 'Base images', 'Merged', 'Non-merged'}
    assert result['base_status'] == {'Merged': True, 'Non-merged': False}
    assert all(field['readonly'] == (not weight if field['group'] == 'Town Hall' else not base) for field in result['fields'])
    assert result['base_originals']['bases.non_merged.link'] == {'exists': False}
    rows = api.document(fixture(), can_weight=weight, can_bases=base)['documents']
    if not weight:
        assert not any(row.get('list_role') == 'add' or row.get('list_group') == 'other' for row in rows)
        assert next(row for row in rows if row['id'] == 'settings').get('endpoint') is None
    assert next(row for row in rows if row['id'] == '19')['bases_meta'] == 'Merged'


def test_base_only_cannot_open_admin_settings_or_other_levels_even_before_migration():
    for item in ('settings', 'add', '11'):
        with pytest.raises((web.HTTPForbidden, web.HTTPNotFound)):
            api.document(fixture(), item, can_weight=False, can_bases=True)
    old = fixture()
    old['schema_version'] = 1
    for entry in old['levels'].values():
        entry.pop('bases', None)
    result = api.document(old, '19', can_weight=False, can_bases=True)
    assert result['readonly'] and all(field['readonly'] for field in result['fields'])


def upload_request(item='19', slot='war_image', revision='7', data=b'fixture-image'):
    async def chunks(_size):
        yield data
    media = SimpleNamespace(upload_bytes=AsyncMock(return_value='https://images.example/upload.jpg'))
    request = SimpleNamespace(match_info={'item': item, 'slot': slot}, query={'revision': revision},
                              content_length=len(data), content=SimpleNamespace(iter_chunked=chunks),
                              app={'server_management_media': media})
    return request, media


def test_upload_fills_draft_url_only_and_uses_shared_merged_folder():
    request, media = upload_request()
    doc = fixture()
    with patch.object(shared, 'require_manage', AsyncMock()), patch.object(shared, 'mongo', mongo), patch.object(api.registry, 'load', AsyncMock(return_value=doc)), patch.object(api.registry, 'save_base_fields', AsyncMock()) as save:
        response = asyncio.run(bases.upload(request))
    assert json.loads(response.text) == {'url': 'https://images.example/upload.jpg'}
    assert media.upload_bytes.call_args.kwargs['folder'] == 'fwa/bases/th19'
    save.assert_not_awaited()
    assert doc == fixture()


@pytest.mark.parametrize('kwargs,error', [({'slot': 'merged.war_image'}, web.HTTPBadRequest), ({'item': '11'}, web.HTTPNotFound), ({'revision': '6'}, web.HTTPConflict)])
def test_upload_rejects_invalid_slot_nonfwa_and_stale_revision_before_media(kwargs, error):
    request, media = upload_request(**kwargs)
    with patch.object(shared, 'require_manage', AsyncMock()), patch.object(shared, 'mongo', mongo), patch.object(api.registry, 'load', AsyncMock(return_value=fixture())):
        with pytest.raises(error):
            asyncio.run(bases.upload(request))
    media.upload_bytes.assert_not_awaited()


def test_upload_size_limit_and_route_order():
    from utils.url_safety import MAX_IMAGE_BYTES
    request, media = upload_request()
    request.content_length = MAX_IMAGE_BYTES + 1
    with patch.object(shared, 'require_manage', AsyncMock()), patch.object(shared, 'mongo', mongo), patch.object(api.registry, 'load', AsyncMock(return_value=fixture())):
        with pytest.raises(web.HTTPRequestEntityTooLarge):
            asyncio.run(bases.upload(request))
    media.upload_bytes.assert_not_awaited()
    paths = [route.path for route in api.routes]
    assert paths.index(api.API + '/{item}/upload/{slot}') < paths.index(api.API + '/{item}')


def test_old_base_write_and_upload_are_gone_without_legacy_reads():
    request = SimpleNamespace(match_info={'section': 'fwa_bases', 'item': 'th19', 'slot': 'war_base_images'})
    with patch.object(shared, 'require_manage', AsyncMock()), patch.object(shared, 'mongo', side_effect=AssertionError('no legacy read')):
        for handler in (manage_operations.save, manage_operations.upload_base):
            with pytest.raises(web.HTTPGone) as gone:
                asyncio.run(handler(request))
            assert gone.value.text == 'FWA bases moved to Town Halls. Refresh this page.'
        with pytest.raises(web.HTTPTemporaryRedirect) as redirect:
            asyncio.run(manage_operations.read(request))
    assert redirect.value.location == '/api/cwl/manage/town-halls/19'


def save_request(values, originals=None):
    body = {'revision': 7, 'values': values, 'originals': originals or {}}
    return SimpleNamespace(app={}, match_info={'item': '19'}, json=AsyncMock(return_value=body))


def test_base_manager_cannot_smuggle_admin_fields_into_save():
    request = save_request({'emoji': ''})
    with patch.object(shared, 'require_manage', AsyncMock(return_value={'user_id': '123'})), patch.object(shared, 'mongo', mongo), patch.object(api, 'required', AsyncMock(return_value=fixture())), patch.object(bases, 'permissions', AsyncMock(return_value=(False, True))), patch.object(api.registry, 'save', AsyncMock()) as save, patch.object(api.registry, 'save_base_fields', AsyncMock()) as base_save:
        with pytest.raises(web.HTTPForbidden):
            asyncio.run(api.save(request))
    save.assert_not_awaited()
    base_save.assert_not_awaited()


def test_mixed_http_save_uses_one_owner_cas_and_history_only_for_changed_fields():
    from cwl_web import change_history
    request = save_request({'min': 182000, 'bases.merged.instructions': 'New notes'}, {'bases.merged.instructions': {'exists': False}})
    committed = fixture()
    committed['levels']['19']['weight']['min'] = 182000
    committed['levels']['19']['bases']['merged']['instructions'] = 'New notes'
    committed.update(revision=8, nonbase_revision=8)
    with patch.object(shared, 'require_manage', AsyncMock(return_value={'user_id': '123'})), patch.object(shared, 'mongo', mongo), patch.object(api, 'required', AsyncMock(return_value=fixture())), patch.object(bases, 'permissions', AsyncMock(return_value=(True, True))), patch.object(api.registry, 'save', AsyncMock(return_value=committed)) as save, patch.object(api.registry, 'save_base_fields', AsyncMock()) as base_save, patch.object(change_history, 'record_committed', AsyncMock()) as history, patch.object(shared, 'queue_action', AsyncMock(return_value=web.json_response({}))):
        result = json.loads(asyncio.run(api.save(request)).text)
    save.assert_awaited_once()
    base_save.assert_not_awaited()
    assert save.call_args.kwargs == {'base_level': 19, 'base_values': {'merged.instructions': 'New notes'}, 'base_originals': {'merged.instructions': {'exists': False}}}
    assert set(history.call_args.args[3]) == set(history.call_args.args[4]) == {'min', 'bases.merged.instructions'}
    assert result['saved'] and result['revision'] == 8


def test_base_conflict_has_its_specific_message_without_history_or_queue():
    from cwl_web import change_history
    request = save_request({'bases.merged.instructions': 'Draft'}, {'bases.merged.instructions': {'exists': False}})
    with patch.object(shared, 'require_manage', AsyncMock(return_value={'user_id': '123'})), patch.object(shared, 'mongo', mongo), patch.object(api, 'required', AsyncMock(return_value=fixture())), patch.object(bases, 'permissions', AsyncMock(return_value=(False, True))), patch.object(api.registry, 'save_base_fields', AsyncMock(side_effect=api.registry.TownHallsConflict(api.registry.BASE_CONFLICT_MESSAGE))), patch.object(change_history, 'record_committed', AsyncMock()) as history, patch.object(shared, 'queue_action', AsyncMock()) as queue:
        with pytest.raises(web.HTTPConflict) as failure:
            asyncio.run(api.save(request))
    assert failure.value.text == api.registry.BASE_CONFLICT_MESSAGE
    history.assert_not_awaited()
    queue.assert_not_awaited()


@pytest.mark.parametrize('revision,stale', [(7, False), (6, True)])
def test_history_base_restore_binds_reviewed_revision_and_current_field_original(revision, stale):
    from cwl_web import change_history
    target = api.API + '/19'
    values = {'bases.merged.instructions': 'Saved historical notes'}
    row = {'kind': 'dashboard_history', 'target': target, 'status': 'saved',
           'before': values, 'after': values}
    db = SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value=row)))
    @asynccontextmanager
    async def history_mongo(_):
        yield db
    request = SimpleNamespace(app={}, query={'target': target},
        json=AsyncMock(return_value={'id': 'history-fixture', 'side': 'before', 'revision': revision}))
    with patch.object(change_history, 'require_manage', AsyncMock()) as permission, patch.object(change_history, 'mongo', history_mongo), patch.object(api.registry, 'load', AsyncMock(return_value=fixture())) as load, patch.object(api, 'save', AsyncMock(return_value=web.json_response({}))) as save:
        if stale:
            with pytest.raises(web.HTTPConflict):
                asyncio.run(change_history.restore(request))
            save.assert_not_awaited()
        else:
            asyncio.run(change_history.restore(request))
            proxy = save.call_args.args[0]
            assert proxy.history_action == 'restore'
            assert asyncio.run(proxy.json()) == {'revision': 7, 'values': values,
                'originals': {'bases.merged.instructions': {'exists': False}}}
        permission.assert_awaited_once_with(request, 'town_halls', write=True)
        assert load.call_args.args[1] == shared.GUILD_ID
