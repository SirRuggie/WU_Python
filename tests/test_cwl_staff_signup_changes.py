"""Staff signup editing: atomic batches, ownership, eligibility and privacy."""
import unittest
from unittest.mock import AsyncMock
import test_cwl_web_foundation as fixture


class StaffSignupChangesTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.WebFoundationTests.asyncSetUp
    asyncTearDown = fixture.WebFoundationTests.asyncTearDown
    auth = fixture.WebFoundationTests.auth
    call = fixture.WebFoundationTests.call
    season = fixture.WebFoundationTests.season

    async def seed(self):
        sid = await self.season()
        await self.call('POST', f'/seasons/{sid}/signups', self.member, json={
            'pool':'lazy','accounts':[{'tag':t,'prefer_crystal_1_or_lower':False} for t in ['#P2Y','#Q2Y']]})
        with self.app['store'].tx() as db:
            db.execute("INSERT OR REPLACE INTO clans(tag,name) VALUES ('#R2Y','Private hosting clan')")
            db.execute("INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,'#P2Y','#R2Y')", (sid,))
        data = await (await self.call('GET', f'/seasons/{sid}/signups?all=1', self.owner)).json()
        return sid, data['revision']

    async def test_atomic_change_stale_retry_and_member_privacy(self):
        sid, revision = await self.seed()
        member = await (await self.call('GET', f'/seasons/{sid}/signups?all=1', self.member)).json()
        self.assertNotIn('Private hosting clan', str(member))
        self.assertNotIn('assigned_clan_tag', str(member))
        staff = await (await self.call('GET', f'/seasons/{sid}/signups?all=1', self.owner)).json()
        self.assertEqual(staff['signups'][0]['assigned_clan_name'], 'Private hosting clan')
        body={'revision':revision,'user_id':'100','tags':['#P2Y','#Q2Y'],'action':'main'}
        path=f'/seasons/{sid}/staff-signup-changes'
        self.assertEqual((await self.call('POST',path,self.member,json=body)).status,403)
        self.assertEqual((await self.call('POST',path,{k:v for k,v in self.owner.items() if k!='X-CSRF-Token'},json=body)).status,403)
        response=await self.call('POST',path,self.owner,json=body)
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual((await response.json())['count'],2)
        self.assertEqual({r['pool'] for r in self.app['store'].rows('SELECT pool FROM signups')},{'main'})
        self.assertIsNone(self.app['store'].one('SELECT assigned_clan_tag FROM roster_entries')['assigned_clan_tag'])
        self.assertEqual((await self.call('POST',path,self.owner,json=body)).status,409)
        self.assertEqual(len(self.app['store'].rows("SELECT * FROM roster_audit WHERE action='staff_pool_change'")),2)

    async def test_fwa_or_changed_member_rejects_whole_batch(self):
        sid, revision=await self.seed()
        path=f'/seasons/{sid}/staff-signup-changes'
        body={'revision':revision,'user_id':'100','tags':['#Q2Y','#P2Y'],'action':'main'}
        self.providers.family_clans=AsyncMock(return_value={'clans':[{'tag':'#R2Y','type':'FWA'}]})
        self.assertEqual((await self.call('POST',path,self.owner,json=body)).status,409)
        self.assertEqual({r['pool'] for r in self.app['store'].rows('SELECT pool FROM signups')},{'lazy'})
        body.update(action='remove',user_id='200')
        self.assertEqual((await self.call('POST',path,self.owner,json=body)).status,409)
        self.assertEqual(len(self.app['store'].rows('SELECT * FROM signups')),2)
        body.update(user_id='100')
        result=await self.call('POST',path,self.owner,json=body)
        self.assertEqual(result.status,200,await result.text())
        self.assertEqual(self.app['store'].rows('SELECT * FROM signups'),[])
        self.assertEqual(self.app['store'].rows('SELECT * FROM roster_entries'),[])
        self.assertEqual(len(self.app['store'].rows("SELECT * FROM roster_audit WHERE action='staff_remove_signup'")),2)

    async def test_malformed_and_archived_batches(self):
        sid,revision=await self.seed()
        path=f'/seasons/{sid}/staff-signup-changes'
        body={'revision':revision,'user_id':'100','tags':['#P2Y'],'action':'remove'}
        for patch in [{'tags':[]},{'tags':['#P2Y','#P2Y']},{'action':'other'},{'user_id':None}]:
            self.assertEqual((await self.call('POST',path,self.owner,json={**body,**patch})).status,400)
        with self.app['store'].tx() as db: db.execute("UPDATE seasons SET status='archived' WHERE id=?",(sid,))
        self.assertEqual((await self.call('POST',path,self.owner,json=body)).status,423)

    async def test_revision_change_during_upstream_check_does_not_mutate(self):
        sid,revision=await self.seed()
        async def changing_player(value):
            with self.app['store'].tx() as db:
                db.execute('UPDATE roster_meta SET revision=revision+1 WHERE season_id=?',(sid,))
            return self.providers.players[value].copy()
        self.providers.player=changing_player
        result=await self.call('POST',f'/seasons/{sid}/staff-signup-changes',self.owner,json={
            'revision':revision,'user_id':'100','tags':['#P2Y','#Q2Y'],'action':'main'})
        self.assertEqual(result.status,409)
        self.assertEqual({r['pool'] for r in self.app['store'].rows('SELECT pool FROM signups')},{'lazy'})
        self.assertEqual(self.app['store'].one('SELECT assigned_clan_tag FROM roster_entries')['assigned_clan_tag'],'#R2Y')

    async def test_cross_member_bulk_switch_preserves_weights_and_published_snapshot(self):
        sid, _ = await self.seed()
        response = await self.call('POST', f'/seasons/{sid}/signups', self.other, json={
            'pool': 'lazy', 'accounts': [{'tag': '#G2Y', 'prefer_crystal_1_or_lower': False}]})
        self.assertEqual(response.status, 200)
        with self.app['store'].tx() as db:
            db.execute("INSERT INTO roster_entries(season_id,tag,manual_weight,assigned_clan_tag,kept) VALUES (?,'#G2Y',171000,'#R2Y',1)", (sid,))
            db.execute("UPDATE roster_entries SET manual_weight=175000,kept=1 WHERE season_id=? AND tag='#P2Y'", (sid,))
        preview = await (await self.call('GET', f'/seasons/{sid}/publication', self.owner)).json()
        publish = await self.call('POST', f'/seasons/{sid}/publication', self.owner, json={
            'revision': preview['draft_revision'], 'acknowledge_unassigned': True,
            'joining_instructions': 'Join your assigned clan.'})
        self.assertEqual(publish.status, 201, await publish.text())
        before = self.app['store'].rows('SELECT * FROM publication_accounts ORDER BY tag')
        revision = (await (await self.call('GET', f'/seasons/{sid}/roster', self.owner)).json())['revision']
        path = f'/seasons/{sid}/staff-signup-changes'
        changed = await self.call('POST', path, self.owner, json={
            'revision': revision, 'tags': ['#P2Y', '#G2Y'], 'action': 'main'})
        self.assertEqual(changed.status, 200, await changed.text())
        self.assertEqual((await changed.json())['count'], 2)
        rows = self.app['store'].rows(
            "SELECT s.tag,s.pool,r.manual_weight,r.assigned_clan_tag,r.kept "
            "FROM signups s JOIN roster_entries r ON r.season_id=s.season_id AND r.tag=s.tag "
            "WHERE s.tag IN ('#P2Y','#G2Y') ORDER BY s.tag")
        self.assertEqual([(r['tag'], r['pool'], r['manual_weight'], r['assigned_clan_tag'], r['kept']) for r in rows],
                         [('#G2Y', 'main', 171000, None, 0), ('#P2Y', 'main', 175000, None, 0)])
        self.assertEqual(self.app['store'].rows('SELECT * FROM publication_accounts ORDER BY tag'), before)
        self.assertEqual((await self.call('POST', path, self.owner, json={
            'revision': revision, 'tags': ['#P2Y', '#G2Y'], 'action': 'remove'})).status, 409)

    async def test_cross_member_bulk_remove_is_atomic_and_strictly_bounded(self):
        sid, _ = await self.seed()
        response = await self.call('POST', f'/seasons/{sid}/signups', self.other, json={
            'pool': 'lazy', 'accounts': [{'tag': '#G2Y', 'prefer_crystal_1_or_lower': False}]})
        self.assertEqual(response.status, 200)
        revision = (await (await self.call('GET', f'/seasons/{sid}/roster', self.owner)).json())['revision']
        path = f'/seasons/{sid}/staff-signup-changes'
        body = {'revision': revision, 'tags': ['#P2Y', '#G2Y'], 'action': 'remove'}
        for patch, status in [
            ({'tags': ['#P2Y', '#J2Y']}, 409),
            ({'tags': ['#P2Y', '#P2Y']}, 400),
            ({'tags': ['#P2Y'] * 51}, 400),
            ({'revision': None}, 409),
            ({'user_id': '100'}, 409),
        ]:
            result = await self.call('POST', path, self.owner, json={**body, **patch})
            self.assertEqual(result.status, status, await result.text())
            self.assertEqual(len(self.app['store'].rows('SELECT * FROM signups')), 3)
        result = await self.call('POST', path, self.owner, json=body)
        self.assertEqual(result.status, 200, await result.text())
        self.assertEqual({row['tag'] for row in self.app['store'].rows('SELECT tag FROM signups')}, {'#Q2Y'})
        self.assertIsNone(self.app['store'].one("SELECT * FROM roster_entries WHERE tag='#P2Y'"))

    async def test_cross_member_main_fwa_failure_and_concurrent_revision_rollback(self):
        sid, _ = await self.seed()
        response = await self.call('POST', f'/seasons/{sid}/signups', self.other, json={
            'pool': 'lazy', 'accounts': [{'tag': '#G2Y', 'prefer_crystal_1_or_lower': False}]})
        self.assertEqual(response.status, 200)
        revision = (await (await self.call('GET', f'/seasons/{sid}/roster', self.owner)).json())['revision']
        path = f'/seasons/{sid}/staff-signup-changes'
        body = {'revision': revision, 'tags': ['#P2Y', '#G2Y'], 'action': 'main'}
        self.providers.family_clans = AsyncMock(return_value={'clans': [{'tag': '#R2Y', 'type': 'FWA'}]})
        self.assertEqual((await self.call('POST', path, self.owner, json=body)).status, 409)
        self.assertEqual({r['pool'] for r in self.app['store'].rows('SELECT pool FROM signups')}, {'lazy'})
        self.providers.family_clans = AsyncMock(return_value={'clans': [{'tag': '#R2Y'}]})
        async def changing_player(value):
            with self.app['store'].tx() as db:
                db.execute('UPDATE roster_meta SET revision=revision+1 WHERE season_id=?', (sid,))
            return self.providers.players[value].copy()
        self.providers.player = changing_player
        self.assertEqual((await self.call('POST', path, self.owner, json=body)).status, 409)
        self.assertEqual({r['pool'] for r in self.app['store'].rows('SELECT pool FROM signups')}, {'lazy'})

    async def test_signup_scope_reads_roster_and_changes_signups_but_cannot_place(self):
        sid, revision = await self.seed()
        response = await self.call('POST', '/access', self.owner, json={
            'user_id': '200', 'permissions': ['cwl_signups']})
        self.assertEqual(response.status, 200, await response.text())
        read = await self.call('GET', f'/seasons/{sid}/roster', self.other)
        self.assertEqual(read.status, 200, await read.text())
        changed = await self.call('POST', f'/seasons/{sid}/staff-signup-changes', self.other, json={
            'revision': revision, 'tags': ['#P2Y'], 'action': 'remove'})
        self.assertEqual(changed.status, 200, await changed.text())
        roster_revision = (await changed.json())['revision']
        denied = await self.call('PATCH', f'/seasons/{sid}/roster/assignments', self.other, json={
            'revision': roster_revision, 'tags': ['#Q2Y'], 'assigned_clan_tag': None})
        self.assertEqual(denied.status, 403)

    async def test_roster_only_and_unprivileged_member_cannot_change_signups(self):
        sid, revision = await self.seed()
        path = f'/seasons/{sid}/staff-signup-changes'
        body = {'revision': revision, 'tags': ['#P2Y'], 'action': 'remove'}
        for actor in (self.member, self.other):
            response = await self.call('POST', path, actor, json=body)
            self.assertEqual(response.status, 403, await response.text())
        grant = await self.call('POST', '/access', self.owner, json={
            'user_id': '200', 'permissions': ['cwl_roster']})
        self.assertEqual(grant.status, 200, await grant.text())
        denied = await self.call('POST', path, self.other, json=body)
        self.assertEqual(denied.status, 403, await denied.text())
        self.assertEqual({row['tag'] for row in self.app['store'].rows('SELECT tag FROM signups')},
                         {'#P2Y', '#Q2Y'})
        self.assertEqual(self.app['store'].rows(
            "SELECT * FROM roster_audit WHERE action='staff_remove_signup'"), [])
