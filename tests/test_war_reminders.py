import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
import re
from utils import war_reminders as r
from utils import war_reminder_store as storage
from extensions.tasks.war_reminders import scan_clan


def config(**kw):
    return {**r.settings(), 'enabled': True, 'channel_id': '123456789012345678', **kw}


def war():
    now = datetime.now(timezone.utc)
    return {**r.sample({'name': 'Warriors', 'tag': '#P0LY'}, '60'), 'start': now-timedelta(hours=23), 'end': now+timedelta(hours=1)}


def test_custom_offsets_validate_and_normalize():
    assert r.validate(config(minutes=[75, 1, 75, 1440]))['minutes'] == [1440, 75, 1]
    assert r.validate(config(minutes=[], war_started=True))['minutes'] == []


@pytest.mark.parametrize('patch', [{'minutes': [True]}, {'minutes': [0]}, {'minutes': [1441]}, {'minutes': [1.5]}, {'minutes': '60'}, {'enabled': 'true'}, {'channel_id': ''}, {'audience': 'everyone'}, {'minutes': [], 'war_started': False}])
def test_invalid_settings_rejected(patch):
    with pytest.raises(ValueError): r.validate(config(**patch))


def test_thresholds_restart_and_ended_wars():
    w = war(); now = w['end']-timedelta(hours=1)
    assert r.due(w, config(), now) == ['60']
    assert r.due(w, config(), now+timedelta(minutes=4)) == ['60']
    assert r.due(w, config(), now+timedelta(minutes=5)) == []
    assert r.due(w, config(), w['end']) == []
    assert r.due(w, config(enabled=False), now) == []
    assert r.due(w, config(), w['start']) == ['start']


def test_only_pending_players_pinged_in_content_and_no_cv2():
    w = war(); w['members'][2]['used'] = 2
    owners = {m['tag']: str(123456789012345670+i) for i,m in enumerate(w['members'])}
    messages = r.messages(w, config(), '60', owners)
    assert len(messages) == 1
    msg = messages[0]
    assert '<@123456789012345670>' in msg['content']
    assert '<@123456789012345671>' in msg['content']
    assert '123456789012345672' not in str(msg)
    assert msg['allowed_mentions']['parse'] == []
    assert 'flags' not in msg
    assert [button['label'] for button in msg['components'][0]['components']] == ['My tasks', 'Wars']
    assert '1/2' in msg['content']
    assert len(r.messages(w, config(audience='zero'), '60', owners)[0]['allowed_mentions']['users']) == 1


def test_cwl_one_attack_and_all_complete_skip():
    w = war(); w['limit'] = 1
    assert len(r.pending(w, 'remaining')) == 2
    for m in w['members']: m['used'] = 1
    assert r.messages(w, config(), '60') == []


def test_unlinked_players_and_sample_do_not_ping_real_members():
    w = war(); uid = '123456789012345678'
    assert 'Shield Bearer' in r.messages(w, config(), '60')[0]['content']
    msg = r.messages(w, config(), '60', {'#SAMPLE1': uid}, test=True)[0]
    assert msg['allowed_mentions']['users'] == []
    msg = r.messages(w, config(), '60', test=True, tester=uid)[0]
    assert msg['allowed_mentions']['users'] == [uid] and f'<@{uid}>' in msg['content']


def test_large_roster_fits_discord_limits_and_deduplicates_mentions():
    w = war(); w['members'] = [{**w['members'][0], 'tag': f'#{i}', 'name': '*'*100, 'position': i} for i in range(50)]
    owners = {m['tag']: '123456789012345678' for m in w['members']}
    payloads = r.messages(w, config(), '60', owners)
    assert len(payloads) > 1
    assert sum(m['content'].count('<@123456789012345678>') for m in payloads) == 1
    assert sum(m['allowed_mentions']['users'].count('123456789012345678') for m in payloads) == 1
    for msg in payloads:
        assert len(msg['content']) <= 2000
        assert r.discord_length(msg['content']) <= 2000
        assert 'embeds' not in msg


