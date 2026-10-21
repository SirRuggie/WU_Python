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


def messages(war, config, event, owners=None, *, test=False, tester=None):
    """Chunk by roster, keeping mentions in content and within Discord limits."""
    members = pending(war, config['audience'])
    if not members and not test:
        return []
    owners = owners or {}
    result = []
    chunks = [members[i:i+15] for i in range(0, len(members), 15)] or [[]]
    for index, chunk in enumerate(chunks):
        users = list(dict.fromkeys(str(owners[m['tag']]) for m in chunk if owners.get(m['tag'])))
        users = [uid for uid in users if re.fullmatch(r'\d{15,22}', uid)]
        if test:
            users = [tester] if tester and re.fullmatch(r'\d{15,22}', tester) else []
        title = f"{clean(war['name'])} · {'War started' if event == 'start' else 'War reminder'}"
        lines = []
        for m in chunk:
            lines.append(f"`{m['position']:02}` · TH{m['th']} · **{clean(m['name'])}** — {m['used']}/{war['limit']}")
        ends = int(war['end'].timestamp())
        description = f"vs **{clean(war['opponent'])}**\nEnds <t:{ends}:R> · <t:{ends}:t>\n\n**Attacks used**\n" + ('\n'.join(lines) or 'All attacks are complete!')
        remaining = sum(war['limit']-m['used'] for m in members)
        result.append(dict(content=('**Test reminder** · Sample players' if test else '') + (('\n' if test else '')+' '.join(f'<@{u}>' for u in users) if users else ''),
            embeds=[dict(title=title, description=description, color=0xE6A640,
                         footer=dict(text=f"{len(members)} players · {remaining} attacks remaining · Warriors United" + (f' · {index+1}/{len(chunks)}' if len(chunks)>1 else '')))],
            allowed_mentions=dict(parse=[], users=users, roles=[], replied_user=False)))
    return result


def sample(clan, event):
    now = datetime.now(timezone.utc)
    minutes = 1440 if event == 'start' else int(event)
    return dict(start=now, end=now+timedelta(minutes=minutes), name=clan['name'], tag=clan['tag'], opponent='Rival Clan', limit=2,
                members=[dict(tag='#SAMPLE1', name='Shield Bearer', position=1, th=18, used=0),
                         dict(tag='#SAMPLE2', name='Night Archer', position=7, th=17, used=1),
                         dict(tag='#SAMPLE3', name='Iron Guardian', position=12, th=16, used=0)])
