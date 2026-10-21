"""War reminder settings, selection, and standard Discord message rendering."""
from datetime import datetime, timedelta, timezone
import re
from pymongo.write_concern import WriteConcern

GUILD_ID = 644963518025826315
DEFAULTS = dict(enabled=False, channel_id='', war_started=True, minutes=[720, 480, 60], audience='remaining')


def collection(db, name='war_reminder_settings'):
    return db.bot_config.database.get_collection(name, write_concern=WriteConcern(w='majority', wtimeout=10000))


def settings(row=None):
    return {key: (row or {}).get(key, value) for key, value in DEFAULTS.items()}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Check the reminder settings.')
    if type(value['enabled']) is not bool or type(value['war_started']) is not bool:
        raise ValueError('Choose whether reminders and war-start notices are enabled.')
    if not isinstance(value['channel_id'], str) or (value['channel_id'] and not re.fullmatch(r'\d{15,22}', value['channel_id'])):
        raise ValueError('Choose a Discord channel.')
    if value['enabled'] and not value['channel_id']:
        raise ValueError('Choose a channel before enabling reminders.')
    minutes = value['minutes']
    if not isinstance(minutes, list) or len(minutes) > 1440 or any(type(n) is not int or not 1 <= n <= 1440 for n in minutes):
        raise ValueError('Use whole minutes from 1 to 1440 (24 hours).')
    if value['enabled'] and not minutes and not value['war_started']:
        raise ValueError('Add a reminder time or enable the war-start notice.')
    if value['audience'] not in ('remaining', 'zero'):
        raise ValueError('Choose players with attacks remaining or no attacks used.')
    return {**value, 'minutes': sorted(set(minutes), reverse=True)}


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def snapshot(war, clan_tag):
    if war is None or war.state != 'inWar':
        return None
    side = war.clan if war.clan.tag == clan_tag else war.opponent
    opponent = war.opponent if side is war.clan else war.clan
    if side.tag != clan_tag:
        raise ValueError('War does not contain the selected clan.')
    limit = war.attacks_per_member
    if type(limit) is not int or limit < 1:
        raise ValueError('War attack allowance is unavailable.')
    members = sorted(side.members, key=lambda m: m.map_position)
    if len(members) != war.team_size:
        raise ValueError('War roster is incomplete.')
    return dict(start=utc(war.start_time.time), end=utc(war.end_time.time), name=side.name,
                opponent=opponent.name, tag=clan_tag, limit=limit,
                members=[dict(tag=m.tag, name=m.name, position=m.map_position,
                              th=m.town_hall, used=len(m.attacks)) for m in members])


def due(war, config, now):
    """Only send within five minutes of a threshold; never replay stale reminders."""
    if not config['enabled'] or not war or not war['start'] <= now < war['end']:
        return []
    events = [('start', war['start'])] if config['war_started'] else []
    events += [(str(n), war['end'] - timedelta(minutes=n)) for n in config['minutes']]
    return [key for key, at in events if war['start'] <= at and 0 <= (now-at).total_seconds() < 300]


def pending(war, audience):
    return [m for m in war['members'] if m['used'] < war['limit'] and (audience != 'zero' or m['used'] == 0)]


def clean(value):
    return re.sub(r'([\\`*_~|<>\[\]@])', r'\\\1', str(value).replace('\n', ' '))[:100]


def duration(minutes):
    hours, minutes = divmod(minutes, 60)
    return ' '.join(text for text in (
        f"{hours} hour{'s' if hours != 1 else ''}" if hours else '',
        f"{minutes} minute{'s' if minutes != 1 else ''}" if minutes else '') if text)


def discord_length(text):
    return len(text.encode('utf-16-le')) // 2


def messages(war, config, event, owners=None, *, test=False, tester=None):
    """Group accounts under one notifying mention; split safely without repeat pings."""
    from utils.emoji import emojis
    members = pending(war, config['audience'])
    if not members and not test:
        return []
    owners = owners or {}
    groups = {}
    for member in members:
        uid = str(tester or '') if test else str(owners.get(member['tag']) or '')
        uid = uid if re.fullmatch(r'\d{15,22}', uid) else ''
        if test:
            uid = '' if member.get('sample_unlinked') else (uid or 'sample')
        groups.setdefault(uid, []).append(member)
    # Unlinked accounts remain visible, but never imply a Discord owner.
    if '' in groups:
        groups[''] = groups.pop('')
    label = 'War started' if event == 'start' else duration(int(event))+' left'
    header = f"🔔 **{clean(war['name'])} war reminder · {label}**\n"
    header += f"vs {clean(war['opponent'])} · Ends <t:{int(war['end'].timestamp())}:t>"
    if test:
        header += '\n-# Test reminder · Sample players · Simulated attacks'
    remaining = sum(war['limit']-m['used'] for m in members)
    footer = f"-# {len(members)} accounts · {remaining} attacks remaining · Attacks used / available"
    budget = 2000 - discord_length(header+'\n\n'+footer+'\n\n')
    # First split oversized owners into continuation blocks with no second mention.
    blocks = []
    for uid, accounts in groups.items():
        title = '**Sample accounts**' if uid == 'sample' else f'<@{uid}>' if uid else '**Unlinked accounts**'
        text, mentions = title, [uid] if uid and uid != 'sample' else []
        for member in accounts:
            emoji = str(getattr(emojis, f"TH{member['th']}", f"TH{member['th']}"))
            player_tag = re.sub(r'[^#A-Z0-9]', '', str(member['tag']).upper())[:24]
            line = f"> {emoji} **{clean(member['name'])}** `{player_tag}` · {member['used']}/{war['limit']}"
            if discord_length(text+'\n'+line) > budget:
                blocks.append((text, mentions))
                text, mentions = '**Accounts continued**', []
            text += '\n'+line
        blocks.append((text, mentions))
    if not blocks:
        blocks = [('All attacks are complete!', [])]
    pages, text, users = [], '', []
    for block, mentions in blocks:
        candidate = text+'\n\n'+block if text else block
        if discord_length(candidate) > budget:
            pages.append((text, users))
            text, users = block, mentions.copy()
        else:
            text, users = candidate, users+mentions
    pages.append((text, users))
    return [dict(content=header+'\n\n'+text+'\n\n'+footer,
                 allowed_mentions=dict(parse=[], users=users, roles=[], replied_user=False))
            for text, users in pages]


def sample(clan, event):
    now = datetime.now(timezone.utc)
    minutes = 1440 if event == 'start' else int(event)
    return dict(start=now, end=now+timedelta(minutes=minutes), name=clan['name'], tag=clan['tag'], opponent='Rival Clan', limit=2,
                members=[dict(tag='#SAMPLE1', name='Shield Bearer', position=1, th=18, used=0),
                         dict(tag='#SAMPLE2', name='Night Archer', position=7, th=17, used=1),
                         dict(tag='#SAMPLE3', name='Iron Guardian', position=12, th=16, used=0, sample_unlinked=True)])