def test_scheduler_claim_is_durable_and_duplicate_scan_does_not_send(monkeypatch):
    from extensions.tasks import war_reminders as task
    w = war(); cfg = {**config(), '_id': '#P0LY', 'version': 1}
    collections = {}
    class Rows:
        def __init__(self): self.rows = {}
        async def find_one(self, q): return self.rows.get(q['_id'])
        async def insert_one(self, row): self.rows[row['_id']] = row.copy()
        async def update_one(self, q, update, **kw): self.rows.setdefault(q['_id'], {}).update(update['$set'])
    def coll(db, name='war_reminder_settings'): return collections.setdefault(name, Rows())
    coll(None).rows['#P0LY'] = cfg
    monkeypatch.setattr(storage, 'collection', coll)
    monkeypatch.setattr(r, 'snapshot', lambda *_: w)
    db = NS(clans=NS(find_one=AsyncMock(return_value={'tag': '#P0LY'})))
    client = NS(get_current_war=AsyncMock())
    bot = NS(rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=r.GUILD_ID, type=0)), create_message=AsyncMock(return_value=NS(id=123))))
    providers = NS(linked_owners=AsyncMock(return_value={'#SAMPLE1':'123456789012345678'}))
    async def run():
        await scan_clan(db, client, bot, providers, cfg)
        await scan_clan(db, client, bot, providers, cfg)
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1
    assert bot.rest.create_message.await_args.kwargs['user_mentions'] == [123456789012345678]
    receipt = next(iter(coll(None, 'war_reminder_deliveries').rows.values()))
    assert receipt['status'] == 'sent'


def test_snapshot_checks_clan_and_cwl_attack_allowance():
    now = datetime.now(timezone.utc)
    member = NS(tag='#P', name='Player', map_position=1, town_hall=17, attacks=[])
    w = NS(state='inWar', clan=NS(tag='#OTHER', name='Other', members=[]), opponent=NS(tag='#P0LY', name='Warriors', members=[member]), attacks_per_member=1, team_size=1, start_time=NS(time=now.replace(tzinfo=None)), end_time=NS(time=now+timedelta(hours=24)))
    snap = r.snapshot(w, '#P0LY')
    assert snap['name'] == 'Warriors' and snap['limit'] == 1
    assert snap['start'].tzinfo == timezone.utc
    with pytest.raises(ValueError): r.snapshot(w, '#WRONG')


def test_five_accounts_group_under_single_owner_and_heading_is_notification_text():
    w=war(); w['name']='Edrag Rush'
    w['members']=[dict(tag=f'#{i}',name=f'Account {i}',position=i,th=18,used=i%2) for i in range(5)]
    uid='505227988229554179'
    payloads=r.messages(w,config(),'720',{m['tag']:uid for m in w['members']})
    assert len(payloads)==1
    text=payloads[0]['content']
    assert text.startswith('🔔 **Edrag Rush · 12 hours left**\n-# vs ')
    assert f'<@{uid}> · 5 accounts' in text
    assert text.count(f'<@{uid}>')==1
    for i in range(5):assert text.count(f'Account {i}')==1
    assert text.index(f'<@{uid}>') < text.index('Account 0')
    assert '<:TH_18:' in text
    assert 'embeds' not in payloads[0]


def test_distinct_owners_have_separate_account_groups():
    w=war(); a='123456789012345670'; b='123456789012345671'
    text=r.messages(w,config(),'75',{'#SAMPLE1':a,'#SAMPLE2':b,'#SAMPLE3':a})[0]['content']
    assert '1 hour 15 minutes left' in text
    # Single-account owners come first, on one line; then grouped owners.
    assert f'<@{b}> <:TH_17:' in text and text.index(f'<@{b}>') < text.index(f'<@{a}> · 2 accounts')
    assert text.index(f'<@{a}>') < text.index('Shield Bearer') < text.index('Iron Guardian')


def test_large_unicode_roster_preserves_every_account_within_discord_limit():
    w=war(); w['members']=[dict(tag=f'#{i}',name=f'Player{i} '+('⚔️'*30),position=i,th=18,used=0) for i in range(50)]
    payloads=r.messages(w,config(),'60',{m['tag']:str(123456789012345600+i) for i,m in enumerate(w['members'])})
    assert all(r.discord_length(p['content'])<=2000 for p in payloads)
    assert sum(len(p['allowed_mentions']['users']) for p in payloads)==50
    for m in w['members']:assert sum(p['content'].count(r.clean(m['name'])) for p in payloads)==1


def test_unlinked_row_includes_name_tag_emoji_and_counts_without_ping():
    w=war();uid='505227988229554179'
    payload=r.messages(w,config(),'720',{'#SAMPLE1':uid,'#SAMPLE2':uid})[0]
    text=payload['content']
    assert '**Shield Bearer** ·\u00a00/2' in text and '#SAMPLE1' not in text
    unlinked=text.split('-# Not linked · no ping')[1]
    assert '<:TH_16:' in unlinked and '> <:TH_16:1395729067990319164> **Iron Guardian** `#SAMPLE3` ·\u00a00/2' in unlinked
    assert '<@' not in unlinked
    assert payload['allowed_mentions']['users']==[uid]


