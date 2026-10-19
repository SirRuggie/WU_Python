import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from aiohttp import web
from test_recruit_question_content import ConfigCollection
from pymongo.errors import DuplicateKeyError
from cwl_web.manage_operations import cas, public_url, revision, checked, load_document

class ManageOperationsTests(unittest.IsolatedAsyncioTestCase):
    def test_revision_tracks_discord_changes_without_revision_field(self):
        self.assertNotEqual(revision({'enabled':True}),revision({'enabled':False}))
        self.assertEqual(revision({'a':1,'b':2}),revision({'b':2,'a':1}))

    def test_urls_reject_local_and_credential_urls(self):
        for value in ['http://example.com/a.png','https://localhost/a','https://127.0.0.1/a','https://169.254.169.254/a','https://user:pass@example.com/a','javascript:alert(1)']:
            self.assertFalse(public_url(value),value)
        self.assertTrue(public_url('https://cdn.discordapp.com/example.png'))

    def test_unknown_fields_rejected(self):
        with self.assertRaises(web.HTTPBadRequest):checked({'admin':True},{'name'})
        with self.assertRaises(web.HTTPBadRequest):checked(None,{'name'})

    async def test_cas_matches_existing_native_fields(self):
        collection=SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=1,upserted_id=None)))
        await cas(collection,'config',{'enabled':False},{'enabled':True})
        collection.update_one.assert_awaited_once_with({'_id':'config','enabled':False},{'$set':{'enabled':True}},upsert=False)

    async def test_cas_conflict_and_create_race_are_conflicts(self):
        collection=SimpleNamespace(update_one=AsyncMock(return_value=SimpleNamespace(matched_count=0,upserted_id=None)))
        with self.assertRaises(web.HTTPConflict):await cas(collection,'config',{'enabled':False},{'enabled':True})
        collection.update_one.side_effect=DuplicateKeyError('duplicate')
        with self.assertRaises(web.HTTPConflict):await cas(collection,'config',{}, {'enabled':True})

    async def test_base_list_and_leaf_are_bounded(self):
        db=SimpleNamespace(bot_config=ConfigCollection(),fwa_data=SimpleNamespace(find_one=AsyncMock(return_value={'_id':'fwa_config','fwa_base_links':{'th18':'https://link.clashofclans.com/a'}})))
        parent=await load_document(db,'fwa_bases')
        self.assertEqual(parent['fields'],[])
        self.assertEqual(len(parent['documents']),13)
        leaf=await load_document(db,'fwa_bases','th18')
        self.assertEqual(len(leaf['fields']),5)
        self.assertEqual(leaf['fields'][0]['value'],'https://link.clashofclans.com/a')
        with self.assertRaises(web.HTTPBadRequest):await load_document(db,'fwa_bases','TH18.$bad')

    async def test_weight_does_not_mutate_defaults_during_read(self):
        collection=SimpleNamespace(find_one=AsyncMock(return_value=None))
        db=SimpleNamespace(bot_config=ConfigCollection(),fwa_data=SimpleNamespace(database=SimpleNamespace(get_collection=lambda _:collection)))
        doc=await load_document(db,'fwa_weight','new')
        self.assertFalse(doc['fields'][0]['readonly'])
        self.assertEqual(doc['fields'][0]['key'],'th')
        parent=await load_document(db,'fwa_weight')
        self.assertEqual(parent['documents'][-1]['id'],'new')

    async def test_channel_overwrite_denial_blocks_save(self):
        from unittest.mock import patch
        from cwl_web.manage_operations import check_channel_permissions
        from cwl_web.server_management import GUILD_ID
        permission=(1<<10)|(1<<11)|(1<<14)
        async def discord(request,method,path):
            if path=='/users/@me':return {'id':'123'}
            if '/members/' in path:return {'roles':['222']}
            return [{'id':str(GUILD_ID),'permissions':str(permission)},{'id':'222','permissions':'0'}]
        with patch('cwl_web.manage_operations.shared.discord',discord):
            await check_channel_permissions({}, {'permission_overwrites':[]})
            with self.assertRaises(web.HTTPBadRequest):
                await check_channel_permissions({}, {'permission_overwrites':[{'id':'222','type':0,'deny':str(1<<11),'allow':'0'}]})

    async def test_source_snapshot_matches_revision_and_ignores_other_town_halls(self):
        row={'_id':'fwa_config','base_information':{'th18':'old','th17':'other'}}
        db=SimpleNamespace(bot_config=ConfigCollection(),fwa_data=SimpleNamespace(find_one=AsyncMock(return_value=row)))
        before={}
        loaded=await load_document(db,'fwa_bases','th18',source_snapshot=before)
        row['base_information']['th17']='updated elsewhere'
        self.assertEqual(loaded['revision'],(await load_document(db,'fwa_bases','th18'))['revision'])
        row['base_information']['th18']='changed natively'
        self.assertEqual(before['base_information']['th18'],'old')
        self.assertNotEqual(loaded['revision'],(await load_document(db,'fwa_bases','th18'))['revision'])

    async def test_native_change_between_web_read_and_save_is_not_overwritten(self):
        from contextlib import asynccontextmanager
        from unittest.mock import patch
        from cwl_web import manage_operations as operations
        row={'_id':'fwa_config','base_information':{'th18':'old'}}
        collection=SimpleNamespace(find_one=AsyncMock(return_value=row))
        db=SimpleNamespace(bot_config=ConfigCollection(),fwa_data=collection)
        initial=await load_document(db,'fwa_bases','th18')
        async def update(query, change, **kwargs):
            # Native modal saves just after the web handler read its snapshot.
            row['base_information']['th18']='native edit'
            self.assertEqual(query['base_information.th18'],'old')
            return SimpleNamespace(matched_count=0,upserted_id=None)
        collection.update_one=AsyncMock(side_effect=update)
        @asynccontextmanager
        async def mongo(_):yield db
        req=SimpleNamespace(match_info={'section':'fwa_bases','item':'th18'})
        with patch.object(operations.shared,'mongo',mongo), patch.object(operations.shared,'require_manage',AsyncMock(return_value={'user_id':'1'})), patch('cwl_web.app._json',AsyncMock(return_value={'revision':initial['revision'],'values':{'base_information':'web edit'}})):
            with self.assertRaises(web.HTTPConflict):await operations.save(req)
        self.assertEqual(row['base_information']['th18'],'native edit')
        # Exactly one database read during save, rather than a fresh unsafe baseline.
        self.assertEqual(collection.find_one.await_count,2)

    async def test_sync_save_uses_original_read_after_validation(self):
        from contextlib import asynccontextmanager
        from unittest.mock import patch
        from cwl_web import manage_operations as operations
        row={'_id':'config','enabled':False}
        collection=SimpleNamespace(find_one=AsyncMock(return_value=row))
        db=SimpleNamespace(bot_config=ConfigCollection(),fwa_sync_config=collection)
        initial=await load_document(db,'fwa_sync')
        async def update(query, change, **kwargs):
            row['enabled']=True
            self.assertIs(query['enabled'],False)
            return SimpleNamespace(matched_count=0,upserted_id=None)
        collection.update_one=AsyncMock(side_effect=update)
        @asynccontextmanager
        async def mongo(_):yield db
        req=SimpleNamespace(match_info={'section':'fwa_sync'})
        with patch.object(operations.shared,'mongo',mongo), patch.object(operations.shared,'require_manage',AsyncMock(return_value={'user_id':'1'})), patch('cwl_web.app._json',AsyncMock(return_value={'revision':initial['revision'],'values':{'enabled':True}})):
            with self.assertRaises(web.HTTPConflict):await operations.save(req)
        self.assertEqual(collection.find_one.await_count,2)

    async def test_blacklist_delete_preserves_readded_entry(self):
        from contextlib import asynccontextmanager
        from unittest.mock import patch
        from cwl_web import manage_operations as operations
        row={'_id':'P2Y','name':'Original','added_at':1}
        db=SimpleNamespace(bot_config=ConfigCollection(),fwa_blacklist=SimpleNamespace(find_one=AsyncMock()))
        @asynccontextmanager
        async def mongo(_):yield db
        async def remove(db,tag,*,expected_added_at):
            self.assertEqual(expected_added_at,1)
            return False # Native editor removed and re-added it with added_at=2.
        req=SimpleNamespace(match_info={'section':'fwa_blacklist','item':'P2Y','action':'remove'})
        with patch.object(operations.fwa_blacklist,'list_blacklisted',AsyncMock(return_value=[row])), patch.object(operations.fwa_blacklist,'remove_blacklisted',remove), patch.object(operations.shared,'mongo',mongo), patch.object(operations.shared,'require_manage',AsyncMock()), patch('cwl_web.app._json',AsyncMock(return_value={'revision':revision(row)})):
            with self.assertRaises(web.HTTPConflict):await operations.action(req)
        db.fwa_blacklist.find_one.assert_not_awaited()

    async def test_weight_save_does_not_reload_newer_native_revision(self):
        from contextlib import asynccontextmanager
        from unittest.mock import patch
        from cwl_web import manage_operations as operations
        config={'revision':4,'minimum_th':9,'ranges':{}}
        @asynccontextmanager
        async def mongo(_):yield SimpleNamespace(bot_config=ConfigCollection())
        load=AsyncMock(return_value=config)
        async def persist(db,guild,row,user):
            self.assertEqual(row['revision'],4)
            self.assertEqual(row['minimum_th'],10)
            raise ValueError('Concurrent update')
        req=SimpleNamespace(match_info={'section':'fwa_weight','item':'settings'})
        with patch.object(operations.war_weight,'load',load), patch.object(operations.war_weight,'save',persist), patch.object(operations.shared,'mongo',mongo), patch.object(operations.shared,'require_manage',AsyncMock(return_value={'user_id':'1'})), patch('cwl_web.app._json',AsyncMock(return_value={'revision':revision(config),'values':{'minimum_th':10}})):
            with self.assertRaises(web.HTTPBadRequest):await operations.save(req)
        self.assertEqual(load.await_count,1)
        self.assertEqual(config['minimum_th'],9)