def test_sample_preview_shows_linked_and_unlinked_groups():
    payload=r.messages(war(),config(),'60',test=True,tester='505227988229554179')[0]
    assert '<@505227988229554179>' in payload['content']
    unlinked=payload['content'].split('-# Not linked · no ping')[1]
    assert '`#SAMPLE3`' in unlinked and '<@' not in unlinked
    muted=r.messages(war(),config(),'60',test=True)[0]
    assert '**Sample accounts**\n> ' in muted['content'] and '-# Not linked · no ping' in muted['content']
    assert '-# Test reminder · Sample players · Simulated attacks' in muted['content']
    assert muted['allowed_mentions']['users']==[]


def test_hostile_names_cannot_create_mentions_or_break_row_layout():
    w=war(); uid='505227988229554179'
    w['members'][0]['name']='@everyone\n<@999999999999999999>\r**fake**\u202e'
    payload=r.messages(w,config(),'60',{'#SAMPLE1':uid})[0]
    assert payload['allowed_mentions']['users']==[uid]
    assert payload['allowed_mentions']['parse']==[]
    assert '\n<@999' not in payload['content'] and '\u202e' not in payload['content']
    assert '\\@everyone' in payload['content']


def test_long_custom_sample_label_is_budgeted_before_chunking():
    w=war();w['name']='🛡'*100;w['opponent']='🛡'*100
    w['members']=[dict(tag=f'#{i}',name='🛡'*100,position=i,th=18,used=0) for i in range(6)]
    messages=r.messages(w,config(),'60',test=True,tester='505227988229554179',sample_label='Your accounts in this clan + unlinked example')
    assert all(r.discord_length(p['content'])<=2000 for p in messages)
    assert sum(p['content'].count('<@505227988229554179>') for p in messages)==1


def test_default_times_are_not_shared_mutable_state():
    first=r.settings();first['minutes'].append(5)
    assert 5 not in r.settings()['minutes']


def test_non_ascii_channel_ids_are_rejected():
    with pytest.raises(ValueError):r.validate(config(channel_id='１'*18))


def test_single_account_owner_uses_one_line_with_used_over_available():
    w=war(); uid='505227988229554179'
    text=r.messages(w,config(),'60',{'#SAMPLE2':uid})[0]['content']
    assert f'<@{uid}> <:TH_17:1395729126014324837> **Night Archer** ·\u00a01/2\n' in text
    assert f'<@{uid}>\n' not in text


def test_header_has_live_end_time_totals_legend_and_singular_count():
    w=war(); w['members']=w['members'][:1]
    text=r.messages(w,config(),'60',{'#SAMPLE1':'505227988229554179'})[0]['content']
    end=int(w['end'].timestamp())
    first,second=text.split('\n')[:2]
    assert first=='🔔 **Warriors · 1 hour left**'
    assert second==f'-# vs Rival Clan · Ends <t:{end}:t> (<t:{end}:R>) · 2 attacks left on 1 account · Attacks used / available'
    assert 'attacks remaining' not in text


def test_long_reminder_repeats_short_header_and_never_repeats_pings():
    w=war(); w['name']='Edrag Rush'
    w['members']=[dict(tag=f'#{i}',name=f'Player number {i}',position=i,th=18,used=0) for i in range(50)]
    owners={m['tag']:str(123456789012345600+i//3) for i,m in enumerate(w['members'])}
    pages=r.messages(w,config(),'start',owners)
    assert len(pages)>1
    assert all(r.discord_length(p['content'])<=2000 for p in pages)
    assert pages[0]['content'].startswith(f'🔔 **Edrag Rush · War started** · part 1 of {len(pages)}\n-# vs ')
    for n,page in enumerate(pages[1:],2):
        assert page['content'].startswith(f'🔔 **Edrag Rush · War started** · part {n} of {len(pages)}\n\n')
        assert '-# vs ' not in page['content']
    users=[u for p in pages for u in p['allowed_mentions']['users']]
    assert len(users)==len(set(users))==len(set(owners.values()))
    for p in pages:
        assert sorted(set(re.findall(r'<@(\d+)>',p['content'])))==sorted(p['allowed_mentions']['users'])


def test_oversized_group_continues_without_second_mention():
    w=war(); uid='505227988229554179'
    w['members']=[dict(tag=f'#{i}',name='🛡'*100,position=i,th=18,used=0) for i in range(12)]
    pages=r.messages(w,config(),'60',{m['tag']:uid for m in w['members']})
    assert len(pages)>1 and all(r.discord_length(p['content'])<=2000 for p in pages)
    assert sum(p['content'].count(f'<@{uid}>') for p in pages)==1
    assert '**Accounts continued**' in pages[-1]['content']
    assert pages[-1]['allowed_mentions']['users']==[]


def test_braces_in_clan_name_render_literally():
    w=war(); w['name']='{part} {0}'
    text=r.messages(w,config(),'60',{'#SAMPLE1':'505227988229554179'})[0]['content']
    assert text.startswith('🔔 **{part} {0} · 1 hour left**')
